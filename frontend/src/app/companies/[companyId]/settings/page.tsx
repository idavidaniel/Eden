import CompanySettings from "@/components/CompanySettings";

export default async function SettingsPage({
  params,
}: {
  params: Promise<{ companyId: string }>;
}) {
  const { companyId } = await params;
  return <CompanySettings companyId={companyId} />;
}
