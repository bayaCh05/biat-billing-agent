"""Email service — sends OTP codes and password reset links via SMTP.

Configuration (env vars or .env file):
    SMTP_HOST=localhost
    SMTP_PORT=1025
    SMTP_FROM=noreply@biat-it.local
    SMTP_USE_TLS=false          # set to "true" for production TLS
    SMTP_USERNAME=              # leave empty for Mailhog/Maildev
    SMTP_PASSWORD=              # leave empty for Mailhog/Maildev
    EMAIL_ENABLED=true          # set to "false" to skip sending (logs to stdout)
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_log = logging.getLogger(__name__)

_HOST     = os.getenv("SMTP_HOST", "localhost")
_PORT     = int(os.getenv("SMTP_PORT", "1025"))
_FROM     = os.getenv("SMTP_FROM", "noreply@biat-it.local")
_USE_TLS  = os.getenv("SMTP_USE_TLS", "false").lower() == "true"
_USERNAME = os.getenv("SMTP_USERNAME", "")
_PASSWORD = os.getenv("SMTP_PASSWORD", "")
_ENABLED  = os.getenv("EMAIL_ENABLED", "true").lower() == "true"


def _send(to: str, subject: str, html: str) -> None:
    """Internal send helper — logs and no-ops if EMAIL_ENABLED=false."""
    if not _ENABLED:
        _log.info("[EMAIL DISABLED] To: %s | Subject: %s", to, subject)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = _FROM
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if _USE_TLS:
            with smtplib.SMTP_SSL(_HOST, _PORT) as smtp:
                if _USERNAME:
                    smtp.login(_USERNAME, _PASSWORD)
                smtp.sendmail(_FROM, [to], msg.as_string())
        else:
            with smtplib.SMTP(_HOST, _PORT) as smtp:
                if _USERNAME:
                    smtp.login(_USERNAME, _PASSWORD)
                smtp.sendmail(_FROM, [to], msg.as_string())
        _log.info("Email envoyé → %s | %s", to, subject)
    except Exception as exc:
        _log.error("Échec envoi email → %s: %s", to, exc)


def send_otp_email(to: str, code: str, purpose_label: str) -> None:
    """Send a 6-digit OTP code email (French)."""
    subject = f"[BIAT IT] Code de vérification — {code}"
    html = f"""
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F0F4F9;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 16px;">
      <table width="480" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(26,58,92,0.10);">
        <!-- Header -->
        <tr>
          <td style="background:#1A3A5C;border-radius:16px 16px 0 0;padding:32px;text-align:center;">
            <p style="margin:0;color:#F0A600;font-size:11px;letter-spacing:3px;font-weight:700;text-transform:uppercase;">
              BIAT INNOVATION &amp; TECHNOLOGY
            </p>
            <h1 style="margin:12px 0 0;color:#fff;font-size:24px;font-weight:700;">
              Code de vérification
            </h1>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:36px 40px;">
            <p style="margin:0 0 20px;color:#374151;font-size:15px;line-height:1.6;">
              Vous avez demandé un changement de mot de passe
              <strong>({purpose_label})</strong>.<br>
              Utilisez le code ci-dessous pour confirmer cette action.
            </p>
            <!-- OTP code box -->
            <div style="background:#F5F8FC;border:2px solid #D5E8F5;border-radius:12px;
                        padding:24px;text-align:center;margin:28px 0;">
              <p style="margin:0 0 8px;color:#5D6D7E;font-size:12px;text-transform:uppercase;letter-spacing:2px;">
                Votre code
              </p>
              <p style="margin:0;font-size:42px;font-weight:900;letter-spacing:12px;color:#1A3A5C;">
                {code}
              </p>
            </div>
            <p style="margin:0;color:#5D6D7E;font-size:13px;text-align:center;">
              Ce code expire dans <strong>10 minutes</strong>.
              Ne le partagez avec personne.
            </p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#F5F8FC;border-radius:0 0 16px 16px;padding:20px 40px;text-align:center;">
            <p style="margin:0;color:#9BAFBF;font-size:11px;">
              Si vous n'avez pas demandé ce changement, ignorez cet email.<br>
              © 2026 BIAT Innovation &amp; Technology — Système sécurisé
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    _send(to, subject, html)


def send_reset_link_email(to: str, link: str) -> None:
    """Send a password reset link email (French)."""
    subject = "[BIAT IT] Réinitialisation de mot de passe"
    html = f"""
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F0F4F9;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 16px;">
      <table width="480" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(26,58,92,0.10);">
        <!-- Header -->
        <tr>
          <td style="background:#1A3A5C;border-radius:16px 16px 0 0;padding:32px;text-align:center;">
            <p style="margin:0;color:#F0A600;font-size:11px;letter-spacing:3px;font-weight:700;text-transform:uppercase;">
              BIAT INNOVATION &amp; TECHNOLOGY
            </p>
            <h1 style="margin:12px 0 0;color:#fff;font-size:24px;font-weight:700;">
              Réinitialisation du mot de passe
            </h1>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:36px 40px;">
            <p style="margin:0 0 24px;color:#374151;font-size:15px;line-height:1.6;">
              Nous avons reçu une demande de réinitialisation de votre mot de passe.<br>
              Cliquez sur le bouton ci-dessous pour définir un nouveau mot de passe.
            </p>
            <!-- CTA button -->
            <div style="text-align:center;margin:32px 0;">
              <a href="{link}" target="_blank"
                 style="background:#1A3A5C;color:#fff;text-decoration:none;
                        font-size:15px;font-weight:700;padding:14px 36px;
                        border-radius:10px;display:inline-block;">
                Réinitialiser mon mot de passe
              </a>
            </div>
            <p style="margin:0 0 12px;color:#5D6D7E;font-size:12px;text-align:center;">
              Ce lien expire dans <strong>1 heure</strong>.
            </p>
            <p style="margin:0;color:#9BAFBF;font-size:11px;text-align:center;word-break:break-all;">
              {link}
            </p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#F5F8FC;border-radius:0 0 16px 16px;padding:20px 40px;text-align:center;">
            <p style="margin:0;color:#9BAFBF;font-size:11px;">
              Si vous n'avez pas demandé cette réinitialisation, ignorez cet email.<br>
              © 2026 BIAT Innovation &amp; Technology — Système sécurisé
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    _send(to, subject, html)
