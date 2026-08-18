"use client";

// Fleet-wide map: one marker per plant, colored by GET /admin/fleet's own
// health color (never recomputed here), positioned at plants.lat/lon.
// Hover shows name/capacity/commissioning/status - the "where's my skid
// and how's it doing" view the plain fleet table couldn't give at a
// glance. Distinct component from TripMap.tsx (that one follows a single
// moving vehicle's GPS trail; this one is a static overview of every
// installed plant) - both live at the shared component layer per
// TripMap.tsx's own header comment inviting a fleet-map reuse.
//
// Must be loaded with `next/dynamic(() => import("@/components/FleetMap"), { ssr: false })`
// - Leaflet touches `window` at import time, same as TripMap.
import { MapContainer, TileLayer, CircleMarker, Tooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import type { FleetEntry } from "@/lib/admin-types";

// Airthra semantic tokens' literal hex values (Leaflet SVG paths can't
// reference CSS custom properties) - same palette/mapping as
// fleet/page.tsx's COLOR_STYLES, just as raw colors instead of Tailwind classes.
const MARKER_COLOR: Record<string, string> = {
  green: "#7a9a5f",
  yellow: "#c9682b",
  red: "#a3402a",
  gray: "#8a8a86",
};

export default function FleetMap({ fleet }: { fleet: FleetEntry[] }) {
  const located = fleet.filter((p): p is FleetEntry & { lat: number; lon: number } => p.lat !== null && p.lon !== null);

  if (located.length === 0) {
    return (
      <div className="flex h-80 w-full items-center justify-center rounded-2xl border border-hair bg-panel font-mono text-sm text-mist">
        No plants have coordinates yet.
      </div>
    );
  }

  // India-centered default view; every located plant fits inside it today
  // (all seeded plants are within India). A future plant far outside this
  // view would still render, just off-screen until the user pans/zooms -
  // no client-side "fit bounds" logic here, since that's presentational
  // convenience, not business logic, and easy to add later without
  // touching data flow.
  const center: [number, number] = [
    located.reduce((s, p) => s + p.lat, 0) / located.length,
    located.reduce((s, p) => s + p.lon, 0) / located.length,
  ];

  return (
    <div className="h-96 w-full overflow-hidden rounded-2xl border border-hair" style={{ boxShadow: "var(--shadow-sm)" }}>
      <MapContainer center={center} zoom={5} scrollWheelZoom style={{ height: "100%", width: "100%" }}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {located.map((p) => (
          <CircleMarker
            key={p.plant_id}
            center={[p.lat, p.lon]}
            radius={9}
            pathOptions={{
              color: MARKER_COLOR[p.color] ?? MARKER_COLOR.gray,
              fillColor: MARKER_COLOR[p.color] ?? MARKER_COLOR.gray,
              fillOpacity: 0.85,
              weight: 2,
            }}
          >
            <Tooltip direction="top" offset={[0, -8]}>
              <div className="font-mono text-xs">
                <div className="font-semibold">{p.name}</div>
                <div>{p.plant_id}</div>
                <div>
                  status: <span>{p.color}</span>
                </div>
                {p.boiler_capacity_tpd !== null && <div>boiler capacity: {p.boiler_capacity_tpd} TPD</div>}
                {p.commissioning_date && <div>commissioned: {p.commissioning_date}</div>}
                <div>
                  last reading:{" "}
                  {p.last_reading_ts ? new Date(p.last_reading_ts).toLocaleString() : "never"}
                </div>
                {p.reasons.length > 0 && <div>{p.reasons.join("; ")}</div>}
              </div>
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
