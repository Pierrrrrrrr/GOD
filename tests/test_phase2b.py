import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tmco.buses import BodyBus, OrganManifest
from tmco.embodiment import (ActionLoop, CapabilityDemand, CapabilityResolver, EmbodimentStore,
 PermissionDenied, PermissionLease, HumanApprovalRequest, MCPAdapter, MCPRegistry, MCPUnavailable,
 OpenAPIOrgan, OrganRegistry, PermissionAuthority, SandboxBus, SandboxUnavailable, WebResearchOrgan, WorkspaceFilesystemOrgan,
 normalize_a2a_card)
from tmco.sisters import (BriefResponse, DigestResponse, SisterBrief, SisterDevelopmentDigest,
 SisterExchangePolicy, SisterView, WorkClass, classify_work, recruited_colonies)


def filesystem(bus, root):
    organ = WorkspaceFilesystemOrgan(root, (root / ".rootguard", root / ".vault"))
    manifest = OrganManifest("workspace", "filesystem", "1", organ.OPERATIONS, permissions={"workspace.write"},
      side_effect_class="workspace", capability_tags={"filesystem"}, filesystem_scope=(str(root),), verified_reliability=1)
    bus.register(manifest, {name: (lambda args, name=name: organ.handle(name,args)) for name in organ.OPERATIONS})


def test_workspace_security_and_real_observation(tmp_path):
    bus=BodyBus(); filesystem(bus,tmp_path); store=EmbodimentStore(tmp_path/"body.sqlite")
    with pytest.raises(PermissionDenied): bus.request("workspace","read",{"path":"../secret"})
    with pytest.raises(PermissionDenied): bus.request("workspace","write",{"path":".vault/key","content":"x"})
    loop=ActionLoop(bus,store); demand=CapabilityDemand("g","save","filesystem","write",{"path":"x.txt","content":"real"},"file exists",risk=1,budget=1)
    result=loop.execute(demand); assert result.success and (tmp_path/"x.txt").read_text()=="real"
    assert store.all("prediction")[0]["created_at"] <= store.all("observation")[0]["started_at"]
    with pytest.raises(ValueError): loop.completion(None)
    loop.verify(result,lambda o: Path(tmp_path/o.result["path"]).exists()); assert "verified" in loop.completion(result)
    store.close()


def test_http_provenance_failure_and_ssrf(tmp_path):
    class H(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.send_header("Content-Type","text/html"); self.end_headers(); self.wfile.write(b"<title>T</title>evidence")
        def log_message(self,*a): pass
    server=HTTPServer(("127.0.0.1",0),H); thread=threading.Thread(target=server.serve_forever); thread.start()
    try:
        web=WebResearchOrgan(test_allow_hosts={"127.0.0.1"}); result=web.request({"url":f"http://127.0.0.1:{server.server_port}/"})
        assert result["status"]==200 and len(result["content_hash"])==64 and result["title"]=="T"
    finally: server.shutdown(); thread.join(); server.server_close()
    with pytest.raises(PermissionDenied): WebResearchOrgan().request({"url":"http://127.0.0.1/"})
    bus=BodyBus(); bus.register(OrganManifest("bad","web","1",{"GET":{"required":["url"]}},risk=0,capability_tags={"web"}),{"GET":lambda _: (_ for _ in ()).throw(OSError("offline"))})
    store=EmbodimentStore(tmp_path/"fail.sqlite"); obs=ActionLoop(bus,store).execute(CapabilityDemand("g","research","web","GET",{"url":"https://example.invalid"},"evidence",risk=1,budget=1))
    assert not obs.success and obs.error_class=="OSError"; store.close()


def test_openapi_permissions_and_gaps(tmp_path):
    api=OpenAPIOrgan({"servers":[{"url":"https://example.com"}],"paths":{"/items/{id}":{"get":{"operationId":"item","parameters":[{"name":"id","required":True}]}}}},WebResearchOrgan())
    with pytest.raises(ValueError): api.validate("item",{})
    assert api.validate("item",{"id":3}) == ("GET","/items/3")
    bus=BodyBus(); bus.register(OrganManifest("mutator","openapi","1",{"mutate":{"required":[]}},permissions={"external.mutate"},risk=.2,side_effect_class="external-mutation",reversible=False,capability_tags={"mutation"}),{"mutate":lambda _: {"ok":1}})
    store=EmbodimentStore(tmp_path/"p.sqlite"); loop=ActionLoop(bus,store); d=CapabilityDemand("g","change","mutation","mutate",{},"changed",risk=1,budget=1,reversible=False)
    assert isinstance(loop.execute(d),HumanApprovalRequest)
    bad=PermissionLease("l","Saphira-A",("external.mutate",),"Saphira-A",10**12); assert isinstance(loop.execute(d,lease=bad),HumanApprovalRequest)
    good=PermissionLease("l2","Pier",("external.mutate",),"Pier",10**12); store.put("lease",good.id,good); assert loop.execute(d,lease=good).success
    with pytest.raises(PermissionDenied): PermissionAuthority(store).issue("Saphira-A","Saphira-A",("external.mutate",),60)
    assert CapabilityResolver(bus,store).resolve(CapabilityDemand("g","x","sandbox","run",{},"x",risk=1,budget=1)) is None
    store.close()


def test_body_state_and_manifest_survive_restart(tmp_path):
    store=EmbodimentStore(tmp_path/"restart.sqlite"); bus=BodyBus(); organ=WorkspaceFilesystemOrgan(tmp_path/"ws")
    manifest=OrganManifest("workspace","filesystem","1",organ.OPERATIONS,capability_tags={"filesystem"})
    OrganRegistry(bus,store).register(manifest,{name:(lambda args,name=name:organ.handle(name,args)) for name in organ.OPERATIONS})
    authority=PermissionAuthority(store); authority.issue("Pier","body",("workspace.write",),60)
    CapabilityResolver(bus,store).resolve(CapabilityDemand("goal","missing","mcp","invoke",{},"result",risk=1,budget=1))
    store.put("goal","goal",{"id":"goal","status":"active"}); store.close()
    restored=EmbodimentStore(tmp_path/"restart.sqlite"); catalog=OrganRegistry(BodyBus(),restored).persisted()
    assert catalog[0].id=="workspace" and restored.all("lease") and restored.all("gap") and restored.all("goal")
    restored.close()


def test_optional_boundaries_are_honest_and_private_data_filtered():
    registry=MCPRegistry(); registry.discover({"name":"unknown"}); assert registry.entries[0]["trusted"] is False
    adapter=MCPAdapter()
    if not adapter.available():
        with pytest.raises(MCPUnavailable): adapter.invoke("x")
    with pytest.raises(SandboxUnavailable): SandboxBus().execute({"code":"x"})
    manifest=normalize_a2a_card({"name":"peer","url":"https://peer","skills":[{"id":"search"}],"credentials":"secret","private_topology":{"x":1}})
    assert manifest.trusted is False and "secret" not in json.dumps(manifest.operations)


def test_selective_exchange_digest_speed_and_diversity():
    a=SisterView("A",{"private":"a"}); b=SisterView("B",{"private":"b"}); policy=SisterExchangePolicy()
    brief=SisterBrief("A","claim","test",("obs:1",),.7,prediction="result")
    assert policy.exchange("t",a,b,brief,BriefResponse.CHALLENGE,trigger="material_disagreement",counterproposal="minority")
    assert not policy.exchange("t",a,b,brief,BriefResponse.ACCEPT,trigger="high_uncertainty")
    assert b.reasoning=={"private":"b"} and b.minority_hypotheses==["minority"]
    digest=SisterDevelopmentDigest("A",("worked",),(),"research",None,"route","check hash",("obs:1",),True)
    assert policy.apply_digest(b,digest,DigestResponse.ADOPT) and b.adopted_lessons==["check hash"]
    unverified=SisterDevelopmentDigest("A",("claimed",),(),None,None,"","guess",(),False)
    assert not policy.apply_digest(b,unverified,DigestResponse.ADOPT)
    assert recruited_colonies(classify_work("hello"))==()
    assert recruited_colonies(classify_work("research this"))==("Saphira-A","Saphira-B")
