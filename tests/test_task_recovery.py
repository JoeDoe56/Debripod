from __future__ import annotations

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from debripod import auth
from debripod.Routes import tasks as task_routes
from debripod.Tasks import manager
from debripod.passwords import generate_password_hash
from debripod.storage import database, users
from debripod.storage.tasks import save_task_metadata
from debripod.user_runtime import USER_RUNTIME_KEY


def test_startup_recovery_marks_only_active_tasks_interrupted_and_restart_creates_new_attempt(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBRIPOD_DATABASE", str(tmp_path / "tasks.sqlite3"))
    database.initialize_database()
    alice = users.create_user("alice", generate_password_hash("alice-password"), role="owner")
    bob = users.create_user("bob", generate_password_hash("bob-password"), role="user")
    active = manager.Task("active-task", "Active", "magnet:?xt=urn:btih:abc", str(tmp_path / "active"), owner_user_id=alice["user_id"], source="debrid", state="downloading")
    complete = manager.Task("complete-task", "Complete", "", str(tmp_path / "complete"), owner_user_id=bob["user_id"], source="youtube", state="done")
    save_task_metadata(active)
    save_task_metadata(complete)

    manager.TASKS.clear()
    restored = manager.restore_persisted_tasks()
    by_id = {task.id: task for task in restored}
    assert by_id[active.id].state == "interrupted"
    assert by_id[active.id].lifecycle_state == "interrupted"
    assert by_id[complete.id].state == "done"
    assert [task.id for task in manager.list_tasks_for_user(alice["user_id"])] == [active.id]
    assert [task.id for task in manager.list_tasks_for_user(bob["user_id"])] == [complete.id]

    restarted = manager.restart_task_attempt(active.id)
    assert restarted is not None
    assert restarted.id != active.id
    assert restarted.previous_task_id == active.id
    assert restarted.attempt == 2
    assert restarted.task_dir != active.task_dir
    assert manager.get_task(active.id).state == "interrupted"


def test_bob_cannot_restart_alices_task(monkeypatch):
    previous_tasks = dict(manager.TASKS)
    manager.TASKS.clear()
    alice_task = manager.Task("alice-task", "Alice", "", "", owner_user_id="alice-id", source="youtube", state="interrupted")
    manager.TASKS[alice_task.id] = alice_task

    monkeypatch.setattr(
        task_routes,
        "current_user",
        lambda request: auth.UserContext("bob-id", "bob", "user") if request.headers.get("X-Test-User") == "bob" else auth.UserContext("alice-id", "alice", "owner"),
    )

    async def scenario():
        app = web.Application()
        task_routes.register_task_routes(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post("/api/tasks/restart", json={"task_id": "alice-task"}, headers={"X-Test-User": "bob"})
            assert response.status == 404
            assert set(manager.TASKS) == {"alice-task"}
        finally:
            await client.close()

    try:
        asyncio.run(scenario())
    finally:
        manager.TASKS.clear()
        manager.TASKS.update(previous_tasks)


def test_restart_uses_the_restarting_users_soulseek_service(monkeypatch):
    previous_tasks = dict(manager.TASKS)
    manager.TASKS.clear()
    task = manager.Task("alice-soulseek", "Alice", "", "", owner_user_id="alice-id", source="soulseek", state="interrupted", slsk_user="peer", slsk_files=[{"remote_path": "Music\\song.flac", "user": "peer"}])
    manager.TASKS[task.id] = task
    calls = []

    class Soulseek:
        def is_ready(self):
            return True

        async def enqueue_downloads_async(self, task_id, username, paths):
            calls.append((task_id, username, paths))

    @web.middleware
    async def attach_runtime(request, handler):
        request[USER_RUNTIME_KEY] = type("Runtime", (), {"soulseek_service": Soulseek()})()
        return await handler(request)

    monkeypatch.setattr(task_routes, "current_user", lambda _request: auth.UserContext("alice-id", "alice", "owner"))

    async def scenario():
        app = web.Application(middlewares=[attach_runtime])
        task_routes.register_task_routes(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post("/api/tasks/restart", json={"task_id": task.id})
            assert response.status == 200
            payload = await response.json()
            assert calls == [(payload["task_id"], "peer", ["Music\\song.flac"])]
            assert manager.get_task(payload["task_id"]).owner_user_id == "alice-id"
        finally:
            await client.close()

    try:
        asyncio.run(scenario())
    finally:
        manager.TASKS.clear()
        manager.TASKS.update(previous_tasks)
