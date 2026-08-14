import LiveView from "@/components/LiveView";

// Reuses LiveView, which already renders the PidDiagram beneath the
// sensor tiles - kept as a distinct route per the brief's "P&ID SVG
// mimic" bullet so it's directly linkable/navigable, without
// duplicating the WS subscription logic.
export default async function PidPage({ params }: PageProps<"/[plant_id]/pid">) {
  const { plant_id } = await params;
  return <LiveView plantId={plant_id} />;
}
