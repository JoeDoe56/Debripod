from __future__ import annotations

import logging
from pathlib import Path

from debripod.Services import soulseek
from debripod.settings import DEFAULT_APP_SETTINGS


def test_aioslsk_diagnostic_logging_defaults_off_and_can_be_disabled(monkeypatch, tmp_path):
    log_path = tmp_path / "soulseek-aioslsk.log"
    monkeypatch.setattr(soulseek, "soulseek_log_file_path", lambda: str(log_path))
    assert DEFAULT_APP_SETTINGS["AIOSLSK_LOGGING_ENABLED"] is False

    logger = logging.getLogger("aioslsk.debripod-test")
    soulseek.configure_aioslsk_logging(True)
    logger.warning("written while enabled")
    assert log_path.is_file()
    enabled_size = log_path.stat().st_size
    assert enabled_size > 0

    assert soulseek.configure_aioslsk_logging(False) == ""
    logger.critical("must not be written while disabled")
    assert log_path.stat().st_size == enabled_size


def test_aioslsk_setting_is_exposed_in_advanced_services():
    source = (Path(__file__).parents[1] / "debripod" / "static" / "js" / "settings-ui.js").read_text(encoding="utf-8")
    assert 'key:"AIOSLSK_LOGGING_ENABLED"' in source
    assert 'key === "AIOSLSK_LOGGING_ENABLED"' in source
