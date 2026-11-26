"""Tenant management. Super-admin manages all tenants; a tenant admin edits only its own settings."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user, require_roles
from app.core.db import get_db
from app.models import Role, Tenant, User
from app.models.tenant import PLATFORM_SETTINGS
from app.services import access
from app.services import tenants as svc
from app.services.logs import log_event

router = APIRouter(prefix="/tenants", tags=["tenants"])
super_admin = require_roles(Role.SUPER_ADMIN)


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_global: bool
    status: str
    settings: dict
    users: int = 0


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    status: str = "onboarding"


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    status: str | None = None
    settings: dict | None = None


class TenantDelete(BaseModel):
    confirm_name: str


def _out(db: Session, t: Tenant) -> TenantOut:
    return TenantOut(
        id=t.id, name=t.name, slug=t.slug, is_global=t.is_global, status=t.status,
        settings=svc.merge_settings(t.settings or {}, {}), users=svc.user_count(db, t),
    )


def _get(db: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    return tenant


@router.get("", response_model=list[TenantOut])
def list_tenants(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[TenantOut]:
    """Super-admins see every tenant (to manage them, not their content); others only theirs."""
    if user.role == Role.SUPER_ADMIN.value:
        rows = list(db.scalars(select(Tenant).order_by(Tenant.is_global.desc(), Tenant.name)))
    elif user.role == Role.TENANT_ADMIN.value:
        rows = access.managed(db, user)  # what it administers and can hand out
    else:
        rows = access.tenants(db, user)
    return [_out(db, t) for t in rows]


@router.post("", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
def create_tenant(body: TenantCreate, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> TenantOut:
    name = body.name.strip()
    if len(name) < 2:  # the length check of the model counts spaces
        raise HTTPException(422, "The name must be 2 to 120 characters.")
    if body.status not in svc.STATUSES:
        raise HTTPException(422, f"Status must be one of: {', '.join(sorted(svc.STATUSES))}.")
    if svc.name_taken(db, name):
        raise HTTPException(status.HTTP_409_CONFLICT, "A tenant with this name already exists.")
    tenant = Tenant(name=name, slug=svc.unique_slug(db, name), status=body.status)
    db.add(tenant)
    db.commit()
    log_event(db, "tenant.created", actor=admin, tenant_id=tenant.id, target=tenant.name, ip=client_ip(request))
    return _out(db, tenant)


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(tenant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> TenantOut:
    if user.role != Role.SUPER_ADMIN.value and not access.sees(db, user, tenant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    return _out(db, _get(db, tenant_id))


@router.patch("/{tenant_id}", response_model=TenantOut)
def update_tenant(
    tenant_id: uuid.UUID, body: TenantUpdate, request: Request,
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> TenantOut:
    is_super = user.role == Role.SUPER_ADMIN.value
    is_own_admin = access.administers(db, user, tenant_id)
    if not (is_super or is_own_admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed.")
    tenant = _get(db, tenant_id)
    changes: dict = {}

    if body.name is not None or body.status is not None:
        if not is_super:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a super-admin can rename a tenant or change its status.")
        if body.name is not None:
            name = body.name.strip()
            if len(name) < 2:
                raise HTTPException(422, "The name must be 2 to 120 characters.")
            if svc.name_taken(db, name, exclude_id=tenant.id):
                raise HTTPException(status.HTTP_409_CONFLICT, "A tenant with this name already exists.")
            changes["name"] = [tenant.name, name]
            tenant.name = name
        if body.status is not None:
            if body.status not in svc.STATUSES:
                raise HTTPException(422, f"Status must be one of: {', '.join(sorted(svc.STATUSES))}.")
            if tenant.is_global and body.status != "active":
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "The General Knowledge Base is always active.")
            changes["status"] = [tenant.status, body.status]
            tenant.status = body.status

    if body.settings is not None:
        if not is_super and PLATFORM_SETTINGS & body.settings.keys():
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a super-admin can change this setting.")
        try:
            tenant.settings = svc.merge_settings(tenant.settings or {}, body.settings)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        changes["settings"] = body.settings

    db.commit()
    log_event(db, "tenant.updated", actor=user, tenant_id=tenant.id, target=tenant.name, ip=client_ip(request), detail=changes)
    return _out(db, tenant)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    tenant_id: uuid.UUID, body: TenantDelete, request: Request,
    db: Session = Depends(get_db), admin: User = Depends(super_admin),
) -> None:
    tenant = _get(db, tenant_id)
    if tenant.is_global:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The General Knowledge Base cannot be deleted.")
    if body.confirm_name.strip() != tenant.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Type the exact tenant name to confirm.")
    name, tid = tenant.name, tenant.id
    svc.delete_tenant(db, tenant)
    log_event(db, "tenant.deleted", level="warning", actor=admin, tenant_id=tid, target=name, ip=client_ip(request))
