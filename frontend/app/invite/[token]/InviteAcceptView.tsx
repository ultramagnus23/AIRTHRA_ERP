"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getInvite, acceptInvite, InviteApiError, type InviteDetails } from "@/lib/inviteApi";

// Unauthenticated by definition - a visitor with no session, arriving from
// a link an admin copied out of the Tenants page. Never routed through
// /api/backend/* (see lib/inviteApi.ts). On success, redirects to /login
// rather than auto-signing-in: the account's password was just set by the
// same browser tab, so a fresh login is a real (cheap) proof it works,
// not just theater.
export default function InviteAcceptView({ token }: { token: string }) {
  const router = useRouter();
  const [invite, setInvite] = useState<InviteDetails | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    getInvite(token)
      .then(setInvite)
      .catch((err) =>
        setLoadError(err instanceof InviteApiError ? err.message : "failed to load invite"),
      );
  }, [token]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);
    if (password.length < 8) {
      setSubmitError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setSubmitError("Passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await acceptInvite(token, password);
      setDone(true);
      setTimeout(() => router.push("/login"), 2000);
    } catch (err) {
      setSubmitError(err instanceof InviteApiError ? err.message : "failed to accept invite");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 bg-bg p-8">
      <h1 className="font-display text-2xl font-light text-fg">
        Airthra<span className="text-copper">.</span>
      </h1>

      {loadError && (
        <div className="w-full max-w-sm rounded-2xl border border-rust/40 bg-rust/10 p-6 text-center">
          <p className="text-sm text-rust">{loadError}</p>
          <p className="mt-2 font-mono text-xs text-mist">
            Ask whoever added you to Airthra for a fresh invite link.
          </p>
        </div>
      )}

      {done && (
        <div className="air-rise w-full max-w-sm rounded-2xl border border-moss/40 bg-moss/10 p-6 text-center">
          <p className="text-sm text-moss">Password set. Taking you to sign in…</p>
        </div>
      )}

      {invite && !done && !loadError && (
        <form
          onSubmit={handleSubmit}
          className="air-rise flex w-full max-w-sm flex-col gap-4 rounded-2xl border border-hair bg-panel p-6"
          style={{ boxShadow: "var(--shadow-md)" }}
        >
          <div>
            <p className="text-sm text-mist">You're setting up access as</p>
            <p className="font-mono text-sm text-fg">{invite.email}</p>
            <p className="font-mono text-xs text-copper">{invite.role}</p>
          </div>

          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] tracking-[0.08em] text-mist uppercase">
              Choose a password
            </span>
            <input
              type="password"
              required
              minLength={8}
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-lg border border-line bg-transparent px-2.5 py-2 text-sm text-fg focus:border-copper focus:outline-none"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="font-mono text-[11px] tracking-[0.08em] text-mist uppercase">
              Confirm password
            </span>
            <input
              type="password"
              required
              minLength={8}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="rounded-lg border border-line bg-transparent px-2.5 py-2 text-sm text-fg focus:border-copper focus:outline-none"
            />
          </label>

          {submitError && <p className="text-sm text-rust">{submitError}</p>}

          <button
            type="submit"
            disabled={busy}
            className="rounded-full bg-copper px-4 py-2.5 text-sm font-medium text-bg disabled:opacity-40"
          >
            {busy ? "Setting password…" : "Set password and continue"}
          </button>
        </form>
      )}

      {!invite && !loadError && (
        <p className="font-mono text-sm text-mist">Loading invite…</p>
      )}
    </main>
  );
}
