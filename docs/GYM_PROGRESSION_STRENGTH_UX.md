# Gym Progression + Strength Experience — dirección visual aprobada

## Estado y alcance

Prototipo navegable, exclusivamente UI/UX, en
`design/gym-progression-strength/`. Rama
`design/gym-progression-strength-experience`, creada desde master productivo
`50053882f7fbb05b90fbce8dcac5c390566232d3` sin worktree.

**Aprobación visual: PASS, 2026-10-04.** Aprobadas Home / Mi entrenamiento,
Evolución por ejercicio, Entrenamiento completado, mobile 390, desktop 1366,
dark mode, estados conceptuales, empty states y medios del catálogo.
Se conserva esta jerarquía como base de implementación; no se añaden KPIs ni
se abre otra iteración de diseño en este cierre.

Todos los registros de entrenamiento son ficticios. Se reutilizan formas de
datos y media pública local; no se leyó historial personal. No hay conexión
al backend, persistencia, llamadas API, motor de progresión, cálculos de
fuerza, standards, percentiles ni acciones AI. No se modifican plantillas
productivas, rutas, modelos, migraciones, schemas públicos ni mappings.

El prototipo estático conserva la jerarquía e interacciones aprobadas antes de
adaptar Jinja. No cambia lo que muestra Gym en producción. `e1RM` permanece
marcado como estimación, las progresiones son propuestas y los datos ficticios
siguen identificados. La aprobación visual no valida reglas ni recomendaciones.

## Abrir y revisar

Desde la raíz del repositorio:

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory design/gym-progression-strength
```

Abrir `http://127.0.0.1:8765/`. El servidor expone únicamente el directorio de
diseño. También se puede abrir `index.html` directamente: los fixtures son JS
local y no necesitan fetch.

- Home → Press banca → evolución (`#progress`). Remo tiene identidad propia.
- Iniciar D1 → fixture de sesión → Finalizar entrenamiento QA → cierre (`#summary`).
- Preparar cambio → vista previa → confirmar/descartar ejemplo; solo cambia el diálogo.
- Ver D2 cambia el día visible, sin iniciar una sesión.
- Ejercicios, Historial, programa y demostración abren vistas locales de diseño.
- Escenarios de diseño, al pie, permite reproducir estados vacíos y alternativos.
- El botón de sol alterna claro/oscuro; la preferencia no se persiste.

Una banda permanente identifica el prototipo y la ausencia de guardado. La CSP
bloquea conexiones y envíos de formularios. No hay almacenamiento local, cookies,
telemetría ni solicitudes de escritura. Los enlaces de atribución son opcionales;
ningún medio requiere GitHub en runtime.

## Jerarquía de las pantallas

### 1. Mi entrenamiento

1. Título, CTA Iniciar D1 y Ver programa.
2. Semana: sesiones, series, volumen comparable y comparación etiquetada QA.
3. Próxima sesión: programa activo, D1–D5, ejercicios/series, duración ilustrativa,
   referencias anteriores y CTA principal.
4. Progresando: tarjetas con imagen, set de referencia, cambio y estado textual.
5. Fuerza: e1RM **Estimación · QA**, separada de la carga registrada.
6. Consistencia: cuatro barras semanales con números accesibles.

Desktop usa columna principal de sesión y progreso, más fuerza/consistencia al
lado. Mobile conserva orden de lectura y CTA accesible desde el hero. Solo hay
cuatro accesos Gym: Entrenamiento, Progreso, Ejercicios, Historial.

### 2. Progreso por ejercicio

Identidad y media → top set de una serie concreta → evolución → métricas
secundarias → propuesta → rango de reps → historial. En desktop la propuesta y
el rango ocupan la columna lateral. El historial usa tarjetas, no tabla horizontal.

La única gráfica principal representa `best_load_kg` por fecha. El eje Y conserva
unidades kg; el eje X utiliza distancia temporal. Los selectores 8 semanas,
3 meses y 6 meses recortan los puntos ficticios. Hay título/descripción SVG y
alternativa textual desplegable. No calcula e1RM ni determina estados.

Los valores máximos independientes de una sesión no se combinan para inventar
un set: `best_load_kg` y `best_reps` pueden pertenecer a series distintas.
El top set y sus reps proceden de una serie explícita del fixture; el futuro
adaptador deberá usar las series del detalle de sesión.

El rango separa por debajo / dentro / tope y muestra el valor escrito. Es un
objetivo de reps, nunca un nivel de fuerza. Los estados son fixtures seleccionados,
sin nueva regla de negocio.

### 3. Cierre de entrenamiento

Finalización D1 → duración/series/volumen → cambios por ejercicio → comparación
con el mismo día anterior → candidatos para revisar → siguiente D2.
El fixture representa 29 sep frente a 21 sep, coherente con el historial de
Press banca (80 × 8 frente a 80 × 7). No hay score ni anuncio de récord.

Existe información de récords históricos en `progress_exercise_detail`, pero
este prototipo no decide si el entrenamiento recién terminado creó uno nuevo.
Esa integración necesita un criterio temporal/comparable validado posteriormente.

## 1. Datos que ya existen en Health Tracker

Referencias inspeccionadas: `backend/app/services/mobile_progress.py`,
`backend/app/gym/routes.py`, `backend/app/services/exercise_catalog.py`,
`backend/app/templates/gym/progress.html` y componentes Gym existentes.

| Elemento | Datos existentes | Límite / adaptación posterior |
| --- | --- | --- |
| Programa y D1–D5 | Programas, revisión, días, prescripciones y cards Gym | Reutilizar selección y CTA oficiales; el prototipo no inicia sesiones |
| Carga/reps/RIR de una serie | Sets del detalle de sesión | No emparejar máximos independientes ni asumir RIR faltante |
| Resumen por ejercicio | `exercise.name`, `session_count`, `set_count`, `best_load_kg`, `best_repetition_set`, `volume_kg`, `volume_partial` | Ventanas y alcance deben coincidir con la etiqueta; conservar null y volumen parcial |
| Gráfica | `points[].date`, `best_load_kg`, `load_comparable` | Null/no comparable no es cero; no conectar segmentos incompatibles |
| Historial | `recent_sessions` y detalle de las sesiones | RIR por serie requiere detalle; `average_rir` no lo sustituye |
| Tendencia actual | `trend: up/down/stable/insufficient_data` | Es comparación entre dos puntos de carga; no equivale al futuro estado de progresión |
| Media | `source`, `external_exercise_id`, `thumbnail_url`, `gallery`, `author`, `license`, `source_url`, `changes` | Resolver solo por identidad confirmada, nunca por parecido del nombre |
| Referencia anterior | Sesión previa ya asociada a la prescripción | Preservar reglas actuales de comparabilidad y modo de carga |
| Volumen | Volumen compatible y flag parcial existentes | No tratar peso corporal, asistencia o duración como kg comparables |

## 2. Cálculos determinísticos para una fase posterior

Esta lista delimita trabajo futuro; **ningún cálculo de esta sección se implementa
en esta rama**. Reutilizar los agregados existentes donde ya resuelven el caso.
Antes de exponer una métrica, definir ventana, zona horaria, unidades, denominador,
modos de carga y tratamiento de datos ausentes. No ampliar los KPIs aprobados.

| Cálculo / composición futura | Entradas existentes | Decisión pendiente para implementar |
| --- | --- | --- |
| Resumen semanal y consistencia | Sesiones completadas, fechas, sets y volumen comparable | Componer ventanas coherentes, sesiones planificadas frente a completadas y agregado semanal; no duplicar el cálculo de volumen existente |
| Comparación entre sesiones/semanas | Identidad confirmada, prescripción, revisión, sets y sesión previa | Comparar el mismo ejercicio/modo de carga; definir denominador y devolver ausencia cuando no haya base comparable |
| Top set reciente y evolución personal | Carga y reps de una misma serie, esfuerzo y puntos históricos | Elegir un criterio explícito y estable; no unir máximos de series diferentes ni modos incompatibles |
| e1RM, siempre estimación | Series elegibles con carga/reps comparables | Seleccionar y versionar fórmula, dominio válido y exclusiones antes de calcular; el número del mock no fija fórmula ni umbral |
| Evaluación de progresión | Prescripción, rango, RIR/RPE, series confirmadas e historial comparable | Definir reglas determinísticas, evidencia mínima, incrementos compatibles y estados de insuficiencia/revisión; el mock no establece esos criterios |
| Cambio de récord en una sesión | Récords históricos existentes y sesión recién completada | Validar comparabilidad y corte temporal antes de mostrar «nuevo»; no volver a implementar todo el historial de récords |

La duración prevista de una sesión sigue siendo un placeholder de diseño: no
se deriva automáticamente del número de ejercicios. Cualquier estimador futuro
necesita un criterio separado y una etiqueta de estimación.

La futura evaluación devuelve una propuesta explicable. Producir esa propuesta
no modifica programa, prescripciones, mappings ni historial; cualquier aplicación
necesita el recorrido explícito de revisión y confirmación definido abajo.
No requiere AI, strength standards externos ni percentiles.

## 3. Campos únicamente de mock / fixture

- Todos los valores de programa, entrenamiento, historia y fecha del prototipo.
- 3/5, 47 series, 18.4 t y +6.4% semanal, agregación/ventanas no conectadas.
- Cambios de carga mensuales y de reps/carga entre sesiones en las tarjetas.
- Estimación e1RM 101 kg y +4.3%, sin fórmula ni cálculo nuevo.
- Consistencia 3/2/4/3 y 12 sesiones, sin endpoint agregado nuevo.
- Duración prevista ~58 min; no se infiere del número de ejercicios.
- Estados, valores propuestos, motivos y candidatos de progresión.
- Cierre 58 min, 18/18, 12.4 t frente a 61 min, 17, 11.8 t.

La UI muestra `—` o un mensaje de ausencia cuando corresponde. Antes de llevarla
a runtime, las métricas deben tener fuente/ventana/unidades comparables o quedar
ocultas. Nunca usar fixtures como fallback de datos personales.

## 4. Contratos visuales del futuro Progression Engine

Este es un contrato de presentación propuesto, **no un JSON Schema público nuevo**.
No fija endpoints ni implementa un motor. El servidor deberá producir y validar
las propuestas; la UI presenta evidencia y pide confirmación explícita.

| Estado | Presentación | Acción de diseño |
| --- | --- | --- |
| `increase_load` | ↗ Progresando, carga actual → propuesta | Preparar cambio |
| `increase_reps` | ＋ Buscando más reps, reps actual → propuesta, misma carga | Preparar objetivo |
| `maintain` | ＝ Mantener, valor actual conservado | Revisar propuesta |
| `review` | ! Revisar, identidad/contexto incompleto | Revisar ejercicio / vínculo |
| `insufficient_data` | ◷ Construyendo historial, sin tendencia | Sin CTA para aplicar |

La propuesta futura necesita identidad owner-scoped, prescripción y revisión,
estado, valores actual/propuesto con unidad y modo de carga, evidencias con
sesiones/series, motivo, identificador/versión de regla y estado de confianza o
evidencia insuficiente. Las revisiones permitirán detectar propuestas obsoletas.
No se requiere un porcentaje de confianza inventado.

Recorrido visual: propuesta → preview (alcance + evidencia + regla) → confirmar
o rechazar. En este diseño ambos son simulaciones; no existe write. En una fase
posterior la confirmación deberá pasar por el servicio oficial, ownership,
validación, CSRF/concurrencia/idempotencia existentes según la operación elegida.
No diseñar un endpoint que confíe en `user_id` enviado por el cliente.

La tarjeta de 80 → 82.5 kg es deliberadamente conceptual: la evidencia 8/7/7
**no demuestra** un criterio de tres series al tope. Se explica que la regla no
está evaluada. El escenario «Tope del rango» cambia la evidencia a 8/8/8 como
otro fixture, sin calcular ni aprobar progresión.

## Estados vacíos y media

| Escenario QA | Comportamiento |
| --- | --- |
| Sin historial | Top set y métricas ausentes, sin tendencia/propuesta; invita a registrar |
| Solo una sesión | Mantiene la sesión, no dibuja tendencia con un punto |
| Sin mapping | Nombre de rutina conservado, media neutral, revisión explícita; no une historias |
| Sin imagen | Fallback textual; carga, identidad e historial permanecen |
| Programa nuevo | Cero sesiones, comparación ausente, inicio disponible |
| Sin progresiones | Rutina vigente como referencia, ninguna aplicación automática |
| Mantener / debajo / tope | Texto + símbolo + rango, sin lenguaje de juicio |

Se reutilizan seis archivos de Free Exercise DB ya presentes en el snapshot
local `f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5`, con licencia y manifiesto
SHA-256 en `design/gym-progression-strength/assets/`. No hubo descargas.
La demo muestra dos posiciones de banca. Identidades exactas y variantes
documentadas en `assets/ATTRIBUTION.md`; las etiquetas de rutina no son aliases
personales. Fallback tanto por ausencia explícita como por fallo de carga.

## Accesibilidad y responsive

`lang=es`, viewport, skip link, main enfocable, navegación nombrada, aria-current,
labels, selector nativo, botones con estado pulsado, foco visible, `dialog` nativo
con Escape/retorno de foco, anuncios de cambios y texto alternativo. Todos los
estados tienen texto/símbolo además del color. No hay animaciones necesarias.
Inputs/select de 16 px; controles principales de al menos 44 px. Los enlaces
de atribución son texto inline. No se oculta overflow global para encubrir errores.

Se verifican 360, 390×844, 430, 768, 1024 y 1366, oscuro y revisión clara,
interacción por teclado y contraste de tokens. La verificación no constituye
una certificación WCAG ni una prueba con todos los lectores de pantalla.

## Cierre visual aprobado (histórico)

Gate visual aprobado. Este cierre autoriza el commit
`design: define gym progression and strength experience` y el push de
`design/gym-progression-strength-experience`.

**Listo para implementación: sí, como dirección visual y contrato de presentación.**
Conectar datos reales y definir/implementar el motor corresponde a una fase
posterior con alcance propio. Esta rama no implementa backend, migraciones,
Progression Engine, AI Coach ni strength standards externos. Sin merge, NAS,
tag o nueva versión en este cierre.

Los resultados de validación y las capturas se registran en
`design/gym-progression-strength/qa/`. Las capturas del 2026-10-03 documentan
la dirección aprobada; la revalidación de cierre del 2026-10-04 no altera el diseño.

## Implementación real — PR #10

La dirección visual anterior se conserva como referencia histórica. En
`feature/gym-progression-strength` las páginas Flask consumen read models reales;
no cargan el JS, controles de escenario ni fixtures del prototipo.

| Categoría | Fuente y comportamiento en runtime |
| --- | --- |
| Datos existentes | Programas/revisiones, prescripciones, sesiones completadas, series confirmadas, carga/modo/unidad, reps/RIR/RPE, identidad y catálogo local del propietario. |
| Cálculos determinísticos implementados | Semana local, volumen oficial y flag parcial, comparación con cobertura compatible, consistencia de cuatro semanas, top set de una serie real, e1RM Epley v1 y doble progresión conservadora. |
| Campos solo mock | Nombres y cifras de demostración, score/confianza inventada, escenarios conmutables y etiquetas QA del prototipo permanecen únicamente en `design/` y fixtures de pruebas. No se insertan en templates productivos. |
| Contratos del motor | `ProgressionEvaluation` contiene estado, prescripción/revisión, propuesta, evidencia y regla versionada. Home, detalle y resumen consumen el mismo motor. El read `training.progression` queda neutral para integración futura, sin acciones ni proveedores AI. |

Home conserva cabecera y semana, seguida por el programa/día y CTA de la próxima
sesión como contenido principal; las tarjetas de progresión vienen después. En
desktop fuerza y consistencia ocupan la columna lateral. No se añaden KPIs.

Solo `increase_load` con cambios concretos habilita «Preparar cambio». Las
propuestas conceptuales de reps, mantener o revisar no publican revisiones.
Preview enseña actual/propuesto, evidencia y regla. Confirmar crea una revisión
inmutable mediante el servicio oficial, con CSRF, ownership, expiración,
revalidación, transacción e idempotencia. Las sesiones anteriores conservan su
versión y sus resultados. La UI siempre etiqueta `e1RM · estimación`.

Los medios, instrucciones y atribución provienen del catálogo local existente.
Sin identidad o sin imagen se mantiene un fallback honesto. Una sola sesión no
produce una tendencia, los huecos no se convierten en cero y los cambios de modo
interrumpen la línea. El resumen se abre al finalizar, muestra resultados reales
y propuestas sin aplicar. No añade récords, estándares externos ni AI Coach.

Las capturas de implementación y los resultados del gate se distinguen de las
del prototipo en [GYM_PROGRESSION_QA.md](GYM_PROGRESSION_QA.md). El zoom real al
200% requiere evidencia separada; reducir el viewport no lo sustituye.
