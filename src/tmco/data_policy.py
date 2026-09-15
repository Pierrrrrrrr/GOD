"""Single fail-closed classification boundary for model-bound data."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DataClass(str, Enum):
    OWNER_TYPED = "OWNER_TYPED"
    PUBLIC_EVIDENCE = "PUBLIC_EVIDENCE"
    OPERATIONAL_METADATA = "OPERATIONAL_METADATA"
    WORKSPACE_PRIVATE = "WORKSPACE_PRIVATE"
    CREDENTIAL = "CREDENTIAL"
    ROOT_PRIVATE = "ROOT_PRIVATE"
    SISTER_PRIVATE = "SISTER_PRIVATE"


@dataclass(frozen=True, slots=True)
class DisclosureApproval:
    approval_id: str
    artifact_id: str


class OutboundDataPolicy:
    ALWAYS_REMOTE = {DataClass.OWNER_TYPED, DataClass.PUBLIC_EVIDENCE,
                     DataClass.OPERATIONAL_METADATA}
    NEVER_REMOTE = {DataClass.CREDENTIAL, DataClass.ROOT_PRIVATE, DataClass.SISTER_PRIVATE}

    def validate(self, classes: set[DataClass], *, remote: bool,
                 artifact_id: str | None = None,
                 approval: DisclosureApproval | None = None) -> None:
        if not remote:
            return
        if classes & self.NEVER_REMOTE:
            raise PermissionError("private constitutional data cannot be exported")
        if DataClass.WORKSPACE_PRIVATE in classes:
            if not artifact_id or approval is None or approval.artifact_id != artifact_id:
                raise PermissionError("workspace disclosure requires specific owner approval")
        unknown = classes - self.ALWAYS_REMOTE - {DataClass.WORKSPACE_PRIVATE}
        if unknown:
            raise PermissionError("unclassified outbound data is blocked")
