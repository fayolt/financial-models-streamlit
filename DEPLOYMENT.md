# Deployment & Operations Guide

## 1. Staging E2E Checklist

Run this after every staging deploy before signing off.

### Infrastructure checks
```bash
# Both services healthy
curl https://staging.numquants.com/_stcore/health        # → ok
curl https://staging.numquants.com/api/health            # → {"status":"ok"}

# Webhook endpoint reachable (unsigned = 401, not 404)
curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://staging.numquants.com/api/webhooks/paystack \
  -H "Content-Type: application/json" -d '{}'            # → 401
```

### Full subscription flow
1. Sign up with a fresh email → check inbox for verification email
2. Click verification link → "Email verified" page
3. Log in → navigate to Pricing
4. Click **Subscribe to Pro** → Paystack checkout opens
5. Complete with Paystack test card `4084 0840 8408 4081`, expiry any future, CVV 408
6. Redirected to `/account` → "Payment confirmed" banner appears
7. Check DB: `SELECT tier FROM users WHERE email = '...'` → `pro`
8. Check DB: `SELECT status FROM subscriptions ORDER BY created_at DESC LIMIT 1` → `active`
9. Check DB: `SELECT * FROM webhook_events ORDER BY received_at DESC LIMIT 3` → rows present with `status=processed`
10. Cancel subscription from Account page → `status=cancelled`, `tier=free` in DB
11. Refresh page → sidebar shows Free tier immediately (no stale cache)

### Error boundary check
```bash
# Temporarily break something and verify friendly error appears, not a traceback
```

---

## 2. Datadog Monitoring Setup

### Log Drain (required — forwards all stdout to Datadog)

After deploying staging or production, create a log drain once per app:

```bash
# Staging
doctl apps create-log-drain <STAGING_APP_ID> \
  --name datadog-staging \
  --type DATADOG \
  --log-types BUILD,DEPLOY,APP \
  --value "api_key=${STAGING_DD_API_KEY}&region=us1"

# Production  
doctl apps create-log-drain <PROD_APP_ID> \
  --name datadog-prod \
  --type DATADOG \
  --log-types BUILD,DEPLOY,APP \
  --value "api_key=${PROD_DD_API_KEY}&region=us1"
```

> **Note:** Change `region=us1` to match your Datadog site (e.g. `eu1` for EU).
> The `DD_SITE` env var in app.yaml controls where the app sends metrics;
> the log drain `region` controls where logs are forwarded.

Verify logs arrive in Datadog: Logs → search `service:numquants-web` or `service:numquants-api`.

### APM Tracing (optional, for production)

Add `DD_INSTALL_EXTRAS=datadog` as a build-time arg in the DO app spec to install `ddtrace`:

```yaml
# In the service build_command or via Dockerfile ARG:
build_command: pip install -e ".[datadog]"
```

Or rebuild the Docker image with:
```
docker build --build-arg DD_INSTALL_EXTRAS=datadog .
```

When `DD_API_KEY` is set and `ddtrace` is installed, the FastAPI service
automatically traces requests and correlates them with log entries via
`dd.trace_id` / `dd.span_id` fields.

### Recommended Monitors

Create these in Datadog after logs are flowing:

**Error rate monitor** (Logs-based):
- Query: `service:numquants-* level:ERROR`
- Condition: count > 10 over 5 minutes
- Alert: PagerDuty / email

**Webhook handler failure** (Logs-based):
- Query: `service:numquants-api event:* handler failed`
- Condition: count > 0 over 5 minutes (any webhook handler failure)

**Health check synthetic** (Synthetics):
- URL: `https://staging.numquants.com/_stcore/health`
- Frequency: every 1 minute
- Assert: response body contains `ok`

---

## 3. Production Deploy Procedure

### First deploy (one-time setup)

1. **Create the production DO App:**
   ```bash
   doctl apps create --spec .do/app.prod.yaml
   # Note the APP ID from the output
   ```

2. **Add `PROD_APP_ID` to `.env.local`:**
   ```
   PROD_APP_ID=<app-id-from-above>
   ```

3. **Create the production database** in the DO control panel:
   - Cluster name: `db-postgresql-financial-models-prod`
   - Region: Frankfurt
   - Create a dedicated user: `numquants_prod` with a strong password
   - Attach to the production app via the DO UI

4. **Set production Paystack live keys** in the Paystack dashboard:
   - Create live plans for Pro (ZAR 250/mo) and Enterprise (ZAR 300/mo)
   - Note the `plan_code` values

5. **Run migrations against production DB:**
   ```bash
   source .env.local
   PROD_DATABASE_URL=... .venv/bin/alembic upgrade head
   PROD_DATABASE_URL=... .venv/bin/python -m app.db.seed
   # Then update plan codes:
   # UPDATE plans SET paystack_plan_code='PLN_xxx' WHERE slug='pro';
   ```

6. **Set up Datadog log drain** (see Section 2).

7. **Configure Paystack webhook:**
   - Dashboard → Settings → API Keys & Webhooks
   - Live Webhook URL: `https://numquants.com/api/webhooks/paystack`

8. **Verify DNS** for `numquants.com` → DO load balancer IP.

### Routine deploy

```bash
source .env.local
./scripts/deploy-prod.sh
# Type 'deploy-production' when prompted
```

Monitor the deployment:
```bash
doctl apps list-deployments $PROD_APP_ID --format ID,Phase,Progress
```

Post-deploy verification:
```bash
curl https://numquants.com/_stcore/health   # → ok
curl https://numquants.com/api/health       # → {"status":"ok"}
```

---

## 4. Secret Rotation

When rotating a secret (e.g. JWT_SECRET, Paystack keys):

1. Generate the new secret value.
2. Update `.env.local` with the new `STAGING_<KEY>` or `PROD_<KEY>` value.
3. Run the appropriate deploy script — it injects all secrets on every deploy,
   so updating `.env.local` + redeploying is the only step required.
4. **JWT_SECRET rotation note:** existing sessions are immediately invalidated
   because all JWTs are signed with the old key. Users will be logged out on
   their next page load. Schedule rotations during low-traffic periods.
5. Delete the old secret from your password manager and any notes.

**Secrets checklist** (never commit any of these):

| Secret | Where stored | Rotation frequency |
|--------|-------------|-------------------|
| JWT_SECRET | `.env.local` → DO secret | Every 6 months or on compromise |
| PAYSTACK_SECRET_KEY | `.env.local` → DO secret | On compromise only |
| PAYSTACK_PUBLIC_KEY | `.env.local` → DO secret | On compromise only |
| OPENAI_API_KEY | `.env.local` → DO secret | On compromise or quarterly |
| ANTHROPIC_API_KEY | `.env.local` → DO secret | On compromise or quarterly |
| MAILGUN_API_KEY | `.env.local` → DO secret | On compromise only |
| DD_API_KEY | `.env.local` → DO secret | On compromise only |

---

## 5. Admin Access

The admin panel (Users + Analytics) is gated on `User.is_admin = TRUE`.
There is no public signup path to admin — the **first admin must be
bootstrapped from a server-side CLI**. Once one admin exists, they can
grant admin to others from the in-app UI.

### Bootstrapping the first admin (one-time)

**Locally:**
```bash
make admin-promote EMAIL=you@numquants.com
make admin-list
```

**On staging or production** (via DO App Platform console):
```bash
# Open the web service's console in the DO dashboard, or:
doctl apps console <APP_ID> --component web

# Inside the container shell:
python -m app.admin promote you@numquants.com
python -m app.admin list
```

After promotion, log out + log back in (the `is_admin` flag is read into
session state on login; existing sessions don't auto-refresh it).

### Granting / revoking admin going forward

Once any admin exists, use the in-app UI:

1. Sign in as an admin.
2. Sidebar → Admin → Users.
3. Look up the user by email.
4. **"Admin access"** section → **"Grant admin"** (with confirmation) or **"Revoke admin"**.
5. Action is recorded in `admin_audit_log` (immutable, queryable).

Self-demotion is intentionally blocked from the UI to prevent lockout.
Use `make admin-demote EMAIL=…` on a server if you really need to.

### Issuing a refund

1. Open Paystack dashboard → Transactions → find the charge to refund.
2. Copy the **transaction reference** (looks like `T123456789` or a UUID).
3. In the admin panel, look up the user → **Refunds** section → **"Issue a refund"**.
4. Paste the reference, choose full or partial amount, enter a reason
   (required for compliance — stored permanently in the audit log).
5. Click **"Issue refund"**. Paystack returns a refund ID immediately; the
   refund status flips from `pending` to `processed` when Paystack sends the
   `refund.processed` webhook (usually within minutes).
6. The user retains their tier — refunds do **not** cancel subscriptions.
   To both refund and cancel, also disable the subscription separately
   (or have the user cancel from their Account page).

### Plan changes (user-facing)

Users can upgrade mid-cycle from the Pricing page:

- **Free → Pro / Enterprise:** standard checkout flow.
- **Pro → Enterprise:** the app cancels the existing Pro subscription on
  Paystack, then opens a fresh checkout for Enterprise. Paystack handles
  proration automatically (unused Pro time is credited toward Enterprise).
- **Downgrades** are intentionally not exposed. To downgrade, a user cancels
  their current plan (Account page) and resubscribes to a lower tier when
  ready. This avoids the complexity of scheduled mid-cycle downgrades and
  prevents accidental refund disputes.

---

## 6. Database Access

```bash
# Connect to staging DB via doctl (requires VPC tunnel):
doctl databases db get <staging-cluster-id>

# Run a migration against staging:
source .env.local
.venv/bin/alembic upgrade head

# Verify migration history:
.venv/bin/alembic history
.venv/bin/alembic current
```
