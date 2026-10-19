# Recuperación operativa compatible con 0046

Estado: validado en MariaDB **LOCAL QA**, 18-10-2026. **No ejecutado en NAS ni autorizado aún para producción.** PR #21; issue #18 permanece abierto.

Este procedimiento conserva `20261018_0046` y sus evidencias. No usa downgrade, stamp, eliminación de tablas ni restore automático sobre la base activa. La imagen 0045 se conserva como antecedente; no interpreta revisiones/tombstones de 0046.

## Prerrequisitos y puntos de parada

1. Aprobación del SHA final y de la ventana de mantenimiento. Repetir el inventario productivo privado: revisión Alembic, imagen efectiva/arquitectura, flags efectivos, propietario, UUID, revisiones y hashes de las fechas del issue. El preflight anterior no sustituye esta lectura nueva.
2. Inventariar **todos** los escritores: web/API móvil, Operator, procesos de importación, workers y cron. Activar mantenimiento en el ingreso, drenar peticiones y detener esos escritores. La API debe devolver indisponibilidad temporal, nunca confirmar una escritura que no se persistió. Clientes conservan su cola para replay idempotente.
3. Verificar que no queden transacciones de escritura. Usar cuenta de mantenimiento limitada para lecturas y, si procede, retirar temporalmente DML a las cuentas de aplicación **sólo sobre el schema de la aplicación**. Inventariar concesiones heredadas antes: un REVOKE de schema no neutraliza un privilegio global. No cambiar grants globales como atajo. Mantener el bloqueo hasta terminar comparación y smoke.
4. DBA debe poder crear un schema de recuperación vacío y conceder sólo privilegios sobre él, sin reutilizar producción como QA. Si no dispone de esa capacidad, espacio suficiente, backups verificables o una imagen compatible conservada, **bloquear despliegue**.
5. Registrar en un inventario privado nombres de schemas/storage, SHA de código, ID/digest de imagen, versión de MariaDB y permisos. No incluir credenciales, rutas privadas, hashes de autenticación ni volcados en Git/PR. No leer ni mostrar `.env`.

## Copia consistente antes del primer DDL

Con escritores detenidos y archivos inmóviles:

- Comprobar que las tablas son InnoDB. Crear dump del **schema completo**, incluidas `alembic_version`, identidades móviles, auditoría, nutrición y catálogo, con `mariadb-dump --single-transaction --quick --skip-lock-tables --skip-add-locks --skip-add-drop-table`. No usar `--databases`: el dump debe poder entrar en otro schema. Inventariar triggers/routines/eventos y sus definers si existen; no conceder autoridad por contenidos del dump.
- Archivar todo el almacenamiento privado referenciado por la cuenta/aplicación (raw, generated y demás archivos persistidos), preservando rutas relativas. El export JSON/ZIP de una cuenta sirve para portabilidad, **no sustituye** esta copia consistente del servicio.
- Calcular SHA256 de dump, archivo de storage e imagen compatible; verificar otra copia de esos bytes antes del restore. Guardar manifest/checksums fuera de Git junto con el backup. Conservar también todos los backups anteriores.
- Restaurar en un schema **nuevo y vacío**, con storage independiente, red de QA y credenciales limitadas. Rechazar un destino no vacío. Verificar checksum, todas las tablas/filas/columnas anteriores y cada archivo referenciado por hash. No restaurar encima del origen.
- Medir duración y espacio de dump/restore antes de decidir la ventana real. Las mediciones de fixtures pequeños no son un RTO de producción.

## Imagen compatible de recuperación

Construir desde el SHA revisado usando el Dockerfile normal, conservar la imagen aprobada para la arquitectura destino y exportarla con `docker image save`. Registrar ID/digest y SHA256 del archivo; comprobar `docker image load` y que el ID cargado coincide. No sobrescribir ni retirar la imagen productiva anterior.

En QA se conservó `health-tracker-energy18:recovery-0046-3ffeba6`, Linux/amd64, Python 3.12; ID y checksum en `design/daily-energy-issue-18/qa/review-controls.json`. El código de aplicación/migraciones/schemas de esa imagen es el HEAD previamente revisado `3ffeba6`; esta revisión añade pruebas, scripts de QA y documentación. No introduce una nueva dependencia ni lógica productiva.

Para recuperar el servicio en 0046, arrancar la imagen por **ID verificado**, con el schema y storage actuales verificados. Durante diagnóstico, sustituir el entrypoint automático por Gunicorn directo: el arranque no debe migrar ni sembrar usuarios por sorpresa. Antes, comprobar head único 0046 y `flask db check` con esa misma imagen. Restituir los escritores únicamente tras el smoke y una decisión explícita del operador. No apuntar una imagen 0045 a datos 0046.

## Matriz de fallos

| Momento | Procedimiento seguro | No continuar si… |
| --- | --- | --- |
| Antes de migrar | Verificar 0045 **y** estructura 0045 intacta. Mantener copia y bloqueo; se puede reabrir la imagen 0045 conocida si no comenzó DDL, o reprogramar el upgrade aprobado. | Hay columnas/tablas de 0046, incluso aunque Alembic diga 0045. |
| Durante DDL MariaDB | Mantener bloqueo, conservar base parcial y sus archivos, tomar copia del estado fallido. Inventariar columnas/tablas/índices y revisión. Recuperar en **otro schema vacío** desde la copia previa ya validada; ejecutar allí el upgrade 0046 original y verificar invariantes. Tras aprobación operativa, cambiar conexión y storage al conjunto recuperado como una unidad. Conservar el origen parcial para investigación. | No se demuestra ausencia de escrituras desde el backup, no hay copia válida, o la estructura no corresponde al incidente previsto. No reintentar el upgrade sobre DDL parcial. |
| Después de 0046, sin nuevas escrituras | Conservar DB/storage 0046 y recuperar web con la imagen 0046 conservada, o una corrección compatible revisada. | Se propone sustituirla por 0045 o ejecutar un entrypoint desconocido. |
| Después de nuevas escrituras | Bloquear/drainar todos los escritores, preservar **estado actual** y tomar dump/storage actuales. Reiniciar con imagen compatible sobre ese estado. Si se necesita mover la DB, validar primero una copia del estado actual en un destino vacío y conmutar sólo con autorización. | Se propone volver al backup pre-DDL: perdería revisiones, evidencias, tombstones y nuevas comidas legítimas. |
| Daño de DB/storage después de nuevas escrituras | Si la copia actual no es legible/íntegra, mantener mantenimiento. Evaluar recuperación a punto en el tiempo sólo con backup y binlogs completos, correlación de archivos y validación aislada hasta la última escritura confirmada. | No se puede acreditar recuperación de todas las escrituras confirmadas. **Servicio/despliegue bloqueados; no aceptar pérdida silenciosa ni restaurar automáticamente un backup antiguo.** |

La conmutación a otro schema exige permisos específicos y actualización coordinada de la conexión privada y storage. Es una operación manual revisada; este PR no automatiza restauraciones productivas. Si se requiere conservar obligatoriamente el nombre del schema original o no se permite esa conmutación, resolver ese requisito antes de migrar; no vaciar el schema original para sortearlo.

## Verificación antes de levantar el bloqueo

1. Alembic en 0046, un solo head, `flask db check` sin nuevas operaciones; tablas, índices, constraints y referencias completas. Repetir upgrade sólo cuando **ya está en head confirmado** como no-op.
2. Comparar todas las columnas originales de DailyEnergy, UUID/revisiones/client_event_id y sus archivos. Una fila de `energy_days` por propietario/fecha, sin sumar fuentes; contradicción = desconocido hasta confirmación.
3. Comparar decisiones, `_pending`, eventos (claves/payload), hashes, referencias owner-only y tombstones. Si hubo escrituras posteriores, comparar con el inventario **posterior**, no con el anterior al DDL.
4. Verificar snapshots históricos MealLog, proyección legacy sin doble conteo, recetas, catálogo y planes/importaciones de Nutrition 2.1. Confirmar conteo productivo esperado de 13.685 alimentos y flags efectivos sin cambiarlos; el fixture QA usa catálogo ficticio pequeño y no certifica ese conteo productivo.
5. HTTP real: healthz, login/CSRF, Energía/listado/detalle/historial, Nutrición/gráficas/micronutrientes/Saved Meals. Verificar balances y tendencias, huecos y valores desconocidos. No insertar consumos ficticios en cuentas reales.
6. UUID, aliases móviles, replay y revisión obsoleta deben conservar comportamiento. Probar escrituras únicamente en QA; smoke físico Android/iOS continúa separado. Comprobar logs saneados y ausencia de 5xx/SQL.
7. Reabrir escritores gradualmente, conservar imagen/backups/estado fallido y monitorizar. La reconciliación específica de los días del issue requiere comparación owner-only y confirmación separada; no se ejecuta como parte del DDL. Cerrar #18 sólo después de esa recuperación y smoke productivos.

## Validación ejecutada en QA LOCAL

Se usó exclusivamente Docker Desktop y la MariaDB local existente, sin nuevos contenedores DB, stacks, puertos publicados ni volúmenes. Tres schemas ficticios con prefijo `energy18_recovery_qa_20261018_` (`a`, `b`, `c`), grants limitados al schema y storage temporal independiente. No se tocó la DB local principal ni el NAS.

| Evidencia | Resultado |
| --- | --- |
| Bootstrap real hasta 0045 con imagen anterior, fixtures de energía + Nutrition/MealLog/receta/catálogo + originales | PASS |
| Dump consistente 0045 + checksum + restore en `b` vacío | Todas las tablas y columnas originales idénticas |
| Interrupción real de upgrade después de CREATE TABLE `energy_days` en `a` | DDL persistido, Alembic 0045; originales intactos; schema fallido retenido |
| Recuperación en `b` desde copia verificada, upgrade original 0046 | PASS; hashes de todas las columnas previas iguales; `db check`; no-op |
| Nuevas evidencias, resolución, móvil con revisiones, tombstones y originales después de 0046 | PASS |
| Retirada temporal de DML al escritor QA de `b` | Intento UPDATE rechazado con 1142; lecturas disponibles |
| Dump posterior + storage independiente en `c` | Todas las tablas/UUID/revisiones/eventos/tombstones/snapshots/hashes idénticos; `db check` |
| Gunicorn directo desde imagen conservada sobre `c`, fallo de proceso y reinicio | HTTP real PASS, login/CSRF, energía y Nutrition 2.1; snapshot inmutable |
| Round-trip de cuenta JSON 1.1 / ZIP y entrada 1.0 en RC y RR | PASS; segunda importación sin duplicados; backup obsoleto no sustituye revisión/eliminación |

Resultados agregados: `design/daily-energy-issue-18/qa/review-controls.json`. Dumps, originales, archivo de imagen y manifests privados permanecen fuera del repositorio.

## Reproducción de QA

Los scripts tienen allowlist de los tres schemas QA, verifican host `db`, usuario `progression_qa`, schema real y head antes de escribir. Nunca utilizan la conexión de producción. Requieren el archivo de conexión QA **como ruta**, sin abrirlo ni imprimirlo, y las wheels pytest ya disponibles.

1. En MariaDB LOCAL existente, crear los tres schemas vacíos `a/b/c` y conceder al usuario QA únicamente SELECT/INSERT/UPDATE/DELETE/CREATE/ALTER/DROP/INDEX/REFERENCES sobre ellos. DROP es el grant de QA de Alembic; **ninguna fase de esta recuperación elimina tablas**. No dar privilegios globales ni crear otra instancia. Verificar que `DB_NAME` controla la conexión; abortar si el envfile contiene una URL que anule el destino (el script comprobará el schema efectivo).
2. Construir y conservar la imagen compatible. Usar la imagen anterior `health-tracker-ni21-runtime:py312-qa-20261016` con entrypoint Python y conexión **a `a` vacío** para ejecutar upgrade hasta 0045; verificar ese head. No ejecutar seed ni migrar la DB principal.
3. Ejecutar `recovery_0046_qa.py baseline --schema energy18_recovery_qa_20261018_a` dentro de la imagen compatible. Montar scripts sólo lectura como `/qa-scripts`, wheels como `/qa-wheels`, evidencia temporal como `/evidence`; `DATA_ROOT=/evidence/recovery-qa-files`, `PYTHONPATH=/app`. Crear venv temporal con `--system-site-packages` y pytest offline. Todos los fixtures son ficticios.
4. Desde PowerShell, para cada fase en orden:

```powershell
# Rutas privadas suministradas por el operador; nunca contenido del envfile.
$qaArgs = @{
    QaEnvFile = $privateQaConnectionFile
    EvidenceRoot = $privateEmptyEvidenceDirectory
    PytestWheels = $existingOfflinePytestWheels
}
foreach ($qaPhase in @('clone-baseline','interrupt','upgrade','roundtrip','postwrite','freeze','clone-post','verify-post','retain-image')) {
    & scripts/energy/recovery_0046_qa.ps1 -Phase $qaPhase @qaArgs
}
```

`clone-baseline` verifica/extrae los archivos en storage independiente; `clone-post` hace lo mismo para el estado posterior. No reutilizar schemas no vacíos para repetir la simulación; conservar la ejecución y planear otra QA aislada. El driver rechaza sobrescribir backups/archivos. El schema fallido `a` queda intacto; `b` queda sin DML.

5. Arrancar un único Gunicorn QA con la imagen compatible por ID, `DB_NAME=..._c`, `DATA_ROOT=/evidence/recovery-qa-files-c`, flags **sólo QA**, bind `127.0.0.1:8000` dentro del contenedor y sin `-p`. Ejecutar `recovery_service_smoke.py`; interrumpir y reiniciar **únicamente ese contenedor QA identificado por imagen** y repetir el smoke. No detener web/DB locales principales. Detener al terminar el contenedor QA; conservar imagen, schemas y backups.

El driver es exclusivo para el laboratorio LOCAL. Para producción, trasladar el procedimiento a la plataforma aprobada y repetir los prerrequisitos/backup/restore sobre su estado vigente antes de cualquier DDL. Las pruebas QA no constituyen por sí mismas autorización de squash ni despliegue.
