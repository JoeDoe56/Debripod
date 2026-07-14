"""Search storage is implemented by the unified library repository for API compatibility."""

from ..Library.library_db import clear_search_cache, load_search_cache, load_search_history, record_search_history_row, save_search_cache

__all__ = ["clear_search_cache", "load_search_cache", "load_search_history", "record_search_history_row", "save_search_cache"]
