# Prompt para generar un archivo HTNX 1.0

Borrador para copiar desde Health Tracker en una fase posterior del [RFC](NUTRITION_EXCHANGE_RFC.md).

```text
Convierte el registro de comidas que te proporcioné en un único objeto JSON de
Health Tracker Nutrition Exchange 1.0. Devuelve sólo JSON válido, sin Markdown,
comentarios ni cifras inventadas. Usa los datos que ya te di. Si no puedes crear
un archivo, deja el objeto listo para copiar.

Este ejemplo es ficticio y describe la forma del archivo. No copies sus datos.

{
  "format": "health-tracker-nutrition",
  "version": "1.0",
  "destination": "consumed",
  "date": "2030-01-15",
  "meals": [
    {
      "type": "lunch",
      "foods": [
        {
          "name": "Alimento de ejemplo",
          "quantity": {"amount": 150, "unit": "g"},
          "nutrition": {
            "basis": {"amount": 100, "unit": "g"},
            "values": {
              "energy": {"value": 130, "unit": "kcal"},
              "protein": {"value": 2.7, "unit": "g"}
            },
            "quality": "estimated"
          }
        }
      ]
    }
  ]
}

- Usa un grupo por comida y una entrada por alimento o plato. type, si se
  conoce, es breakfast, lunch, dinner, snack u other. Puedes añadir name al
  grupo. Usa fecha YYYY-MM-DD sólo si la conoces. date en una comida prevalece
  sobre date del documento. Usa destination sólo si se conoce: consumed,
  plan, recipe o product.
- En cada alimento incluye name. En quantity, usa amount positivo y unit
  g, ml, portion o piece. Con portion o piece añade label que describa esa
  unidad del alimento. Omite quantity si falta información para describirla.
- En nutrition.basis usa amount y unit para la referencia real, como 100 g.
  Si la referencia es nominal, incluye label. Si los nutrientes ya son el
  total de la quantity indicada, usa {"kind":"consumed"}. Si no conoces la
  base, omite basis y conserva los valores. No escales los valores por tu cuenta.
- Usa números JSON o cadenas decimales simples con punto, hasta 12
  decimales. En una observación con valor incluye value y unit. Un cero
  conocido es 0. Un desconocido explícito se expresa con {"state":"unknown"}.
  Una traza se expresa con state "trace" y unit. Un valor bajo el límite
  se expresa con state "below_limit", unit y limit positivo. Omite value
  en los tres casos. Omite los nutrientes que no aparezcan en la fuente.
- Claves y unidades permitidas en values:
    kcal: energy
    g: protein, carbohydrate_total, net_carbs, fat, fiber, sugar
    mg: sodium, potassium, calcium, iron, magnesium, phosphorus, zinc,
        vitamin_c, vitamin_e_alpha, thiamin, riboflavin, niacin, vitamin_b6, choline
    ug: vitamin_a_rae, retinol, vitamin_a_re, vitamin_d, vitamin_k1, vitamin_k2,
        vitamin_b12, folate_dfe, folate_food
  Conserva otros nutrientes o formas sin equivalencia en
  nutrition.additional_nutrients, una lista de objetos con name y observation
  (la observación tiene los mismos estados y conserva su unidad original).
  No escribas un bloque nutrition si no hay observaciones.
- quality puede ser declared, estimated, label o unknown en nutrition o en
  una observación. Marca estimaciones como estimated, incluidas las obtenidas de imágenes sin
  una medición explícita. Usa label sólo para
  información de etiqueta. Puedes añadir source y note para conservar la
  procedencia o incertidumbre. No supongas equivalencias entre masa, volumen
  y unidad nominal ni entre formas químicas de nutrientes.
- Los ingredientes de un plato van únicamente dentro de ingredients de
  ese plato. Usan name, quantity y nutrition si se conocen. Conserva los
  datos de la fuente si declara un total de plato, sin sumar los ingredientes
  a ese total. No incluyas identificadores de usuario, metadatos de la app,
  campos de confirmación ni suposiciones sobre qué debería guardar.
```
