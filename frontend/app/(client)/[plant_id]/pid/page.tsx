import LiveView from "@/components/LiveView";

// Reuses LiveView's WS-subscription/history-buffer logic rather than
// duplicating it, but renders only the diagram (view="diagram") - the
// Live tab (app/(client)/[plant_id]/page.tsx) renders the tiles+trend
// variant instead, so the two tabs are no longer identical pages.
export default async function PidPage({ params }: PageProps<"/[plant_id]/pid">) {
  const { plant_id } = await params;
  return <LiveView plantId={plant_id} view="diagram" />;
}
