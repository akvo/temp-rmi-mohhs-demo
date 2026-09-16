"""Pure score-summary math shared between build_performance_data.py (the
static-baseline ETL) and performance_live.py (the runtime live-round merge)
-- extracted verbatim from build_performance_data.py so both paths compute
baseline/latest/improvement/median exactly the same way.
"""


def round_summary(scores, rounds_order):
    """scores: {"2025-07": {"overall": 59}, ...} for one site.
    rounds_order: the dataset's full ordered round-key list.

    baseline = the first round in rounds_order this site has data for,
    latest = the last one. improvement_pts is None if they're the same
    round (nothing to compare) or if either score is missing.
    """
    rounds_present = [r for r in rounds_order if r in scores]
    baseline_round = rounds_present[0] if rounds_present else None
    latest_round = rounds_present[-1] if rounds_present else None
    baseline_score = scores[baseline_round]["overall"] if baseline_round else None
    latest_score = scores[latest_round]["overall"] if latest_round else None
    improvement_pts = (
        latest_score - baseline_score
        if baseline_score is not None and latest_score is not None and baseline_round != latest_round
        else None
    )
    return dict(
        baseline_round=baseline_round,
        baseline_score=baseline_score,
        latest_round=latest_round,
        latest_score=latest_score,
        improvement_pts=improvement_pts,
    )


def median_and_flags(sites, global_latest_round):
    """sites: list of site dicts, each already carrying latest_round/latest_score
    (i.e. after round_summary has been applied). global_latest_round: the
    dataset's overall most-recent round key (rounds_order[-1]).

    Returns (median, {site_key: above_median_or_None}) -- median is computed
    over sites whose own latest_round == global_latest_round (i.e. sites that
    have reported for the current round); a site that hasn't reached that
    round yet gets above_median=None rather than being compared against a
    round it has no data for.
    """
    latest_scores = [s["latest_score"] for s in sites if s["latest_round"] == global_latest_round]
    latest_scores_sorted = sorted(latest_scores)
    n = len(latest_scores_sorted)
    median = (
        latest_scores_sorted[n // 2]
        if n % 2
        else (latest_scores_sorted[n // 2 - 1] + latest_scores_sorted[n // 2]) / 2
    )
    flags = {
        s["site_key"]: (s["latest_score"] > median if s["latest_round"] == global_latest_round else None)
        for s in sites
    }
    return median, flags
