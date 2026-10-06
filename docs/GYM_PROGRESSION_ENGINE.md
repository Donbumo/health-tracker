# Gym progression: implementación y contratos

## Auditoría previa (2026-10-04)

| Dominio existente | Reutilización / límite |
| --- | --- |
| `mobile_progress.py` | `_set_volume`, `_session_volume`, modos comparables y carga normalizada. Su comparación sustituye ausencias por cero: no sirve para la nueva comparación semanal. |
| `gym_sessions.py` | Captura y finalización oficiales; las sesiones completadas pueden ser parciales. La sugerencia previa no prueba cumplimiento del programa. |
| `training_plans.py`, `gym_programs.py` | `TrainingPlanVersion` es la revisión inmutable; `publish_program_document` valida el schema, publica y actualiza la proyección móvil. El caller controla commit/rollback. |
| `Exercise`, aliases y catálogo | Identidad explícita o alias exacto confirmado por el usuario. Sin equivalencia por semejanza. Los medios y atribución siguen en el catálogo local. |
| `ExerciseLoadProfile`, `workout_loads.py` | Unidades y conversiones Decimal oficiales; incrementos configurados. Un stack desconocido no permite inventar la siguiente carga. |
| Dashboard y `exercise_progress.py` | Se conservan sus contratos. El Dashboard tiene semántica de volumen diferente; no se modifica ni se replica en Resumen. |
| AI reads y Operator training actions | Los reads actuales permanecen; las correcciones ya usan revisión y bloqueo de sesión. El nuevo read es neutral y no registra acciones AI. |
| Schema training_plan | No tiene incrementos ni distinción warmup/working. Se consideran de trabajo todas las series prescritas; esquemas heterogéneos requieren revisión. |

La implementación no requiere tablas ni migración. Los resultados son derivados; la única escritura es una nueva revisión confirmada del programa. Los contratos públicos JSON permanecen intactos.

## Contratos implementados

`GymStrengthOverview`, `ExerciseStrengthDetail`, `WorkoutCompletionSummary` y `ProgressionEvaluation` son proyecciones owner-only en `gym_strength.py`. `GymProgressionEngine` es puro y comparte estado/evidencia entre Home, evolución y resumen. `training.progression` expone solo el read neutral; no se registra proveedor ni acción de IA.

## Fórmula y comparabilidad

`E1RM_EPLEY_V1` calcula `load × (1 + reps / 30)` usando una sola serie. Solo acepta carga externa comparable positiva, 1–10 repeticiones, y excluye asistencia, peso corporal, duración y modos desconocidos. El valor siempre se presenta como `e1RM · estimación`; no es un PR ni un máximo medido. La mejor carga y el top set también pertenecen a una sola serie: nunca se mezclan carga y repeticiones de filas distintas.

El volumen llama a `_set_volume`/`_session_volume` de `mobile_progress.py`. Se conserva la unidad normalizada y el indicador parcial. La semana empieza el lunes en el timezone del usuario. La comparación semanal requiere volumen no parcial, base distinta de cero y la misma cobertura de identidades/modos en ambos periodos; compara la semana actual acumulada con la anterior, no exige que el calendario semanal haya terminado. Si no existe esa cobertura, se muestra `—`. Las gráficas tienen un punto por sesión, cortan la línea cuando hay carga ausente o cambia el modo, y mantienen una alternativa textual.

## Reglas versionadas

La regla actual es `double_progression_v1`:

- `insufficient_data`: menos de dos sesiones completas compatibles, prescripción ausente o modo no soportado.
- `increase_reps`: la última sesión completa está en el rango pero no alcanza el máximo en todas las series.
- `increase_load`: dos sesiones consecutivas completas alcanzan el máximo, sin contradicción de RIR/RPE. Un RIR faltante queda explícito como `RIR no disponible` y nunca se inventa.
- `maintain`: evidencia válida sin criterio de aumento o esfuerzo que contradice el objetivo.
- `review`: identidad no resuelta, prescripción incompatible, cambio de unidad/modo, datos contradictorios, tres sesiones por debajo del mínimo o regresión persistente. No existe deload automático.

Una sesión completada que omite un ejercicio prescrito conserva un hueco de evidencia: no une dos éxitos antiguos. Una pareja con el mismo ID de sesión tampoco puede justificar un aumento. Las sesiones abiertas o abandonadas no cuentan como sesiones completadas. La regla no reinterpreta una serie faltante como cero ni infiere RIR/RPE.

La siguiente carga usa el incremento explícito del perfil cuando coincide con modo/unidad; si no, `+2.5 kg` o `+5 lb` solo para `direct_total` convencional. Una máquina sin incremento representable conserva estado `increase_load` y muestra `Revisar siguiente carga disponible`, sin inventar un stack.

## Propuesta y confirmación

El preview firma con `URLSafeTimedSerializer` el usuario efectivo, programa, revisión y versión, prescripción, cambios permitidos, regla, hash de evidencia y hash del documento resultante. El token dura 30 minutos. La confirmación vuelve a bloquear usuario/programa, reevalúa el historial, comprueba revisión activa, identidad y propuesta, y llama únicamente a `publish_program_document`. Se crea una `TrainingPlanVersion` nueva; sesiones históricas siguen referenciando su revisión original. Un replay exacto devuelve idempotencia. Una revisión obsoleta responde 409 con `La rutina cambió. Revisa de nuevo la propuesta.`. CSRF y transacción son responsabilidad de la ruta oficial; el caller hace commit o rollback.

## Resumen posterior

`WorkoutCompletionSummary` compara preferentemente el mismo día del programa y solo muestra duración, series y volumen anterior cuando la cobertura es compatible. Por ejercicio informa cambios concretos o ausencia de comparación, y lista candidatos del mismo motor sin escribir cambios. El PR solo aparecería cuando la evidencia exacta de la sesión lo demostrara; no se añade una lógica de récord nueva.

## Rendimiento, privacidad y límites

`StrengthReader` realiza lecturas owner-scoped en lotes (`selectinload`) de identidades, revisiones y sesiones; no consulta una fila por tarjeta, set o medio. El número de consultas crece con los lotes de historial, no con las tarjetas renderizadas. La confirmación obtiene un snapshot privado con locking reads de padres e hijos, probado con READ COMMITTED y REPEATABLE READ. Las páginas Gym responden `private, no-store`; solo los assets locales del catálogo conservan su cache existente. No se descargan medios ni se tocan volúmenes persistentes. El esquema actual no distingue warm-up de working set, por lo que en esta versión todas las series prescritas son series de trabajo; prescripciones heterogéneas pasan a revisión.

El reader carga el historial del propietario para mantener continuidad y comparabilidad; con 40 ejercicios y 200 sesiones la baseline QA es 1.6–2 s. Una futura paginación deberá preservar los huecos de evidencia. No hay microoptimización ni truncamiento arbitrario en este gate. El detalle presenta las diez sesiones recientes y la gráfica del periodo seleccionado. El resumen de una sesión antigua muestra candidatos **actuales**, identificados así en la UI, no reconstruye una evaluación histórica persistida.

Evidencia reproducible: `backend/tests/test_gym_strength_contracts.py`, `backend/tests/test_gym_strength_mariadb.py` y `scripts/gym/strength_qa_app.py`. Este último está restringido a una MariaDB efímera en loopback y storage temporal explícito. El informe del gate final y sus capturas se encuentran en [GYM_PROGRESSION_QA.md](GYM_PROGRESSION_QA.md).

No se creó migración: las métricas son derivadas y las propuestas se convierten en revisiones existentes. No hay estándares externos, percentiles, AI Coach, fuerza poblacional ni deload automático.
