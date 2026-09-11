import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from tmco.awakening import GodRuntime
from tmco.models import ModelRecord


class BodyPlanningProvider:
    def __init__(self, url: str): self.url, self.calls = url, []
    def infer(self, request):
        self.calls.append(request); prompt = request["prompt"]
        if "Assess only whether" in prompt: return {"material_disagreement": True, "reasons": ["method"]}
        if "separate sister-audit" in prompt: return {"disagreements":["method"],"synthesis":"use observed evidence","selected_next_action":"research","rationale":"bounded evidence"}
        context = json.loads(prompt.split("JSON context:\n",1)[1]); goal = context.get("goal", "")
        perspective = request["model_id"]
        if "summarize" in goal.lower():
            demands = [
              {"required_capability":"filesystem","intent":"read","inputs":{"path":"source.txt"},"expected_output":"text","expected_evidence":"file text","risk":0,"side_effect_class":"none","budget":1,"reversibility":True,"confidence":.9,"information_gain":.8,"filesystem_need":"workspace"},
              {"required_capability":"filesystem","intent":"write","inputs":{"path":"source.summary.txt","content":"Summary: {evidence}"},"expected_output":"summary file","expected_evidence":"file hash","risk":0,"side_effect_class":"workspace","budget":1,"reversibility":True,"confidence":.9,"goal_value":3,"filesystem_need":"workspace"}]
        else:
            demands = [
              {"required_capability":"web","intent":"GET","inputs":{"url":self.url},"expected_output":"official evidence","expected_evidence":"HTTP hash","risk":0,"side_effect_class":"none","budget":1,"reversibility":True,"confidence":.8,"information_gain":2,"network_need":"public-http-test"},
              {"required_capability":"filesystem","intent":"write","inputs":{"path":"report.txt","content":"Evidence: {evidence}"},"expected_output":"report file","expected_evidence":"file hash","risk":0,"side_effect_class":"workspace","budget":1,"reversibility":True,"confidence":.9,"goal_value":4,"filesystem_need":"workspace"}]
        return {"desired_outcome":"saved evidence", "hypotheses":[perspective], "constraints":[], "unknowns":[],
                "next_useful_action":"use body", "confidence":.8, "sister_response":"CHALLENGE", "body_demands":demands}


def test_real_godruntime_research_save_sister_digest_and_restart(tmp_path: Path):
    class Evidence(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.send_header("Content-Type","text/plain"); self.end_headers(); self.wfile.write(b"controlled official protocol evidence")
        def log_message(self, *_): pass
    server=HTTPServer(("127.0.0.1",0),Evidence); worker=threading.Thread(target=server.serve_forever); worker.start()
    url=f"http://127.0.0.1:{server.server_port}/status"; providers={"p":BodyPlanningProvider(url)}
    runtime=GodRuntime(tmp_path,providers,[ModelRecord("p","A"),ModelRecord("p","B")],secret="key",web_test_allow_hosts={"127.0.0.1"})
    identities={k:v.id for k,v in runtime.organism.colonies.items()}; lineages={k:list(v.lineage) for k,v in runtime.organism.colonies.items()}
    try:
        episode=runtime.submit_goal("Research current protocol evidence and save a report")
        assert episode["work_class"]=="DELIBERATIVE" and set(episode["interpretations"])=={"Saphira-A","Saphira-B"}
        assert episode["exchange"]["round"]==1 and episode["body"]["status"]=="verified"
        report=(tmp_path/"workspace/report.txt"); assert report.exists() and "controlled official" in report.read_text()
        assert len(runtime.embodiment_store.all("prediction")) >= 4
        assert all(o["content_hash"] for o in runtime.embodiment_store.all("observation"))
        assert runtime.embodiment_store.all("digest")
        assert "Completed real body actions" in episode["body"]["final_response"]
    finally: runtime.close(); server.shutdown(); worker.join(); server.server_close()
    restored=GodRuntime(tmp_path,providers,[ModelRecord("p","A"),ModelRecord("p","B")],secret="key",web_test_allow_hosts={"127.0.0.1"})
    assert {k:v.id for k,v in restored.organism.colonies.items()}==identities
    assert {k:list(v.lineage) for k,v in restored.organism.colonies.items()}==lineages
    assert restored.operational_status()["work_class"]=="DELIBERATIVE"
    assert restored.embodiment_store.all("observation") and restored.embodiment_store.all("exchange") and restored.embodiment_store.all("digest")
    assert restored.sister_exchange.rounds and ("workspace","read") in restored.body_bus.handlers
    restored.close()


def test_real_godruntime_workspace_summarize_and_save(tmp_path: Path):
    provider=BodyPlanningProvider("unused")
    runtime=GodRuntime(tmp_path,{"p":provider},[ModelRecord("p","A"),ModelRecord("p","B")],secret="key")
    workspace=tmp_path/"workspace"; workspace.mkdir(exist_ok=True); (workspace/"source.txt").write_text("alpha beta gamma")
    episode=runtime.submit_goal("Read this workspace file, summarize it, and save the summary beside it")
    assert episode["body"]["status"]=="verified"
    assert "alpha beta gamma" in (workspace/"source.summary.txt").read_text()
    runtime.close()


def test_redirect_target_is_revalidated():
    from tmco.embodiment import PermissionDenied, WebResearchOrgan
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(302); self.send_header("Location","http://169.254.169.254/latest/meta-data"); self.end_headers()
        def log_message(self,*_): pass
    server=HTTPServer(("127.0.0.1",0),Redirect); worker=threading.Thread(target=server.serve_forever); worker.start()
    try:
        organ=WebResearchOrgan(test_allow_hosts={"127.0.0.1"})
        try: organ.request({"url":f"http://127.0.0.1:{server.server_port}/redirect"})
        except PermissionDenied: pass
        else: raise AssertionError("metadata redirect target was accepted")
    finally: server.shutdown(); worker.join(); server.server_close()
