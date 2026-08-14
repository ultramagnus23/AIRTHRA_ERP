import ComplianceView from "@/components/ComplianceView";

export default async function CompliancePage({
  params,
}: PageProps<"/[plant_id]/compliance">) {
  const { plant_id } = await params;
  return <ComplianceView plantId={plant_id} />;
}
