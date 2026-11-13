from __future__ import annotations

import asyncio

from debripod.Services.http import HttpStatusError
from debripod.Services.search.models import ProviderSearchResponse
from debripod.Services.search.pipeline import SearchPipeline
from debripod.Services.search.providers import SearchContext
from debripod.Services.torrent_search import TorrentSearchProvider
from debripod.Services.torrent_sources.base import SourcePolicy, TorrentHit


INFOHASH = "a" * 40


def context(search_id="async-search"):
    return SearchContext("user", "Example Release", "example release", {}, {}, search_id)


class Adapter:
    source_id = "knaben"
    source_label = "Knaben"
    policy = SourcePolicy()

    def __init__(self, started):
        self.started = started

    async def search(self, query, search_context):
        self.started.set()
        return [TorrentHit(self.source_id, self.source_label, "Example Release", infohash=INFOHASH, seeders=20)]


def test_torrent_sources_stream_as_soon_as_each_one_answers():
    class DelayedProvider:
        def __init__(self, provider_group, delay):
            self.provider_group = provider_group
            self.delay = delay

        async def search_stream(self, query, search_context):
            await asyncio.sleep(self.delay)
            yield ProviderSearchResponse(
                self.provider_group,
                {"source_id": self.provider_group, "status": "empty"},
                [],
            )

    class DelayedAdapter:
        source_label = "Synthetic"
        policy = SourcePolicy()

        def __init__(self, source_id, delay, infohash):
            self.source_id = source_id
            self.delay = delay
            self.infohash = infohash

        async def search(self, query, search_context):
            await asyncio.sleep(self.delay)
            return [TorrentHit(self.source_id, self.source_id.title(), "Example Release", infohash=self.infohash)]

    async def scenario():
        providers = [
            DelayedProvider("library", 0.005),
            DelayedProvider("soulseek", 0.020),
            TorrentSearchProvider(
                [
                    DelayedAdapter("knaben", 0.001, INFOHASH),
                    DelayedAdapter("torlock", 0.250, "b" * 40),
                    DelayedAdapter("torrentclaw", 0.400, "c" * 40),
                ]
            ),
            DelayedProvider("ytdlp", 0.040),
        ]
        started = asyncio.get_running_loop().time()
        timeline = []
        async for event in SearchPipeline(providers).search_stream("Example Release", context("timing")):
            timeline.append((asyncio.get_running_loop().time() - started, event))
        return timeline

    timeline = asyncio.run(scenario())
    source_events = [(elapsed, event) for elapsed, event in timeline if event["event"] == "source"]
    identities = [event["source_id"] for _elapsed, event in source_events]
    assert identities == ["knaben", "library", "soulseek", "ytdlp", "torlock", "torrentclaw"]
    knaben_time = next(elapsed for elapsed, event in source_events if event["source_id"] == "knaben")
    assert knaben_time < 0.100
    final = timeline[-1][1]
    assert final["event"] == "done"
    assert len(final["results"]) == 3
    assert sum(result["result_id"] == "torrent:" + INFOHASH for result in final["results"]) == 1


class FailedAdapter(Adapter):
    source_id = "bitsearch"
    source_label = "BitSearch"

    async def search(self, query, search_context):
        self.started.set()
        raise HttpStatusError(429, "https://example.invalid")


def test_adapter_failure_is_rate_limited_status_and_does_not_fail_done():
    async def scenario():
        started = asyncio.Event()
        provider = TorrentSearchProvider([Adapter(started), FailedAdapter(started)])
        search_context = context("partial")
        return [event async for event in SearchPipeline([provider]).search_stream("Example Release", search_context)]

    events = asyncio.run(scenario())
    assert events[-1]["event"] == "done" and len(events[-1]["results"]) == 1
    statuses = [event for event in events if event["event"] == "source"]
    assert any(event["status"] == "rate_limited" for event in statuses)


def test_cancelling_stream_cancels_pending_provider_work():
    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class SlowProvider:
            provider_group = "library"

            async def search(self, query, search_context):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        async def consume():
            async for _event in SearchPipeline([SlowProvider()]).search_stream("Example Release", context("cancel")):
                await asyncio.sleep(0)

        task = asyncio.create_task(consume())
        await started.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.wait_for(cancelled.wait(), timeout=1)

    asyncio.run(scenario())


def test_remote_adapter_concurrency_is_bounded_and_default_can_start_all_seven():
    async def run_with_limit(limit):
        active = 0
        maximum = 0
        all_started = asyncio.Event()
        release = asyncio.Event()

        class CountingAdapter:
            source_label = "Synthetic"
            policy = SourcePolicy()

            def __init__(self, number):
                self.source_id = f"source-{number}"

            async def search(self, query, search_context):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                if maximum == min(limit, 7):
                    all_started.set()
                try:
                    await release.wait()
                    return [TorrentHit(self.source_id, self.source_label, f"Example Release {self.source_id}", infohash=str(int(self.source_id.split('-')[1]) + 1).zfill(40))]
                finally:
                    active -= 1

        adapters = [CountingAdapter(number) for number in range(7)]
        search_context = context(f"bounded-{limit}")
        provider = TorrentSearchProvider(adapters, max_concurrent=limit)

        async def consume():
            return [response async for response in provider.search_stream("Example Release", search_context)]

        task = asyncio.create_task(consume())
        await asyncio.wait_for(all_started.wait(), timeout=1)
        assert maximum == min(limit, 7)
        release.set()
        responses = await task
        assert len(responses) == 7
        return maximum

    assert asyncio.run(run_with_limit(3)) == 3
    assert asyncio.run(run_with_limit(7)) == 7
