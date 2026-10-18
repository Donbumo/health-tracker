# Energía diaria — corrección P0 del issue #18

Fecha: 18 de octubre de 2026. Base: `500589bbafa6d730536595cb7d115f72ebdfe462`.
Rama: `fix/daily-energy-issue-18`. Estado: PR #21, dos controles finales validados en QA LOCAL; **sin merge, despliegue ni recuperación productiva aplicada**.

Referencia: [issue #18 y sus dos comentarios](https://github.com/Donbumo/health-tracker/issues/18).
No usar cierre automático del issue al fusionar: su cierre exige recuperación y smoke productivos posteriores.

## Diagnóstico previo a los cambios

Se reprodujo el código de la base en la MariaDB LOCAL 11.4 existente, schema QA aislado, con fixtures ficticias fechadas en 2040. No se usaron los datos reales del issue como fixtures.

| Caso | Antes, RC y RR | Corrección |
| --- | --- | --- |
| Pasos/distancia parcial → completo, otra fuente | Dos filas presentadas como días independientes | Una representación diaria; ambas evidencias conservadas |
| Mismo contenido con otro nombre | Dedupe del archivo, no una política general del día | Identidad de evento y valores; registrar también la procedencia de otro archivo |
| Nuevos valores, misma fuente | JSON directo rechaza completar | Completar únicamente valores faltantes |
| Mismo valor/evento repetido | Políticas distintas entre escritores | Sin duplicación ni aumento innecesario de revisiones |
| Ausencia/null/cero | Null público rechazado; adaptador interno podía borrar | Ausencia/null no borran; cero sigue siendo conocido |
| Móvil antes/después de calorías | Dos fuentes; un parcial podía ocultar gasto conocido | Fuente móvil conservada, resolución compartida por campo |
| Lectores diario/tendencias | Elegían resultados distintos | Misma proyección canónica |
| Escrituras concurrentes | Dos fuentes pasan el UNIQUE legado | Mutex del propietario + UNIQUE del día canónico |
| Editar/eliminar web | Rutas inexistentes, HTTP 404 | Formularios owner-only con CSRF, revisión y confirmación |

Reproducción conservada en `scripts/energy/baseline_reproduction.py` y `design/daily-energy-issue-18/qa/baseline-reproduction.json`. La prueba directa del adaptador con null no se presenta como un bypass público del schema anterior.

## Modelo y política de resolución

`EnergyDay` (`energy_days`) registra **exactamente un canónico por `(user_id,date)`**. `DailyEnergy` sigue siendo la tabla de evidencias actuales por fuente y de identidades móviles. No se impone una unicidad por día sobre esta última: destruiría la semántica introducida por 0031.

La nueva revisión **`20261018_0046`**, posterior a 0045, añade el registro canónico, el diario privado `energy_evidence_events`, tombstones y SHA256 de origen. Hace backfill de todos los propietarios con `GROUP BY user_id,date`. No retira ni renumera filas originales; conserva UUID, revisiones, eventos móviles, valores, `source_file_id`, payload y timestamps originales. El canónico es una proyección de lectura: no recalcula ni reescribe el historial nutricional.

Resolución por campo:

1. Un único valor conocido, o varios iguales: usar ese valor una sola vez.
2. Fuentes complementarias: completar los campos conocidos, sin inferir gasto total a partir de pasos ni de componentes.
3. Valores distintos: conservarlos, marcar conflicto y devolver desconocido para ese campo; no sumar ni elegir el más reciente.
4. Importar una contradicción de la misma fuente conserva la fila aceptada y añade una propuesta pendiente en el diario. Los previews avisan de la discrepancia.
5. Una edición explícita confirma un valor o un vaciado por campo y deja la decisión y las evidencias previas auditables. Nuevas contradicciones posteriores vuelven a requerir revisión.

Esto elimina la antigua precedencia implícita de una fuente llamada `manual`. Un nombre de fuente enviado en un archivo no autoriza sobrescribir otra fuente. Un conflicto histórico puede pasar de un valor arbitrariamente elegido a «desconocido» hasta revisión; es una corrección de interpretación, no pérdida de los valores originales.

## Escrituras, edición y eliminación

JSON directo y captura manual, StandardImportExecutor, CSV/TSV de Import Hub, restore de cuenta, portabilidad de pasos y demo se apoyan en el servicio `energy_days`. Móvil comparte mutex, registro diario, revisión y auditoría; sigue conservando sus UUID por fuente.

El bloqueo del propietario serializa también el primer insert de una fecha bajo READ COMMITTED y REPEATABLE READ. Las lecturas de escritura usan `FOR UPDATE` y refrescan la identidad ORM. El índice único es la última defensa; un fallo provoca rollback de evidencias, registro y eventos. El servicio no hace commits internos: se conserva la atomicidad de los lotes.

Las confirmaciones estándar y CSV incluyen la huella del día completo, no sólo la fuente destino. Se vuelve a comprobar bajo bloqueo al confirmar; una fuente añadida o una revisión cambiada invalida el preview anterior.

Edición: precarga, fecha, totales, activas, reposo, pasos, metros y notas. Ausencias en el POST conservan lo existente; los checkboxes «Vaciar» distinguen borrado explícito de un campo vacío. Una revisión obsoleta responde 409. Cambiar a una fecha ocupada se bloquea; no se fusiona el destino.

Eliminación: POST con CSRF y confirmación, de todo el día o de una fuente seleccionada. Retención mediante tombstones y diario; no se borran originales. Un import o alta móvil no resucita automáticamente un día eliminado. El restore de ese estado exige revisión; no existe un botón de deshacer automático en este hotfix.

`delete_steps` sólo quita pasos de la fuente móvil y conserva identidad, revisión, evento, calorías y distancia. Si después se crea de nuevo con otro `client_event_id`, el diario conserva ese alias y permite replay sin sustituir el ID legado ni generar otra fila; los aliases son owner-only. Mover por móvil una fuente que contiene gasto u otras métricas se rechaza para exigir revisión conjunta desde Energía. Las demás formas de los contratos y UUID públicos móviles siguen vigentes.

## Exportación, restore y compatibilidad

- Los documentos diarios **1.0 siguen aceptados**. Sus opcionales pueden venir ausentes/null para completar conservadoramente; vaciar requiere edición explícita.
- El JSON exportado con procedencia usa **`schema_version: "1.1"`** y una extensión `evidence` versionada: fuentes, revisiones, eventos, hashes de archivos y decisiones canónicas. No se hace pasar esta extensión por un archivo 1.0 ante validadores antiguos.
- JSON de cuenta y ZIP conservan esa extensión. En otro propietario, las colisiones UUID se remapean; los IDs históricos quedan en el payload de evidencia, sin conceder acceso. Una fuente o decisión distinta en destino bloquea el reemplazo.
- Las referencias a raw se resuelven por propietario + SHA256. El puntero legado único `DailyEnergy.source_file_id` se conserva; el diario representa la relación de un CSV con múltiples días. El restore ZIP enlaza después de verificar/restaurar los miembros raw.
- CSV es una vista diaria con unidades y sin auditoría de fuentes; la UI lo informa. Para round-trip íntegro se utiliza JSON 1.1 o ZIP. Las celdas de texto no ejecutan fórmulas.
- No cambia ningún schema de transporte Android/iOS, Bearer, Idempotency-Key, companion ni workout sync. El resumen diario/progreso devuelve null ante fuentes contradictorias; las fuentes individuales siguen disponibles con sus UUID/revisiones. Los clientes que consuman archivos diarios con auditoría deben reconocer la versión 1.1; pueden seguir enviando 1.0.
- Sin cambios de migración 0045, catálogo, nutrientes, MealLog, snapshots, flags predeterminados ni servicios externos. No se requiere nueva dependencia.

## Evidencia de QA

Fixtures ficticias únicamente. Scripts en `scripts/energy/`; resultados y seis capturas en `design/daily-energy-issue-18/qa/`.

- Reproducción previa: MariaDB 11.4, READ COMMITTED y REPEATABLE READ.
- Migración MariaDB 0045 → 0046: aserciones de hash de todas las columnas anteriores de DailyEnergy y de nutrición/recetas/snapshots/catálogo sin cambios. Tres evidencias duplicadas sintéticas conservadas, un canónico y conflicto explícito. `db check`, unicidad y upgrade repetido PASS.
- Migración SQLite: duplicados de dos propietarios, todas las columnas originales iguales, SHA de origen y restricción única PASS. También upgrade de un fixture completo del schema 0045, `db check` y no-op PASS. La cadena histórica desde vacío conserva una limitación anterior en 0015 (ALTER de FK específico de MariaDB); no se reescribió esa migración. Downgrade destructivo expresamente bloqueado.
- RC/RR: alta concurrente de dos fuentes, una sola fila canónica; revisiones concurrentes con un ganador y un 409 lógico; idempotencia, null/cero, rollback, ownership y móvil sin pérdida de gasto PASS.
- Gunicorn/Python 3.12 + MariaDB QA por HTTP real: healthz, login/CSRF, parcial/completo, edición, revisión obsoleta, JSON 1.1 y borrado confirmado PASS.
- JSON/ZIP: fuentes, decisiones, eventos y bytes/hashes raw conservados; referencias del propietario destino PASS.
- Visual Flask: **60 combinaciones PASS**, 360/390/430/768/1024/1366, dark/light, listado/detalle/conflicto/edición/confirmación. Sin overflow, foco de teclado visible, edición y borrado mediante formularios CSRF reales. Checkboxes con etiqueta de 44 px. Capturas sólo de QA ficticia.
- **Suite backend final: 1297 PASS, 34 skipped, 1 warning (330,66 s). Focal Docker final: 135 PASS (43,28 s).** Los skips son gates opcionales; los casos MariaDB críticos se ejecutaron además en Docker y en el script RC/RR. Conteos y motivos en `tests-final.json`. Smoke físico Android/iOS no realizado; compatibilidad validada por contratos y pruebas HTTP, sin cambios obligatorios de cliente.

Reproducibilidad: usar exclusivamente el schema QA existente y su archivo de conexión privado mediante `--env-file`; no incluirlo en Git ni en paquetes de evidencia. El script MariaDB valida nombre exacto de schema, usuario QA y revisión antes de escribir. No crea stacks, volúmenes, usuarios ni bases; si ya está en 0046 sólo prueba el no-op. Para la reproducción anterior se usa la imagen baseline 0045 existente. El servidor visual usa el venv existente, almacenamiento temporal y el puerto QA 8025; no abre la DB local personal.

## Cierre de revisión del PR #21

HEAD de aplicación revisado: `3ffeba6118292e053a5ae80230a5eb14f6a3cb59`. En este cierre sólo se añaden pruebas, scripts QA, evidencia y documentación. **No fue necesario modificar código productivo**, modelos, formularios, migración 0046 ni schemas.

**Control 1 — PASS.** `test_energy_account_roundtrip.py` combina cuatro originales distintos, pasos parciales y gasto en fuentes diferentes, contradicción, resolución confirmada, fuente retirada y otro día completamente eliminado, revisiones/eventos móviles y nutrición legacy. Export de cuenta JSON 1.1 y ZIP hacia otro propietario, confirmación y segunda importación: valores/payloads, decisiones, claves/eventos y hashes idénticos; UUID vivos remapeados sin autoridad cruzada, UUID históricos intactos. Los bytes raw se verifican por SHA256; sin referencias a archivos de otro propietario. Un canónico por fecha, día eliminado retenido, mismas series y medias móviles, balance ficticio -450, sin duplicación. Replay móvil conserva UUID/revisión destino. Backup anterior bloqueado después de nueva revisión o eliminación. Entrada de cuenta JSON 1.0 repetida y null/cero PASS.

El formato de cuenta por fuente **no causó un error** en este caso combinado: cada documento conserva evidencia, incluso tombstones, y comparte la revisión del día; los balances exportados y lectores usan la proyección canónica. No se sustituyó por una lista de proyecciones activas que perdería fuentes/días eliminados. No se creó otro formato.

**Control 2 — PASS en QA aislado.** [Runbook operativo 0046](ENERGY_0046_RECOVERY_RUNBOOK.md). Bootstrap real 0045, dump consistente y checksums; restore en schema vacío; fallo inyectado después de DDL confirmado con Alembic todavía en 0045; origen parcial conservado y respaldado, sin reintento ciego. Recuperación en copia previa verificada, upgrade original 0046, hashes de todas las columnas originales intactos y `db check`. Nuevas revisiones/eventos/tombstones, bloqueo DML comprobado (1142), dump actual y restore con storage independiente: **80 tablas idénticas**, originales por hash, catálogo/recetas/MealLog conservados. Imagen compatible construida, guardada, checksum y `docker image load` comprobados. Gunicorn real detenido/reiniciado sobre 0046 posterior a nuevas escrituras; HTTP de energía y Nutrition 2.1 PASS.

Gates finales de este cierre: **154 pruebas focales PASS, 1 warning esperado por ZIP duplicado de seguridad (42,27 s)**; E2E completo JSON/ZIP, replay móvil, entrada 1.0 y rechazo obsoleto en MariaDB 11.4 **READ COMMITTED y REPEATABLE READ**; regresión concurrente RC/RR PASS; `db check`, compileall y Compose PASS. La suite anterior de 1297 PASS se conserva como evidencia previa y no se repitió: no cambió código funcional. Capturas existentes vigentes, sin cambios UI.

Resultados agregados y checksums no sensibles: `design/daily-energy-issue-18/qa/review-controls.json`. Los dumps, originales, archivo de imagen y manifests privados permanecen fuera de Git. Las tres bases de recuperación QA y la imagen se conservan; el contenedor web de smoke quedó detenido. No se accedió al NAS ni a la DB local principal durante este cierre.

## Preflight productivo y recuperación pendiente

Preflight de la entrega anterior, no repetido en este cierre: Windows, origin/master y NAS coincidían en la base citada; NAS sigue en 0045, Nutrition habilitado y lookup externo deshabilitado. Se identificó una sola cuenta candidata al comparar las evidencias exactas del issue. El día 10 tiene un completo correcto y un parcial; 11 y 12 aún difieren del reporte. Las filas observadas no tienen modificaciones posteriores al reporte original. No se publican IDs, cuenta, valores adicionales ni payloads personales.

Tras revisión del PR y autorización de integración/despliegue:

1. Repetir identificación owner-only y comparar IDs, revisiones, hashes, fuentes y archivos de las tres fechas con este preflight. Si cambió algo, detener la recuperación automática.
2. Backup nuevo consistente inmediatamente antes de DDL, checksum y restore aislado; conservar también los backups anteriores y la imagen previa. No sustituir nuevos registros legítimos por un backup antiguo.
3. Preflight de todos los duplicados: la migración conserva todas sus filas como evidencia y registra un canónico por día. Presentar los conflictos, sin resolución automática entre fuentes.
4. Aplicar sólo el SHA aprobado y 0046, sin tocar DB/volúmenes originales, flags de Nutrition ni catálogo. Recrear únicamente web mediante el Compose existente.
5. Para el día 10, conservar la identidad de la evidencia completa y retirar sólo el parcial demostrado redundante, mediante tombstone auditable. Para 11/12, confirmar por campo únicamente los valores del comentario original aún necesarios. No SQL global, otras fechas ni otros propietarios.
6. Verificar una representación por día, identidades/evidencias retenidas, gastos/balances/tendencias, Nutrition/Gym/AI/móvil, HTTPS/healthz y ausencia de SQL/5xx. Pruebas de escritura sólo con QA seguro.
7. Publicar resultado en el issue sin nuevos datos personales y cerrarlo **después** del smoke productivo. Sólo entonces iniciar `feature/energy-experience-2-0` separada.

## Recuperación y límites de integración

Aplicar [ENERGY_0046_RECOVERY_RUNBOOK.md](ENERGY_0046_RECOVERY_RUNBOOK.md): recuperación hacia adelante con imagen 0046 compatible y bloqueo de escritores. Para DDL parcial, conservar el origen fallido y recuperar en un destino vacío desde una copia consistente verificada, ejecutar allí el upgrade original y conmutar conexión/storage sólo tras aprobación. Nunca downgrade, stamp, eliminación de tablas ni restauración automática sobre el origen. Después de nuevas escrituras, conservar el estado actual, no el backup previo al DDL.

Ambos controles tienen evidencia QA suficiente para **solicitar autorización final**, no para declarar recuperada producción. Antes del despliegue siguen siendo obligatorios inventario y backup/restore productivos nuevos, permisos específicos y posibilidad de conmutar schema/storage. Si falta esa capacidad o no se pueden recuperar todas las escrituras confirmadas después de un daño de DB/storage, mantener mantenimiento y bloquear despliegue. No se ha validado PITR productivo ni medido un RTO real. Smoke físico Android/iOS pendiente por separado.

Mantener abierto #18; reconciliación de datos reales y smoke productivos requieren la siguiente autorización. Energy Experience 2.0 sigue condicionada a ese cierre, en otra rama. Sin merge ni NAS en esta entrega.
