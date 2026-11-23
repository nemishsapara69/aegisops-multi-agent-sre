import hmac
import logging
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.rag.rbac import normalize_role

load_dotenv()
log = logging.getLogger("aegisops.api")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class Principal:
    name: str
    role: str            # RBAC role used by the memory agent
    can_approve: bool


def load_keys():
    """AEGIS_API_KEYS = key:name:role:perm,key:name:role:perm   (perm is approver or member)."""
    entries = []
    for part in os.environ.get("AEGIS_API_KEYS", "").split(","):
        bits = [b.strip() for b in part.strip().split(":")]
        if len(bits) != 4 or not all(bits):
            if part.strip():
                log.warning("ignoring a malformed AEGIS_API_KEYS entry")
            continue
        key, name, role, perm = bits
        entries.append((key, Principal(name=name, role=normalize_role(role),
                                       can_approve=(perm.lower() == "approver"))))
    return entries


def authenticate(api_key: Optional[str] = Security(api_key_header)) -> Principal:
    entries = load_keys()
    if not entries:
        raise HTTPException(status_code=503, detail="API keys are not configured on the server.")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    found = None
    for key, principal in entries:                 # check every entry, no early exit
        if hmac.compare_digest(api_key.encode("utf-8"), key.encode("utf-8")):
            found = principal
    if found is None:
        log.warning("rejected a request with an invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return found


def require_approver(principal: Principal = Depends(authenticate)) -> Principal:
    if not principal.can_approve:
        raise HTTPException(status_code=403,
                            detail="This API key is not allowed to approve or reject changes.")
    return principal