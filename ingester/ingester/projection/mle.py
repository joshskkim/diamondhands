"""Minor-league equivalencies (MLEs) — Phase 4.

A debutant or recent call-up has no MLB track record, so the Marcel prior reverts to
the flat league mean — the weakest projection on the board, on exactly the players whose
prop lines are softest. This module translates a minor-league line to an MLB-equivalent
one (hit rate and ISO fall, K rate rises as the level climbs) and packages it as a
synthetic prior season that ``compute_marcel_prior`` can consume, with its effective PA
discounted so the model trusts a translation less than real MLB evidence.

Pure helpers are unit-tested; the ingestion of raw minor-league lines (via the MLB Stats
API, `mlb_api.fetch_minor_league_hitting`) and the call-up wiring into refresh_priors are
the remaining (heavier, network/DB) steps.
"""
from __future__ import annotations

from dataclasses import dataclass

from ingester.projection.constants import MLE_LEVEL_FACTORS, MLE_PA_DISCOUNT
from ingester.projection.prior import SeasonLine

# MLB Stats API sportId → our level code (see MLE_LEVEL_FACTORS).
LEVEL_BY_SPORT_ID: dict[int, str] = {
    11: "AAA",
    12: "AA",
    13: "A+",
    14: "A",
    16: "R",   # Rookie
}


@dataclass(frozen=True)
class MinorLeagueLine:
    """A raw minor-league season hitting line for one player at one level."""
    level: str          # 'AAA' | 'AA' | 'A+' | 'A' | 'R'
    pa: int
    ab: int
    hits: int
    hr: int
    tb: int
    k: int


def is_supported_level(level: str) -> bool:
    return level in MLE_LEVEL_FACTORS


def translate_rates(level: str, hit_rate: float, iso: float, k_rate: float) -> tuple[float, float, float]:
    """Translate (hit_rate, iso, k_rate) to MLB-equivalent rates for ``level``.

    Hit rate and ISO are scaled down, K rate up, by the level's factors. K is capped at
    a sane ceiling. Raises KeyError for an unsupported level (call is_supported_level).
    """
    f = MLE_LEVEL_FACTORS[level]
    return (
        hit_rate * f["hit"],
        max(iso * f["iso"], 0.0),
        min(k_rate * f["k"], 0.45),
    )


def to_equivalent_season(line: MinorLeagueLine) -> SeasonLine | None:
    """Translate a minor-league line into a synthetic MLB-equivalent ``SeasonLine``.

    The counting totals are rebuilt from the translated rates over a PA-discounted sample
    (MLE_PA_DISCOUNT), so the prior both shifts toward MLB-realistic rates AND regresses
    harder (less effective evidence) than a true MLB season. xwOBA is left None — the
    minors have no Statcast xwOBA, so that component falls back to league in the prior.
    Returns None for an unsupported level or an empty line.
    """
    if not is_supported_level(line.level) or line.pa <= 0 or line.ab <= 0:
        return None

    hit_rate = line.hits / line.pa
    iso = (line.tb - line.hits) / line.ab
    k_rate = line.k / line.pa
    mlb_hit, mlb_iso, mlb_k = translate_rates(line.level, hit_rate, iso, k_rate)

    eff_pa = max(int(round(line.pa * MLE_PA_DISCOUNT)), 1)
    # Keep the line's AB/PA ratio; rebuild counting stats from the translated rates.
    ab_ratio = line.ab / line.pa
    eff_ab = max(int(round(eff_pa * ab_ratio)), 1)
    hits = int(round(mlb_hit * eff_pa))
    k = int(round(mlb_k * eff_pa))
    # ISO = (TB - H)/AB  →  extra bases = iso * AB; TB = H + extra bases.
    extra_bases = mlb_iso * eff_ab
    tb = int(round(hits + extra_bases))
    # HR isn't separately translated here; approximate from HR's share of the raw line's
    # extra-base power, capped at the translated extra-base total.
    raw_xb = max(line.tb - line.hits, 0)
    hr_share = (line.hr / raw_xb) if raw_xb > 0 else 0.0
    hr = min(int(round(hr_share * extra_bases)), max(tb - hits, 0))

    return SeasonLine(pa=eff_pa, ab=eff_ab, hits=hits, hr=hr, tb=tb, k=k, xwoba=None)
