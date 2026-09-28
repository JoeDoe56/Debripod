from __future__ import annotations

import os
import re
import shutil
from typing import Any, Callable, Dict, List, Optional, Tuple

from .roots import safe_path_join
from ..media_types import (
    PLAYLISTS_FOLDER_NAME,
    SMART_PLAYLISTS_FOLDER_NAME,
    SMART_PLAYLIST_MEDIA_FILENAME,
    SMART_PLAYLIST_RULES_FILENAME,
    SMART_PLAYLIST_RULES_TEMPLATE,
)
from ..utils import is_audio, is_video, is_playlist_file, sha1_text

_file_meta_provider: Callable[[str], dict] = lambda _path: {}
_track_sort_key_provider: Callable[[str], Tuple[int, str]] = lambda track: (10**9, str(track or ""))
_is_loved_provider: Callable[[str, str, str], bool] = lambda _artist, _title, _album: False
_get_index_provider: Callable[[str], Optional[dict]] = lambda _root_id: None
_build_index_provider: Callable[[str], dict] = lambda _root_abs: {"tracks": [], "videos": []}
_set_index_provider: Callable[[str, dict], None] = lambda _root_id, _data: None


def configure_playlists(
    *,
    file_meta_provider: Callable[[str], dict],
    track_sort_key_provider: Callable[[str], Tuple[int, str]],
    is_loved_provider: Callable[[str, str, str], bool],
    get_index_provider: Callable[[str], Optional[dict]],
    build_index_provider: Callable[[str], dict],
    set_index_provider: Callable[[str, dict], None],
) -> None:
    global _file_meta_provider, _track_sort_key_provider, _is_loved_provider
    global _get_index_provider, _build_index_provider, _set_index_provider
    _file_meta_provider = file_meta_provider
    _track_sort_key_provider = track_sort_key_provider
    _is_loved_provider = is_loved_provider
    _get_index_provider = get_index_provider
    _build_index_provider = build_index_provider
    _set_index_provider = set_index_provider


def file_meta_cached(abs_path: str) -> dict:
    return _file_meta_provider(abs_path)


def track_sort_key(track_s: str) -> Tuple[int, str]:
    return _track_sort_key_provider(track_s)


def lastfm_is_loved(artist: str, title: str, album: str) -> bool:
    return bool(_is_loved_provider(artist, title, album))


def get_index(root_id: str) -> Optional[dict]:
    return _get_index_provider(root_id)


def build_index_for_root(root_abs: str) -> dict:
    return _build_index_provider(root_abs)


def _playlist_rel_from_abs(root_abs: str, abs_path: str) -> Optional[str]:
    try:
        ap = os.path.abspath(abs_path)
        root_abs = os.path.abspath(root_abs)
        common = os.path.commonpath([root_abs, ap])
        if common != root_abs:
            return None
        rel = os.path.relpath(ap, root_abs).replace('\\', '/')
        return '' if rel == '.' else rel
    except Exception:
        return None


def _playlist_resolve_entry(root_abs: str, playlist_abs: str, entry: str) -> Optional[str]:
    raw = str(entry or '').strip().strip('"').strip("'")
    if not raw:
        return None
    low = raw.lower()
    if low.startswith('http://') or low.startswith('https://') or low.startswith('file://'):
        return None

    candidates: List[str] = []
    if os.path.isabs(raw):
        candidates.append(raw)
    else:
        try:
            candidates.append(os.path.join(os.path.dirname(playlist_abs), raw))
        except Exception:
            pass
        try:
            candidates.append(os.path.join(root_abs, raw))
        except Exception:
            pass

    seen = set()
    for cand in candidates:
        try:
            cand_abs = os.path.abspath(cand)
        except Exception:
            continue
        if cand_abs in seen:
            continue
        seen.add(cand_abs)
        if not os.path.exists(cand_abs) or not os.path.isfile(cand_abs):
            continue
        if not (is_audio(cand_abs) or is_video(cand_abs)):
            continue
        rel = _playlist_rel_from_abs(root_abs, cand_abs)
        if rel:
            return rel
    return None


def scan_root_playlists(root_abs: str) -> List[dict]:
    out: List[dict] = []
    seen = set()
    root_norm = os.path.abspath(root_abs)
    std_root = os.path.join(root_norm, PLAYLISTS_FOLDER_NAME)
    smart_root = os.path.join(root_norm, SMART_PLAYLISTS_FOLDER_NAME)

    if os.path.isdir(std_root):
        try:
            for dirpath, dirnames, filenames in os.walk(std_root):
                dirnames.sort(key=lambda x: x.lower())
                for fn in sorted(filenames, key=lambda x: x.lower()):
                    ap = os.path.join(dirpath, fn)
                    if not is_playlist_file(ap):
                        continue
                    rel = _playlist_rel_from_abs(root_abs, ap)
                    if not rel or rel in seen:
                        continue
                    seen.add(rel)
                    out.append(
                        {
                            'kind': 'playlist',
                            'label': os.path.splitext(fn)[0] or fn,
                            'rel': rel,
                            'badge': os.path.splitext(fn)[1].lower().lstrip('.'),
                            'smart': False,
                        }
                    )
        except Exception:
            pass

    if os.path.isdir(smart_root):
        try:
            for entry in sorted(os.listdir(smart_root), key=lambda x: x.lower()):
                subdir = os.path.join(smart_root, entry)
                if not os.path.isdir(subdir):
                    continue
                playlist_abs = os.path.join(subdir, SMART_PLAYLIST_MEDIA_FILENAME)
                rules_abs = os.path.join(subdir, SMART_PLAYLIST_RULES_FILENAME)
                if not os.path.isfile(playlist_abs):
                    continue
                rel = _playlist_rel_from_abs(root_abs, playlist_abs)
                if not rel or rel in seen:
                    continue
                seen.add(rel)
                out.append(
                    {
                        'kind': 'playlist',
                        'label': entry,
                        'rel': rel,
                        'badge': 'Smart',
                        'smart': True,
                        'rules_rel': _playlist_rel_from_abs(root_abs, rules_abs) or '',
                    }
                )
        except Exception:
            pass

    out.sort(key=lambda x: (str(x.get('label') or '').lower(), str(x.get('rel') or '').lower()))
    return out


def playlist_tracks_for_root(root_abs: str, playlist_rel: str) -> List[dict]:
    if is_smart_playlist_rel(playlist_rel):
        try:
            root_id = sha1_text(os.path.abspath(root_abs))
        except Exception:
            root_id = ''
        return smart_playlist_tracks_for_root(root_abs, playlist_rel, root_id)
    try:
        playlist_abs = safe_path_join(root_abs, playlist_rel)
    except ValueError:
        return []
    if not os.path.exists(playlist_abs) or not os.path.isfile(playlist_abs) or not is_playlist_file(playlist_abs):
        return []

    ext = os.path.splitext(playlist_abs)[1].lower()
    raw_entries: List[str] = []
    try:
        with open(playlist_abs, 'r', encoding='utf-8-sig', errors='ignore') as f:
            lines = f.read().splitlines()
    except Exception:
        folder_abs, playlist_abs, _, _ = _resolve_smart_playlist_parts(root_abs, playlist_rel)
        if playlist_abs:
            try:
                _write_playlist_entries(playlist_abs, [], root_abs)
            except Exception:
                pass
        return []

    if ext in {'.m3u', '.m3u8'}:
        for line in lines:
            s = (line or '').strip()
            if not s or s.startswith('#'):
                continue
            raw_entries.append(s)
    elif ext == '.pls':
        for line in lines:
            s = (line or '').strip()
            if not s:
                continue
            m = re.match(r'(?i)file\d+\s*=\s*(.+)$', s)
            if m:
                raw_entries.append((m.group(1) or '').strip())

    items: List[dict] = []
    seen = set()
    num = 0
    for entry in raw_entries:
        rel = _playlist_resolve_entry(root_abs, playlist_abs, entry)
        if not rel or rel in seen:
            continue
        seen.add(rel)
        num += 1
        try:
            abs_track = safe_path_join(root_abs, rel)
        except ValueError:
            continue
        label = os.path.splitext(os.path.basename(abs_track))[0] or os.path.basename(abs_track) or 'Track'
        badge = str(num)
        try:
            meta = file_meta_cached(abs_track)
            if isinstance(meta, dict):
                label = (meta.get('title') or meta.get('name') or label)
                if meta.get('track'):
                    badge = str(meta.get('track'))
        except Exception:
            pass
        items.append({'kind': 'file' if is_video(abs_track) else 'track', 'media': 'video' if is_video(abs_track) else 'audio', 'label': label, 'rel': rel, 'badge': badge})

    return items


def _normalize_new_playlist_name(name: str) -> str:
    s = str(name or '').strip()
    if not s:
        return ''
    s = re.sub(r'[\\/:*?\"<>|\x00-\x1f]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip().rstrip('.')
    if not s:
        return ''
    base, _ = os.path.splitext(s)
    s = (base or s).strip().rstrip('.')
    if not s:
        return ''
    return s + '.m3u8'



def create_root_playlist(root_abs: str, name: str) -> Tuple[bool, str, Dict[str, Any]]:
    filename = _normalize_new_playlist_name(name)
    if not filename:
        return False, 'Enter a playlist name', {}

    folder_abs = os.path.join(root_abs, PLAYLISTS_FOLDER_NAME)
    try:
        os.makedirs(folder_abs, exist_ok=True)
    except Exception as e:
        return False, f'Failed to create playlist folder: {e}', {}

    playlist_abs = os.path.abspath(os.path.join(folder_abs, filename))
    try:
        common = os.path.commonpath([os.path.abspath(root_abs), playlist_abs])
        if common != os.path.abspath(root_abs):
            return False, 'Invalid playlist path', {}
    except Exception:
        return False, 'Invalid playlist path', {}

    if os.path.exists(playlist_abs):
        rel_existing = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
        label_existing = os.path.splitext(os.path.basename(playlist_abs))[0] or os.path.basename(playlist_abs) or 'Playlist'
        return False, 'Playlist already exists', {'rel': rel_existing, 'label': label_existing}

    body = '#EXTM3U\n'
    try:
        with open(playlist_abs, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
    except Exception as e:
        return False, f'Failed to create playlist: {e}', {}

    rel = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
    label = os.path.splitext(os.path.basename(playlist_abs))[0] or os.path.basename(playlist_abs) or 'Playlist'
    return True, '', {'rel': rel, 'label': label, 'folder': PLAYLISTS_FOLDER_NAME}


def _normalize_playlist_stem(name: str) -> str:
    s = str(name or '').strip()
    if not s:
        return ''
    s = re.sub(r'[\/:*?"<>|\x00-\x1f]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip().rstrip('.')
    if not s:
        return ''
    base, _ = os.path.splitext(s)
    return (base or s).strip().rstrip('.')


def _resolve_playlist_abs(root_abs: str, playlist_rel: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        playlist_abs = safe_path_join(root_abs, playlist_rel)
    except Exception:
        return None, 'Invalid playlist path'
    if not os.path.exists(playlist_abs) or not os.path.isfile(playlist_abs) or not is_playlist_file(playlist_abs):
        return None, 'Playlist not found'
    return playlist_abs, None


def _playlist_rel_entries(root_abs: str, playlist_rel: str) -> List[str]:
    items = playlist_tracks_for_root(root_abs, playlist_rel)
    out: List[str] = []
    seen = set()
    for it in items:
        rel = str((it or {}).get('rel') or '').strip().replace('\\', '/')
        if not rel or rel in seen:
            continue
        seen.add(rel)
        out.append(rel)
    return out


def _write_playlist_entries(playlist_abs: str, rels: List[str], root_abs: Optional[str] = None) -> None:
    ext = os.path.splitext(playlist_abs)[1].lower()
    clean: List[str] = []
    seen = set()
    playlist_dir = os.path.dirname(os.path.abspath(playlist_abs))
    root_abs_norm = os.path.abspath(root_abs) if root_abs else None
    for rel in rels:
        rp = str(rel or '').strip().replace('\\', '/')
        if not rp or rp in seen:
            continue
        seen.add(rp)
        out_rel = rp
        if root_abs_norm:
            try:
                abs_track = safe_path_join(root_abs_norm, rp)
                out_rel = os.path.relpath(abs_track, playlist_dir).replace('\\', '/')
            except Exception:
                out_rel = rp
        clean.append(out_rel)
    if ext == '.pls':
        lines = ['[playlist]']
        for idx, rel in enumerate(clean, 1):
            title = os.path.splitext(os.path.basename(rel))[0] or f'Track {idx}'
            lines.append(f'File{idx}={rel}')
            lines.append(f'Title{idx}={title}')
            lines.append(f'Length{idx}=-1')
        lines.append(f'NumberOfEntries={len(clean)}')
        lines.append('Version=2')
        body = '\n'.join(lines) + '\n'
    else:
        body = '\n'.join(['#EXTM3U'] + clean) + '\n'
    with open(playlist_abs, 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)


def rename_root_playlist(root_abs: str, playlist_rel: str, name: str) -> Tuple[bool, str, Dict[str, Any]]:
    stem = _normalize_playlist_stem(name)
    if not stem:
        return False, 'Enter a playlist name', {}
    playlist_abs, err = _resolve_playlist_abs(root_abs, playlist_rel)
    if not playlist_abs:
        return False, str(err or 'Playlist not found'), {}
    ext = os.path.splitext(playlist_abs)[1] or '.m3u8'
    new_abs = os.path.abspath(os.path.join(os.path.dirname(playlist_abs), stem + ext))
    try:
        common = os.path.commonpath([os.path.abspath(root_abs), new_abs])
        if common != os.path.abspath(root_abs):
            return False, 'Invalid playlist path', {}
    except Exception:
        return False, 'Invalid playlist path', {}
    if os.path.normcase(new_abs) == os.path.normcase(playlist_abs):
        rel_same = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
        label_same = os.path.splitext(os.path.basename(playlist_abs))[0] or os.path.basename(playlist_abs) or 'Playlist'
        return True, '', {'rel': rel_same, 'label': label_same}
    if os.path.exists(new_abs):
        rel_existing = _playlist_rel_from_abs(root_abs, new_abs) or ''
        label_existing = os.path.splitext(os.path.basename(new_abs))[0] or os.path.basename(new_abs) or 'Playlist'
        return False, 'Playlist already exists', {'rel': rel_existing, 'label': label_existing}
    try:
        os.replace(playlist_abs, new_abs)
    except Exception as e:
        return False, f'Failed to rename playlist: {e}', {}
    rel_new = _playlist_rel_from_abs(root_abs, new_abs) or ''
    label_new = os.path.splitext(os.path.basename(new_abs))[0] or os.path.basename(new_abs) or 'Playlist'
    return True, '', {'rel': rel_new, 'label': label_new}


def add_tracks_to_playlist(root_abs: str, playlist_rel: str, rels: List[str]) -> Tuple[bool, str, Dict[str, Any]]:
    playlist_abs, err = _resolve_playlist_abs(root_abs, playlist_rel)
    if not playlist_abs:
        return False, str(err or 'Playlist not found'), {}
    existing = _playlist_rel_entries(root_abs, playlist_rel)
    added = 0
    for rel in rels or []:
        rp = str(rel or '').strip().replace('\\', '/')
        if not rp:
            continue
        try:
            abs_track = safe_path_join(root_abs, rp)
        except Exception:
            continue
        if not os.path.exists(abs_track) or not os.path.isfile(abs_track) or not (is_audio(abs_track) or is_video(abs_track)):
            continue
        if rp not in existing:
            existing.append(rp)
            added += 1
    if added <= 0:
        return False, 'No songs added', {'added': 0}
    try:
        _write_playlist_entries(playlist_abs, existing, root_abs)
    except Exception as e:
        return False, f'Failed to update playlist: {e}', {'added': 0}
    return True, '', {'added': added}


def remove_tracks_from_playlist(root_abs: str, playlist_rel: str, rels: List[str]) -> Tuple[bool, str, Dict[str, Any]]:
    playlist_abs, err = _resolve_playlist_abs(root_abs, playlist_rel)
    if not playlist_abs:
        return False, str(err or 'Playlist not found'), {}
    remove_set = {str(rel or '').strip().replace('\\', '/') for rel in (rels or []) if str(rel or '').strip()}
    existing = _playlist_rel_entries(root_abs, playlist_rel)
    kept = [rel for rel in existing if rel not in remove_set]
    removed = max(0, len(existing) - len(kept))
    if removed <= 0:
        return False, 'No songs removed', {'removed': 0}
    try:
        _write_playlist_entries(playlist_abs, kept, root_abs)
    except Exception as e:
        return False, f'Failed to update playlist: {e}', {'removed': 0}
    return True, '', {'removed': removed}




def delete_root_playlist(root_abs: str, playlist_rel: str) -> Tuple[bool, str, Dict[str, Any]]:
    rel = str(playlist_rel or '').strip().replace('\\', '/')
    if not rel:
        return False, 'Playlist not found', {}

    if is_smart_playlist_rel(rel):
        folder_abs, playlist_abs, rules_abs, _ = _resolve_smart_playlist_parts(root_abs, rel)
        if not folder_abs or not playlist_abs or not rules_abs:
            return False, 'Smart playlist not found', {}
        try:
            common = os.path.commonpath([os.path.abspath(root_abs), os.path.abspath(folder_abs)])
            if common != os.path.abspath(root_abs):
                return False, 'Invalid playlist path', {}
        except Exception:
            return False, 'Invalid playlist path', {}
        try:
            shutil.rmtree(folder_abs)
        except Exception as e:
            return False, f'Failed to delete playlist: {e}', {}
        return True, '', {'smart': True}

    playlist_abs, err = _resolve_playlist_abs(root_abs, rel)
    if not playlist_abs:
        return False, str(err or 'Playlist not found'), {}
    try:
        common = os.path.commonpath([os.path.abspath(root_abs), os.path.abspath(playlist_abs)])
        if common != os.path.abspath(root_abs):
            return False, 'Invalid playlist path', {}
    except Exception:
        return False, 'Invalid playlist path', {}
    try:
        os.remove(playlist_abs)
    except Exception as e:
        return False, f'Failed to delete playlist: {e}', {}
    return True, '', {'smart': False}


def _smart_playlist_dir_from_name(root_abs: str, name: str) -> Tuple[Optional[str], str, str]:
    stem = _normalize_playlist_stem(name)
    if not stem:
        return None, '', 'Enter a playlist name'
    folder_abs = os.path.join(root_abs, SMART_PLAYLISTS_FOLDER_NAME, stem)
    return folder_abs, stem, ''


def _default_smart_playlist_rules(name: str) -> str:
    stem = _normalize_playlist_stem(name) or 'Playlist'
    body = SMART_PLAYLIST_RULES_TEMPLATE.replace("[any|all]", "[all]")
    body = re.sub(r'^\[name\]\s*$', f'[{stem}]', body, count=1, flags=re.MULTILINE)
    return body


def is_smart_playlist_rel(playlist_rel: str) -> bool:
    rel = str(playlist_rel or '').replace('\\', '/').strip('/')
    low = rel.lower()
    pref = SMART_PLAYLISTS_FOLDER_NAME.lower() + '/'
    return bool(low == SMART_PLAYLISTS_FOLDER_NAME.lower() or low.startswith(pref))


def _resolve_smart_playlist_parts(root_abs: str, playlist_rel: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    try:
        playlist_abs = safe_path_join(root_abs, playlist_rel)
    except Exception:
        return None, None, None, None
    if not os.path.isfile(playlist_abs):
        return None, None, None, None
    folder_abs = os.path.dirname(playlist_abs)
    rules_abs = os.path.join(folder_abs, SMART_PLAYLIST_RULES_FILENAME)
    if not os.path.isfile(rules_abs):
        return None, None, None, None
    rel = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
    rules_rel = _playlist_rel_from_abs(root_abs, rules_abs) or ''
    return folder_abs, playlist_abs, rules_abs, rules_rel


def create_root_smart_playlist(root_abs: str, name: str) -> Tuple[bool, str, Dict[str, Any]]:
    folder_abs, stem, err = _smart_playlist_dir_from_name(root_abs, name)
    if not folder_abs:
        return False, err, {}
    playlist_abs = os.path.join(folder_abs, SMART_PLAYLIST_MEDIA_FILENAME)
    rules_abs = os.path.join(folder_abs, SMART_PLAYLIST_RULES_FILENAME)
    try:
        common = os.path.commonpath([os.path.abspath(root_abs), os.path.abspath(folder_abs)])
        if common != os.path.abspath(root_abs):
            return False, 'Invalid playlist path', {}
    except Exception:
        return False, 'Invalid playlist path', {}
    if os.path.exists(folder_abs):
        rel_existing = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
        return False, 'Playlist already exists', {'rel': rel_existing, 'label': stem, 'smart': True}
    try:
        os.makedirs(folder_abs, exist_ok=True)
        with open(rules_abs, 'w', encoding='utf-8', newline='\n') as f:
            f.write(_default_smart_playlist_rules(stem))
        with open(playlist_abs, 'w', encoding='utf-8', newline='\n') as f:
            f.write('#EXTM3U\n')
    except Exception as e:
        return False, f'Failed to create smart playlist: {e}', {}
    rel = _playlist_rel_from_abs(root_abs, playlist_abs) or ''
    return True, '', {'rel': rel, 'label': stem, 'folder': SMART_PLAYLISTS_FOLDER_NAME, 'smart': True}


def load_smart_playlist_rules(root_abs: str, playlist_rel: str) -> Tuple[bool, str, Dict[str, Any]]:
    folder_abs, playlist_abs, rules_abs, rules_rel = _resolve_smart_playlist_parts(root_abs, playlist_rel)
    if not rules_abs:
        return False, 'Smart playlist not found', {}
    try:
        with open(rules_abs, 'r', encoding='utf-8-sig', errors='ignore') as f:
            body = f.read()
    except Exception as e:
        return False, f'Failed to read rules: {e}', {}
    label = os.path.basename(folder_abs) if folder_abs else 'Smart Playlist'
    return True, '', {'text': body, 'rel': _playlist_rel_from_abs(root_abs, playlist_abs) or playlist_rel, 'rules_rel': rules_rel or '', 'label': label}


def save_smart_playlist_rules(root_abs: str, playlist_rel: str, text: str) -> Tuple[bool, str, Dict[str, Any]]:
    folder_abs, playlist_abs, rules_abs, rules_rel = _resolve_smart_playlist_parts(root_abs, playlist_rel)
    if not rules_abs:
        return False, 'Smart playlist not found', {}
    body = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    if not body.endswith('\n'):
        body += '\n'
    try:
        with open(rules_abs, 'w', encoding='utf-8', newline='\n') as f:
            f.write(body)
    except Exception as e:
        return False, f'Failed to save rules: {e}', {}
    try:
        smart_playlist_tracks_for_root(root_abs, playlist_rel)
    except Exception:
        pass
    label = os.path.basename(folder_abs) if folder_abs else 'Smart Playlist'
    return True, '', {'rel': _playlist_rel_from_abs(root_abs, playlist_abs) or playlist_rel, 'rules_rel': rules_rel or '', 'label': label}


def _smart_rule_values(raw: str) -> List[str]:
    out: List[str] = []
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', raw or ''):
        try:
            out.append(bytes(m.group(1), 'utf-8').decode('unicode_escape'))
        except Exception:
            out.append(m.group(1))
    if out:
        return out
    inner = str(raw or '').strip()
    if inner.startswith('(') and inner.endswith(')'):
        inner = inner[1:-1]
    for part in inner.split(','):
        part = str(part or '').strip().strip('"').strip("'")
        if part:
            out.append(part)
    return out


def _parse_smart_rule_line(line: str) -> Optional[Dict[str, Any]]:
    s = str(line or '').strip()
    if not s:
        return None
    if s.startswith('#'):
        s = s[1:].strip()
        active = False
    else:
        active = True
    m = re.match(r'(?i)^([a-z_]+)(?:\((is|not)\))?\s*=\s*(\(.*\))\s*$', s)
    if not m:
        return None
    field = (m.group(1) or '').strip().lower()
    op = (m.group(2) or '').strip().lower()
    vals = _smart_rule_values(m.group(3) or '')
    if field == 'liked':
        vv = str(vals[0] if vals else '').strip().lower()
        if vv not in ('true', 'false', '1', '0', 'yes', 'no'):
            return None
        vals = ['true' if vv in ('true', '1', 'yes') else 'false']
    return {'type': 'rule', 'active': active, 'field': field, 'op': op or ('is' if field != 'liked' else ''), 'values': vals}


def _parse_smart_block(lines: List[str], idx: int) -> Tuple[Optional[Dict[str, Any]], int]:
    mode = 'any'
    while idx < len(lines):
        raw = lines[idx]
        s = str(raw or '').strip()
        if not s:
            idx += 1
            continue
        if s.startswith('#'):
            test = s[1:].strip()
        else:
            test = s
        m = re.match(r'^\[?(any|all)\]?\s*\{\s*$', test, re.I)
        if not m:
            return None, idx
        mode = (m.group(1) or 'any').lower()
        active = not s.startswith('#')
        idx += 1
        break
    node = {'type': 'group', 'mode': mode, 'active': active, 'items': []}
    while idx < len(lines):
        raw = lines[idx]
        s = str(raw or '').strip()
        if not s:
            idx += 1
            continue
        if s == '}':
            idx += 1
            return node, idx
        test = s[1:].strip() if s.startswith('#') else s
        if re.match(r'^\[?(any|all)\]?\s*\{\s*$', test, re.I):
            child, idx = _parse_smart_block(lines, idx)
            if child:
                node['items'].append(child)
            else:
                idx += 1
            continue
        rule = _parse_smart_rule_line(s)
        if rule:
            node['items'].append(rule)
        idx += 1
    return node, idx


def parse_smart_playlist_rules_text(text: str) -> Dict[str, Any]:
    lines = str(text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    idx = 0
    name = ''
    while idx < len(lines):
        s = str(lines[idx] or '').strip()
        if not s:
            idx += 1
            continue
        m = re.match(r'^\[(.*)\]\s*$', s)
        if m:
            name = (m.group(1) or '').strip()
            idx += 1
        break
    group, _ = _parse_smart_block(lines, idx)
    if not group:
        raise RuntimeError('Invalid smart playlist rules')
    return {'name': name, 'root': group}


def _smart_text_value(v: Any) -> str:
    return str(v or '').strip().lower()


def _smart_folder_match(track_rel: str, folder_rule: str) -> bool:
    rel = '/' + str(track_rel or '').replace('\\', '/').lstrip('/')
    folder = '/' + str(folder_rule or '').replace('\\', '/').strip()
    folder = '/' + folder.strip('/') if folder.strip('/') else '/'
    if folder == '/':
        return True
    base = folder.rstrip('/')
    return rel == base or rel.startswith(base + '/')


def _smart_rule_match(rule: Dict[str, Any], track: Dict[str, Any]) -> bool:
    field = str(rule.get('field') or '').lower()
    values = list(rule.get('values') or [])
    op = str(rule.get('op') or 'is').lower()
    if field == 'liked':
        want = str(values[0] if values else 'false').strip().lower() == 'true'
        got = False
        try:
            got = lastfm_is_loved(str(track.get('artist') or ''), str(track.get('title') or ''), str(track.get('album') or ''))
        except Exception:
            got = False
        return got == want
    if field == 'folder':
        got_rel = str(track.get('rel') or '')
        matched = any(_smart_folder_match(got_rel, v) for v in values) if values else False
        return (not matched) if op == 'not' else matched
    track_val = ''
    if field == 'artist':
        track_val = _smart_text_value(track.get('artist'))
    elif field == 'albumartist':
        track_val = _smart_text_value(track.get('album_artist') or track.get('artist'))
    elif field == 'album':
        track_val = _smart_text_value(track.get('album'))
    elif field == 'genre':
        track_val = _smart_text_value(track.get('genre'))
    else:
        return False
    vals = {_smart_text_value(v) for v in values if str(v or '').strip()}
    matched = track_val in vals if vals else False
    return (not matched) if op == 'not' else matched


def _smart_group_match(node: Dict[str, Any], track: Dict[str, Any]) -> bool:
    if not node:
        return False
    if not bool(node.get('active', True)):
        return False

    results: List[bool] = []
    for item in node.get('items') or []:
        if not bool(item.get('active', True)):
            continue
        if item.get('type') == 'group':
            results.append(_smart_group_match(item, track))
        elif item.get('type') == 'rule':
            results.append(_smart_rule_match(item, track))

    # If nothing is active in this group, it matches nothing.
    if not results:
        return False

    return any(results) if str(node.get('mode') or 'any').lower() == 'any' else all(results)


def smart_playlist_tracks_for_root(root_abs: str, playlist_rel: str, root_id: str = '') -> List[dict]:
    ok, err, info = load_smart_playlist_rules(root_abs, playlist_rel)
    if not ok:
        return []
    text = str((info or {}).get('text') or '')
    try:
        parsed = parse_smart_playlist_rules_text(text)
    except Exception:
        folder_abs, playlist_abs, _, _ = _resolve_smart_playlist_parts(root_abs, playlist_rel)
        if playlist_abs:
            try:
                _write_playlist_entries(playlist_abs, [], root_abs)
            except Exception:
                pass
        return []
    data = get_index(root_id) if root_id else None
    if data is None:
        data = build_index_for_root(root_abs)
        if root_id:
            _set_index_provider(root_id, data)
    tracks = list((data or {}).get('tracks') or []) + list((data or {}).get('videos') or [])
    matched = [t for t in tracks if _smart_group_match(parsed.get('root') or {}, t)]
    matched.sort(key=lambda x: track_sort_key(x.get('track') or '') + ((x.get('artist') or '').lower(), (x.get('album') or '').lower(), (x.get('title') or x.get('name') or '').lower()))
    items: List[dict] = []
    for idx, t in enumerate(matched, 1):
        rel = str(t.get('rel') or '').strip().replace('\\', '/')
        if not rel:
            continue
        label = str(t.get('title') or t.get('name') or os.path.splitext(os.path.basename(rel))[0] or 'Track')
        badge = str(t.get('track') or idx)
        items.append({'kind': 'file' if is_video(rel) else 'track', 'media': 'video' if is_video(rel) else 'audio', 'label': label, 'rel': rel, 'badge': badge})
    folder_abs, playlist_abs, _, _ = _resolve_smart_playlist_parts(root_abs, playlist_rel)
    if playlist_abs:
        try:
            _write_playlist_entries(playlist_abs, [str(t.get('rel') or '') for t in matched], root_abs)
        except Exception:
            pass
    return items
