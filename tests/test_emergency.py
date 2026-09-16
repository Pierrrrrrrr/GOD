import json
import multiprocessing
from pathlib import Path

import pytest

from tmco.awakening import GodRuntime
from tmco.buses import OrganManifest
from tmco.emergency import EmergencyFactor, EmergencyState
from tmco.owner_control import open_owner_system
from tmco.paths import ProductPaths
from tmco.root import AuthorizationError


def _stop_in_process(path: str) -> None:
    control=open_owner_system(Path(path),secret=b"x"*32)
    control.emergency.restrict(EmergencyState.STOP_REQUESTED)


def test_product_and_control_share_root_path_authority_and_fingerprint(tmp_path: Path) -> None:
    runtime=GodRuntime(tmp_path,secret=b"x"*32); control=open_owner_system(tmp_path,secret=b"x"*32)
    assert runtime.paths.organism_root==control.emergency.paths.organism_root
    assert runtime.organism.root.key_fingerprint==control.root.key_fingerprint
    assert runtime.emergency is runtime.organism.emergency
    runtime.close()


def test_second_process_restrictions_refresh_live_and_survive_restart(tmp_path: Path) -> None:
    runtime=GodRuntime(tmp_path,secret=b"x"*32); control=open_owner_system(tmp_path,secret=b"x"*32)
    runtime.body_bus.register(OrganManifest("x","test","1",{"go":{}}),{"go":lambda _:{"ok":True}})
    assert runtime.body_bus.request("x","go",{})=={"ok":True}
    control.emergency.restrict(EmergencyState.STOP_REQUESTED)
    with pytest.raises(AuthorizationError):runtime.body_bus.request("x","go",{})
    with pytest.raises(AuthorizationError):runtime.launch_goal("new work")
    runtime.close(); restored=GodRuntime(tmp_path,secret=b"x"*32)
    assert restored.emergency.state==EmergencyState.STOP_REQUESTED;restored.close()


def test_actual_second_process_stop_blocks_already_running_runtime(tmp_path: Path) -> None:
    runtime=GodRuntime(tmp_path,secret=b"x"*32)
    process=multiprocessing.get_context("spawn").Process(target=_stop_in_process,args=(str(tmp_path),))
    process.start();process.join(10)
    assert process.exitcode==0
    with pytest.raises(AuthorizationError):runtime.bus.request("not-configured",{})
    runtime.close()


def test_tampering_fails_closed_and_cache_never_downgrades(tmp_path: Path) -> None:
    runtime=GodRuntime(tmp_path,secret=b"x"*32);runtime.emergency.restrict(EmergencyState.LOCKDOWN)
    path=runtime.paths.emergency_state; value=json.loads(path.read_text());value["state"]="RUNNING";path.write_text(json.dumps(value))
    with pytest.raises(AuthorizationError):runtime.emergency.require_external_effects_allowed()
    assert runtime.emergency._state>=EmergencyState.LOCKDOWN;runtime.close()


def test_atomic_synthetic_factor_and_wrong_phrase(tmp_path: Path) -> None:
    factor=EmergencyFactor(ProductPaths.resolve(tmp_path));factor.enroll("synthetic-only")
    assert factor.verify("synthetic-only") and not factor.verify("wrong")
    with pytest.raises(FileExistsError):factor.enroll("replacement")
