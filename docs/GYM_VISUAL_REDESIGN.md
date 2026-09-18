# Gym Training 2.0 — rediseño visual

2026-09-17 · rama `codex/gym-visual-redesign`, sobre `ef49b20`.
Esta fase cambia exclusivamente presentación, templates y QA. No añade rutas,
modelos, migraciones, contratos persistentes ni dependencias de ejecución.

## Cierre de dirección de arte — aprobación visual concedida

La composición principal ahora concentra programa activo, selector, próxima sesión
con imagen existente y CTA, ejercicios, Progreso e Importar. Se retiraron los
bloques promocionales repetidos y Coach AI ocupa una sola tarjeta discreta.
El dashboard oculta volumen desconocido, categorías sin observaciones y estimaciones
inexistentes; conserva métricas confirmadas y el cronómetro real.

Las vistas aprobadas de captura y rango se conservaron byte por byte, incluyendo
el macro de serie, markup de ejercicios y cálculo de rango. Las nuevas reglas CSS
están limitadas a `.gym-programs`, `#gym-dashboard` y la tarjeta compacta nueva.
No cambian backend, modelos, persistencia ni lógica de entrenamiento.

La última sesión de la principal muestra únicamente su fecha real por variante:
el contexto actual no entrega volumen ni duración de esa sesión. El historial
existente sigue accesible. No hay nuevas tendencias ni estadísticas simuladas.

Medios: solo los tres archivos existentes de Wikimedia Commons, sin nuevas
 descargas. Autor, fuente y CC BY-SA 3.0 están documentados en
[`ATTRIBUTION.md`](../backend/app/static/images/gym/ATTRIBUTION.md) y en el modal.
Son ilustraciones estáticas; no se presentan como videos.

Validación focal de esta revisión: 6 tests Node, 24 combinaciones (principal y
dashboard, 6 anchos y 2 temas), guardado real con fixtures QA, ocultación de métricas,
medios/fallback, foco y cronómetro. El contador avanzó 0:00 → 0:02, sobrevivió a una
recarga y se detuvo al finalizar. Un inicio inválido oculta el contador del dashboard.
La suite backend no se repitió. Capturas nuevas: principal completa de 390 px de
ancho y dashboard íntegro en viewport 390 × 844, ambas en dark mode.

Reproducción: iniciar `scripts/gym/qa_app.py` en almacenamiento QA temporal y
usar `node scripts/gym/art_direction_qa.cjs` con Playwright/Edge disponibles.
El script entrega solo dos PNG y un reporte. El usuario aprobó Mi entrenamiento,
entrenamiento en curso, captura rápida, calculadora de rango y dashboard de gym.
El cierre autoriza commit y push; merge y despliegue quedan pendientes.

## Pantallas y componentes

- Programa: hero, días con nombres libres, fecha de última sesión completada,
  objetivos, miniaturas, gestión existente e importación visible.
- Entrenamiento: KPIs confirmados, tarjetas expandibles, referencia anterior,
  objetivo y resultado separados, rango, captura de tres números y barra inferior.
- Atajos: sugerencia, repetir serie confirmada, referencia previa, incrementos,
  decrementos, limpiar campos pendientes y Enter entre inputs.
- Guardado: mismo POST con CSRF. Los controles quedan bloqueados mientras se
  guarda; un fallo conserva el borrador y permite reintentar. Solo una respuesta
  `saved` actualiza resultados. Borradores locales conservan el TTL de 24 horas.
- Descanso: contador tras confirmar, minimizar y cerrar. El tiempo transcurrido
  se calcula desde el inicio existente, sin inventar un estado persistente de pausa.
- Importación: preparar archivo/texto → preview y mapping → confirmar. Se
  conservan tokens, revisiones, acciones y servicios de importación existentes.

Los macros están en `backend/app/templates/gym/_components.html`. Estilos
aislados bajo `.gym`, tema claro/oscuro heredado y recursos versionados en sus URLs.
`gym_core.js` contiene cálculos puros; `gym_ui.js`, navegación y medios;
`gym_workout.js`, integración de la captura existente.

## Catálogo neutral de presentación

`backend/app/static/media/gym-catalog.json` es una fixture compatible de
presentación con tres ilustraciones licenciadas y alojadas localmente. No es el catálogo persistente del
usuario ni resuelve identidades para importar. Las coincidencias visuales son
exactas por nombre/alias normalizado; no se usa fuzzy matching.

Cada entrada admite `source`, `external_exercise_id`, `name`, `aliases`,
`primary_muscles`, `secondary_muscles`, `equipment`, `instructions`, `media_url`,
`thumbnail_url`, `tags`, `difficulty`, `force` y `mechanic`. Los campos plurales
son listas de texto; los demás son texto. `media_type` añade `image` (incluye GIF)
o `video`. Ninguno de esos campos se envía al servidor para registrar una serie.

Miniaturas licenciadas estáticas, lazy loading y skeleton; modal con imagen/GIF o
video con controles y sin autoplay. URL inválida, catálogo ausente, ejercicio
desconocido y medio fallido tienen fallback. Medios HTTPS externos se cargan solo
al pulsar «Cargar medio externo»; tampoco se precargan sus miniaturas. No existe
dependencia de un proveedor. Los medios son ilustraciones estáticas con atribución, no videos técnicos.

## Rango y datos reales

Se evalúan únicamente series confirmadas con reps y carga directa comparables.
Cada serie conserva su propio objetivo. Si alguna cae bajo el mínimo, el
ejercicio aparece debajo del rango. «Tope» y «Por encima» se calculan con todas
las series evaluables; el marcador representa la última evaluable.

«Candidato a progresar» requiere todas las series confirmadas y comparables,
carga positiva, reps en el máximo o superiores y un objetivo explícito de
esfuerzo cumplido (RIR real ≥ objetivo; RPE real ≤ objetivo). RIR cero es válido;
esfuerzo ausente no equivale a cero. Es una heurística informativa: no modifica
la carga ni prescribe automáticamente una subida o bajada.

Volumen = suma de carga total × reps confirmadas, en la unidad que ya entrega
el contexto. Las modalidades no comparables quedan fuera y se marca parcial.
El panel cuenta ejercicios completos, dentro, encima, debajo y candidatos;
«Foco por ejercicio» enumera los casos que revisar.

## Límites explícitos de esta fase

- Editar/quitar una serie confirmada usa el editor de registro existente después
  de finalizar. No se inventó un endpoint de edición/borrado durante la sesión.
- Notas del programa se muestran; no hay un nuevo campo persistente de notas
  rápidas por serie. Modalidades avanzadas conservan el acceso a captura avanzada.
- La mayor carga anterior se identifica como parte de esa referencia, no récord
  global. «Progreso» abre el historial real existente.
- Volumen semanal/frecuencia se consultan mediante los enlaces al resumen y
  progreso. Adherencia, mejoras semanales, estancamiento y tiempo restante no
  tienen métricas fabricadas: su integración queda señalada como pendiente.
- Coach AI es un módulo visual futuro, sin acciones automáticas.
- Sin JavaScript siguen disponibles importación, mapping, formularios nativos,
  todas las variantes, series confirmadas y cierre. Medios interactivos,
  calculadora y guardado del borrador local requieren JavaScript.

## Verificación histórica de la implementación

Datos ficticios en SQLite y almacenamiento temporal, sin usar datos personales,
`.env`, `/data`, volúmenes persistentes o producción.

| Comprobación | Resultado |
| --- | --- |
| Gym y estados vacíos/errores | 31 passed |
| Suite backend completa | 1033 passed, 16 skipped; warning conocido de fixture ZIP duplicado |
| Node, cálculos y contrato visual | 6 passed |
| Recorrido existente de Gym | 36 combinaciones; captura, Enter, recuperación, referencia, progreso, XLSX |
| Rediseño | 60 combinaciones: 5 vistas × 6 anchos × claro/oscuro |
| Anchos | 360, 390, 430, 768, 1024 y 1366; altura 844 |
| QA visual | Capturas móvil/escritorio revisadas, modal y rango confirmado revisados |
| Interacción adicional | Texto, mapping, DVO2, foco, fallo/reintento, bloqueo durante guardado, volumen/rango, timer, siguiente, reanudar, finalizar y fallback sin JS |
| Medios | Ilustración, desconocido, video externo opt-in y fallo recuperable, fixture GIF, skeleton |
| Tamaños | Sin overflow de documento; controles ≥44 px, inputs ≥16 px |
| Validación técnica | Compileall, sintaxis JS, Compose config con variables ficticias y diff check |
| Esquema | `db check` sin diferencias sobre SQLite QA creado desde metadata y estampado al único head `20260913_0040` |

El upgrade histórico completo desde cero en SQLite se detuvo en `0015`, que
crea una FK mediante ALTER TABLE; no constituye una validación de migraciones
MariaDB. Esta fase no cambia esquema ni requiere nuevas migraciones. No se
repitió QA MariaDB, ni se afirma QA en teléfono físico o conformidad WCAG completa.

Reproducción (con Playwright disponible y Edge instalado):

```powershell
$env:FLASK_SKIP_DOTENV='1'
.venv/Scripts/python.exe scripts/gym/qa_app.py
# En otra terminal, configurando NODE_PATH si Playwright es un runtime externo:
node --test scripts/gym/presentation.test.cjs
node scripts/gym/visual_qa.cjs
node scripts/gym/visual_redesign_qa.cjs
```

Los scripts imprimen el directorio temporal de capturas y `report.json`.
La publicación de la rama no incluye merge, despliegue NAS, migraciones ni tag.


## Verificación final para publicar la rama — 2026-09-17

Sin cambios de diseño después de la aprobación. El diff contiene exclusivamente
frontend (CSS, JS y Jinja), tres imágenes con su catálogo de presentación y
atribuciones, documentación y scripts de QA frontend. No modifica código Python,
modelos, persistencia, contratos, migraciones ni configuración de infraestructura.

- Tests JS focales: 6/6; sintaxis de los tres módulos JS válida.
- Responsive: 36 combinaciones del flujo existente, 60 del rediseño y 24 de
  principal/dashboard; anchos 360, 390, 430, 768, 1024 y 1366, claro y oscuro.
- Cronómetro: avanza, persiste al recargar, se detiene al finalizar y se oculta
  con fecha de inicio inválida. Dashboard sin métricas inventadas.
- Los selectores de QA se alinearon con «Iniciar entrenamiento» y con los dos
  accesos existentes a Finalizar. No cambia el comportamiento de la aplicación.
- El recorrido de dirección de arte requiere una instancia QA recién iniciada;
  los otros recorridos añaden programas y alteran su fixture inicial.
- SHA-256 de las tres imágenes distribuídas cotejados con ATTRIBUTION.md:
  originales sin modificar, Everkinetic, adaptación SVG de Urutseg en sentadillas,
  CC BY-SA 3.0, con fuente y licencia accesibles desde el modal.
- `git diff --check` y `docker compose --env-file <archivo QA temporal> config --quiet`.
  Compose usa valores ficticios, sin leer `.env` ni iniciar contenedores.
- No se repite la suite backend; sus resultados anteriores figuran únicamente
  en la sección histórica. No se integran catálogos externos ni funciones de Coach AI.

Commit autorizado: `feat: redesign gym training experience`.
La rama se publica para integración; merge y operaciones de producción requieren
una instrucción posterior.
