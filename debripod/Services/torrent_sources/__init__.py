from .base import SourcePolicy, SourceUnavailable, TorrentHit, TorrentSourceAdapter
from .bitsearch import BitSearchAdapter
from .bt4g import BT4GAdapter
from .knaben import KnabenAdapter
from .magnetz import MagnetzAdapter
from .torapi import TorAPIAdapter
from .torlock import TorLockAdapter
from .torrentclaw import TorrentClawAdapter

ADAPTER_TYPES = (
    KnabenAdapter,
    BitSearchAdapter,
    MagnetzAdapter,
    TorLockAdapter,
    BT4GAdapter,
    TorrentClawAdapter,
    TorAPIAdapter,
)

__all__ = [
    "ADAPTER_TYPES", "BT4GAdapter", "BitSearchAdapter", "KnabenAdapter", "MagnetzAdapter",
    "SourcePolicy", "SourceUnavailable", "TorAPIAdapter", "TorLockAdapter", "TorrentClawAdapter",
    "TorrentHit", "TorrentSourceAdapter",
]
