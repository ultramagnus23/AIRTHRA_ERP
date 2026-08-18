import InviteAcceptView from "./InviteAcceptView";

export default async function InvitePage({ params }: PageProps<"/invite/[token]">) {
  const { token } = await params;
  return <InviteAcceptView token={token} />;
}
