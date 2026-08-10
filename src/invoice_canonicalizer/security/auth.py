"""Business objective: prevent callers from selecting another client's tenant and restrict knowledge mutations to reviewers.

Technical description: authenticates bearer API keys from secret-manager JSON, binds a principal to one tenant, checks roles, and supports an explicit auth-disabled local assessment mode.
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Protocol

from invoice_canonicalizer.domain.errors import AuthenticationError, AuthorizationError


class Role(StrEnum):
    PROCESSOR = "processor"
    REVIEWER = "reviewer"


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    tenant_id: str | None
    roles: frozenset[Role]
    auth_mode: str


class Authenticator(Protocol):
    @property
    def enabled(self) -> bool: ...

    def authenticate(self, authorization: str | None) -> Principal: ...


class DisabledAuthenticator:
    """Local-only mode; tenant must still be supplied explicitly by the CLI/API request."""

    enabled = False

    def authenticate(self, authorization: str | None) -> Principal:
        del authorization
        return Principal(
            subject="local-auth-disabled",
            tenant_id=None,
            roles=frozenset({Role.PROCESSOR, Role.REVIEWER}),
            auth_mode="disabled",
        )


class ApiKeyAuthenticator:
    enabled = True

    def __init__(self, principals: Mapping[str, Principal]) -> None:
        if not principals:
            raise AuthenticationError("api-key auth requires at least one configured principal")
        self._principals = dict(principals)

    @classmethod
    def from_environment(cls, env_name: str) -> "ApiKeyAuthenticator":
        raw = os.getenv(env_name)
        if not raw:
            raise AuthenticationError(f"missing API auth configuration environment variable: {env_name}")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthenticationError(f"invalid API auth JSON in {env_name}") from exc
        if not isinstance(payload, dict):
            raise AuthenticationError("API auth configuration must be a JSON object")
        principals: dict[str, Principal] = {}
        for token, config in payload.items():
            if not isinstance(config, dict):
                raise AuthenticationError("each API principal must be an object")
            tenant_id = str(config.get("tenant_id", "")).strip()
            if not tenant_id:
                raise AuthenticationError("each API principal requires tenant_id")
            try:
                roles = frozenset(Role(str(item)) for item in config.get("roles", []))
            except ValueError as exc:
                raise AuthenticationError("API principal contains an unsupported role") from exc
            if not roles:
                raise AuthenticationError("each API principal requires at least one role")
            principals[str(token)] = Principal(
                subject=str(config.get("subject", f"api-key:{tenant_id}")),
                tenant_id=tenant_id,
                roles=roles,
                auth_mode="api-key",
            )
        return cls(principals)

    def authenticate(self, authorization: str | None) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthenticationError("missing bearer API key")
        supplied = authorization.removeprefix("Bearer ").strip()
        for configured, principal in self._principals.items():
            if hmac.compare_digest(supplied, configured):
                return principal
        raise AuthenticationError("invalid bearer API key")


def require_role(principal: Principal, role: Role) -> None:
    if role not in principal.roles:
        raise AuthorizationError(f"principal lacks required role: {role.value}")


def resolve_tenant(principal: Principal, supplied_tenant_id: str | None) -> str:
    """Use authenticated scope when enabled and reject, rather than ignore, mismatched tenant input."""
    supplied = (supplied_tenant_id or "").strip()
    if principal.tenant_id is None:
        if not supplied:
            raise AuthorizationError("tenant_id is required when authentication is disabled")
        return supplied
    if supplied and supplied != principal.tenant_id:
        raise AuthorizationError("caller-supplied tenant_id does not match authenticated tenant")
    return principal.tenant_id
