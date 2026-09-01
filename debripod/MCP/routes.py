from __future__ import annotations

import asyncio

from aiohttp import web

from ..factory import SERVICES_KEY, json_response
from ..runtime_state import *
from ..runtime_downloads import *
from ..runtime_route_state import *
from ..storage.tasks import save_task_metadata
from ..Services.debrid import get_active_provider
from ..Services.search.pipeline import SearchPipeline
from ..Services.search.providers import SearchContext
from ..Library.search_ranker import infer_query_intent, normalize_search_text
from ..auth import UserContext, current_user
from ..storage import users as user_repository
from ..user_runtime import UserRuntime


async def _mcp_runtime(request: web.Request) -> UserRuntime:
    """Resolve an explicit owner runtime for browser or bearer MCP traffic."""
    user = current_user(request)
    if user is None:
        owner = next((item for item in user_repository.list_users() if str(item.get("role") or "") == "owner"), None)
        if owner is None:
            raise web.HTTPUnauthorized(text="No owner account is available")
        user = UserContext(str(owner.get("user_id") or ""), str(owner.get("username") or ""), "owner")
    if user.role != "owner":
        raise web.HTTPForbidden(text="MCP access requires an owner account")
    registry = request.app[SERVICES_KEY].user_runtimes
    if registry is None:
        raise RuntimeError("User runtime registry is unavailable")
    return await registry.get_user_runtime(user)

def _mcp_allowed_origins(request: web.Request) -> List[str]:
    allowed = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
    try:
        allowed.add(f"{request.scheme}://{request.host}")
    except Exception:
        pass
    return sorted(x for x in allowed if x)


def _mcp_is_loopback_host(host: str) -> bool:
    h = str(host or '').strip().lower().strip('[]')
    if not h:
        return False
    return h in {'localhost', '127.0.0.1', '::1'}


def _mcp_validate_origin(request: web.Request) -> Optional[web.Response]:
    origin = (request.headers.get('Origin') or '').strip()
    if not origin:
        return None
    if origin.lower() == 'null':
        return None
    try:
        parsed = urlparse(origin)
        norm = f"{parsed.scheme}://{parsed.netloc}"
        host = (parsed.hostname or '').strip().lower()
    except Exception:
        norm = origin
        host = ''
    if norm in _mcp_allowed_origins(request):
        return None
    if _mcp_is_loopback_host(host):
        return None
    try:
        req_host = (request.host or '').split(':', 1)[0].strip().lower()
    except Exception:
        req_host = ''
    if req_host and host and host == req_host:
        return None
    return web.Response(text='Forbidden', status=403, content_type='text/plain')


def _mcp_prune_sessions() -> None:
    now = time.time()
    with MCP_SESSIONS_LOCK:
        stale = []
        for sid, sess in list(MCP_SESSIONS.items()):
            if not isinstance(sess, dict):
                stale.append(sid)
                continue
            try:
                updated = float(sess.get('updated') or sess.get('created') or 0.0)
            except Exception:
                updated = 0.0
            if updated <= 0 or (now - updated) > MCP_SESSION_TTL_SECONDS:
                stale.append(sid)
        for sid in stale:
            MCP_SESSIONS.pop(sid, None)


def _mcp_new_session(client_info: Optional[dict] = None) -> str:
    _mcp_prune_sessions()
    sid = uuid.uuid4().hex
    with MCP_SESSIONS_LOCK:
        MCP_SESSIONS[sid] = {
            'created': time.time(),
            'updated': time.time(),
            'initialized': False,
            'client_info': dict(client_info or {}),
        }
    return sid


def _mcp_touch_session(session_id: str) -> None:
    if not session_id:
        return
    with MCP_SESSIONS_LOCK:
        sess = MCP_SESSIONS.get(session_id)
        if isinstance(sess, dict):
            sess['updated'] = time.time()


def _mcp_get_session(session_id: str) -> Optional[dict]:
    if not session_id:
        return None
    with MCP_SESSIONS_LOCK:
        sess = MCP_SESSIONS.get(session_id)
        return dict(sess) if isinstance(sess, dict) else None


def _mcp_ensure_session(session_id: str = '', client_info: Optional[dict] = None) -> str:
    sid = str(session_id or '').strip()
    if sid and _mcp_get_session(sid) is not None:
        _mcp_touch_session(sid)
        return sid
    return _mcp_new_session(client_info)


def _mcp_set_initialized(session_id: str, initialized: bool = True) -> None:
    if not session_id:
        return
    with MCP_SESSIONS_LOCK:
        sess = MCP_SESSIONS.get(session_id)
        if isinstance(sess, dict):
            sess['initialized'] = bool(initialized)
            sess['updated'] = time.time()


def _mcp_json_response(payload: Any, status: int = 200, session_id: str = '') -> web.Response:
    resp = web.json_response(payload, status=status)
    if session_id:
        resp.headers['Mcp-Session-Id'] = session_id
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


def _mcp_result(msg_id: Any, result: dict, session_id: str = '') -> web.Response:
    return _mcp_json_response({'jsonrpc': '2.0', 'id': msg_id, 'result': result}, 200, session_id=session_id)


def _mcp_error(msg_id: Any, code: int, message: str, *, data: Any = None, status: int = 400, session_id: str = '') -> web.Response:
    err = {'code': int(code), 'message': str(message)}
    if data is not None:
        err['data'] = data
    return _mcp_json_response({'jsonrpc': '2.0', 'id': msg_id, 'error': err}, status, session_id=session_id)


async def _mcp_sse_response(request: web.Request, session_id: str) -> web.StreamResponse:
    sid = _mcp_ensure_session(session_id)
    first = {
        'jsonrpc': '2.0',
        'method': 'notifications/message',
        'params': {
            'level': 'info',
            'data': {
                'server': 'debripod',
                'version': str(VERSION),
                'endpoint': '/mcp',
                'sessionId': sid,
            },
        },
    }
    response = web.StreamResponse(status=200, headers={
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
        'Mcp-Session-Id': sid,
    })
    await response.prepare(request)
    await response.write(b': connected\n\n')
    await response.write(('event: endpoint\ndata: ' + json.dumps({'path': '/mcp', 'sessionId': sid}, ensure_ascii=False) + '\n\n').encode())
    await response.write(('event: message\ndata: ' + json.dumps(first, ensure_ascii=False) + '\n\n').encode())
    try:
        while True:
            await asyncio.sleep(MCP_SSE_KEEPALIVE_SECONDS)
            _mcp_touch_session(sid)
            await response.write(b': keepalive\n\n')
    except (ConnectionResetError, asyncio.CancelledError):
        return response


def _mcp_tool_result(structured: dict, text: str, *, is_error: bool = False) -> dict:
    out = {
        'content': [{'type': 'text', 'text': str(text)}],
        'structuredContent': structured if isinstance(structured, dict) else {},
    }
    if is_error:
        out['isError'] = True
    return out


def _mcp_get_limit(args: dict, runtime: UserRuntime) -> int:
    raw = runtime.settings.get("MCP_SEARCH_RESULT_LIMIT") or MCP_SEARCH_RESULT_LIMIT
    if isinstance(args, dict) and args.get('limit') is not None:
        raw = args.get('limit')
    try:
        val = int(raw)
    except Exception:
        val = int(MCP_SEARCH_RESULT_LIMIT)
    return max(1, min(val, max(1, int(runtime.settings.get("SOULSEEK_SEARCH_MAX_RESULTS") or SOULSEEK_SEARCH_MAX_RESULTS))))


def _mcp_identifier_encode(payload: dict) -> str:
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _mcp_identifier_decode(token: str) -> dict:
    s = str(token or '').strip()
    if not s:
        raise ValueError('Missing identifier')
    pad = '=' * ((4 - (len(s) % 4)) % 4)
    raw = base64.urlsafe_b64decode((s + pad).encode('ascii'))
    js = json.loads(raw.decode('utf-8'))
    if not isinstance(js, dict):
        raise ValueError('Invalid identifier')
    return js


def _mcp_group_soulseek_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    users: Dict[str, Dict[str, Any]] = {}
    for it in items or []:
        user = str(it.get('user') or '').strip()
        rp = _slsk_norm_remote_path(str(it.get('remote_path') or ''))
        if not user or not rp:
            continue
        try:
            size = int(it.get('size') or 0)
        except Exception:
            size = 0
        try:
            speed = int(it.get('speed') or 0)
        except Exception:
            speed = 0
        parts = rp.split('\\')
        fname = parts[-1] if parts else rp
        directory = '\\'.join(parts[:-1]) if len(parts) > 1 else ''
        kind, ext, br, bd, sr, dur, vbr, codec = _slsk_guess_kind_ext_attrs(fname, it)
        u = users.get(user)
        if not u:
            u = {'user': user, 'speed': speed, 'dirs': {}, 'total_size': 0, 'total_files': 0}
            users[user] = u
        u['speed'] = max(int(u.get('speed') or 0), speed)
        dirs = u.get('dirs') or {}
        d = dirs.get(directory)
        if not d:
            d = {'directory': directory, 'files': [], 'total_size': 0, 'total_files': 0}
            dirs[directory] = d
            u['dirs'] = dirs
        d['files'].append({
            'name': fname,
            'remote_path': rp,
            'size': size,
            'kind': kind,
            'ext': ext,
            'bitrate': br,
            'bit_depth': bd,
            'sample_rate': sr,
            'duration': dur,
            'vbr': vbr,
            'codec': codec,
        })
        d['total_size'] += size
        d['total_files'] += 1
        u['total_size'] = int(u.get('total_size') or 0) + size
        u['total_files'] = int(u.get('total_files') or 0) + 1
    out: List[Dict[str, Any]] = []
    for u in users.values():
        dirs_list = list((u.get('dirs') or {}).values())
        dirs_list.sort(key=lambda d: (int(d.get('total_size') or 0), int(d.get('total_files') or 0)), reverse=True)
        out.append({
            'user': u.get('user') or '',
            'speed': int(u.get('speed') or 0),
            'dirs': dirs_list,
            'total_size': int(u.get('total_size') or 0),
            'total_files': int(u.get('total_files') or 0),
        })
    out.sort(key=lambda u: (int(u.get('speed') or 0), int(u.get('total_size') or 0), str(u.get('user') or '').lower()), reverse=True)
    return out


async def _mcp_search_torrents(query: str, limit: int, runtime: UserRuntime) -> dict:
    search_runtime = runtime.search_runtime
    pipeline = SearchPipeline([search_runtime.local_index_provider, search_runtime.torrent_provider])
    context = SearchContext(
        username=runtime.user_id,
        query=query,
        normalized_query=normalize_search_text(query),
        intent=infer_query_intent(query),
        settings=dict(runtime.settings),
        search_id="mcp:" + uuid.uuid4().hex,
    )
    response = await pipeline.search_once(query, context)
    trimmed = list(response.get('results') or [])[:limit]
    items = []
    for it in trimmed:
        provider = it.get('provider_data') or {}
        ident = _mcp_identifier_encode({
            'kind': 'torrent_item',
            'title': str(it.get('title') or 'Torrent'),
            'magnet': str(provider.get('magnet') or ''),
            'infohash': str(provider.get('infohash') or ''),
        })
        items.append({
            'identifier': ident,
            'title': str(it.get('title') or ''),
            'size': it.get('size'),
            'seeders': provider.get('seeders'),
            'leechers': provider.get('leechers'),
            'category': str(provider.get('category') or ''),
            'infohash': str(provider.get('infohash') or ''),
            'indexers': list(provider.get('indexer_labels') or []),
            'href': str(it.get('canonical_url') or ''),
        })
    return {
        'engine': 'torrents',
        'query': query,
        'limit': limit,
        'error': '',
        'results': items,
        'result_count': len(items),
    }


async def _mcp_search_soulseek(query: str, limit: int, runtime: UserRuntime) -> dict:
    svc = runtime.soulseek_service
    if not svc or not svc.is_ready():
        return {'engine': 'soulseek', 'query': query, 'limit': limit, 'results': [], 'result_count': 0, 'error': 'Soulseek service is not ready'}
    items = await svc.search_async(query)
    grouped = _mcp_group_soulseek_items(items)
    out = []
    for u in grouped:
        user = str(u.get('user') or '')
        speed = int(u.get('speed') or 0)
        for d in (u.get('dirs') or []):
            files = list(d.get('files') or [])
            directory = str(d.get('directory') or '')
            ident = _mcp_identifier_encode({
                'kind': 'slsk_dir',
                'user': user,
                'directory': directory,
                'files': [{'remote_path': str(f.get('remote_path') or ''), 'size': int(f.get('size') or 0)} for f in files if str(f.get('remote_path') or '').strip()],
            })
            out.append({
                'identifier': ident,
                'user': user,
                'directory': directory,
                'speed': speed,
                'file_count': int(d.get('total_files') or 0),
                'total_size': int(d.get('total_size') or 0),
                'sample_files': [str(f.get('name') or '') for f in files[:5]],
            })
    out.sort(key=lambda x: (int(x.get('speed') or 0), int(x.get('total_size') or 0), str(x.get('user') or '').lower()), reverse=True)
    out = out[:limit]
    return {'engine': 'soulseek', 'query': query, 'limit': limit, 'results': out, 'result_count': len(out), 'error': ''}


async def _mcp_start_debrid_download(title: str, magnet: str, http, runtime: UserRuntime) -> dict:
    if not magnet.startswith('magnet:?'):
        raise RuntimeError('Invalid magnet')
    download_dir = str(runtime.settings.get("DOWNLOAD_DIR") or "").strip()
    if not download_dir:
        raise RuntimeError('Pick the Debrid folder in Downloads settings before downloading.')
    provider = get_active_provider(runtime.settings, int(runtime.settings.get("REQUEST_TIMEOUT_SECONDS") or 25), http)
    preview = await provider.preview_magnet(magnet)
    file_ids = [item.file_id for item in preview.files]
    if not file_ids:
        raise RuntimeError('No files found in torrent')
    task_id = uuid.uuid4().hex
    task_dir = os.path.join(download_dir, sanitize_folder_name(f"{task_id[:8]}_{title}"))
    os.makedirs(task_dir, exist_ok=True)
    t = Task(
        id=task_id,
        title=title or 'Torrent',
        magnet=magnet,
        task_dir=task_dir,
        owner_user_id=runtime.user_id,
        source='debrid',
        state='queued',
        message='Queued',
        debrid_provider=provider.id,
        debrid_task_id=preview.provider_task_id,
        debrid_selected_file_ids=file_ids,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t
    save_task_metadata(t, original_result_title=title, remote_files=preview.files, selected_file_ids=file_ids, version=str(VERSION))
    asyncio.create_task(worker(task_id), name=f"debrid-download:{task_id}")
    return {'task_id': task_id, 'task_dir': task_dir, 'provider': provider.id, 'debrid_task_id': preview.provider_task_id, 'selected_file_count': len(file_ids)}


async def _mcp_start_slsk_download(user: str, directory: str, files_in: List[Dict[str, Any]], runtime: UserRuntime, title: str = '') -> dict:
    svc = runtime.soulseek_service
    if not svc or not svc.is_ready():
        raise RuntimeError('Soulseek is not configured or failed to start')
    soulseek_download_dir = str(runtime.settings.get("SOULSEEK_DOWNLOAD_DIR") or "").strip()
    task_download_dir = os.path.join(soulseek_download_dir, _slsk_sanitized_dir_name(directory))
    try:
        os.makedirs(task_download_dir, exist_ok=True)
    except Exception:
        task_download_dir = soulseek_download_dir
    files: List[Dict[str, Any]] = []
    remote_paths: List[str] = []
    for it in files_in or []:
        rp = _slsk_norm_remote_path(str((it or {}).get('remote_path') or '').strip())
        if not rp:
            continue
        try:
            sz = int((it or {}).get('size') or 0)
        except Exception:
            sz = 0
        remote_paths.append(rp)
        rel = _slsk_relative_under_directory(directory, rp)
        rel_parts = [x for x in _slsk_norm_remote_path(rel).split('\\') if x]
        local_path = os.path.join(task_download_dir, *rel_parts) if rel_parts else task_download_dir
        incoming_path = _slsk_expected_incoming_path(rp)
        files.append({
            'user': user,
            'directory': directory,
            'remote_path': rp,
            'file_id': hashlib.sha1((user + '|' + rp).encode('utf-8', 'ignore')).hexdigest()[:16],
            'name': _slsk_norm_remote_path(rp).split('\\')[-1],
            'total': sz,
            'done': 0,
            'state': 'queued',
            'state_raw': 'queued',
            'error': '',
            'paused': False,
            'canceled': False,
            'local_path': local_path,
            'incoming_path': incoming_path,
            'speed': 0.0,
        })
    if not user or not remote_paths:
        raise RuntimeError('Missing user or selected files')
    if not title:
        base = directory.split('\\')[-1] if directory else ''
        title = f"Soulseek: {user} {base}".strip()
    task_id = uuid.uuid4().hex
    t = Task(
        id=task_id,
        title=title,
        magnet='',
        task_dir=task_download_dir,
        owner_user_id=runtime.user_id,
        source='soulseek',
        state='queued',
        message='Queued',
        slsk_user=user,
        slsk_directory=directory,
        slsk_files=files,
    )
    with TASKS_LOCK:
        TASKS[task_id] = t
    save_task_metadata(t, original_result_title=title, remote_files=files, selected_file_ids=[item.get('file_id') for item in files], version=str(VERSION))
    await svc.enqueue_downloads_async(task_id, user, remote_paths)
    return {'task_id': task_id, 'task_dir': task_download_dir, 'file_count': len(remote_paths), 'user': user, 'directory': directory}


def _mcp_build_library_tree() -> dict:
    roots_out = []
    for rid, name, root_abs, mode in roots():
        tree = {'name': name, 'root_id': rid, 'path': root_abs, 'mode': mode, 'folders': []}
        index: Dict[str, dict] = {'': tree}
        for base, dirs, _files in os.walk(root_abs):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != "_debripod_cache"]
            rel_base = os.path.relpath(base, root_abs).replace('\\', '/')
            if rel_base == '.':
                rel_base = ''
            parent = index.get(rel_base)
            if parent is None:
                continue
            for d in sorted(dirs, key=lambda x: x.lower()):
                rel = f"{rel_base}/{d}".strip('/')
                node = {'name': d, 'path': rel, 'folders': []}
                parent['folders'].append(node)
                index[rel] = node
        roots_out.append(tree)
    return {'roots': roots_out}


async def _mcp_handle_tool_call(name: str, args: dict, http, runtime: UserRuntime) -> dict:
    name = str(name or '').strip()
    args = args if isinstance(args, dict) else {}
    if name == 'debripod_torrent_search':
        query = str(args.get('query') or '').strip()
        if not query:
            return _mcp_tool_result({'ok': False, 'error': 'Missing query'}, 'Error: Missing query', is_error=True)
        limit = _mcp_get_limit(args, runtime)
        data = await _mcp_search_torrents(query, limit, runtime)
        ok = not data.get('error')
        text = json.dumps(data, ensure_ascii=False, indent=2)
        data['ok'] = ok
        return _mcp_tool_result(data, text, is_error=not ok)

    if name == 'debripod_soulseek_search':
        query = str(args.get('query') or '').strip()
        if not query:
            return _mcp_tool_result({'ok': False, 'error': 'Missing query'}, 'Error: Missing query', is_error=True)
        limit = _mcp_get_limit(args, runtime)
        data = await _mcp_search_soulseek(query, limit, runtime)
        ok = not data.get('error')
        text = json.dumps(data, ensure_ascii=False, indent=2)
        data['ok'] = ok
        return _mcp_tool_result(data, text, is_error=not ok)

    if name == 'debripod_download':
        ident = str(args.get('identifier') or '').strip()
        if not ident:
            return _mcp_tool_result({'ok': False, 'error': 'Missing identifier'}, 'Error: Missing identifier', is_error=True)
        try:
            payload = _mcp_identifier_decode(ident)
        except Exception:
            return _mcp_tool_result({'ok': False, 'error': 'Invalid identifier'}, 'Error: Invalid identifier', is_error=True)
        kind = str(payload.get('kind') or '').strip().lower()
        try:
            if kind == 'slsk_dir':
                out = await _mcp_start_slsk_download(
                    str(payload.get('user') or '').strip(),
                    _slsk_norm_remote_path(str(payload.get('directory') or '').strip()),
                    payload.get('files') if isinstance(payload.get('files'), list) else [],
                    runtime,
                    str(payload.get('title') or '').strip(),
                )
                data = {'ok': True, 'source': 'soulseek', 'status': 'started', **out}
                text = f"Soulseek download started. Files are downloading to {out.get('task_dir')}."
                return _mcp_tool_result(data, text)
            if kind == 'torrent_item':
                out = await _mcp_start_debrid_download(str(payload.get('title') or 'Torrent').strip() or 'Torrent', str(payload.get('magnet') or '').strip(), http, runtime)
                data = {'ok': True, 'source': 'torrent', 'status': 'started', **out}
                text = f"Torrent download started. Files are downloading to {out.get('task_dir')}."
                return _mcp_tool_result(data, text)
            return _mcp_tool_result({'ok': False, 'error': 'Unsupported identifier type'}, 'Error: Unsupported identifier type', is_error=True)
        except Exception:
            return _mcp_tool_result({'ok': False, 'error': 'Tool call failed'}, 'Error: Tool call failed', is_error=True)

    if name == 'debripod_get_tasks':
        tasks = []
        for t in list_tasks():
            try:
                tasks.append(task_public_dict(t))
            except Exception:
                continue
        data = {'ok': True, 'tasks': tasks}
        return _mcp_tool_result(data, json.dumps(data, ensure_ascii=False, indent=2))

    if name == 'debripod_get_library':
        data = {'ok': True, **_mcp_build_library_tree()}
        return _mcp_tool_result(data, json.dumps(data, ensure_ascii=False, indent=2))

    if name == 'debripod_get_recents':
        try:
            limit = int(args.get('limit') or 20)
        except Exception:
            limit = 20
        limit = max(1, min(limit, 100))
        snap = playback_snapshot_public(runtime.playback)
        recent = list((snap.get('recent') or [])[:limit])
        data = {'ok': True, 'recent': recent, 'count': len(recent)}
        return _mcp_tool_result(data, json.dumps(data, ensure_ascii=False, indent=2))

    return _mcp_tool_result({'ok': False, 'error': 'Unknown tool: ' + name}, 'Error: Unknown tool: ' + name, is_error=True)


def _mcp_tools_list() -> List[dict]:
    return [
        {
            'name': 'debripod_torrent_search',
            'title': 'DebriPod Torrent Search',
            'description': 'Search DebriPod Local Index and enabled structured torrent APIs. Returns DebriPod download identifiers.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'},
                    'limit': {'type': 'integer', 'minimum': 1},
                },
                'required': ['query'],
            },
        },
        {
            'name': 'debripod_soulseek_search',
            'title': 'DebriPod Soulseek Search',
            'description': 'Search Soulseek directory results. Returns DebriPod download identifiers.',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'},
                    'limit': {'type': 'integer', 'minimum': 1},
                },
                'required': ['query'],
            },
        },
        {
            'name': 'debripod_download',
            'title': 'DebriPod Download',
            'description': 'Start a DebriPod download from a search result identifier. Soulseek downloads use whole directories; torrent downloads queue the whole selection.',
            'inputSchema': {
                'type': 'object',
                'properties': {'identifier': {'type': 'string'}},
                'required': ['identifier'],
            },
        },
        {
            'name': 'debripod_get_tasks',
            'title': 'DebriPod Get Tasks',
            'description': 'List current DebriPod tasks and their status.',
            'inputSchema': {'type': 'object', 'properties': {}},
        },
        {
            'name': 'debripod_get_library',
            'title': 'DebriPod Get Library',
            'description': 'Return a folder tree for every configured library root. Files are omitted.',
            'inputSchema': {'type': 'object', 'properties': {}},
        },
        {
            'name': 'debripod_get_recents',
            'title': 'DebriPod Get Recents',
            'description': 'Return recently watched and recently listened items.',
            'inputSchema': {
                'type': 'object',
                'properties': {'limit': {'type': 'integer', 'minimum': 1}},
            },
        },
    ]


async def _mcp_handle_message(msg: dict, session_id: str = '', http=None, runtime: UserRuntime | None = None) -> Tuple[Optional[dict], str, int]:
    if not isinstance(msg, dict):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}, session_id, 400
    method = str(msg.get('method') or '').strip()
    msg_id = msg.get('id')
    params = msg.get('params') if isinstance(msg.get('params'), dict) else {}
    if method == 'initialize':
        client_info = params.get('clientInfo') if isinstance(params.get('clientInfo'), dict) else {}
        requested_version = str(params.get('protocolVersion') or '').strip() or MCP_PROTOCOL_VERSION
        session_id = _mcp_ensure_session(session_id, client_info)
        result = {
            'protocolVersion': MCP_PROTOCOL_VERSION if requested_version != MCP_PROTOCOL_VERSION else requested_version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': 'debripod', 'version': str(VERSION)},
            'instructions': 'Use the search tool to get download identifiers, then pass one identifier to the download tool.',
        }
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}, session_id, 200
    if method == 'notifications/initialized':
        session_id = _mcp_ensure_session(session_id)
        _mcp_set_initialized(session_id, True)
        return None, session_id, 202
    if method == 'ping':
        session_id = _mcp_ensure_session(session_id)
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {}}, session_id, 200
    if method == 'tools/list':
        session_id = _mcp_ensure_session(session_id)
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {'tools': _mcp_tools_list()}}, session_id, 200
    if method == 'tools/call':
        session_id = _mcp_ensure_session(session_id)
        tool_name = str(params.get('name') or '').strip()
        tool_args = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
        if runtime is None:
            return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': -32001, 'message': 'User runtime unavailable'}}, session_id, 500
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': await _mcp_handle_tool_call(tool_name, tool_args, http, runtime)}, session_id, 200
    if msg_id is None:
        session_id = _mcp_ensure_session(session_id) if method else session_id
        return None, session_id, 202
    session_id = _mcp_ensure_session(session_id) if method else session_id
    return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': -32601, 'message': 'Method not found'}}, session_id, 404


async def mcp_get(request: web.Request):
    bad = _mcp_validate_origin(request)
    if bad is not None:
        return bad
    session_id = (request.headers.get('Mcp-Session-Id') or '').strip()
    return await _mcp_sse_response(request, session_id)


async def mcp_delete(request: web.Request):
    bad = _mcp_validate_origin(request)
    if bad is not None:
        return bad
    session_id = (request.headers.get('Mcp-Session-Id') or '').strip()
    if session_id:
        with MCP_SESSIONS_LOCK:
            MCP_SESSIONS.pop(session_id, None)
    return web.Response(status=204)


async def mcp_post(request: web.Request):
    bad = _mcp_validate_origin(request)
    if bad is not None:
        return bad
    try:
        body = await request.json()
    except Exception:
        return _mcp_error(None, -32700, 'Parse error', status=400)
    header_session_id = (request.headers.get('Mcp-Session-Id') or '').strip()
    runtime = await _mcp_runtime(request)
    msgs = body if isinstance(body, list) else [body]
    replies = []
    status = 200
    session_id = header_session_id
    for msg in msgs:
        reply, session_id, this_status = await _mcp_handle_message(msg, session_id=session_id, http=request.app[SERVICES_KEY].http, runtime=runtime)
        status = max(status, this_status)
        if reply is not None:
            replies.append(reply)
    if not replies:
        session_id = _mcp_ensure_session(session_id or header_session_id) if msgs else session_id
        resp = web.Response(status=202)
        if session_id:
            resp.headers['Mcp-Session-Id'] = session_id
        resp.headers['Cache-Control'] = 'no-cache'
        return resp
    payload = replies if isinstance(body, list) else replies[0]
    return _mcp_json_response(payload, status=200 if status < 400 else status, session_id=session_id)


def register_mcp_routes(app: web.Application) -> None:
    app.router.add_get('/mcp', mcp_get)
    app.router.add_delete('/mcp', mcp_delete)
    app.router.add_post('/mcp', mcp_post)


__all__ = [name for name in globals() if not name.startswith("__")]
