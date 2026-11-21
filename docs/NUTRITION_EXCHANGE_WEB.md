# Importar comidas con IA

En Nutrición → Importar archivo se puede copiar el [prompt HTNX 1.0](NUTRITION_EXCHANGE_PROMPT.md), descargar el ejemplo, pegar un JSON o subir un archivo. La entrada admite [HTNX 1.0 y las familias de JSON común documentadas](NUTRITION_EXCHANGE_ENGINE.md). Health Tracker recibe el JSON que entrega el usuario. El botón de copiar usa el portapapeles local.

La revisión ordena los alimentos por comida y distingue los valores declarados, calculados y pendientes. Conserva cero, desconocido, traza, bajo el límite y dato omitido. Los nutrientes adicionales se muestran en procedencia y quedan fuera de los totales. Una base ausente con cantidad en la misma unidad métrica se puede resolver en grupo si el propietario confirma la relación con la cantidad consumida. Las bases incompatibles se revisan por alimento. El flujo resuelve el destino de comidas consumidas. Los flujos existentes siguen gestionando planes, recetas y productos.

Algunos portapapeles Markdown escapan corchetes y guiones bajos al copiar un documento HTNX. La entrada web reconoce esa representación tras el fallo de sintaxis, conserva íntegro el original y valida la vista decodificada con el mismo esquema y los mismos límites.

Los posibles duplicados muestran coincidencias en el archivo o en el historial del propietario. El usuario puede elegir si la entrada corresponde a un evento distinto o debe omitirse. El solapamiento con un resumen diario tiene una confirmación independiente que conserva el registro existente.

## Activación

`NUTRITION_EXCHANGE_ENABLED` se desactiva por defecto. La interfaz requiere también `NUTRITION_INTELLIGENCE_ENABLED` y una sesión autenticada. Los recursos versionados usan `Cache-Control: private, no-store`. Los borradores anteriores conservan su ruta habitual.

El flujo comparte el motor HTNX, los borradores y el escritor oficial `StandardImportExecutor`. Guarda las correcciones como decisiones en la revisión, con el original íntegro. Valida el propietario, el SHA del original, la caducidad, la revisión optimista y el CSRF. Actualiza el estado de coincidencias antes de firmar el plan y vuelve a comprobarlo con el bloqueo del propietario al confirmar. Guardar requiere el consentimiento expreso del usuario. El checkbox empieza desmarcado.

## Evidencia con datos ficticios

| Origen | Evidencia |
| --- | --- |
| Manual | [Ejemplo HTNX](../examples/qa/nutrition-exchange/valid-explicit.json) con cuatro comidas, 30 claves nutricionales y un total de 570.125 kcal. |
| Gemini | [Salida independiente](../examples/qa/nutrition-exchange/providers/gemini.json). Dos alimentos listos. Conserva la calidad estimada y la calidad de etiqueta declarada. |
| Perplexity | [Bloque JSON independiente](../examples/qa/nutrition-exchange/providers/perplexity.json). Dos alimentos listos. El asistente omitió la calidad de etiqueta del yogur ficticio y la aplicación respetó la omisión. |
| ChatGPT | [Copia original de la respuesta](../examples/qa/nutrition-exchange/providers/chatgpt.clipboard.txt) obtenida el 21 de noviembre de 2026 en ChatGPT web, sesión pública. La interfaz no mostró un identificador de modelo. Pegado y subida de la misma copia con 2 listos, 1 pendiente y 0 inválidos. |
| Claude | Pendiente. El servicio pidió iniciar sesión. |
| JSON común | Casos sintéticos representativos en español e inglés. Sirven para probar adaptadores, agrupación y contradicciones. |

Gemini y Perplexity recibieron el mismo caso ficticio en conversaciones separadas mediante sus interfaces. El caso pide una base de 100 g para una cantidad de 150 g y una base consumida para una porción nominal. Ambas salidas conservaron el total de 260.125 kcal, 4.05 g de proteína, el cero declarado, potasio desconocido, hierro en trazas y un límite en vitamina D. Las pruebas HTTP usan el JSON de cada asistente tal como se obtuvo.

La prueba de ChatGPT une el [prompt oficial](NUTRITION_EXCHANGE_PROMPT.md) y el [mismo registro ficticio preparado para Claude](../examples/qa/nutrition-exchange/providers/phase-d-case.txt), separados por una línea en blanco. «Copiar respuesta» devolvió escapes Markdown en corchetes y guiones bajos. La copia se conserva byte por byte y la prueba HTTP compara los 30 valores y sus unidades con el registro ficticio. El archivo conserva 162.81890625 kcal de aporte, calidad mixta y la declaración visible del alimento pendiente. La prueba comprueba que pegar y subir no duplican el borrador.

El [handoff de cierre](https://github.com/Donbumo/health-tracker/issues/44#issuecomment-7058462180) mantiene la validación independiente con Claude y la aprobación PM como gates de activación. Las pruebas de navegador usan datos ficticios y un entorno local.

[Entrada en escritorio](../design/nutrition-exchange/qa/desktop-entry.png) · [Resumen móvil con una excepción](../design/nutrition-exchange/qa/mobile-review.png) · [Declaración visible en la fila pendiente](../design/nutrition-exchange/qa/mobile-exception.png).

## Repetir las pruebas

Ejecuta `python -m pytest -q backend/tests` con `PYTHONPATH=backend`. Para las regresiones de archivos de actividad, el set QA local incluye los archivos ficticios enumerados en [real-file-imports](../examples/qa/real-file-imports/README.md). El generador del directorio recrea los FIT sintéticos.

Con MariaDB desechable 11.4 en loopback, ejecuta las suites `test_nutrition_exchange_*`, `test_nutrition_import_basis_string`, `test_nutrition_import_pending_basis` y `test_nutrition_import_source_21` con `QA_SOURCE21_DATABASE_URL` y `QA_ISOLATION`. El fixture comprueba MariaDB 0046 y el esquema mediante Alembic. Repite en READ COMMITTED y REPEATABLE READ. `scripts/nutrition/mariadb_preview_qa.py` añade retención de revisiones, exportación/restauración, rollback y carreras sobre la ruta del importador estándar.

Para navegador, inicia `scripts/nutrition/qa_exchange_web.py` y ejecuta `node scripts/nutrition/ui_qa_exchange_web.cjs` con Playwright y Edge. Define `QA_EXCHANGE_BROWSER_OUTPUT` hacia un directorio local de evidencia. El script usa una base SQLite desechable, dos cuentas de QA ficticias y el puerto 8067 en loopback. Comprueba portapapeles con teclado, descarga, pegado, subida, agrupación, consentimiento desmarcado y ausencia de HTTP 500 o errores JavaScript. Prueba seis anchos y dos temas en cada recorrido.
