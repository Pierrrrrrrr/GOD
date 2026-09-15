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
import secrets
import socket
from collections import deque
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .awakening import GodRuntime
from .connectors import (GeminiConnector, OllamaConnector, OpenAICompatibleConnector,
                         OpenRouterConnector, ProviderConnector)
from .models import HTTPModelProvider, ModelRecord, ModelRouter, ResponseMode
from .vault import CredentialHandle, CredentialVault

PROVIDER_STATES = {"CONNECTED", "INVALID_CREDENTIAL", "UNAVAILABLE", "RECONNECT_REQUIRED", "NOT_CONFIGURED"}


PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><meta name=csrf-token content="{csrf}"><title>G.O.D.</title>
<style>:root{color-scheme:dark;--bg:#071019;--card:#101c28;--line:#26394b;--text:#eaf2fa;--muted:#9eb0c2;--blue:#6eb6ff;--green:#6ce2ad;--amber:#ffc46b}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -20%,#17324a,var(--bg) 45%);color:var(--text);font:15px system-ui,sans-serif}button,input,select{font:inherit}button,input,select{border:1px solid var(--line);border-radius:10px;background:#132536;color:var(--text);padding:.75rem}button{cursor:pointer}button:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid var(--blue);outline-offset:2px}button:disabled{opacity:.55;cursor:wait}.top{position:sticky;top:0;z-index:2;display:flex;gap:1rem;align-items:center;justify-content:space-between;padding:.75rem 1.25rem;background:#08131ded;border-bottom:1px solid var(--line);backdrop-filter:blur(12px)}.brand{font-weight:800;letter-spacing:.12em}.safe{color:var(--green);font-size:.8rem}.shell{max-width:1400px;margin:auto;display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:1rem;padding:1rem}.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:1rem;box-shadow:0 12px 40px #0004}.conversation{min-height:72vh;display:flex;flex-direction:column}.messages{flex:1;overflow:auto;min-height:420px;padding:.5rem}.empty{color:var(--muted);text-align:center;margin:auto}.bubble{max-width:78%;padding:.8rem 1rem;border-radius:14px;margin:.65rem 0;white-space:pre-wrap}.user{margin-left:auto;background:#1d5682}.assistant{background:#182b3b}.composer{display:flex;gap:.6rem;border-top:1px solid var(--line);padding-top:1rem}.composer input{flex:1}.job{min-height:1.5rem;color:var(--amber);font-size:.9rem}.side{display:flex;flex-direction:column;gap:1rem}h2,h3{margin:.2rem 0 .8rem}dl{display:grid;grid-template-columns:auto 1fr;gap:.35rem .8rem;margin:0}dt{color:var(--muted)}details summary{cursor:pointer;font-weight:700}.sister{padding:.7rem;border-left:3px solid var(--blue);margin:.6rem 0}.timeline{max-height:280px;overflow:auto}.event{padding:.55rem 0;border-bottom:1px solid var(--line)}.doctor-row{padding:.6rem 0;border-bottom:1px solid var(--line)}.controls form{display:flex;flex-wrap:wrap;gap:.4rem;margin:.5rem 0}.controls input{min-width:0;flex:1}.sr{position:absolute;left:-9999px}@media(max-width:900px){.shell{grid-template-columns:1fr}.conversation{min-height:62vh}.top{align-items:flex-start;flex-direction:column}.bubble{max-width:92%}}</style></head>
<body><header class=top><div><span class=brand>G.O.D.</span> <span class=safe>CORPORATE_SAFE · ZERO COST</span></div><div aria-label="Runtime health">{header}</div></header>
<main class=shell><section class="card conversation" aria-labelledby=conversation-title><h2 id=conversation-title>Conversation</h2><div id=job class=job role=status aria-live=polite>Ready</div><div id=chat class=messages>{chat}</div><form id=chat-form class=composer method=post action=/chat><label class=sr for=message>Message</label><input id=message name=message maxlength=8000 autocomplete=off placeholder="Message G.O.D." required><button id=send type=submit>Send</button></form></section>
<aside class=side><section class=card><h3>Autonomous goal</h3><div id=task>{status}</div><form method=post action=/advance><input type=hidden name=steps value=1><button>Advance one safe step</button></form><div id=approval-live>{approval}</div></section><section class=card><h3>Intelligence & privacy</h3><div id=resource>No free intelligence selected.</div><details><summary>Intelligence Doctor & settings</summary><div id=doctor>Run a synthetic, non-sensitive probe to inspect intelligence.</div><button id=doctor-run type=button>Find working free intelligence</button><div class=controls>{onboarding}<form method=post action=/local><button>Detect local models</button></form><form method=post action=/policy><select name=policy aria-label="Zero-cost routing"><option>ZERO_COST</option><option value=LOCAL_FIRST>LOCAL FREE FIRST</option><option value=FREE_FIRST>ANY VERIFIED FREE</option></select><button>Apply</button></form></div></details></section>
<section class=card><details><summary>Saphira observatory</summary><div id=sisters>{sisters}</div></details></section><section class=card><details open><summary>Development & capabilities</summary><div id=development>No persisted development activity.</div><div id=events class=timeline>{timeline}</div></details></section></aside></main>
<script nonce="{nonce}">const esc=x=>String(x??'none').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const csrf=document.querySelector('meta[name=csrf-token]').content;let activeJob=null;let pendingText=null;const chat=document.querySelector('#chat'),send=document.querySelector('#send'),input=document.querySelector('#message'),job=document.querySelector('#job');
function renderConversation(items){chat.innerHTML=items.length?items.map(x=>`<div class="bubble ${x.role==='user'?'user':'assistant'}">${esc(x.content)}</div>`).join(''):'<div class=empty>No messages yet. Start a conversation or launch a goal.</div>';if(pendingText&&!items.some(x=>x.role==='user'&&x.content===pendingText))chat.innerHTML+=`<div class="bubble user">${esc(pendingText)}</div>`;chat.scrollTop=chat.scrollHeight}
async function poll(){const q=activeJob?'?job_id='+encodeURIComponent(activeJob):'';const r=await fetch('/api/status'+q,{cache:'no-store'});if(!r.ok)return;const s=await r.json();renderConversation(s.conversation||[]);document.querySelector('#events').innerHTML=(s.timeline||[]).slice().reverse().map(e=>`<div class=event><b>${esc(e.kind)}</b><br>${esc(e.summary)}</div>`).join('')||'<div class=empty>No persisted activity.</div>';document.querySelector('#sisters').innerHTML=Object.entries(s.sisters||{}).map(([n,v])=>`<div class=sister><b>${esc(n)}</b><br>${esc(v?.status)} · ${esc(v?.summary)} · confidence ${esc(v?.confidence)}</div>`).join('');const cls=s.selection?.cost_classification||'NO FREE SAFE INTELLIGENCE AVAILABLE';document.querySelector('#resource').innerHTML=`<b>${esc(cls)}</b><br>${esc(s.selection?s.selection.provider+':'+s.selection.model_id:'No model selected')}<br>Privacy: ${esc(s.selection?.provider==='ollama'?'local':'corporate-safe remote only')}`;document.querySelector('#development').textContent=s.capability_gap?'Capability gap: '+(s.capability_gap.reason||'persisted gap'):(s.goal?.current_organ?'Current organ: '+s.goal.current_organ:'No active capability development.');if(s.job){job.textContent=s.job.state+(s.job.error?' — '+s.job.error:'');if(['COMPLETE','FAILED','WAITING_FOR_APPROVAL'].includes(s.job.state)){activeJob=null;pendingText=null;send.disabled=false;input.disabled=false;input.focus()}}}
async function mutate(url,data){return fetch(url,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','X-GOD-CSRF':csrf},body:new URLSearchParams(data)})}document.querySelector('#chat-form').addEventListener('submit',async e=>{e.preventDefault();if(activeJob)return;pendingText=input.value;chat.querySelector('.empty')?.remove();chat.insertAdjacentHTML('beforeend',`<div class="bubble user">${esc(pendingText)}</div>`);chat.scrollTop=chat.scrollHeight;send.disabled=true;input.disabled=true;job.textContent='QUEUED';const r=await mutate('/chat',{message:pendingText});if(r.ok){const data=await r.json();activeJob=data.job_id;input.value='';job.textContent='QUEUED';poll()}else{job.textContent='Request rejected safely';activeJob=null;send.disabled=false;input.disabled=false}});document.querySelector('#doctor-run').addEventListener('click',async()=>{const b=document.querySelector('#doctor-run');b.disabled=true;const r=await mutate('/doctor',{synthetic:'true'});const data=await r.json();document.querySelector('#doctor').innerHTML=data.models.map(m=>`<div class=doctor-row><b>${esc(m.provider+':'+m.model)}</b><br>${esc(m.cost_classification)} · ${esc(m.health)} · ${esc(m.location)}<br>TEXT ${esc(m.text)} · STRUCTURED ${esc(m.structured)} · ${esc(m.failure_class||'no failure')}</div>`).join('')||'<div class=empty>NO FREE SAFE INTELLIGENCE AVAILABLE</div>';b.disabled=false;poll()});document.querySelectorAll('form:not(#chat-form)').forEach(f=>f.addEventListener('submit',async e=>{e.preventDefault();const r=await mutate(f.action,new FormData(f));if(r.ok)location.reload()}));setInterval(poll,600);poll();</script></body></html>"""


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
        eligible = [record for record in records if record.zero_cost_eligible and (record.privacy == "local" or record.corporate_safe)]
        self.discovered.update((record.key, record) for record in records)
        if not eligible:
            return 0
        preferred = next((r for r in eligible if r.privacy == "local"), eligible[0])
        connector.probe(preferred.model_id)
        self.connectors[connector.name] = connector
        self.provider_states[connector.name] = "CONNECTED"
        return len(records)

    def _apply_connectors(self, *, configuration_changed: bool = False) -> None:
        if self.connectors and self.discovered:
            self.runtime.attach_intelligence(self.connectors, list(self.discovered.values()),
                                             configuration_changed=configuration_changed)

    def import_secrets(self, path: str, delete_source: bool = False) -> int:
        handles = self.vault.import_file(Path(path), delete_source=delete_source)
        count = 0
        for handle in handles:
            connector = self._connector(handle)
            if connector is not None:
                try: count += self._add_connector(connector)
                except Exception: continue
        self._apply_connectors(configuration_changed=True)
        return count

    def connect_openrouter(self, api_key: str) -> int:
        connector = OpenRouterConnector(api_key)
        records = connector.discover()
        if not records:
            raise RuntimeError("provider catalog is unavailable")
        self.discovered.update((record.key, record) for record in records)
        eligible = [record for record in records if record.zero_cost_eligible and (record.privacy == "local" or record.corporate_safe)]
        if not eligible:
            raise RuntimeError("NO_FREE_SAFE_INTELLIGENCE_AVAILABLE")
        preferred = eligible[0]
        connector.probe(preferred.model_id)
        self.vault.set_provider("openrouter", api_key)
        self.connectors[connector.name] = connector
        self.discovered.update((record.key, record) for record in records)
        self._apply_connectors(configuration_changed=True)
        return len(records)

    def connect_gemini(self, api_key: str) -> int:
        connector = GeminiConnector(api_key)
        records = connector.discover()
        if not records: raise RuntimeError("provider catalog is unavailable")
        self.discovered.update((record.key, record) for record in records)
        eligible = [record for record in records if record.zero_cost_eligible and (record.privacy == "local" or record.corporate_safe)]
        if not eligible: raise RuntimeError("NO_FREE_SAFE_INTELLIGENCE_AVAILABLE")
        connector.probe(eligible[0].model_id)
        self.vault.set_provider("gemini", api_key)
        self.connectors[connector.name] = connector
        self.provider_states["gemini"] = "CONNECTED"
        self.discovered.update((record.key, record) for record in records)
        self._apply_connectors(configuration_changed=True)
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

    def intelligence_doctor(self, probe: bool = False) -> list[dict[str, object]]:
        """Return compact health facts; optional probes contain synthetic text only."""
        if probe:
            try: self.detect_local_models()
            except Exception: pass
            for record in list(self.runtime.records.values()):
                if not record.zero_cost_eligible or record.blocked or not record.retry_eligible():
                    continue
                connector = self.connectors.get(record.provider)
                if connector is None: continue
                started = time.monotonic()
                record.last_synthetic_probe = time.time()
                try:
                    connector.probe(record.model_id)
                    ModelRouter.observe_call(record, True, (time.monotonic() - started) * 1000)
                except Exception as error:
                    ModelRouter.observe_call(record, False, (time.monotonic() - started) * 1000,
                                             getattr(error, "failure_class", None))
            self.runtime._save_models()
        records = {**self.discovered, **self.runtime.records}
        try:
            selected = self.runtime.router.choose(list(records.values()), "conversation",
                                                  policy=self.runtime.routing_policy).key
        except RuntimeError:
            selected = None
        return [{"provider": record.provider, "model": record.model_id,
                 "location": "local" if record.privacy == "local" else "remote",
                 "zero_cost": record.zero_cost_eligible,
                 "cost_classification": record.cost_classification,
                 "text": record.text_capability, "structured": record.structured_capability,
                 "privacy": record.privacy, "health": record.health_state,
                 "last_synthetic_probe": record.last_synthetic_probe,
                 "latency_ms": round(record.latency_ms, 1),
                 "failure_class": record.last_failure_class, "selected": record.key == selected}
                for record in sorted(records.values(), key=lambda item: item.key)]

    def find_working_free_intelligence(self) -> list[dict[str, object]]:
        return self.intelligence_doctor(probe=True)

    def _connect(self, values: dict[str, str]) -> None:
        provider, model, key = values["provider"], values["model"], values["key"]
        if provider == "Gemini":
            endpoint = "https://generativelanguage.googleapis.com/v1beta"
            organ = HTTPModelProvider(endpoint, key, gemini=True)
            name = "gemini"
        elif provider == "OpenRouter":
            endpoint = "https://openrouter.ai/api/v1/chat/completions"
            organ = HTTPModelProvider(endpoint, key, openrouter=True)
            name = "openrouter"
        else:
            raise ValueError("unsupported provider in CORPORATE_SAFE mode")
        record = ModelRecord(name, model)
        record.corporate_safe = name == "openrouter"
        catalog = organ.catalog()
        metadata = next((item for item in catalog if item.get("id", item.get("name", "")).endswith(model)), None)
        if metadata:
            record.context_capability = metadata.get("context_length") or metadata.get("inputTokenLimit")
            record.modalities = metadata.get("architecture", {}).get("input_modalities", ["text"])
            record.tool_capability = "generateContent" in metadata.get("supportedGenerationMethods", [])
            if name == "openrouter":
                record.structured_capability = "response_format" in metadata.get("supported_parameters", [])
            pricing = metadata.get("pricing", {})
            record.input_cost = self._price(pricing.get("prompt"))
            record.output_cost = self._price(pricing.get("completion"))
        self.discovered[record.key] = record
        if not record.zero_cost_eligible:
            raise RuntimeError(record.cost_classification)
        started = time.monotonic()
        probe = organ.infer({"model_id": model, "response_mode": ResponseMode.TEXT.value,
                             "prompt": "Synthetic capability probe. Reply with OK."})
        probe_latency = (time.monotonic() - started) * 1000
        if not isinstance(probe, str) or not probe.strip():
            raise RuntimeError("provider capability probe failed")
        self.runtime.attach_intelligence({name: organ}, [record], configuration_changed=True)
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
        lines = ["Saphira-A INITIALIZED", "Saphira-B INITIALIZED", "Root AUDIT VERIFIED",
                 f"Intelligence {intelligence}"] if healthy else [
                     "Saphira-A OFFLINE", "Saphira-B OFFLINE", "Root NOT INITIALIZED",
                     f"Intelligence {intelligence}"]
        lines.append(f"Discovered providers: {len(self.runtime.bus.providers)}; models: {len(self.runtime.records)}")
        lines.append(f"Routing: {self.runtime.routing_policy}")
        lines.append("Monetary budget: 0")
        lines.extend(f"{name.title()} — {status}" for name, status in self.provider_states.items())
        lines.extend(f"Resource {record.key} — {record.cost_classification}"
                     for record in sorted(self.discovered.values(), key=lambda item: item.key))
        state = self.runtime.operational_status(); show = lambda value: "none" if value is None or value == [] else str(value)
        lines.extend((f"Current goal: {show(state['current_goal'])}", f"Current step: {state['current_step']}",
                      f"Work class: {show(state['work_class'])}", f"Current body organ: {show(state['current_organ'])}",
                      f"Selected colony: {show(state['selected_colony'])}",
                      f"Selected model: {show(state['selected_model'])}",
                      f"Intelligence resource: {state['intelligence_resource']}",
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
        header = " · ".join((f"Root audit <b class=ok>{'VERIFIED' if healthy else 'FAULT'}</b>",
            "Saphira-A <b class=ok>INITIALIZED</b>", "Saphira-B <b class=ok>INITIALIZED</b>",
            f"Intelligence <b class={'ok' if self.runtime.intelligence_connected else 'off'}>{'ATTACHED' if self.runtime.intelligence_connected else 'NOT ATTACHED'}</b>",
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

    def advance_current_goal(self, max_steps: int = 1) -> dict[str, object]:
        rows = self.runtime.store.rows("SELECT id FROM goals ORDER BY rowid DESC LIMIT 1")
        if not rows: raise ValueError("No goal has been launched.")
        goal_id = str(rows[0]["id"])
        return (self.runtime.advance_goal(goal_id) if max_steps == 1
                else self.runtime.run_goal(goal_id, max_steps=max_steps))

    def close(self) -> None:
        self.runtime.close()


class RuntimeWorker:
    """Owns App, GodRuntime, and every writable SQLite connection on one thread."""
    def __init__(self, data: Path):
        self.data, self.jobs = data, queue.Queue(maxsize=16)
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
            with self.lock: self.states[job_id]["state"] = "THINKING" if operation == "chat" else "RUNNING"
            try:
                result = getattr(self.app, operation)(*arguments)
                if operation == "chat":
                    self.app.transcript.append(f"Pier: {arguments[0]}\nG.O.D.: {result}")
                runtime_state = self.app.runtime.operational_status()
                state = "WAITING_FOR_APPROVAL" if runtime_state["pending_approval"] else "COMPLETE"
                with self.lock:
                    self.states[job_id].update(state=state, result=str(result),
                        approval_request_id=(runtime_state["pending_approval"] or {}).get("id"))
                    if operation == "decide_approval":
                        request_id, approved = arguments
                        for identity, job in self.states.items():
                            if identity != job_id and job.get("approval_request_id") == request_id:
                                job.update(state="COMPLETE", result=("Approval resumed; goal awaits outcome."
                                           if approved else "Approval denied; goal blocked."), approval_request_id=None)
                reply.put((True, result))
            except Exception as error:
                safe_error = ("NO_FREE_SAFE_INTELLIGENCE_AVAILABLE"
                              if "NO_FREE_SAFE_INTELLIGENCE_AVAILABLE" in str(error)
                              else "Request failed safely; review Intelligence Doctor.")
                with self.lock: self.states[job_id].update(state="FAILED", error=safe_error)
                reply.put((False, safe_error))

    def submit(self, operation: str, *arguments: object, _exposed: bool = True) -> tuple[str, queue.Queue]:
        identity, reply = uuid4().hex, queue.Queue(maxsize=1)
        with self.lock: self.states[identity] = {"job_id": identity, "state": "QUEUED", "result": None,
                                                "exposed": _exposed}
        try:
            self.jobs.put_nowait((identity, operation, arguments, reply))
        except queue.Full:
            with self.lock: self.states.pop(identity, None)
            raise ProviderUnavailable("the local work queue is full") from None
        return identity, reply

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
        # Read the newest transition marker first. If it is visible, all events
        # committed before it must also be visible to the subsequent queries.
        selected = connection.execute("SELECT goal_id,episode_id,task_class,colony,provider,model_id,routing_policy,"
                                      "routing_reason,started_at,finished_at,latency_ms,success FROM model_selections "
                                      "ORDER BY started_at DESC LIMIT 1").fetchone()
        selected_view = dict(selected) if selected else None
        if selected_view:
            key = f'{selected_view["provider"]}:{selected_view["model_id"]}'
            model = connection.execute("SELECT state FROM models WHERE key=?", (key,)).fetchone()
            if model:
                record = ModelRecord(**json.loads(model[0]))
                selected_view["cost_classification"] = record.cost_classification
        events = [dict(row) for row in connection.execute(
            "SELECT sequence,kind,summary,created FROM runtime_events ORDER BY sequence DESC LIMIT 50")]
        sisters = {}
        for name in ("Saphira-A", "Saphira-B"):
            row = connection.execute("SELECT status,summary,confidence,created FROM sister_states WHERE colony=? "
                                     "ORDER BY sequence DESC LIMIT 1", (name,)).fetchone()
            sisters[name] = dict(row) if row else None
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
                approval_data = json.loads(approval[0]) if approval else None
                pending = ({key: approval_data.get(key) for key in
                            ("id", "goal_id", "organ", "operation", "reason", "scope", "risk", "cost",
                             "side_effect_class", "reversible", "status", "requested_at")}
                           if approval_data and approval_data.get("status") == "pending" else None)
                gap = json.loads(gap_row[0]) if gap_row else None
                verification = json.loads(observation[0]).get("verification_state") if observation else None
            finally: body_db.close()
        job_values = jobs or {}; selected_job = job_values.get(job_id) if job_id else (list(job_values.values())[-1] if job_values else None)
        return {"timeline": events, "sisters": sisters, "selection": selected_view,
                "goal": goal, "verification": verification, "pending_approval": pending,
                "capability_gap": gap, "conversation": conversation, "job": selected_job}
    finally: connection.close()


def serve(data: Path, port: int, *, open_browser: bool = True) -> None:
    worker = RuntimeWorker(data)
    csrf_token = secrets.token_urlsafe(32)
    csp_nonce = secrets.token_urlsafe(24)
    failed_requests: deque[float] = deque()
    class Handler(BaseHTTPRequestHandler):
        server_version = "GODLoopback"
        sys_version = ""

        def _allowed_host(self) -> bool:
            host = self.headers.get("Host", "")
            return host in {f"127.0.0.1:{self.server.server_address[1]}",
                            f"localhost:{self.server.server_address[1]}"}

        def _security_headers(self) -> None:
            self.send_header("Content-Security-Policy", f"default-src 'none'; script-src 'nonce-{csp_nonce}'; "
                             "style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cache-Control", "no-store, max-age=0")

        def _reject(self, status: int, message: str) -> None:
            now = time.monotonic()
            while failed_requests and failed_requests[0] < now - 60: failed_requests.popleft()
            failed_requests.append(now)
            body = message.encode("ascii")
            self.send_response(status); self._security_headers()
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)

        def page(self) -> None:
            app = worker.app; assert app is not None
            view = worker.call("observatory")
            body = (PAGE.replace("{csrf}", csrf_token).replace("{nonce}", csp_nonce)
                    .replace("{header}", view["header"]).replace("{onboarding}", worker.call("onboarding"))
                    .replace("{status}", worker.call("status")).replace("{approval}", worker.call("approval"))
                    .replace("{sisters}", view["sisters"]).replace("{timeline}", view["timeline"])
                    .replace("{chat}", html.escape("\n".join(app.transcript)))).encode()
            self.send_response(200); self._security_headers(); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self) -> None:
            if len(failed_requests) >= 12:
                self._reject(429, "Too many rejected requests."); return
            if not self._allowed_host():
                self._reject(400, "Invalid local host context."); return
            target = urlsplit(self.path)
            if target.path == "/api/status":
                job_id = parse_qs(target.query).get("job_id", [None])[0]
                body = json.dumps(read_safe_snapshot(data, worker.snapshot_jobs(), job_id)).encode()
                self.send_response(200); self._security_headers(); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if target.path == "/": self.page()
            else: self._reject(404, "Not found.")
        def do_POST(self) -> None:
            if len(failed_requests) >= 12:
                self._reject(429, "Too many rejected requests."); return
            if not self._allowed_host():
                self._reject(400, "Invalid local host context."); return
            origin, referer = self.headers.get("Origin"), self.headers.get("Referer")
            allowed = {f"http://127.0.0.1:{self.server.server_address[1]}",
                       f"http://localhost:{self.server.server_address[1]}"}
            if origin and origin not in allowed or referer and not any(referer.startswith(x + "/") for x in allowed):
                self._reject(403, "Cross-origin mutation rejected."); return
            if not secrets.compare_digest(self.headers.get("X-GOD-CSRF", ""), csrf_token):
                self._reject(403, "Mutation capability required."); return
            try: length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._reject(400, "Malformed request."); return
            if length < 1 or length > 65_536:
                self._reject(413, "Request body is outside the safe limit."); return
            try:
                fields = {k: v[0] for k, v in parse_qs(
                    self.rfile.read(length).decode("utf-8"), max_num_fields=32).items()}
            except (UnicodeDecodeError, ValueError):
                self._reject(400, "Malformed request."); return
            if self.path == "/chat" and not 1 <= len(fields.get("message", "")) <= 8_000:
                self._reject(400, "Chat message must contain 1 to 8000 characters."); return
            try:
                app = worker.app; assert app is not None
                if self.path == "/chat":
                    job_id, _ = worker.submit("chat", fields.get("message", ""))
                    body = json.dumps({"job_id": job_id, "status": "QUEUED"}).encode()
                    self.send_response(202); self._security_headers(); self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
                if self.path == "/doctor":
                    models = worker.call("find_working_free_intelligence")
                    body = json.dumps({"models": models}).encode()
                    self.send_response(200); self._security_headers(); self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
                if self.path == "/advance":
                    result = worker.call("advance_current_goal", max(1, min(int(fields.get("steps", "1")), 10)))
                    body = json.dumps({"status": result.get("status"), "step": result.get("step_count")}).encode()
                    self.send_response(200); self._security_headers(); self.send_header("Content-Type", "application/json")
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
                    worker.call("set_policy", fields.get("policy", "ZERO_COST"))
                    response = f"Routing policy: {app.runtime.routing_policy}."
                elif self.path in {"/approve", "/deny"}:
                    worker.call("decide_approval", fields["id"], self.path == "/approve")
                    response = "Approval recorded by Pier." if self.path == "/approve" else "Request denied by Pier."
                    body = json.dumps({"request_id": fields["id"], "status": "COMPLETE",
                                       "decision": "APPROVED" if self.path == "/approve" else "DENIED"}).encode()
                    self.send_response(200); self._security_headers(); self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
                else:
                    message = fields.get("message", ""); response = worker.call("chat", message)
                    app.transcript.append(f"Pier: {message}\nG.O.D.: {response}")
            except Exception:
                response = "The request failed. Check provider configuration; no credential details were logged."
            if self.path != "/chat": app.transcript.append(response)
            self.send_response(303); self._security_headers(); self.send_header("Location", "/"); self.end_headers()
        def log_message(self, format: str, *args: object) -> None: pass
    # The runtime and its SQLite connection are intentionally confined to this
    # single-user server thread. Browser launching is the only background work.
    server = HTTPServer(("127.0.0.1", port), Handler)
    if open_browser: threading.Timer(.5, webbrowser.open, (f"http://127.0.0.1:{port}",)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); worker.close()


def startup_doctor(data: Path) -> dict[str, object]:
    """Headless, redacted startup diagnostic; performs no installation or mutation outside data."""
    checks: dict[str, object] = {}
    data.mkdir(parents=True, exist_ok=True)
    checks["data_directory"] = "writable" if data.is_dir() else "unavailable"
    app: App | None = None
    try:
        app = App(data)
        checks["root_audit"] = "verified" if app.runtime.organism.root.verify_audit() else "fault"
        checks["vault"] = "available"
        checks["workspace_confinement"] = str((data / "workspace").resolve()).startswith(str(data.resolve()))
        with sqlite3.connect(data / "awakening.sqlite3") as database:
            checks["database_recovery"] = database.execute("PRAGMA quick_check").fetchone()[0]
        checks["models"] = app.find_working_free_intelligence()
    except Exception as error:
        checks["startup"] = "failed"
        checks["safe_failure_class"] = type(error).__name__
    finally:
        if app is not None: app.close()
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0)); checks["loopback"] = "available"
    except OSError:
        checks["loopback"] = "unavailable"
    finally: probe.close()
    checks["ok"] = not any(isinstance(value, str) and value in {"fault", "failed", "unavailable"}
                           for value in checks.values())
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--data", type=Path, default=Path.home() / ".god")
    parser.add_argument("--port", type=int, default=8765); parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    args = parser.parse_args()
    if args.doctor:
        report = startup_doctor(args.data)
        print(json.dumps(report, indent=2, sort_keys=True))
        raise SystemExit(0 if report.get("ok") else 1)
    serve(args.data, args.port, open_browser=not args.no_browser)


if __name__ == "__main__": main()
