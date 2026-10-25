# Energy Experience 2.0 — cierre productivo A+B+C+D

24-10-2026. Despliegue de D autorizado expresamente después de que el usuario fusionó y verificó [PR #25](https://github.com/Donbumo/health-tracker/pull/25). **Entrega funcional A+B+C+D operativa en producción.** No se repitió merge ni se ejecutaron suites generales, Narrador, axe, matrices visuales o zoom.

## Código e imagen

| Control | Resultado |
| --- | --- |
| GitHub master / Windows master / NAS master | `38c6085565f49f560c9c4a1fefc18356bd1e3000` |
| Imagen D activa | `sha256:9ed11ee13feb5ac4e2db7e5c46ac2c2fc0e40d6575d927b19975d55f9a22c8d6` |
| Imagen C recuperable, preservada | `sha256:7785e11d8623514089d986ff8b7d8f3ce0330e1b1ba5fea527a3cb21c0aec21d` |
| Runtime | Python 3.12, linux/amd64; dependencias idénticas a C, `pip check` PASS |
| Identidad de contenido | 534 archivos de app/schema/migraciones idénticos al master autorizado |
| Imagen conservada | Export, checksum y recarga verificados; revisión OCI contrastada |
| Alembic | `20261018_0046`; `db check` PASS, sin migraciones nuevas |

Se construyó desde el runtime inmutable aprobado de C y los archivos del nuevo master. No se resolvieron paquetes nuevos ni se modificaron requirements, Dockerfile productivo, schemas o migraciones. El arranque efectivo sigue siendo Gunicorn `app:create_app()`; no ejecuta upgrade, seed, downgrade ni un módulo QA.

Windows y NAS se sincronizaron por fast-forward seguro. El informe local anterior del issue #18 quedó sin versionar y sin modificar. La propuesta siguiente parte de este mismo SHA en `codex/unified-health-summary`; no cambia la revisión desplegada.

## Backup y recuperación

Backup consistente nuevo **`energy-d-20261024T201630Z`**, **283.741.986 bytes** de DB/storage. Escritores detenidos y drenados, respuesta temporal 503 con Retry-After, cero transacciones activas. Se conservaron imagen C y cuatro conjuntos de backup anteriores; checksum del archivo de imagen C y su backup comprobados.

El dump nuevo y sus archivos de almacenamiento pasaron checksum. Se restauraron en schema y storage independientes: **todas las tablas, columnas, índices y filas idénticos**; **2.026 archivos regulares idénticos byte a byte**. La candidata pasó `db check` sobre ese clon mediante una cuenta limitada a SELECT. No se crearon cuentas ni consumos QA en producción. El clon y los originales de recuperación permanecen privados en NAS; no se copiaron dumps ni archivos personales a Windows/Git.

Antes de activar D se volvió a drenar C y se comprobó que el estado seguía coincidiendo con el backup recién verificado. Después del smoke, DB y archivos continuaban idénticos. Estas comprobaciones describen la ventana de despliegue; no prohíben escrituras legítimas posteriores.

Si falla un control crítico, recuperar sólo web con la imagen C compatible y DB/storage **actuales**. No usar downgrade ni restaurar un backup antiguo sobre escrituras recientes. Se conserva el estado y los backups para diagnóstico.

## Despliegue y smoke mínimo

Únicamente web se recreó mediante el proyecto Compose principal y su override operativo. Se verificaron ID de la imagen activa, revisión de la aplicación, mismo contenedor/volumen MariaDB, mismos mounts, puertos, secretos y flags. `healthz` 200.

Una petición por ruta y protocolo, autenticación real con usuario/contraseña y CSRF, cookies sólo en memoria:

| Ruta funcional | HTTP interno | HTTPS/TLS |
| --- | --- | --- |
| healthz | 200 | 200 |
| A · Energía, calendario y gráficas | 200 | 200 |
| B · Fuentes / historial | 200 / 200 | 200 / 200 |
| C · Importación / revisión de un día propio existente | 200 / 200 | 200 / 200 |
| Nutrition 2.1 | 200 | 200 |
| Tres entradas legacy de energía | 200 | 200 |

Sólo GET de dominio; los únicos POST fueron los de login. Cero fixtures y cero escrituras de dominio desde el smoke. Las respuestas sensibles conservaron `private, no-store`. No se guardaron cuerpos, cookies, credenciales ni valores personales en la evidencia. La comprobación operativa final de las 14:38:53 de México volvió a confirmar healthz 200, D activa, MariaDB saludable, mismo volumen, cero reinicios/errores y 314,8 GiB libres; sin repetir el smoke autenticado ni comparar contra escrituras legítimas posteriores.

Flags efectivos conservados: Nutrition Intelligence **true**, lookup externo **false**, AI **true**. Catálogo activo: **13.685 alimentos**. Cero nuevos ERROR/Traceback/HTTP 5xx y cero reinicios durante **110 segundos** observados; no es una garantía de disponibilidad futura ni un benchmark de carga.

## Incidencia operativa resuelta

El primer comprobador privado de la candidata omitía `PYTHONPATH=/app` y no pudo importar la aplicación. El control recuperó automáticamente C, saludable, sobre DB/storage actuales. No fue un cambio del producto ni se restauraron datos. Se corrigió exclusivamente el comprobador privado y se repitió la verificación del clon; la comparación con el backup nuevo volvió a pasar antes de activar D. La imagen D aprobada no cambió por esta corrección del harness.

## Accesibilidad: deuda conocida aceptada para este despliegue

- Zoom nativo 200 % no corroborado técnicamente. Sin otra ronda manual.
- WCAG 2.2.1: falta extensión explícita del TTL de 15 minutos. Las firmas y la seguridad actuales permanecen intactas; [propuesta de mejora](ENERGY_EXPERIENCE_2_0_D_ASSISTED_CLOSEOUT.md#propuesta-de-tiempo-que-requiere-revisión).
- No se afirma certificación WCAG completa.

Estos pendientes dejaron de bloquear **este despliegue** por autorización explícita del 24-10-2026. Los resultados históricos de pruebas y su alcance no se reescriben como PASS retroactivos.

## Evidencia y siguiente avance

[Cierre verificable agregado](../design/energy-experience-2-0-d/qa-production/closeout.json), con imagen, backup/restore, integridad, flags y resultados HTTP/HTTPS. Detalles privados de recuperación y checksums permanecen en NAS. Cierres anteriores: [A](ENERGY_EXPERIENCE_2_0_A_PRODUCTION.md), [B](ENERGY_EXPERIENCE_2_0_B_PRODUCTION.md), [C](ENERGY_EXPERIENCE_2_0_C_PRODUCTION.md).

Siguiente avance, implementación local para revisión de PR y sin despliegue: [Resumen de salud unificado](UNIFIED_HEALTH_SUMMARY_DESIGN.md). PITR, smoke físico Android/iOS y prueba externa real de Open Food Facts siguen como pendientes separados.
