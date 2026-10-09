# Gym Training 2.0

## Auditoría antes de implementación

Base: `origin/master` fe82b2f. Se reutilizan TrainingPlan (programa),
TrainingPlanVersion (snapshot inmutable), TrainingPlanWorkout (proyección editable
de días), TrainingSession, TrainingSessionExercise y TrainingSet. No se crea otro
sistema de entrenamiento. Las prescriptions ya están en el JSON Schema público
training_plan: sets, reps/rango, carga/unidad, RIR/RPE, descanso y notas opcionales.
Tempo y warmup no tienen un contrato vigente y no se inventan.

Los snapshots agrupan posiciones en bloques de siete por compatibilidad; no son
días de semana. La identidad histórica de un día es versión + week_number +
day_number. Cambiar el orden produce una versión nueva, nunca cambia sesiones.
TrainingPlanWorkout es mutable y sus IDs pueden renovarse; no debe ser el vínculo
histórico de una sesión. Las sesiones legacy ya enlazan snapshots: se conservan
exactamente, sin backfill inventado.

Exercise/ExerciseAlias ya aíslan nombres y mappings por usuario. El progreso
resuelve aliases sobre nombres históricos. workout_loads usa Decimal, conversión
exacta lb/kg y load_details; weight_kg sigue siendo carga total normalizada.
User ya conserva unidad y timezone. El dashboard y mobile_progress precargan
ejercicios/sets, pero asumían que todas las sesiones eran realizadas.

La captura web anterior confirma la sesión completa; tiene drafts y UUID de
idempotencia. Se conserva para edición avanzada/compatibilidad. El nuevo flujo
confirma cada serie en las mismas tablas y reanuda la sesión persistida. No se
crean TrainingSet para sugerencias. Los servicios de importación oficiales,
exportación JSON, restore de cuenta y portabilidad conservan el mismo dominio.
La eliminación de cuenta usa cascadas user_id; los nuevos campos no añaden
archivos o registros sin ownership.

AI training summary/history usa los read models existentes. Solo se amplían
contratos de lectura y se excluyen sesiones aún abiertas de métricas realizadas;
no se cambian providers, modelos, timeouts ni se habilita AI Coach.

## Arquitectura implementada

| Concepto | Modelo/contrato existente reutilizado |
| --- | --- |
| Program | TrainingPlan; `gym_active` expresa la selección del usuario |
| Revision | TrainingPlanVersion, contenido JSON y SHA256 inmutables |
| Day | Día del snapshot identificado por versión/semana/posición; nombre libre |
| Prescription | `training_plan.schema.json`: ejercicios ordenados y objetivos por serie |
| Session | TrainingSession con estado in_progress/completed/abandoned |
| ExercisePerformance | TrainingSessionExercise, creado al confirmar la primera serie |
| SetPerformance | TrainingSet; solo datos que el usuario confirmó |

`gym_programs` publica documentos canónicos validados usando el mismo dominio,
versiones y proyección de `training_plans`/`mobile_planning`. Publica también el
cambio de planificación para sync. Un contenido nuevo crea una versión; un retry
idéntico se omite. Volver a un contenido histórico idéntico reactiva su snapshot
existente, respetando la unicidad previa de SHA por plan. El número de revisión
optimista del plan sigue avanzando. Editar/reordenar nunca reescribe sesiones.

La migración `20260913_0040` añade gym_active, status y un índice user/status.
Las sesiones previas conservan sus enlaces y reciben completed por defecto.
No se inventan fechas, cargas, identidades ni enlaces para historia legacy.
Downgrade elimina los nuevos campos; hacerlo tras usar la funcionalidad pierde
la distinción de estados. Probarlo únicamente sobre datos de QA aislados.

## Asistente e import contract

`RoutineParser.parse(bytes, filename, name) -> RoutineImportDraft` es la interfaz
compartida para un parser futuro. Hoy solo existe DeterministicParser. El draft
tipado contiene program, days ordenados, exercises, sets canónicos, warnings,
unresolved, source_sha256 y referencia temporal opcional al original.
No es un nuevo schema público ni un contrato de performance.

Flujo: archivo/texto/manual/preset → draft → resolución → documento estándar →
validación → preview firmado → confirmación → servicio oficial de programas.
El token expira y vincula usuario efectivo, contenido, plan destino y revisión.
Corregir datos o mappings exige un preview nuevo. El servidor vuelve a validar.
El parser, la resolución y el preview no crean planes, ejercicios ni sesiones.
Los archivos quedan en cuarentena privada temporal por usuario; confirmar los
promueve mediante el storage oficial y registra ImportRun con SHA y resumen.
La promoción del original es separada de la transacción de dominio: un error
posterior puede conservar el archivo privado, pero no un programa parcial.

| Entrada | Soporte |
| --- | --- |
| CSV/TXT | UTF-8, encabezados, coma/punto y coma/tab/pipe; no prosa libre |
| XLSX | Una hoja con columna Día; ZIP/XML como datos, sin ejecución |
| JSON | Filas, draft con días o documento canónico training_plan |
| PDF/foto | Sin soporte; parser futuro debe producir el mismo draft |

Aliases de columnas en inglés/español están allowlisted en routine_draft.py.
Ejemplos: Día/Day, Ejercicio/Exercise, Series/Sets, Reps, Min Reps, Max Reps,
Carga/Load/Peso/Weight, Unit, RIR, RPE, Rest, Notes/Notas. Se reconocen 3x8,
6-8, 80kg y RIR/RPE; una carga sin unidad inequívoca se rechaza para corregirla.
Filas vacías generan warnings; filas inválidas bloquean sin omisión silenciosa.
Límites: 2 MB, 1000 filas, 24 columnas, 28 días, 100 ejercicios/día y 30
series/ejercicio. XLSX limita además 100 entradas ZIP y 20 MB descomprimidos;
rechaza macros, fórmulas, enlaces externos, entidades XML y hojas adicionales.

La resolución usa catálogo propio, aliases normalizados y mappings confirmados.
Dos equivalencias bilingües explícitas ayudan si ya existe la identidad destino.
No hay fuzzy match automático. Un desconocido requiere elegir una identidad o
crear uno nuevo. El mapping se conserva como alias del usuario en la misma
transacción. IDs de otra cuenta producen 404. Los IDs externos de JSON no
conceden ownership; se resuelven de nuevo. La edición de snapshots restaurados
resuelve nombres locales sin alterar la copia histórica.

Full Body v1, Upper/Lower v1 y PPL v1 son templates estructurales en código,
editables y copiados por usuario; no prescripciones clínicas ni filas globales.
La pantalla distingue crear de actualizar; reimportar el mismo contenido no
duplica silenciosamente. Archivar o cambiar el programa activo conserva historia.

## Captura, recuperación e historial

`/training-plans` es Mi programa. El inicio usa POST/CSRF y UUID idempotente,
con bloqueo de usuario para resolver double tap concurrente. Solo entonces
crea una sesión in_progress asociada al snapshot/día. No crea series ficticias.

La referencia prioriza la última aparición comparable en el mismo programa,
después la historia global por catálogo/alias, excluyendo sesión actual y datos
posteriores. Incluye series realmente confirmadas de sesiones incompletas.
La consulta precarga relaciones, tiene tope de 2000 apariciones y no consulta
por cada serie; la prueba de contexto comprueba como máximo ocho consultas.
Los objetivos/sugerencias se muestran separados de los valores actuales.
Carga sugerida: anterior comparable → objetivo convertido → vacío.
Reps: objetivo exacto → anterior → extremo inferior del rango. Esfuerzo: objetivo.

Captura rápida: carga total, reps y RIR o RPE; copiar anterior, repetir, incrementos
kg/lb y Enter/Next. La confirmación hace POST JSON con CSRF (o POST normal como
fallback). El servidor bloquea la sesión, valida schema/carga Decimal y persiste
una sola serie. Un retry idéntico devuelve éxito; cambiar una ya guardada exige
revisión mediante el editor avanzado accesible desde el resumen.

Cada serie confirmada queda inmediatamente en servidor. Los campos en edición
se conservan opcionalmente en localStorage por UUID de sesión/posición, con TTL
de 24 horas al recuperar; nunca se guardan tokens o CSRF allí. El guardado borra
su borrador local. Sin storage, las series confirmadas siguen siendo recuperables.
El timer de descanso es local y no bloquea. No se finaliza mientras hay saves
pendientes. Finalizar exige al menos una serie; cerrar incompleto admite cero.

El resumen incluye duración, ejercicios/series, volumen comparable y referencia
anterior. El progreso reutiliza mobile_progress: cargas comparables, mejor serie
por reps, volumen, tendencias y RIR/RPE promedio, sin abrir cada sesión. Los
máximos de carga y reps se etiquetan por separado, pues pueden ser series distintas.
La gráfica/read model conserva su unidad normalizada kg; captura y sugerencias
respetan preferencia kg/lb. Las fechas de Mi programa usan timezone del usuario;
el progreso conserva las fechas del read model existente.

La captura rápida confirma total explícito para cargas externas. Bodyweight,
bodyweight_plus, assistance y duration_distance siguen usando captura avanzada
para conservar componentes; las referencias rápidas no mezclan esas modalidades.
No se habilita un cálculo nuevo de PR. Las sesiones abiertas no cuentan como
entrenamiento completado en dashboard, adherencia, AI summary o mobile progress.
El historial web también muestra sesiones cerradas incompletas.

## Compatibilidad y AI futura

Export JSON, import estándar, restore y portabilidad conservan el estado y las
fechas. El restore usa client_submission_id si existe para no unir dos sesiones
del mismo segundo. CSV incluye objetivos de carga/esfuerzo y escapa texto con
prefijos de fórmula; JSON sigue siendo el formato de round-trip íntegro.
La selección explícita del programa activo se refleja en active_routine API,
con fallback legacy a la versión activa del plan más reciente.

Lecturas neutrales: training.program, training.program_day, training.session y
training.exercise_progress. Los nuevos adaptadores respetan ownership y los
contratos de summary/history siguen disponibles. No dependen de provider/model.
`FUTURE_ACTIONS` reserva program.adjust, exercise.replace, prescription.update y
load.propose, con IDs y base_revision; ninguna está registrada como escritura.
El futuro Coach deberá producir draft → preview → confirmación con el servicio
oficial y las mismas comprobaciones de revisión, nunca cambios silenciosos.

## QA reproducible

Fixtures sintéticas equivalentes en `backend/tests/fixtures/gym_qa/`.
Pruebas de dominio: test_gym_training.py. Concurrencia MariaDB:
test_gym_mariadb.py, habilitada solo con GYM_QA_MARIADB apuntando al schema QA
exacto que el test comprueba. Nunca dirigirla a una base con datos del usuario.

`scripts/gym/qa_app.py` crea SQLite/storage temporal y usuario ficticio local;
`scripts/gym/visual_qa.cjs` usa Playwright/Edge contra localhost:8011, genera
capturas/report.json y recorre importación, captura, recuperación y progreso.
La comprobación visual automatizada cubre 360/390/430/768/1024/1366 × 844,
sin overflow, inputs de 16 px y targets de 44 px. No sustituye una prueba física
de teclado táctil/iOS. Ver resultados y los 40 puntos de entrega en
[GYM_TRAINING_2_QA.md](GYM_TRAINING_2_QA.md).
