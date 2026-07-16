# Solución de problemas para usuario

## No veo un entrenamiento para hoy

Comprueba la agenda y la zona horaria de la cuenta. Planificar congela una versión y un día concretos; activar otra versión no reescribe ese snapshot.

## Cerré el navegador durante una sesión

Vuelve al dashboard o al mismo día planeado. La captura intenta recuperar el borrador compatible. No borres el almacenamiento del navegador mientras estés trabajando.

## La importación falla

Revisa destino detectado, operaciones y advertencias. Corrige el archivo y vuelve a generar el preview. El error no muestra SQL, rutas internas ni el payload completo.

## Importar o restaurar

Importa archivos de dominios concretos en `/imports`. Restaura un backup ZIP solo para recuperación completa y siempre revisa el preview.

## Diagnóstico homelab

Abre `/account/system`, comprueba DB, storage y migración, y revisa logs del contenedor. No publiques la app directamente en Internet: usa VPN o HTTPS y recuerda que el rate limiter actual es por proceso.
