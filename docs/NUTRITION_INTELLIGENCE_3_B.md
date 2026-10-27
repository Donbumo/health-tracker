# Nutrition Intelligence 3.0 B — candidatos revisables

Implementación para revisión, desde A productiva
`2f0275ba6c86b14a797a7671b43b6257282886ac`, en
`codex/nutrition-intelligence-3-0-enrichment`. **Sin merge ni despliegue de B.**

## Alcance implementado

Desde el detalle de un alimento personal, “Revisar nutrientes faltantes con
candidatos” abre una búsqueda local de identidades publicadas. Cada propuesta
conserva fuente, identidad, preparación, marca cuando existe, base, unidad y
revisión de catálogo/alimento. El orden es el buscador existente: no establece
equivalencia ni recomienda una dieta. Ningún candidato queda seleccionado por defecto.

La cantidad para comparar se introduce explícitamente. `ingredient` reutiliza
Decimal y las reglas de g/ml: sin densidad no se inventan equivalencias. La tabla
contrasta la definición personal escalada con una estimación orientativa **del
candidato**. Known cero, unknown, trace y below_limit permanecen distintos. Los
valores publicados no se trasplantan al alimento personal ni a un día histórico.
“Faltante” aquí es ausencia/unknown; las trazas y límites ya tienen evidencia y
no se presentan como campos vacíos que haya que sustituir.

Una casilla obligatoria confirma que se eligió la identidad del alimento publicado
para otro borrador. El POST verifica CSRF, owner, firma y vigencia de 30 minutos,
definición original, revisión de fuente, cantidad y fecha. Si algo cambia, exige
revisión nueva. `create_draft` es el único servicio de escritura invocado: el
resultado sigue pendiente, sin ingredientes aceptados y sin consumo. Aceptar
ingrediente y confirmar consumo continúan en el flujo oficial existente.

La definición personal nunca se edita, completa, sustituye o incrementa por esta
acción. Sus revisiones anteriores y los snapshots de recetas/consumos permanecen
intactos. Elegir el candidato significa registrar **otro alimento publicado**;
no afirmar que su composición es la del alimento original.

## Autoridad y límites deliberados

| Estado de revisión | Tratamiento en B |
| --- | --- |
| Propuesta | Candidato de búsqueda local, sin autoridad sobre el original |
| Estimación | Comparación orientativa fuera del vector canónico original |
| Fuente publicada | Identidad/revisión/base de ese candidato, sin equivalencia automática |
| Declaración personal | Se muestra y conserva; no se modifica ni se crea una nueva por inferencia |
| Consumo confirmado | Fuera de esta pantalla; exige el flujo oficial posterior |

No hay llamada a un modelo IA, red externa, nuevo proveedor, nuevos tools de AI
o permiso de escritura para un modelo. B entrega el flujo local verificable sobre
el que podría añadirse una explicación IA sólo de lectura tras otra revisión.
No implementa reconocimiento fotográfico, recomendaciones personalizadas,
diagnóstico ni porcentajes de ingesta recomendada.

No persiste propuestas/estimaciones ni escribe revisiones derivadas de definiciones
personales. La opción de crear una definición enriquecida y el archivo completo
de revisiones personales **no consumidas** siguen fuera de esta implementación;
requieren el contrato/revisión descritos en el [diseño](NUTRITION_INTELLIGENCE_3_B_DESIGN.md).
Se preserva lo existente sin simular que ya existe ese archivo de revisiones.

El recibo en sesión reutiliza el borrador en reenvíos secuenciales de una revisión,
con hasta ocho referencias públicas. No es una garantía exactly-once entre sesiones
o peticiones simultáneas: podrían existir borradores pendientes distintos; esta
pantalla jamás confirma consumos por sí sola. No se añadió DDL para convertir
propuestas en una segunda persistencia canónica.

## Privacidad

La revisión requiere login y filtra siempre por el owner efectivo. Un user_id
cliente no concede autoridad; los candidatos personales ajenos no son elegibles.
Firmas no se publican en evidencias ni logs. La revisión contiene sólo los hashes
de definiciones y selección, no un vector propuesto por el cliente.

Nutrition añade en B `Cache-Control: private, no-store` a sus respuestas, incluidos
errores owner-only. Es un endurecimiento respecto de A, detectado durante su gate
operativo; no se afirma que ya esté desplegado. El service worker sigue limitado
a assets estáticos. Sin cambios a schemas, migraciones, tablas, dependencias,
contratos móviles o cálculos del dashboard/Coach.

## Verificación

- **8 pruebas B** aprobadas: propuestas sólo públicas, fuentes/revisiones, desconocidos,
  cero y calificaciones, cantidades inválidas, incompatibilidad de volumen, firma,
  caducidad, CSRF, flags, dos propietarios, revisión personal/fuente obsoleta,
  payload cliente ignorado, GET sin DML y no-store. Selección sólo prepara borrador;
  producto, receta y snapshot consumido permanecen idénticos.
- **83 pruebas dirigidas** de B/A, Nutrition Intelligence, revisión de productos y
  FoodCatalog aprobadas antes de añadir el último caso HTTP owner-only; incluye
  siete de las ocho pruebas B. No se suman como suites disjuntas.
- [MariaDB QA 0046](../design/nutrition-intelligence-3-b/qa/mariadb.json): runtime
  inmutable de A con código B montado en sólo lectura, schema LOCAL aislado y fixtures
  ficticias. db check sin operaciones nuevas; GET autenticado sin DML/DDL, owner,
  definición intacta y sólo borrador oficial pendiente PASS. Sin upgrade/stamp.
- [Flask/Edge QA](../design/nutrition-intelligence-3-b/qa/ui-report.json): 36 combinaciones
  de candidatos/comparación/vacío, light/dark, 360/390/430/768/1024/1366. Sin overflow
  de página, errores JavaScript o requests externos; confirmación no preseleccionada.
  Flujo real al borrador pendiente y definición original r1 PASS.

Capturas: [comparación escritorio](../design/nutrition-intelligence-3-b/qa/comparison-light-1366.png),
[comparación móvil oscuro](../design/nutrition-intelligence-3-b/qa/comparison-dark-390.png),
[candidatos móvil claro](../design/nutrition-intelligence-3-b/qa/candidates-light-390.png).
Las tablas se desplazan horizontalmente; la página conserva navegación y enlace
directo a la decisión. Esta QA focal no certifica WCAG.

Reproducción SQLite/UI: `scripts/nutrition/qa_equivalents.py` y
`scripts/nutrition/ui_qa_equivalents.cjs`, con dependencias QA ya instaladas. La
comprobación MariaDB sólo admite el esquema QA literal y usa configuración aislada;
nunca se ejecuta contra cuentas personales o storage productivo.
