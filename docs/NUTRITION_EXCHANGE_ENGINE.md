# Universal Nutrition Import · Fase B

Implementación de motor y QA para el [Issue #44](https://github.com/Donbumo/health-tracker/issues/44), sobre el [RFC aprobado](NUTRITION_EXCHANGE_RFC.md). El contrato HTNX 1.0 y el contrato canónico 2.1 conservan sus versiones.

## Uso en QA

```python
from app.services.importers.nutrition_exchange import common, intake, normalize

parsed = intake.parse(payload)
# HTNX estricto trae la IR. El adaptador común sólo admite las familias documentadas.
if parsed.profile in {"htnx_1_0", "common"}:
    batch = parsed.batch if parsed.batch is not None else common.adapt(parsed.document)
    result = normalize.evaluate(batch)
```

`intake.parse`, la adaptación y la revisión semántica no escriben. Los perfiles 2.1 y Daily Nutrition 1.0 conservan el despacho y la validación vigentes. El detector reconoce esos contratos sin tratarlos como HTNX ni reconstruir agregados diarios como alimentos.

`nutrition_import.start` conecta el motor con el borrador oficial exclusivamente bajo `TESTING=True` y `NUTRITION_EXCHANGE_QA_ENABLED=True`. Usar los dos valores en la configuración de la app efímera de QA. La opción no se carga desde el entorno. El guardado de un borrador de intercambio también verifica el modo QA. Las rutas de edición legacy no se usan para cambiar decisiones de intercambio.

El POST de preparación crea o reutiliza el original y una revisión técnica por propietario. Si falla la transacción, revierte la fila y quita el original nuevo. Las revisiones de otros perfiles con los mismos bytes se conservan. Reconocer duplicados técnicos usa el SHA de los bytes y lecturas con bloqueo bajo el bloqueo de propietario. La recuperación de un borrador vencido verifica SHA y pertenencia y crea una revisión vigente sin arrastrar decisiones vencidas. El POST final exige el consentimiento, firma, CSRF y comprobaciones vigentes del ejecutor.

## Módulos

| Módulo | Responsabilidad |
| --- | --- |
| [intake](../backend/app/services/importers/nutrition_exchange/intake.py) y [source](../backend/app/services/importers/nutrition_exchange/source.py) | Parseo acotado, precedencia de marcadores, validación con el schema, evidencia y diagnósticos tipados con JSON Pointer. Duplicados de clave, UTF-8 inválido, números no finitos y versiones no admitidas generan 422. Tamaño, profundidad, miembros y cantidad de filas están acotados. |
| [common](../backend/app/services/importers/nutrition_exchange/common.py) | Familias comprobables en español e inglés. Grupos `meals/comidas` con `foods/alimentos`, o una colección plana `foods/alimentos` con metadatos de grupo en la raíz. Cantidad, base y observaciones se leen de objetos estructurados. Los aliases conflictivos y carbohidratos sin distinción total/neto requieren revisión. Las claves adicionales son evidencia. |
| [normalize](../backend/app/services/importers/nutrition_exchange/normalize.py) | Aportes, cualificadores y límites mediante el cálculo Decimal vigente, una autoridad por plato y escala nominal NFC/recorte dentro de una misma entrada. Las cantidades incompatibles permanecen pendientes. Los componentes compatibles se suman antes del límite de precisión del snapshot. |
| [projection](../backend/app/services/importers/nutrition_exchange/projection.py) | Convierte la revisión en la forma del borrador consumido por el servicio vigente. Delega la construcción y validación 2.1. Conserva el agrupamiento por ruta de comida en la revisión. |
| [preparation](../backend/app/services/importers/nutrition_exchange/preparation.py) | Selección sólo en QA, comparación por propietario para posibles duplicados y solapamientos, y presupuesto de materialización del borrador. |

El límite del archivo es 10 MiB, con hasta 250 alimentos e ingredientes combinados. La revisión serializada tiene un límite propio de 4 MiB porque la evidencia puede crecer durante la materialización. Ambos límites responden 413 antes de almacenar el original. En QA, el cliente que solicita `application/json` recibe diagnósticos con código, puntero, ámbito, severidad, clave de mensaje y clave de acción. Los errores HTML siguen la ruta de importación vigente.

Una equivalencia verificada registra el factor, procedencia, entrada afectada, cantidad y base originales y su versión de borrador. El servicio `apply_exchange_decision` sólo acepta una decisión construida del lado del servidor. Verifica propietario, vigencia, revisión, bytes del original y dependencias antes de aplicar. El documento de origen no puede suministrarla. Una entrada con dos fuentes de plato necesita la elección de una sola autoridad. Elegir ingredientes exige cantidades compatibles, verificables para la cantidad del plato, y nutrientes suficientes. El dato de la otra autoridad permanece como evidencia.

La similitud de nombre, fecha, comida y cantidad compatible produce `possible_duplicate` sin quitar datos. Se elige el conjunto de candidatos desde el propietario efectivo. El solapamiento con un registro diario se evalúa aparte. Las dos decisiones permanecen pendientes para revisión, con los bloqueos del plan canónico como última verificación.

## Portabilidad demostrada

[Pruebas del flujo oficial](../backend/tests/test_nutrition_exchange_portability.py), con archivos ficticios:

- Validación HTNX, borrador, proyección 2.1 y guardado sintético con consentimiento. El replay reutiliza el resultado del escritor vigente.
- El vector de origen sigue disperso: clave ausente, desconocido explícito, cero conocido, traza y límite se cotejan en proyección, snapshot y restore. La calidad por nutriente y los valores declarados quedan en el vector y la procedencia. Los resúmenes densos siguen siendo sólo vistas.
- El restore ZIP repone el original byte a byte y conserva snapshots y documento del recibo en el propietario de destino. El restore JSON conserva la autoridad elegida y los dos niveles de evidencia de plato e ingredientes.
- Una equivalencia comprobada de piezas a gramos mantiene el tipo nominal y la etiqueta del original en la evidencia y escala el aporte una sola vez. No se requirieron cambios al escritor, a snapshots ni al formato de backup.
- La revisión distingue instancias de comida con la misma fecha y tipo. La proyección guarda esas rutas y orden en evidencia. El agrupamiento de la proyección legacy sigue organizado por fecha y tipo, como en el escritor vigente.

## QA

| Gate | Resultado |
| --- | --- |
| SQLite focal | 495 PASS. Dos pruebas de bloqueos se omitieron en SQLite y se ejecutaron en ambos perfiles MariaDB. Incluye 70 casos nuevos ejecutados y regresiones 1.0/2.1, de lotes 14/18/21/23 y de AI Energy Balance. |
| MariaDB 11.4.12, 0046, READ COMMITTED | 176 PASS, incluidos 72 casos de intercambio y 104 de compatibilidad 2.1. |
| MariaDB 11.4.12, 0046, REPEATABLE READ | 176 PASS con la misma cobertura. |
| Regresiones transaccionales de importación | 33 escenarios más carreras de edición/confirmación por perfil MariaDB, con comprobación de migraciones PASS. |
| Esquema y comprobaciones estáticas | Cinco fixtures del contrato con sus resultados esperados, paridad de las 30 claves/unidades y compilación del backend. Docker Compose analizado con variables ficticias, sin resolver archivos de entorno del servicio. |

La variante ficticia de 18 filas deja 17 calculables y una excepción con el valor declarado visible. El caso de plato con dos fuentes conserva ambas y sólo escala la autoridad seleccionada. No se ejecutaron pruebas de navegador de Fase C/D.

## Alcance pendiente

La preparación canónica activa en QA cubre consumos declarados. Planes, recetas y productos admiten análisis de fuente, pero permanecen pendientes de revisión para vincular identidades autorizadas y cumplir las reglas vigentes de esos destinos. Quedan para C la selección de destino, las decisiones sobre duplicados y solapamientos, el editor guiado y los controles para pegar/copiar/descargar. Los archivos rechazados se pueden corregir y volver a subir; el motor no crea una revisión vacía para conservar un rechazo. La validación con salidas independientes de múltiples IA y el flujo de navegador de producto pertenecen a C/D.
