import EmployeeProfile from "@/components/EmployeeProfile";

export default async function EmployeePage({
  params,
}: {
  params: Promise<{ companyId: string; employeeId: string }>;
}) {
  const { companyId, employeeId } = await params;
  return <EmployeeProfile companyId={companyId} employeeId={employeeId} />;
}
