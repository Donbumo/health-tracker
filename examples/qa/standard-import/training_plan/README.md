# training_plan manual QA order

1. `insert.json`
2. `repeat.json`
3. `update.json`
4. `batch_valid.json`
5. `invalid.json`
6. `batch_mixed.json`

Expected contract: insert creates version 1, exact repeat skips by stable content SHA, update with same plan name creates a new active version, omitted description is preserved, invalid ordering rolls back.

