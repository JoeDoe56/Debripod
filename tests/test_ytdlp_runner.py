import json

import pytest

from debripod.Services import ytdlp_runner


def test_base_args_and_flat_json(monkeypatch):
    captured = {}

    def fake(args, timeout):
        captured["args"] = args
        return 0, json.dumps({"entries": [{"id": "1"}]}), ""

    monkeypatch.setattr(ytdlp_runner, "run_cmd", fake)
    ytdlp_runner.configure_ytdlp_runner(ytdlp_cmd_provider=lambda: "custom-ytdlp")
    assert ytdlp_runner.run_flat_entries("https://example.test") == [{"id": "1"}]
    assert captured["args"][0] == "custom-ytdlp"
    assert captured["args"][1:6] == ["--no-warnings", "--ignore-config", "--plugin-dirs", ytdlp_runner.plugin_root(), "--flat-playlist"]
    assert "--playlist-end" not in captured["args"] and "--max-downloads" not in captured["args"]


@pytest.mark.parametrize(("message", "category"), [("DRM protected", "drm"), ("geo restricted", "geo_restricted"), ("This video is private", "private_or_deleted")])
def test_error_classification(monkeypatch, message, category):
    monkeypatch.setattr(ytdlp_runner, "run_cmd", lambda args, timeout: (1, "", message))
    with pytest.raises(ytdlp_runner.YtdlpError) as raised:
        ytdlp_runner.run_json("x")
    assert raised.value.category == category
