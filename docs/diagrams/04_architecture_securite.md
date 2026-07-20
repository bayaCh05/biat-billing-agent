# Diagram 4 — Security Architecture

**Updated 2026-07-16** — Layer 4 said "bcrypt password hashing"; the actual
code (`backend/api/auth.py`) hashes new passwords with argon2id and only
uses bcrypt to verify pre-migration legacy hashes.

**Updated 2026-07-20**: Layer 3 named a single "SecurityMiddleware" node.
That was imprecise about the mechanism (corrected below), and an earlier
version of this note additionally overstated a related finding's severity
— corrected here too, since it was wrong: `GET /ai/health-summary` and
`POST /ai/suggest-mitigation` were **not** reachable by anonymous callers.
Every protected router is included in `api/main.py` via
`app.include_router(router, prefix="/api", dependencies=_PROTECTED)`
where `_PROTECTED = [Depends(get_current_user)]` — FastAPI applies that to
every route added through that call, confirmed live (`GET /api/kpi`, which
has no `Depends` of its own, correctly returns 401 unauthenticated). Both
routes already required a valid access token; the actual gap was narrower:
they were missing their own `require_role(...)`, so any authenticated user
of *any* role could call them, not just the intended ones — fixed
2026-07-20 (`backend/api/routers/ai.py`).

Real remaining gap, closed the same day: that per-router protection only
works if every `include_router()` call remembers `dependencies=_PROTECTED`
— nothing stops a future router from being added without it. Added
`RequireAuthMiddleware` (`api/security/auth_middleware.py`) as an ASGI-level
safety net: it runs before routing/dependency resolution, so it protects
any `/api/*` path by default — including a brand-new, entirely unprotected
router — regardless of whether that router's registration remembers the
parameter. It checks authentication only (valid, non-revoked token); role
authorization stays a per-route `require_role()` concern. See the updated
Layer 3 below.

# Paste into Eraser → New Diagram → Flowchart

```mermaid
flowchart TB
  classDef layer1 fill:#C0391B,color:#fff,stroke:none
  classDef layer2 fill:#1A3A5C,color:#fff,stroke:none
  classDef layer3 fill:#2E86C1,color:#fff,stroke:none
  classDef layer4 fill:#1D9E76,color:#fff,stroke:none
  classDef layer5 fill:#804CD7,color:#fff,stroke:none

  Request(["🌐 HTTP Request"])

  subgraph L1["Layer 1 — Network"]
    CORS["CORS\norigins: localhost:5173/5174/4173"]
    Rate["SlowAPI Rate Limiting\n10 req/min (upload)\n60 req/min (default)"]
    Headers["Security Headers\nCSP · X-Frame-Options: DENY\nX-XSS-Protection · Referrer-Policy"]
  end

  subgraph L2["Layer 2 — Authentication"]
    JWT["JWT Access Token\n8h lifetime · in-memory only"]
    Refresh["JWT Refresh Token\n7 days · httpOnly cookie"]
    Revoke["Token Revocation\nrevoked_tokens table"]
    Lockout["Account Lockout\n5 failures → 15 min lock\nfailed_login_attempts counter"]
  end

  subgraph L3["Layer 3 — Authorization"]
    ProtectedDeps["dependencies=_PROTECTED\non every app.include_router()\n(Depends(get_current_user)) — per-router,\nnot a global default"]
    AuthMW["RequireAuthMiddleware (ASGI)\nSafety net: any /api/* path requires\na valid token by default, even a\nrouter that forgets the above"]
    RequireRole["require_role() Depends\nper-route — role authorization,\nnarrower than authentication"]
    RBAC["4 Roles × N endpoints\nADMIN · COMPTABLE\nCHEF_PROJET · DIRECTION"]
    AuthMW --> ProtectedDeps --> RequireRole
  end

  subgraph L4["Layer 4 — Data Protection"]
    Bcrypt["argon2id password hashing\n(bcrypt kept for legacy verification only)"]
    FileVal["File validation\nMIME magic bytes check\nMax size · extension filter"]
    Sanitize["Input sanitization\nLength limits · XSS patterns\nSQL injection via ORM only"]
    NoLeak["No sensitive fields\nin API responses"]
  end

  subgraph L5["Layer 5 — Audit & Integrity"]
    AuditLog["AuditLog table\nAppend-only (no DELETE)\nAll auth events + IP"]
    HMAC["HMAC-SHA256 row hash\nTamper detection per row"]
    Verify["GET /audit/verify-integrity\nAdmin only endpoint"]
    Events["Events logged:\nLOGIN · LOGOUT · FILE_REJECTED\nINVOICE_UPLOADED · REVIEW_ACTION"]
  end

  Request --> L1 --> L2 --> L3 --> L4
  L3 --> L5
  JWT <--> Revoke
  Lockout --> JWT

  style L1 fill:#FEF0EE,stroke:#C0391B
  style L2 fill:#E8F0FA,stroke:#1A3A5C
  style L3 fill:#E3F0F9,stroke:#2E86C1
  style L4 fill:#E6F9F3,stroke:#1D9E76
  style L5 fill:#F3EEF9,stroke:#804CD7
```
