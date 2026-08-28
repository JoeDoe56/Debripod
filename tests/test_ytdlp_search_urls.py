from debripod.Services.ytdlp_search import YtdlpSearchProvider, youtube_music_search_url, youtube_search_url


def test_exact_category_urls_and_counts():
    calls = []

    def runner(url):
        calls.append(url)
        return []

    provider = YtdlpSearchProvider(runner)
    provider._search_youtube("Alice in Chains")
    music = [url for url in calls if url.startswith("https://music.youtube.com/")]
    ordinary = [url for url in calls if url.startswith("https://www.youtube.com/")]
    assert len(music) == 7
    assert len(ordinary) == 3
    assert youtube_music_search_url("a b", "songs") == "https://music.youtube.com/search?q=a%20b&sp=EgWKAQIIAWoMEA4QChADEAQQCRAF"
    assert youtube_music_search_url("a b", "playlists").endswith("Eg-KAQwIABAAGAAgACgBMABqChAEEAMQCRAFEAo%3D")
    assert youtube_search_url("a b", "videos") == "https://www.youtube.com/results?search_query=a%20b&sp=EgIQAQ%3D%3D"
    assert not any("ytsearch:" in url for url in calls)


def test_youtube_search_concurrency_is_bounded():
    import threading
    import time
    active = maximum = 0
    lock = threading.Lock()

    def runner(_url):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(.01)
        with lock:
            active -= 1
        return []

    YtdlpSearchProvider(runner, max_concurrent=4)._search_youtube("test")
    assert maximum <= 4
