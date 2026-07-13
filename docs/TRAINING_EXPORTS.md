# Exports de entrenamiento

## Training plan

JSON, CSV, HTML y PDF pueden usar la versión activa o una versión histórica seleccionada. JSON se valida contra `training_plan.schema.json`. HTML es standalone, sin recursos remotos, y escapa texto. PDF se genera con ReportLab, sin navegador externo.

ZWO y MRC aceptan únicamente sets con `duration_seconds` y target FTP explícito:

```text
75% FTP
power_pct_ftp:0.75
```

ERG acepta únicamente sets con duración y watts explícitos:

```text
190W
power_watts:190
```

Si el plan contiene varios días se debe seleccionar exactamente semana/día. Reps, peso, descanso, notas y ejercicios de fuerza se muestran como pérdidas. No se inventa FTP ni potencia.

## Training session

- JSON: `completed_workout.schema.json`.
- CSV: una fila por set, con duración, FC, calorías, reps, peso, RIR, RPE y descanso.
- HTML/PDF: resumen y tabla de ejercicios/sets con texto escapado.

El JSON conserva la referencia semántica a la rutina y versión exacta. El round-trip usa el importador oficial de completed_workout; IDs técnicos pueden remapearse en restore, pero no se ignoran versión, ejercicios, sets, reps o peso.
