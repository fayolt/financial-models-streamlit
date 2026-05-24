"""Terms of Service page."""
from __future__ import annotations

import streamlit as st

_EFFECTIVE_DATE = "1 June 2026"
_COMPANY = "Numquants (Pty) Ltd"
_EMAIL = "legal@numquants.com"
_WEBSITE = "numquants.com"


def render() -> None:
    st.title("Terms of Service")
    st.caption(f"Effective date: {_EFFECTIVE_DATE}")

    st.markdown(f"""
These Terms of Service ("Terms") govern your use of the Numquants platform
("Service") operated by **{_COMPANY}** ("we", "us", "our"). By creating an
account or using the Service you agree to these Terms.

---

### 1. Service Description

Numquants provides web-based financial modelling tools. Models are provided
for informational and planning purposes only and do not constitute financial,
investment, legal, or tax advice.

### 2. Eligibility

You must be at least 18 years old and legally capable of entering into a
binding contract to use the Service.

### 3. Accounts and Security

You are responsible for keeping your login credentials confidential and for
all activity that occurs under your account. Notify us immediately at
**{_EMAIL}** if you suspect unauthorised access.

### 4. Subscriptions and Billing

Paid plans are billed monthly in ZAR via Paystack. Subscriptions renew
automatically unless cancelled before the next billing date. You may cancel
at any time from the Account page; access continues until the end of the
paid period. No partial-month refunds are issued unless required by law.

### 5. Acceptable Use

You agree not to:
- Attempt to reverse-engineer, scrape, or extract model logic in bulk.
- Use the Service for any unlawful purpose.
- Share account credentials with third parties.
- Circumvent access controls or rate limits.

### 6. Intellectual Property

All model logic, software, and content are owned by {_COMPANY} or its
licensors. Nothing in these Terms grants you ownership of any intellectual
property.

### 7. Disclaimer of Warranties

The Service is provided **"as is"** without warranties of any kind, express
or implied, including accuracy, fitness for a particular purpose, or
uninterrupted availability.

### 8. Limitation of Liability

To the maximum extent permitted by applicable law, {_COMPANY} shall not be
liable for any indirect, incidental, special, or consequential damages
arising from your use of the Service, even if advised of the possibility of
such damages.

### 9. Termination

We may suspend or terminate your account for material breach of these Terms,
with or without notice at our discretion.

### 10. Governing Law

These Terms are governed by the laws of the Republic of South Africa.
Disputes shall be resolved in the courts of South Africa.

### 11. Changes

We may update these Terms at any time. Continued use after changes constitutes
acceptance. Material changes will be notified by email.

### 12. Contact

Questions about these Terms: **{_EMAIL}**
    """)
