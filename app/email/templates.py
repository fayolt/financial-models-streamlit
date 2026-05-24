"""Plain-text and HTML templates for transactional emails.

Each builder returns a (subject, text, html) tuple. Keep the HTML minimal —
no external CSS, no images, no fancy layouts. Email clients are inconsistent.
"""
from __future__ import annotations


def _html_shell(body_html: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Numquants</title></head>
<body style="font-family: -apple-system, Helvetica, Arial, sans-serif; color: #1f2937; max-width: 560px; margin: 24px auto; padding: 0 16px; line-height: 1.5;">
{body_html}
<hr style="border:none; border-top:1px solid #e5e7eb; margin-top: 32px;">
<p style="font-size: 12px; color: #6b7280;">Numquants Financial Models</p>
</body></html>"""


def welcome_email(
    *,
    recipient_email: str,
    full_name: str | None,
    app_url: str,
) -> tuple[str, str, str]:
    display_name = full_name or recipient_email.split("@", 1)[0]
    subject = "Welcome to Numquants Financial Models"
    text = f"""Hi {display_name},

Your Numquants account is ready. You're signed in on the Free tier — you can view all 7 financial models in the browser.

To unlock report exports (XLSX on Pro, PDF + AI commentary on Enterprise), pick a plan from the Pricing page:
{app_url.rstrip('/')}/pricing

Reply to this email if you hit any issues.

— The Numquants team
"""
    html = _html_shell(
        f"""<h2 style="margin-bottom:8px;">Welcome to Numquants</h2>
<p>Hi {display_name},</p>
<p>Your account is ready. You're on the <strong>Free</strong> tier — view all 7 financial models in the browser.</p>
<p>To unlock report exports, pick a plan on the Pricing page:</p>
<p><a href="{app_url.rstrip('/')}/pricing"
   style="background:#1f3a5f;color:#fff;text-decoration:none;padding:10px 16px;border-radius:6px;display:inline-block;">View pricing</a></p>
<p>Reply to this email if you hit any issues.</p>"""
    )
    return subject, text, html


def password_changed_email(*, recipient_email: str) -> tuple[str, str, str]:
    subject = "Your Numquants password was changed"
    text = f"""The password for your Numquants account ({recipient_email}) was just changed.

If this was you, no action is needed.

If you didn't change your password, reply to this email immediately so we can help secure your account.

— Numquants Security
"""
    html = _html_shell(
        f"""<h2 style="margin-bottom:8px;">Password changed</h2>
<p>The password for your Numquants account (<strong>{recipient_email}</strong>) was just changed.</p>
<p>If this was you, no action is needed.</p>
<p style="color:#b91c1c;">If you didn't change your password, reply to this email immediately so we can help secure your account.</p>"""
    )
    return subject, text, html


def account_deleted_email(*, recipient_email: str) -> tuple[str, str, str]:
    subject = "Your Numquants account has been deleted"
    text = f"""The Numquants account for {recipient_email} has been deleted at your request. All saved data has been removed.

Any active subscription has been cancelled — you will not be billed again.

If you didn't request this, reply to this email immediately.

— Numquants Security
"""
    html = _html_shell(
        f"""<h2 style="margin-bottom:8px;">Account deleted</h2>
<p>The Numquants account for <strong>{recipient_email}</strong> has been deleted at your request. All saved data has been removed.</p>
<p>Any active subscription has been cancelled — you will not be billed again.</p>
<p style="color:#b91c1c;">If you didn't request this, reply to this email immediately.</p>"""
    )
    return subject, text, html


def verify_email_email(
    *,
    recipient_email: str,
    verify_link: str,
    ttl_hours: int = 48,
) -> tuple[str, str, str]:
    subject = "Confirm your Numquants email"
    text = f"""Welcome to Numquants Financial Models.

Please confirm that this email address ({recipient_email}) is yours by clicking the link below within the next {ttl_hours} hours:

{verify_link}

You'll need to verify your email before you can subscribe to a paid plan. You can still log in and explore the free tier in the meantime.

— The Numquants team
"""
    html = _html_shell(
        f"""<h2 style="margin-bottom:8px;">Confirm your email</h2>
<p>Welcome to Numquants. Please confirm that <strong>{recipient_email}</strong> is your address by clicking below within the next <strong>{ttl_hours} hours</strong>.</p>
<p><a href="{verify_link}"
   style="background:#1f3a5f;color:#fff;text-decoration:none;padding:10px 16px;border-radius:6px;display:inline-block;">Confirm email</a></p>
<p style="color:#6b7280;font-size:13px;">You'll need to verify your email before subscribing to a paid plan.</p>"""
    )
    return subject, text, html


def signup_attempt_existing_email(
    *,
    recipient_email: str,
    app_url: str,
) -> tuple[str, str, str]:
    """Sent when someone tries to sign up with an already-registered email.
    Pairs with the generic success response shown in the UI so we don't leak
    whether an address is on file."""
    subject = "Account already exists for this email"
    text = f"""Someone just tried to create a new Numquants account using {recipient_email}, but an account with this email already exists.

If it was you:
  • Log in at {app_url.rstrip('/')}/login
  • Or reset your password at {app_url.rstrip('/')}/forgot-password

If it wasn't you, you can safely ignore this email — no account changes were made.

— Numquants Security
"""
    html = _html_shell(
        f"""<h2 style="margin-bottom:8px;">Account already exists</h2>
<p>Someone just tried to create a new Numquants account using <strong>{recipient_email}</strong>, but an account already exists with this email.</p>
<p>If it was you, log in or reset your password:</p>
<p>
  <a href="{app_url.rstrip('/')}/login"
     style="background:#1f3a5f;color:#fff;text-decoration:none;padding:10px 16px;border-radius:6px;display:inline-block;margin-right:8px;">Log in</a>
  <a href="{app_url.rstrip('/')}/forgot-password"
     style="background:#f3f4f6;color:#1f2937;text-decoration:none;padding:10px 16px;border-radius:6px;display:inline-block;border:1px solid #d1d5db;">Reset password</a>
</p>
<p style="color:#6b7280;font-size:13px;">If it wasn't you, ignore this email — nothing changed.</p>"""
    )
    return subject, text, html


def password_reset_email(
    *,
    recipient_email: str,
    reset_link: str,
    ttl_minutes: int = 60,
) -> tuple[str, str, str]:
    subject = "Reset your Numquants password"
    text = f"""Someone (hopefully you) requested a password reset for {recipient_email}.

If it was you, follow this link within the next {ttl_minutes} minutes to set a new password:

{reset_link}

If it wasn't you, you can safely ignore this email — your password won't be changed.

— Numquants Security
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
