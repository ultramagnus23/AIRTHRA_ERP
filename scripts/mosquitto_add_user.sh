#!/usr/bin/env bash
# Add (or update) one device's MQTT credentials in docker/mosquitto/passwd.
#
# Usage: bash scripts/mosquitto_add_user.sh <device_id> <password>
#
# Requires the mosquitto-clients package for `mosquitto_passwd` locally, OR
# run it inside the running mosquitto container:
#   docker compose exec mosquitto mosquitto_passwd -b /mosquitto/config/passwd <device_id> <password>

set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <device_id> <password>" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASSWD_FILE="${SCRIPT_DIR}/../docker/mosquitto/passwd"

if command -v mosquitto_passwd >/dev/null 2>&1; then
  mosquitto_passwd -b "${PASSWD_FILE}" "$1" "$2"
  echo "Added/updated credentials for '$1' in ${PASSWD_FILE}"
else
  echo "mosquitto_passwd not found locally. Run this instead:" >&2
  echo "  docker compose exec mosquitto mosquitto_passwd -b /mosquitto/config/passwd $1 $2" >&2
  echo "then: docker compose restart mosquitto" >&2
  exit 1
fi
