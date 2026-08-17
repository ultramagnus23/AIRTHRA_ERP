import HistoryChart from "@/components/HistoryChart";

export default async function HistoryPage({ params }: PageProps<"/[plant_id]/history">) {
  const { plant_id } = await params;
  return (
    <div className="flex flex-col gap-4">
      <h1 className="font-display text-2xl font-light text-fg">History</h1>
      <HistoryChart plantId={plant_id} />
    </div>
  );
}
