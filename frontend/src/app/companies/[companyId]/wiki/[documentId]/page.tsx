import WikiPageView from "@/components/WikiPageView";

export default async function DocumentPage({
  params,
}: {
  params: Promise<{ companyId: string; documentId: string }>;
}) {
  const { companyId, documentId } = await params;
  return <WikiPageView companyId={companyId} documentId={documentId} />;
}
