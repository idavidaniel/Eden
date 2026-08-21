import ProjectBoard from "@/components/ProjectBoard";

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ companyId: string; projectId: string }>;
}) {
  const { companyId, projectId } = await params;
  return <ProjectBoard companyId={companyId} projectId={projectId} />;
}
