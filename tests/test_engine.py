from app.services.engine import AnalysisEngine


def _repo(state="CURRENT", scope="model"):
    current = {"components": {"model": "m1", "services": "s1", "data": "d1", "dependencies": "dep1", "config": "c1"}}
    accepted = {"components": {"model": "m0", "services": "s0", "data": "d0", "dependencies": "dep0", "config": "c0"}}
    return {"scope": scope, "state": state, "current": current, "accepted": accepted}


def test_prediction_environment_fingerprint_changes_after_accepted_update():
    stale_fp = AnalysisEngine._prediction_environment_fingerprint(_repo("STALE"))
    current_fp = AnalysisEngine._prediction_environment_fingerprint(_repo("CURRENT"))
    assert stale_fp != current_fp


def test_external_repository_does_not_bind_model_environment():
    assert AnalysisEngine._prediction_environment_fingerprint(_repo(scope="external")) == ""
