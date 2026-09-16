"""Single fail-closed classification boundary for model-bound data."""
from __future__ import annotations

from enum import Enum
from .capabilities import OwnerCapability, OwnerCapabilityAuthority
from .root import AuthorizationError


class DataClass(str, Enum):
    OWNER_TYPED = "OWNER_TYPED"
    PUBLIC_EVIDENCE = "PUBLIC_EVIDENCE"
    OPERATIONAL_METADATA = "OPERATIONAL_METADATA"
    WORKSPACE_PRIVATE = "WORKSPACE_PRIVATE"
    CREDENTIAL = "CREDENTIAL"
    ROOT_PRIVATE = "ROOT_PRIVATE"
    SISTER_PRIVATE = "SISTER_PRIVATE"


class OutboundDataPolicy:
    ALWAYS_REMOTE = {DataClass.OWNER_TYPED, DataClass.PUBLIC_EVIDENCE,
                     DataClass.OPERATIONAL_METADATA}
    NEVER_REMOTE = {DataClass.CREDENTIAL, DataClass.ROOT_PRIVATE, DataClass.SISTER_PRIVATE}

    def __init__(self, authority: OwnerCapabilityAuthority | None = None):
        self.authority = authority

    def validate(self, classes: set[DataClass], *, remote: bool,
                 artifact_id: str | None = None,
                 content_hash: str | None = None, provider: str | None = None,
                 purpose: str | None = None, approval: OwnerCapability | None = None) -> None:
        if not remote:
            return
        if classes & self.NEVER_REMOTE:
            raise PermissionError("private constitutional data cannot be exported")
        if DataClass.WORKSPACE_PRIVATE in classes:
            if (not artifact_id or not content_hash or not provider or not purpose
                    or approval is None or self.authority is None):
                raise PermissionError("workspace disclosure requires specific owner approval")
            request = approval.request
            if (request.service != provider or request.operation != "disclose_workspace" or request.purpose != purpose
                    or request.account_id != artifact_id
                    or request.allowed_submitted_data != (content_hash,)
                    or request.executor_principal != "outbound-data-policy"
                    or request.maximum_cost != 0):
                raise AuthorizationError("disclosure capability scope mismatch")
            self.authority.start(approval, request, executor_principal="outbound-data-policy")
        unknown = classes - self.ALWAYS_REMOTE - {DataClass.WORKSPACE_PRIVATE}
        if unknown:
            raise PermissionError("unclassified outbound data is blocked")
