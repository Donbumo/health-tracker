# Nutrition 2.1 — informe de importación

Evidencia: `backend/tests/test_nutrition_experience_21.py`, fixtures en
`examples/nutrition-2-1/fixtures/` y flujos reales en
`design/nutrition-intelligence-2-1/qa/ui-report.json`.
Todos los archivos y cuentas privados de QA son ficticios.

| Fixture/perfil | Resultado y límite |
| --- | --- |
| `diet-prescribed.pdf` | Texto, dos preparaciones con cantidades y macros; plan sugerido, sin consumo automático. |
| `diet-scanned.pdf` | PDF raster sin capa de texto; OCR ONNX local extrae ambas filas. |
| `diet.xlsx` | Hoja con nombre, cantidad, unidad, fecha y macros; evidencia de hoja/fila. Fórmulas no se ejecutan. |
| `app.csv` | Perfil de columnas MyFitnessPal probado con export sintético; fecha/comida/alimento/macros. Unidades y total/neto ambiguos requieren revisión. |
| `table.tsv` | Separador tabular detectado; cantidades/unidades explícitas. |
| `internal.json` | Documento válido DailyNutrition 1.0; conserva valores, sin confiar en su `user_id`. |
| `external.json` | Nombres de campos externos normalizados, original conservado. |
| `nutrition-export.zip` | JSON y TSV contenidos; extracción acotada sin rutas arbitrarias ni ZIP anidado. |
| `label.png`, `label.jpg`, `label.webp` | OCR local real; valores por 100 ml, porción 250 ml, contenido neto 500 ml, marca y código. “Carbohidratos totales” es explícito. |
| `compound-macros.json` | Conserva 450 kcal/35 g; ingredientes y micros estimados separados. |
| `missing-brand.json` | Producto no catalogado; no inventa marca ni nutrientes faltantes. |
| `ambiguous-unit.json` | “cup” sin equivalencia y proteína sin unidad no se convierten ni confirman automáticamente. |
| `duplicate.json` | Mismos bytes con otro nombre: recibo idempotente, sin duplicar registros. |
| `prescribed-no-consumption.json` | Destino plan, día prescrito sin inventar fecha real. |
| `date-conflict.json` | Fecha registrada: bloquea; exige omisión o decisión explícita de consumo distinto. |

Son 17 archivos representativos, cubriendo los 14 escenarios solicitados. La
compatibilidad se limita a los perfiles y estructuras probados; no se afirma
lectura universal de exportaciones de otras aplicaciones ni de cualquier PDF.

## Controles comprobados

Firma y estructura prevalecen sobre extensión/MIME declarados. Máximo 10 MiB,
250 filas, 8 páginas/hojas, 12 MP, 40 MiB expandido y 100 entradas ZIP. No se
truncan silenciosamente listas extensas. Se rechazan traversal, enlaces,
compresión excesiva, ZIP anidado, PDF cifrado/acciones activas y macros Excel.
Se usa defusedxml para XLSX. No se ejecutan fórmulas ni se abren URLs del archivo.

Owner se deriva del servidor. Preview y extracción no escriben dominios.
El usuario confirma destino, identidad, cantidad y campos críticos; hay CSRF,
revisión optimista, token de confirmación, SHA de archivo, idempotencia, auditoría
y rollback del batch. El estado del original y el recibo se actualizan dentro
de la transacción. Cambiar un evento importado existente genera conflicto.

Un porcentaje de referencia queda como evidencia si no hay base absoluta. Un
carbohidrato ambiguo debe clasificarse como total, neto o no contabilizable.
Cambiar de clasificación retira su asignación anterior. Un campo con unidad
incompatible no se prellena bajo la unidad canónica. Unknown no se convierte en
cero; preparación parcial sin macros originales no inventa valores declarados.

La prueba de navegador completa PDF → dos IDs USDA reales → plan y foto →
producto privado → edición de revisión. Los planes y productos no se suman a
DailyNutrition al guardarlos. Usar un plan después crea un borrador nuevo con
revisión explícita; sólo confirmar ese borrador crea MealLog y su proyección.

## Límites visibles

Un layout OCR no reconocido devuelve texto/evidencia y pide corrección manual.
No hay reconocimiento de proporciones por foto de plato ni IA autoritativa.
Campos genéricos vitamina A/folato sin forma química no se equiparan a RAE/RE/DFE.
Rendimiento se documenta sin inferir pérdidas o retención. Una receta legacy
requiere masa representable; preparaciones por volumen sin densidad pueden
quedar en planes/borradores/consumos con cobertura por masa no calculable.

## Revisión final por etapas y originales

Identificación → cantidad/composición → declaración nutricional → confirmación.
Cada formulario modifica sólo su etapa y retira la confirmación anterior.
Los guards, canonización, tokens, idempotencia y transacción existentes siguen
siendo obligatorios; navegar directamente a confirmación no los evita.

Cancelar conserva el original por defecto. El usuario puede eliminarlo
explícitamente antes de confirmar o después de cancelar, aceptando la advertencia.
La revisión se cierra, texto/evidencia se conservan y los snapshots no cambian.
Se bloquea eliminación ante recibos confirmados, referencias o revisiones
compartidas; un archivo identificado por otro importador requiere su política.
Una revisión que perdió su original no puede confirmarse.

La selección OFF firma una propuesta owner-bound y abre el formulario precargado.
Crear el producto requiere revisar sus campos, generar un preview y confirmar.
La procedencia se conserva; total/neto ambiguo, porcentaje o límite no se
autocompletan como un valor exacto. El UI end-to-end usa respuesta OFF simulada,
sin tráfico externo. Ver [evidencia final](NUTRITION_EXPERIENCE_2_1_FINAL_REVIEW.md).
