import AlarmsList from "@/components/AlarmsList";

export default async function AlarmsPage({ params }: PageProps<"/[plant_id]/alarms">) {
  const { plant_id } = await params;
  return (
    <div className="flex flex-col gap-4">
      <h1 className="font-display text-2xl font-light text-fg">Alarms</h1>
      <AlarmsList plantId={plant_id} />
    </div>
  );
}
