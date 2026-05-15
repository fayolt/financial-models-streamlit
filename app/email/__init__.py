from .client import EmailError, send_email, send_email_best_effort
from .templates import (
    account_deleted_email,
    password_changed_email,
    password_reset_email,
    welcome_email,
)

__all__ = [
    "EmailError",
    "account_deleted_email",
    "password_changed_email",
    "password_reset_email",
    "send_email",
    "send_email_best_effort",
    "welcome_email",
]
