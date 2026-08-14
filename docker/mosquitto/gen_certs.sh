#!/usr/bin/env bash
# Generates a local, self-signed CA + server certificate for the Mosquitto
# TLS listener (dev/pilot use only - NOT for production, which should use
# certs from a real CA or per-device provisioning workflow).
#
# Usage: bash docker/mosquitto/gen_certs.sh
#
# Output: docker/mosquitto/certs/{ca.crt,ca.key,server.crt,server.key}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="${SCRIPT_DIR}/certs"
DAYS=3650
CN_CA="Airthra Dev CA"
CN_SERVER="${MQTT_CN:-localhost}"

mkdir -p "${CERT_DIR}"
cd "${CERT_DIR}"

echo "==> Generating CA key + self-signed CA cert"
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days "${DAYS}" \
  -out ca.crt -subj "/O=Airthra/CN=${CN_CA}"

echo "==> Generating server key + CSR"
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
  -subj "/O=Airthra/CN=${CN_SERVER}"

echo "==> Signing server cert with the CA"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days "${DAYS}" -sha256

rm -f server.csr

chmod 644 ca.crt server.crt
chmod 600 ca.key server.key

echo "==> Done. Certs written to ${CERT_DIR}"
echo "    ca.crt / ca.key       - local dev CA (trust ca.crt on client devices)"
echo "    server.crt / server.key - mosquitto broker identity"
echo
echo "Per-device credentials still go through docker/mosquitto/passwd (mosquitto_passwd)."
echo "See README.md for how to add a device user."
