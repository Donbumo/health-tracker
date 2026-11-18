# Cuenta DEMO histórica

La cuenta `demo@healthtracker.test` usa login, hash Werkzeug, MariaDB y los servicios reales. Nombre: **Health Tracker Demo**, rol `user`; `UserMixin.is_active` proporciona el estado activo vigente. Su UUID público determinista identifica a este generador sin añadir columnas. Un correo coincidente sin esa identidad se rechaza, incluso si pertenece a un usuario normal. La contraseña nunca se imprime ni se restablece al repetir el comando.

El generador cubre nutrición, energía, fuerza y, en la ampliación del mismo PR #47, peso y composición corporal. No hay datos médicos, sueño, metas inventadas ni acceso remoto AI habilitado para la cuenta. La ampliación corporal está validada en QA y **todavía no se ejecutó en el NAS**.

## Ejecución normal

Con la aplicación actualizada y su esquema ya en **0046**, desde `backend/`:

```powershell
$env:FLASK_SKIP_DOTENV = '1'
$env:DEMO_SEED_ENABLED = 'true'
$env:DEMO_SEED_ENVIRONMENT = 'local'
$env:NUTRITION_INTELLIGENCE_ENABLED = 'true'
# DEMO_USER_PASSWORD debe existir sólo en el entorno del proceso (mínimo 12 caracteres).
..\.venv\Scripts\python.exe -m flask --app app:create_app seed demo --as-of 2026-11-18 --confirm-local
```

La invocación confirma la escritura. El generador no se ejecuta durante arranque, migraciones ni despliegues. No lee archivos `.env`. Rechaza producción, hosts DB remotos y ausencia de confirmación por defecto. La excepción productiva exige autorización explícita, `DEMO_SEED_ENVIRONMENT=production` y **`--confirm-production`**, que no se puede combinar con `--confirm-local`.

Omitir `--as-of` usa hoy en la zona horaria de la aplicación. La primera ejecución cubre el mes anterior completo y el mes actual hasta la referencia inclusive. Los reintentos omiten los días existentes; las actualizaciones rellenan el intervalo pendiente y conservan los anteriores. El origen de progresión permanece en la versión inmutable de la rutina. Un salto pendiente superior a 366 días requiere fechas intermedias. No se crean fechas posteriores a la referencia ni se aceptan referencias futuras. No hay comando de reset o borrado.

## Contraseña con DPAPI en Windows

Desde la raíz del checkout:

```powershell
. ./scripts/demo/password.ps1
$demoCredential = [pscredential]::new('demo@healthtracker.test', $demoSecurePassword)
$env:DEMO_USER_PASSWORD = $demoCredential.GetNetworkCredential().Password
# Ejecutar aquí el comando autorizado.
Remove-Item Env:DEMO_USER_PASSWORD
$demoCredential = $null
$demoSecurePassword = $null
```

La primera llamada genera 32 bytes aleatorios y guarda únicamente el valor protegido con DPAPI en `%LOCALAPPDATA%\HealthTrackerDemo\password.dpapi`, con ACL restringida al usuario Windows y SYSTEM. Las siguientes reutilizan el mismo secreto. No pertenece al repositorio ni al NAS. Para iniciar sesión manualmente sin imprimir la contraseña:

```powershell
./scripts/demo/password.ps1 -CopyToClipboard
```

La copia al portapapeles es explícita; sustituye su contenido después de usarla. Si se pierde el perfil/archivo DPAPI, la recuperación se hace por la administración normal de contraseñas, no por el seed.

## Instalación existente sin desplegar la rama

El runner `scripts/demo/seed_existing.py` permite ejecutar una vez el generador sobre un contenedor ya actualizado, con la contraseña del entorno. Carga cuatro módulos revisados sólo en la memoria de ese proceso administrativo, verifica 0046 y las huellas del código de dominio. Nutrición debe estar habilitada para el seed completo; `--body-only` no necesita esa bandera. No reemplaza archivos del contenedor, imagen, checkout, workers, configuración persistente o migraciones.

```powershell
.\.venv\Scripts\python.exe scripts/demo/seed_existing.py --as-of 2026-11-18 --confirm-production --ssh-host HOST_AUTORIZADO --ssh-user USUARIO_SSH --ssh-port PUERTO_SSH
```

Requiere el acceso SSH existente y autorización para ese destino. Usa claves ya configuradas, verificación estricta del host, contraseña por stdin y ningún secreto en argumentos. No admite rutas de código elegidas por el cliente. Compara en memoria del servidor el estado de los usuarios anteriores y sólo devuelve conteos y resultados. No almacena copias de sus datos ni expone huellas, payloads o credenciales. Una discrepancia de integridad posterior al commit se informa como fallo de verificación: no desencadena un borrado ni una restauración automática.

## Datos y contratos

- Nutrición: 3–5 comidas diarias, menús y porciones deterministas por fecha. Doce recetas reutilizables se guardan con el servicio oficial; sus snapshots fijan las fuentes para futuras actualizaciones. Los ingredientes generan una única proyección por consumo, sin contar de nuevo el plato. Los micros válidos del catálogo se conservan; los ausentes permanecen desconocidos.
- Se priorizan identidades USDA exactas con preparación conocida. Si faltan, se crean exclusivamente alimentos privados identificados como DEMO con macros sintéticos y sin micros inventados. Nunca se escribe en catálogos compartidos ni se reutilizan alimentos privados de otros usuarios.
- El contrato publicado `nutrition_import 2.1` está integrado en el código base. HTNX 1.0 está en RFC/QA separada y no es un escritor publicado en esta base. Este generador usa directamente el flujo oficial de borrador → confirmación de Nutrition Intelligence y sus snapshots 2.0/2.1; no fabrica un archivo de importación ni un segundo contrato.
- Energía: una evidencia `demo_history_v1` y un día canónico por fecha mediante `energy_days.upsert_document`. El gasto incluye actividad y reposo; las calorías de entrenamiento no se suman otra vez. La ingesta y el balance los leen/calculan `daily_balance`, las series canónicas y los dashboards existentes.
- Fuerza: Full Body A/B/C lunes, miércoles y viernes, seis ejercicios y tres series por sesión. Se reutilizan referencias exactas del catálogo externo cuando existen y los nombres de presets reales cuando no está instalado. `confirm_program`, `start_session`, `complete_set` y `finish_session` crean versiones, sesiones, cargas, reps, RIR/RPE y descanso. Los tiempos históricos también quedan en los cambios de sync. No se guardan volumen ni 1RM redundantes.
- Cuerpo: `body_document` genera el contrato existente `weigh_in 1.0` y el importador oficial comparte `persist_weigh_in_document`, sin commit interno. Un pesaje diario a las 07:00 locales se normaliza a UTC; martes/jueves/sábado incorpora los seis campos corporales en esa misma fila. UUID y evento estables por fecha, fuente `demo_body_v1` y notas inequívocas. No se añaden schemas, modelos o migraciones.
- Toda la operación es una transacción; las colisiones o fallos revierten el lote. No se adopta la antigua cuenta `demo@example.com` ni se borra su historial.

## Consulta y límites de presentación

En la rama, **Mes actual · mismos días** compara noviembre 1–18 con octubre 1–18. **Mes anterior completo** permite consultar octubre 1–31. Los rangos se resuelven en el backend, incluido el recorte al último día de febrero; la comparación anterior por días consecutivos conserva su comportamiento. No hay cálculos DEMO en JavaScript.

La ejecución administrativa sobre un servidor existente no publica esos controles nuevos. En el NAS, hasta revisar y desplegar la rama, se pueden abrir los rangos existentes por separado:

```text
/dashboard?from=2026-11-01&to=2026-11-18
/dashboard?from=2026-10-01&to=2026-10-18
/dashboard?from=2026-10-01&to=2026-10-31
/energy?date=2026-11-18&period=90
/nutrition/?date=2026-11-18&period=90
/training-plans
/training-sessions
/progress
```

Energía/nutrición conservan sus ventanas de 7/30/90 días y los límites de los módulos actuales. En el NAS, la sección corporal seguirá vacía hasta autorizar y ejecutar el backfill; la médica permanece fuera del generador. No se inventan sesiones planificadas para producir cumplimiento de agenda. Las métricas de fuerza son las soportadas por los lectores actuales. Los exports nutricionales legacy pueden responder 409 para evitar aplanar snapshots completos; el export de cuenta y el backup conservan Nutrition Intelligence.

## Ampliación corporal y backfill independiente

El recorrido corporal parte del origen histórico guardado en la rutina DEMO, **no** del cursor de energía/nutrición. Por ello rellena octubre completo aunque esos módulos ya lleguen al 18 de noviembre. Repetir crea cero registros; una extensión conserva los anteriores y agrega sólo los pesajes faltantes. Se rechaza cualquier pesaje manual o modificado en un día del intervalo, incluso con otra hora/fuente, en lugar de sustituirlo o duplicar ese día. Un fallo tardío revierte todo el lote.

Perfil completamente ficticio: tendencia de unos 78.4 a 77.2 kg con fluctuaciones diarias; grasa de 23.4 a 22.8 %, músculo de 56.8 a 57.0 kg, agua de 55.2 a 55.8 % e índice visceral de 8.0 a 7.8. Son valores sintéticos independientes: **no se deducen del balance energético**. El IMC usa estatura fija de 1.78 m. El BMR es la estimación ilustrativa `1700 + 10 × (peso_kg − 75)` kcal/día, explícitamente no clínica y distinta de `DailyEnergy.resting_calories`.

`--body-only` exige la cuenta y la rutina DEMO existentes, comprueba la contraseña actual y no crea usuarios, recetas, energía, nutrición, sesiones o series. No restablece credenciales. El runner comprueba también que todos los dominios previos de esa cuenta, además de los otros usuarios, sigan idénticos.

Comando para una aplicación local actualizada, con las variables de autorización y contraseña descritas arriba:

```powershell
..\.venv\Scripts\python.exe -m flask --app app:create_app seed demo --body-only --as-of 2026-11-18 --confirm-local
```

Para completar el NAS **sólo después de autorización expresa**, desde la raíz de esta rama y usando el mismo acceso SSH ya configurado. Las variables `HT_NAS_HOST`, `HT_NAS_USER` y `HT_NAS_SSH_PORT` deben contener el destino verificado; el repositorio no guarda direcciones ni credenciales:

```powershell
if (-not $env:HT_NAS_HOST -or -not $env:HT_NAS_USER -or -not $env:HT_NAS_SSH_PORT) {
    throw 'Falta el destino SSH autorizado; no se ejecutó el seed.'
}
. ./scripts/demo/password.ps1 -RequireExisting
$demoCredential = [pscredential]::new('demo@healthtracker.test', $demoSecurePassword)
$env:DEMO_USER_PASSWORD = $demoCredential.GetNetworkCredential().Password
try {
    .\.venv\Scripts\python.exe scripts/demo/seed_existing.py --body-only --as-of 2026-11-18 --confirm-production --ssh-host $env:HT_NAS_HOST --ssh-user $env:HT_NAS_USER --ssh-port $env:HT_NAS_SSH_PORT
} finally {
    Remove-Item Env:DEMO_USER_PASSWORD
    $demoCredential = $null
    $demoSecurePassword = $null
}
```

Resultado esperado, verificado en MariaDB QA: **49 pesajes, 21 composiciones**, una sola fila por fecha; se conservan 49 días de energía/nutrición, 196 comidas, 21 sesiones y 378 series. El replay informa `weigh_ins=0`, `body_measurements=0` y cero registros nuevos. Ninguno de esos pesajes se ha insertado aún en producción en esta ampliación.

Las vistas existentes `/dashboard`, `/weigh-ins` y `/weigh-ins/history` muestran peso actual, cambios, promedio, tendencia y media móvil de siete días. Resumen presenta grasa, músculo, agua, índice visceral e IMC; permite los rangos de octubre/noviembre y la comparación por los mismos días de esta rama. BMR queda visible en el detalle/export del pesaje, sin gráfica longitudinal propia. No se añadió frontend exclusivo para DEMO. [Capturas y reproducción](../design/demo-body/README.md).

Validación de esta ampliación: **94 pruebas del área PASS, 1 skipped**, incluyendo backfill sobre la cuenta previa, contraseña/estado de todos sus otros módulos, aislamiento, rechazo de pesajes manuales/modificados, rollback tardío, extensión y hora local/UTC con cambio de horario. Suite completa actual: **1885 PASS, 35 skipped y el único fallo preexistente de `test_active_handoff.py`** (160 líneas frente al límite de 80); el archivo ajeno permanece intacto. MariaDB 11.4 aislada: 49 pesajes/21 composiciones creados, replay cero, dominios anteriores intactos y `db check` PASS en READ COMMITTED y REPEATABLE READ. El runner administrativo se probó en esa misma base con `--body-only`, sin requerir nutrición habilitada. Navegador local: cinco páginas, 30 layouts, cinco métricas de composición y 13 capturas; cero errores JS/HTTP u overflow. El [reporte visual](../design/demo-body/qa/report.json) contiene únicamente resultados de QA ficticia.

## Verificación inicial de energía, nutrición y fuerza en el NAS

Realizada el 18 de noviembre de 2026, antes de la ampliación corporal. Creación autorizada en el NAS, **sin despliegue de la rama**:

| Registro persistido | Total real |
| --- | ---: |
| Energía, 2026-10-01 a 2026-11-18 | 49 días |
| Nutrición, mismo periodo | 49 días |
| Comidas consumidas | 196 |
| Recetas | 12 |
| Rutinas / versiones iniciales | 1 / 1 |
| Sesiones completadas | 21 (13 octubre, 8 noviembre) |
| Series reales | 378 |
| Alimentos privados nuevos | 0; se reutilizó el catálogo |
| Registros nuevos al repetir | 0 |

Login HTTP real con CSRF y siete páginas autenticadas PASS; 49 balances canónicos completos; recurso de entrenamiento ajeno 404. Estado de los demás usuarios idéntico antes/después. Imagen, checkout productivo y reinicios de `web` intactos; ninguna migración nueva o aplicada al NAS.

QA local: **22 pruebas específicas DEMO PASS; gate final del área: 217 PASS, 1 skipped**. Suite completa: **1871 PASS, 35 skipped y un fallo preexistente** en `test_active_handoff.py`: el handoff ajeno ya modificado tiene 160 líneas frente al límite de 80; se conservó intacto. MariaDB 11.4 aislada: upgrade completo a 0046, `db check`, READ COMMITTED/REPEATABLE READ, login, dashboards y replay PASS. Compilación, Compose y `git diff --check` PASS.

Navegador local sobre Flask y datos persistidos sintéticos: siete páginas, 42 combinaciones en 360/390/430/768/1024/1366 px, sin overflow, errores JavaScript o HTTP inesperados. Esta evidencia visual corresponde a la rama local; las siete comprobaciones HTTP productivas se midieron aparte. No se afirma una auditoría de accesibilidad completa.
