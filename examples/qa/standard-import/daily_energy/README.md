# daily_energy manual QA order

1. `insert.json`
2. `repeat.json`
3. `update.json`
4. `batch_valid.json`
5. `invalid.json`
6. `batch_mixed.json`

Expected contract: insert by user/date, exact repeat becomes skip, same user/date with changed fields becomes update, missing date is invalid, mixed invalid batch rolls back.

