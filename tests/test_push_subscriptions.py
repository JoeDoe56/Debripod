from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from debripod.storage.database import initialize_database
from debripod.storage.push_subscriptions import (
    claim_delivery,
    save_subscription,
    subscriptions_for_client,
)
from debripod.Tasks.manager import TASKS, TASKS_LOCK, Task, configure_task_manager, set_task
from debripod.Services.push_notifications import enqueue_task_completion


class PushSubscriptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "push.sqlite3")
        self.env = patch.dict(os.environ, {"DEBRIPOD_DATABASE": self.db_path})
        self.env.start()
        initialize_database()
        save_subscription(
            "alice",
            "client-a",
            {"endpoint": "https://push.invalid/a", "keys": {"p256dh": "p-a", "auth": "a-a"}},
        )
        save_subscription(
            "alice",
            "client-b",
            {"endpoint": "https://push.invalid/b", "keys": {"p256dh": "p-b", "auth": "a-b"}},
        )

    def tearDown(self) -> None:
        self.env.stop()
        self.tempdir.cleanup()

    def test_subscription_lookup_is_device_scoped(self) -> None:
        selected = subscriptions_for_client("alice", "client-a")
        self.assertEqual([row["client_id"] for row in selected], ["client-a"])
        self.assertEqual(subscriptions_for_client("alice", ""), [])
        self.assertEqual(subscriptions_for_client("bob", "client-a"), [])

    def test_delivery_is_claimed_once(self) -> None:
        self.assertTrue(claim_delivery("task-1", "alice", "client-a", "done"))
        self.assertFalse(claim_delivery("task-1", "alice", "client-a", "done"))
        self.assertTrue(claim_delivery("task-1", "alice", "client-b", "done"))

    def test_done_transition_notifies_once(self) -> None:
        calls = []
        configure_task_manager(completion_notifier=lambda task: calls.append(task.id))
        task = Task(id="task-done", title="Done", magnet="", task_dir="", owner="alice", origin_client_id="client-a")
        with TASKS_LOCK:
            TASKS[task.id] = task
        try:
            set_task(task.id, state="done")
            set_task(task.id, state="done")
            self.assertEqual(calls, ["task-done"])
        finally:
            with TASKS_LOCK:
                TASKS.pop(task.id, None)
            configure_task_manager(completion_notifier=lambda task: None)

    def test_task_without_origin_never_schedules_push(self) -> None:
        task = Task(id="no-origin", title="No origin", magnet="", task_dir="", owner="alice")
        self.assertFalse(enqueue_task_completion(task, sender=lambda *_args: None))


if __name__ == "__main__":
    unittest.main()
