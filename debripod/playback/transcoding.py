from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import uuid
from typing import Callable, Dict, List, Optional, Tuple

from ..media_types import AUDIO_EXTS, VIDEO_EXTS
from ..paths import cache_dir, transcode_cache_dir
from ..utils import is_audio, is_video, sha1_text
from .probe import ffprobe_json, run_cmd

_audio_transcode_provider: Callable[[], str] = lambda: ""
_ffmpeg_path_provider: Callable[[], str] = lambda: ""
_video_browser_target_ext_provider: Callable[[], str] = lambda: ""


def configure_transcoding(
    *,
    audio_transcode_provider: Callable[[], str],
    ffmpeg_path_provider: Callable[[], str],
    video_browser_target_ext_provider: Callable[[], str],
) -> None:
    global _audio_transcode_provider, _ffmpeg_path_provider, _video_browser_target_ext_provider
    _audio_transcode_provider = audio_transcode_provider
    _ffmpeg_path_provider = ffmpeg_path_provider
    _video_browser_target_ext_provider = video_browser_target_ext_provider
    parse_audio_transcode_rules.cache = None  # type: ignore[attr-defined]


def _ffmpeg_path() -> str:
    return _ffmpeg_path_provider()


def _video_browser_target_ext() -> str:
    return (_video_browser_target_ext_provider() or "").lower().lstrip(".")


def parse_audio_transcode_rules() -> List[Tuple[str, str]]:
    cached = getattr(parse_audio_transcode_rules, "cache", None)
    raw = _audio_transcode_provider() or ""
    if cached and cached[0] == raw:
        return list(cached[1])

    rules = []
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        a, b = part.split(":", 1)
        a = a.strip().lower().lstrip(".")
        b = b.strip().lower().lstrip(".")
        if a and b:
            rules.append((a, b))
    parse_audio_transcode_rules.cache = (raw, tuple(rules))  # type: ignore[attr-defined]
    return rules


TRANSCODE_LOCKS: Dict[str, threading.Lock] = {}
TRANSCODE_LOCKS_GUARD = threading.Lock()


def lock_for_key(key: str) -> threading.Lock:
    with TRANSCODE_LOCKS_GUARD:
        lk = TRANSCODE_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            TRANSCODE_LOCKS[key] = lk
        return lk


FFMPEG_ENCODERS_CACHE: Optional[set] = None
FFMPEG_ENCODERS_CACHE_AT: float = 0.0
FFMPEG_ENCODERS_CACHE_TTL_SECONDS: float = 300.0


def _ffmpeg_encoders() -> set:
    global FFMPEG_ENCODERS_CACHE, FFMPEG_ENCODERS_CACHE_AT
    now = time.time()
    if FFMPEG_ENCODERS_CACHE is not None and (now - FFMPEG_ENCODERS_CACHE_AT) < FFMPEG_ENCODERS_CACHE_TTL_SECONDS:
        return FFMPEG_ENCODERS_CACHE

    code, out, _err = run_cmd([_ffmpeg_path(), "-hide_banner", "-encoders"])
    enc: set = set()
    if code == 0 and out:
        for line in (out or "").splitlines():
            line = line.strip()
            if not line or line.startswith("--") or line.startswith("Encoders:"):
                continue
            parts = line.split()
            if len(parts) >= 2 and re.match(r"^[A-Za-z0-9_]+$", parts[1]):
                enc.add(parts[1])

    FFMPEG_ENCODERS_CACHE = enc
    FFMPEG_ENCODERS_CACHE_AT = now
    return enc


def _safe_remove(p: str) -> None:
    try:
        if p and os.path.exists(p):
            os.remove(p)
    except OSError:
        pass


def ffmpeg_log_dir() -> str:
    p = os.path.join(transcode_cache_dir(), "logs")
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


_LAST_FFMPEG_LOCK = threading.Lock()
_LAST_FFMPEG_ERROR: Dict[str, str] = {}


def _cmdline_for_log(args: List[str]) -> str:
    try:
        return subprocess.list2cmdline(args)
    except Exception:
        return " ".join(args)


def _record_ffmpeg_failure(stage: str, args: List[str], code: int, out: str, err: str, src_path: str, tmp_path: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    key = sha1_text(f"{src_path}|{tmp_path}|{stage}|{ts}|{uuid.uuid4().hex}")
    log_path = os.path.join(ffmpeg_log_dir(), f"{ts}_{stage}_{key[:10]}.log")
    body = [
        f"timestamp: {ts}",
        f"stage: {stage}",
        f"src: {src_path}",
        f"tmp: {tmp_path}",
        f"exit_code: {code}",
        "",
        "command:",
        _cmdline_for_log(args),
        "",
    ]
    if out:
        body += ["stdout:", out, ""]
    if err:
        body += ["stderr:", err, ""]
    try:
        with open(log_path, "w", encoding="utf-8", errors="ignore") as f:
            f.write("\n".join(body))
    except OSError:
        log_path = ""

    with _LAST_FFMPEG_LOCK:
        _LAST_FFMPEG_ERROR.clear()
        _LAST_FFMPEG_ERROR.update(
            {
                "timestamp": ts,
                "stage": stage,
                "src": src_path,
                "tmp": tmp_path,
                "exit_code": str(code),
                "command": _cmdline_for_log(args),
                "log_path": log_path,
                "stderr_tail": (err or "")[-2000:],
            }
        )

    return log_path


def last_ffmpeg_error() -> Dict[str, str]:
    with _LAST_FFMPEG_LOCK:
        return dict(_LAST_FFMPEG_ERROR)


def _run_ffmpeg_to_tmp(args: List[str], tmp_path: str, *, stage: str, src_path: str) -> Tuple[bool, str]:
    code, out, err = run_cmd(args)
    if code == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
        return True, ""
    _safe_remove(tmp_path)
    log_path = _record_ffmpeg_failure(stage, args, code, out, err, src_path, tmp_path)
    msg = (err or "").strip() or "ffmpeg failed"
    if log_path:
        msg = msg + f"\nLog saved to: {log_path}"
    msg = msg + f"\nCache dir: {transcode_cache_dir()}"
    return False, msg


def _is_audio_ext(ext_no_dot: str) -> bool:
    e = "." + (ext_no_dot or "").lower().lstrip(".")
    return e in AUDIO_EXTS and e not in VIDEO_EXTS


def _pick_video_encoder_for_target(target_ext_no_dot: str) -> Tuple[str, List[str]]:
    target = (target_ext_no_dot or "").lower().lstrip(".")
    enc = _ffmpeg_encoders()

    if target == "webm":
        for name in ["av1_nvenc", "av1_qsv", "av1_amf"]:
            if name in enc:
                return name, []
        return "libvpx-vp9", ["-b:v", "0", "-crf", "32"]

    for name in ["h264_nvenc", "h264_qsv", "h264_amf"]:
        if name in enc:
            return name, []
    return "libx264", ["-preset", "veryfast", "-crf", "23"]


def _pick_audio_encoder_for_target(target_ext_no_dot: str) -> Tuple[str, List[str]]:
    target = (target_ext_no_dot or "").lower().lstrip(".")
    if target == "mp3":
        return "libmp3lame", ["-b:a", "192k"]
    if target in ("m4a", "mp4", "m4v", "mov", "aac"):
        return "aac", ["-b:a", "192k"]
    if target == "opus":
        return "libopus", ["-b:a", "128k"]
    if target == "ogg":
        return "libvorbis", ["-q:a", "5"]
    if target == "flac":
        return "flac", []
    if target == "wav":
        return "pcm_s16le", []
    return "aac", ["-b:a", "192k"]


def _build_transmux_args(src_path: str, target_ext_no_dot: str, tmp_path: str, *, first_audio_only: bool = False) -> List[str]:
    target = (target_ext_no_dot or "").lower().lstrip(".")
    audio_only = _is_audio_ext(target)
    args = [_ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", "-i", src_path]

    if audio_only:
        args += ["-vn", "-sn", "-dn", "-c:a", "copy", tmp_path]
        return args

    args += ["-map", "0:v:0"]
    args += ["-map", "0:a:0?"] if first_audio_only else ["-map", "0:a?"]
    args += ["-sn", "-dn", "-c", "copy"]

    if target in ("mp4", "m4v", "mov"):
        args += ["-movflags", "+faststart"]

    args += [tmp_path]
    return args


def _build_transcode_args(src_path: str, target_ext_no_dot: str, tmp_path: str) -> List[str]:
    target = (target_ext_no_dot or "").lower().lstrip(".")
    audio_only = _is_audio_ext(target)
    args = [_ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", "-i", src_path]

    if audio_only:
        aenc, aextra = _pick_audio_encoder_for_target(target)
        args += ["-vn", "-sn", "-dn", "-c:a", aenc] + aextra + [tmp_path]
        return args

    venc, vextra = _pick_video_encoder_for_target(target)
    aenc, aextra = _pick_audio_encoder_for_target("opus" if target == "webm" else "aac")

    args += ["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-c:v", venc]

    if venc == "h264_nvenc":
        args += ["-preset", "p5", "-rc", "vbr", "-cq", "23"]
    elif venc == "h264_qsv":
        args += ["-global_quality", "23"]
    elif venc == "h264_amf":
        args += ["-quality", "balanced", "-qp_i", "23", "-qp_p", "23"]
    elif venc in ("libx264", "libvpx-vp9"):
        args += vextra

    args += ["-pix_fmt", "yuv420p", "-c:a", aenc] + aextra

    if target in ("mp4", "m4v", "mov"):
        args += ["-movflags", "+faststart"]

    args += [tmp_path]
    return args


def _primary_stream_info(path: str) -> dict:
    info = {"v_codec": None, "v_pix_fmt": None, "a_codec": None}
    try:
        j = ffprobe_json(path)
    except Exception:
        return info

    streams = j.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if v:
        info["v_codec"] = (v.get("codec_name") or "").lower() or None
        info["v_pix_fmt"] = (v.get("pix_fmt") or "").lower() or None
    if a:
        info["a_codec"] = (a.get("codec_name") or "").lower() or None
    return info


def _browser_compatible_for_target(
    target_ext_no_dot: str,
    v_codec: Optional[str],
    v_pix_fmt: Optional[str],
    a_codec: Optional[str],
) -> Tuple[bool, bool]:
    target = (target_ext_no_dot or "").lower().lstrip(".")

    if _is_audio_ext(target):
        return True, True

    if target in ("mp4", "m4v", "mov"):
        video_ok = (v_codec == "h264") and (v_pix_fmt in (None, "", "yuv420p"))
        audio_ok = (a_codec is None) or (a_codec == "aac")
        return video_ok, audio_ok

    if target == "webm":
        video_ok = v_codec in (None, "", "vp8", "vp9", "av1")
        audio_ok = (a_codec is None) or (a_codec in ("opus", "vorbis"))
        return video_ok, audio_ok

    return False, False


def _build_smart_transcode_args(
    src_path: str,
    target_ext_no_dot: str,
    tmp_path: str,
    *,
    video_ok: bool,
    audio_ok: bool,
) -> List[str]:
    target = (target_ext_no_dot or "").lower().lstrip(".")
    audio_only = _is_audio_ext(target)
    args = [_ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", "-i", src_path]

    if audio_only:
        aenc, aextra = _pick_audio_encoder_for_target(target)
        args += ["-vn", "-sn", "-dn", "-c:a", aenc] + aextra + [tmp_path]
        return args

    args += ["-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]

    if video_ok:
        args += ["-c:v", "copy"]
    else:
        venc, vextra = _pick_video_encoder_for_target(target)
        args += ["-c:v", venc]
        if venc == "h264_nvenc":
            args += ["-preset", "p5", "-rc", "vbr", "-cq", "23"]
        elif venc == "h264_qsv":
            args += ["-global_quality", "23"]
        elif venc == "h264_amf":
            args += ["-quality", "balanced", "-qp_i", "23", "-qp_p", "23"]
        else:
            args += vextra
        args += ["-pix_fmt", "yuv420p"]

    if audio_ok:
        args += ["-c:a", "copy"]
    else:
        a_target = "opus" if target == "webm" else "aac"
        aenc, aextra = _pick_audio_encoder_for_target(a_target)
        args += ["-c:a", aenc] + aextra

    if target in ("mp4", "m4v", "mov"):
        args += ["-movflags", "+faststart"]

    args += [tmp_path]
    return args


def audio_transcode_if_needed(src_path: str) -> str:
    ext = os.path.splitext(src_path)[1].lower().lstrip(".")
    for a, b in parse_audio_transcode_rules():
        if ext != a:
            continue

        key = sha1_text(os.path.abspath(src_path) + "|" + a + "->" + b)
        out_path = os.path.join(transcode_cache_dir(), f"{key}.{b}")
        lk = lock_for_key(out_path)

        with lk:
            try:
                src_m = os.path.getmtime(src_path)
            except OSError:
                return src_path

            if os.path.exists(out_path):
                try:
                    out_m = os.path.getmtime(out_path)
                    if out_m >= src_m and os.path.getsize(out_path) > 0:
                        return out_path
                except OSError:
                    pass

            base_tmp, ext_tmp = os.path.splitext(out_path)
            tmp_path = base_tmp + ".tmp" + ext_tmp
            _safe_remove(tmp_path)

            transmux_args = _build_transmux_args(src_path, b, tmp_path, first_audio_only=True)
            ok1, err1 = _run_ffmpeg_to_tmp(transmux_args, tmp_path, stage="audio_transmux", src_path=src_path)
            if ok1:
                os.replace(tmp_path, out_path)
                return out_path

            _safe_remove(tmp_path)

            trans_args = _build_transcode_args(src_path, b, tmp_path)
            ok2, err2 = _run_ffmpeg_to_tmp(trans_args, tmp_path, stage="audio_transcode", src_path=src_path)
            if ok2:
                os.replace(tmp_path, out_path)
                return out_path

            raise RuntimeError((err2 or err1 or "ffmpeg failed").strip())

    return src_path


def transcode_if_needed(src_path: str) -> str:
    if is_audio(src_path):
        return audio_transcode_if_needed(src_path)

    if is_video(src_path):
        base, _ = os.path.splitext(src_path)
        cand = base + "." + _video_browser_target_ext()
        if os.path.exists(cand) and os.path.isfile(cand):
            return cand
        cand2 = base + ".browser." + _video_browser_target_ext()
        if os.path.exists(cand2) and os.path.isfile(cand2):
            return cand2
        return src_path

    return src_path
