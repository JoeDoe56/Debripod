from __future__ import annotations

from . import runtime_state as _state
from .runtime_state import *  # noqa: F401,F403
from .runtime_video_post import *  # noqa: F401,F403
from .runtime_debrid_downloads import *  # noqa: F401,F403
from .runtime_youtube_downloads import *  # noqa: F401,F403


configure_task_manager(
    soulseek_service_provider=lambda: _state.SOULSEEK_SERVICE,
    retry_worker_provider=lambda source: (
        youtube_download_remaining_worker if source == "youtube"
        else debrid_download_remaining_worker if source == "debrid"
        else None
    ),
)

__all__ = [name for name in globals() if not name.startswith("__")]
