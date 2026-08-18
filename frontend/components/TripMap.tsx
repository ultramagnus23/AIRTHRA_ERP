"use client";

// Reusable live trip map: renders a trip's GPS pings (trip_pings rows) as
// a marker trail plus a live marker at the latest position.
//
// This is intentionally generic (owned by the driver-page workstream, not
// the admin logistics screen), so the admin agent can import it for their
// own fleet-map page later: `import TripMap from "@/components/TripMap"`.
// It renders whatever `pings` it's given and computes nothing business-y
// itself (no ETA/distance) - fetching/polling is the caller's job.
//
// Must be loaded with `next/dynamic(() => import("@/components/TripMap"), { ssr: false })`
// by any server-rendered page that uses it - Leaflet touches `window` at
// import time and has no SSR-safe path.
import { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Leaflet's default marker icon points at image URLs that don't resolve
// under a bundler unless patched - standard react-leaflet workaround.
// Colors below are the literal rendered values of --color-rust / a
// lighter mist mix (Leaflet icon SVGs can't reference CSS custom
// properties, so the Airthra palette is inlined here to stay in sync
// with globals.css's token values).
const driverIcon = L.icon({
  iconUrl:
    "data:image/svg+xml;base64," +
    btoa(
      `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8" fill="#c9682b" stroke="#f3efe9" stroke-width="2"/>
      </svg>`,
    ),
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

const trailIcon = L.icon({
  iconUrl:
    "data:image/svg+xml;base64," +
    btoa(
      `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10">
        <circle cx="5" cy="5" r="3" fill="#8a4a20" stroke="#c9682b" stroke-width="1"/>
      </svg>`,
    ),
  iconSize: [10, 10],
  iconAnchor: [5, 5],
});

export interface TripPing {
  trip_id?: string;
  ts: string;
  lat: number;
  lon: number;
  speed?: number | null;
}

interface TripMapProps {
  pings: TripPing[];
  /** Follow the latest ping by re-centering the map as new pings arrive. */
  follow?: boolean;
  heightClassName?: string;
}

function FollowLatest({ lat, lon, enabled }: { lat: number; lon: number; enabled: boolean }) {
  const map = useMap();
  useEffect(() => {
    if (enabled) map.setView([lat, lon], map.getZoom(), { animate: true });
  }, [lat, lon, enabled, map]);
  return null;
}

export default function TripMap({ pings, follow = true, heightClassName = "h-64" }: TripMapProps) {
  const sorted = useMemo(
    () => [...pings].sort((a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime()),
    [pings],
  );
  const latest = sorted[sorted.length - 1];

  if (!latest) {
    return (
      <div
        className={`flex ${heightClassName} w-full items-center justify-center rounded-2xl border border-hair bg-panel font-mono text-sm text-mist`}
      >
        No GPS pings yet
      </div>
    );
  }

  const trail: [number, number][] = sorted.map((p) => [p.lat, p.lon]);

  return (
    <div className={`${heightClassName} w-full overflow-hidden rounded-2xl`}>
      <MapContainer
        // react-leaflet's MapContainer only reads `center` at mount -
        // changing it on a later render does not move an already-mounted
        // map (that's why FollowLatest above exists, using useMap() +
        // an imperative setView() to actually re-center as new pings
        // arrive). A ref-frozen "initial" value was therefore redundant:
        // whatever renders here the moment this component first mounts
        // is the only evaluation that ever matters.
        center={[latest.lat, latest.lon]}
        zoom={15}
        scrollWheelZoom
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {trail.length > 1 && <Polyline positions={trail} pathOptions={{ color: "#c9682b", weight: 3 }} />}
        {sorted.slice(0, -1).map((p, i) => (
          <Marker key={`${p.ts}-${i}`} position={[p.lat, p.lon]} icon={trailIcon} />
        ))}
        <Marker position={[latest.lat, latest.lon]} icon={driverIcon}>
          <Popup>
            <span className="font-mono text-xs">
              {new Date(latest.ts).toLocaleTimeString()}
              {typeof latest.speed === "number" ? ` — ${latest.speed.toFixed(1)} m/s` : ""}
            </span>
          </Popup>
        </Marker>
        <FollowLatest lat={latest.lat} lon={latest.lon} enabled={follow} />
      </MapContainer>
    </div>
  );
}
