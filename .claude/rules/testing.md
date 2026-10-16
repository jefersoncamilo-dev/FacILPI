---
paths:
  - "backend/tests/**/*.py"
  - "backend/src/**/*.py"
---

# Testing rules

- Automated backend tests must never read, copy, migrate, seed or depend on `storage/app.db` or `backend/storage/app.db`.
- Reuse the repository's disposable database guards/fixtures. Do not bypass target validation to make a test run.
- Classify the database target before destructive setup: only `DISPOSABLE_TEST` may be reset or recreated by automated tests.
- Prefer the smallest test that proves the changed behavior. Then run directly affected historical tests. Use PostgreSQL disposable when schema, FK, constraint, tenant or RBAC behavior requires it.
- Run the full regression once at the final gate when required, not after every edit.
- Never delete or skip a failing test merely to get green. Never weaken an assertion, broaden tolerance, change fixtures to hide a defect, or hardcode the implementation to test values.
- If a test conflicts with an approved functional contract, stop and report the conflict with evidence rather than changing product behavior blindly.
- Avoid repeating the same failing command without a new hypothesis or change. After at most two justified attempts with the same unresolved symptom, stop and report.
