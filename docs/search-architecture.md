# Unified search architecture

DebriPod keeps Flask and Requests and divides search into provider, processing, and UI layers. The provider layer runs Library, Soulseek, Torrents, and yt-dlp concurrently. The visible `source` remains `library`, `soulseek`, `torrent`, `youtube`, or `soundcloud`; a provider group is ownership and scheduling, not a display source.

## Canonical result contract

Every provider returns the same top-level fields before filtering, ranking, caching, or rendering: stable identity, provider group, visible source and labels, kind and kind label, title metadata, URL and stable source ID, search/filter metadata, confidence and rank, browse/stream/download flags, file summary, files, and `provider_data`. Provider-specific values never become new top-level fields. Library navigation, Soulseek user/directory, torrent hashes/magnets/indexers, YouTube IDs, and SoundCloud IDs/permalinks live in `provider_data`.

## Processing boundaries

YouTube Music categories are processed before ordinary YouTube categories, so their video, playlist, and channel identities win. Later duplicates may only fill empty metadata. SoundCloud never participates in YouTube or cross-provider deduplication. Torrents merge only by lowercase info hash, or by exactly equal canonical magnet identity when no hash exists; merged rows retain all indexer IDs, labels, and source URLs.

The relevance gate is provider independent. It normalizes Unicode and punctuation, removes format noise, understands years and season/episode structure, and combines exact token boundaries, weighted coverage, and a secondary fuzzy score. It rejects only clearly unrelated rows. Ranking happens after that gate and never imposes a total result cap.

## Cardigann and challenge handling

The Cardigann layer validates definitions, renders templates and supported filters, creates Requests calls, parses HTML or JSON, resolves downloads, persists cookies/status, applies retries and backoff, and isolates per-indexer failures. Enabled indexers search concurrently. A browser fallback is eligible only after positive anti-bot challenge detection—not empty results, selector errors, DNS failures, authentication errors, or malformed definitions. Browser discovery starts with the operating-system default, uses an isolated DebriPod profile, and uses no extension.

Tracked definitions are split between `indexer-definitions/official` and `indexer-definitions/custom`. Staging downloads and validates into `data/indexer-definitions/staging` without changing active files. Activation backs up active official files, replaces official definitions, preserves custom overrides, and updates the manifest. Rollback restores the last exact backup; discard removes staging only.

Private indexers are deliberately not configured yet. Definition metadata already exposes required setting fields, and the settings UI routes such definitions to a detail page that reports setup is required. Future password and cookie values must use DebriPod's secret store, not ordinary JSON settings.

## Browser performance model

The browser retains the full canonical result set and sends compact filter records to a Web Worker. The existing text filter row supports free text plus source, type, indexer, and media qualifiers. Search results and file rows are fixed at 76 pixels; status and filter rows are fixed at 56 pixels. Prefix heights are keyed by item-array version, row-height revision, and count, and visible bounds use binary search with ten-row overscan. Fixed rows are not measured, large mutations do not animate individual rows, and only the virtual window is present in the DOM. The automated 30,000-row test asserts fewer than 140 rendered rows.
