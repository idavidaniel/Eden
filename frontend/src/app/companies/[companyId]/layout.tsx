import CompanyShell from "@/components/CompanyShell";

export default async function CompanyLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ companyId: string }>;
}) {
  const { companyId } = await params;
  return <CompanyShell companyId={companyId}>{children}</CompanyShell>;
}
