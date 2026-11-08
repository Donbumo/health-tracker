# Misión de integración y despliegue de AI Energy Balance

Fecha de inicio: 2026-11-08. Entorno productivo: NAS principal.
Vehículo de integración: [PR #42](https://github.com/Donbumo/health-tracker/pull/42).

## Diagnóstico y reparación

El NAS tenía checkout limpio `master` en `4ed7d76`; el fuente y la imagen activa
no registraban `get_energy_balance`. MariaDB estaba saludable y en el único head
`20261018_0046`. GitHub master estaba en `bb7f535`, sin cambios adicionales de base
respecto al PR original. No bastaba con reconstruir la imagen anterior.

La auditoría conserva el servicio canónico y los contratos documentados en
[AI_ENERGY_BALANCE.md](AI_ENERGY_BALANCE.md). El gasto ya existía en el dominio.
Los defectos adicionales reproducidos son propios del adaptador **fake**:

- `26/10`, `26-10-2026` y `ayer` caían en una ventana de 30 días.
- `compara octubre contra septiembre` seleccionaba septiembre por el orden del
  catálogo de meses, en lugar de conservar el primer mes de la petición.
- La presentación de comparación omitía ingesta/gasto del periodo anterior y
  los valores de los deltas de promedios.

Se corrigen las fechas numéricas, ayer local, el orden de meses, errores de fechas
inválidas como 422 seguros y la presentación de comparación. La comparación fake
rechaza meses no contiguos, en vez de cambiar silenciosamente el periodo solicitado.
Las instrucciones y pruebas del adaptador Responses transportan explícitamente
las formas de fecha y el año/zona locales. Esto demuestra el contrato remoto;
la aceptación por un modelo externo exige una prueba real separada.

## QA reproducible

La matriz nueva recorre once expresiones de fecha por chat libre, Energía,
Nutrición, Resumen y Comparación. Usa sólo fixtures ficticias. Incluye los
cuatro formatos de 26 de octubre, hoy, ayer, semana pasada, ventanas 7/30 días,
mes calendario y comparación octubre/septiembre. Se comprueban argumentos,
autorización, tool audit completado, zona y límites anteriores.

Los resultados definitivos de las suites SQLite, MariaDB RC/RR, proveedor real,
integración GitHub y producción se incorporarán al completar cada gate. No se
marca PASS anticipadamente.

## Gates y continuidad durable

| Gate | Estado al preparar la integración |
| --- | --- |
| Auditoría del PR, base y servicios | Completada; sin cambios de modelo/schema/dependencias |
| Reproducción de fechas faltantes | 4 fallos reproducidos, 7 casos aprobados antes de reparar |
| Regresiones de servicio/conversación/Responses | 117 aprobadas tras la reparación inicial; ampliadas con errores seguros |
| GitHub | Ruleset activo: PR, historia lineal, sin borrado ni force push; cero aprobaciones obligatorias; no Actions aplicables al backend |
| NAS principal | Identidad, checkout, compose project, montajes y head 0046 verificados; web/db activos, cero reinicios |
| Configuración efectiva | Provider configurado con key disponible; se preservará en privado. Se detectó diferencia de un flag entre runtime y Compose, que debe conservarse al desplegar |
| Backup, merge y despliegue | Pendientes de los gates de QA finales |

El working tree original contiene cuatro documentos modificados por trabajo ajeno.
Se preservan, no se incorporan al PR y no se usa `reset --hard`. La suite general
se ejecutará en una extracción limpia de los archivos versionados y el cambio
exacto, sin esos documentos locales, para comprobar el antecedente del handoff.

El registro privado durable de operaciones, snapshots de recuperación, resultados
y configuración se mantiene fuera del repositorio. No contiene credenciales en
salidas públicas. No se leen archivos de entorno.

## Política operativa

La actualización mantendrá la misma MariaDB, volumen y montaje de datos. Se
verificará backup consistente, integridad y restauración aislada antes de activar
la nueva imagen. El rollback conservará la imagen anterior y los datos actuales;
nunca restaurará una base antigua encima de nuevas escrituras sin demostrar
ausencia de pérdida. Las comprobaciones personales de lectura sólo usarán un
contexto autenticado disponible, sin elegir ni suplantar usuarios por ID.
