"""Dependency-free loopback awakening UI."""
from __future__ import annotations

import argparse
import html
import json
import sqlite3
import threading
import time
import webbrowser
import queue
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .awakening import GodRuntime
from .connectors import (GeminiConnector, OllamaConnector, OpenAICompatibleConnector,
                         OpenRouterConnector, ProviderConnector)
from .models import HTTPModelProvider, ModelRecord, ModelRouter
from .vault import CredentialHandle, CredentialVault

PROVIDER_STATES = {"CONNECTED", "INVALID_CREDENTIAL", "UNAVAILABLE", "RECONNECT_REQUIRED", "NOT_CONFIGURED"}


PAGE = """<!doctype html><html><head><meta charset=utf-8><title>G.O.D. Observatory</title>
<style>:root{color-scheme:dark}body{font:14px system-ui;margin:0;background:#0b0f17;color:#e8edf8}header{display:flex;gap:1.3rem;padding:1rem 2rem;background:#141b28;border-bottom:1px solid #33415c;position:sticky;top:0}.ok{color:#75e0a7}.off{color:#ffbc70}.grid{display:grid;grid-template-columns:1fr 2fr 1.25fr;gap:1rem;padding:1rem}.panel,fieldset{background:#121925;border:1px solid #2c3952;border-radius:8px;padding:1rem}input,select,button{padding:.65rem;margin:.25rem;background:#202b3e;color:#fff;border:1px solid #526582;border-radius:4px}input[name=message]{width:70%}#chat{white-space:pre-wrap;min-height:20rem}.timeline{max-height:65vh;overflow:auto}.event{border-left:2px solid #709cf5;padding:.35rem .65rem;margin:.5rem 0}.offline{text-align:center;border-color:#b27a3e}.offline h2{letter-spacing:.12em}.summary{margin:.6rem 0;padding:.6rem;background:#192234}a{color:#8fb5ff}@media(max-width:900px){.grid{grid-template-columns:1fr}}</style></head>
<body><header>{header}</header><main>{onboarding}<div class=grid><section class=panel><h2>Current task</h2><div id=task>{status}</div>{approval}</section>
<section class=panel><h2>Owner conversation</h2><div id=chat>{chat}</div><form id=chat-form method=post action=/chat><input name=message autofocus placeholder="Find a realistic way to achieve X" required><button>Send</button></form><h3>Safe sister summaries</h3><div id=sisters>{sisters}</div></section>
<aside class="panel timeline"><h2>Live activity</h2><div id=events>{timeline}</div></aside></div>
<fieldset><legend>Intelligence controls</legend><form method=post action=/local><button>DETECT LOCAL MODELS</button></form>
<form method=post action=/policy><label>Routing <select name=policy><option>AUTO</option><option value=FREE_FIRST>FREE FIRST</option><option value=LOCAL_FIRST>LOCAL FIRST</option></select></label><button>Apply</button></form>
<details><summary>Advanced: secrets file, custom endpoint, manual provider/model IDs</summary><form method=post action=/import><input name=path placeholder="secrets.json path" required><label><input type=checkbox name=delete value=yes>Delete source after secure import</label><button>IMPORT</button></form><form method=post action=/connect>
<select name=provider><option>OpenRouter</option><option>Gemini</option><option>OpenAI-compatible</option></select>
<input name=model placeholder="model id" required><input name=endpoint placeholder="compatible endpoint">
<input type=password name=key placeholder="API key" autocomplete=off required><button>Connect manually</button></form></details></fieldset></main>
<script>
const esc=x=>String(x??'none').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function poll(){const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)return;const s=await r.json();
document.querySelector('#events').innerHTML=s.timeline.slice().reverse().map(e=>`<div class=event><b>${esc(e.kind)}</b><br>${esc(e.summary)}</div>`).join('');
document.querySelector('#task').innerHTML=['job: '+esc(s.job?.state),'goal: '+esc(s.goal?.description),'step: '+esc(s.goal?.current_step),'work class: '+esc(s.goal?.work_class),'selected colony: '+esc(s.goal?.selected_colony),'selected model: '+esc(s.selection&&s.selection.provider+':'+s.selection.model_id),'routing reason: '+esc(s.selection?.routing_reason),'organ: '+esc(s.goal?.current_organ),'verification: '+esc(s.verification),'pending approval: '+esc(s.pending_approval?.id),'capability gap: '+esc(s.capability_gap?.reason)].join('<br>');
document.querySelector('#sisters').innerHTML=Object.entries(s.sisters).map(([n,v])=>`<div class=summary><b>${esc(n)}</b><br>${esc(v?.status)} · ${esc(v?.summary)} · confidence ${esc(v?.confidence)}</div>`).join('');
document.querySelector('#chat').textContent=s.conversation.map(x=>(x.role==='user'?'Pier: ':'G.O.D.: ')+x.content).join('\n');}
document.querySelector('#chat-form').addEventListener('submit',async e=>{e.preventDefault();const f=e.currentTarget;await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(f))});f.reset();poll()});setInterval(poll,750);
</script></body></html>"""


class App:
    def __init__(self, data: Path):
        self.data, self.vault = data, CredentialVault(data)
        # The organism is primary and always boots; intelligence is an attachable organ.
        self.runtime = GodRuntime(data)
        self.connectors: dict[str, ProviderConnector] = {}
        self.discovered: dict[str, ModelRecord] = {}
        self.provider_states = {name: "NOT_CONFIGURED" for name in ("openrouter", "gemini", "ollama")}
        self.transcript: list[str] = []
        self._connect_stored_credentials()
        # Local discovery is safe and credential-free. Absence is an ordinary
        # offline state; production inference is never replaced with a fixture.
        try:
            self.detect_local_models()
        except Exception:
            pass
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
                    count = self._add_connector(connector)
                    self.provider_states[handle.provider] = "CONNECTED" if count else "RECONNECT_REQUIRED"
            except Exception:
                self.provider_states[handle.provider] = "RECONNECT_REQUIRED"
                continue
        self._apply_connectors()

    def _add_connector(self, connector: ProviderConnector) -> int:
        records = connector.discover()
        if not records:
            return 0
        preferred = next((r for r in records if r.model_id == "openrouter/free"), records[0])
        connector.probe(preferred.model_id)
        self.connectors[connector.name] = connector
        self.provider_states[connector.name] = "CONNECTED"
        self.discovered.update((record.key, record) for record in records)
        return len(records)

    def _apply_connectors(self) -> None:
        if self.connectors and self.discovered:
            self.runtime.attach_intelligence(self.connectors, list(self.discovered.values()))

    def import_secrets(self, path: str, delete_source: bool = False) -> int:
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

    def connect_gemini(self, api_key: str) -> int:
        connector = GeminiConnector(api_key)
        records = connector.discover()
        if not records: raise RuntimeError("provider catalog is unavailable")
        connector.probe(records[0].model_id)
        self.vault.set_provider("gemini", api_key)
        self.connectors[connector.name] = connector
        self.provider_states["gemini"] = "CONNECTED"
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
        self.provider_states[provider] = "CONNECTED"
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
        lines.extend(f"{name.title()} — {status}" for name, status in self.provider_states.items())
        state = self.runtime.operational_status(); show = lambda value: "none" if value is None or value == [] else str(value)
        lines.extend((f"Current goal: {show(state['current_goal'])}", f"Current step: {state['current_step']}",
                      f"Work class: {show(state['work_class'])}", f"Current body organ: {show(state['current_organ'])}",
                      f"Selected colony: {show(state['selected_colony'])}",
                      f"Selected model: {show(state['selected_model'])}",
                      f"Routing reason: {show(state['routing_reason'])}",
                      f"Prediction: {show(state['prediction'])}", f"Verification: {show(state['verification'])}",
                      f"Last observation: {show(state['last_observation'])}", f"Pending approval: {show(state['pending_approval'])}",
                      f"Capability gaps: {show(state['capability_gaps'])}", f"A confidence: {state['a_confidence']}",
                      f"B confidence: {state['b_confidence']}", f"Sister exchange: {show(state['sister_exchange'])}",
                      f"Latest latency: {show(state['latest_latency'])}"))
        return "<br>".join(html.escape(line) for line in lines)

    def onboarding(self) -> str:
        if self.runtime.intelligence_connected:
            return ""
        return '''<section class="panel offline"><h2>INTELLIGENCE OFFLINE</h2><p>Recommended gateway: OpenRouter</p>
        <p><a href="https://openrouter.ai/keys" target="_blank" rel="noopener noreferrer">GET API KEY</a>
        · <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer">Gemini / Google AI Studio</a></p>
        <form method=post action=/openrouter><b>OPENROUTER</b> <input type=password name=key aria-label="OpenRouter secure key input" placeholder="paste key" autocomplete=off required><button>CONNECT</button></form>
        <form method=post action=/gemini><b>GEMINI</b> <input type=password name=key aria-label="Gemini secure key input" placeholder="paste key" autocomplete=off required><button>CONNECT</button></form></section>'''

    def observatory(self) -> dict[str, str]:
        state = self.runtime.operational_status()
        healthy = self.runtime.organism.root.verify_audit()
        manifests = self.runtime.body_bus.manifests
        available = {manifest.kind for manifest in manifests.values() if manifest.available and manifest.trusted}
        body_health = "READY" if {"filesystem", "web"} <= available else ("DEGRADED" if available else "NO_EXTERNAL_BODY")
        header = " · ".join((f"Root <b class=ok>{'SECURE' if healthy else 'FAULT'}</b>",
            "Saphira-A <b class=ok>ONLINE</b>", "Saphira-B <b class=ok>ONLINE</b>",
            f"Intelligence <b class={'ok' if self.runtime.intelligence_connected else 'off'}>{'ONLINE' if self.runtime.intelligence_connected else 'OFFLINE'}</b>",
            f"Body health <b class={'ok' if body_health == 'READY' else 'off'}>{body_health}</b>"))
        sister_cards = []
        for name, summary in state["sisters"].items():
            safe = " · ".join(f"{html.escape(str(k))}: {html.escape(str(v if v is not None else 'none'))}"
                              for k, v in summary.items())
            sister_cards.append(f'<div class=summary><b>{name}</b><br>{safe}</div>')
        events = "".join(f'<div class=event><b>{html.escape(event["kind"])}</b><br>{html.escape(event["summary"])}</div>'
                         for event in state["timeline"]) or "<p>No runtime events recorded.</p>"
        return {"header": header, "sisters": "".join(sister_cards), "timeline": events}

    def approval(self) -> str:
        request = self.runtime.operational_status()["pending_approval"]
        if not request: return ""
        details = html.escape(json.dumps({k:request[k] for k in ("reason","organ","operation","scope","risk","cost","reversible")}, sort_keys=True))
        identity = html.escape(request["id"])
        return f'<fieldset><legend>PENDING APPROVAL</legend><p>{details}</p><form method=post action=/approve><input type=hidden name=id value="{identity}"><button>APPROVE</button></form><form method=post action=/deny><input type=hidden name=id value="{identity}"><button>DENY</button></form></fieldset>'

    def chat(self, message: str) -> str:
        return self.runtime.chat(message)

    def set_policy(self, policy: str) -> str:
        self.runtime.set_routing_policy(policy); return self.runtime.routing_policy

    def decide_approval(self, request_id: str, approved: bool) -> None:
        self.runtime.decide_approval(request_id, approved)

    def close(self) -> None:
        self.runtime.close()


class RuntimeWorker:
    """Owns App, GodRuntime, and every writable SQLite connection on one thread."""
    def __init__(self, data: Path):
        self.data, self.jobs = data, queue.Queue()
        self.states: dict[str, dict[str, object]] = {}; self.lock = threading.Lock()
        self.ready = threading.Event(); self.app: App | None = None
        self.thread = threading.Thread(target=self._run, name="god-runtime-owner")
        self.thread.start(); self.ready.wait()

    def _run(self) -> None:
        self.app = App(self.data); self.ready.set()
        while True:
            job_id, operation, arguments, reply = self.jobs.get()
            if operation == "stop":
                self.app.close(); reply.put(None); return
            with self.lock: self.states[job_id]["state"] = "RUNNING"
            try:
                result = getattr(self.app, operation)(*arguments)
                if operation == "chat":
                    self.app.transcript.append(f"Pier: {arguments[0]}\nG.O.D.: {result}")
                runtime_state = self.app.runtime.operational_status()
                state = "WAITING_FOR_APPROVAL" if runtime_state["pending_approval"] else "COMPLETE"
                with self.lock: self.states[job_id].update(state=state, result=str(result))
                reply.put((True, result))
            except Exception as error:
                with self.lock: self.states[job_id].update(state="FAILED", error=type(error).__name__)
                reply.put((False, type(error).__name__))

    def submit(self, operation: str, *arguments: object, _exposed: bool = True) -> tuple[str, queue.Queue]:
        identity, reply = uuid4().hex, queue.Queue(maxsize=1)
        with self.lock: self.states[identity] = {"job_id": identity, "state": "QUEUED", "result": None,
                                                "exposed": _exposed}
        self.jobs.put((identity, operation, arguments, reply)); return identity, reply

    def snapshot_jobs(self) -> dict[str, dict[str, object]]:
        with self.lock: return {key: {k: v for k, v in value.items() if k != "exposed"}
                                for key, value in self.states.items() if value["exposed"]}

    def call(self, operation: str, *arguments: object) -> object:
        identity, reply = self.submit(operation, *arguments, _exposed=False); success, result = reply.get()
        with self.lock: self.states.pop(identity, None)
        if not success: raise RuntimeError(str(result))
        return result

    def close(self) -> None:
        reply = queue.Queue(maxsize=1); self.jobs.put(("shutdown", "stop", (), reply)); reply.get(); self.thread.join()


def read_safe_snapshot(data: Path, jobs: dict[str, dict[str, object]] | None = None,
                       job_id: str | None = None) -> dict[str, object]:
    """Read WAL snapshots without touching the runtime owner's connections."""
    database = data / "awakening.sqlite3"
    if not database.exists(): return {"timeline": [], "sisters": {}, "selection": None, "job": None}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        events = [dict(row) for row in connection.execute(
            "SELECT sequence,kind,summary,created FROM runtime_events ORDER BY sequence DESC LIMIT 50")]
        sisters = {}
        for name in ("Saphira-A", "Saphira-B"):
            row = connection.execute("SELECT status,summary,confidence,created FROM sister_states WHERE colony=? "
                                     "ORDER BY sequence DESC LIMIT 1", (name,)).fetchone()
            sisters[name] = dict(row) if row else None
        selected = connection.execute("SELECT goal_id,episode_id,task_class,colony,provider,model_id,routing_policy,"
                                      "routing_reason,started_at,finished_at,latency_ms,success FROM model_selections "
                                      "ORDER BY started_at DESC LIMIT 1").fetchone()
        goal_row = connection.execute("SELECT state FROM goals ORDER BY rowid DESC LIMIT 1").fetchone()
        goal = json.loads(goal_row[0]) if goal_row else None
        conversation = [dict(row) for row in connection.execute("SELECT role,content,created FROM chat ORDER BY id")]
        verification = None
        pending = gap = None
        body = data / "embodiment.sqlite3"
        if body.exists():
            body_db = sqlite3.connect(f"file:{body}?mode=ro", uri=True); body_db.row_factory = sqlite3.Row
            try:
                approval = body_db.execute("SELECT state FROM body WHERE kind='approval' ORDER BY rowid DESC LIMIT 1").fetchone()
                gap_row = body_db.execute("SELECT state FROM body WHERE kind='gap' ORDER BY rowid DESC LIMIT 1").fetchone()
                observation = body_db.execute("SELECT state FROM body WHERE kind='observation' ORDER BY rowid DESC LIMIT 1").fetchone()
                pending = json.loads(approval[0]) if approval and json.loads(approval[0]).get("status") == "pending" else None
                gap = json.loads(gap_row[0]) if gap_row else None
                verification = json.loads(observation[0]).get("verification_state") if observation else None
            finally: body_db.close()
        job_values = jobs or {}; selected_job = job_values.get(job_id) if job_id else (list(job_values.values())[-1] if job_values else None)
        return {"timeline": events, "sisters": sisters, "selection": dict(selected) if selected else None,
                "goal": goal, "verification": verification, "pending_approval": pending,
                "capability_gap": gap, "conversation": conversation, "job": selected_job}
    finally: connection.close()


def serve(data: Path, port: int, *, open_browser: bool = True) -> None:
    worker = RuntimeWorker(data)
    class Handler(BaseHTTPRequestHandler):
        def page(self) -> None:
            app = worker.app; assert app is not None
            view = worker.call("observatory")
            body = (PAGE.replace("{header}", view["header"]).replace("{onboarding}", worker.call("onboarding"))
                    .replace("{status}", worker.call("status")).replace("{approval}", worker.call("approval"))
                    .replace("{sisters}", view["sisters"]).replace("{timeline}", view["timeline"])
                    .replace("{chat}", html.escape("\n".join(app.transcript)))).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self) -> None:
            target = urlsplit(self.path)
            if target.path == "/api/status":
                job_id = parse_qs(target.query).get("job_id", [None])[0]
                body = json.dumps(read_safe_snapshot(data, worker.snapshot_jobs(), job_id)).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            self.page()
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            fields = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
            try:
                app = worker.app; assert app is not None
                if self.path == "/chat":
                    job_id, _ = worker.submit("chat", fields.get("message", ""))
                    body = json.dumps({"job_id": job_id, "status": "QUEUED"}).encode()
                    self.send_response(202); self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
                if self.path == "/connect": response = worker.call("connect", fields)
                elif self.path == "/import":
                    count = worker.call("import_secrets", fields.get("path", ""), fields.get("delete") == "yes")
                    response = f"Secrets securely imported. Discovered {count} models."
                elif self.path == "/openrouter":
                    count = worker.call("connect_openrouter", fields.get("key", ""))
                    response = f"OpenRouter connected. Discovered {count} models."
                elif self.path == "/gemini":
                    count = worker.call("connect_gemini", fields.get("key", ""))
                    response = f"Gemini connected. Discovered {count} models."
                elif self.path == "/local":
                    count = worker.call("detect_local_models")
                    response = f"Discovered {count} local models."
                elif self.path == "/policy":
                    worker.call("set_policy", fields.get("policy", "AUTO"))
                    response = f"Routing policy: {app.runtime.routing_policy}."
                elif self.path in {"/approve", "/deny"}:
                    worker.call("decide_approval", fields["id"], self.path == "/approve")
                    response = "Approval recorded by Pier." if self.path == "/approve" else "Request denied by Pier."
                else:
                    message = fields.get("message", ""); response = worker.call("chat", message)
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
    finally: server.server_close(); worker.close()


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--data", type=Path, default=Path.home() / ".god")
    parser.add_argument("--port", type=int, default=8765); parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(); serve(args.data, args.port, open_browser=not args.no_browser)


if __name__ == "__main__": main()
