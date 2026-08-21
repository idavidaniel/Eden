import ChatWorkspace from "@/components/ChatWorkspace";

export default async function ChatPage({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = await params;
  return <ChatWorkspace companyId={companyId} />;
}
