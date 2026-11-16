# Vectores ficticios de HTNX 1.0

Todos los números y alimentos son sintéticos, redactados manualmente para Fase A. El [RFC](../../../docs/NUTRITION_EXCHANGE_RFC.md) define los resultados semánticos esperados al implementar B–D. La validación estructural de estos archivos no ejecuta la aplicación ni escribe datos.

| Archivo | Resultado estructural | Resultado semántico esperado |
| --- | --- | --- |
| [valid-explicit.json](valid-explicit.json) | Válido | Cuatro comidas. Referencias por masa, volumen, pieza y total consumido. Para energía: 195, 150, 165.125 y 60 kcal en sus comidas correspondientes, total 570.125 kcal. Detalles con las 30 claves, estimación sobre etiqueta declarada, cero, desconocido, traza, límite y un nutriente adicional. Los ingredientes descriptivos sin cantidades ni declaración no aportan al total del plato. |
| [valid-needs-review.json](valid-needs-review.json) | Válido | Solicita destino una vez. Primera comida pendiente de fecha si se elige consumo, filas con base ausente, base de masa incompatible con volumen y cantidad ausente. Segunda comida presenta dos fuentes para un plato. No sumar 120 y 110 kcal ni seleccionar una fuente sin revisión. |
| [invalid-internal-field.json](invalid-internal-field.json) | Inválido en `/meals/0/foods/0` | La fuente no puede enviar confirmación de revisión. |
| [invalid-nutrient-unit.json](invalid-nutrient-unit.json) | Inválido en `/meals/0/foods/0/nutrition/values/sodium/unit` | La clave canónica `sodium` usa mg. |
| [invalid-nutrient-state.json](invalid-nutrient-state.json) | Inválido en `/meals/0/foods/0/nutrition/values/vitamin_d` | Traza y cero exacto no pueden coexistir en la misma observación. |

Reproducción desde la raíz con Python y `jsonschema` del proyecto:

```powershell
@'
import json
from decimal import Decimal
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

def read(path):
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)

schema = read(Path("schemas/nutrition_exchange_1_0.schema.json"))
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema, format_checker=FormatChecker())
fixtures = Path("examples/qa/nutrition-exchange")
expected = {
    "valid-explicit.json": set(),
    "valid-needs-review.json": set(),
    "invalid-internal-field.json": {("meals", 0, "foods", 0)},
    "invalid-nutrient-unit.json": {("meals", 0, "foods", 0, "nutrition", "values", "sodium", "unit")},
    "invalid-nutrient-state.json": {("meals", 0, "foods", 0, "nutrition", "values", "vitamin_d")},
}
for name, paths in expected.items():
    errors = {tuple(error.absolute_path) for error in validator.iter_errors(read(fixtures / name))}
    assert errors == paths, (name, errors)
    print(name, "PASS")
'@ | .venv/Scripts/python.exe -
```
