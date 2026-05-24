"""Privacy Policy page."""
from __future__ import annotations

import streamlit as st

_EFFECTIVE_DATE = "1 June 2026"
_COMPANY = "Numquants (Pty) Ltd"
_EMAIL = "privacy@numquants.com"


def render() -> None:
    st.title("Privacy Policy")
    st.caption(f"Effective date: {_EFFECTIVE_DATE}")

    st.markdown(f"""
{_COMPANY} ("we", "us") is committed to protecting your personal information
in compliance with the **Protection of Personal Information Act 4 of 2013
(POPIA)** and, where applicable, the EU General Data Protection Regulation
(GDPR).

---

### 1. Information We Collect

| Category | Examples | Purpose |
|----------|----------|---------|
| Account data | Email address, name, password hash | Authentication and account management |
| Usage data | Pages visited, model runs, download events | Service improvement and quota enforcement |
| Payment data | Transaction reference, plan tier | Processed by Paystack — we store only a reference, not card details |
| Technical data | IP address, browser headers | Security (rate limiting, fraud prevention) |

We do **not** sell or rent your personal information to third parties.

### 2. Legal Basis for Processing

We process your data on the following grounds:
- **Contract performance**: to provide the Service you subscribed to.
- **Legitimate interest**: security, fraud prevention, and service improvement.
- **Legal obligation**: tax records, compliance requirements.
- **Consent**: where you have explicitly opted in (e.g. marketing communications).

### 3. Data Retention

| Data type | Retention period |
|-----------|-----------------|
| Account data | For the lifetime of your account + 12 months |
| Session tokens | 30 days or until logout |
| Payment references | 5 years (statutory minimum) |
| Security logs (IP, rate-limit records) | 24 hours |
| Model run history | For the lifetime of your account |

You may request deletion of your account and associated data at any time
(see Section 6).

### 4. Third-Party Services

We share data with the following sub-processors:

| Provider | Purpose | Location |
|----------|---------|---------|
| DigitalOcean | Hosting and database | Netherlands (AMS) / EU |
| Paystack | Payment processing | Nigeria / South Africa |
| Mailgun | Transactional email | EU |
| Datadog | Logging and monitoring | US (EU region if configured) |
| OpenAI / Anthropic | AI commentary generation | US |

For AI commentary, only your financial model inputs are sent to the LLM
provider — no personal identifiers are included.

### 5. Cookies and Tracking

The Service uses a single authentication cookie to maintain your session.
No third-party advertising cookies are used.

### 6. Your Rights

Under POPIA and GDPR you have the right to:
- **Access** the personal information we hold about you.
- **Correct** inaccurate information.
- **Delete** your account and associated data (via Account → Delete account).
- **Object** to processing based on legitimate interest.
- **Data portability** — request an export of your data.
- **Lodge a complaint** with the South African Information Regulator
  (inforeg.org.za) or your local supervisory authority.

To exercise any right, email **{_EMAIL}**.

### 7. Security

We use industry-standard measures including TLS encryption in transit,
bcrypt password hashing, and access controls. No system is completely secure;
please report suspected vulnerabilities to **security@numquants.com**.

### 8. Children

The Service is not directed at children under 18 and we do not knowingly
collect personal information from minors.

### 9. Changes to This Policy

We will notify you by email of material changes at least 14 days before
they take effect.

### 10. Contact

**Information Officer:** {_COMPANY}
**Email:** {_EMAIL}
    """)
