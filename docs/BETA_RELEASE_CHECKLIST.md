# Checklist Beta 1 Android

## Freeze y contratos

- [x] Rama/HEAD inicial exactos y staging vacío.
- [x] Sin Alpha 2.1 ni funciones nuevas.
- [x] Room 10 y Alembic 0036 sin cambio de schema.
- [x] applicationId, firma, SDKs y toolchain conservados.
- [x] VersionCode 21 y versionName `2.0.0-beta01`.

## Defectos

- [x] Cancelación estructurada no se transforma en retry/failure.
- [x] IDs remotos no forman paths de caché/FileProvider.
- [x] Mensaje de límite de exportación sin mojibake.
- [x] Regresiones JVM añadidas.
- [ ] Carreras logout/cambio de servidor ejecutadas en AVD.

## Gates locales

- [x] Backend `compileall`.
- [x] Backend completo: 716 passed, 9 skipped.
- [x] 77 schemas válidos y refs locales presentes.
- [x] Android `lintDebug` final.
- [x] JVM final forzada: 172/172.
- [x] `assembleDebug` final.
- [x] `compileDebugAndroidTestKotlin` final: 123 tests fuente compilados, no ejecutados.
- [x] Segunda JVM final forzada: 172/172.
- [x] APK audit/manifest externo: 173 entradas, firma v2, cero hallazgos bloqueantes.
- [x] MariaDB efímera completa y limpia: 724 passed/1 skipped, cero volúmenes.

## AVD y dispositivo

- [x] Harness seguro PowerShell 5.1 (25 aserciones).
- [ ] AVD permitido creado/serial validado — bloqueado por imagen instalada.
- [ ] Instrumentación ejecutada — bloqueada.
- [ ] Room 1→10 y reapertura ejecutados — bloqueados.
- [ ] Upgrade `install -r` ejecutado — bloqueado.
- [ ] Offline/process death/WorkManager/reboot/notificaciones/SAF ejecutados — bloqueados.
- [ ] Rendimiento y layouts medidos — bloqueados.
- [ ] TalkBack físico — pendiente, no aprobado.

## Repositorio e infraestructura

- [x] Cero `git add`, commit, push, merge, tag o cambio de rama.
- [x] Compose diario, `.env`, `/data`, NAS y `qa-temp-alpha15*` intactos.
- [x] Recursos efímeros Beta eliminados y baseline Docker restaurado.
- [x] `git diff --check` final verde.
- [x] `git diff --cached --name-only` final vacío.

Beta 1 no es una release final. Los checks bloqueados deben cerrarse en un entorno que cumpla el runbook; no se convierten en aprobados por compilación.
