import WikiIndex from "@/components/WikiIndex";

export default async function WikiPage({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = await params;
  return <WikiIndex companyId={companyId} />;
}
