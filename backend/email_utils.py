"""
Transactional email over Gmail SMTP (standard-library ``smtplib``).

Only one message is sent today: the address-verification email dispatched from
``POST /auth/register``. Credentials come from ``config.settings`` (SMTP_HOST /
SMTP_PORT / SMTP_USER / SMTP_PASS / SMTP_FROM). Port 465 uses implicit SSL;
any other port (typically 587) uses STARTTLS.

``send_verification_email`` raises on failure — callers run it from a FastAPI
background task and log, rather than failing the registration response.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from config import settings

logger = logging.getLogger(__name__)

_SUBJECT = "Verify your email for xShotAI"


def build_verification_url(token: str) -> str:
    """`{FRONTEND_URL}/verify-email?token=...` with a normalised base."""
    return f"{settings.frontend_base_url}/verify-email?token={token}"


def _plain_body(username: str, verify_url: str) -> str:
    return (
        f"Hi {username},\n\n"
        "Welcome to xShotAI!\n\n"
        "Please confirm your email address by opening the link below to "
        "complete your registration and activate your account:\n\n"
        f"{verify_url}\n\n"
        "This link will expire in 24 hours.\n\n"
        "If you didn't create an account with xShotAI, you can safely ignore "
        "this email.\n\n"
        "Best regards,\n"
        "The xShotAI Team\n"
    )


def _html_body(username: str, verify_url: str) -> str:
    # Inline styles only — email clients strip <style> blocks and external CSS.
    return f"""\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#0f0f11;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background:#0f0f11;padding:32px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="440" cellpadding="0" cellspacing="0"
                 style="max-width:440px;width:100%;background:#16161a;border-radius:16px;
                        border:1px solid rgba(255,255,255,0.08);padding:32px;
                        font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
                        color:#f4f4f5;">
            <tr><td style="font-size:20px;font-weight:700;padding-bottom:8px;">
              xShot<span style="color:#ff6b2c;">AI</span>
            </td></tr>
            <tr><td style="font-size:15px;line-height:1.6;color:#c7c7cf;padding:12px 0;">
              Hi {username},<br><br>
              Welcome to xShotAI! Please confirm your email address to complete
              your registration and activate your account.
            </td></tr>
            <tr><td align="center" style="padding:20px 0 8px;">
              <a href="{verify_url}"
                 style="display:inline-block;background:#ff6b2c;color:#ffffff;
                        text-decoration:none;font-weight:600;font-size:15px;
                        padding:13px 28px;border-radius:12px;">
                Verify Email Address
              </a>
            </td></tr>
            <tr><td style="font-size:13px;color:#8b8b94;padding:12px 0 0;">
              This link will expire in 24 hours.
            </td></tr>
            <tr><td style="font-size:13px;color:#8b8b94;padding:16px 0 0;line-height:1.6;">
              If the button above doesn't work, copy and paste this link into
              your browser:<br>
              <a href="{verify_url}" style="color:#ff6b2c;word-break:break-all;">{verify_url}</a>
            </td></tr>
            <tr><td style="font-size:13px;color:#8b8b94;padding:20px 0 0;line-height:1.6;">
              If you didn't create an account with xShotAI, you can safely ignore
              this email.<br><br>
              Best regards,<br>
              The xShotAI Team
            </td></tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def send_verification_email(*, to_email: str, username: str, token: str) -> None:
    """Send the address-verification email. Raises on any SMTP/config error."""
    if not settings.email_verification_active:
        raise RuntimeError("SMTP is not configured (SMTP_USER / SMTP_PASS missing)")

    verify_url = build_verification_url(token)
    from_addr = settings.SMTP_FROM or settings.SMTP_USER

    msg = EmailMessage()
    msg["Subject"] = _SUBJECT
    msg["From"] = formataddr(("xShotAI", from_addr))
    msg["To"] = to_email
    msg.set_content(_plain_body(username, verify_url))
    msg.add_alternative(_html_body(username, verify_url), subtype="html")

    context = ssl.create_default_context()
    if settings.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=20
        ) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASS)
            server.send_message(msg)
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASS)
            server.send_message(msg)

    logger.info("Verification email sent to %s", to_email)
