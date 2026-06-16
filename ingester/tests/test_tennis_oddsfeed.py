"""Tennis odds-feed helpers: name normalization/matching and h2h parsing."""
from ingester.tennis.oddsfeed import (
    is_grand_slam,
    match_player,
    normalize_name,
    parse_h2h,
)


def test_normalize_strips_accents_and_punctuation():
    assert normalize_name("Stefanos Tsitsipás") == "stefanos tsitsipas"
    assert normalize_name("Alex de Minaur") == "alex de minaur"
    assert normalize_name("J.J. Wolf") == "j j wolf"


def test_match_player_exact_and_fuzzy():
    index = {
        "carlos alcaraz": "A0E2",
        "jannik sinner": "S0AG",
        "stefanos tsitsipas": "TE51",
    }
    assert match_player("Carlos Alcaraz", index) == "A0E2"
    # Accented / transliterated variant still resolves.
    assert match_player("Stefanos Tsitsipás", index) == "TE51"
    # A clearly different name does not false-match.
    assert match_player("Roger Federer", index) is None


def test_is_grand_slam():
    assert is_grand_slam("ATP Roland Garros")
    assert is_grand_slam("ATP US Open")
    assert not is_grand_slam("ATP Halle")
    assert not is_grand_slam(None)


def test_parse_h2h_computes_decimal_and_implied():
    event = {
        "bookmakers": [
            {"key": "dk", "last_update": "2026-06-16T15:30:00Z", "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Carlos Alcaraz", "price": 120},
                    {"name": "Jannik Sinner", "price": -145},
                ]},
            ]},
        ]
    }
    rows = parse_h2h(event)
    assert len(rows) == 2
    alc = next(r for r in rows if r["player_name"] == "Carlos Alcaraz")
    assert alc["bookmaker"] == "dk"
    assert abs(alc["price_decimal"] - 2.20) < 1e-6      # +120 -> 2.20
    assert abs(alc["implied_prob"] - 0.4545) < 1e-3     # 100/220
