#!/bin/sh
# Deploy staging: injects SECRET env vars before applying the spec.
# DATABASE_URL is managed by the DO App Platform database attachment — do not set here.
#
# Required env vars (store in .env.local, never commit):
#   STAGING_JWT_SECRET
#   STAGING_PAYSTACK_SECRET_KEY
#   STAGING_PAYSTACK_PUBLIC_KEY
#   STAGING_OPENAI_API_KEY
#   STAGING_ANTHROPIC_API_KEY
#   STAGING_MAILGUN_API_KEY
#
# Usage:
#   source .env.local && ./scripts/deploy-staging.sh
set -e

APP_ID="ad6efbdf-732b-450c-b55d-f9e9a2826ad5"

MISSING=""
for var in STAGING_JWT_SECRET STAGING_PAYSTACK_SECRET_KEY \
           STAGING_PAYSTACK_PUBLIC_KEY STAGING_OPENAI_API_KEY \
           STAGING_ANTHROPIC_API_KEY STAGING_MAILGUN_API_KEY; do
  eval "val=\$$var"
  if [ -z "$val" ]; then
    MISSING="$MISSING $var"
  fi
done
if [ -n "$MISSING" ]; then
  echo "Error: missing required env vars:$MISSING" >&2
  exit 1
fi

TMPSPEC=$(mktemp /tmp/staging-spec-XXXXXX.yaml)

python3 - "$TMPSPEC" <<EOF
import sys, re, os

secrets = {
    'JWT_SECRET':            os.environ['STAGING_JWT_SECRET'],
    'PAYSTACK_SECRET_KEY':   os.environ['STAGING_PAYSTACK_SECRET_KEY'],
    'PAYSTACK_PUBLIC_KEY':   os.environ['STAGING_PAYSTACK_PUBLIC_KEY'],
    'OPENAI_API_KEY':        os.environ['STAGING_OPENAI_API_KEY'],
    'ANTHROPIC_API_KEY':     os.environ['STAGING_ANTHROPIC_API_KEY'],
    'MAILGUN_API_KEY':       os.environ['STAGING_MAILGUN_API_KEY'],
}

out = sys.argv[1]
with open('.do/app.yaml') as f:
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

doctl apps update "$APP_ID" --spec "$TMPSPEC"
rm "$TMPSPEC"
doctl apps create-deployment "$APP_ID"
