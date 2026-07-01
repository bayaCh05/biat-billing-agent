# Diagram 10 — Sequence: Authentication Flow
# Paste into Eraser → New Diagram → Sequence Diagram

```
title Flux d'Authentification Complet — BIAT IT Billing Agent

Utilisateur [color: "#1A3A5C", icon: user]
Frontend [color: "#2E86C1", icon: monitor]
FastAPI [color: "#2E86C1", icon: server]
Database [color: "#1A3A5C", icon: database]
EmailService [color: "#1D9E76", icon: mail]

note over Utilisateur, Database: "=== SCÉNARIO 1 — Connexion normale ==="

Utilisateur -> Frontend: "Saisit email + mot de passe"
Frontend -> FastAPI: "POST /api/auth/login\n{email, password}"
FastAPI -> Database: "SELECT user WHERE email=? + check locked_until"

alt "Compte verrouillé"
  FastAPI --> Frontend: "423 Locked\n'Compte verrouillé jusqu'à HH:MM'"
  Frontend --> Utilisateur: "Message de verrouillage"
else "Compte actif"
  FastAPI -> FastAPI: "bcrypt.verify(password, hashed)"
  alt "Mauvais mot de passe"
    FastAPI -> Database: "failed_login_attempts += 1"
    alt "Attempts >= 5"
      FastAPI -> Database: "locked_until = now + 15 min"
    end
    FastAPI --> Frontend: "401 Unauthorized"
  else "Mot de passe correct"
    FastAPI -> Database: "failed_login_attempts = 0"
    FastAPI -> FastAPI: "generate_access_token(8h)\ngenerate_refresh_token(7d)"
    FastAPI -> Database: "save ActiveToken\nsave AuditLog(LOGIN)"
    FastAPI --> Frontend: "200 {access_token, role, is_first_login}\nSet-Cookie: refresh_token (httpOnly)"
    Frontend -> Frontend: "Store token IN MEMORY\n(no localStorage)"
  end
end

note over Utilisateur, Database: "=== SCÉNARIO 2 — Premier login (force change password) ==="

Frontend --> Utilisateur: "is_first_login=true\n→ Redirect /changer-mot-de-passe"
Utilisateur -> Frontend: "Saisit nouveau mot de passe"
Frontend -> FastAPI: "POST /api/auth/change-password\n{current_password, new_password}"
FastAPI -> Database: "UPDATE user SET hashed=bcrypt(new)\nSET is_first_login=false"
FastAPI --> Frontend: "200 OK"
Frontend --> Utilisateur: "✅ Mot de passe mis à jour"

note over Utilisateur, Database: "=== SCÉNARIO 3 — Refresh automatique ==="

Frontend -> Frontend: "Timer: token expires in < 60s"
Frontend -> FastAPI: "POST /api/auth/refresh\n(httpOnly cookie)"
FastAPI -> FastAPI: "Verify refresh token signature\nCheck not revoked"
FastAPI -> FastAPI: "generate_access_token(8h)"
FastAPI --> Frontend: "200 {access_token}"
Frontend -> Frontend: "Update in-memory token"

note over Utilisateur, Database: "=== SCÉNARIO 4 — Déconnexion ==="

Utilisateur -> Frontend: "Clic Déconnexion"
Frontend -> FastAPI: "POST /api/auth/logout"
FastAPI -> Database: "INSERT revoked_tokens(jti)\nsave AuditLog(LOGOUT)"
FastAPI --> Frontend: "200 OK + Clear cookie"
Frontend -> Frontend: "Clear in-memory token\nRedirect /login"

note over Utilisateur, Database: "=== SCÉNARIO 5 — Mot de passe oublié (OTP) ==="

Utilisateur -> Frontend: "Clic 'Mot de passe oublié'"
Frontend -> FastAPI: "POST /api/auth/forgot-password\n{email}"
FastAPI -> Database: "save PasswordVerification(otp, expires_at)"
FastAPI -> EmailService: "send OTP email (Mailhog local)"
FastAPI --> Frontend: "200 OK (message générique)"
Utilisateur -> Frontend: "Saisit OTP reçu par email"
Frontend -> FastAPI: "POST /api/auth/reset-password\n{token, new_password}"
FastAPI -> Database: "Verify OTP + not expired\nUPDATE user password\nDELETE verification"
FastAPI --> Frontend: "200 OK"
Frontend --> Utilisateur: "✅ Mot de passe réinitialisé"
```
