# Fixtures ficticias — Issue #32

Todos los alimentos, marcas, cantidades y nutrientes son inventados para QA.
No representan una persona ni una dieta real. Regenerar desde raíz con:

```powershell
.venv/Scripts/python.exe scripts/nutrition/qa_preview_fixtures.py
```

- `clean-21.json`: alias externo, destino explícito consumos, 21 declaraciones
  completas por 100 g. No es JSON legacy. Resultado: 21 listos/0 pendientes.
- `clean-21.csv`: los mismos 21 alimentos con columnas de aplicación y unidades
  absolutas explícitas. Resultado: 21 listos/0 pendientes, sin catálogo.
- `one-error-51.json`: 50 declaraciones completas y una con referencia por 100 ml
  que contradice la base explícita de 100 g (registro 26). Se bloquea sólo esa
  fila hasta que QA verifica la base; los 51 se guardan atómicamente.

Los tests generan además TSV, XLSX, texto y 2.1 en memoria. Las fixtures legacy,
PDF/OCR e imágenes anteriores se siguen probando; no se modifican para simular
compatibilidad universal.
