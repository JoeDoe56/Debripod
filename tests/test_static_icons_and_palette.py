from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from debripod.Library import metadata
from debripod.Routes.icons import register_icon_routes, ICON_VERSION


ROOT = Path(__file__).resolve().parents[1]
STATIC_ICONS = ROOT / "debripod" / "static" / "icons"


def _png_dimensions(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    assert raw[12:16] == b"IHDR"
    return struct.unpack(">II", raw[16:24])


def test_committed_icon_assets_have_expected_formats_and_sizes():
    expected = {16, 32, 180, 192, 512}
    for size in expected:
        assert _png_dimensions(STATIC_ICONS / f"icon-{size}.png") == (size, size)
    assert (STATIC_ICONS / "favicon.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_generated_icons_match_the_current_svg_source():
    record = json.loads((STATIC_ICONS / "app-icon-assets.json").read_text())
    assert hashlib.sha256((ROOT / record["source"]).read_text(encoding="utf-8").encode()).hexdigest() == record["sha256"]
    for name, expected in record["assets"].items():
        assert hashlib.sha256((STATIC_ICONS / name).read_bytes()).hexdigest() == expected


def test_app_icon_wheel_is_centered_below_screen():
    svg = ET.parse(ROOT / "icons/debripod-app-icon.svg").getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}
    body, screen, _ = svg.findall(".//svg:rect", ns)
    wheel, center = svg.findall(".//svg:circle", ns)
    screen_bottom = float(screen.attrib["y"]) + float(screen.attrib["height"])
    body_bottom = float(body.attrib["y"]) + float(body.attrib["height"])
    cy, radius = float(wheel.attrib["cy"]), float(wheel.attrib["r"])
    assert cy - radius - screen_bottom == body_bottom - cy - radius
    assert center.attrib["cy"] == wheel.attrib["cy"]


def test_icon_routes_serve_static_immutable_assets_and_png_manifest():
    async def scenario() -> None:
        app = web.Application()
        register_icon_routes(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            for path in ("/favicon.ico", "/apple-touch-icon.png", "/icon-192.png", "/icon-512.png"):
                response = await client.get(path)
                assert response.status == 200
                assert response.headers["Cache-Control"] == "no-cache"
                await response.read()
                response = await client.get(path + "?v=" + ICON_VERSION)
                assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
                await response.read()

            response = await client.get("/site.webmanifest")
            manifest = await response.json(content_type=None)
            assert [icon["src"].split("?", 1)[0] for icon in manifest["icons"]] == [
                "/icon-192.png",
                "/icon-512.png",
            ]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_palette_extraction_decodes_one_small_rgb24_frame_with_ffmpeg(monkeypatch):
    pixels = bytes([240, 30, 20] * 8 + [20, 80, 220] * 3)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=pixels, stderr=b"")

    monkeypatch.setattr(metadata.subprocess, "run", fake_run)
    palette = metadata._extract_palette_from_image("cover.png")

    assert palette and palette["version"] == metadata.PALETTE_ALGORITHM_VERSION
    assert [240, 30, 20] in palette["colors"]
    args, kwargs = calls[0]
    assert args[args.index("-vf") + 1] == "scale=48:48:force_original_aspect_ratio=decrease"
    assert args[-3:] == ["-pix_fmt", "rgb24", "pipe:1"]
    assert kwargs["timeout"] == 30


def test_wheel_uses_repository_svg_assets_and_no_generated_image_markup():
    shell = (ROOT / "debripod" / "static" / "shell.html").read_text(encoding="utf-8")
    css = (ROOT / "debripod" / "static" / "debripod.css").read_text(encoding="utf-8")
    now_playing = (ROOT / "debripod" / "static" / "js" / "now-playing-ui.js").read_text(encoding="utf-8")
    wheel_icons = (ROOT / "debripod" / "static" / "js" / "wheel-icons.js").read_text(encoding="utf-8")

    for symbol in ("forward.end.alt.fill", "backward.end.alt.fill", "heart.fill", "playpause.fill", "gobackward.15", "goforward.15"):
        assert symbol in wheel_icons
    for filename in ("forward-end-alt-fill.svg", "backward-end-alt-fill.svg", "heart.svg", "heart-fill.svg", "playpause.svg", "playpause-fill.svg"):
        assert (ROOT / "debripod/static/icons/sf" / filename).is_file()
    assert 'file:"shuffleinactivefull-fixed",legacy:true' in wheel_icons
    assert 'file:"shuffleactivefull-fixed",legacy:true' in wheel_icons
    wheel_label_lines = [line for line in shell.splitlines() if 'class="wheelLabel ' in line]
    assert len(wheel_label_lines) == 4
    assert all('class="wheelIcon"' in line and "--wheel-icon-mask:url(" in line and "<img " not in line for line in wheel_label_lines)
    wheel_update = now_playing[now_playing.index("function setWheelLabel"):now_playing.index("function adjustSeekPreview")]
    forbidden = ("data:image", "base64,", "mask-image", "innerHTML", "replaceChildren", "createElement")
    assert all(token not in wheel_update for token in forbidden)
    assert all(token not in wheel_icons for token in forbidden)
    assert ".wheelLabel .menuWord[hidden]" in css
    assert ".wheelLabel .wheelIcon[hidden]" in css
    assert "display:none !important" in css
