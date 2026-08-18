# Deploying Airthra: Render (backend) + Vercel (frontend)

This is a private, invite-only deployment for showing the app to your
client — not a public launch. Reasons and what's still needed before a
real public launch are in [SHIPPING.md](SHIPPING.md).

**Read this before running anything:** `render.yaml` and the Dockerfiles
in this repo were written without a Render account to test against —
there was no way to verify the Blueprint end-to-end first. Render's
schema was followed carefully, but expect first deploy to need one or two
rounds of fixing something Render's dashboard flags as wrong, not a
guaranteed one-click success. This document's verification steps exist
for exactly that reason — work through them in order and don't assume
success until each one actually confirms it.

**Cost**: every Render service below is always-on with a persistent disk.
This is not free-tier-shaped. Check Render's current pricing for your
region/plan before applying the Blueprint, and decide with whoever's
paying whether all 4 workers need to run continuously or whether some
can be started on-demand instead (see the "trimming cost" section at the
bottom).

---

## 1. Prerequisites

- A Render account (render.com) — you create this, not me.
- A Vercel account (vercel.com) — same.
- This repo pushed to GitHub, on `master` — already done.

## 2. Deploy the backend to Render

1. Render dashboard → **New +** → **Blueprint**.
2. Connect your GitHub account, select `ultramagnus23/AIRTHRA_ERP`.
3. Render reads `render.yaml` from the repo root and proposes 7 services:
   `airthra-postgres`, `airthra-minio`, `airthra-mosquitto`, `airthra-api`,
   `airthra-ingest`, `airthra-edge-mock`, `airthra-kpi-worker`,
   `airthra-alarm-engine`. Review the plan Render shows you, then
   **Apply**.
4. This will take a while (building 5 Docker images). Watch each
   service's **Logs** tab as it comes up — `airthra-postgres` and
   `airthra-minio` should reach "ready"/healthy first since they're
   pre-built images, not a Docker build.

## 3. The one manual step: DATABASE_URL

Render's Blueprint format can't compose a full connection string from
another service's host + a generated password in one YAML file, so this
is a copy-paste step, done once:

1. Open `airthra-postgres` in the Render dashboard → **Environment** tab.
   Copy the generated `POSTGRES_PASSWORD` value.
2. Open `airthra-postgres` → **Info**/**Connect** tab, copy its **internal
   hostname** (looks like `airthra-postgres:5432` or similar — Render
   shows the exact form).
3. Build these two strings:
   ```
   DATABASE_URL=postgresql+psycopg://airthra:<PASSWORD>@<INTERNAL_HOST>/airthra
   ASYNC_DATABASE_URL=postgresql+asyncpg://airthra:<PASSWORD>@<INTERNAL_HOST>/airthra
   ```
4. Paste both into the **Environment** tab of ALL FIVE of: `airthra-api`,
   `airthra-ingest`, `airthra-edge-mock`, `airthra-kpi-worker`,
   `airthra-alarm-engine`. Each service redeploys automatically when you
   save its env vars.

## 4. Run migrations and seed data

Render's **Shell** tab (on `airthra-api`) gives you a terminal inside the
running container:

```bash
python -m alembic upgrade head
python seed/seed.py
python seed/seed_hardware_components.py
python workers/seed_alarm_rules.py
python workers/seed_fault_tree_rules.py
```

**Verify before moving on**: `curl localhost:$PORT/health` from that same
shell should return `{"status":"ok"}`. If `alembic upgrade head` errors,
stop here and fix it — nothing downstream will work against a half-
migrated database.

## 5. Confirm the API is actually reachable

`airthra-api`'s dashboard page shows its public URL
(`https://airthra-api-xxxx.onrender.com` or similar). Open
`<that-url>/health` in a browser — you should see `{"status":"ok"}`. If
you don't, the frontend won't either; fix this before touching Vercel.

## 6. Deploy the frontend to Vercel

1. Vercel dashboard → **Add New** → **Project** → import the same GitHub
   repo.
2. **Root Directory**: set this to `frontend` (this repo is a monorepo —
   Vercel needs to know the Next.js app isn't at the repo root). This is
   a project setting in Vercel's import screen, not a file.
3. Environment variables (Vercel project settings → Environment
   Variables), using the Render API URL from step 5:
   ```
   API_BASE=https://airthra-api-xxxx.onrender.com
   NEXT_PUBLIC_API_BASE=https://airthra-api-xxxx.onrender.com
   NEXT_PUBLIC_WS_BASE=wss://airthra-api-xxxx.onrender.com
   ```
   (`wss://` not `ws://` — Render terminates TLS for you, and a browser
   on an `https://` page refuses to open a plain `ws://` socket to a
   different host.)
4. Deploy.

## 7. Close the loop: CORS

Back on Render, `airthra-api` → **Environment** → set:
```
CORS_ALLOWED_ORIGINS=https://your-actual-vercel-url.vercel.app
```
Until you do this, the deployed frontend's API calls will fail with a
CORS error in the browser console — this is the API deliberately
rejecting credentialed requests from an origin it doesn't recognize (see
[AUDIT.md](AUDIT.md) §2.4), not a bug.

## 8. Make it private, not public

Vercel project → **Settings** → **Deployment Protection** → turn on
**Vercel Authentication** or **Password Protection**. This is the actual
privacy boundary for a client preview — without it, anyone with the URL
can open the login page (though not get past it without real
credentials).

## 9. Final verification checklist

Work through this in order; each step depends on the one before it:

- [ ] `airthra-postgres`, `airthra-minio`, `airthra-mosquitto` all show
      "Live"/healthy in Render
- [ ] `airthra-api`'s `/health` returns `{"status":"ok"}` when hit
      directly
- [ ] Migrations ran with no errors (step 4)
- [ ] The Vercel URL loads the login page
- [ ] Logging in as `admin@airthra.dev` / `Airthra_Dev_2026!` works and
      lands on `/fleet`
- [ ] The Live page for a plant shows sensor tiles updating (proves
      edge-mock → mosquitto → ingest → Postgres → API → frontend all work
      end to end)
- [ ] Deployment Protection is on — confirm by opening the URL in an
      incognito window with no Vercel session; you should be challenged

If the Live page tiles are frozen (not updating), check
`airthra-edge-mock` and `airthra-ingest`'s logs first — that's the most
likely break point, and their logs will show exactly where.

## Trimming cost

If running all 4 workers continuously is too expensive for a demo that
doesn't need to look "live" every second:

- `airthra-edge-mock` + `airthra-ingest` are the two that generate new
  data — without them the dashboard shows whatever the seed data left
  behind, frozen. Keep both or drop both together; dropping one alone
  just produces errors in the other.
- `airthra-kpi-worker` + `airthra-alarm-engine` only matter if you want
  KPIs/alarms to recompute live. Seeded data already includes some
  alarm rules and historical readings, so a demo can survive without
  these running continuously.
- None of the four are safe to delete from the Blueprint and re-add
  later without re-running their env var setup (step 3) — suspend them
  in Render's dashboard instead of deleting if you want to pause and
  resume.
