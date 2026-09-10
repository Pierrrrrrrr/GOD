from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class EventStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.events_path = directory / "events.jsonl"
        self.snapshot_path = directory / "checkpoint.json"

    def append(self, kind: str, payload: dict[str, Any]) -> int:
        sequence = len(self.events())
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"sequence": sequence, "kind": kind, "payload": payload}, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return sequence

    def checkpoint(self, state: dict[str, Any]) -> None:
        temporary = self.snapshot_path.with_suffix(".tmp")
        envelope = {"through_sequence": len(self.events()) - 1, "state": state}
        temporary.write_text(json.dumps(envelope, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(temporary, self.snapshot_path)
        self.append("checkpoint", {"event_count": len(self.events())})

    def load(self) -> dict[str, Any] | None:
        if not self.snapshot_path.exists():
            return None
        return json.loads(self.snapshot_path.read_text(encoding="utf-8"))

    def recover_state(self) -> dict[str, Any] | None:
        checkpoint = self.load()
        state = checkpoint["state"] if checkpoint else None
        through = checkpoint["through_sequence"] if checkpoint else -1
        for event in self.events():
            if event["sequence"] > through and event["kind"] == "state_committed":
                state = event["payload"]["state"]
        return state

    def completed_action(self, action_id: str) -> dict[str, Any] | None:
        for event in reversed(self.events()):
            if event["kind"] == "action_completed" and event["payload"]["action_id"] == action_id:
                return event["payload"]
        return None

    def events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        return [json.loads(line) for line in self.events_path.read_text().splitlines() if line]
