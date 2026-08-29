# Raspberry Pi edge daemon image - polls real sensors (Modbus RS-485,
# DS18B20 1-Wire, PMS7003 UART), buffers locally to SQLite, publishes to
# the cloud MQTT broker. Deliberately scoped to edge/ + shared/ only: this
# image should never need anything from api/, frontend/, ingest/, or
# workers/ - that's the whole point of edge/requirements.txt being a
# separate, smaller file from the root requirements.txt.
#
# Build context is the REPO ROOT, not edge/, because shared/quality.py
# lives outside edge/ and both directories are copied in below:
#   docker buildx build --platform linux/arm64 -f edge/Dockerfile -t airthra-edge:latest .
# Use linux/arm64 for a 64-bit Raspberry Pi OS (Pi 4/5, recommended) or
# linux/arm/v7 for 32-bit Raspberry Pi OS (older Pi 3 / Zero 2 W). See
# edge/DEPLOY.md for the full build-and-run walkthrough, including why
# cross-building on a dev machine is usually better than building on the
# Pi itself.
FROM python:3.11-slim

WORKDIR /app

# libpq-dev/gcc: psycopg[binary] ships prebuilt wheels for the common
# platforms but not reliably for 32-bit arm/v7, so keep the ability to
# build it from source rather than fail on those devices (same reasoning
# as the root Dockerfile).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY edge/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Only what edge/daemon.py actually imports - see its sys.path handling,
# which expects shared/ as a sibling of edge/ (both under /app here).
COPY edge/ ./edge/
COPY shared/ ./shared/

# edge/cache (manifest cache) and edge/data (SQLite buffer, watchdog
# heartbeat, stats) must survive container restarts/image upgrades - mount
# them as named volumes at runtime (see edge/DEPLOY.md), don't rely on
# what a stopped-and-removed container had written into its own layer.
RUN mkdir -p /app/edge/cache /app/edge/data

# .env and the three wiring maps (modbus_map.json / onewire_map.json /
# pms7003_map.json) are intentionally NOT copied in - they're
# plant-specific, contain real ROM ids/registers once filled in, and get
# edited during commissioning without wanting a rebuild each time. Bind-
# mount them at runtime instead.

ENTRYPOINT ["python", "edge/daemon.py"]
CMD ["--plant-id", "goa_pilot_01"]
