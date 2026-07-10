# completed_workout manual QA order

1. Create/import a training plan owned by the QA user.
2. Replace `training_plan_id` and `training_plan_version_id` in these fixtures with IDs from that plan.
3. Import `insert.json`.
4. Import `repeat.json` and confirm it becomes explicit conflict.
5. Import `conflict.json`.
6. Import `batch_valid.json`.
7. Import `invalid.json` and `batch_mixed.json`.

Expected contract: completed workout requires an owned, consistent plan/version. Exact repeats and unsafe updates remain explicit conflicts; invalid mixed batches roll back.

