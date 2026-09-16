"""Non-evolvable structural envelope for simulation-only DigitalCells."""
from .types import DevelopmentalAction, SAFE_ACTIONS

FORBIDDEN_INTERFACES = frozenset({"filesystem", "network", "credentials", "provider_keys",
    "root", "owner_identity", "subprocess", "shell", "registry", "os_services", "code_execution"})


def require_safe_action(action: DevelopmentalAction) -> None:
    if action not in SAFE_ACTIONS: raise PermissionError("action is outside the cell safety envelope")
