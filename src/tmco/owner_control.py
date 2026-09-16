"""Local, non-model emergency phrase enrollment and Root emergency control CLI."""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from .emergency import EmergencyAction, EmergencyPhraseStore
from .system import TMCOSystem
from .executive import Cognition
from .types import ActionCandidate, Goal


class _NoIntelligence(Cognition):
    def decompose(self, goal: Goal) -> list[str]: return []
    def candidates(self, goal: Goal) -> list[ActionCandidate]: return []
    def verify(self, goal: Goal, observation: str) -> bool: return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Root owner emergency control")
    parser.add_argument("command", choices=("enroll-emergency", "pause", "lockdown", "stop", "revoke-external"))
    parser.add_argument("--data", type=Path, default=Path.home() / ".god")
    arguments = parser.parse_args(argv)
    phrase_store = EmergencyPhraseStore(arguments.data)
    phrase = getpass.getpass("Emergency phrase: ")
    if arguments.command == "enroll-emergency":
        confirmation = getpass.getpass("Confirm emergency phrase: ")
        if phrase != confirmation: raise SystemExit("phrases do not match")
        phrase_store.enroll(phrase); return 0
    organism = TMCOSystem(arguments.data, _NoIntelligence())
    authority = organism.emergency
    action = {"pause": EmergencyAction.PAUSE, "lockdown": EmergencyAction.LOCKDOWN,
              "stop": EmergencyAction.STOP, "revoke-external": EmergencyAction.REVOKE_EXTERNAL_CAPABILITIES}[arguments.command]
    authority.apply(authority.attest(phrase_store, phrase, action))
    organism.checkpoint()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
