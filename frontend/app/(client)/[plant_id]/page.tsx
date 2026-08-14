import LiveView from "@/components/LiveView";

export default async function LivePage({ params }: PageProps<"/[plant_id]">) {
  const { plant_id } = await params;
  return <LiveView plantId={plant_id} />;
}
