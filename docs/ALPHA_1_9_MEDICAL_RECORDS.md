# Alpha 1.9 — estudios médicos y laboratorio

Alpha 1.9 añade registros médicos privados, resultados de laboratorio estructurados y documentos originales. El recorrido Android mantiene las cinco pestañas y sitúa **Salud → Estudios médicos** como pantalla anidada. La app conserva lo escrito offline y sincroniza después mediante endpoints Bearer agregados; no añade estas entidades al push genérico de Mobile Sync.

## Alcance y límites clínicos

`MedicalStudy` admite laboratorio, imagen, documento clínico, receta, vacunación y otro. Solo `laboratory` admite `LabPanel` y `LabResult` estructurados en esta versión. Los estados son `draft`, `complete` y `archived`; archivar es la acción normal y la eliminación definitiva exige confirmación e impacto aceptado.

La función es documental. No hay OCR, IA, diagnóstico, pronóstico, score, objetivo recomendado ni tratamiento. Los estados `source_status` se conservan como dato del informe. `derived_range_status` es únicamente una comparación mecánica contra límites presentes en ese mismo resultado y se marca `not_computable` cuando no se cumplen sus precondiciones. La UI muestra “Según el rango incluido en este informe” y no presenta los colores como interpretación clínica.

## Modelo y procedencia

- `MedicalStudy` conserva UUID público, owner, tipo, título, institución/profesional opcionales, fechas, timezone informativa, notas, estado, fuente, revisión y timestamps.
- `MedicalStudySource` registra procedencia limitada sin copiar contenido clínico a auditoría.
- `LabPanel` ordena grupos del informe; `LabResult` conserva siempre valor y unidad originales, tipo, comparador, límites/texto de referencia, status de fuente, método, specimen, notas y revisión.
- `LabResultRevision` conserva cada corrección manual.
- `MedicalDocument` enlaza metadata a `UploadedFile`; el binario nunca vive en MariaDB ni Room.
- `MedicalDuplicateCandidate` diferencia duplicado exacto de documento/estructura, probable, posible y distinto. Solo la exactitud puede resolverse automáticamente; lo ambiguo se conserva.

Los value types son `numeric`, `text`, `categorical`, `positive_negative`, `detected_not_detected` y `unknown`. Los comparadores son `equal`, `less_than`, `less_or_equal`, `greater_than`, `greater_or_equal`, `approximate` y `none`. `NaN` e infinitos se rechazan.

## Unidades, catálogo e historial

La allowlist `medical-units-v1` solo incluye escalas dimensionales exactas de masa (`kg/g/mg`), volumen (`L/mL`), concentración simple (`g/L` y `mg/L`) y temperatura idéntica en °C. Cada regla publica unidad fuente/canónica, factor, precisión y versión. No hay conversiones molares, dependientes del analito, método, población o fórmula clínica.

El catálogo técnico cubre claves frecuentes para autocompletado y agrupación, sin rangos ni interpretación, y admite marcadores personalizados. El historial ofrece 30/90/180 días, un año y todo, con filtros por laboratorio, unidad, método, fuente y tipo de estudio. Solo calcula cambio absoluto/porcentual y traza una serie cuando clave, tipo, unidad y método son compatibles; de otro modo declara “Unidades o métodos no comparables”.

## API y storage

Las rutas `/api/v1/mobile/medical-*`, `/lab-results`, `/lab-markers` y `/lab-history` derivan siempre el owner del Bearer token. UUID ajeno responde 404. Escrituras usan `Idempotency-Key`; PATCH/DELETE usan revisión base. Las consultas tienen paginación/filtros acotados y loaders agregados para evitar N+1.

PDF, JPEG, PNG, JSON médico interno y CSV controlado pasan detección de contenido, comparación MIME/extensión, nombre sanitizado, límites de archivo/cuenta y SHA-256. HTML, SVG/XML activo, ZIP arbitrario y PDF cifrado se rechazan. Storage reutiliza `UploadedFile` con nombre aleatorio bajo el root existente y descarga owner-only con `Content-Disposition` seguro y `no-store`. No hay antivirus integrado: la app valida estructura/tipo, nunca ejecuta ni renderiza contenido activo y recomienda visor externo seguro.

## Android y offline

Room 9 añade nueve tablas médicas, todas con `accountScope + serverIdentity`. La migración 8→9 es aditiva y la cadena explícita 1→9 no usa fallback destructivo. Los binarios permanecen fuera de SQLite.

Crear/editar/finalizar/archivar estudio, añadir/corregir/eliminar resultado y preparar/eliminar documento emiten Room antes de red. `medical_operations` conserva payload mínimo, hash e idempotency key. Create→update y updates consecutivos consolidan el estado final; create de resultado→delete descarta la operación. WorkManager reanuda la cola. Logout limpia filas y temporales de la cuenta; cambiar servidor conserva scopes anteriores aislados.

SAF limita la selección a la allowlist, intenta conservar permiso URI y copia temporalmente a almacenamiento privado sin backup para un upload reiniciable. Se calcula SHA final y el temporal se elimina al completar, borrar o cerrar la cuenta. Compartir exige tocar la acción explícita: descarga o copia a caché privada, vuelve a verificar tamaño/SHA y concede una URI temporal de lectura mediante el FileProvider `.medical-documents`, que no está exportado.

## Portabilidad

`health-tracker-portable-v1` añade `medical_studies`, `lab_panels`, `lab_results` y `medical_documents_metadata`. La metadata estructurada puede exportarse sin binarios. Los originales requieren `include_medical_attachments=true`, que añade `attachments` y las dependencias médicas. Nunca se exportan rutas, URIs locales, logs, auditorías, tokens o IDs internos.

Inspect/dry-run precede a la importación. UUIDs globalmente ocupados se remapean; referencias padre se reconstruyen; la aplicación es transaccional. Sin binario, el documento queda `metadata_only`; con attachment verificado queda `available`. Una repetición del mismo package queda idempotente y no duplica recursos.

## Retención y QA pendiente

Un documento puede borrarse sin borrar resultados; un estudio puede permanecer sin documento. La eliminación definitiva del estudio borra únicamente su agregado y limpia archivos médicos sin afectar cuerpo, nutrición, entrenamiento u otros dominios. Auditoría solo conserva acción, tipo, conteos, estado y revisión.

Siguen pendientes QA físico/manual en AVD o teléfono aislado: process death con URI persistida/perdida, modo avión→reconexión, visor/compartir externo, upload interrumpido, TalkBack, rotación, fuente grande, temas y anchos 320/360/411/600 dp. No se ejecuta `connectedDebugAndroidTest` ni se instala APK durante este gate.

El gate automatizado final pasó con backend local 687/7 y Docker/MariaDB 693/1. El E2E MariaDB cubre documento ficticio y hash, revisión, historial, exportación metadata-only, replay sin duplicados, attachment opt-in owner-only y rollback. Android pasó lint, 157 JVM dos veces, APK y compilación de instrumentadas; no constituye QA físico.
