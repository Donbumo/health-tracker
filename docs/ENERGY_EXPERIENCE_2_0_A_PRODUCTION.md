# Energy Experience 2.0 A — operativa en producción

Cierre: **20-10-2026**. Runtime nuevo activo y smoke autenticado completo PASS. [Evidencia saneada de cierre](../design/energy-experience-2-0/qa-production-resume/closeout.json), [HTTP QA real](../design/energy-experience-2-0/qa-production-resume/qa-http.json) y [visual sobre fixtures](../design/energy-experience-2-0/qa-production-resume/report.json).

## Identidad, sonda y recuperación

- Código autorizado/checkout GitHub, Windows y NAS: `9624142901c191ebc5dd47f333a42f5096e9065e`, squash del PR #22 ya integrado. No se repitió el merge ni se cambió Flask.
- Imagen **realmente activa**: `sha256:d0322c07899e52830769a25b192daa42d2582aa77cd7f2762adc7b32b3cb751a`. Anterior preservada: `sha256:b513331ea4e1fba1ca1549f4c5830d49a4be3ecddfbac4cb98ac26fde87e73c7`, código `9e2f2dc7fea728bfec3c8abf1aed6bc7bb428852`.
- Checksum del archivo de imagen candidata verificado; **525 archivos** de aplicación, schemas y migraciones idénticos al SHA aprobado. Docker inspect del destino coincide con la candidata y se comprobó la ruta `/energy`, su servicio y plantilla. APP_VERSION se contrastó con imagen y contenido, no se usó como única prueba.
- Sonda en contenedor efímero separado: DNS `web` resuelve a la IP Docker del web activo en la red Compose compartida existente, puerto 8000. Se registró la identidad del origen de la sonda, se contrastó su destino con Docker inspect y se ejercitó login real con CSRF y `/energy`. La QA usa otro Gunicorn identificado y otra sonda, con DNS distinto explícito y sin publicar puertos.
- Se detectaron cambios desde el backup anterior; se preservó el estado vigente y se creó un punto de recuperación NUEVO: `energy-a-20261020T162301Z` (identificador UTC). Copia consistente MariaDB/storage, checksums y restore aislado PASS. Backups e imágenes anteriores conservados; ningún restore sobre producción.
- Candidata validada con **Gunicorn real**, schema y storage restaurados independientes; fixtures sintéticas añadidas sólo al clon. Usuario QA limitado a ese schema y, antes del HTTP, sólo SELECT. Sin autoridad de escritura sobre producción.
- Se recreó únicamente web con el Compose existente. MariaDB, montajes, puertos, secretos y flags preservados. Arranque Gunicorn directo, sin `flask db upgrade` ni `seed-admin`. Alembic **0046**, `db check` y `pip check` PASS; ninguna migración ejecutada. Catálogo activo: 13.685 alimentos.

## Smoke y rendimiento

- Login autenticado y `/energy` **HTTP/HTTPS 200**, TLS validado; 7/30/90 con SVG, tablas, calendario, métricas y enlaces legacy. Nutrition 2.1, Gym y AI PASS. Parámetro user_id ajeno ignorado y lectura owner-only.
- Observaciones, balances, medias y denominadores idénticos a Nutrition/Daily Balance. Consulta sin DML; QA SELECT-only y todas las tablas/columnas/filas productivas idénticas al baseline congelado después del smoke. UUID, revisiones, eventos, tombstones y snapshots conservados.
- Estados cero/parcial/conflicto/retirada/eliminado/hoy vacío/último y fuentes complementarias/resueltas probados con fixtures QA. **36/36** combinaciones visuales y **14 capturas reales** de Gunicorn QA, seis anchos × dos temas × tres períodos. Sin capturas ni valores personales en evidencias.
- Estabilidad observada tras activación: **102.1 segundos**, cero reinicios, cero ERROR/Traceback y cero HTTP 5xx nuevos. Es una ventana puntual, no una garantía de disponibilidad futura.

Latencias HTTP reales: **5 muestras secuenciales por período y protocolo**, sobre la cuenta autorizada en lectura, desde la sonda en el NAS. Incluyen lectura completa de HTML; sin carga concurrente. Muestras individuales en JSON. No se calculan percentiles.

| Período | HTTP mediana / máximo ms | HTTPS mediana / máximo ms |
| --- | --- | --- |
| 7 | 25.4 / 400.2 | 53.6 / 55.6 |
| 30 | 34.9 / 46.8 | 63.3 / 70.6 |
| 90 | 52.9 / 54.6 | 68.7 / 76.3 |

No se repitieron las suites completas aprobadas de A: no hubo cambios de aplicación. El lanzador QA requirió explicitar PYTHONPATH para ejecutar el script externo; se corrigió únicamente el lanzador, antes de validar Gunicorn.

## Continuación

A queda cerrada y permite iniciar `feature/energy-experience-2-0-b` desde master para fuentes, eventos, filtros, paginación y originales protegidos, con su propio PR. B no se fusiona ni despliega sin revisión. Para **D** se mantienen la navegación en fechas límite y la auditoría integral de accesibilidad. Smoke físico Android/iOS y prueba externa real de OFF siguen separados.

---

## Antecedente: intento detenido del 19-10-2026

El siguiente diagnóstico se conserva como historial y queda sustituido por el cierre anterior.

# Energy Experience 2.0 A — integración y despliegue detenido

Fecha: 19-10-2026. **A no está certificado en producción. B no se ha iniciado.** Se cumplió la condición de parada ante un gate fallido; la imagen estable compatible con 0046 está nuevamente en servicio.

## Estado verificable

| Elemento | Resultado |
| --- | --- |
| PR integrado | [#22](https://github.com/Donbumo/health-tracker/pull/22), squash |
| HEAD autorizado revisado | `740966af7ef512805026be220ae14bba4fd48032` |
| Squash/master GitHub, Windows y checkout NAS | `9624142901c191ebc5dd47f333a42f5096e9065e` |
| Imagen actualmente en servicio | Versión estable `9e2f2dc7fea728bfec3c8abf1aed6bc7bb428852` |
| Alembic | `20261018_0046`; sin upgrade, downgrade ni stamp |
| MariaDB y datos | Mismo contenedor; todas las tablas/columnas/filas idénticas a la línea base congelada |
| Servicio estable restaurado | HTTP/HTTPS con TLS: healthz 200; cero reinicios y cero ERROR/Traceback nuevos en stdout/stderr combinados |
| Flags y configuración | Conservados; no cambios de contratos móviles |

Evidencia saneada: [deployment-diagnostic.json](../design/energy-experience-2-0/qa-production/deployment-diagnostic.json). Dumps, storage, identidades de cuentas, hashes de filas, credenciales y logs completos permanecen privados fuera de Git.

## Gates superados

1. PR abierto con HEAD exacto, base master vigente y sin conflictos. Ruleset activo «Protect master»: squash permitido, cero aprobaciones obligatorias, sin bypass; reglas sin cambios. Checks/workflows GitHub N/A, ninguno registrado.
2. Squash autorizado y fast-forward de Windows/NAS. Árbol del squash idéntico al HEAD revisado. El informe operativo local previo se preservó sin versionar.
3. Preflight: runtime estable previo, schema 0046, tablas InnoDB, espacio disponible y escritores identificados. Backups anteriores y archivo de imagen compatible anterior verificados por checksum.
4. Build aprobado Python 3.12/linux-amd64, imagen nueva archivada y recargada; imagen anterior preservada. Ninguna dependencia nueva ni modificación funcional durante la operación.
5. Mantenimiento 503 con escritores detenidos y cero transacciones; backup nuevo consistente MariaDB/storage con checksums comprobados, sin sobrescribir backups anteriores.
6. Restore aislado en schema vacío y storage independiente. Todas las tablas, columnas y filas coinciden; **2022 archivos regulares** restaurados idénticos por SHA256. Sin restore sobre producción.
7. Imagen nueva contra la copia: `db check` sin operaciones pendientes; 0046, catálogo activo de 13.685 y flags conservados. Consulta owner-only 7/30/90, paridad exacta de observaciones/medias/denominadores con Nutrition y de balances con Daily Balance; cero escrituras. Calendario por mes/año y zona efectiva verificados.
8. Sustitución del web: imagen nueva efectiva, mismo contenedor MariaDB, puertos y entorno salvo APP_VERSION, y estado completo de las tablas idéntico a la línea base.

Rendimiento de servicio en el NAS sobre la copia del estado real: 7 días **37.0 ms**, 30 días **14.4 ms**, 90 días **21.2 ms**. Son muestras puntuales de consulta, no latencias HTTP productivas certificadas, carga concurrente ni percentiles.

## Gate fallido y diagnóstico

La sonda posterior corría mediante `compose run` en un contenedor efímero de validación. Intentó abrir `http://127.0.0.1:8000/healthz`: ese loopback pertenece al contenedor efímero, donde no se había iniciado servidor HTTP. El resultado fue conexión rechazada antes de completar el smoke HTTP/HTTPS de la aplicación nueva.

El error es de la sonda operativa. **No demuestra una avería de `/energy`, pero tampoco certifica su smoke productivo.** No se modificó el código aprobado para sortearlo.

Se detuvo el procedimiento y se repuso la imagen estable 0046 sobre la DB/storage actuales. No se restauraron datos ni se ejecutó downgrade. La comparación posterior del estado completo contra la línea base confirmó que la operación no alteró historial, UUID, revisiones, eventos, snapshots ni otras tablas.

La sonda corregida está preparada fuera de Git y conserva el original fallido. Cambia únicamente el destino HTTP a `http://web:8000` desde el contenedor efímero. Su conectividad HTTP y HTTPS con TLS fue comprobada con healthz 200, manteniendo la imagen estable en servicio. **No se repitió el despliegue ni el gate completo de A.**

## Pendiente para cerrar A y comenzar B

- Reanudar controladamente el despliegue del mismo código aprobado con la sonda corregida; repetir preflight y verificar nuevamente vigencia/consistencia de backups y estado antes de sustituir el web.
- Completar HTTP/HTTPS autenticado de `/energy` en 7/30/90, rendimiento HTTP real, owner-only, paridad, calendario, assets de temas/gráficas y enlaces legacy. La QA visual previa sobre fixtures sigue siendo evidencia separada; no se tomaron capturas de datos personales.
- Sólo tras el cierre productivo documentado de A, crear rama y PR de B para fuentes/procedencia, eventos, filtros, paginación y originales protegidos. **No hay rama ni PR de B en esta ejecución.** No integrar/desplegar B sin revisión.

## Registrado para D

- Corregir navegación en límites de fecha permitidos: día/mes anteriores a 1900 y posteriores al año 9998 generan destinos fuera del intervalo aceptado. Desactivar/normalizar esos enlaces de forma coherente; probar ambos extremos sin alterar fechas históricas. No corregido dentro de A aprobada.
- Auditoría integral de accesibilidad: lectores de pantalla, navegación/foco completo, estados, tablas y gráficas, contraste y objetivos táctiles en toda la experiencia. Las verificaciones focales de A no equivalen a esa auditoría.

Smoke físico Android/iOS y prueba externa real de Open Food Facts continúan separados. No se realizaron escrituras de dominio en cuentas reales durante esta operación.
