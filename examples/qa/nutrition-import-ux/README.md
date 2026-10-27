# Fixtures ficticias de importación UX

Datos inventados exclusivamente para QA. Sin personas, consumos reales ni fuentes
nutricionales publicadas. `qa_import_ux` es un catálogo sintético de dos alimentos.

- `normal-10.json`: diez comidas de un plan explícito, dos ingredientes cada una,
  identidad/fuente/preparación/revisión, cantidades y declaraciones inequívocas.
- `mixed-13.json`: las anteriores y tres excepciones independientes: cantidad de
  ingrediente ausente, nombre parecido sin identidad verificada y `carbs` sin
  distinción total/neto. No se infiere la cantidad ausente ni equivalencia textual.
- `catalog.json`: base sintética de 100 g, con energía/proteína ficticias y cero
  conocido de vitamina D. Se carga únicamente en SQLite temporal o MariaDB QA
  explícitamente aislada.

Decisiones ficticias de la prueba: introducir 100 g para la cantidad ausente,
elegir deliberadamente la identidad de pollo QA y conservar los carbohidratos
ambiguos como desconocidos. El archivo original permanece intacto.
