# Energy Experience 2.0 C — cierre productivo

23-10-2026. [PR #24](https://github.com/Donbumo/health-tracker/pull/24) integrado por squash respetando Protect master, sin bypass. HEAD autorizado `e32daee801b60ebd23c24fcdf9b9d28badf100b8`; squash y checkouts GitHub/Windows/NAS `fcf901b903ab7e467444e6f9a5fe898624207efa`. Árbol idéntico al revisado; revisión publicada favorable y checks GitHub N/A.

## Identidad y preflight

- C activa: `sha256:7785e11d8623514089d986ff8b7d8f3ce0330e1b1ba5fea527a3cb21c0aec21d`. Python 3.12/linux-amd64, 532 archivos de app/schema/migraciones idénticos al squash, pip check PASS. Imagen guardada, checksum y recarga verificados; APP_VERSION contrastado con imagen/contenido.
- B recuperable: `sha256:d7e4dba4095cdbab45f3879a13c74857c301a37eec80acf2ce2409317ad3aa31`; su archivo y backups anteriores se comprobaron y preservaron.
- El build normal resolvió SQLAlchemy 2.1.6, Alembic 1.20.1 y pypdf 6.21.2 frente a 2.1.4/1.20.0/6.21.0 de B. Esa candidata **no se desplegó**. Se construyó C desde el runtime inmutable preservado de B, copiando únicamente los archivos aprobados; `pip freeze` idéntico. Sin cambios de dependencias en el repositorio.
- MariaDB saludable, todas las tablas InnoDB, espacio/memoria y permisos de storage comprobados. 0046, db check y Compose config PASS; catálogo activo 13.685, flags/secretos/puertos/montajes preservados. Sólo web recreado; mismo contenedor MariaDB. Gunicorn original `app:create_app`, sin módulo QA ni upgrade/seed/DDL/stamp/downgrade.

## Backup y recuperación

Nuevo backup consistente MariaDB/storage `energy-c-20261023T143521Z`, 283.712.756 bytes, con escritores detenidos y transacciones drenadas. Checksums verificados; restore en schema/storage independientes: mismas tablas/columnas/filas y metadata de archivos. Antes del cambio final el estado seguía coincidiendo con ese backup.

**2.026 archivos regulares** restaurados idénticos. Después del smoke, producción conserva exactamente esos archivos y no hay originales nuevos creados por las lecturas. Se contrastó un snapshot consistente de lectura con el algoritmo privado original antes de usarlo para reducir el tiempo de mantenimiento. Ningún hash de datos personales en informes/Git.

Si falla C, reponer imagen B compatible sobre DB/storage actuales. No restaurar un backup antiguo sobre escrituras posteriores ni ejecutar downgrade. El archivo confirmado tiene un commit independiente: puede quedar metadata `pending` y auditoría de importación fallida sin evento energético. Conciliar privadamente owner, original/hash/tamaño, ImportRun fallido y revisión canónica; revisar nuevamente antes de reintentar. **No borrar originales confirmados automáticamente.**

## Candidata: POST sólo en copia QA

Gunicorn real con dos workers, schema y storage restaurados independientes, secreto QA propio y usuario SQL limitado al clon. Se crearon dos cuentas ficticias únicamente ahí. Sonda separada, DNS/IP contrastado con el contenedor de la candidata, sin publicar puertos.

PASS mediante HTTP real:

- Cuatro etapas completas; preview/operaciones sin escrituras DB/storage, detectadas también mediante guard de DML en el proceso QA.
- CSRF obligatorio; propietario, bytes/nombre, etapa y estado ligados a firma. Manipulación, falta de confirmación y caducidad rechazadas antes de guardar.
- Original exacto con BOM/espacios; SHA/tamaño y descarga owner-only idénticos, sin cuerpos retenidos en informes.
- Replay sin evento/revisión extra; dos sesiones con revisión obsoleta 409; **dos confirmaciones simultáneas: 302/409 y un único evento**.
- Contradicción conservada pendiente; decisión por fuente, manual y vaciado distinto de cero. Valores originales de fuentes intactos y cuenta ajena 404.
- Fallo inyectado después del flush del escritor oficial: 409, ningún día/evento nuevo, original confirmado conservado. La instrumentación estuvo en un módulo QA externo a la imagen; no en la aplicación productiva.
- JSON 1.0 de **256 KiB exactos** aceptado en servidor y confirmado; 256 KiB + 1 rechazado. JSON 1.1 identificado y remitido al flujo estándar, sin aplanarlo.
- db check PASS en 0046. Sin migración nueva ni modificación de escritores, schemas, UUID móviles o Nutrition 2.1.

Al cerrar: Gunicorn QA detenido y privilegios DML revocados; queda SELECT sólo sobre el clon. Fixtures, originales confirmados y metadata fallida se conservan aislados para auditoría. No hubo cuenta QA ni confirmaciones sintéticas en producción.

## Smoke productivo y privacidad

HTTP/HTTPS con TLS y login real usuario/contraseña + CSRF. Sólo lecturas: `/energy`, `/energy/import`, **`/energy/review` de un día propio 200**, fuentes/historial B, gráficas/calendario A, tres rutas legacy y Nutrition/Gym/AI. Los cuatro pasos y las confirmaciones se ejercitaron completos en QA, sin POST energéticos sobre cuentas reales.

Canónico, procedencia, revisiones, UUID, eventos, tombstones y snapshots conservados: **todas las tablas/columnas/filas idénticas** tras el smoke. Observaciones, balance y medias/denominadores comparados con Nutrition/Daily Balance. Sin doble conteo.

Las páginas sensibles de C devolvieron `private, no-store`. El vhost HTTPS efectivo y los formatos del proxy no registran cuerpos, cookies, Authorization ni tokens de C; logging debug desactivado. Los logs normales conservan metadatos de ruta/estado/URI; originales y firmas de C viajan en POST, nunca en URLs. Configuración del proxy sin modificar. Marcadores ficticios de cuerpos/tokens no aparecieron en logs QA; cero nuevos ERROR/Traceback, SQL o HTTP 5xx productivos.

Cinco muestras HTTP secuenciales por ruta/período/protocolo; no carga concurrente ni percentiles. Medianas HTTPS: Energía 7/30/90 **40,6 / 56,2 / 73,1 ms**; entrada guiada **25,8 ms**, fuentes **24,8 ms**, historial **28,8 ms**. Máximo HTTPS observado en fuentes: **188,9 ms**. Revisión propia: GET 200 (no se informa como serie de cinco muestras). QA: revisión mediana 8,2 ms y máximo 9,8 ms.

Estabilidad observada: **127,4 s**, cero reinicios/errores/5xx. Ventana puntual, sin garantía de disponibilidad futura.

## Evidencia y continuación

[Cierre consolidado](../design/energy-experience-2-0-c/qa-production/closeout.json), [QA HTTP real](../design/energy-experience-2-0-c/qa-production/qa-http.json), [HTTP/HTTPS productivo](../design/energy-experience-2-0-c/qa-production/production-http.json), [privacidad del proxy](../design/energy-experience-2-0-c/qa-production/proxy-privacy.json) e [identidad](../design/energy-experience-2-0-c/qa-production/content-identity.json). Dumps, originales, credenciales y logs privados quedan fuera de Git.

C queda operativa antes de iniciar `feature/energy-experience-2-0-d`. D se prepara en rama/PR separado; sin merge/despliegue automático. PITR, smoke físico Android/iOS y Open Food Facts externo siguen pendientes separados.
