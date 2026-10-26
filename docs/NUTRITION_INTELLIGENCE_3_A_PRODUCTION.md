# Nutrition Intelligence 3.0 A — cierre productivo

26-10-2026, America/Mexico_City. **A operativa**, después de integrar el
[PR #27](https://github.com/Donbumo/health-tracker/pull/27) favorablemente revisado.

| Identidad verificada | Resultado |
| --- | --- |
| HEAD revisado | `8b959d8ba26cf0ed954260a061ecf69bf68c470c` |
| Squash GitHub / Windows master / NAS master | `2f0275ba6c86b14a797a7671b43b6257282886ac` |
| Imagen activa NAS, ID de configuración | `sha256:adfb59b115705746d24f444e0aba8d75cbf32a8cc4f3ad09e72fb160a563ea66` |
| Manifiesto OCI de la misma imagen en Docker Desktop QA | `sha256:0528dc1079ec1f012a9842068b7e8a05063a63b342a8bc687efe0ec7b1d2d2ab` |
| Imagen anterior Unified Summary, conservada | `sha256:6e47b07df963f3f347cad7fadad2244ea7f11bfddf79b45075b9e7173c48c195` |
| Alembic / comprobación | `20261018_0046` / db check PASS |

Ruleset `Protect master` activo, PR e historial lineal obligatorios, squash
permitido y sin bypass. La integración se envió con expected head exacto.
Sin conflictos ni checks GitHub registrados. El squash conserva el árbol del
HEAD revisado. Windows/NAS avanzaron por fast-forward y conservaron archivos
operativos y documentos anteriores no versionados. La rama B se abrió después
del cierre, desde ese squash; no redefine el master desplegado.

## Imagen y gate aislado

Imagen construida sin caché sobre el runtime anterior inmutable: Python 3.12,
linux/amd64, sin instalar ni actualizar dependencias. `pip check` PASS y freeze
idéntico al anterior. Los **541 archivos** app/migraciones/schemas coinciden con
Git. Export, SHA256, recarga, blob de configuración, rootfs y plataforma de la
copia usada en QA contrastados: no se probó una reconstrucción diferente.

MariaDB LOCAL aislada en 0046, con usuarios y datos ficticios: `db check` y smoke
Flask autenticado PASS en READ COMMITTED y REPEATABLE READ. Completo, parcial,
desconocido, cero, trace, below_limit, snapshots tras editar receta/producto,
proyección sin duplicar, períodos 7/30/90 y dos owners PASS. SQL instrumentado:
cero DML/DDL durante GET. Nutrition, dashboard, Energy y legacy PASS. No se
repitieron suites generales ni campañas de accesibilidad o Energy 2.0.

## Backup y restore

Backup consistente nuevo **`nutrition3-a-20261026T211943Z`**, **283,748,691 bytes**,
DB y storage. Mantenimiento 503 con escritores drenados y cero transacciones
activas. Checksums PASS. Restore en schema/storage independientes: todas las
tablas, columnas, índices y filas idénticos, **2,026 archivos idénticos byte a byte**.
La candidata pasó db check sobre el clon con cuenta limitada a SELECT.

Se preservan el primer backup de esta operación, el definitivo, los seis conjuntos
anteriores comprobados y la imagen productiva anterior. Dumps, inventarios de
filas, credenciales, storage y logs detallados permanecen privados en NAS.
No se copiaron datos personales a Windows/Git ni se restauró sobre producción.

## Activación, smoke e integridad

Únicamente web fue recreada mediante el Compose principal y override operativo.
La imagen efectiva y APP_VERSION coinciden con el squash. Mismo contenedor y
volumen MariaDB; mounts, puertos, secretos y flags intactos. Arranque Gunicorn
directo, sin upgrade, seed, downgrade ni stamp.

Login real con CSRF/cookies en memoria y lecturas HTTP interno/HTTPS con TLS:

- Micronutrientes 7/30/90, tablas, cobertura y denominadores: 200 en ambos protocolos.
- Paridad del resumen diario con el servicio oficial; GET Flask instrumentados sin DML.
- MealLog inexistente: 404 correcto. La cuenta operativa no tenía MealLogs propios:
  estados especiales y desglose/snapshots poblados se verificaron en QA aislada,
  sin insertar fixtures ni suplantar otras cuentas productivas.
- Nutrition 2.1, Unified Summary 7/30/90, Hoy, Coach/assets y Energy A/B/C/D: PASS.
- Tres entradas legacy: PASS. Cero POST de dominio; sólo autenticación.

Después del smoke, DB completa y storage permanecen idénticos al backup fresco.
Catálogo activo: **13,685**. Flags: Nutrition Intelligence true, lookup externo
false, AI true. Cero nuevos ERROR/Traceback/HTTP 5xx y reinicios en los **22.8 s**
del cierre inicial; la comprobación posterior sólo revisa runtime/salud y no
compara escrituras legítimas posteriores contra ese backup.

## Incidencias del arnés y alcance de privacidad

El primer comprobador exigía por suposición la cabecera de Energy
`private, no-store` también en Nutrition. La comparación aislada y HTTP/HTTPS
del baseline mostró el comportamiento existente: **Nutrition anterior y A tienen
Vary: Cookie y no emiten Cache-Control explícito**. Se corrigió el arnés para
verificar ese baseline y ausencia de directiva public, sin alterar el código
revisado. No se afirma que A haya incorporado no-store. Ese endurecimiento queda
implementado en B para revisión y todavía no está desplegado.

La primera copia de la corrección no se aplicó por CRLF; después, una guarda
impidió reutilizar el archivo privado de configuración del probe. Se corrigieron
únicamente scripts operativos, se verificaron sus prerrequisitos y se conservaron
los diagnósticos. Cada intento fallido recuperó automáticamente la imagen anterior
compatible con DB/storage actuales. No hubo restauración de datos, DDL ni cambios
de producto. Antes de reintentar se verificó nuevamente que la DB drenada seguía
idéntica al backup fresco cuyo restore ya había pasado.

Otros ajustes del arnés QA: contexto CSRF entre clientes ficticios y dependencia
de una búsqueda del catálogo QA anterior; se corrigieron sin cambiar el producto.

## Evidencia y continuidad

[Cierre agregado](../design/nutrition-intelligence-3-a/release-qa/closeout.json),
[identidad de imagen](../design/nutrition-intelligence-3-a/release-qa/image-transfer.json),
[MariaDB QA](../design/nutrition-intelligence-3-a/release-qa/mariadb.json),
[baseline de cabeceras](../design/nutrition-intelligence-3-a/release-qa/cache-baseline.json),
[comprobación final de runtime](../design/nutrition-intelligence-3-a/release-qa/final-runtime.json).
Los registros públicos contienen sólo resultados agregados, sin valores personales.

La comprobación final de las 15:33 de México confirmó la misma imagen A, healthz
200, 0046, flags y mismo contenedor/volumen MariaDB; cero errores nuevos, 5xx y
reinicios en los logs de esa instancia. B no está desplegada. No se compararon
escrituras legítimas posteriores contra el backup anterior.

Recuperación: sólo imagen anterior compatible sobre DB/storage actuales; nunca
restaurar un backup antiguo sobre escrituras nuevas. No se modificaron migraciones,
schemas o contratos móviles. Zoom/TTL y ausencia de certificación WCAG completa
conservan la deuda conocida anterior. B queda en rama/PR independientes, sin
autorización de merge ni despliegue automático.
