# Arquitectura vigente

## Sistema

Health Tracker es una plataforma self-hosted y multiusuario: backend Flask/Jinja con SQLAlchemy, Alembic, MariaDB y Docker Compose, más un cliente Android nativo Kotlin/Compose. El repositorio contiene código, schemas, documentación y fixtures ficticias; los datos reales viven fuera de Git.

## Flujo de datos

```text
upload, captura manual o sincronización
  → parser/conversor/generador
  → JSON estándar canónico
  → JSON Schema
  → preview y confirmación cuando corresponda
  → servicio/importador oficial
  → MariaDB
  → export, análisis o sincronización
```

Separaciones obligatorias:

- parsers, detectores y generadores no escriben dominio;
- preview no hace commit;
- el usuario efectivo proviene de sesión/Bearer, no del payload;
- escritura batch confirmada conserva atomicidad y auditoría;
- archivos raw/generated/exportados pertenecen a un usuario y conservan integridad mediante SHA256.

## Capas principales

- `backend/app/models/`: persistencia y ownership.
- `backend/app/services/importers/`: detección, generación estándar, preview y ejecución confirmada.
- `backend/app/services/exporters/`: capability, render y formatos por dominio.
- `backend/app/api_v1/`: Bearer, dispositivos, sync y protocolo companion.
- `backend/app/templates/` y `static/`: web diaria con mejora progresiva.
- `android/app/`: cliente móvil, cache Room aislada por cuenta, cola offline y WorkManager.
- `schemas/`: contratos JSON públicos versionados.
- `backend/migrations/`: historial Alembic.

## Dominios implementados

Auth/usuarios, uploads, peso/composición, nutrición/energía, alimentos/recetas, laboratorios, rutinas/sesiones/progreso, actividades/rutas, importación estándar y de archivos reales, exports, portabilidad/backup, API v1, Mobile Sync, planned workouts, backend Companion y cliente Android Companion.

Los detalles vigentes pertenecen al código y a las reglas enlazadas desde `../DOCUMENTATION_INDEX.md`; esta vista no duplica matrices de campos, rutas o capabilities.

## Límites

El código Android todavía requiere compilación/QA con el toolchain externo y no hay APK firmado/publicado. No hay app de reloj, Bluetooth, telemetría continua, FIT de salida ni integraciones privadas de fabricantes. Consulta `../ROADMAP.md` para trabajo futuro y `../PROJECT_CONTEXT.md` para visión y límites de producto.
