import DriverView from "./DriverView";

// No layout guard here on purpose: this route is excluded from proxy.ts's
// JWT-cookie gate (see the /driver/ check added there) because a driver
// has no user JWT - the [trip_token] segment itself is the credential,
// verified server-side by FastAPI on every ping/stop call.
export default async function DriverPage({
  params,
}: {
  params: Promise<{ trip_token: string }>;
}) {
  const { trip_token } = await params;
  return <DriverView tripToken={trip_token} />;
}
