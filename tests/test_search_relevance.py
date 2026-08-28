import pytest

from debripod.Services.search.relevance import assess_match, is_clearly_unrelated, normalize_text


@pytest.mark.parametrize("title", [
    "Alice in Chains",
    "Alice in Chains Dirt",
    "Alice in Chains Live at the Moore",
    "Alice in Chains S01E02",
])
def test_alice_in_chains_related(title):
    assert not is_clearly_unrelated("Alice in Chains", {"title": title, "kind": "video"})


@pytest.mark.parametrize("result", [
    {"title": "Alice Cooper Greatest Hits"},
    {"title": "Chainsaw Repair Manual"},
    {"title": "In the Air Tonight"},
    {"title": "Unrelated", "provider_data": {"directory": r"misc\in\other"}},
])
def test_alice_in_chains_unrelated(result):
    assert is_clearly_unrelated("Alice in Chains", result)
    assert assess_match("Alice in Chains", result).code == "unrelated"


def test_structured_episode_requires_show_relation():
    assert not is_clearly_unrelated("The Sopranos S06E02", {"title": "The Sopranos S06E02 1080p"})
    assert is_clearly_unrelated("The Sopranos S06E02", {"title": "The Simpsons S06E02 1080p"})


def test_artist_title_permutations_and_single_token_boundaries():
    assert not is_clearly_unrelated("Wonderwall Oasis", {"title": "Wonderwall", "artist": "Oasis"})
    assert not is_clearly_unrelated("Oasis", {"title": "Oasis Live"})


def test_nfkd_punctuation_and_roman_normalization():
    assert normalize_text("Beyoncé: Part IV") == "beyonce part 4"
