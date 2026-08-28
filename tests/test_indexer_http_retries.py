from types import SimpleNamespace

import requests

from debripod.Services.indexers.http_client import IndexerHttpClient
from debripod.Services.indexers.status import IndexerStatus


class StatusStore:
    def __init__(self):
        self.status = IndexerStatus("demo")
        self.failures = []
        self.successes = []
        self.clearances = []

    def get(self, _id): return self.status
    def record_failure(self, *args, **kwargs): self.failures.append((args, kwargs)); return self.status
    def record_success(self, *args, **kwargs): self.successes.append((args, kwargs)); return self.status
    def save_clearance(self, *args, **kwargs): self.clearances.append((args, kwargs)); return self.status


class Session:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes); self.calls = 0; self.headers = {}; self.cookies = requests.cookies.RequestsCookieJar()
    def request(self, *args, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception): raise outcome
        return outcome


def _response(status, headers=None, text=""):
    return SimpleNamespace(status_code=status, headers=headers or {}, text=text)


def test_retries_only_transient_responses_and_honors_retry_after():
    sleeps = []
    session = Session([_response(503), _response(429, {"Retry-After": "2"}), _response(200)])
    client = IndexerHttpClient("demo", status_store=StatusStore(), session=session, retries=2, sleep=sleeps.append, jitter=lambda a, b: 0)
    assert client.request("GET", "https://tracker.test/search").status_code == 200
    assert session.calls == 3 and 2 in sleeps


def test_does_not_retry_ordinary_4xx_or_connection_beyond_limit():
    session = Session([_response(401)])
    client = IndexerHttpClient("demo", status_store=StatusStore(), session=session, retries=2, sleep=lambda _: None, jitter=lambda a, b: 0)
    assert client.request("GET", "https://tracker.test/").status_code == 401 and session.calls == 1
    session = Session([requests.ConnectionError("reset")] * 3)
    client = IndexerHttpClient("demo", status_store=StatusStore(), session=session, retries=2, sleep=lambda _: None, jitter=lambda a, b: 0)
    import pytest
    with pytest.raises(requests.ConnectionError): client.request("GET", "https://tracker.test/")
    assert session.calls == 3


def test_solver_only_runs_after_positive_detection():
    class Solver:
        def __init__(self): self.calls = 0
        def solve(self, *args): self.calls += 1; return {"ok": False}
    solver = Solver()
    session = Session([_response(503, text="Maintenance")])
    IndexerHttpClient("demo", status_store=StatusStore(), session=session, retries=0, solver=solver).request("GET", "https://tracker.test/")
    assert solver.calls == 0


def test_unresolved_positive_challenge_is_marked_for_provider_short_circuit():
    class Solver:
        def solve(self, *_args): return {"ok": False, "error": "challenge timeout"}
    response = _response(403, text="<title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'></script>")
    returned = IndexerHttpClient("demo", status_store=StatusStore(), session=Session([response]), retries=0, solver=Solver()).request("GET", "https://tracker.test/")
    assert returned._debripod_challenge_failed is True
    assert returned._debripod_challenge_error == "challenge timeout"
