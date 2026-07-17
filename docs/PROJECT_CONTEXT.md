# Contexto estable del producto

Este documento es contexto frío. Explica la visión y los límites duraderos de Health Tracker; no contiene el estado de una rama, resultados temporales de QA ni instrucciones obligatorias para toda tarea.

Para trabajo en curso consulta `ACTIVE_HANDOFF.md`. Para localizar contratos y guías usa `DOCUMENTATION_INDEX.md`. La arquitectura ejecutable resumida está en `architecture/OVERVIEW.md`.

## Visión

Health Tracker es una plataforma privada, self-hosted y multiusuario para normalizar, conservar, analizar e intercambiar datos personales de salud y entrenamiento.

Centraliza, según el soporte real del código:

- nutrición y gasto energético;
- peso y composición corporal;
- laboratorios y marcadores;
- alimentos y recetas;
- rutinas, sesiones, progreso y actividades;
- archivos originales, imports, exports y backups;
- sincronización con clientes companion mediante contratos versionados.

No está diseñado como SaaS público. El despliegue esperado es local o mediante una red/VPN privada administrada por el usuario.

## Diferenciador

El valor principal es un pipeline trazable, no solo el dashboard:

```text
capturar o recibir
  → normalizar a un contrato estándar
  → validar
  → persistir con ownership
  → analizar
  → exportar o sincronizar
  → reimportar sin perder el contrato
```

En entrenamiento, la dirección de producto es:

```text
planear → exportar/entregar → ejecutar → importar resultado → comparar → ajustar
```

## Principios permanentes

1. Cada usuario tiene login y datos separados.
2. Todo registro sensible y archivo pertenece a un `user_id` efectivo del servidor.
3. Los archivos originales y SHA256 permiten rastrear el origen cuando el flujo lo requiere.
4. Las capturas manuales y adaptadores producen JSON estándar antes de persistir dominio.
5. Los JSON Schemas versionados son el contrato público importable/exportable.
6. Los aliases externos nunca contaminan el JSON estándar.
7. Preview, detección y generación asistida permanecen separados de la escritura.
8. Import/export debe declarar dedupe, update y pérdida de información.
9. Los formatos y dispositivos no soportados se declaran honestamente; no se fabrican datos.
10. Git solo contiene código, documentación y fixtures ficticias.

Las reglas ejecutables de estos principios viven en `../AGENTS.md`, `schemas/AGENTS.md` y `project-rules/`.

## Plataforma técnica

- Backend: Python y Flask.
- UI: Flask/Jinja/CSS con mejora progresiva.
- Persistencia: SQLAlchemy/Flask-SQLAlchemy y MariaDB.
- Migraciones: Alembic/Flask-Migrate.
- Validación: JSON Schema.
- Ejecución: Docker Compose; SQLite se usa en pruebas donde corresponde.
- Archivos: storage local por usuario para raw, generated, exports y backups.

La estructura real del código manda sobre diagramas o rutas narrativas antiguas. Consulta `architecture/OVERVIEW.md` y el árbol del repositorio en vez de copiar una estructura sugerida a nuevas tareas.

## Capacidades de producto

### Identidad y archivos

El sistema ofrece autenticación web, administración básica, dispositivos/API, uploads con SHA256, estados de importación y aislamiento owner-only.

### Bienestar y salud

Incluye contratos y flujos para peso/composición, nutrición, energía, alimentos, recetas y laboratorios. La aplicación conserva y muestra datos; no sustituye evaluación médica ni debe emitir diagnósticos.

### Entrenamiento

Las rutinas son versionables y las sesiones realizadas conservan la versión histórica del plan. El sistema registra sets, carga, reps, RIR/RPE y otros campos soportados, compara plan vs realidad y calcula métricas descriptivas de progreso.

Las cargas avanzadas mantienen `weight_kg` como total normalizado compatible y usan detalle opcional versionado. Consulta las reglas de entrenamiento antes de cambiar ese contrato.

### Importación

Los JSON estándar pasan por su schema e importador oficial. Los JSON no estándar pueden usar detección, mapping y generación canónica en preview. FIT/GPX/TCX/CSV soportados pasan por parsers que generan JSON estándar antes del commit confirmado.

### Exportación y portabilidad

Los exporters declaran capability, warnings y pérdidas. Los artefactos persistidos guardan owner, formato, tamaño y SHA256. El export de cuenta y el backup ZIP agregan portabilidad sin permitir que IDs o paths del archivo elijan el usuario destino.

### API y companion

`/api/v1` usa Bearer independiente de la sesión web, UUID públicos y contratos versionados. Mobile Sync y Companion backend soportan los dominios y operaciones expresamente documentados; no implican que exista una aplicación móvil o de reloj.

## Seguridad y privacidad de producto

- Login incluso en red local.
- Exposición pública directa fuera del alcance; usar red privada/VPN o infraestructura revisada.
- No registrar credenciales, tokens, payloads clínicos ni contenido sensible completo.
- Descargas y consultas filtran por owner; recursos ajenos responden sin revelar existencia.
- Backups y exports no incluyen contraseñas, sesiones ni secretos.
- Fixtures, ejemplos y QA usan identidades y datos ficticios.

## Fuera de alcance actual

Salvo evidencia nueva en código y pruebas, no considerar implementados:

- APK Android o app de reloj;
- Bluetooth o bridge con reloj;
- telemetría continua;
- FIT binario de salida;
- APIs privadas o scraping de fabricantes;
- OCR/FHIR o interpretación clínica;
- operación como SaaS público.

El trabajo futuro vive en `ROADMAP.md`, no en instrucciones operativas.

## Fuentes de verdad

1. Schemas para contratos JSON públicos.
2. Pruebas para comportamiento vigente.
3. Reglas en `project-rules/` para invariantes de dominio.
4. Código para implementación actual.
5. Este documento para visión y límites estables.
6. `history/` para trazabilidad, nunca para redefinir el presente.

Consulta `DOCUMENTATION_INDEX.md` para el mapa completo por dominio.
