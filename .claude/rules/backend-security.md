---
paths:
  - "backend/src/**/*.py"
  - "backend/alembic/**/*.py"
---

# Backend security rules

- Tenant must come from authenticated security context/session. Never trust tenant identifiers from request payloads when the contract requires session-derived tenant.
- Clinical/assistential authorship and executor identity must come from authenticated identity, not client payload.
- Preserve cross-tenant non-disclosure behavior. Do not weaken 404/no-existence semantics used by current modules.
- Platform Superuser has platform authority, not automatic clinical ILPI access.
- Profession is descriptive data; clinical permissions require explicit RBAC/profile assignment.
- Preserve history for clinical/assistential records. Corrections should use the module's append/estorno/substitution contract rather than destructive overwrite.
- Before changing models, constraints, FKs, indexes or RBAC catalog, inspect the latest migration chain and affected tests.
- Never edit a historical migration to implement a new feature unless the Issue explicitly authorizes a repair strategy; normally create an incremental migration.
- Do not introduce dual sources of truth for resident status, degree of dependency, medication state, PAIS, care occurrence/execution, authorship or tenant.
- Do not create automatic clinical decisions or cross-module automations without an approved operational rule.
