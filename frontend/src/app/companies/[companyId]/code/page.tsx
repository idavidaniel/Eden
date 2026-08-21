import WorkspacePicker from "@/components/WorkspacePicker";

export default async function WorkspacesPage({
  params,
}: {
  params: Promise<{ companyId: string }>;
}) {
  const { companyId } = await params;
  return <WorkspacePicker companyId={companyId} />;
}
