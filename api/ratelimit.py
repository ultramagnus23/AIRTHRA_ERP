"""Brute-force protection for the login endpoint.

Two independent limits, both required (see AUDIT.md §2.10 - the login
endpoint previously had none, with bcrypt's per-attempt cost as the only
brake):

  1. Per-IP attempt ceiling. Blunt instrument against a single host
     spraying many accounts. Counts EVERY attempt, success or failure.
  2. Per-email failure ceiling. Targets the "one account, many guesses"
     case. Counts only FAILURES, and is cleared on a successful login so
     a legitimate user who fumbles their password a few times and then
     gets it right is not left locked out.

The per-email key is the *submitted* email, which is attacker-controlled.
That is deliberate: it means an attacker can lock out an account they know
the address of (a denial-of-service on one user). The alternative - not
limiting per-account - means unlimited guesses against a known address,
which is worse. The DoS window is bounded (FAIL_WINDOW_S) rather than a
permanent lockout requiring support intervention, which is the usual
compromise.

SCOPE LIMITATION - read before deploying more than one API replica:
this is in-process state. Two uvicorn workers each enforce their own
counters, so N replicas multiply the effective limit by N. That is
acceptable for a single-replica deployment and is a real gap beyond it;
moving to a shared Redis backend is tracked in SHIPPING.md Phase B.

Client IP is taken from `request.client.host`, NOT from a raw
X-Forwarded-For header (which any client can forge). Behind Caddy this
requires uvicorn to run with --proxy-headers and --forwarded-allow-ips set
to the proxy's address, so that request.client.host is already the
resolved client. Without that, every request appears to originate from the
proxy and the per-IP limit degrades to a global one - loud and
conservative rather than silently permissive.
"""
from __future__ import annotations

import time
from collections import deque

# Per-IP: total attempts (success or failure) allowed in the window.
IP_MAX_ATTEMPTS = 20
IP_WINDOW_S = 300  # 5 minutes

# Per-email: consecutive failures allowed before the address is locked.
FAIL_MAX_ATTEMPTS = 5
FAIL_WINDOW_S = 900  # 15 minutes

# Stop tracking keys idle longer than this, so the dicts don't grow
# without bound under a distributed spray across many IPs/addresses.
_PRUNE_AFTER_S = max(IP_WINDOW_S, FAIL_WINDOW_S) * 2

_ip_attempts: dict[str, deque[float]] = {}
_email_failures: dict[str, deque[float]] = {}
_last_prune = 0.0


def _trim(bucket: deque[float], window_s: float, now: float) -> None:
    cutoff = now - window_s
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


def _prune(now: float) -> None:
    """Drop keys whose buckets have gone fully stale. Amortised - runs at
    most once per _PRUNE_AFTER_S rather than on every request."""
    global _last_prune
    if now - _last_prune < _PRUNE_AFTER_S:
        return
    _last_prune = now
    for store, window in ((_ip_attempts, IP_WINDOW_S), (_email_failures, FAIL_WINDOW_S)):
        for key in [k for k, b in store.items() if not b or b[-1] < now - window]:
            del store[key]


def check(ip: str, email: str) -> int | None:
    """Called BEFORE verifying credentials. Returns None if the attempt may
    proceed, or the number of seconds to wait if it is rate-limited.

    Deliberately does not distinguish "IP limited" from "email limited" to
    the caller - the endpoint returns the same 429 either way, so a prober
    can't use the response to learn whether an address exists.
    """
    now = time.monotonic()
    _prune(now)

    ip_bucket = _ip_attempts.get(ip)
    if ip_bucket is not None:
        _trim(ip_bucket, IP_WINDOW_S, now)
        if len(ip_bucket) >= IP_MAX_ATTEMPTS:
            return max(1, int(IP_WINDOW_S - (now - ip_bucket[0])))

    fail_bucket = _email_failures.get(email.lower())
    if fail_bucket is not None:
        _trim(fail_bucket, FAIL_WINDOW_S, now)
        if len(fail_bucket) >= FAIL_MAX_ATTEMPTS:
            return max(1, int(FAIL_WINDOW_S - (now - fail_bucket[0])))

    return None


def record_attempt(ip: str) -> None:
    """Every attempt that got past check(), regardless of outcome."""
    now = time.monotonic()
    bucket = _ip_attempts.setdefault(ip, deque())
    _trim(bucket, IP_WINDOW_S, now)
    bucket.append(now)


def record_failure(email: str) -> None:
    now = time.monotonic()
    bucket = _email_failures.setdefault(email.lower(), deque())
    _trim(bucket, FAIL_WINDOW_S, now)
    bucket.append(now)


def clear_failures(email: str) -> None:
    """On successful login - so an honest user who mistyped twice isn't
    carrying those failures toward a lockout."""
    _email_failures.pop(email.lower(), None)


def reset_all() -> None:
    """Test-support only: drops all limiter state."""
    _ip_attempts.clear()
    _email_failures.clear()
