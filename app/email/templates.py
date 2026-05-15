"""Plain-text and HTML templates for transactional emails.

Each builder returns a (subject, text, html) tuple. Keep the HTML minimal —
no external CSS, no images, no fancy layouts. Email clients are inconsistent.
"""
from __future__ import annotations


def _html_shell(body_html: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Zenkos</title></head>
<body style="font-family: -apple-system, Helvetica, Arial, sans-serif; color: #1f2937; max-width: 560px; margin: 24px auto; padding: 0 16px; line-height: 1.5;">
{body_html}
<hr style="border:none; border-top:1px solid #e5e7eb; margin-top: 32px;">
<p style="font-size: 12px; color: #6b7280;">Zenkos Financial Models</p>
</body></html>"""


def welcome_email(
    *,
    recipient_email: str,
    full_name: str | None,
    app_url: str,
) -> tuple[str, str, str]:
    display_name = full_name or recipient_email.split("@", 1)[0]
    subject = "Welcome to Zenkos Financial Models"
    text = f"""Hi {display_name},

Your Zenkos account is ready. You're signed in on the Free tier — you can view all 7 financial models in the browser.

To unlock report exports (XLSX on Pro, PDF + AI commentary on Enterprise), pick a plan from the Pricing page:
{app_url.rstrip('/')}/pricing

Reply to this email if you hit any issues.

— The Zenkos team
"""
    html = _html_shell(
        f"""<h2 style="margin-bottom:8px;">Welcome to Zenkos</h2>
<p>Hi {display_name},</p>
<p>Your account is ready. You're on the <strong>Free</strong> tier — view all 7 financial models in the browser.</p>
<p>To unlock report exports, pick a plan on the Pricing page:</p>
<p><a href="{app_url.rstrip('/')}/pricing"
   style="background:#1f3a5f;color:#fff;text-decoration:none;padding:10px 16px;border-radius:6px;display:inline-block;">View pricing</a></p>
<p>Reply to this email if you hit any issues.</p>"""
    )
    return subject, text, html


def password_reset_email(
    *,
    recipient_email: str,
    reset_link: str,
    ttl_minutes: int = 60,
) -> tuple[str, str, str]:
    subject = "Reset your Zenkos password"
    text = f"""Someone (hopefully you) requested a password reset for {recipient_email}.

If it was you, follow this link within the next {ttl_minutes} minutes to set a new password:

{reset_link}

If it wasn't you, you can safely ignore this email — your password won't be changed.

— Zenkos Security
"""
    html = _html_shell(
        f"""<h2 style="margin-bottom:8px;">Reset your password</h2>
<p>Someone (hopefully you) requested a password reset for <strong>{recipient_email}</strong>.</p>
<p>Follow this link within the next <strong>{ttl_minutes} minutes</strong> to set a new password:</p>
<p><a href="{reset_link}"
   style="background:#1f3a5f;color:#fff;text-decoration:none;padding:10px 16px;border-radius:6px;display:inline-block;">Reset password</a></p>
<p style="color:#6b7280;font-size:13px;">If it wasn't you, ignore this email — your password won't change.</p>"""
    )
    return subject, text, html
