"""analyze-picks: read-only CLV / pick diagnostics over settled model_picks.

The track record's headline CLV (clvN/clvRate/avgClv in /api/track-record) is computed
on a mismatched de-vig basis: bet-time fair_prob came from OddsService's best-of-books
de-vig, while score-picks de-vigs the close from the pick's single book (_closing_quote
docstring acknowledges this). Best-of-books inflates the bet-time fair, so stored CLV
carries a systematic negative offset. This command quantifies that artifact (--verify
recomputes CLV on a consistent single-book basis at both ends), classifies why picks
are missing CLV (line moved off our number / one-sided at close / no snapshot), and
slices the record by market / book / tier / edge bucket / timing.

Diagnosis only: reads model_picks + odds_snapshots, writes nothing. Unit/ROI math
mirrors TrackRecordService (flat 1u: win = decimal-1, loss = -1, push = 0, void
excluded), so the headline row here must match /api/track-record on the same window.
"""
from __future__ import annotations

import argparse
import math
import statistics
from datetime import timedelta
from zoneinfo import ZoneInfo

from ingester.db import eastern_today, get_connection
from ingester.commands.picks import (
    LONGSHOT_EDGE,
    STRONG_EDGE,
    _OPPOSITE_SIDE,
    _devig_two_way,
)

_EASTERN = ZoneInfo("America/New_York")

# Slices with fewer picks than this get a low-sample flag (CIs are printed regardless).
LOW_N = 30
# |clv| below this is treated as a tie for sign-coherence purposes (4dp storage noise).
CLV_EPS = 0.002


# ── pure helpers (unit-tested, no DB) ────────────────────────────────────────

def american_to_decimal(american: int) -> float:
    """American → decimal odds. +150 → 2.50, −120 → 1.833 (mirrors TrackRecordService)."""
    return 1.0 + american / 100.0 if american > 0 else 1.0 + 100.0 / -american


def classify_outcome(won: bool | None, result_value) -> str:
    """'win' | 'loss' | 'push' | 'void' — same disambiguation as TrackRecordService:
    won NULL with an actual result_value is a push; without one it's a void."""
    if won is not None:
        return "win" if won else "loss"
    return "push" if result_value is not None else "void"


def units_for(outcome: str, price_american: int) -> float:
    if outcome == "win":
        return american_to_decimal(price_american) - 1.0
    if outcome == "loss":
        return -1.0
    return 0.0


def edge_bucket(edge: float) -> str:
    """Bucket a pick's recorded model−fair edge.

    Bucket boundaries are the PRE-July-2026 bar thresholds (MIN_EDGE .04 /
    STRONG_EDGE .06 / LONGSHOT_EDGE .08 / MAX_EDGE .15) kept as literals on
    purpose: the settled record spans both regimes, and these cuts keep the
    historical slices comparable. The live bar is now MIN_EDGE .06 / MAX_EDGE
    .125 (see commands/picks.py)."""
    if edge < 0.04:
        return "<.04"
    if edge < STRONG_EDGE:
        return "[.04,.06)"
    if edge < LONGSHOT_EDGE:
        return "[.06,.08)"
    if edge <= 0.15:
        return "[.08,.15]"
    return ">.15"


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson 95% interval for a proportion; None when n == 0."""
    if n == 0:
        return None
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def mean_ci95(values: list[float]) -> tuple[float, float, float] | None:
    """(mean, lo, hi) normal-approx 95% CI; None when empty. Zero half-width at n=1."""
    if not values:
        return None
    m = statistics.fmean(values)
    if len(values) < 2:
        return m, m, m
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return m, m - half, m + half


def classify_miss(clv, close_price_american, had_any_line_quote: bool) -> str:
    """Why a settled pick has no CLV.

    'captured'   — it does have CLV.
    'one_sided'  — a closing quote existed at our line but the opposite side didn't
                   (close_price_american stored, clv NULL — _closing_quote's partial return).
    'line_moved' — our exact line never appeared in odds_snapshots at the pick's book
                   pre-pitch, but the selection did at other lines: the book moved the
                   number (or snapshot cadence missed our line). These are the systematic
                   exclusions that bias stored CLV — line moves ARE the big CLV events.
    'no_quote'   — no snapshot for the selection at the book at any line (coverage gap,
                   or book/market dropped before close, or pick has no book).
    """
    if clv is not None:
        return "captured"
    if close_price_american is not None:
        return "one_sided"
    return "line_moved" if had_any_line_quote else "no_quote"


def shown_cohort(first_shown_at) -> str:
    """'morning' (the 9am ET daily board) vs 'intraday' (the */30 12-23 quick loop)."""
    if first_shown_at is None:
        return "unknown"
    return "morning" if first_shown_at.astimezone(_EASTERN).hour < 12 else "intraday"


def hours_to_close_bucket(first_shown_at, start_time) -> str:
    """Exposure window: pick first shown → first pitch (the close is just before it)."""
    if first_shown_at is None or start_time is None:
        return "unknown"
    hours = (start_time - first_shown_at).total_seconds() / 3600.0
    if hours < 3:
        return "<3h"
    if hours < 6:
        return "3-6h"
    if hours < 12:
        return "6-12h"
    return "12h+"


def quartile_labels(n: int) -> list[int]:
    """Quartile index (0..3) for each rank position 0..n-1, sizes as even as possible."""
    if n == 0:
        return []
    base, extra = divmod(n, 4)
    out: list[int] = []
    for q in range(4):
        out.extend([q] * (base + (1 if q < extra else 0)))
    return out


def clv_histogram(clvs: list[float], width: float = 0.01,
                  lo: float = -0.05, hi: float = 0.05) -> list[tuple[str, int]]:
    """Fixed-width bins over [lo, hi) with outlier bins on both ends."""
    nbins = round((hi - lo) / width)
    counts = [0] * nbins
    below = above = 0
    for v in clvs:
        if v < lo:
            below += 1
        elif v >= hi:
            above += 1
        else:
            counts[min(int((v - lo) / width), nbins - 1)] += 1
    out = [(f"<{lo:+.2f}", below)]
    out += [(f"[{lo + i * width:+.2f},{lo + (i + 1) * width:+.2f})", counts[i])
            for i in range(nbins)]
    out.append((f">={hi:+.2f}", above))
    return out


# ── slice accumulator (mirror of TrackRecordService.Acc + CLV stats) ─────────

class SliceAcc:
    def __init__(self, label: str) -> None:
        self.label = label
        self.wins = self.losses = self.pushes = 0
        self.units = 0.0
        self.clvs: list[float] = []
        self.clv_null = 0

    def add(self, outcome: str, units: float, clv) -> None:
        if outcome == "win":
            self.wins += 1
        elif outcome == "loss":
            self.losses += 1
        else:
            self.pushes += 1
        self.units += units
        if clv is None:
            self.clv_null += 1
        else:
            self.clvs.append(clv)

    @property
    def n(self) -> int:
        return self.wins + self.losses + self.pushes

    def row(self) -> list[str]:
        decided = self.wins + self.losses
        win_pct = f"{self.wins / decided:.1%}" if decided else "—"
        roi = f"{self.units / self.n * 100:+.1f}%" if self.n else "—"
        cn = len(self.clvs)
        if cn:
            avg = statistics.fmean(self.clvs)
            beat = sum(1 for c in self.clvs if c > 0)
            tie = sum(1 for c in self.clvs if c == 0)
            ci = wilson_ci(beat, cn)
            clv_cols = [str(cn), f"{avg:+.4f}", f"{beat / cn:.0%}",
                        f"{(beat + tie) / cn:.0%}",
                        f"[{ci[0]:.0%},{ci[1]:.0%}]"]
        else:
            clv_cols = ["0", "—", "—", "—", "—"]
        flag = " (n<%d)" % LOW_N if self.n < LOW_N else ""
        return [self.label + flag, str(self.n),
                f"{self.wins}-{self.losses}-{self.pushes}", win_pct,
                f"{self.units:+.2f}", roi, *clv_cols, str(self.clv_null)]


SLICE_HEADERS = ["slice", "n", "W-L-P", "win%", "units", "ROI",
                 "clvN", "avgCLV", "beat%", "beat/tie%", "beat95CI", "noCLV"]


def emit_table(headers: list[str], rows: list[list[str]], md: bool) -> None:
    if md:
        print("| " + " | ".join(headers) + " |")
        print("|" + "|".join("---" for _ in headers) + "|")
        for r in rows:
            print("| " + " | ".join(r) + " |")
    else:
        widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h)
                  for i, h in enumerate(headers)]
        print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
        for r in rows:
            print("  ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
    print()


# ── DB access ────────────────────────────────────────────────────────────────

def _scope(market: str) -> str:
    return "prop" if market in ("hit", "hr") else "game"


def _fetch_settled(conn, since):
    lotto = "mp.lotto" if _has_lotto_column(conn) else "FALSE"
    rows = conn.execute(
        f"""
        SELECT mp.id, mp.slate_date, mp.game_id, mp.market, mp.side, mp.line,
               mp.player_id, mp.model_prob, mp.fair_prob, mp.edge, mp.price_american,
               mp.book, mp.strong, {lotto} AS lotto, mp.recorded_at, mp.first_shown_at,
               mp.result_value, mp.won, mp.close_price_american, mp.close_price_decimal,
               mp.close_fair_prob, mp.clv, mp.clv_captured_at, g.start_time_utc
        FROM model_picks mp
        JOIN games g ON g.id = mp.game_id
        WHERE mp.scored_at IS NOT NULL AND mp.slate_date >= %s
        ORDER BY mp.slate_date, mp.rank NULLS LAST, mp.first_shown_at
        """,
        (since,),
    ).fetchall()
    cols = ["id", "slate_date", "game_id", "market", "side", "line", "player_id",
            "model_prob", "fair_prob", "edge", "price_american", "book", "strong",
            "lotto", "recorded_at", "first_shown_at", "result_value", "won",
            "close_price_american", "close_price_decimal", "close_fair_prob",
            "clv", "clv_captured_at", "start_time_utc"]
    picks = []
    for r in rows:
        p = dict(zip(cols, r))
        for k in ("model_prob", "fair_prob", "edge", "line", "close_price_decimal",
                  "close_fair_prob", "clv"):
            if p[k] is not None:
                p[k] = float(p[k])
        p["outcome"] = classify_outcome(p["won"], p["result_value"])
        p["units"] = units_for(p["outcome"], p["price_american"])
        picks.append(p)
    return picks


def _has_lotto_column(conn) -> bool:
    return conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'model_picks' AND column_name = 'lotto'
        )
        """
    ).fetchone()[0]


def _had_any_line_quote(conn, p) -> bool:
    """Did odds_snapshots hold the selection at the pick's book at ANY line pre-pitch?
    Distinguishes 'line moved off our number' from a plain coverage gap."""
    if p["book"] is None:
        return False
    row = conn.execute(
        """
        SELECT 1 FROM odds_snapshots
        WHERE game_id = %s AND scope = %s AND player_id IS NOT DISTINCT FROM %s
          AND market = %s AND side = %s AND LOWER(bookmaker) = LOWER(%s)
          AND captured_at < %s
        LIMIT 1
        """,
        (p["game_id"], _scope(p["market"]), p["player_id"], p["market"],
         p["side"], p["book"], p["start_time_utc"]),
    ).fetchone()
    return row is not None


def _bettime_samebook_fair(conn, p) -> float | None:
    """De-vigged fair prob at the pick's own book as of bet time (first_shown_at,
    falling back to recorded_at) — the consistent-basis counterpart of close_fair_prob.
    None when the snapshot history lacks a two-sided quote at our line by then."""
    bet_ts = p["first_shown_at"] or p["recorded_at"]
    if p["book"] is None or bet_ts is None:
        return None
    ts_row = conn.execute(
        """
        SELECT MAX(captured_at) FROM odds_snapshots
        WHERE game_id = %s AND scope = %s AND player_id IS NOT DISTINCT FROM %s
          AND market = %s AND side = %s AND line IS NOT DISTINCT FROM %s
          AND LOWER(bookmaker) = LOWER(%s) AND captured_at <= %s
        """,
        (p["game_id"], _scope(p["market"]), p["player_id"], p["market"], p["side"],
         p["line"], p["book"], bet_ts),
    ).fetchone()
    captured_at = ts_row[0] if ts_row else None
    if captured_at is None:
        return None
    rows = conn.execute(
        """
        SELECT side, price_decimal FROM odds_snapshots
        WHERE game_id = %s AND scope = %s AND player_id IS NOT DISTINCT FROM %s
          AND market = %s AND LOWER(bookmaker) = LOWER(%s)
          AND line IS NOT DISTINCT FROM %s AND captured_at = %s
        """,
        (p["game_id"], _scope(p["market"]), p["player_id"], p["market"], p["book"],
         p["line"], captured_at),
    ).fetchall()
    prices = {r[0]: float(r[1]) for r in rows}
    opp = _OPPOSITE_SIDE.get(p["side"])
    if p["side"] not in prices or opp is None or opp not in prices:
        return None
    return _devig_two_way(prices[p["side"]], prices[opp])


# ── report sections ──────────────────────────────────────────────────────────

def _section(title: str, md: bool) -> None:
    print(f"## {title}\n" if md else f"── {title} " + "─" * max(0, 60 - len(title)))


def _coverage(conn, picks, md: bool) -> None:
    _section("CLV coverage & miss taxonomy", md)
    accs = {k: SliceAcc(k) for k in ("captured", "one_sided", "line_moved", "no_quote")}
    for p in picks:
        cls = classify_miss(p["clv"], p["close_price_american"],
                            _had_any_line_quote(conn, p) if p["clv"] is None
                            and p["close_price_american"] is None else False)
        p["miss_class"] = cls
        accs[cls].add(p["outcome"], p["units"], p["clv"])
    rows = [a.row() for a in accs.values() if a.n > 0]
    emit_table(SLICE_HEADERS, rows, md)
    excluded = [p for p in picks if p["miss_class"] != "captured"]
    if excluded:
        eu = sum(p["units"] for p in excluded)
        print(f"Selection bias check: {len(excluded)} settled picks carry NO CLV "
              f"(units {eu:+.2f}). 'line_moved' rows are the worrying cohort — line "
              f"moves are the largest CLV events and they are systematically excluded "
              f"from the stored number.\n")


def _verify(conn, picks, md: bool) -> None:
    _section("Verification: consistent-basis CLV recompute (H1)", md)
    stored: list[float] = []
    consistent: list[float] = []
    unmatched = 0
    for p in picks:
        if p["clv"] is None:
            continue
        bt_fair = _bettime_samebook_fair(conn, p)
        if bt_fair is None or p["close_fair_prob"] is None:
            unmatched += 1
            continue
        p["clv_consistent"] = round(p["close_fair_prob"] - bt_fair, 4)
        stored.append(p["clv"])
        consistent.append(p["clv_consistent"])
    if not stored:
        print("No CLV'd pick could be re-based (no same-book bet-time snapshots).\n")
        return
    rows = []
    for label, vals in (("stored (mixed basis)", stored),
                        ("consistent (single-book both ends)", consistent)):
        m, lo, hi = mean_ci95(vals)
        beat = sum(1 for v in vals if v > 0)
        tie = sum(1 for v in vals if v == 0)
        wci = wilson_ci(beat, len(vals))
        rows.append([label, str(len(vals)), f"{m:+.4f}",
                     f"[{lo:+.4f},{hi:+.4f}]", f"{statistics.median(vals):+.4f}",
                     f"{beat / len(vals):.0%}", f"{(beat + tie) / len(vals):.0%}",
                     f"[{wci[0]:.0%},{wci[1]:.0%}]"])
    emit_table(["basis", "n", "mean", "mean95CI", "median", "beat%", "beat/tie%",
                "beat95CI"], rows, md)
    deltas = [c - s for s, c in zip(stored, consistent)]
    m, lo, hi = mean_ci95(deltas)
    print(f"Basis offset (consistent − stored): mean {m:+.4f} [{lo:+.4f},{hi:+.4f}] — "
          f"this is the de-vig-basis artifact baked into every stored clv value.")
    if unmatched:
        print(f"({unmatched} CLV'd picks had no same-book bet-time snapshot; excluded.)")
    print()

    # H2: sign composition of the stored numbers.
    _section("Verification: stored CLV sign mass (H2)", md)
    clvs = [p["clv"] for p in picks if p["clv"] is not None]
    pos = sum(1 for c in clvs if c > 0)
    zero = sum(1 for c in clvs if c == 0)
    neg = sum(1 for c in clvs if c < 0)
    print(f"clv > 0: {pos}   clv = 0: {zero}   clv < 0: {neg}   "
          f"(clvRate counts strictly > 0; ties deflate it)\n")
    emit_table(["clv bin", "count"],
               [[b, str(c)] for b, c in clv_histogram(clvs) if c > 0], md)

    # Sign coherence vs the raw same-book price move (no de-vig involved).
    _section("Verification: sign coherence vs raw price move", md)
    agree = disagree = ties = 0
    for p in picks:
        if p["clv"] is None or p["close_price_decimal"] is None:
            continue
        if abs(p["clv"]) < CLV_EPS:
            ties += 1
            continue
        raw_move = 1.0 / p["close_price_decimal"] \
            - 1.0 / american_to_decimal(p["price_american"])
        if raw_move == 0:
            ties += 1
        elif (raw_move > 0) == (p["clv"] > 0):
            agree += 1
        else:
            disagree += 1
    print(f"agree {agree} / disagree {disagree} / tie-ish {ties} — disagreements are "
          f"where the cross-book vig basis flips the sign of a same-book move.\n")

    # Hand-verifiable dump of the 5 most recent CLV'd picks.
    _section("Verification: 5 most recent CLV'd picks, end to end", md)
    recent = [p for p in picks if p["clv"] is not None][-5:]
    for p in recent:
        cons = p.get("clv_consistent")
        print(f"{p['slate_date']} {p['market']} {p['side']} {p['line']} "
              f"@{p['book']} {p['price_american']:+d}"
              f"{f' player={p['player_id']}' if p['player_id'] else ''}\n"
              f"    bet fair(best-of-books)={p['fair_prob']:.4f}  "
              f"close {p['close_price_american']:+d} "
              f"fair(same-book)={p['close_fair_prob']:.4f}  "
              f"stored clv={p['clv']:+.4f}"
              + (f"  consistent clv={cons:+.4f}" if cons is not None else ""))
    print()


def _slices(picks, md: bool) -> None:
    def run(title: str, key) -> None:
        _section(f"By {title}", md)
        accs: dict[str, SliceAcc] = {}
        for p in picks:
            k = key(p)
            accs.setdefault(k, SliceAcc(k)).add(p["outcome"], p["units"], p["clv"])
        ordered = sorted(accs.values(), key=lambda a: -a.n)
        emit_table(SLICE_HEADERS, [a.row() for a in ordered], md)

    run("market", lambda p: p["market"])
    run("book", lambda p: p["book"] or "?")
    run("tier", lambda p: "Lotto" if p["lotto"] else "Strong" if p["strong"] else "Standard")
    run("edge bucket", lambda p: edge_bucket(p["edge"]))
    run("first-shown cohort (H4)", lambda p: shown_cohort(p["first_shown_at"]))
    run("pick-to-pitch window (H4)",
        lambda p: hours_to_close_bucket(p["first_shown_at"], p["start_time_utc"]))


def _clv_outcome_link(picks, md: bool) -> None:
    _section("CLV → outcome link (ROI by stored-CLV quartile)", md)
    clvd = sorted((p for p in picks if p["clv"] is not None), key=lambda p: p["clv"])
    if len(clvd) < 8:
        print(f"Only {len(clvd)} CLV'd picks — too few for quartiles.\n")
        return
    labels = quartile_labels(len(clvd))
    accs = [SliceAcc(f"Q{q + 1}") for q in range(4)]
    for p, q in zip(clvd, labels):
        accs[q].add(p["outcome"], p["units"], p["clv"])
    for q, a in enumerate(accs):
        in_q = [p["clv"] for p, lab in zip(clvd, labels) if lab == q]
        a.label = f"Q{q + 1} [{min(in_q):+.3f},{max(in_q):+.3f}]"
    emit_table(SLICE_HEADERS, [a.row() for a in accs], md)


# ── entrypoint ───────────────────────────────────────────────────────────────

def cmd_analyze_picks(args: argparse.Namespace) -> None:
    days = args.days
    md = args.md
    since = eastern_today() - timedelta(days=days)

    conn = get_connection()
    try:
        picks = [p for p in _fetch_settled(conn, since) if p["outcome"] != "void"]
        if not picks:
            print(f"[analyze-picks] no settled non-void picks since {since} — "
                  f"nothing to analyze (is this the stripped dev DB?).")
            return

        overall = SliceAcc("Overall")
        for p in picks:
            overall.add(p["outcome"], p["units"], p["clv"])
        _section(f"Headline (last {days}d, since {since}) — must match "
                 f"/api/track-record?days={days}", md)
        emit_table(SLICE_HEADERS, [overall.row()], md)
        if overall.clvs:
            m, lo, hi = mean_ci95(overall.clvs)
            print(f"avgClv 95% CI: [{lo:+.4f},{hi:+.4f}]  — n={len(overall.clvs)}; "
                  f"treat every number here as provisional under a few hundred picks.\n")

        _coverage(conn, picks, md)
        if args.verify:
            _verify(conn, picks, md)
        _slices(picks, md)
        _clv_outcome_link(picks, md)
    finally:
        conn.close()
