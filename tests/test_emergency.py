import json
from dataclasses import replace

import pytest

from tmco.buses import BodyBus, ModelBus, OrganManifest
from tmco.emergency import (EmergencyAction, EmergencyAuthority, EmergencyPhraseStore,
                            EmergencyState)
from tmco.root import AuthorizationError, RootGuard, RootKernel
from tmco.capabilities import CapabilityRequest, OwnerCapabilityAuthority


SYNTHETIC_TEST_PHRASE = "TEST-ONLY emergency factor 9274"


def authority(tmp_path, clock=None):
    now = clock or [100.]
    root = RootKernel("Pier", RootGuard(b"synthetic-root-material"))
    return root, EmergencyPhraseStore(tmp_path), EmergencyAuthority(root, tmp_path, lambda: now[0]), now


def test_canonical_owner_constitution_and_phrase_enrollment(tmp_path):
    root, store, emergency, _ = authority(tmp_path)
    assert root.owner == "Pier"
    with pytest.raises(AttributeError): root.owner = "Saphira-A"
    assert {"owner_identity_is_not_an_evolution_target", "cognition_cannot_redefine_owner",
            "cells_cannot_grant_owner_authority", "absence_of_intelligence_cannot_block_owner_stop"} <= set(root.constitution)
    store.enroll(SYNTHETIC_TEST_PHRASE)
    raw = store.path.read_bytes()
    assert SYNTHETIC_TEST_PHRASE.encode() not in raw
    with pytest.raises(AuthorizationError): store.enroll("TEST-ONLY replacement factor")
    assert not store.verify("TEST-ONLY wrong emergency factor")
    attestation = emergency.attest(store, SYNTHETIC_TEST_PHRASE, EmergencyAction.STOP)
    assert attestation.fact()["status"] == "OWNER_AUTHORIZED"
    assert emergency.apply(attestation) is EmergencyState.STOP_REQUESTED
    with pytest.raises(AuthorizationError): emergency.apply(attestation)
    with pytest.raises(AuthorizationError): emergency.apply(replace(attestation, resource="other"))
    with pytest.raises(AuthorizationError): emergency.apply(replace(attestation, action="LOCKDOWN", nonce="new"))


def test_emergency_boundaries_and_restart_do_not_need_models(tmp_path):
    root, store, emergency, clock = authority(tmp_path); store.enroll(SYNTHETIC_TEST_PHRASE)
    body = BodyBus(emergency); effects = []
    body.register(OrganManifest("external", "test", "1", {"write": {}}, side_effect_class="external"),
                  {"write": lambda args: effects.append(args)})
    pause = emergency.attest(store, SYNTHETIC_TEST_PHRASE, EmergencyAction.PAUSE)
    emergency.apply(pause)
    with pytest.raises(AuthorizationError): body.request("external", "write", {"x": 1})
    assert effects == []
    body.register(OrganManifest("network-read", "test", "1", {"GET": {}}, side_effect_class="read",
                                network_scope=("public",)), {"GET": lambda args: effects.append(args)})
    with pytest.raises(AuthorizationError): body.request("network-read", "GET", {})
    lockdown = emergency.attest(store, SYNTHETIC_TEST_PHRASE, EmergencyAction.LOCKDOWN)
    emergency.apply(lockdown)
    class Remote:
        privacy = "remote"
        def infer(self, request): raise AssertionError("provider must not be called")
    models = ModelBus({"remote": Remote()}, emergency=emergency)
    with pytest.raises(AuthorizationError):
        models.request("remote", {"data_classes": ["OWNER_TYPED"], "prompt": "synthetic"})
    capabilities = OwnerCapabilityAuthority(root, tmp_path/"capabilities.sqlite3", emergency=emergency)
    with pytest.raises(AuthorizationError):
        capabilities.request(CapabilityRequest("Pier", "remote", "connect", "test", "w", "host",
                                               "none", "account"))
    restored = EmergencyAuthority(root, tmp_path, lambda: clock[0])
    assert restored.state is EmergencyState.LOCKDOWN
    stop = restored.attest(store, SYNTHETIC_TEST_PHRASE, EmergencyAction.STOP)
    restored.apply(stop)
    assert EmergencyAuthority(root, tmp_path, lambda: clock[0]).state is EmergencyState.STOP_REQUESTED
    assert not hasattr(restored, "clear")


def test_expired_attestation_fails(tmp_path):
    _, store, emergency, clock = authority(tmp_path); store.enroll(SYNTHETIC_TEST_PHRASE)
    attestation = emergency.attest(store, SYNTHETIC_TEST_PHRASE, EmergencyAction.LOCKDOWN, ttl_seconds=1)
    clock[0] += 2
    with pytest.raises(AuthorizationError): emergency.apply(attestation)
