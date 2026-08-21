import CompanyOverview from "@/components/CompanyOverview";

export default async function OverviewPage({
  params,
}: {
  params: Promise<{ companyId: string }>;
}) {
  const { companyId } = await params;
  return <CompanyOverview companyId={companyId} />;
}
