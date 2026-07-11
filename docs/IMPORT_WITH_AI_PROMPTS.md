# Preparar JSON de importación con prompts para IA

Health Tracker incluye ayudas de “prompt base” en `/imports/standard` para preparar archivos JSON compatibles con los schemas internos.

La app no integra ninguna API de IA. No envía tus datos a proveedores externos, no guarda el texto que copias y no almacena el contenido del prompt usado. El usuario decide si copia el prompt y dónde lo usa.

## Flujo recomendado

1. Inicia sesión.
2. Abre `/imports/standard`.
3. Despliega **Preparar archivo con IA**.
4. Elige el tipo de importación.
5. Copia el prompt base o la plantilla JSON.
6. Pega en la IA externa solo los datos ficticios o personales mínimos que tú decidas compartir.
7. Pide que devuelva únicamente JSON válido, sin Markdown ni explicaciones.
8. Revisa manualmente el JSON devuelto.
9. Súbelo de nuevo en `/imports/standard`.
10. Revisa el preview y el plan antes de confirmar la importación.

## Targets soportados

- `weigh_in_batch`
- `food_products`
- `daily_energy`
- `daily_nutrition`
- `completed_workout`
- `medical_lab`
- `training_plan`
- `recipe`
- `recipe_bundle`

## Reglas importantes

- No pegues información personal que no sea necesaria.
- No compartas `.env`, contraseñas, tokens, rutas internas ni exports completos sin revisar.
- No aceptes valores inventados por una IA.
- Si faltan campos requeridos, corrige el JSON antes de confirmar.
- Reemplaza marcadores como `REEMPLAZAR_USER_ID`, `REEMPLAZAR_PLAN_ID` o `REEMPLAZAR_PLAN_VERSION_ID` solo con IDs obtenidos dentro de Health Tracker.
- Para `completed_workout`, no inventes IDs de rutina o versión.
- Para recetas y nutrición, no inventes `food_product_id` o `recipe_id`; usa nombres si no conoces el ID.
- Para laboratorios, no uses la IA para diagnosticar ni interpretar clínicamente.

## Privacidad

Texto mostrado en la UI:

> Health Tracker no envía tus datos a ninguna IA. Este prompt se copia localmente para que tú decidas dónde usarlo. Evita compartir información personal que no sea necesaria.

No se afirma privacidad ni cumplimiento legal de proveedores externos. Si usas una IA externa, revisa sus políticas por separado.

## Limitaciones

- Los prompts son ayudas para preparar JSON; no garantizan exactitud.
- La IA puede equivocarse, omitir campos o inventar valores.
- El preview de Health Tracker sigue siendo obligatorio antes de confirmar.
- El catálogo de prompts debe mantenerse alineado con los schemas en `schemas/`.
- No hay restore completo ni importación desde texto libre; el resultado final debe ser JSON.
