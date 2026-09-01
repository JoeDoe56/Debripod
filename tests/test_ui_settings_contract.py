from pathlib import Path

from debripod.runtime_routes import _coerce_advanced_ui_defaults, _coerce_glass_defaults
from debripod import settings as settings_module
from debripod.settings import DEVICE_SETTING_KEYS, SETTING_DESCRIPTORS, DEFAULT_UI_SETTINGS, migrate_owner_server_settings, normalize_settings, ui_setting_updates


REPO = Path(__file__).resolve().parents[1]


def test_device_ui_settings_have_explicit_descriptors_and_never_normalize_as_server_values():
    settings = normalize_settings(
        {
            "UI_TEXT_WHEEL_LABELS": "black",
            "UI_TEXT_PATH_PILL": "white",
            "UI_TEXT_INFO_PILL": "engraved",
            "UI_TEXT_ROWS": "not-a-mode",
        }
    )
    assert all(SETTING_DESCRIPTORS[key]["scope"] == "device" for key in DEVICE_SETTING_KEYS)
    assert "UI_TEXT_WHEEL_LABELS" not in settings
    assert "UI_TEXT_PATH_PILL" not in settings
    assert "UI_TEXT_INFO_PILL" not in settings
    assert "UI_TEXT_ROWS" not in settings

    defaults = _coerce_advanced_ui_defaults(
        {"textModes": {"wheelLabels": "black", "pathPill": "white", "rows": "engraved"}},
        {},
    )
    assert defaults["textModes"]["wheelLabels"] == "contrast"
    assert defaults["textModes"]["pathPill"] == "contrast"
    assert defaults["textModes"]["rows"] == "contrast"


def test_retired_animation_keys_are_removed_from_defaults_and_legacy_updates():
    assert "pageTransition" not in DEFAULT_UI_SETTINGS["animationFps"]
    assert "rowExpansion" not in DEFAULT_UI_SETTINGS["animationFps"]
    updates = ui_setting_updates({"animationFps": {"pageTransition": 30, "rowExpansion": 120}})
    assert "UI_ANIMATION_PAGE_TRANSITION_FPS" not in updates
    assert "UI_ANIMATION_ROW_EXPANSION_FPS" not in updates


def test_remote_torrent_setting_accepts_only_the_seven_fixed_adapters():
    settings = normalize_settings(
        {"TORRENT_SEARCH_ENABLED_SOURCES": ["Knaben", "TorAPI", "cardigann", "torrents_csv", "unknown"]}
    )
    assert settings["TORRENT_SEARCH_ENABLED_SOURCES"] == ["knaben", "torapi"]


def test_owner_server_setting_migration_keeps_meaningful_legacy_value(monkeypatch):
    rows = {
        "owner-id": {"YTDLP_CMD": "D:/tools/yt-dlp.exe", "DOWNLOAD_DIR": "D:/owner"},
        "": {},
    }
    writes = []
    monkeypatch.setattr(settings_module.settings_repository, "load", lambda scope="": dict(rows.get(scope, {})))
    monkeypatch.setattr(settings_module.settings_repository, "save", lambda values, scope="": writes.append((dict(values), scope)))

    assert migrate_owner_server_settings("owner-id") is True
    assert writes == [({"YTDLP_CMD": "D:/tools/yt-dlp.exe"}, "")]


def test_ui_offers_exactly_contrast_and_transparent_text_modes():
    source = (REPO / "debripod" / "static" / "js" / "settings-ui.js").read_text(encoding="utf-8")
    list_view = (REPO / "debripod" / "static" / "js" / "list-view.js").read_text(encoding="utf-8")
    library_browser = (REPO / "debripod" / "static" / "js" / "library-browser.js").read_text(encoding="utf-8")
    playback_sync = (REPO / "debripod" / "static" / "js" / "playback-sync.js").read_text(encoding="utf-8")
    assert 'const TEXT_MODE_ORDER = ["contrast", "transparent"];' in source
    assert 'pageTransition' not in source
    assert 'rowExpansion' not in source
    assert 'replaceListItems(arr, {animate:false, preserveSelection:false, preserveScroll:false' in list_view
    assert 'pageTransition' not in list_view
    assert 'animateWhenPageIsVisible' not in list_view
    assert '_dpPageTransitionActive' not in list_view
    assert 'runLibraryPageTransition' not in library_browser
    assert 'runLibraryPageTransition' not in playback_sync
    assert 'applyThemeVars(defaultTheme)' not in playback_sync
    assert 'applyVisualizerPresetPalette()' not in playback_sync


def test_cached_view_startup_still_initializes_server_config_and_liquid_glass():
    startup = (REPO / "debripod" / "static" / "debripod.js").read_text(encoding="utf-8")
    config_call = startup.index("await loadConfig();")
    cached_restore = startup.index("DebriPod.clientSync.awaitReady")
    roots_fallback = startup.index("await showRoots()")
    assert config_call < cached_restore < roots_fallback


def test_screen_content_stays_above_the_main_liquid_glass_canvas():
    css = (REPO / "debripod" / "static" / "debripod.css").read_text(encoding="utf-8")
    assert ".liquidGlassCanvasMain{ z-index: 65 !important; }" in css
    screen_rule = css[css.index(".ipodScreen{"):css.index(".ipodScreenContent{")]
    expanded_start = css.index(".ipodStage.layoutExpanded .ipodScreen{")
    expanded_rule = css[expanded_start:css.index("}", expanded_start)]
    assert "z-index:70;" in screen_rule
    assert "z-index:70;" in expanded_rule


def test_service_worker_never_matches_versioned_assets_without_their_query():
    worker = (REPO / "debripod" / "static" / "debripod-sw.js").read_text(encoding="utf-8")
    assert "ignoreSearch" not in worker
    assert "return caches.match(request);" in worker


def test_glass_settings_migrate_to_one_signed_material_value_per_target():
    migrated = _coerce_glass_defaults(
        {
            "libraryList": {"glassTint": 0.0, "frost": 4, "shadow": True},
            "wheel": {"glassTint": 2.0, "refraction": 0.2},
            "pathPill": {"material": 4},
            "infoPill": {"material": float("nan")},
            "listPills": {"mode": "dark"},
            "selectedRow": {"glassTint": 1.5, "transparency": 0.5},
        }
    )
    assert migrated["libraryList"] == {"label": "Library list", "material": -0.52}
    assert migrated["wheel"] == {"label": "Wheel", "material": 0.52}
    assert migrated["pathPill"]["material"] == 1.0
    assert migrated["infoPill"]["material"] == 0.0
    assert migrated["listPills"]["material"] == -0.52
    assert migrated["selectedRow"]["material"] == 0.13
    assert all(set(value) == {"label", "material"} for value in migrated.values())
    assert DEFAULT_UI_SETTINGS["liquidGlassElements"] == {
        "libraryList": {"material": -0.20},
        "wheel": {"material": -0.20},
        "pathPill": {"material": -0.20},
        "infoPill": {"material": -0.20},
        "listPills": {"material": 0.0},
        "selectedRow": {"material": -0.50},
    }


def test_glass_ui_exposes_only_material_and_previews_without_snapshot_recapture():
    settings_ui = (REPO / "debripod" / "static" / "js" / "settings-ui.js").read_text(encoding="utf-8")
    glue = (REPO / "debripod" / "static" / "js" / "liquid-glue.js").read_text(encoding="utf-8")
    css = (REPO / "debripod" / "static" / "debripod.css").read_text(encoding="utf-8")
    assert 'action:"set_glass_value:" + key + ":material"' in settings_ui
    assert "glass_section:" not in settings_ui
    assert "viewGlassElementSettings" not in settings_ui
    for retired_label in ("Glass tint", "Refraction fill", "Bevel depth", "Bevel width", "Magnification"):
        assert retired_label not in settings_ui
    assert "onPreview: async function(value)" in settings_ui
    assert "previewLiquidGlassElementMaterial" in settings_ui
    assert "corner-shape:squircle" in css
    setting_body = glue.split("function setLiquidGlassElementSetting", 1)[1].split("applyElementGlassMaterialClasses();", 1)[0]
    assert "scheduleLiquidGlassSnapshot" not in setting_body
