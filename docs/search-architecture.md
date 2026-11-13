# Unified search architecture

DebriPod has four first-class search families: Library, Torrents, Soulseek, and YouTube. All providers normalize results into the canonical `SearchResult` contract before relevance filtering, deduplication, ranking, caching, or browser rendering. Provider-specific fields stay inside `provider_data`.

## Async streaming and ordering

The aiohttp NDJSON endpoint starts Library, Soulseek, YouTube/YouTube Music, and all enabled remote torrent adapters together. Each source is ingested as soon as it answers.

Each source response produces its own status event. A timeout, rate limit, malformed response, or unavailable service affects only that source. The final event contains every canonical result and all source statuses; partial failure is not reported as a global search failure.

## Torrent identity and provenance

Torrents share `torrent:<lowercase-infohash>` identity. The incremental accumulator and final deduplicator use the same merge primitive. A duplicate from another source therefore updates the existing row in place while preserving its result ID. Merging retains every provenance label and source URL, keeps maximum seed/peer counts, ORs verification, prefers a magnet matching the canonical hash, and fills missing metadata.

Provenance labels come from exactly seven structured-data adapters: Knaben, BitSearch, Magnetz, TorLock, BT4G, TorrentClaw, and TorAPI. TorAPI detail resolution is lazy and restricted to its known upstream provider IDs.

## Network and runtime lifecycle

The aiohttp application owns one long-lived `ClientSession`. Remote torrent adapters, Last.fm, TVMaze, YouTube feeds, debrid APIs, and debrid download streaming all use it. Independent remote searches run concurrently behind a bounded semaphore. Multi-gigabyte downloads stream in chunks; local blocking libraries and SQLite maintenance are isolated from the event loop. Soulseek's aioslsk client runs on the same asyncio loop and shuts down with the application.

## Browser model

The browser keeps the complete canonical result set. A generation-safe Web Worker filters compact records, and stale worker or stale search-ID responses cannot overwrite newer state. Filtering changes `visibleIds`, never `allResults`. Virtualization limits DOM nodes rather than logical rows. The 30,000-row regressions verify canonical count, result map count, visible count without filters, and generated result-row count remain equal.

The source row is directly beneath Search history and has pills for Library, Torrents, Soulseek, and YouTube. Result pills use fixed non-clipping layouts. View changes do not run row-expansion choreography. Wheel icons reference a single inline SVG symbol sprite with one glyph layer per icon and no generated data-URI masks.
