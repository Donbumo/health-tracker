# Privacidad de datos médicos

Los estudios y resultados pueden contener información médica sensible. Alpha 1.9 aplica aislamiento por el usuario efectivo del servidor y, en Android, por `accountScope + serverIdentity`.

## Datos y acceso

- Backend: consultas, archivos, imports, exports y auditoría filtran por `user_id` efectivo; nunca aceptan owner del cliente.
- Android: Room, cola y caché filtran por cuenta e identidad de servidor. Logout/revocación elimina esa cuenta; cambiar servidor no mezcla ni reutiliza tokens.
- Documentos: almacenamiento privado, nombre aleatorio, SHA-256, límites, descarga `no-store` y 404 para UUID ajeno.
- Room/MariaDB: no almacenan PDF, imagen o CSV completo; solo metadata y referencias privadas.

No se registran título/laboratorio/profesional, notas, nombres de archivo, valores, unidades, rangos, marcadores, contenido JSON/CSV, documentos, hashes completos, URI o rutas. Diagnóstico técnico permite tipo de operación, conteos, tamaño, estado, código, timestamp truncado e identificador/fingerprint corto.

Las notificaciones Alpha 1.8 permanecen genéricas y no incorporan resultados, estados ni nombres médicos. No se crean recordatorios automáticos por un valor fuera del rango reportado.

## Documentos, SAF y compartir

SAF evita acceso amplio al almacenamiento. La app solicita lectura solo para el documento elegido, intenta persistir el permiso y conserva una copia temporal privada para reintentar el upload. Si el acceso se pierde antes de copiar, el usuario debe seleccionar el archivo otra vez. Temporales y parciales se eliminan tras éxito, eliminación o cleanup de cuenta.

El FileProvider médico es no exportado. Compartir o abrir fuera de la app debe partir de una acción explícita y conceder lectura temporal al destino elegido; no existe share automático. No se abre contenido activo en WebView.

## Exportación y retención

La portabilidad incluye datos estructurados/metadata solo cuando se seleccionan las secciones correspondientes. Los documentos originales están desactivados por defecto y requieren el opt-in separado `include_medical_attachments`. El package no demuestra autenticidad, no está cifrado por el formato y debe guardarse en un lugar seguro.

Archivar conserva historial. Borrar documento elimina archivo y metadata de ese documento, pero no el estudio. Borrar definitivamente un estudio exige confirmación e impacto aceptado y elimina solo su agregado. No hay borrado masivo ni retención automática en Alpha 1.9.

## Límites conocidos

No hay antivirus, OCR, IA, FHIR, interpretación de PDF ni cifrado extremo a extremo del package portable. La detección de tipo y las listas permitidas reducen superficie, pero no prueban que un archivo sea benigno ni auténtico. Un visor externo queda sujeto a la seguridad de la app elegida por el usuario.
