# Modos de carga de entrenamiento

Alpha 0.9 registra la carga realmente usada con un modo explícito. Ningún modo infiere componentes ausentes.

| Modo | Componentes | Total normalizado |
| --- | --- | --- |
| `direct_total` | `direct_total` | carga indicada |
| `per_side` | `per_side` | dos lados |
| `bar_plus_per_side` | `bar`, `per_side` | barra + dos lados |
| `machine_initial_total` | `initial_total`, `added_total` | inicial + añadido |
| `machine_initial_per_side` | `initial_per_side`, `external_per_side` | dos lados de ambos componentes |
| `machine_external_per_side_initial_total` | `initial_total`, `external_per_side` | inicial total + dos lados externos |
| `selector_stack` | `selector_stack` | valor de la pila |
| `dumbbell_each` | `dumbbell_each` | dos mancuernas |
| `bodyweight` | `bodyweight` | peso corporal explícito |
| `bodyweight_plus` | `bodyweight`, `added_total` | cuerpo + carga |
| `assistance` | `bodyweight`, `assistance` | cuerpo − asistencia |
| `duration_distance` | `duration_seconds`, `distance_meters` | `weight_kg = 0`; conserva tiempo/distancia |

Los componentes de peso aceptan `kg` o `lb` individualmente. Duración usa segundos y distancia metros. Los valores negativos, unidades incompatibles, componentes extra y modos desconocidos se rechazan.

Ver [WORKOUT_LOAD_CALCULATIONS.md](WORKOUT_LOAD_CALCULATIONS.md) para precisión y [WORKOUT_LOAD_ENTRY.md](WORKOUT_LOAD_ENTRY.md) para el flujo web.
