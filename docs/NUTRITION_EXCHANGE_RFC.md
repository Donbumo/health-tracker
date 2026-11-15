# RFC · Health Tracker Nutrition Exchange 1.0

Propuesta de Fase A para el [Issue #44](https://github.com/Donbumo/health-tracker/issues/44). Auditada sobre `master@1832336`. El [schema HTNX](../schemas/nutrition_exchange_1_0.schema.json), los [ejemplos ficticios](../examples/qa/nutrition-exchange/README.md) y el [prompt para copiar](NUTRITION_EXCHANGE_PROMPT.md) requieren revisión antes de activar el formato en Health Tracker.

## Decisión

HTNX define el intercambio de **observaciones nutricionales externas**. `nutrition_import 2.1` sigue siendo el contrato canónico para planificar, validar y registrar el lote en Health Tracker. El contenido entrante pasa por detección, normalización y validación semántica. El servidor crea la proyección 2.1 validada para planificar el guardado cuando hay datos suficientes, y la revalida dentro de la confirmación. La exportación y el backup conservan sus formatos de dominio y la procedencia. HTNX no introduce un escritor, un segundo modelo de dominio ni un formato de restore.

### Auditoría

| Capa vigente | Qué ofrece y dónde interviene el cambio |
| --- | --- |
| [Detección estándar](../backend/app/services/importers/schema_detector.py), [generador](../backend/app/services/importers/standard_json_generator.py) | Detección por schemas registrados y generación que valida el contrato. HTNX se detectará en la entrada nutricional, sin registrarlo como destino estándar ejecutable. |
| [Extractor nutricional](../backend/app/services/importers/nutrition_sources.py), [adaptación 2.1](../backend/app/services/importers/nutrition_source_21.py), [semántica 1.0](../backend/app/services/importers/nutrition_legacy_semantics.py) | JSON, etiquetas, PDF y tablas pasan por extractores con límites. Las rutas JSON ya tienen aliases, gramáticas de notas y recuperación de 2.1. La rama genérica elige una colección y normaliza sus filas, sin un contrato que distinga de forma uniforme comida, alimento y componente. Los formatos explícitos 1.0 y 2.1 conservan el despacho vigente. |
| [Schema 2.1](../schemas/nutrition_import_2_1.schema.json), [schema 1.0](../schemas/daily_nutrition.schema.json) | Los dos exigen campos del dominio. 2.1 requiere propietario, SHA, clave de evento, destino y estructuras de composición, evidencia y confirmación. Esos requisitos protegen la persistencia, pero dejan trabajo del servidor en manos de quien emite un archivo. |
| [Revisión](../backend/app/services/nutrition_import_review.py), [bases compartidas](../backend/app/services/nutrition_import_basis.py), [porciones](../backend/app/services/nutrition_import_portions.py) | Ya separan valores declarados de aportes consumidos, permiten revisar por fila y agrupan propuestas verificadas contra el original. La ruta de agrupación 2.1 exige condiciones concretas sobre el original y una decisión de revisión. HTNX aporta una base estructurada que evita usar una frase como prueba de equivalencia. |
| [Cálculo Decimal](../backend/app/services/nutrition_math.py), [preview](../backend/app/services/nutrition_import_preview.py) | Registro de 30 nutrientes, estados, cálculo de aporte, cobertura y resumen. Se reutilizan para evitar una fórmula paralela y para que el preview y el escritor den los mismos totales. |
| [Rutas](../backend/app/nutrition/routes.py), [servicio de importación](../backend/app/services/nutrition_import.py), [ejecutor](../backend/app/services/importers/standard_import_executor.py) | Revisión autenticada, recurso ligado al propietario, CSRF, plan firmado con revisión y documento, consentimiento, recibo, bloqueo y transacción. La ruta de carga oficial conserva originales tras extracción y deduplica por propietario y bytes. La detección y el cálculo se mantienen de sólo lectura. |
| [Reprocesado](../backend/app/services/nutrition_import_reprocess.py), [portabilidad nutricional](../backend/app/services/nutrition_portability.py), [backup](../backend/app/services/backups.py) | Original verificable, plazos de revisión, revisiones nuevas con arrastre controlado de decisiones y exportación/restauración sobre los contratos de dominio. La Fase B probará la supervivencia de procedencia y de la distinción ausente/desconocido en el round-trip. |

Los fixes [#38](https://github.com/Donbumo/health-tracker/issues/38) y [#40](https://github.com/Donbumo/health-tracker/issues/40) sirven como regresiones. Su aceptación real y las revisiones previas siguen su propio flujo.

## Contrato de entrada

Validar el objeto declarado con [JSON Schema 2020-12](https://json-schema.org/draft/2020-12/json-schema-validation) y un comprobador de fechas. La validez estructural permite la revisión. El estado «Listo» añade requisitos de destino, evidencia, porción, base y conflictos. El schema es autocontenido y usa referencias locales. Su `$id` identifica el contrato y no exige conectividad.

| Ubicación | Campos HTNX | Autoridad y comportamiento |
| --- | --- | --- |
| Documento | `format: "health-tracker-nutrition"`, `version: "1.0"`, `meals` requeridos | Una o más comidas/grupos. El orden de arrays se conserva. El orden de propiedades es indiferente. |
| Documento | `destination`, `date`, `note` opcionales | El destino es una propuesta del archivo. Los valores son `consumed`, `plan`, `recipe` y `product`. Con destino ausente o discrepante se pregunta una vez. Fecha ISO `YYYY-MM-DD`, predeterminada para grupos sin fecha propia. |
| Comida | `foods` requerido. `type`, `name`, `date`, `note` opcionales | `type` admite `breakfast`, `lunch`, `dinner`, `snack`, `other`. Una fecha de comida sustituye explícitamente al valor predeterminado. Una comida sin categoría conserva su nombre y su lugar en el archivo. |
| Alimento o ingrediente | `name` requerido. `quantity`, `nutrition`, `note` opcionales | Omitir lo desconocido. Una cantidad omitida o una fecha sin resolver para un consumo se mantiene pendiente. `quantity` lleva `amount` positivo y `unit`. Para `portion` o `piece`, `label` describe la unidad de ese alimento. |
| Plato | `ingredients` opcional | Lista de componentes del plato en las cantidades que contiene el plato descrito. Un nivel de anidamiento. Se conservan el orden y las relaciones. Cada comida puede incluir platos y alimentos separados. |
| Nutrición | `values` y/o `additional_nutrients`, con al menos un dato. `basis`, `quality`, `source`, `note` opcionales | Las observaciones usan la base del bloque. Un bloque sin base conserva los valores pendientes. `source` y `note` aportan evidencia textual, sin instrucciones ejecutables ni acceso de red. |
| Observación | `value`, `state`, `unit`, `limit` según estado. `quality`, `source`, `note` opcionales | `value` con unidad implica `known` si se omite `state`. `unknown` permite omitir la unidad. `trace` exige unidad. `below_limit` exige unidad y `limit` positivo. Los tres estados cualificados carecen de `value`. Sólo `below_limit` admite un límite. |
| Entrada al servidor | Propietario, original, SHA, evento, vínculos, revisión, firma y consentimiento | Se derivan en la capa correspondiente. Las propiedades estructurales no listadas se rechazan, también dentro de alimentos, ingredientes y observaciones. |

Para receta y producto, los grupos organizan el archivo y sus fechas son contextuales. El mapeo propuesto hacia 2.1 usa `recipes` y `products` respectivamente. Formar una receta o una ficha de producto requiere sus verificaciones actuales y un destino explícito de revisión. Una ficha de producto con sólo base nominal y una receta sin composición verificable se mantienen pendientes. Los grupos prescritos usan `plan`. HTNX 1.0 describe alimentos y sus componentes. Los resúmenes diarios sin alimentos siguen en el flujo 1.0 existente.

### Bases, cantidades y decimales

- `basis: {"amount":100,"unit":"g"}` o su equivalente en ml declara una referencia. Cualquier cantidad positiva de referencia compatible se admite, incluidas porciones y piezas con etiqueta. `basis: {"kind":"consumed"}` declara el total para la cantidad de esa fila tal como figura en el original. Un cambio a esa cantidad invalida la interpretación automática. La cantidad sigue siendo necesaria para completar la fila.
- Con dimensiones compatibles, el motor Decimal existente calcula `valor × cantidad_elegida / base`. Por ejemplo, 150 g referidos a 130 kcal por 100 g producen 195 kcal. Si la fuente ya expresa 195 kcal para los 150 g consumidos, el factor inicial es uno. Un límite de detección se convierte con el mismo factor sin pasar a valor conocido.
- Una pieza o porción sólo se escala dentro de la misma fila y con idéntica unidad y etiqueta tras NFC y recorte exterior. La adaptación mapea `piece` a la unidad nominal `portion` de 2.1 con evidencia de tipo y etiqueta. Dimensiones o etiquetas distintas quedan pendientes de una equivalencia explícita y de revisión por el propietario. Sin conversión implícita entre g, ml, pieza, porción o estados crudo/cocido.
- Los números JSON se leen desde el lexema con Decimal. También se admiten cadenas decimales simples con punto. Cantidades, bases y límites son mayores que cero. Nutrientes conocidos admiten cero. El máximo es 100 000 000 y se usan hasta 12 decimales efectivos tras eliminar ceros de escala sin redondear. Para números JSON, esa precisión se comprueba semánticamente. El schema comprueba rango y acota la sintaxis y escala de cadenas. Las cadenas no admiten exponente, signo o coma.
- Una base estructurada, comprobable y compatible hace calculable el aporte de revisión con una sola escala. Bases ausentes, evidencias incompatibles y dos autoridades del mismo plato no pasan a totales. Las observaciones en texto se muestran en contexto. Una contradicción detectada con evidencia explícita se eleva a diagnóstico por campo o archivo. Una nota larga por sí sola no decide la semántica.

### Nutrientes, calidad y cobertura

| Unidad | Claves exactas de `nutrition.values` |
| --- | --- |
| `kcal` | `energy` |
| `g` | `protein`, `carbohydrate_total`, `net_carbs`, `fat`, `fiber`, `sugar` |
| `mg` | `sodium`, `potassium`, `calcium`, `iron`, `magnesium`, `phosphorus`, `zinc`, `vitamin_c`, `vitamin_e_alpha`, `thiamin`, `riboflavin`, `niacin`, `vitamin_b6`, `choline` |
| `ug` | `vitamin_a_rae`, `retinol`, `vitamin_a_re`, `vitamin_d`, `vitamin_k1`, `vitamin_k2`, `vitamin_b12`, `folate_dfe`, `folate_food` |

`additional_nutrients` conserva observaciones con nombre y unidad original. Se muestran fuera de los totales y siguen siendo evidencia aunque su nombre se parezca al de una clave soportada. El catálogo de claves queda fijado por versión de HTNX. Una versión nueva puede añadir nutrientes y documentar su proyección canónica.

Un valor `known` cero cuenta como valor conocido. Una clave omitida está **no proporcionada**. Una clave con `unknown` registra que la fuente la declaró desconocida. `trace` y `below_limit` conservan su significado y límite, cuando existe. El subtotal de conocidos puede ser parcial. Si no hay valores conocidos queda sin valor numérico. Se preserva la diferencia entre clave omitida y desconocida en el vector fuente y la procedencia incluso si la vista agregada usa un estado común de cobertura.

`quality` admite `declared`, `estimated`, `label` y `unknown`. El valor por nutriente prevalece sobre el del bloque. Al omitir ambos se muestra «Declarado» sin atribuir verificación. `label` significa que la fuente dice haber leído una etiqueta, por lo que se proyecta como procedencia declarada salvo verificación independiente en el flujo vigente. Con estimaciones y valores de otras calidades se muestra calidad mixta, conservando la etiqueta por nutriente. Ni la fuente ni un modelo pueden reconocer una identidad del catálogo por nombre o convertir una estimación en medición.

Una declaración directa de plato y sus ingredientes son fuentes alternativas del mismo aporte. Si sólo la declaración directa es calculable, los ingredientes descriptivos siguen visibles como evidencia. Para derivar desde ingredientes se comprueba que cubran el plato y correspondan a la cantidad descrita, además de validar cantidades, unidades y nutrientes. Si hay dos fuentes calculables o la composición es dudosa, se pide una sola elección de autoridad para ese plato. Sólo la fuente elegida se proyecta a 2.1. Nunca se crean consumos independientes para sus componentes por recorrer el árbol.

## Arquitectura propuesta para Fase B

1. **Decodificar y detectar.** Una ruta nutricional para bytes de archivo o texto pegado. Límite inicial de 10 MiB, hasta 250 alimentos más ingredientes combinados y presupuestos explícitos de profundidad, miembros y longitud antes de procesar. Rechazar UTF-8 inválido, claves duplicadas, no finitos y números fuera del presupuesto antes de interpretar. El marcador de HTNX tiene precedencia. Su versión desconocida o schema inválido se diagnostican como HTNX. Un documento que combine marcadores explícitos incompatibles genera conflicto de formato. Para 2.1 y 1.0 se conservan los discriminantes y modos oficiales; cualquier modo de rescate existente conserva sus validaciones y diagnóstico propio.
2. **Adaptar a observaciones.** HTNX exacto, 2.1, Daily Nutrition y JSON común tienen adaptadores independientes. Durante la migración sólo HTNX y las familias comunes aprobadas entran por la ruta nueva. Para JSON común, detectar contenedores arraigados de comida/alimento y usar un diccionario versionado de aliases por campo y contexto, con candidatos y ruta de origen. Por ejemplo, `comidas/alimentos` y `meals/foods` pueden mapear a la misma estructura. `carbs` a secas no autoriza total/neto. Dos aliases conflictivos quedan pendientes en lugar de escoger uno por orden. El conversor sólo aplica conversiones de unidades explícitas, exactas y compatibles, como kg→g o mcg→ug. Cualquier IA que sugiera mappings es opcional, fuera de B, y pasa por los mismos controles.
3. **Normalizar, validar y presentar.** El validador distingue faltantes, contradicciones y valores no soportados con diagnósticos estructurados. Después de validar, se proyectan los datos al mecanismo de revisión existente y se reutiliza el motor Decimal. En la revisión se guardan por separado la presencia original, propuesta de interpretación y decisión del usuario. En edición se invalida la decisión si cambian sus entradas. Para contratos verificables se ofrece una confirmación por grupo: misma acción, base y evidencia determinista aplicable a cada fila. Las excepciones se excluyen y explican por separado. Una base ausente sin evidencia suficiente carece de propuesta aceptable, aunque aparezca en todas las filas.
4. **Confirmar mediante el sistema vigente.** Antes de emitir token, generar 2.1, validar su schema, planificar y detectar datos previos por fecha. Resolver un conflicto de fecha es independiente de confirmar la base. El POST de base sólo muta el borrador. El POST de guardado requiere propietario efectivo, CSRF, revisión, token vigente, consentimiento y plan consistente dentro del bloqueo existente. Para consumo declarado suficiente se reutiliza la ruta sin alta de catálogo. El escritor, los snapshots y el recibo mantienen la transacción existente.

### Contrato de representación intermedia

Tipos conceptuales de B. La IR contiene hechos del documento y localizadores, con decisiones fuera de la fuente. Los agregados 1.0 sin alimentos siguen por su ruta oficial, sin crear alimentos ficticios para ajustarlos a la IR. La versión del adaptador forma parte de la procedencia al guardarse el borrador. Los valores ausentes se representan por ausencia de clave o `null` interno según se indica.

```text
SourceBatch {
  profile: htnx_1_0 | standard_2_1 | daily_1_0 | common
  adapter_version: string
  destination_hint: consumed | plan | recipe | product | daily_aggregate | null
  default_date: LocalDate | null
  meals: ordered list<SourceMeal>
  diagnostics: list<Diagnostic>
}
SourceMeal {
  path: JsonPointer
  date: LocalDate | null               // fecha efectiva resuelta por ámbito
  date_path: JsonPointer | null       // documento o comida
  type: breakfast | lunch | dinner | snack | other | null
  name: text | null
  foods: ordered list<SourceFood>
}
SourceFood {
  path: JsonPointer
  name: text | null                    // falta de identidad en fuentes comunes
  quantity: Quantity | null
  nutrition: Declaration | null
  ingredients: ordered list<SourceFood> at depth 1
  evidence: list<Evidence>
}
Quantity { amount: Decimal > 0, unit: g | ml | portion | piece, label: text | null }
Declaration {
  basis: reference(Quantity) | consumed | absent
  values: sparse map<CanonicalNutrientKey, Observation>
  additional: ordered list<{ name: text, observation: Observation }>
  evidence: list<Evidence>
}
Observation =
  known(Decimal >= 0, Unit) | unknown(Unit?) | trace(Unit) | below_limit(Decimal > 0, Unit)
  with effective_quality, source_text?, note?, source_path
Evidence { path: JsonPointer, mapping_rule?: string, conversion?: string, note?: text }
Diagnostic { code, path: JsonPointer, scope: file | meal | food | field,
             severity: warning | decision | invalid, message_key, action_key }
```

`JsonPointer` usa escapes estándar de JSON Pointer y es relativo al documento. Las cadenas originales y notas por nivel se leen del original por su localizador y se conservan como evidencia. La IR normaliza la forma: una conversión mantiene unidad y valor fuente accesibles. `LocalDate` no aplica una zona horaria ni inventa una fecha. Las identidades internas, el SHA, la revisión, el estado de preparación, el plan y el consentimiento pertenecen a servicios de aplicación fuera de la IR. El borrador registra por separado decisiones con huella de entradas relevantes (documento, ruta, base, cantidad, vector, conflictos y versión) y localizadores de evidencia para revalidar antes de un POST agrupado.

La proyección a 2.1 usa fechas, nombres y vectores validados, aporta `portion_amount`, `portion_unit`, `declaration.basis_*`, calidad por nutriente y evidencia de valores originales mediante el constructor actual. Conserva las observaciones adicionales como evidencia, fuera del vector canónico. Los vínculos y la composición se obtienen sólo tras verificar identidades y autoridad del plato en la revisión. Se verifica mediante round-trip de 2.1, exportación y restore que cada hecho que afecta a valores, cobertura, autoridad y calidad sobrevive. Si el almacenamiento actual no representa un hecho, B debe resolver su portabilidad antes de activar la familia correspondiente.

### Diagnóstico, originales y repetición

| Ejemplo de código | Respuesta y acción |
| --- | --- |
| `invalid_json`, `unsupported_version`, `schema_error` | 422 con archivo/sección, puntero cuando se conoce, motivo y acción (p. ej. elegir un ejemplo de versión compatible). Se permite corregir y volver a intentar. Cuerpo o estructuras que superan límites reciben 413. |
| `missing_date`, `missing_quantity`, `missing_basis`, `incompatible_units`, `conflicting_authority` | Borrador revisable. Mostrar observación fuente y campo pendiente. Pedir una acción sólo donde falta autoridad. |
| `unsupported_nutrient`, `possible_duplicate` | Evidencia no contabilizada o candidato que requiere comparar con datos existentes. Una coincidencia por nombre, fecha o igualdad de macros carece de autoridad para fusionar. |
| `stale_revision`, `original_unavailable` | Conflicto de revisión, recuperar con las rutas oficiales cuando existe original. Recursos ajenos se tratan como no encontrados. |
| Fallo inesperado | Mensaje genérico con identificador de diagnóstico para soporte. Los logs incluyen código, perfil y conteos cuando se conocen y excluyen archivo, valores, fecha personal, rutas internas, credenciales y texto de la fuente. |

Los extractores y la planificación no escriben. El POST técnico de preparación oficial crea o reutiliza original y revisión owner-only de manera consistente. Un error revierte DB y archivo recién creado según las garantías vigentes. Un original íntegro de un borrador revisable se conserva aunque tenga campos pendientes. Para un JSON rechazado antes de crear borrador, B evaluará ofrecer «Conservar original para reintentar» como paso explícito del flujo oficial. Tendrá que crear evidencia recuperable y enlazada a la cuenta o devolver un diagnóstico sin escrituras. Un archivo inválido o que exceda límites no se convierte en un borrador vacío.

Se reutilizan SHA de bytes por propietario, recibo y operación atómica. Cambios sólo de formato pueden generar otro SHA y no restauran la autoridad de un recibo anterior. La detección de similitud propone revisar duplicados sin descartar comidas identificables ni autorizar una segunda escritura. El historial de revisiones, los límites de vigencia y los originales se conservan. Reprocesar es explícito y crea o reutiliza una revisión vinculada. Las decisiones compatibles se copian mediante el mecanismo vigente y se comprueban nuevamente contra la evidencia.

## Fases de activación y criterios verificables

| Fase | Entrega y condición para avanzar |
| --- | --- |
| A · Revisión | Contrato, esquema, RFC, prompt y vectores ficticios. Los válidos pasan con validación de fechas, los inválidos fallan en su campo, las 30 claves y unidades coinciden con el registro canónico. PM revisa destino, evidencia de unidades nominales y valor insuficiente antes de aprobar el motor. |
| B · Motor aislado | Nuevos adaptadores, IR, diagnósticos, reglas Decimal y proyección. Primero HTNX bajo selección explícita en QA. Incorporar sólo familias genéricas con fixtures trazables. Mantener despacho 1.0/2.1 y demás extractores. Verificar ida y vuelta del dato canónico y originales reanalizables. Sin migración de borradores ni cambio de DB previsto. |
| C · Interfaz | Desde la entrada habitual de importaciones, «Importar comidas con IA» permite pegar, subir, copiar el prompt y descargar un ejemplo. El usuario ve alimentos por comida, cantidad, base, valores declarados frente a aporte calculado, micronutrientes y calidad. Muestra conteo de filas, advertencias y CTA por grupo. Accesibilidad, tema y ancho según las [reglas Web UI](project-rules/web-ui.md). La publicación de schema/ejemplo bajo una URL versionada se diseña aquí. |
| D · Pruebas y activación | SQLite y MariaDB RC/RR 0046, escritorio/móvil, backup restaurado y smoke propietario tras autorización. Publicar sólo `web`, con posibilidad de desactivar la entrada nueva o volver a la imagen anterior. Antes de habilitar en NAS, probar que el rollback conserva acceso o recuperación a los nuevos originales y no reinterpreta silenciosamente sus borradores. |

| Caso | Observación requerida antes de activar |
| --- | --- |
| HTNX completo, 100 g, 100 ml, porción, pieza y total consumido | El 100% de fixtures conformes y resolubles se revisa sin correcciones técnicas. Paridad exacta Decimal en alimento, comida y día para las 30 claves. Ningún factor aplicado dos veces. |
| Parciales, calidad mixta, omisión, cero, desconocido, traza, límite y nutriente adicional | Todas las observaciones aparecen con su estado y procedencia. El subtotal sólo incluye los conocidos calculables. El valor declarado pendiente nunca aparece como ausente. |
| 18 filas homogéneas, una excepción, base ausente sin evidencia, plato con ingredientes, fecha solapada | 18/0 o 17/1 según variante, con una sola acción si el grupo necesita confirmación. La excepción no cambia el estado de las otras filas. El conflicto de fecha mantiene bloqueado el guardado hasta su revisión. No sumar plato y componentes. |
| JSON común en varios idiomas, propiedades reordenadas y campos omitidos | Cada equivalencia de clave conserva ruta y regla. Fechas ambiguas, unidades conflictivas y total/neto requieren resolución. Casos desconocidos generan 422 o revisión parcial explícita. |
| Fixtures independientes | En D obtener al menos una salida ficticia independiente de ChatGPT, Gemini, Claude y otro asistente, más una manual. Conservar prompt, modelo y fecha de la prueba, estructura original y resultado sin datos personales. Los ejemplos de A son manuales. |
| Recuperación y concurrencia | Regresiones ficticias de 14/18/21/23 filas en 1.0/2.1, caducidad, original perdido, clon y revisión posterior. Mismo byte y mismo propietario reutilizan. Aislamiento entre propietarios, doble envío, replay, firma obsoleta, CSRF, rollback sin huérfanos, export/restore y notas intactas. |
| Confirmación y UX | En escritorio y móvil una persona sin conocimientos de JSON copia el prompt, trae el documento y revisa sólo ambigüedades. Ningún consumo, producto, receta, plan o recibo antes del POST final autorizado. Borrador preparado con consentimiento desmarcado. En QA aislada, confirmar una vez y comprobar persistencia y replay. |

Riesgos para revisión PM: preservar la ausencia frente a desconocido en export/restore, compatibilidad de etiquetas nominales durante reprocesado, falsos positivos de mapeo o duplicación, y separación de evidencia inválida frente a originales recuperables. El gate de activación también mide el porcentaje de fixtures completamente resolubles que llegan al estado listo sin correcciones. Un schema válido por sí solo no prueba ese resultado.
