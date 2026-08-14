import EventForm from "@/components/EventForm";

export default async function EventsPage({ params }: PageProps<"/[plant_id]/events">) {
  const { plant_id } = await params;
  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-sm font-semibold text-slate-700">Operator action log</h2>
      <EventForm plantId={plant_id} />
      <p className="text-xs text-slate-400">
        There is currently no GET endpoint to list past operator_events, so this page is
        write-only (matches what P2 shipped — only POST /api/v1/&#123;plant_id&#125;/event
        exists). A list view can be added the same way the alarms list endpoint was, once needed.
      </p>
    </div>
  );
}
