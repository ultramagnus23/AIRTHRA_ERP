import Link from "next/link";

export default function ForbiddenPage() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
      <h1 className="text-xl font-semibold text-red-700">403 - Not authorized</h1>
      <p className="text-slate-600">Your account is not scoped to this plant.</p>
      <Link href="/" className="mt-4 text-sm text-slate-900 underline">
        Back to dashboard
      </Link>
    </main>
  );
}
