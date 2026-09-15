from debripod.playback.state import PlaybackRuntime, playback_snapshot_public, playback_update_from_client


def _item(rel: str) -> dict:
    return {"root_id": "music", "rel": rel, "media": "audio", "label": rel}


def _update(runtime: PlaybackRuntime, rel: str, event: str, session_id: str, queue: list[dict]) -> None:
    result = playback_update_from_client(
        {
            "media": "audio",
            "root_id": "music",
            "rel": rel,
            "label": rel,
            "playing": True,
            "event": event,
            "playlist": {"items": queue, "index": next((i for i, item in enumerate(queue) if item["rel"] == rel), 0)},
            "session": {"queue": queue, "queueIndex": 0, "queueSessionId": session_id},
        },
        runtime,
    )
    assert result["ok"]


def test_natural_track_transitions_stay_in_one_history_queue():
    runtime = PlaybackRuntime()
    queue = [_item("one.flac"), _item("two.flac")]
    _update(runtime, "one.flac", "start", "queue-a", queue)
    _update(runtime, "two.flac", "start", "queue-a", queue)
    _update(runtime, "two.flac", "time", "queue-a", queue)

    recent = playback_snapshot_public(runtime)["recent"]
    assert len(recent) == 1
    assert recent[0]["rel"] == "two.flac"
    assert [item["rel"] for item in recent[0]["playlist"]["items"]] == ["one.flac", "two.flac"]


def test_new_queue_session_adds_history_entry_and_append_updates_it():
    runtime = PlaybackRuntime()
    first_queue = [_item("one.flac"), _item("two.flac")]
    second_queue = [_item("album-a.flac"), _item("album-b.flac")]
    _update(runtime, "one.flac", "start", "queue-a", first_queue)
    _update(runtime, "album-a.flac", "start", "queue-b", second_queue)
    appended_queue = second_queue + [_item("album-c.flac")]
    _update(runtime, "album-a.flac", "time", "queue-b", appended_queue)
    _update(runtime, "album-b.flac", "start", "queue-b", appended_queue)

    recent = playback_snapshot_public(runtime)["recent"]
    assert len(recent) == 2
    assert recent[0]["rel"] == "album-b.flac"
    assert [item["rel"] for item in recent[0]["playlist"]["items"]] == ["album-a.flac", "album-b.flac", "album-c.flac"]
    assert recent[1]["rel"] == "one.flac"


def test_resume_history_retains_appended_queue_and_session_identity():
    runtime = PlaybackRuntime()
    dirt = [_item("Dirt/one.flac"), _item("Dirt/two.flac")]
    extended = dirt + [_item("Tripod/one.flac")]
    _update(runtime, "Dirt/one.flac", "start", "dirt", dirt)
    _update(runtime, "Dirt/two.flac", "time", "dirt", extended)
    _update(runtime, "stream", "start", "stream", [_item("stream")])
    _update(runtime, "Dirt/two.flac", "start", "dirt", extended)
    recent = playback_snapshot_public(runtime)["recent"]
    assert len(recent) == 2
    assert recent[0]["queueSessionId"] == "dirt"
    assert len(recent[0]["playlist"]["items"]) == 3
    assert recent[1]["queueSessionId"] == "stream"


def test_time_update_recovers_missing_start_even_when_other_history_exists():
    runtime = PlaybackRuntime()
    _update(runtime, "previous", "start", "old", [_item("previous")])
    _update(runtime, "new", "time", "new", [_item("new")])
    recent = playback_snapshot_public(runtime)["recent"]
    assert [entry["rel"] for entry in recent] == ["new", "previous"]
