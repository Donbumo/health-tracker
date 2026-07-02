# Contexto del proyecto: Plataforma self-hosted de salud, nutrición, entrenamiento y dispositivos

## Visión general

El proyecto es una aplicación web self-hosted, multiusuario y privada, pensada para ejecutarse localmente o mediante VPN.

El objetivo es centralizar:

- Nutrición diaria.
- Gasto energético.
- Pesajes.
- Composición corporal.
- Estudios médicos.
- Rutinas.
- Entrenamientos.
- Resultados de dispositivos.
- Capturas manuales.
- Importadores y exportadores de archivos.

El backend principal será Python con Flask. La base de datos será MariaDB. El proyecto debe poder levantarse con Docker Compose.

El repositorio de GitHub solo debe contener código, documentación, schemas, ejemplos ficticios, parsers, importadores y exportadores. Los datos reales deben vivir localmente en `/data` y estar ignorados por Git.

---

## Filosofía principal

Todo dato debe entrar por un pipeline común:

```text
Archivo subido
  o
Captura manual
  o
Sincronización desde app/dispositivo
        ↓
Conversor / generador
        ↓
Archivo estándar interno
        ↓
Validación contra JSON Schema
        ↓
Importación a MariaDB
        ↓
Dashboard / análisis / reportes