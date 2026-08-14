"use client";

// Mobile-first driver page. Genuinely unauthenticated by JWT - see
// proxy.ts's /driver/ exclusion and lib/driverApi.ts's header comment for
// the full auth story. This component owns all the interactive bits;
// app/driver/[trip_token]/page.tsx just unwraps the async `params`.
//
// What "Start"/"Stop" actually do, since the API surface doesn't map 1:1
// onto the PRD's "driver page" bullet:
//   - Start: 100% client-side. It does NOT call POST /logistics/trips
//     (that's the dispatcher's trip-*creation* call, JWT-gated, already
//     done before this link ever reached the driver). "Start" here means
//     "begin the 30s GPS ping loop" - the trip already exists and is
//     already 'in_transit' server-side from the moment it was created.
//   - Each tick: browser geolocation -> POST /logistics/trips/{id}/ping
//     with X-Trip-Token. This is the only thing that touches the server
//     per tick; no client-side distance/ETA math.
//   - Stop: calls the real POST /logistics/trips/{id}/stop endpoint,
//     which server-side sets status='completed' and completed=now(). This
//     one IS a genuine server mutation, not just a client-side toggle.
import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { DriverApiError, parseTripToken, postPing, stopTrip, type PingResult } from "@/lib/driverApi";

const TripMap = dynamic(() => import("@/components/TripMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-64 w-full items-center justify-center rounded-lg bg-gray-100 text-sm text-gray-400">
      Loading map…
    </div>
  ),
});

const PING_INTERVAL_MS = 30_000;

type Phase = "idle" | "pinging" | "stopped" | "link_error";

export default function DriverView({ tripToken }: { tripToken: string }) {
  const parsed = useRef(parseTripToken(tripToken)).current;

  const [phase, setPhase] = useState<Phase>(parsed ? "idle" : "link_error");
  const [pings, setPings] = useState<PingResult[]>([]);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [pingCount, setPingCount] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const sendPing = useCallback(() => {
    if (!parsed) return;
    if (!("geolocation" in navigator)) {
      setGeoError("Geolocation is not available on this device/browser.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        setGeoError(null);
        try {
          const result = await postPing(parsed.tripId, parsed.token, {
            lat: pos.coords.latitude,
            lon: pos.coords.longitude,
            speed: pos.coords.speed ?? undefined,
          });
          setApiError(null);
          setPings((prev) => [...prev, result]);
          setPingCount((c) => c + 1);
        } catch (err) {
          if (err instanceof DriverApiError) {
            setApiError(`Ping failed (${err.status}): ${err.message}`);
            if (err.status === 401 || err.status === 404) {
              // Invalid/unknown trip link - no point retrying every 30s.
              stopLoop();
              setPhase("link_error");
            }
          } else {
            setApiError("Ping failed: network error.");
          }
        }
      },
      (err) => {
        setGeoError(
          err.code === err.PERMISSION_DENIED
            ? "Location permission denied. Enable it in your browser settings to keep pinging."
            : `Could not get location: ${err.message}`,
        );
      },
      { enableHighAccuracy: true, timeout: 20_000, maximumAge: 0 },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed]);

  const stopLoop = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const handleStart = () => {
    if (!parsed || phase === "pinging") return;
    setPhase("pinging");
    setApiError(null);
    sendPing(); // immediate first ping, then every 30s
    timerRef.current = setInterval(sendPing, PING_INTERVAL_MS);
  };

  const handleStop = async () => {
    if (!parsed) return;
    stopLoop();
    try {
      await stopTrip(parsed.tripId, parsed.token);
      setApiError(null);
    } catch (err) {
      setApiError(err instanceof DriverApiError ? `Stop failed (${err.status}): ${err.message}` : "Stop failed: network error.");
    }
    setPhase("stopped");
  };

  useEffect(() => stopLoop, [stopLoop]);

  if (phase === "link_error") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-red-50 p-6 text-center">
        <p className="text-lg font-semibold text-red-700">Invalid driver link</p>
        <p className="text-sm text-red-600">
          This link doesn&apos;t look like a valid trip link, or the trip could not be found. Ask your
          dispatcher for a fresh link.
        </p>
        {apiError && <p className="text-xs text-red-500">{apiError}</p>}
      </div>
    );
  }

  const lastPing = pings[pings.length - 1];

  return (
    <div className="flex min-h-screen flex-col bg-gray-50">
      <header className="bg-blue-700 px-4 py-4 text-white">
        <h1 className="text-lg font-bold">Airthra Driver</h1>
        <p className="text-xs text-blue-100">Trip {parsed?.tripId.slice(0, 8)}…</p>
      </header>

      <main className="flex flex-1 flex-col gap-4 p-4">
        <StatusBanner phase={phase} lastPingTs={lastPing?.ts} pingCount={pingCount} />

        {geoError && (
          <div className="rounded-lg bg-amber-100 p-3 text-sm text-amber-800" role="alert">
            {geoError}
          </div>
        )}
        {apiError && (
          <div className="rounded-lg bg-red-100 p-3 text-sm text-red-800" role="alert">
            {apiError}
          </div>
        )}

        <div className="flex-1">
          <TripMap pings={pings} heightClassName="h-72" />
        </div>

        <button
          type="button"
          onClick={phase === "pinging" ? handleStop : handleStart}
          disabled={phase === "stopped"}
          className={`w-full rounded-2xl py-6 text-2xl font-bold text-white shadow-lg transition active:scale-95 disabled:cursor-not-allowed disabled:opacity-50 ${
            phase === "pinging" ? "bg-red-600" : "bg-green-600"
          }`}
        >
          {phase === "pinging" ? "STOP TRIP" : phase === "stopped" ? "TRIP ENDED" : "START TRIP"}
        </button>

        <p className="text-center text-xs text-gray-400">
          Keep this page open while driving. GPS location is sent every 30 seconds.
        </p>
      </main>
    </div>
  );
}

function StatusBanner({
  phase,
  lastPingTs,
  pingCount,
}: {
  phase: Phase;
  lastPingTs?: string;
  pingCount: number;
}) {
  const color =
    phase === "pinging" ? "bg-green-100 text-green-800" : phase === "stopped" ? "bg-gray-200 text-gray-600" : "bg-blue-100 text-blue-800";
  const label = phase === "pinging" ? "Pinging live" : phase === "stopped" ? "Trip completed" : "Not started";

  return (
    <div className={`rounded-lg p-3 text-sm font-medium ${color}`}>
      <div className="flex items-center gap-2">
        <span
          className={`h-2.5 w-2.5 rounded-full ${phase === "pinging" ? "animate-pulse bg-green-600" : "bg-gray-400"}`}
        />
        {label}
      </div>
      <div className="mt-1 text-xs font-normal opacity-80">
        {lastPingTs ? `Last ping: ${new Date(lastPingTs).toLocaleTimeString()}` : "No pings sent yet"}
        {pingCount > 0 ? ` · ${pingCount} sent` : ""}
      </div>
    </div>
  );
}
