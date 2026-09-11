---
paths:
  - "frontend/**/*.{ts,tsx,js,jsx,css}"
---

# Frontend rules

- Mobile-first: design the interaction for small screens first, then expand to tablet/desktop. Do not treat mobile as a compressed desktop.
- Keep the resident at the center of information architecture and use operational language understandable by ILPI staff with little technical familiarity.
- Frontend talks to the backend API only. It must not become a second source of authorization, tenant, authorship or clinical truth.
- Never trust a hidden/disabled UI control as security; backend permissions remain authoritative.
- Do not send tenant or clinical executor/author values when the backend derives them from session.
- Prefer a restrained institutional visual system: strong hierarchy, few competing colors, large touch targets, accessible contrast and consistent states.
- Preserve functionality at 360/390/430/768/1366 widths and avoid page-level horizontal scrolling.
- Do not create mock business behavior, fake persistence or speculative integrations as part of a visual change unless the Issue explicitly authorizes it.
- Frontend redesign must not silently alter backend contracts, RBAC semantics or clinical workflows.
