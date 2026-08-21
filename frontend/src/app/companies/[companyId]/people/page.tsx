import PeopleDirectory from "@/components/PeopleDirectory";

export default async function PeoplePage({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = await params;
  return <PeopleDirectory companyId={companyId} />;
}
