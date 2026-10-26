#!/bin/sh
set -eu

DATA_DIR="${OEIS_DATA_DIR:-/data}"
ENV_FILE="$DATA_DIR/oeis.env"
mkdir -p "$DATA_DIR"
python scripts/generate_local_secrets.py --env-file "$ENV_FILE" >/dev/null

from_file() { grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- || true; }
load() {
  eval "current=\${$1:-}"
  if [ -z "$current" ]; then
    value="$(from_file "$1")"
    [ -n "$value" ] && export "$1=$value"
  fi
  return 0
}

GENERATED_ADMIN_PASSWORD=""
if [ -z "${BOOTSTRAP_ADMIN_PASSWORD:-}" ] && [ -z "$(from_file BOOTSTRAP_ADMIN_PASSWORD)" ]; then
  GENERATED_ADMIN_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(18))')"
  printf 'BOOTSTRAP_ADMIN_PASSWORD=%s\n' "$GENERATED_ADMIN_PASSWORD" >> "$ENV_FILE"
fi

load JWT_SECRET
load TOKEN_ENCRYPTION_KEY
load TOKEN_ENCRYPTION_KEY_ID
load BOOTSTRAP_ADMIN_PASSWORD

export DATABASE_URL="${DATABASE_URL:-sqlite:///$DATA_DIR/oeis.db}"
export BOOTSTRAP_ADMIN_EMAIL="${BOOTSTRAP_ADMIN_EMAIL:-admin@example.com}"
export BOOTSTRAP_ADMIN_NAME="${BOOTSTRAP_ADMIN_NAME:-OEIS Admin}"
export SUMMARY_HOUR="${SUMMARY_HOUR:-18}"
export FRONTEND_URL="${FRONTEND_URL:-http://localhost:8000}"
export DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:8000}"
export ENABLE_API_DOCS="${ENABLE_API_DOCS:-false}"
export SCHEDULER_ENABLED="${SCHEDULER_ENABLED:-true}"

# Migration 0001 creates the schema from current models. On a new database,
# create that schema once and stamp it; existing versioned databases are upgraded.
DB_STATE="$(python - <<'PY'
from sqlalchemy import inspect
from app.core.database import Base, engine
from app.models import entities  # noqa: F401
tables = set(inspect(engine).get_table_names())
if "alembic_version" in tables:
    print("existing")
elif tables:
    raise SystemExit("Database has tables but no Alembic version; refusing to stamp it")
else:
    Base.metadata.create_all(engine)
    print("fresh")
PY
)"
if [ "$DB_STATE" = "fresh" ]; then
  python -m alembic stamp head
else
  python -m alembic upgrade head
fi

if [ -n "$GENERATED_ADMIN_PASSWORD" ]; then
  echo "OEIS first run admin email: $BOOTSTRAP_ADMIN_EMAIL"
  echo "OEIS first run admin password: $GENERATED_ADMIN_PASSWORD"
  echo "Password is also stored in $ENV_FILE inside the volume."
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
