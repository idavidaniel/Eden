import ProjectsList from "@/components/ProjectsList";

export default async function ProjectsPage({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = await params;
  return <ProjectsList companyId={companyId} />;
}
