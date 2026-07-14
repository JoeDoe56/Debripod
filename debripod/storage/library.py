from __future__ import annotations

import json
import os

from .database import database, optimize_and_vacuum


def cleanup_stale_rows(*, expired_before: float) -> dict[str, int]:
    counts: dict[str, int] = {}
    with database() as conn:
        statements = {
            "library_items": "DELETE FROM library_items WHERE deleted=1",
            "metadata_cache": "DELETE FROM metadata_cache WHERE NOT EXISTS (SELECT 1 FROM library_items i WHERE i.abs_path=metadata_cache.abs_path AND i.deleted=0)",
            "media_files": "DELETE FROM media_files WHERE NOT EXISTS (SELECT 1 FROM library_items i WHERE i.root_id=media_files.root_id AND i.rel=media_files.rel_path AND i.deleted=0)",
            "media_palettes": "DELETE FROM media_palettes WHERE root_id<>'' AND NOT EXISTS (SELECT 1 FROM library_items i WHERE i.root_id=media_palettes.root_id AND i.rel=media_palettes.rel AND i.deleted=0)",
            "video_palette_timelines": "DELETE FROM video_palette_timelines WHERE root_id<>'' AND NOT EXISTS (SELECT 1 FROM library_items i WHERE i.root_id=video_palette_timelines.root_id AND i.rel=video_palette_timelines.rel AND i.deleted=0)",
            "visualizer_analysis": "DELETE FROM visualizer_analysis WHERE root_id<>'' AND NOT EXISTS (SELECT 1 FROM library_items i WHERE i.root_id=visualizer_analysis.root_id AND i.rel=visualizer_analysis.rel AND i.deleted=0)",
            "search_cache": "DELETE FROM search_cache WHERE expires_at IS NOT NULL AND expires_at<?",
            "show_aliases": "DELETE FROM show_aliases WHERE NOT EXISTS (SELECT 1 FROM library_roots r WHERE r.root_id=show_aliases.root_id)",
        }
        for name, sql in statements.items():
            cur = conn.execute(sql, (expired_before,)) if "?" in sql else conn.execute(sql)
            counts[name] = max(0, int(cur.rowcount))
        removed_tasks = 0
        for row in conn.execute("SELECT task_id,task_dir,state_json,updated_at FROM tasks WHERE task_dir<>'' AND updated_at<?", (expired_before - 30 * 86400,)).fetchall():
            try:
                state = json.loads(row["state_json"] or "{}")
            except json.JSONDecodeError:
                state = {}
            terminal = str(state.get("state") or "") in {"done", "error", "canceled"}
            if terminal and not os.path.exists(str(row["task_dir"] or "")):
                conn.execute("DELETE FROM tasks WHERE task_id=?", (row["task_id"],))
                removed_tasks += 1
        counts["tasks"] = removed_tasks
    return counts


def finish_full_reindex() -> dict[str, object]:
    import time
    removed = cleanup_stale_rows(expired_before=time.time())
    return {"removed": removed, "maintenance": optimize_and_vacuum()}
