"""P5 ERP auth gate: global_admin/global_read-gated dependencies, built on
top of api/deps.py's CurrentUser/get_current_user/db_session (reused, not
duplicated - deps.py itself is not touched, per the P5 phase boundary).

ERP tables (vendors, materials, quotations, projects, drawings, boms, pos,
grn, vendor_invoices, tasks, ...) carry no plant_id and are not RLS-scoped
(see migrations/versions/0001_initial_schema.py, "NOTE ON TABLES WITHOUT
RLS"). Access control for them is a role/permission concern at the API
layer, which is exactly what this module implements: any global_admin or
global_read user may read; only global_admin may write.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from .deps import CurrentUser, db_session, get_current_user  # noqa: F401  (re-exported for routers)

__all__ = ["CurrentUser", "db_session", "get_current_user", "erp_read_user", "erp_admin_user"]


async def erp_read_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Gate for GET/list/detail ERP endpoints: global_admin or global_read."""
    if not user.is_global:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ERP endpoints require a global_admin or global_read user",
        )
    return user


async def erp_admin_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Gate for write (create/update/release/PDF-generate/...) ERP endpoints:
    global_admin only."""
    if user.role != "global_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this ERP action requires a global_admin user",
        )
    return user
