#!/bin/sh
# Deploy staging: injects DATABASE_URL secret before applying the spec.
# Usage: STAGING_DATABASE_URL="postgresql://..." ./scripts/deploy-staging.sh
#
# Store the URL in your local .env.local (gitignored) and source it first:
#   export STAGING_DATABASE_URL="postgresql://doadmin:...@...db.ondigitalocean.com:25060/db-numquants-staging?sslmode=require"
set -e

APP_ID="ad6efbdf-732b-450c-b55d-f9e9a2826ad5"

if [ -z "$STAGING_DATABASE_URL" ]; then
  echo "Error: STAGING_DATABASE_URL is not set." >&2
  echo "Export it before running this script." >&2
  exit 1
fi

TMPSPEC=$(mktemp /tmp/staging-spec-XXXXXX.yaml)

python3 - "$STAGING_DATABASE_URL" "$TMPSPEC" <<'EOF'
import sys, re
db_url, out = sys.argv[1], sys.argv[2]
with open('.do/app.yaml') as f:
    content = f.read()
fixed = re.sub(
    r'(- key: DATABASE_URL\n    scope: RUN_AND_BUILD_TIME\n)    type: SECRET',
    f'\\1    value: "{db_url}"',
    content
)
with open(out, 'w') as f:
    f.write(fixed)
EOF

doctl apps update "$APP_ID" --spec "$TMPSPEC"
rm "$TMPSPEC"
doctl apps create-deployment "$APP_ID"
