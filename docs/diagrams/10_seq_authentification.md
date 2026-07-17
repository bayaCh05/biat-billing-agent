# Diagram 10 — Sequence: Authentication Flow

**Updated 2026-07-16** — translated to English and fixed a stale detail:
password hashing/verification used `bcrypt.verify`/`bcrypt(new)`; the
actual code (`backend/api/auth.py`) hashes with argon2id, falling back to
bcrypt only to verify pre-migration legacy hashes.

# Paste into Eraser → New Diagram → Sequence Diagram

```
title Complete Authentication Flow — BIAT IT Billing Agent

User [color: "#1A3A5C", icon: user]
Frontend [color: "#2E86C1", icon: monitor]
FastAPI [color: "#2E86C1", icon: server]
Database [color: "#1A3A5C", icon: database]
EmailService [color: "#1D9E76", icon: mail]

note over User, Database: "=== SCENARIO 1 — Normal login ==="

User -> Frontend: "Enters email + password"
Frontend -> FastAPI: "POST /api/auth/login\n{email, password}"
FastAPI -> Database: "SELECT user WHERE email=? + check locked_until"

alt "Account locked"
  FastAPI --> Frontend: "423 Locked\n'Account locked until HH:MM'"
  Frontend --> User: "Lockout message"
else "Account active"
  FastAPI -> FastAPI: "verify_password(password, hashed)\nargon2id, or bcrypt for legacy hashes"
  alt "Wrong password"
    FastAPI -> Database: "failed_login_attempts += 1"
    alt "Attempts >= 5"
      FastAPI -> Database: "locked_until = now + 15 min"
    end
    FastAPI --> Frontend: "401 Unauthorized"
  else "Correct password"
    FastAPI -> Database: "failed_login_attempts = 0"
    FastAPI -> FastAPI: "generate_access_token(8h)\ngenerate_refresh_token(7d)"
    FastAPI -> Database: "save ActiveToken\nsave AuditLog(LOGIN)"
    FastAPI --> Frontend: "200 {access_token, role, is_first_login}\nSet-Cookie: refresh_token (httpOnly)"
    Frontend -> Frontend: "Store token IN MEMORY\n(no localStorage)"
  end
end

note over User, Database: "=== SCENARIO 2 — First login (forced password change) ==="

Frontend --> User: "is_first_login=true\n→ Redirect /change-password"
User -> Frontend: "Enters new password"
Frontend -> FastAPI: "POST /api/auth/change-password\n{current_password, new_password}"
FastAPI -> Database: "UPDATE user SET hashed=argon2id(new)\nSET is_first_login=false"
FastAPI --> Frontend: "200 OK"
Frontend --> User: "✅ Password updated"

note over User, Database: "=== SCENARIO 3 — Automatic refresh ==="

Frontend -> Frontend: "Timer: token expires in < 60s"
Frontend -> FastAPI: "POST /api/auth/refresh\n(httpOnly cookie)"
FastAPI -> FastAPI: "Verify refresh token signature\nCheck not revoked"
FastAPI -> FastAPI: "generate_access_token(8h)"
FastAPI --> Frontend: "200 {access_token}"
Frontend -> Frontend: "Update in-memory token"

note over User, Database: "=== SCENARIO 4 — Logout ==="

User -> Frontend: "Clicks Logout"
Frontend -> FastAPI: "POST /api/auth/logout"
FastAPI -> Database: "INSERT revoked_tokens(jti)\nsave AuditLog(LOGOUT)"
FastAPI --> Frontend: "200 OK + Clear cookie"
Frontend -> Frontend: "Clear in-memory token\nRedirect /login"

note over User, Database: "=== SCENARIO 5 — Forgot password (OTP) ==="

User -> Frontend: "Clicks 'Forgot password'"
Frontend -> FastAPI: "POST /api/auth/forgot-password\n{email}"
FastAPI -> Database: "save PasswordVerification(otp, expires_at)"
FastAPI -> EmailService: "send OTP email (local Mailhog)"
FastAPI --> Frontend: "200 OK (generic message)"
User -> Frontend: "Enters OTP received by email"
Frontend -> FastAPI: "POST /api/auth/reset-password\n{token, new_password}"
FastAPI -> Database: "Verify OTP + not expired\nUPDATE user password\nDELETE verification"
FastAPI --> Frontend: "200 OK"
Frontend --> User: "✅ Password reset"
```
