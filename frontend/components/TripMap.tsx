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
import { useEffect, useMemo, useRef } from "react";
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Leaflet's default marker icon points at image URLs that don't resolve
// under a bundler unless patched - standard react-leaflet workaround.
const driverIcon = L.icon({
  iconUrl:
    "data:image/svg+xml;base64," +
    btoa(
      `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8" fill="#2563eb" stroke="white" stroke-width="2"/>
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
        <circle cx="5" cy="5" r="3" fill="#93c5fd" stroke="#2563eb" stroke-width="1"/>
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
  const initialCenter = useRef<[number, number] | null>(null);
  if (!initialCenter.current && latest) {
    initialCenter.current = [latest.lat, latest.lon];
  }

  if (!latest) {
    return (
      <div
        className={`flex ${heightClassName} w-full items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 text-sm text-gray-500`}
      >
        No GPS pings yet
      </div>
    );
  }

  const trail: [number, number][] = sorted.map((p) => [p.lat, p.lon]);

  return (
    <div className={`${heightClassName} w-full overflow-hidden rounded-lg`}>
      <MapContainer
        center={initialCenter.current ?? [latest.lat, latest.lon]}
        zoom={15}
        scrollWheelZoom
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {trail.length > 1 && <Polyline positions={trail} pathOptions={{ color: "#2563eb", weight: 3 }} />}
        {sorted.slice(0, -1).map((p, i) => (
          <Marker key={`${p.ts}-${i}`} position={[p.lat, p.lon]} icon={trailIcon} />
        ))}
        <Marker position={[latest.lat, latest.lon]} icon={driverIcon}>
          <Popup>
            {new Date(latest.ts).toLocaleTimeString()}
            {typeof latest.speed === "number" ? ` — ${latest.speed.toFixed(1)} m/s` : ""}
          </Popup>
        </Marker>
        <FollowLatest lat={latest.lat} lon={latest.lon} enabled={follow} />
      </MapContainer>
    </div>
  );
}
