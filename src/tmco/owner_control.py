from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from .emergency import EmergencyFactor, EmergencyState
from .paths import ProductPaths
from .system import TMCOSystem


class _NoCognition:
    def propose(self, *_args: object, **_kwargs: object) -> list[object]: return []
    def verify(self, *_args: object, **_kwargs: object) -> bool: return False


def open_owner_system(data: Path, *, secret: bytes | str | None = None) -> TMCOSystem:
    paths = ProductPaths.resolve(data)
    return TMCOSystem(paths.organism_root, _NoCognition(), owner="Pier", secret=secret)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local constitutional emergency control")
    parser.add_argument("action", choices=("enroll", "pause", "lockdown", "stop", "status"))
    parser.add_argument("--data", type=Path, default=Path.home() / ".god")
    args = parser.parse_args()
    paths, phrase = ProductPaths.resolve(args.data), None
    factor = EmergencyFactor(paths)
    if args.action == "enroll":
        phrase = getpass.getpass("Temporary emergency phrase: ")
        factor.enroll(phrase)
        print("Emergency fallback factor enrolled.")
        return
    system = open_owner_system(args.data)
    if args.action == "status":
        print(system.emergency.state.name); return
    phrase = getpass.getpass("Emergency phrase: ")
    if not factor.verify(phrase):
        raise SystemExit("Emergency authentication failed.")
    target = {"pause": EmergencyState.PAUSED, "lockdown": EmergencyState.LOCKDOWN,
              "stop": EmergencyState.STOP_REQUESTED}[args.action]
    print(system.emergency.restrict(target).state.name)


if __name__ == "__main__": main()
