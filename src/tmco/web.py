"""Dependency-free loopback awakening UI."""
from __future__ import annotations

import argparse
import html
import json
import sqlite3
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .awakening import GodRuntime
from .connectors import (GeminiConnector, OllamaConnector, OpenAICompatibleConnector,
                         OpenRouterConnector, ProviderConnector)
from .models import HTTPModelProvider, ModelRecord, ModelRouter
from .vault import CredentialHandle, CredentialVault


PAGE = """<!doctype html><html><head><meta charset=utf-8><title>G.O.D. Awakening</title>
<style>body{font:16px system-ui;max-width:850px;margin:3rem auto;padding:0 1rem;background:#10131a;color:#eef}
fieldset{border:1px solid #456;margin:1rem 0}input,select,button{padding:.65rem;margin:.25rem;background:#202838;color:#fff;border:1px solid #567}
input[name=message]{width:70%}#chat{white-space:pre-wrap;background:#171c26;padding:1rem;min-height:12rem}</style></head>
<body><h1>G.O.D. — Awakening</h1><p>Local-only control surface. Keys disappear after submission.</p>
<div id=status>{status}</div>
<fieldset><legend>INTELLIGENCE</legend>
<form method=post action=/import><input name=path placeholder="secrets.json path" required>
<label><input type=checkbox name=delete value=yes>Delete source file after secure import</label>
<button>IMPORT SECRETS FILE</button></form>
<form method=post action=/openrouter><input type=password name=key placeholder="OpenRouter API key" autocomplete=off required>
<button>CONNECT OPENROUTER</button></form>
<form method=post action=/local><button>DETECT LOCAL MODELS</button></form>
<form method=post action=/policy><label>Routing <select name=policy><option>AUTO</option><option value=FREE_FIRST>FREE FIRST</option>
<option value=LOCAL_FIRST>LOCAL FIRST</option></select></label><button>Apply</button></form>
<details><summary>Advanced</summary><form method=post action=/connect>
<select name=provider><option>OpenRouter</option><option>Gemini</option><option>OpenAI-compatible</option></select>
<input name=model placeholder="model id" required><input name=endpoint placeholder="compatible endpoint">
<input type=password name=key placeholder="API key" autocomplete=off required><button>Connect manually</button></form></details></fieldset>
<div id=chat>{chat}</div><form method=post action=/chat><input name=message autofocus placeholder="Find a realistic way to achieve X" required>
<button>Send</button></form></body></html>"""


class App:
    def __init__(self, data: Path):
        self.data, self.vault = data, CredentialVault(data)
        # The organism is primary and always boots; intelligence is an attachable organ.
        self.runtime = GodRuntime(data)
        self.connectors: dict[str, ProviderConnector] = {}
        self.discovered: dict[str, ModelRecord] = {}
        self.transcript: list[str] = []
        self._connect_stored_credentials()
        self._load_transcript()

    def _connector(self, handle: CredentialHandle) -> ProviderConnector | None:
        key = self.vault.resolve(handle)
        if handle.provider == "openrouter":
            return OpenRouterConnector(key)
        if handle.provider == "gemini":
            return GeminiConnector(key)
        if handle.provider == "groq":
            return OpenAICompatibleConnector("groq", "https://api.groq.com/openai/v1/chat/completions", key)
        return None

    def _connect_stored_credentials(self) -> None:
        for handle in self.vault.handles():
            try:
                connector = self._connector(handle)
                if connector is not None:
                    self._add_connector(connector)
            except Exception:
                continue
        self._apply_connectors()

    def _add_connector(self, connector: ProviderConnector) -> int:
        records = connector.discover()
        if not records:
            return 0
        preferred = next((r for r in records if r.model_id == "openrouter/free"), records[0])
        connector.probe(preferred.model_id)
        self.connectors[connector.name] = connector
        self.discovered.update((record.key, record) for record in records)
        return len(records)

    def _apply_connectors(self) -> None:
        if self.connectors and self.discovered:
            self.runtime.attach_intelligence(self.connectors, list(self.discovered.values()))

    def import_secrets(self, path: str, *, delete_source: bool = False) -> int:
        handles = self.vault.import_file(Path(path), delete_source=delete_source)
        count = 0
        for handle in handles:
            connector = self._connector(handle)
            if connector is not None:
                try: count += self._add_connector(connector)
                except Exception: continue
        self._apply_connectors()
        return count

    def connect_openrouter(self, api_key: str) -> int:
        connector = OpenRouterConnector(api_key)
        records = connector.discover()
        if not records:
            raise RuntimeError("provider catalog is unavailable")
        preferred = next((r for r in records if r.model_id == "openrouter/free"), records[0])
        connector.probe(preferred.model_id)
        self.vault.set_provider("openrouter", api_key)
        self.connectors[connector.name] = connector
        self.discovered.update((record.key, record) for record in records)
        self._apply_connectors()
        return len(records)

    def detect_local_models(self) -> int:
        connector = OllamaConnector()
        records = connector.discover()
        if not records:
            return 0
        connector.probe(records[0].model_id)
        self.connectors[connector.name] = connector
        self.discovered.update((record.key, record) for record in records)
        self._apply_connectors()
        return len(records)

    def _connect(self, values: dict[str, str]) -> None:
        provider, model, key = values["provider"], values["model"], values["key"]
        if provider == "Gemini":
            endpoint = "https://generativelanguage.googleapis.com/v1beta"
            organ = HTTPModelProvider(endpoint, key, gemini=True)
            name = "gemini"
        else:
            endpoint = values.get("endpoint") or "https://openrouter.ai/api/v1/chat/completions"
            organ = HTTPModelProvider(endpoint, key)
            name = "openrouter" if provider == "OpenRouter" else "compatible"
        started = time.monotonic()
        probe = organ.infer({"model_id": model,
                             "prompt": "Capability probe. Return only JSON: {\"probe\": true}"})
        probe_latency = (time.monotonic() - started) * 1000
        if probe.get("probe") is not True:
            raise RuntimeError("provider capability probe failed")
        record = ModelRecord(name, model)
        catalog = organ.catalog()
        metadata = next((item for item in catalog if item.get("id", item.get("name", "")).endswith(model)), None)
        if metadata:
            record.context_capability = metadata.get("context_length") or metadata.get("inputTokenLimit")
            record.modalities = metadata.get("architecture", {}).get("input_modalities", ["text"])
            record.tool_capability = "generateContent" in metadata.get("supportedGenerationMethods", [])
            pricing = metadata.get("pricing", {})
            record.input_cost = self._price(pricing.get("prompt"))
            record.output_cost = self._price(pricing.get("completion"))
        self.runtime.attach_intelligence({name: organ}, [record])
        attached = self.runtime.records[record.key]
        ModelRouter.observe_call(attached, True, probe_latency)
        self.runtime._save_models()

    def connect(self, values: dict[str, str]) -> str:
        self._connect(values)
        provider = "gemini" if values["provider"] == "Gemini" else "openrouter"
        self.vault.set_provider(provider, values["key"])
        return "Connected. The credential is protected and is not displayed."

    @staticmethod
    def _price(value: object) -> float | None:
        if value is None: return None
        try: return float(value)
        except (TypeError, ValueError): return None

    def _load_transcript(self) -> None:
        database = self.data / "awakening.sqlite3"
        if not database.exists(): return
        connection = sqlite3.connect(database)
        try:
            rows = connection.execute("SELECT role,content FROM chat ORDER BY id").fetchall()
            self.transcript = [f"{'Pier' if role == 'user' else 'G.O.D.'}: {content}"
                               for role, content in rows]
        finally: connection.close()

    def status(self) -> str:
        intelligence = "CONNECTED" if self.runtime.intelligence_connected else "DISCONNECTED"
        healthy = (set(self.runtime.organism.colonies) == {"Saphira-A", "Saphira-B"}
                   and self.runtime.organism.root.verify_audit())
        lines = ["Saphira-A ONLINE", "Saphira-B ONLINE", "Root SECURE",
                 f"Intelligence {intelligence}"] if healthy else [
                     "Saphira-A OFFLINE", "Saphira-B OFFLINE", "Root NOT INITIALIZED",
                     f"Intelligence {intelligence}"]
        lines.append(f"Discovered providers: {len(self.runtime.bus.providers)}; models: {len(self.runtime.records)}")
        lines.append(f"Routing: {self.runtime.routing_policy}")
        active = self.runtime.store.rows(
            "SELECT description FROM goals WHERE status='active' ORDER BY rowid DESC LIMIT 1")
        if active:
            lines.extend((f"Current goal: {active[0]['description']}", "Current step: reasoning",
                          "Work class: DELIBERATIVE", "Current body organ: none",
                          "A confidence: pending", "B confidence: pending"))
        else:
            lines.extend(("Current goal: none", "Current step: idle", "Work class: REFLEX",
                          "Current body organ: none", "A confidence: n/a", "B confidence: n/a"))
        lines.extend(("Last observation: none", "Pending approval: none", "Capability gaps: none",
                      "Sister exchange: none", "Latest latency: n/a"))
        return "<br>".join(html.escape(line) for line in lines)

    def chat(self, message: str) -> str:
        return self.runtime.chat(message)

    def close(self) -> None:
        self.runtime.close()


def serve(data: Path, port: int, *, open_browser: bool = True) -> None:
    app = App(data)
    class Handler(BaseHTTPRequestHandler):
        def page(self) -> None:
            body = PAGE.replace("{status}", app.status()).replace(
                "{chat}", html.escape("\n".join(app.transcript))).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self) -> None: self.page()
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            fields = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
            try:
                if self.path == "/connect": response = app.connect(fields)
                elif self.path == "/import":
                    count = app.import_secrets(fields.get("path", ""),
                                               delete_source=fields.get("delete") == "yes")
                    response = f"Secrets securely imported. Discovered {count} models."
                elif self.path == "/openrouter":
                    count = app.connect_openrouter(fields.get("key", ""))
                    response = f"OpenRouter connected. Discovered {count} models."
                elif self.path == "/local":
                    count = app.detect_local_models()
                    response = f"Discovered {count} local models."
                elif self.path == "/policy":
                    app.runtime.set_routing_policy(fields.get("policy", "AUTO"))
                    response = f"Routing policy: {app.runtime.routing_policy}."
                else:
                    message = fields.get("message", ""); response = app.chat(message)
                    app.transcript.append(f"Pier: {message}\nG.O.D.: {response}")
            except Exception:
                response = "The request failed. Check provider configuration; no credential details were logged."
            if self.path != "/chat": app.transcript.append(response)
            self.send_response(303); self.send_header("Location", "/"); self.end_headers()
        def log_message(self, format: str, *args: object) -> None: pass
    # The runtime and its SQLite connection are intentionally confined to this
    # single-user server thread. Browser launching is the only background work.
    server = HTTPServer(("127.0.0.1", port), Handler)
    if open_browser: threading.Timer(.5, webbrowser.open, (f"http://127.0.0.1:{port}",)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); app.close()


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--data", type=Path, default=Path.home() / ".god")
    parser.add_argument("--port", type=int, default=8765); parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(); serve(args.data, args.port, open_browser=not args.no_browser)


if __name__ == "__main__": main()
