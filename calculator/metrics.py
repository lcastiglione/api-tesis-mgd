"""Métricas, tasa diaria y contrastes; los ausentes conservan estado y causa."""

from datetime import datetime, timezone
from math import expm1, fsum, isfinite, log, log1p, sqrt
from statistics import stdev


METRICS = ("return_cumulative", "return_annualized", "volatility_annualized", "max_drawdown", "sharpe_annualized", "initial_capital", "final_capital")
DIRECTIONS = {"return_annualized": 1, "volatility_annualized": -1, "sharpe_annualized": 1}
YEAR_SECONDS = 365.2425 * 86400


def prepare_references(tables):
    rates = {r["rate_id"]: r for r in tables["rates"]}
    result = []
    for trace in tables["rate-trace"]:
        selected = rates.get(trace["rate_id"])
        rf = ""
        if selected and selected["quoted_value"]:
            quote = float(selected["quoted_value"])
            if quote <= -100:
                raise ValueError("La tasa no admite la transformación compuesta.")
            rf = expm1(log1p(quote / 100) / 252)
        result.append({**trace, "observation_date": selected["observation_date"] if selected else "",
                       "available_at": selected["available_at"] if selected else "",
                       "valid_until": selected["valid_until"] if selected else "",
                       "quoted_value": selected["quoted_value"] if selected else "", "rf_daily": rf})
    return result


def attach_references(rows, references):
    for row in rows:
        rate = references[row["session_date"]] if row["row_kind"] == "observation" else None
        row["rate_id"] = rate["rate_id"] if rate else ""
        row["rf_daily"] = rate["rf_daily"] if rate else ""
        row["excess_return"] = float(row["daily_return"]) - float(rate["rf_daily"]) if rate and rate["rf_daily"] != "" else ""


def measure_trajectory(rows):
    observations = [r for r in rows if r["row_kind"] == "observation"]
    if not observations:
        raise ValueError("La trayectoria no contiene retornos.")
    base = float(rows[0]["equity"])
    last = float(observations[-1]["equity"])
    start_at = datetime.fromisoformat(rows[0]["observed_at"]).astimezone(timezone.utc)
    end_at = datetime.fromisoformat(observations[-1]["observed_at"]).astimezone(timezone.utc)
    years = (end_at - start_at).total_seconds() / YEAR_SECONDS
    returns = [float(r["daily_return"]) for r in observations]
    excess = [float(r["excess_return"]) for r in observations if r["excess_return"] != ""]
    peak, mdd = base, 0.0
    for row in observations:
        value = float(row["equity"])
        peak = max(peak, value)
        mdd = max(mdd, 1 - value / peak)
    if abs(expm1(fsum(log1p(r) for r in returns)) - (last / base - 1)) > 1e-10:
        raise ValueError("Los retornos no reconstruyen el capital.")
    values = {"return_cumulative": last / base - 1, "return_annualized": expm1(log(last / base) / years) if years > 0 else None,
              "volatility_annualized": stdev(returns) * sqrt(252) if len(returns) > 1 else None,
              "max_drawdown": mdd, "sharpe_annualized": None, "initial_capital": base, "final_capital": last}
    states = {key: ("calculated" if value is not None else "insufficient_observations") for key, value in values.items()}
    excess_sd = stdev(excess) if len(excess) > 1 else None
    if len(excess) != len(returns):
        states["sharpe_annualized"] = "missing_rate"
    elif excess_sd is not None and excess_sd > 0:
        values["sharpe_annualized"] = fsum(excess) / len(excess) / excess_sd * sqrt(252)
        states["sharpe_annualized"] = "calculated"
    elif excess_sd == 0:
        states["sharpe_annualized"] = "zero_excess_variance"
    if any(value is not None and not isfinite(value) for value in values.values()):
        raise ValueError("Una métrica produjo un valor no finito.")
    return {"values": values, "states": states, "observations": len(returns), "rate_observations": len(excess),
            "duration_years": years, "excess_mean": fsum(excess) / len(excess) if excess else None,
            "excess_sd": excess_sd, "operations": sum(r["operation"] != "none" for r in observations),
            "transaction_costs": fsum(float(r["total_cost"]) for r in observations)}


def quantile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    return ordered[lower] if lower == len(ordered) - 1 else ordered[lower] + (position - lower) * (ordered[lower + 1] - ordered[lower])


def distribution(values, expected):
    q1, median, q3 = (quantile(values, fraction) for fraction in (.25, .5, .75))
    return {"valid_windows": len(values), "excluded_windows": expected - len(values), "q1": q1, "median": median, "q3": q3,
            "iqr": q3 - q1 if len(values) > 1 else None,
            "status": "calculated" if len(values) > 1 else "insufficient_windows"}


def build_contrasts(metric_rows, window_rows):
    index = {(r["case_key"], r["window_id"], r["segment"], r["alternative"], r["metric"]): r for r in metric_rows}
    gaps, summaries = [], []
    keys = sorted({r["case_key"] for r in window_rows})
    for window in window_rows:
        for alternative in ("strategy", "buy_hold"):
            for metric in (*DIRECTIONS, "max_drawdown"):
                before = index[(window["case_key"], window["window_id"], "IS", alternative, metric)]
                after = index[(window["case_key"], window["window_id"], "OOS", alternative, metric)]
                state = "non_comparable_duration" if metric == "max_drawdown" else "calculated"
                if metric != "max_drawdown" and (before["status"] != "calculated" or after["status"] != "calculated"):
                    state = "missing_metric"
                value = DIRECTIONS[metric] * (after["value"] - before["value"]) if state == "calculated" else None
                gaps.append({"case_key": window["case_key"], "window_id": window["window_id"], "window_number": window["window_number"],
                             "alternative": alternative, "metric": metric, "is_value": before["value"], "oos_value": after["value"],
                             "value": value, "status": state, "unit": "ratio" if metric == "sharpe_annualized" else "fraction"})
    for key in keys:
        expected = sum(w["case_key"] == key for w in window_rows)
        for alternative in ("strategy", "buy_hold"):
            for metric in METRICS[:5]:
                for kind in ("OOS", "gap"):
                    source = metric_rows if kind == "OOS" else gaps
                    selected = [r["value"] for r in source if r["case_key"] == key and r["alternative"] == alternative and r["metric"] == metric
                                and r["status"] == "calculated" and (kind == "gap" or r["segment"] == "OOS")]
                    if kind == "gap" and metric not in (*DIRECTIONS, "max_drawdown"):
                        continue
                    summary = {"case_key": key, "alternative": alternative, "kind": kind, "metric": metric,
                               **distribution(selected, expected), "positive_windows": None, "positive_proportion": None}
                    if kind == "gap" and metric == "max_drawdown":
                        summary["status"] = "non_comparable_duration"
                    summaries.append(summary)
            returns = [r["value"] for r in metric_rows if r["case_key"] == key and r["alternative"] == alternative and r["metric"] == "return_annualized"
                       and r["segment"] == "OOS" and r["status"] == "calculated"]
            summaries.append({"case_key": key, "alternative": alternative, "kind": "OOS", "metric": "positive_windows", "valid_windows": len(returns),
                              "excluded_windows": expected - len(returns), "q1": None, "median": None, "q3": None, "iqr": None,
                              "status": "calculated" if returns else "insufficient_windows", "positive_windows": sum(v > 0 for v in returns),
                              "positive_proportion": sum(v > 0 for v in returns) / len(returns) if returns else None})
    return gaps, summaries
