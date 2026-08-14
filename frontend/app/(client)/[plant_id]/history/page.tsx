import HistoryChart from "@/components/HistoryChart";

export default async function HistoryPage({ params }: PageProps<"/[plant_id]/history">) {
  const { plant_id } = await params;
  return <HistoryChart plantId={plant_id} />;
}
