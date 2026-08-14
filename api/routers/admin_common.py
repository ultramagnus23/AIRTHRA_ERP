"""P7 shared helpers for the admin/global-platform routers.

New file (not touching api/deps.py, which other concurrent phases may also
be extending) - everything P7-specific and reusable across admin_*.py
routers lives here instead.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from ..deps import CurrentUser


def require_global(user: CurrentUser) -> None:
    """Gate for every /admin/* endpoint: global_admin or global_read JWT
    roles only, never tenant_read. Mirrors api/deps.py's
    require_plant_access in spirit (explicit 403, never a silent
    empty-result or 404) but for the "must be global" axis instead of the
    "must own this plant_id" axis.
    """
    if not user.is_global:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this endpoint requires a global_admin or global_read role",
        )


def require_global_admin(user: CurrentUser) -> None:
    """Stricter gate for state-mutating admin endpoints (e.g. invoice
    approval): global_admin only, global_read may not write."""
    if user.role != "global_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this endpoint requires the global_admin role (global_read is read-only)",
        )
