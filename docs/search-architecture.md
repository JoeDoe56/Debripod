# Unified search architecture

DebriPod has five first-class search families: Library, Local Index, Torrents, Soulseek, and YouTube. All providers normalize results into the canonical `SearchResult` contract before relevance filtering, deduplication, ranking, caching, or browser rendering. Provider-specific fields stay inside `provider_data`.

## Async streaming and ordering

The aiohttp NDJSON endpoint starts Library, Local Index, Soulseek, YouTube/YouTube Music, and all enabled remote torrent adapters together. Library, Soulseek, and YouTube can stream independently. Remote torrent HTTP work also begins immediately, but remote torrent results cannot merge or emit until Local Index has completed and seeded the search session's shared torrent accumulator. Local Index failure or disablement always releases this barrier with an empty seed.

Each source response produces its own status event. A timeout, rate limit, malformed response, or unavailable service affects only that source. The final event contains every canonical result and all source statuses; partial failure is not reported as a global search failure.

## Torrent identity and provenance

Local and remote torrents share `torrent:<lowercase-infohash>` identity. The incremental accumulator and final deduplicator use the same merge primitive. A remote duplicate therefore updates the existing Local Index row in place while preserving its result ID. Merging retains every local and remote provenance label and source URL, keeps maximum seed/peer counts, ORs verification, prefers a magnet matching the canonical hash, and fills missing metadata.

Local provenance labels are DMM and Torrents CSV. Remote provenance labels come from exactly seven structured-data adapters: Knaben, BitSearch, Magnetz, TorLock, BT4G, TorrentClaw, and TorAPI. Torrents CSV is never called as an interactive search API. TorAPI detail resolution is lazy and restricted to its known upstream provider IDs.

## Local Index storage

Local Index is stored at `data/torrent_index.sqlite`. SQLite runs in WAL mode. Torrent v1 infohashes are validated and stored as 20-byte BLOBs with a unique constraint, while an FTS5 external-content table searches both original release names and parsed titles. Compact resolution and source-quality codes reuse DebriPod's existing release-name parser. `source_mask`, `dmm_refcount`, and `csv_present` allow either ingestion source to disappear without deleting a hash still owned by the other source.

The expected working database size is approximately 0.5–1.0 GB for a low-single-digit-million merged corpus. This is a capacity estimate; Settings exposes actual row counts, source counts, overlap, database bytes, source SHAs, and update status.

## Bootstrap, updates, and recovery

On an empty index, the DMM updater resolves the exact current `debridmediamanager/hashlists` commit, streams an archive for that immutable SHA, reads `.html` members directly from the ZIP, decodes their LZ-String `hashlist#` payloads, and commits the replacement snapshot before recording the SHA. Temporary archives are removed afterward.

Later DMM updates compare the stored SHA with GitHub. A supported linear commit range is applied oldest first. Added files increment hash ownership; removed files fetch their parent-commit contents and decrement it; modified files diff old and new hash sets. Network payloads are fetched before the SQLite mutation. The complete mutation, source SHA, success time, and Local Index generation are committed together. Missing history, non-linear history, an excessive gap, or a corrupt payload triggers an exact-SHA snapshot recovery instead of guessed changes.

Torrents CSV uses a small bare Git object store under `data/torrent_index_update/`. Bootstrap streams only top-level `torrents.csv` from an exact commit; `torrent_files.csv` is not imported. Incremental updates fetch exact old/new commits and apply a zero-context CSV diff in one transaction. If history or diff processing fails, the updater replaces only CSV ownership from the exact new snapshot, so DMM-owned rows survive.

Source SHAs and `LOCAL_INDEX_GENERATION` advance only with successful database mutations. An interrupted update rolls back both data and metadata. Interactive FTS searches continue against the last committed state while maintenance runs. Search cache keys include the Local Index generation, enabled top-level settings, fixed remote-source selection, and library generations, so successfully ingested data becomes visible immediately.

## Network and runtime lifecycle

The aiohttp application owns one long-lived `ClientSession`. Remote torrent adapters, DMM GitHub ingestion, Last.fm, TVMaze, YouTube feeds, debrid APIs, and debrid download streaming all use it. Independent remote searches run concurrently behind a bounded semaphore. Multi-gigabyte downloads and DMM archives stream in chunks; local blocking libraries and Git/SQLite maintenance are isolated from the event loop. Soulseek's aioslsk client runs on the same asyncio loop and shuts down with the application.

## Browser model

The browser keeps the complete canonical result set. A generation-safe Web Worker filters compact records, and stale worker or stale search-ID responses cannot overwrite newer state. Filtering changes `visibleIds`, never `allResults`. Virtualization limits DOM nodes rather than logical rows. The 30,000-row regressions verify canonical count, result map count, visible count without filters, and generated result-row count remain equal.

The source row is directly beneath Search history and has pills for Library, Local Index, Torrents, Soulseek, and YouTube. Result pills use fixed non-clipping layouts. View changes do not run row-expansion choreography. Wheel icons reference a single inline SVG symbol sprite with one glyph layer per icon and no generated data-URI masks.
