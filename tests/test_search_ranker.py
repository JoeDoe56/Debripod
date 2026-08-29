from debripod.Library.search_ranker import infer_query_intent, rank_combined_results, score_combined_result


def _result(result_id, source, kind, title, **extra):
    return {"result_id": result_id, "source": source, "kind": kind, "title": title, "provider_data": {}, **extra}


def test_ranker_adds_scores_without_discarding_and_is_deterministic():
    rows = [
        _result("torrent:b", "torrent", "torrent", "Wonderwall Oasis", provider_data={"seeders": 50, "verified": True}),
        _result("library:a", "library", "song", "Wonderwall", artist="Oasis"),
        _result("youtube:c", "youtube", "video", "Oasis Wonderwall live"),
    ]
    first = rank_combined_results(rows, "Wonderwall Oasis")
    second = rank_combined_results(list(reversed(rows)), "Wonderwall Oasis")
    assert [row["result_id"] for row in first] == [row["result_id"] for row in second]
    assert len(first) == len(rows)
    assert all("rank_score" in row and "match_confidence" in row for row in first)
    assert first[0]["source"] == "library"


def test_intent_and_kind_quality_terms():
    intent = infer_query_intent("The Sopranos S06E02")
    assert intent["movie_show"] >= 0.9
    rows = [
        _result("torrent:a", "torrent", "torrent", "The Sopranos S06E02", provider_data={"seeders": 1}),
        _result("torrent:b", "torrent", "torrent", "The Sopranos S06E02", provider_data={"seeders": 100, "verified": True}),
    ]
    assert rank_combined_results(rows, "The Sopranos S06E02", intent=intent)[0]["result_id"] == "torrent:b"


def test_local_index_uses_exactly_the_torrent_rank_semantics():
    intent = infer_query_intent("The Sopranos S06E02")
    data = {"seeders": 12, "verified": True}
    torrent = _result("torrent:a", "torrent", "torrent", "The Sopranos S06E02", provider_data=data)
    local = _result("torrent:a", "local_index", "torrent", "The Sopranos S06E02", provider_data=data)
    assert score_combined_result(torrent, "The Sopranos S06E02", intent)["total_score"] == score_combined_result(local, "The Sopranos S06E02", intent)["total_score"]
