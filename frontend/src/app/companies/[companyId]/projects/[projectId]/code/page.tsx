import CodeWorkspace from "@/components/CodeWorkspace";

export default async function CodePage({
  params,
}: {
  params: Promise<{ companyId: string; projectId: string }>;
}) {
  const { companyId, projectId } = await params;
  return <CodeWorkspace companyId={companyId} projectId={projectId} />;
}
