import EventForm from "@/components/EventForm";
import QuickEventBar from "@/components/QuickEventBar";

export default async function EventsPage({ params }: PageProps<"/[plant_id]/events">) {
  const { plant_id } = await params;
  return (
    <div className="flex flex-col gap-4">
      <h1 className="font-display text-2xl font-light text-fg">Operator action log</h1>
      <QuickEventBar plantId={plant_id} />
      <div>
        <h2 className="mb-2 font-mono text-xs tracking-[0.15em] text-mist uppercase">
          Something else
        </h2>
        <EventForm plantId={plant_id} />
      </div>
      <p className="font-mono text-[11px] text-mist">
        There is currently no GET endpoint to list past operator_events, so this page is
        write-only (matches what P2 shipped — only POST /api/v1/&#123;plant_id&#125;/event
        exists). A list view can be added the same way the alarms list endpoint was, once needed.
      </p>
    </div>
  );
}
