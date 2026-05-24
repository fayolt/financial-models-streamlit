#!/bin/sh
# Deploy production: injects SECRET env vars before applying the spec.
# DATABASE_URL is managed by the DO App Platform database attachment — do not set here.
#
# Required env vars (store in .env.local, never commit):
#   PROD_JWT_SECRET
#   PROD_PAYSTACK_SECRET_KEY
#   PROD_PAYSTACK_PUBLIC_KEY
#   PROD_OPENAI_API_KEY
#   PROD_ANTHROPIC_API_KEY
#   PROD_MAILGUN_API_KEY
#   PROD_DD_API_KEY
#
# Usage:
#   source .env.local && ./scripts/deploy-prod.sh
set -e

# ── Safety guard ─────────────────────────────────────────────────────────────
# Require explicit confirmation before deploying to production.
echo ""
echo "  ⚠  You are about to deploy to PRODUCTION (numquants.com)."
echo "     This will affect live users."
printf "  Type 'deploy-production' to confirm: "
read -r CONFIRM
if [ "$CONFIRM" != "deploy-production" ]; then
  echo "Aborted." >&2
  exit 1
fi

# ── Validate required vars ───────────────────────────────────────────────────
# Update PROD_APP_ID after creating the production DO App.
PROD_APP_ID="${PROD_APP_ID:-}"
if [ -z "$PROD_APP_ID" ]; then
  echo "Error: PROD_APP_ID is not set in environment." >&2
  echo "       Set it in .env.local after creating the production DO App." >&2
  exit 1
fi

MISSING=""
for var in PROD_JWT_SECRET PROD_PAYSTACK_SECRET_KEY \
           PROD_PAYSTACK_PUBLIC_KEY PROD_OPENAI_API_KEY \
           PROD_ANTHROPIC_API_KEY PROD_MAILGUN_API_KEY PROD_DD_API_KEY; do
  eval "val=\$$var"
  if [ -z "$val" ]; then
    MISSING="$MISSING $var"
  fi
done
if [ -n "$MISSING" ]; then
  echo "Error: missing required env vars:$MISSING" >&2
  exit 1
fi

TMPSPEC=$(mktemp /tmp/prod-spec-XXXXXX.yaml)

python3 - "$TMPSPEC" <<EOF
import sys, re, os

secrets = {
    'JWT_SECRET':            os.environ['PROD_JWT_SECRET'],
    'PAYSTACK_SECRET_KEY':   os.environ['PROD_PAYSTACK_SECRET_KEY'],
    'PAYSTACK_PUBLIC_KEY':   os.environ['PROD_PAYSTACK_PUBLIC_KEY'],
    'OPENAI_API_KEY':        os.environ['PROD_OPENAI_API_KEY'],
    'ANTHROPIC_API_KEY':     os.environ['PROD_ANTHROPIC_API_KEY'],
    'MAILGUN_API_KEY':       os.environ['PROD_MAILGUN_API_KEY'],
    'DD_API_KEY':            os.environ['PROD_DD_API_KEY'],
}

out = sys.argv[1]
with open('.do/app.prod.yaml') as f:
    content = f.read()

def inject(text, key, value):
    pattern = rf'(- key: {re.escape(key)}\n    scope: \S+\n)    type: SECRET'
    replacement = rf'\1    value: "{value}"'
    return re.sub(pattern, replacement, text)

for key, value in secrets.items():
    content = inject(content, key, value)

with open(out, 'w') as f:
    f.write(content)
EOF

doctl apps update "$PROD_APP_ID" --spec "$TMPSPEC"
rm "$TMPSPEC"
doctl apps create-deployment "$PROD_APP_ID"
