# QA fixtures for confirmed standard import

These are fictional fixtures for manual QA of `/imports/standard`.

Order suggested:

1. Import `insert.json`.
2. Import `repeat.json` and confirm it becomes `skip` or explicit conflict according to the domain contract.
3. Import `update.json` or `conflict.json`.
4. Import `batch_valid.json`.
5. Import `invalid.json` and `batch_mixed.json` to verify errors and rollback.

Notes:

- These files use fictitious data only.
- `user_id` is a placeholder. For direct standard JSON import, replace it with the authenticated test user's database id.
- `completed_workout` also contains placeholder `training_plan_id` and `training_plan_version_id`; replace them with IDs from a training plan owned by the test user.
- Do not copy these fixtures into `/data`.
- Do not use real health, medical, nutrition, or training data.

