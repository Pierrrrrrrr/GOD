from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .awakening import GodRuntime


PAGE = """<!doctype html><meta charset=utf-8><title>G.O.D.</title>
<style>body{font:16px system-ui;max-width:850px;margin:40px auto;background:#10131a;color:#edf1ff}
button,input,select{padding:10px;margin:5px}pre{white-space:pre-wrap;background:#1b2130;padding:16px}
.online{color:#7dffa1}</style><h1>G.O.D.</h1><div id=status></div>
<section id=connect><h2>Connect Intelligence</h2><select id=provider><option value=openrouter>OpenRouter</option>
<option value=gemini>Gemini</option><option value=openai-compatible>Generic OpenAI-compatible</option></select>
<input id=model placeholder="Model ID"><input id=base placeholder="Base URL (generic only)">
<input id=key type=password placeholder="API credential"><button onclick=connect()>CONNECT INTELLIGENCE</button></section>
<h2>Persistent chat</h2><input id=message style="width:70%" placeholder="Talk to G.O.D. or give a goal">
<button onclick=chat()>Chat</button><button onclick=goal()>Submit goal</button><pre id=transcript></pre><details><summary>Organism detail</summary><pre id=detail></pre></details>
<script>
async function api(path,data){let r=await fetch(path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json'},body:data?JSON.stringify(data):null});let j=await r.json();if(!r.ok)throw Error(j.error);return j}
async function refresh(){let s=await api('/api/status');status.innerHTML=['Saphira-A','Saphira-B','Root','Memory','Intelligence'].map(k=>`${k.padEnd(15)} <b class=online>${s[k]}</b>`).join('<br>')+`<br>Session/day cost: $${s.session_cost.toFixed(4)}`;detail.textContent=JSON.stringify(s,null,2);connect.style.display=s.Intelligence==='CONNECTED'?'none':'block';if(!transcript.textContent)transcript.textContent=s.messages.map(m=>`${m.role==='user'?'Pier':'G.O.D.'}: ${m.content}`).join('\n\n')}
async function connect(){try{await api('/api/connect',{provider:provider.value,model:model.value,base_url:base.value,credential:key.value});key.value='';refresh()}catch(e){alert(e)}}
async function chat(){try{let text=message.value;message.value='';let r=await api('/api/chat',{text});transcript.textContent+=`Pier: ${text}\nG.O.D.: ${r.answer}\n\n`;detail.textContent=JSON.stringify(r.detail,null,2);refresh()}catch(e){alert(e)}}refresh();
async function goal(){try{let text=message.value;message.value='';let r=await api('/api/goals',{text});transcript.textContent+=`Pier goal: ${text}\nG.O.D. next step: ${r.next_action}\n\n`;detail.textContent=JSON.stringify(r,null,2);refresh()}catch(e){alert(e)}}
</script>"""


def handler(runtime: GodRuntime) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, value: Any, content_type: str = "application/json") -> None:
            body = value.encode() if isinstance(value, str) else json.dumps(value).encode()
            self.send_response(status); self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/": self._send(200, PAGE, "text/html; charset=utf-8")
            elif self.path == "/api/status": self._send(200, runtime.status())
            else: self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/connect":
                    runtime.connect(data["provider"], data["model"], data["credential"], data.get("base_url", "")); result = {"ok": True}
                elif self.path == "/api/chat": result = runtime.chat(data["text"])
                elif self.path == "/api/goals": result = runtime.submit_goal(data["text"])
                else: return self._send(404, {"error": "not found"})
                self._send(200, result)
            except Exception as error:
                self._send(400, {"error": str(error)})

        def log_message(self, format: str, *args: Any) -> None:
            pass
    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local G.O.D. interface")
    parser.add_argument("--state", type=Path, default=Path.home() / ".god")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(GodRuntime(args.state)))
    if not args.no_browser:
        threading.Timer(.5, webbrowser.open, args=(f"http://127.0.0.1:{args.port}",)).start()
    print(f"G.O.D. is online at http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
