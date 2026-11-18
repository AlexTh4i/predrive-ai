#!/usr/bin/env bash
# PreDrive AI PostgreSQL Backup & Offsite Sync Script (P2-5)
# SECURITY RULE (R4): NEVER echo, print, or log connection strings or cloud keys.
set -euo pipefail
set +x

TARGET_DB_URL="${SUPABASE_DB_URL:-${DATABASE_URL:-}}"
if [[ -z "${TARGET_DB_URL}" ]]; then
  echo "ERROR: Set SUPABASE_DB_URL or DATABASE_URL before running backup.sh" >&2
  exit 1
fi

# Normalize SQLAlchemy postgresql+psycopg:// -> libpq postgresql://
CLEAN_URL="${TARGET_DB_URL/#postgresql+psycopg:\/\//postgresql:\/\/}"
CLEAN_URL="${CLEAN_URL/#postgres:\/\//postgresql:\/\/}"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${BACKUP_DIR}"

DUMP_FILE="${BACKUP_DIR}/predrive_${TIMESTAMP}.dump"
SHA_FILE="${DUMP_FILE}.sha256"

echo "[1/4] Creating custom-format PostgreSQL dump -> ${DUMP_FILE}"
if command -v pg_dump >/dev/null 2>&1; then
  pg_dump --format=custom --no-owner --no-privileges --dbname="${CLEAN_URL}" --file="${DUMP_FILE}"
else
  # Fallback via postgres:15-alpine container (translates 127.0.0.1/localhost -> host.docker.internal)
  DOCKER_URL="${CLEAN_URL//127.0.0.1/host.docker.internal}"
  DOCKER_URL="${DOCKER_URL//localhost/host.docker.internal}"
  docker run --rm -e SRC_URL="${DOCKER_URL}" postgres:15-alpine \
    sh -c 'pg_dump --format=custom --no-owner --no-privileges --dbname="$SRC_URL"' > "${DUMP_FILE}"
fi

if [[ ! -s "${DUMP_FILE}" ]]; then
  echo "ERROR: Dump file is empty!" >&2
  exit 2
fi

echo "[2/4] Generating SHA-256 checksum -> ${SHA_FILE}"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${DUMP_FILE}" > "${SHA_FILE}"
else
  shasum -a 256 "${DUMP_FILE}" > "${SHA_FILE}"
fi
cat "${SHA_FILE}"

echo "[3/4] Offsite sync check..."
if [[ -n "${BACKUP_S3_URI:-}" ]]; then
  if command -v aws >/dev/null 2>&1; then
    ENDPOINT_ARGS=()
    if [[ -n "${BACKUP_S3_ENDPOINT:-}" ]]; then
      ENDPOINT_ARGS=(--endpoint-url "${BACKUP_S3_ENDPOINT}")
    fi
    aws "${ENDPOINT_ARGS[@]}" s3 cp "${DUMP_FILE}" "${BACKUP_S3_URI}/"
    aws "${ENDPOINT_ARGS[@]}" s3 cp "${SHA_FILE}" "${BACKUP_S3_URI}/"
    echo "Uploaded backup + checksum to ${BACKUP_S3_URI}"
  elif command -v rclone >/dev/null 2>&1; then
    rclone copy "${DUMP_FILE}" "${BACKUP_S3_URI}"
    rclone copy "${SHA_FILE}" "${BACKUP_S3_URI}"
    echo "Synced backup + checksum via rclone to ${BACKUP_S3_URI}"
  else
    echo "ERROR: BACKUP_S3_URI is set, but neither 'aws' CLI nor 'rclone' is installed." >&2
    exit 3
  fi
else
  echo "BACKUP_S3_URI not set -> skipping offsite cloud upload (local backup retained)."
fi

echo "[4/4] Pruning local backups older than ${BACKUP_RETENTION_DAYS} day(s)..."
find "${BACKUP_DIR}" -maxdepth 1 -type f \( -name "predrive_*.dump" -o -name "predrive_*.dump.sha256" \) -mtime +"${BACKUP_RETENTION_DAYS}" -delete || true

echo "Backup completed successfully: ${DUMP_FILE}"
