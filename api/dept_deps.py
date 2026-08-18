"""Department-scoped RBAC gate, built on top of api/deps.py's CurrentUser/
get_current_user/db_session (reused, not duplicated - deps.py itself is
not touched here, same discipline api/erp_deps.py already follows).

Five business functions exist: finance, procurement, engineering, sales,
logistics (security.DEPARTMENTS is the single source of truth for the
list). A dept_user's JWT carries exactly one of them; require_department
grants access only to the router(s) tagged with that department, and
always lets global_admin/global_read through regardless of department
(mirrors api/erp_deps.py's global-only gates - global roles see
everything, department roles see one slice).

This is deliberately a *narrower* gate than api/erp_deps.py's
erp_read_user/erp_admin_user: those two only ever admit global roles.
Routers that should also admit the matching department import
require_department from here instead (or in addition, for endpoints that
mix a department concern with a global-only one - see
api/routers/production.py's installations endpoint, which stays
global-only on purpose: it's the ERP<->machine-data bridge, not a single
department's resource).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from .deps import CurrentUser, db_session, get_current_user  # noqa: F401  (re-exported for routers)
from .security import DEPARTMENTS

__all__ = [
    "CurrentUser",
    "db_session",
    "get_current_user",
    "require_department",
    "require_department_admin",
]


def _check_departments(allowed: tuple[str, ...]) -> None:
    unknown = set(allowed) - DEPARTMENTS
    if unknown:
        raise ValueError(f"require_department: unknown department(s) {unknown}")


def require_department(*allowed: str):
    """Read-tier gate, the department analogue of erp_deps.erp_read_user:
    global_admin, global_read, or a dept_user whose department is in
    `allowed` - any other role (the plant-scoped tenant roles) is always
    rejected, since department resources are never plant-scoped."""
    _check_departments(allowed)

    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.is_global:
            return user
        if user.role == "dept_user" and user.department in allowed:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "this endpoint requires a global_admin/global_read user, "
                f"or a dept_user in one of: {', '.join(sorted(allowed))}"
            ),
        )

    return _dep


def require_department_admin(*allowed: str):
    """Write-tier gate, the department analogue of erp_deps.erp_admin_user:
    global_admin, or a dept_user whose department is in `allowed`.
    global_read is deliberately excluded here (same read-only intent as
    erp_admin_user) - a department login gets full read+write within its
    own function, but a global_read login stays read-only everywhere,
    department resources included."""
    _check_departments(allowed)

    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role == "global_admin":
            return user
        if user.role == "dept_user" and user.department in allowed:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "this action requires a global_admin user, "
                f"or a dept_user in one of: {', '.join(sorted(allowed))}"
            ),
        )

    return _dep
