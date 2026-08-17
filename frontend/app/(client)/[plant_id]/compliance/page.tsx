import ComplianceView from "@/components/ComplianceView";

export default async function CompliancePage({
  params,
}: PageProps<"/[plant_id]/compliance">) {
  const { plant_id } = await params;
  return (
    <div className="flex flex-col gap-4">
      <h1 className="font-display text-2xl font-light text-fg">Compliance</h1>
      <ComplianceView plantId={plant_id} />
    </div>
  );
}
