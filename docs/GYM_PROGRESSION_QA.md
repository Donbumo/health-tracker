# Gym Progression — gate de revisión del PR #10

Rama: `feature/gym-progression-strength`. Base: `50053882f7fbb05b90fbce8dcac5c390566232d3`.
Incluye el diseño aprobado `f021727` y la implementación `7658f0a`, más el cierre
de continuidad, seguridad y jerarquía visual. No merge, NAS, tag ni versión nueva.

## Entorno y alcance

Flask real y MariaDB 11.4 efímera, aislada del stack ordinario; solo usuarios
ficticios `strength-qa` y `strength-final-qa`. El programa QA tiene D1/D2/D3,
banca 75→77.5→80→80, remo 8/7/7, esfuerzo incompatible, historial insuficiente
y un ejercicio sin identidad. Los medios son copias de assets públicos ya
presentes en el diseño, sin descargas. Ningún mapping personal se modifica.

## Gates funcionales

| Gate | Evidencia |
| --- | --- |
| `increase_load` | Dos sesiones distintas, consecutivas, completas a 80 kg y 8/8/8 → propuesta de 82.5 kg. |
| `increase_reps` | 8/7/7 con rango 6–8; propuesta conceptual, sin escritura. |
| `maintain` | RIR/RPE que contradice el objetivo, o pareja sin cumplir incremento. |
| `review` | Identidad unresolved, cambio de unidad/modo, duplicación, tres sesiones bajo rango o regresión persistente. |
| `insufficient_data` | Menos de dos sesiones, series incompletas y modalidades no soportadas. |
| Continuidad | Omitir completamente el ejercicio en una sesión rompe la pareja; no une éxitos antiguos. |
| RIR/RPE | Ausencia explícita, sin inferencia; esfuerzo mayor al objetivo bloquea aumento. |
| e1RM | `E1RM_EPLEY_V1`, Decimal, carga positiva comparable, reps 1–10, misma serie; exclusión de asistencia, duración, bodyweight y desconocidos. |
| Top set | 100×1 y 80×10 no se convierten en 100×10; carga y reps conservan la misma fila. |
| Preview/confirm | CSRF, token owner-bound, TTL, firma, regla/evidencia/revisión revalidadas, publicación oficial. |
| Historial | La revisión 1 y las sesiones a 80 kg permanecen inmutables; nueva sesión usa revisión 2 y objetivo 82.5 kg. |
| Idempotencia | Segundo confirm exacto no publica otra versión; concurrencia y rollback probados en MariaDB. |
| Resumen | Finalizar 15 series abre automáticamente summary con duración, volumen y cambios reales; candidatos del mismo motor. |
| Comparación | Cobertura compatible compara valores reales. Ejercicios añadidos/omitidos/unresolved o modos incompatibles dan ausencia, nunca cero inventado. |
| Home | Cabecera con acceso principal a siguiente sesión, semana, programa/día protagonista, progresiones y lateral de fuerza/consistencia. |
| AI/Operator | `/ai` y reads existentes conservados. `training.progression` es read neutral; sin proveedor, llamadas AI ni writes. |
| Privacidad | Read models owner-only y `private, no-store`; sin fixtures de diseño en templates/runtime. |

El E2E se repitió en navegador con una segunda cuenta ficticia:
Home → evolución → preview 80/82.5 → confirmar → revisión 2 → iniciar →
objetivo 82.5 visible → 15 series guardadas → finalizar → summary.
Los tests verifican además rechazo de token adulterado/expirado/obsoleto,
rollback, comparación válida, primera sesión, volumen parcial y ausencia de candidatos.

## Rendimiento: baseline local, sin microoptimización

Una solicitud por caso, incluyendo render de Jinja y autenticación. Los tiempos
no son un benchmark de producción. Las consultas adicionales del historial
amplio corresponden a los lotes `selectinload`, no a consultas por card/set/media.

| Ejercicios | Sesiones | Home queries / ms | Detalle queries / ms | Summary queries / ms |
| ---: | ---: | ---: | ---: | ---: |
| 5 | 4 | 17 / 83.3 | 10 / 28.4 | 10 / 23.2 |
| 40 | 4 | 17 / 44.8 | 10 / 98.8 | 10 / 36.0 |
| 5 | 10 | 17 / 28.0 | 10 / 17.4 | 10 / 17.0 |
| 5 | 200 | 18 / 184.3 | 11 / 186.7 | 11 / 116.2 |
| 40 | 200 | 32 / 1735.2 | 25 / 1585.3 | 25 / 1966.6 |

## Validación reproducible

- Focales SQLite: `test_gym_progression.py`, `test_gym_strength_contracts.py`,
  `test_gym_training.py` — 75 PASS antes de fijar HEAD.
- MariaDB: `test_gym_strength_mariadb.py`, habilitado exclusivamente con
  `STRENGTH_QA_MARIADB` apuntando a la base QA validada. Tres pruebas por cada
  aislamiento READ COMMITTED / REPEATABLE READ: concurrencia, stale snapshot, rollback.
- Alembic conserva `20260928_0043`; no hay diff en migraciones.
- Android afectado: 22 PASS (LoadCalculator, MobileProgressContract,
  PlanningRules, PlanningEditorState, SyncTriggerPolicy). Android no cambia.
- JS: presentación, media, autosave de imports y tooltip de fuerza.
- `compileall`, `docker compose config --quiet`, `git diff --check`.
- La full suite antigua de 1125 PASS **no certifica este cierre**. El resultado
  de la única full suite del HEAD final, SHA exacto, skips y warnings se publica
  en la descripción actualizada del PR #10, sin reejecución si el código no cambia.

## Evidencia visual y aprobación

Las capturas de Flask/QA se guardan en `docs/qa/gym-progression-runtime/`;
son distintas de las capturas históricas de `design/`. Los nombres QA visibles
pertenecen a la cuenta ficticia y no están escritos en las plantillas.

| Pantalla | Viewport 390×844 | Viewport 1366×900 |
| --- | --- | --- |
| Home | [Mobile](qa/gym-progression-runtime/home-390.png) | [Desktop](qa/gym-progression-runtime/home-1366.png) |
| Evolución | [Mobile](qa/gym-progression-runtime/exercise-390.png) | [Desktop](qa/gym-progression-runtime/exercise-1366.png) |
| Post Workout | [Mobile](qa/gym-progression-runtime/summary-390.png) | [Desktop](qa/gym-progression-runtime/summary-1366.png) |

[Detalle de gráfica móvil](qa/gym-progression-runtime/exercise-chart-390.png).
[Mediciones de los 18 casos](qa/gym-progression-runtime/responsive.json).
Se validó `innerWidth`, altura y escala antes de capturar. El PNG del navegador
excluye parte del chrome/scrollbars; las dimensiones CSS del viewport constan
en el JSON. Las capturas descartadas por escala incorrecta no forman parte del PR.

Responsive: Home, evolución y summary a 360, 390×844, 430, 768, 1024 y 1366.
La gráfica ofrece botones de 44 px, tooltip por foco/click y alternativa textual.
La evidencia y los estados se expresan con texto; los tokens de tema y reduced
motion reutilizan el contrato web existente. La comparación visual mantiene
la dirección aprobada, adaptada al shell y navegación de Health Tracker.

Zoom 200%: no certificado; no bloquea esta entrega.
El navegador automatizado no expone control fiable de zoom; un viewport reducido
no constituye esa prueba. La clasificación no implica que haya pasado el gate.
Los demás gates del PR #10 quedaron aprobados y se autorizó Squash and merge.
