# Cálculos de carga de entrenamiento

El backend es autoritativo y calcula con `Decimal`. La conversión exacta es:

```text
1 lb = 0.45359237 kg
```

Cada componente se convierte una sola vez a kg; después se aplica la fórmula del modo. `weight_kg` conserva el total redondeado compatible con el modelo, mientras `load_details.normalized_total_kg` y `calculated_total_lb` conservan la representación de cálculo.

## Contrato `load_details` 1.0

Campos canónicos:

- `schema_version` y `calculation_version`;
- `load_mode`;
- `original_input`, `original_unit` y `components`;
- `normalized_total_kg` y `calculated_total_lb`;
- `display_total`;
- `bodyweight_kg` y `assistance` cuando aplican;
- `warnings` solo cuando existe una condición semántica conocida.

Cada componente tiene `{ "value": "...", "unit": "kg|lb|s|m" }`. El navegador calcula solo un preview; el backend recalcula, valida el schema y comprueba que `weight_kg` sea consistente. Una discrepancia, valor no finito o campo inventado invalida la operación.

Las sesiones históricas sin `load_details` siguen siendo válidas y no se reescriben. La regla canónica está en [project-rules/workout-load-entry.md](project-rules/workout-load-entry.md).
