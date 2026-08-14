import AlarmsList from "@/components/AlarmsList";

export default async function AlarmsPage({ params }: PageProps<"/[plant_id]/alarms">) {
  const { plant_id } = await params;
  return <AlarmsList plantId={plant_id} />;
}
