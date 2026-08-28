from debripod.Services.indexers.status import BACKOFF_PERIODS, IndexerStatusStore


def test_backoff_persists_and_success_deescalates(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "status.sqlite3"))
    clock = [1000.0]
    store = IndexerStatusStore(now=lambda: clock[0], startup_at=0)
    failed = store.record_failure("demo", "http_500")
    assert failed.escalation_level == 1
    assert failed.disabled_until == clock[0] + BACKOFF_PERIODS[1]
    clock[0] += 1
    failed = store.record_failure("demo", "http_500")
    assert failed.escalation_level == 2
    assert IndexerStatusStore(now=lambda: clock[0], startup_at=0).get("demo").escalation_level == 2
    success = store.record_success("demo")
    assert success.escalation_level == 1 and success.disabled_until is None
    assert store.record_success("demo", manual_test=True).escalation_level == 0


def test_retry_after_and_startup_grace(monkeypatch, tmp_path):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "grace.sqlite3"))
    store = IndexerStatusStore(now=lambda: 100, startup_at=0)
    assert store.record_failure("retry", "rate", retry_after=900).disabled_until == 1000
    startup = IndexerStatusStore(now=lambda: 100, startup_at=50)
    status = None
    for _ in range(9):
        status = startup.record_failure("startup", "failure")
    assert status.disabled_until <= 400
