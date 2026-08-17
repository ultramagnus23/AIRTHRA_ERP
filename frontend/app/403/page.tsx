import Link from "next/link";

export default function ForbiddenPage() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-2 bg-bg p-8 text-center">
      <h1 className="font-display text-2xl font-light text-rust">403 — Not authorized</h1>
      <p className="text-mist">Your account is not scoped to this plant.</p>
      <Link href="/" className="mt-4 text-sm text-copper underline hover:text-fg">
        Back to dashboard
      </Link>
    </main>
  );
}
