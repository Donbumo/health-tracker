# Cierre de misiÃ³n: AI Energy Balance en el NAS

Fecha: 2026-11-08. Entorno: **NAS principal**.
Estado final: **Ã‰XITO PARCIAL**.

La reparaciÃ³n, integraciÃ³n y actualizaciÃ³n productiva estÃ¡n completadas. La
herramienta estÃ¡ registrada y las dos consultas reales del asistente funcionan
por HTTPS con una cuenta operativa autenticada y con consentimiento remoto.
Queda sin verificar el resultado numÃ©rico del propietario para el 26/10: la
cuenta disponible no contiene esos registros y la automatizaciÃ³n de la sesiÃ³n
Edge del propietario se detuvo por no poder verificar la URL con confianza.
No se eludiÃ³ ese control ni se eligiÃ³ otro usuario desde la base de datos.

## DiagnÃ³stico y reparaciones

El NAS tenÃ­a checkout limpio `master` en `4ed7d76`, fuente sin herramienta e
imagen activa que devolvÃ­a `False`. GitHub master estaba en `bb7f535`. El gasto
ya existÃ­a en el read model de nutriciÃ³n; faltaba integrar y desplegar la lectura
AI por fechas. El servicio y contrato se describen en
[AI_ENERGY_BALANCE.md](AI_ENERGY_BALANCE.md).

La auditorÃ­a adicional reprodujo cuatro fallos del provider fake: `26/10`,
`26-10-2026` y `ayer` caÃ­an en una ventana de 30 dÃ­as; `compara octubre contra
septiembre` elegÃ­a septiembre por el orden del catÃ¡logo. Se corrigieron fechas
numÃ©ricas/locales, el orden del mes solicitado, comparaciones no contiguas y
fechas invÃ¡lidas como errores 422 seguros. Se completÃ³ la presentaciÃ³n de
comparaciÃ³n con ingesta, gasto, balance y deltas con denominadores.

Una prueba del proveedor real encontrÃ³ una respuesta en inglÃ©s, pese a una
pregunta en espaÃ±ol. Se aÃ±adiÃ³ una instrucciÃ³n explÃ­cita de idioma, cobertura y
gasto registrado, sin inferir necesidades metabÃ³licas. Otra repeticiÃ³n recibiÃ³
una respuesta remota malformada: el adaptador la rechazÃ³ con 502. No se relajÃ³
el parser; el retesteo real posterior fue satisfactorio. La configuraciÃ³n de
proveedor/modelo existente se conservÃ³; su disponibilidad y variabilidad externas
siguen siendo un lÃ­mite operativo.

## CÃ³digo e integraciÃ³n GitHub

- [PR #42, fusionado](https://github.com/Donbumo/health-tracker/pull/42).
- Commit original: `868431d37839f11f54415d671867af8c1a88c9b7`.
- ReparaciÃ³n de fechas: `bb3d21192324201495548ea2a572cf0642a5617a`.
- PresentaciÃ³n en espaÃ±ol: `41e1884e17458b7f9a9002de0dc5afb68a9e862f`.
- Squash y SHA desplegado de aplicaciÃ³n:
  [`6e7af699a5d46967c0a7e2f46e479e827b180434`](https://github.com/Donbumo/health-tracker/commit/6e7af699a5d46967c0a7e2f46e479e827b180434).
- `git diff` confirmÃ³ que el squash conserva exactamente el Ã¡rbol del head
  probado. Ruleset activo revisado: PR e historia lineal obligatorios, sin
  borrados ni force push, cero aprobaciones externas obligatorias. No se
  deshabilitaron reglas. No habÃ­a Actions/checks aplicables a estos paths de
  backend; el workflow existente se limita a Android.

Cambios de aplicaciÃ³n: `energy_balance.py`, registro/sanitizaciÃ³n en `ai/tools.py`,
manifests de EnergÃ­a/NutriciÃ³n/Resumen, instrucciones de conversaciÃ³n y adaptador
fake. Pruebas: `test_ai_energy_balance.py` y expectativas del registro/templates.
DocumentaciÃ³n: contrato, AI Foundation y este informe. Script de comprobaciÃ³n
MariaDB: `scripts/ai/energy_balance_mariadb_check.py`.

No hay modelos, schemas pÃºblicos, dependencias ni migraciones nuevas. El Ãºnico
head continÃºa en `20261018_0046`. Este informe se versiona despuÃ©s del despliegue;
los commits de cierre documental no cambian el Ã¡rbol de aplicaciÃ³n probado.

## Pruebas y evidencia

| ComprobaciÃ³n ejecutada | PASS | FAIL | ERROR | SKIP |
| --- | ---: | ---: | ---: | ---: |
| Suite general limpia, reparaciÃ³n de fechas | 1852 | 0 | 0 | 35 |
| Suite focal final AI, nutriciÃ³n, energÃ­a y balance tras el ajuste de idioma | 447 | 0 | 0 | 5 |
| MariaDB READ COMMITTED, regresiones de balance | 120 | 0 | 0 | 0 |
| MariaDB REPEATABLE READ, regresiones de balance | 120 | 0 | 0 | 0 |
| Fechas/contrato Responses/errores, retesteo del ajuste final | 62 | 0 | 0 | 0 |

Duraciones: suite general 583.85 s; focal final 108.73 s; MariaDB RC 100.62 s y
RR 101.41 s. Las 58 deselecciones del retesteo focal no son omisiones ni PASS.
Las 35 omisiones generales son gates opt-in de otros dominios/motores y una
prueba de symlink que Windows no permite; las cinco focales corresponden a
integraciones/concurrencia MariaDB opt-in. No se presentan como aprobadas.
Las 120 regresiones de este dominio sÃ­ se ejecutaron sin omisiones en ambos
niveles de aislamiento.

La matriz nueva cubre once expresiones por cinco contextos: chat libre, EnergÃ­a,
NutriciÃ³n, Resumen y ComparaciÃ³n. Incluye cuatro formatos del 26 de octubre,
hoy, ayer, semana pasada, ventanas 7/30 dÃ­as, mes calendario y octubre/septiembre.
Se comprueban argumentos, autorizaciÃ³n, owner, fechas inclusivas, zona,
comparaciÃ³n, precisiÃ³n Decimal, coberturas, ausencia/cero, fuentes duplicadas,
conflictos, resoluciones, tombstones, lÃ­mites y 366 puntos sin truncar.

El antecedente de handoff local de 160 lÃ­neas desaparece con el documento
versionado: su prueba pasa en la suite limpia. La primera extracciÃ³n de QA,
sin fixtures generadas ni objetos histÃ³ricos Git, registrÃ³ 1811 PASS, 37 FAIL,
4 ERROR y 35 SKIP. Eran requisitos de preparaciÃ³n, no regresiones de aplicaciÃ³n:
se generaron las fixtures FIT sintÃ©ticas, se prepararon los ejemplos ficticios
GPX/TCX/CSV documentados y se dio acceso de lectura al object store Git para
las pruebas que reconstruyen importadores histÃ³ricos. Los 41 casos afectados
pasaron y luego se repitiÃ³ toda la suite, con el resultado verde de la tabla.
No se cambiaron aserciones para esconder fallos.

La suite general cubriÃ³ la reparaciÃ³n de fechas. El Ãºltimo cambio posterior
fue de instrucciones de presentaciÃ³n; se repitieron toda la suite focal y las
pruebas del contrato/proveedor real. CompilaciÃ³n Python, Compose config,
`git diff --check`, head Ãºnico y `flask_migrate.check`: PASS.

El adaptador Responses se probÃ³ con HTTP simulado y con el proveedor real
configurado, usando SQLite temporal y datos ficticios en una instancia aislada
del NAS. Se verificaron fechas, totales, balances, denominadores, herramienta y
evidencia. Hubo aserciones iniciales no satisfechas y una respuesta malformada;
no se ocultan como PASS. Tras diagnosticar el idioma y mantener el rechazo seguro
de respuestas invÃ¡lidas, ambos tipos de consulta completaron el recorrido real.

## Respaldo y despliegue NAS

Punto privado de recuperaciÃ³n: `energy-balance-20261108T202043Z`, fuera del
repositorio. Incluye SQL completo, datos persistentes, manifiesto de archivos,
configuraciÃ³n efectiva y referencia de imagen/SHA anteriores. Permisos privados,
espacio de recuperaciÃ³n, tamaÃ±os no vacÃ­os, checksums e integridad verificados.
No se imprimieron secretos ni se leyeron archivos de entorno; Compose utilizÃ³
su configuraciÃ³n existente.

La pausa controlada de web permitiÃ³ un SQL/archivo coherente; se verificÃ³ que
no habÃ­a otros contenedores escritores conectados a esa base y que MariaDB no
publicaba un puerto al host. SQL se restaurÃ³ en una MariaDB descartable sin red,
comparando datos y esquema con el origen. Los archivos se extrajeron y verificaron
por tamaÃ±o, contenido y permisos. El contenedor de restore y la copia de ensayo
se retiraron; los respaldos y la imagen anterior se conservan.

Antes de actualizar se comprobÃ³ de nuevo checkout limpio, `master`, remoto,
backup validado y Ã¡rbol probado. Se hizo fetch y pull `--ff-only`, sin reset ni
force push. La imagen se construyÃ³ sobre la base de paquetes activa, comprobando
que las dependencias no cambiaban. Una configuraciÃ³n privada de Compose mantuvo
los flags y secretos efectivos: el Compose base diferÃ­a del contenedor activo
en un flag de nutriciÃ³n y la versiÃ³n. Se conservÃ³ el arranque Gunicorn existente
y se ejecutÃ³ explÃ­citamente el upgrade oficial, que resultÃ³ compatible en 0046.
SÃ³lo se recreÃ³ web; DB y montajes quedaron intactos.

| Gate productivo | Resultado observado |
| --- | --- |
| Registro dentro del contenedor | **True** |
| CÃ³digo de app/migraciones/schemas cargado | Coincide con master desplegado |
| Salud HTTP | 200 |
| Web | Activa, cero reinicios |
| DB | Saludable, mismo contenedor y volumen |
| Migraciones | 0046; db check PASS |
| Integridad durante cutover | Todas las filas y todos los archivos idÃ©nticos |
| ConfiguraciÃ³n efectiva | Conservada, salvo versiÃ³n de aplicaciÃ³n actualizada |
| Login y lecturas HTTPS | Siete rutas con 200: salud, login, dashboard, balance diario, nutriciÃ³n, energÃ­a y AI |
| Coherencia owner-only con daily-balance | PASS en contexto autenticado disponible; valores ausentes coherentes |
| Pregunta real 26/10 | Tool completada, fecha/cobertura/evidencia/respuesta verificadas; ausencia reconocida |
| ComparaciÃ³n real de Ãºltimos 7 dÃ­as | Tool completada, rango anterior/cobertura/evidencia/respuesta verificadas; ausencia reconocida |
| Integridad tras smoke | Registros de salud idÃ©nticos; sÃ³lo auditorÃ­a/conversaciones AI autorizadas |
| Rollback | No fue necesario; imagen/configuraciÃ³n anterior y backup conservados |

No se crearon fixtures de salud en producciÃ³n, cuentas nuevas, sesiones
suplantadas, instalaciones productivas duplicadas ni accesos persistentes nuevos.
Las consultas AI productivas usaron login real por HTTPS, CSRF y el consentimiento
ya existente. Sus resultados privados no se publican en GitHub ni en este informe.

## LÃ­mite pendiente y estado final

**Ã‰XITO PARCIAL.** PR integrado, respaldo restaurado/verificado, instalaciÃ³n
actualizada, herramienta registrada y asistente real verificado con la cuenta
operativa. Falta comprobar las cifras del propietario del 26/10: esa cuenta no
es accesible mediante una sesiÃ³n controlable disponible y la cuenta operativa
carece de esos registros. El bloqueo de Computer Use fue: no pudo determinar la
URL actual del navegador Windows con suficiente confianza para aplicar su polÃ­tica.
Se detuvieron las acciones de UI, sin bypass ni lectura de cookies/credenciales
del navegador. Esta limitaciÃ³n no se presenta como falta de datos global ni como
fallo del servicio. No se solicita ni se necesita otra intervenciÃ³n para conservar
el despliegue operativo y sus datos.
