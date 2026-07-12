# CSV import

Ruta: `/imports/files`.

## Pesajes

Perfiles:

- `generic_es`
- `generic_en`

Columnas reconocidas:

- fecha / date / datetime / recorded_at
- peso / peso_kg / weight / weight_kg
- unidad / unit

Unidades:

- kg directo;
- lb/lbs convertido a kg.

Fechas:

- ISO;
- `YYYY-MM-DD HH:MM`;
- `DD/MM/YYYY`;
- `DD/MM/YYYY HH:MM`.

## EnergÃ­a diaria

Columnas reconocidas:

- fecha / date
- calorias_totales / total_expenditure_kcal / total_calories
- calorias_activas / active_expenditure_kcal / active_calories
- calorias_reposo / resting_expenditure_kcal / resting_calories
- pasos / steps
- distancia_m / distance_m / distance_meters
- distancia_km / distance_km

## Reglas

- UTF-8 con o sin BOM.
- Delimitadores coma, punto y coma o tab.
- Decimal punto o coma.
- Filas invÃ¡lidas aparecen como warnings; si ninguna fila genera documento vÃ¡lido, se rechaza.
- MM/DD/YYYY no se autodetecta para evitar ambigÃ¼edad.
