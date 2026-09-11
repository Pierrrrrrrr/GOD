import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from tmco.awakening import GodRuntime
from tmco.embodiment import OutcomeEvaluation
from tmco.models import ModelRecord
from tmco.sisters import DigestResponse
import time


class BodyPlanningProvider:
    def __init__(self, url: str): self.url, self.calls = url, []
    def infer(self, request):
        self.calls.append(request); prompt = request["prompt"]
        if "Assess only whether" in prompt: return {"material_disagreement": True, "reasons": ["method"]}
        if "separate sister-audit" in prompt: return {"disagreements":["method"],"synthesis":"use observed evidence","selected_next_action":"research","rationale":"bounded evidence"}
        if "Respond to this SisterBrief" in prompt: return {"response":"CHALLENGE","reason":"retain alternative","updated_confidence":.7,"counterproposal":"verify independently","evidence_refs":[]}
        context = json.loads(prompt.split("JSON context:\n",1)[1]); goal = context.get("goal", "")
        perspective = request["model_id"]
        if "summarize" in goal.lower():
            demands = [
              {"required_capability":"filesystem","intent":"read","inputs":{"path":"source.txt"},"expected_output":"text","expected_evidence":"file text","risk":0,"side_effect_class":"none","budget":1,"reversibility":True,"confidence":.9,"goal_value":2,"information_gain":.8,"capability_gain":0,"uncertainty":.1,"network_need":"none","filesystem_need":"workspace"},
              {"required_capability":"filesystem","intent":"write","inputs":{"path":"source.summary.txt","content":"Summary: {evidence}"},"expected_output":"summary file","expected_evidence":"file hash","risk":0,"side_effect_class":"workspace","budget":1,"reversibility":True,"confidence":.9,"goal_value":3,"information_gain":0,"capability_gain":0,"uncertainty":.1,"network_need":"none","filesystem_need":"workspace"}]
        else:
            demands = [
              {"required_capability":"web","intent":"GET","inputs":{"url":self.url},"expected_output":"official evidence","expected_evidence":"HTTP hash","risk":0,"side_effect_class":"none","budget":1,"reversibility":True,"confidence":.8,"goal_value":2,"information_gain":2,"capability_gain":0,"uncertainty":.2,"network_need":"public-http-test","filesystem_need":"none"},
              {"required_capability":"filesystem","intent":"write","inputs":{"path":"report.txt","content":"Evidence: {evidence}"},"expected_output":"report file","expected_evidence":"file hash","risk":0,"side_effect_class":"workspace","budget":1,"reversibility":True,"confidence":.9,"goal_value":4,"information_gain":0,"capability_gain":0,"uncertainty":.1,"network_need":"none","filesystem_need":"workspace"}]
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
        prompts=[call["prompt"] for call in providers["p"].calls]
        independent=[i for i,prompt in enumerate(prompts) if "Reason independently" in prompt]
        post_index=next(i for i,prompt in enumerate(prompts) if "Respond to this SisterBrief" in prompt)
        assert len(independent)==2 and max(independent)<post_index
        assert "body_demands as a JSON list" in prompts[independent[0]]
        assert all("sister_brief" not in prompts[index] and "independent_arguments" not in prompts[index] for index in independent)
        post_context=json.loads(prompts[post_index].split("JSON context:\n",1)[1])
        assert set(post_context)=={"goal","sister_brief"} and "independent_arguments" not in post_context
        assert episode["work_class"]=="DELIBERATIVE" and set(episode["interpretations"])=={"Saphira-A","Saphira-B"}
        assert episode["exchange"]["round"]==1 and episode["exchange"]["post_brief_response"]["response"]=="CHALLENGE"
        assert episode["body"]["status"]=="executed"
        report=(tmp_path/"workspace/report.txt"); assert report.exists() and "controlled official" in report.read_text()
        assert len(runtime.embodiment_store.all("prediction")) >= 4
        assert all(o["content_hash"] for o in runtime.embodiment_store.all("observation"))
        assert not runtime.embodiment_store.all("digest")
        assert sum(n.verified_contribution for c in runtime.organism.colonies.values() for n in c.neurons.values())==0
        assert not any(record.task_performance for record in runtime.records.values())
        assert runtime.body_bus.manifests["web-research"].verified_reliability > .8
        assert runtime.operational_status()["current_step"]=="AWAITING_OUTCOME"
        observation_id=episode["body"]["observations"][0]["action_id"]
        prediction=next(p for p in runtime.embodiment_store.all("prediction") if p["action_id"]==observation_id)
        assert (prediction["expected"],prediction["expected_evidence"])==("official evidence","HTTP hash")
        assert (prediction["confidence"],prediction["expected_value"],prediction["information_gain"],prediction["uncertainty"])==(.8,2,2,.2)
        ambiguous=next(o["action_id"] for o in episode["body"]["observations"] if o["decision_provenance_id"] is None)
        assert not runtime.evaluate_outcome(OutcomeEvaluation(ambiguous,"OBJECTIVE_TEST",("test:ambiguous",),True,"pass",time.time(),"objective"))
        try: runtime.evaluate_outcome(OutcomeEvaluation(observation_id,"Saphira-A",("self:claim",),True,"pass",time.time(),"self claim"))
        except PermissionError: pass
        else: raise AssertionError("colony self-verification was trusted")
        memories={name:list(colony.memories) for name,colony in runtime.organism.colonies.items()}
        provenance=next(p for p in runtime.embodiment_store.all("decision_provenance") if p["id"]==prediction["decision_provenance_id"])
        assert runtime.evaluate_outcome(OutcomeEvaluation(observation_id,"OBJECTIVE_TEST",("human-evaluation:1",),True,"pass",time.time(),"objective result"))
        assert runtime.embodiment_store.all("digest")
        source=provenance["source_colony"]; other=next(name for name in runtime.organism.colonies if name!=source)
        assert sum(n.verified_contribution for n in runtime.organism.colonies[source].neurons.values())>0
        assert sum(n.verified_contribution for n in runtime.organism.colonies[other].neurons.values())==0
        assert runtime.records[provenance["source_model_key"]].task_performance
        assert runtime.operational_status()["current_step"]=="OUTCOME_VERIFIED"
        assert not any(record.task_performance for key,record in runtime.records.items() if key!=provenance["source_model_key"])
        assert {name:list(colony.memories) for name,colony in runtime.organism.colonies.items()}==memories
        runtime.respond_to_digest(observation_id,other,DigestResponse.TEST_INDEPENDENTLY)
        assert runtime.embodiment_store.all("borrowed_hypothesis")[-1]["verified"] is False
        assert {name:list(colony.memories) for name,colony in runtime.organism.colonies.items()}==memories
        assert "cognitive outcome remains unverified" in episode["body"]["final_response"]
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
    assert episode["body"]["status"]=="executed"
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
