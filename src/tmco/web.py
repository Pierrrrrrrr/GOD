"""Dependency-free loopback awakening UI."""
from __future__ import annotations

import argparse
import html
import json
import sqlite3
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .awakening import GodRuntime
from .models import HTTPModelProvider, ModelRecord
from .vault import CredentialVault


PAGE = """<!doctype html><html><head><meta charset=utf-8><title>G.O.D. Awakening</title>
<style>body{font:16px system-ui;max-width:850px;margin:3rem auto;padding:0 1rem;background:#10131a;color:#eef}
fieldset{border:1px solid #456;margin:1rem 0}input,select,button{padding:.65rem;margin:.25rem;background:#202838;color:#fff;border:1px solid #567}
input[name=message]{width:70%}#chat{white-space:pre-wrap;background:#171c26;padding:1rem;min-height:12rem}</style></head>
<body><h1>G.O.D. — Awakening</h1><p>Local-only control surface. Keys disappear after submission.</p>
<div id=status>{status}</div>
<fieldset><legend>Connect a replaceable cognitive organ</legend><form method=post action=/connect>
<select name=provider><option>OpenRouter</option><option>Gemini</option><option>OpenAI-compatible</option></select>
<input name=model placeholder="model id" required><input name=endpoint placeholder="compatible endpoint (optional)">
<input type=password name=key placeholder="API key" autocomplete=off required><button>Securely connect</button></form></fieldset>
<div id=chat>{chat}</div><form method=post action=/chat><input name=message autofocus placeholder="Find a realistic way to achieve X" required>
<button>Send</button></form></body></html>"""


class App:
    def __init__(self, data: Path):
        self.data, self.vault, self.runtime = data, CredentialVault(data), None
        self.transcript: list[str] = []
        credentials = self.vault.load()
        if credentials:
            try: self._connect(credentials)
            except Exception: self.runtime = None
        self._load_transcript()

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
        probe = organ.infer({"model_id": model,
                             "prompt": "Capability probe. Return only JSON: {\"probe\": true}"})
        if probe.get("probe") is not True:
            raise RuntimeError("provider capability probe failed")
        if self.runtime: self.runtime.close()
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
        self.runtime = GodRuntime(self.data, {name: organ}, [record])

    def connect(self, values: dict[str, str]) -> str:
        self._connect(values)
        self.vault.save(values)
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
        intelligence = "CONNECTED" if self.runtime else "DISCONNECTED"
        healthy = (self.runtime is not None
                   and set(self.runtime.organism.colonies) == {"Saphira-A", "Saphira-B"}
                   and self.runtime.organism.root.verify_audit())
        lines = ["Saphira-A ONLINE", "Saphira-B ONLINE", "Root SECURE",
                 f"Intelligence {intelligence}"] if healthy else [
                     "Saphira-A OFFLINE", "Saphira-B OFFLINE", "Root NOT INITIALIZED",
                     f"Intelligence {intelligence}"]
        if self.runtime:
            active = self.runtime.store.rows(
                "SELECT description FROM goals WHERE status='active' ORDER BY rowid DESC LIMIT 1")
            if active: lines.append(f"Active goal: {active[0]['description']}")
        return "<br>".join(html.escape(line) for line in lines)

    def chat(self, message: str) -> str:
        if not self.runtime: return "Connect a model provider first."
        return self.runtime.chat(message)

    def close(self) -> None:
        if self.runtime: self.runtime.close()


def serve(data: Path, port: int, *, open_browser: bool = True) -> None:
    app = App(data)
    class Handler(BaseHTTPRequestHandler):
        def page(self) -> None:
            body = PAGE.format(status=app.status(), chat=html.escape("\n".join(app.transcript))).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self) -> None: self.page()
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            fields = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
            try:
                if self.path == "/connect": response = app.connect(fields)
                else:
                    message = fields.get("message", ""); response = app.chat(message)
                    app.transcript.append(f"Pier: {message}\nG.O.D.: {response}")
            except Exception:
                response = "The request failed. Check provider configuration; no credential details were logged."
            if self.path == "/connect": app.transcript.append(response)
            self.send_response(303); self.send_header("Location", "/"); self.end_headers()
        def log_message(self, format: str, *args: object) -> None: pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if open_browser: threading.Timer(.5, webbrowser.open, (f"http://127.0.0.1:{port}",)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); app.close()


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--data", type=Path, default=Path.home() / ".god")
    parser.add_argument("--port", type=int, default=8765); parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(); serve(args.data, args.port, open_browser=not args.no_browser)


if __name__ == "__main__": main()
