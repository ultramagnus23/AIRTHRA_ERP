"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { login, ApiError } from "@/lib/api";
import { DEPARTMENT_HOME } from "@/lib/departments";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await login(email, password);
      const next = searchParams.get("next");
      if (next && next !== "/login") {
        router.push(next);
      } else if (res.role === "tenant_read" && res.plant_ids.length > 0) {
        router.push(`/${res.plant_ids[0]}`);
      } else if (res.role === "dept_user" && res.department) {
        router.push(DEPARTMENT_HOME[res.department]);
      } else {
        router.push("/");
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex flex-1 items-center justify-center overflow-hidden bg-bg p-6">
      <div
        className="pointer-events-none absolute -top-32 left-1/2 h-96 w-96 -translate-x-1/2 rounded-full opacity-25 blur-3xl"
        style={{ background: "oklch(0.52 0.16 48)" }}
        aria-hidden
      />
      <form onSubmit={handleSubmit} className="relative w-full max-w-sm">
        <p className="mb-3 font-mono text-xs tracking-[0.15em] text-copper uppercase">
          Airthra Research
        </p>
        <h1 className="mb-1 font-display text-3xl font-light text-fg">
          Sign in
        </h1>
        <p className="mb-8 text-sm text-mist">
          Access your plant dashboard, fleet console, or ERP workspace.
        </p>

        <label className="mb-1.5 block text-sm font-medium text-fg" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          type="email"
          required
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mb-4 w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none"
        />

        <label className="mb-1.5 block text-sm font-medium text-fg" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mb-5 w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-fg placeholder:text-mist focus:border-copper focus:outline-none"
        />

        {error && (
          <p className="mb-4 rounded-lg border border-rust bg-panel px-3 py-2 text-sm text-fg">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-rust px-3 py-2.5 text-sm font-medium text-fg transition-colors duration-200 [transition-timing-function:var(--ease)] hover:bg-copper disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
