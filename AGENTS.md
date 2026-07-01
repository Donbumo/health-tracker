# AGENTS.md

## Proyecto

Este repositorio contiene una aplicación web self-hosted, privada y multiusuario para seguimiento de salud, nutrición, gasto energético, composición corporal, estudios médicos, rutinas, entrenamientos y datos de dispositivos.

El backend principal debe desarrollarse en Python con Flask. La base de datos debe ser MariaDB. El sistema debe correr con Docker Compose.

Lee primero:

* `docs/PROJECT_CONTEXT.md`

Ese archivo contiene la visión completa del producto, arquitectura, módulos, fases, schemas, importadores, exportadores y reglas de privacidad.

## Principios obligatorios

1. La aplicación es multiusuario.
2. Todo dato debe estar asociado a `user_id`.
3. No asumir modo single-user.
4. Todo dato capturado manualmente debe generar primero un archivo JSON estándar.
5. Todo archivo generado/subido debe validarse contra JSON Schema antes de importarse.
6. El sistema debe conservar archivos originales.
7. El sistema debe registrar hash SHA256 para evitar duplicados.
8. El código del repo no debe incluir datos personales reales.
9. `/data`, `.env`, estudios médicos reales, archivos `.fit`, `.pdf`, `.csv`, `.xlsx` reales y exports deben estar ignorados por Git.
10. La app debe estar pensada para uso local o por VPN, no como SaaS público.

## Stack inicial

* Python
* Flask
* Flask-SQLAlchemy
* Flask-Migrate
* MariaDB
* Dockerfile
* docker-compose.yml
* Jinja templates para MVP
* JSON Schema para validación
* Bootstrap o CSS simple para UI inicial

## MVP prioritario

Construir primero:

1. Estructura base del repositorio.
2. Dockerfile.
3. docker-compose con Flask + MariaDB.
4. `.env.example`.
5. `.gitignore` seguro.
6. App Flask mínima.
7. Modelo `User`.
8. Login/logout.
9. Usuario admin inicial desde variables `.env`.
10. Modelo `UploadedFile`.
11. Upload básico de archivos por usuario.
12. Guardado en `/data/uploads/raw/user_<id>/`.
13. Cálculo de SHA256.
14. Registro del archivo en MariaDB.
15. Primer schema JSON de ejemplo.
16. Servicio base de validación.
17. Servicio base de generación de archivos manuales.

## Módulos futuros

No implementar todo al inicio, pero dejar arquitectura preparada para:

* Nutrición diaria.
* Gasto energético.
* Pesajes.
* Estudios médicos.
* Rutinas versionables.
* Sesiones de entrenamiento.
* Sobrecarga progresiva.
* Plan vs realidad.
* Importadores `.fit`, `.json`, `.gpx`, `.tcx`, `.csv`.
* Exportadores JSON, CSV, HTML, PDF, GPX, ZWO, ERG, MRC, FIT experimental.
* Perfil Magene.
* Perfil Huawei companion.
* APK Android companion.
* App de reloj.

## Arquitectura esperada

Usar una estructura parecida a:

```text
backend/
  app/
    auth/
    routes/
    models/
    services/
      files/
      importers/
      exporters/
      training/
      nutrition/
      medical/
    templates/
    static/
  migrations/
  Dockerfile
  requirements.txt

schemas/
examples/
docs/
android-app/
watch-app/
docker-compose.yml
.env.example
.gitignore
README.md
```

## Flujo de datos obligatorio

Todo dato debe seguir este patrón:

```text
archivo subido / captura manual / sync dispositivo
        ↓
conversor o generador
        ↓
archivo JSON estándar interno
        ↓
validación JSON Schema
        ↓
importación a MariaDB
        ↓
dashboard / análisis / exportación
```

## Reglas de privacidad

Nunca incluir datos reales en commits.

Ignorar como mínimo:

```text
.env
data/uploads/raw/*
data/uploads/processed/*
data/uploads/generated/*
data/exports/*
*.fit
*.tcx
*.gpx
*.csv
*.xlsx
*.xls
*.pdf
*.zip
```

Mantener `.gitkeep` donde haga falta para conservar carpetas vacías.

## Estilo de desarrollo

* Hacer cambios pequeños e iterativos.
* Priorizar código funcional y simple.
* No sobrearquitectar antes del MVP.
* Crear modelos y servicios separados.
* Mantener importadores/exportadores como adaptadores independientes.
* Escribir nombres claros en inglés para código.
* Documentar decisiones importantes en `docs/`.
* Cuando haya ambigüedad, implementar la versión más segura y extensible.
