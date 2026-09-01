from __future__ import annotations

import asyncio

import pytest

from debripod.Services import soulseek
from debripod.Tasks import manager


def test_soulseek_search_sessions_and_staging_are_runtime_owned(tmp_path, monkeypatch):
    monkeypatch.setattr(soulseek, "cache_dir", lambda: str(tmp_path / "cache"))

    async def scenario():
        alice = soulseek.SoulseekService("user-alice", "alice", "password", str(tmp_path / "alice"), 0, 0)
        bob = soulseek.SoulseekService("user-bob", "bob", "password", str(tmp_path / "bob"), 0, 0)
        alice_sid = alice.create_search_session("alice-key", "alice search")
        bob_sid = bob.create_search_session("bob-key", "bob search")
        alice._add_search_session_items(alice_sid, [{"user": "peer", "remote_path": "A\\song.flac", "size": 1}])

        assert alice.search_session_snapshot(alice_sid)["file_count"] == 1
        assert bob.search_session_snapshot(alice_sid) is None
        assert bob.search_session_snapshot(bob_sid)["file_count"] == 0
        assert alice.incoming_dir != bob.incoming_dir
        assert "user-alice" in alice.incoming_dir and "user-bob" in bob.incoming_dir

    asyncio.run(scenario())


def test_soulseek_port_reservations_reject_collisions_without_affecting_other_runtime(tmp_path):
    async def scenario():
        alice = soulseek.SoulseekService("user-alice", "alice", "password", str(tmp_path / "alice"), 56111, 0)
        bob = soulseek.SoulseekService("user-bob", "bob", "password", str(tmp_path / "bob"), 56111, 0)
        alice._reserve_ports()
        try:
            with pytest.raises(RuntimeError, match="already used by another DebriPod account"):
                bob._reserve_ports()
            assert soulseek._SLSK_RESERVED_PORTS[56111] == "user-alice"
        finally:
            alice._release_ports()
        bob._reserve_ports()
        bob._release_ports()

    asyncio.run(scenario())


def test_soulseek_task_controls_resolve_the_tasks_owner_service():
    previous_tasks = dict(manager.TASKS)
    previous_provider = manager._soulseek_service_provider
    calls: list[tuple[str, str]] = []

    class Service:
        def __init__(self, user_id: str):
            self.user_id = user_id

        def abort_task(self, task_id: str):
            calls.append((self.user_id, task_id))

    try:
        manager.TASKS.clear()
        manager.configure_task_manager(soulseek_service_provider=lambda user_id: Service(user_id))
        task = manager.Task("soulseek-task", "title", "", "", owner_user_id="user-alice", source="soulseek")
        manager.TASKS[task.id] = task
        assert manager.cancel_task(task.id)
        assert calls == [("user-alice", "soulseek-task")]
    finally:
        manager.TASKS.clear()
        manager.TASKS.update(previous_tasks)
        manager._soulseek_service_provider = previous_provider
