# medical_lab manual QA order

1. `insert.json`
2. `repeat.json`
3. `update.json`
4. `batch_valid.json`
5. `invalid.json`
6. `batch_mixed.json`

Expected contract: insert by user/date/laboratory, exact repeat skips, same date/lab with changed markers updates by replacing marker rows, missing date or marker unit is invalid, mixed invalid batch rolls back.

