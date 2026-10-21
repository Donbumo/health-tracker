# Energy Experience 2.0 B — cierre productivo

20-10-2026. PR #23 integrado mediante squash, sin bypass de «Protect master». HEAD aprobado `930eaecaf2590a3caf9f1097a589645a6dd5d89f`; squash/checkouts GitHub, Windows y NAS `6fdd594151f5ede12997b5447e28b10d4e8a901f`. Árbol idéntico al revisado; checks GitHub N/A.

## Runtime y recuperación

- Imagen activa: `sha256:d7e4dba4095cdbab45f3879a13c74857c301a37eec80acf2ce2409317ad3aa31`. Python 3.12, linux/amd64. 528 archivos Git idénticos; pip check y comparación completa de dependencias con A PASS. Imagen archivada, checksum comprobado y recarga verificada.
- Imagen A preservada: `sha256:d0322c07899e52830769a25b192daa42d2582aa77cd7f2762adc7b32b3cb751a`; backups e imágenes anteriores conservados.
- Nuevo backup consistente DB/storage `energy-b-20261020T233932Z`, checksum PASS. Restore en schema/storage independientes: todas las tablas/columnas/filas iguales y **2.022 archivos regulares idénticos**. Antes del cambio final, el estado productivo seguía coincidiendo con ese backup.
- Sólo web recreado con Compose existente y Gunicorn directo; sin upgrade/seed, DDL ni migraciones. Mismo contenedor MariaDB, Alembic `20261018_0046`, db check PASS, catálogo 13.685, flags/secretos/montajes/puertos preservados.

## Rendimiento: volumen real y escenario complementario separados

Gunicorn real B sobre restore aislado y cuenta SQL con **SELECT sólo en QA**, sin privilegios productivos. Storage clonado RO. Sondas en contenedor distinto, DNS/IP del destino contrastados con inspect, imagen verificada.

El estado real contiene cinco eventos auditables: no permite certificar páginas intermedias distintas. Se consultó su propietario mediante una sesión firmada emitida sólo para QA, sin cambiar contraseñas ni datos originales. Login real usuario/contraseña se probó además con la cuenta de smoke. Se añadió **otro propietario ficticio**, exclusivamente al clon, con 10.000 eventos, cinco orígenes, cuatro operaciones y 400 páginas. Ninguna fixture productiva.

Cinco muestras HTTP secuenciales por caso: sin filtros, origen, fechas, operación, combinados, primera/intermedia/última y sin coincidencias. Máximo con datos reales **21,6 ms**; máximo con 10.000 sintéticos **286,7 ms**. Memoria del Gunicorn QA: 204,9 → 222,7 MiB. Sin carga concurrente ni afirmación de capacidad ilimitada.

EXPLAIN confirma índice owner/date en consultas aplicables. JSON de origen, COUNT, DISTINCT y ordenación pueden escanear/usar temporales/filesort. Es una limitación registrada; no se añadieron índices ni migraciones. El volumen real y el escenario complementario superaron el gate operativo de 1 s por consulta HTTP.

Comparación de la misma cuenta de login, cinco muestras por período:

| Período | A productiva mediana ms | B clon mediana ms | B productiva mediana ms |
| --- | --- | --- | --- |
| 7 | 27,1 | 26,9 | 26,9 |
| 30 | 33,6 | 32,1 | 32,0 |
| 90 | 53,4 | 55,5 | 55,9 |

## Smoke e integridad

HTTP/HTTPS autenticado con usuario/contraseña y CSRF: `/energy`, `/energy/sources`, `/energy/history`, filtros y navegación, legacy, Nutrition, Gym y AI PASS; TLS válido y healthz. Cinco muestras por caso/protocolo. Historial HTTPS: máximo **47,2 ms**. La cuenta productiva de smoke no tiene eventos auditables: páginas pobladas, decisiones, retiradas y originales se verificaron sobre QA y evidencia focal, sin crear datos en cuentas reales ni suplantar sesiones productivas.

El original de un evento real restaurado pasó owner/ref/hash/tamaño/cabeceras mediante HTTP QA; bytes descartados, ningún contenido/nombre/hash personal en informes. Se conserva la regresión Linux de 29 tests de B (token ajeno/caducado, CSRF, hash/tamaño, traversal, symlink y swap), con código y dependencias idénticos a la imagen desplegada. No se hicieron pruebas adversariales en producción.

Después del HTTP, **todas las tablas/columnas/filas productivas idénticas** al baseline congelado. Canónico, UUID, eventos, revisiones, tombstones y snapshots intactos. Reglas de balance, export/restore y contratos móviles no cambiaron. Cero ERROR/Traceback, 5xx o reinicios en **72,7 s** observados; ventana puntual, sin garantía futura. QA Gunicorn detenido al cerrar; clon y respaldos preservados.

Incidencias del lanzador, sin cambios a Flask: referencia de archivo de imagen preservada corregida antes del build; sesión QA de otro owner requirió conservar CSRF. A se repuso mientras se amplió la prueba de rendimiento. No hubo restore productivo ni downgrade.

## Evidencia y continuación

[Cierre consolidado](../design/energy-experience-2-0-b/qa-production/closeout.json), [rendimiento](../design/energy-experience-2-0-b/qa-production/performance.json), [EXPLAIN/datos reales](../design/energy-experience-2-0-b/qa-production/qa-largest-http.json), [10.000 sintéticos](../design/energy-experience-2-0-b/qa-production/qa-load-http.json), [HTTP/HTTPS productivo](../design/energy-experience-2-0-b/qa-production/production-http.json). Son resultados saneados; dumps, credenciales, logs completos y hashes privados quedan fuera de Git.

B operativa. C se inicia después en rama/PR independiente, sin merge/despliegue autorizado. D conserva fechas extremas y accesibilidad integral. Smoke físico Android/iOS y OFF externo continúan separados.
