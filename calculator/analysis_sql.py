"""Deriva el catálogo y las comparaciones de C5 de campañas verificadas.

No ejecuta estrategias ni modifica insumos. Requiere pandas y numpy; el motor
de simulación conserva su independencia de estas bibliotecas.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
METRICS = ("return_cumulative", "return_annualized", "volatility_annualized", "sharpe_annualized", "max_drawdown")
CONDITIONS = ("up_low", "up_high", "down_low", "down_high", "flat_low", "flat_high")


DB = None

def relative(path):
    return path.relative_to(ROOT).as_posix()

def sha(path):
    if path.suffix == '.py':
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return DB.document(relative(path))['sha256']

def read_json(path):
    return DB.json(relative(path))


def read(path):
    return DB.frame(relative(path))


def distribution(values):
    data = pd.Series(values, dtype=float).dropna()
    if data.empty:
        return {"count": 0, "minimum": None, "q1": None, "median": None, "q3": None, "maximum": None}
    return {"count": len(data), "minimum": data.min(), "q1": data.quantile(.25), "median": data.median(), "q3": data.quantile(.75), "maximum": data.max()}


def classify(prices, settings):
    """La mediana usa volatilidades anteriores; la etiqueta se rezaga un cierre."""
    frames = []
    for asset, raw in prices.groupby("instrument_id", sort=False):
        raw = raw.sort_values("session_date").reset_index(drop=True)
        close = raw.adj_close.astype(float)
        returns = close.pct_change(fill_method=None)
        vol = returns.rolling(settings["volatility_returns"], min_periods=settings["volatility_returns"]).std(ddof=0)
        threshold = vol.shift(1).expanding(min_periods=1).median()
        change = close / close.shift(settings["trend_closes"] - 1) - 1
        trend = np.where(change > 0, "up", np.where(change < 0, "down", "flat"))
        condition = pd.Series(trend + np.where(vol > threshold, "_high", "_low"), dtype="object")
        condition.iloc[:settings["minimum_history_closes"] - 1] = None
        frames.append(pd.DataFrame({"ETF": asset, "date": raw.session_date, "label_date": raw.session_date.shift(1),
                                    "trend_change": change.shift(1), "volatility": vol.shift(1), "past_median": threshold.shift(1),
                                    "condition": condition.shift(1)}))
    return pd.concat(frames, ignore_index=True)


def curve_metrics(values, rf, years):
    returns = values[1:] / values[:-1] - 1
    excess = returns - rf
    excess_sd = np.std(excess, ddof=1)
    return {"return_cumulative": values[-1] / values[0] - 1,
            "return_annualized": np.expm1(np.log(values[-1] / values[0]) / years),
            "volatility_annualized": np.std(returns, ddof=1) * np.sqrt(252),
            "sharpe_annualized": np.mean(excess) / excess_sd * np.sqrt(252) if excess_sd > 0 else None,
            "max_drawdown": np.max(1 - values / np.maximum.accumulate(values))}


def run(database, namespace='analysis/v9'):
    global DB
    DB = database
    catalog_path = ROOT / "calculators/v6/study-catalog.json"
    design = read_json(catalog_path)
    output = ROOT / namespace / 'chapter5'
    source_hashes, contracts = {}, {}
    collected = {name: [] for name in ("summary", "configurations", "curve", "window-summary", "scale-membership", "sensitivity", "dsr")}
    for asset, identifier in design["campaigns"].items():
        directory = ROOT / "campaigns" / identifier
        contract = read_json(directory / "manifest.json")
        assert contract["status"] == "verified" and contract["parameters"]["instrument"] == asset
        validation = directory / "validation.json"
        assert read_json(validation)["passed"]
        assert sha(validation) == contract["validation"]["sha256"]
        assert sha(ROOT / "db/manifest.json") == contract["dataset_manifest_sha256"]
        contracts[asset] = contract
        for name in ("manifest.json", "validation.json"):
            source_hashes[(directory / name).relative_to(ROOT).as_posix()] = sha(directory / name)
        for name in collected:
            path = directory / (name + ".csv")
            assert sha(path) == contract["files"][path.name]["sha256"]
            frame = read(path)
            assert len(frame) == contract["files"][path.name]["rows"]
            frame["ETF"], frame["campaign"] = asset, identifier
            collected[name].append(frame)
            source_hashes[path.relative_to(ROOT).as_posix()] = sha(path)
    tables = {name: pd.concat(parts, ignore_index=True) for name, parts in collected.items()}
    summary, configs = tables["summary"], tables["configurations"]
    assert len(summary) == 945 and len(configs) == 189
    assert not summary.duplicated(["ETF", "case_key"]).any()
    membership = tables["scale-membership"].groupby(["ETF", "config_key"])["scale"].agg(lambda s: "+".join(sorted(s))).rename("scales")
    full = summary.merge(membership, on=["ETF", "config_key"], validate="many_to_one")
    full["complete_oos"] = full.windows_evaluated == full.windows_expected
    for metric in METRICS:
        direction = -1 if metric in ("volatility_annualized", "max_drawdown") else 1
        full["advantage_" + metric] = direction * (full["strategy_" + metric] - full["buy_hold_" + metric])
    outputs = {"catalog": full, "configurations": configs}

    calendar = read(ROOT / "db/calendar.csv").set_index("session_date")
    prices = read(ROOT / "db/prices.csv")
    rates_path = ROOT / "campaigns" / design["campaigns"]["SPY"] / "rate-reference.csv"
    rates = read(rates_path).set_index("session_date").rf_daily
    source_hashes[rates_path.relative_to(ROOT).as_posix()] = sha(rates_path)
    for name in ("prices.csv", "calendar.csv", "manifest.json"):
        source_hashes["db/" + name] = sha(ROOT / "db" / name)
    conditions = classify(prices, design["conditions"])
    outputs["conditions"] = conditions
    # El intervalo incluye el patrimonio del cierre anterior al primer retorno.
    common_start, common_end = full.first_date.max(), full.last_date.min()
    dates = calendar.index.tolist()
    base_date = dates[dates.index(common_start) - 1]
    observed_dates = [d for d in dates if common_start <= d <= common_end]
    duration = (pd.Timestamp(calendar.loc[common_end, "close_at"]) - pd.Timestamp(calendar.loc[base_date, "close_at"])).total_seconds() / (365.2425 * 86400)
    label_index = conditions.set_index(["ETF", "date"])
    common, conditioned, central_daily = [], [], []
    summary_index = summary.set_index(["ETF", "case_key"])
    for (asset, case), curve in tables["curve"].groupby(["ETF", "case_key"], sort=False):
        identity = summary_index.loc[(asset, case)]
        selected = curve[curve.session_date.between(base_date, common_end)].sort_values("session_date")
        assert selected.session_date.tolist() == [base_date] + observed_dates
        reference = rates.loc[observed_dates].to_numpy(float)
        record = {"ETF": asset, "case_key": case, "family": identity.family, "config_key": identity.config_key,
                  "length_years": int(identity.length_years), "base_date": base_date, "first_date": common_start, "last_date": common_end,
                  "observations": len(observed_dates), "duration_years": duration}
        daily_returns = {}
        for alternative in ("strategy", "buy_hold"):
            values = selected[alternative + "_equity"].to_numpy(float)
            record.update({alternative + "_" + key: value for key, value in curve_metrics(values, reference, duration).items()})
            daily_returns[alternative] = values[1:] / values[:-1] - 1
        for metric in METRICS:
            direction = -1 if metric in ("volatility_annualized", "max_drawdown") else 1
            a, b = record["strategy_" + metric], record["buy_hold_" + metric]
            record["advantage_" + metric] = direction * (a - b) if a is not None and b is not None else None
        common.append(record)
        labels = label_index.loc[[(asset, day) for day in observed_dates], "condition"].to_numpy()
        for condition in CONDITIONS:
            mask = labels == condition
            count = int(np.sum(mask))
            valid = count >= design["conditions"]["minimum_category_dates"]
            values = {"ETF": asset, "case_key": case, "config_key": identity.config_key, "family": identity.family, "length_years": int(identity.length_years),
                      "condition": condition, "dates": count, "status": "calculated" if valid else "insufficient_dates"}
            for alternative in ("strategy", "buy_hold"):
                values[alternative + "_daily_mean"] = float(np.mean(daily_returns[alternative][mask])) if valid else None
            values["advantage_daily_mean"] = values["strategy_daily_mean"] - values["buy_hold_daily_mean"] if valid else None
            conditioned.append(values)
        if identity.config_key in design["centers"].values():
            # Curvas centrales completas para figuras; no se reinicia la cuenta.
            normalized = curve.sort_values("session_date").copy()
            normalized["family"], normalized["length_years"] = identity.family, int(identity.length_years)
            for alternative in ("strategy", "buy_hold"):
                values = normalized[alternative + "_equity"].to_numpy(float)
                normalized[alternative + "_normalized"] = values / values[0]
                normalized[alternative + "_drawdown"] = values / np.maximum.accumulate(values) - 1
            central_daily.append(normalized)
    outputs["common-metrics"] = pd.DataFrame(common)
    outputs["condition-results"] = pd.DataFrame(conditioned)
    outputs["central-curves"] = pd.concat(central_daily, ignore_index=True)
    coverage = []
    for asset in design["campaigns"]:
        subset = label_index.loc[[(asset, day) for day in observed_dates]]
        for condition in CONDITIONS:
            count = int((subset.condition == condition).sum())
            coverage.append({"ETF": asset, "condition": condition, "dates": count, "share": count / len(observed_dates),
                             "status": "calculated" if count >= 30 else "insufficient_dates"})
    outputs["condition-coverage"] = pd.DataFrame(coverage)
    condition_summary = []
    for key, group in outputs["condition-results"].groupby(["ETF", "family", "condition"], sort=False):
        record = dict(zip(["ETF", "family", "condition"], key))
        record.update(dates=int(group.dates.iloc[0]), cases=len(group), status=group.status.iloc[0])
        for field in ("strategy_daily_mean", "buy_hold_daily_mean", "advantage_daily_mean"):
            record.update({field + "_" + k: v for k, v in distribution(group[field]).items()})
        condition_summary.append(record)
    outputs["condition-summary"] = pd.DataFrame(condition_summary)

    comparisons = []
    for row in tables["window-summary"].to_dict("records"):
        for metric in METRICS[1:]:
            before, after, passive = (row[prefix + metric] for prefix in ("is_strategy_", "oos_strategy_", "oos_buy_hold_"))
            available = row["status"] == "evaluable" and all(pd.notna(value) for value in (before, after, passive))
            direction = -1 if metric in ("volatility_annualized", "max_drawdown") else 1
            comparisons.append({**{key: row[key] for key in ("ETF", "case_key", "config_key", "family", "length_years", "window_id", "window_number", "oos_start", "oos_end", "oos_sessions")},
                                "metric": metric, "is_value": before, "oos_value": after, "buy_hold_value": passive,
                                "gap": direction * (after - before) if available else None,
                                "advantage": direction * (after - passive) if available else None,
                                "status": "calculated" if available else "missing_metric",
                                "duration_caveat": metric == "max_drawdown"})
    outputs["window-comparisons"] = pd.DataFrame(comparisons)
    grouped_gaps, grid = [], []
    expanded = outputs["window-comparisons"].merge(tables["scale-membership"][["ETF", "config_key", "scale"]], on=["ETF", "config_key"], validate="many_to_many")
    for key, group in expanded.groupby(["scale", "length_years", "family", "metric"], sort=False):
        record = dict(zip(["scale", "length_years", "family", "metric"], key))
        record.update(expected=len(group), **distribution(group.gap), deteriorated=int((group.gap < -1e-10).sum()), at_least_benchmark=int((group.advantage >= -1e-10).sum()))
        grouped_gaps.append(record)
    outputs["gap-summary"] = pd.DataFrame(grouped_gaps)
    for key, group in expanded.groupby(["ETF", "scale", "length_years", "family", "window_id", "metric"], sort=False):
        record = dict(zip(["ETF", "scale", "length_years", "family", "window_id", "metric"], key))
        record.update(expected=len(group), **distribution(group.oos_value), positive=int((group.oos_value > 0).sum()))
        grid.append(record)
    outputs["grid-distribution"] = pd.DataFrame(grid)
    sensitivity = []
    for key, group in tables["sensitivity"].groupby(["scale", "family", "length_years", "parameter", "segment", "metric"], sort=False):
        record = dict(zip(["scale", "family", "length_years", "parameter", "segment", "metric"], key))
        valid = group[group.status == "calculated"]
        record.update(expected=len(group), **distribution(valid.difference.abs()),
                      strict_sign_reversals=int(((valid.left_value * valid.right_value) < 0).sum()) if key[-1].startswith("return") else None,
                      zero_transitions=int(((valid.left_value == 0) ^ (valid.right_value == 0)).sum()) if key[-1].startswith("return") else None)
        sensitivity.append(record)
    outputs["sensitivity-summary"] = pd.DataFrame(sensitivity)
    dsr = []
    for key, group in tables["dsr"].groupby(["ETF", "scale", "length_years", "family"], sort=False):
        record = dict(zip(["ETF", "scale", "length_years", "family"], key))
        valid = group.status == "calculated"
        record.update(evaluations=len(group), groups=group.group_id.nunique(), calculated=int(valid.sum()),
                      above=int((group.loc[valid, "above_threshold"] == 1).sum()), unavailable=int((~valid).sum()))
        dsr.append(record)
    outputs["dsr-summary"] = pd.DataFrame(dsr)
    outputs["dsr-status"] = tables["dsr"].groupby(["ETF", "scale", "status"]).size().reset_index(name="evaluations")
    length_comparison = []
    for key, group in outputs["common-metrics"].groupby(["ETF", "config_key", "family"], sort=False):
        assert set(group.length_years) == {1, 2, 3, 5, 7}
        length_comparison.append({**dict(zip(["ETF", "config_key", "family"], key)), "spread_return": group.strategy_return_cumulative.max() - group.strategy_return_cumulative.min()})
    outputs["length-comparison"] = pd.DataFrame(length_comparison)
    outputs["coverage"] = full.groupby(["ETF", "length_years"], sort=False).agg(configurations=("case_key", "count"), first_date=("first_date", "min"), last_date=("last_date", "max"),
                              windows=("windows_expected", "first"), evaluable=("windows_evaluated", "first"), observations=("strategy_observations", "first")).reset_index()
    files = {}
    for name, frame in outputs.items():
        path = output / (name + ".csv")
        DB.add_evaluations(relative(path), list(__import__('csv').DictReader(__import__('io').StringIO(frame.to_csv(index=False, float_format='%.17g', lineterminator='\n')))), 'derived')
        files[path.name] = {"rows": len(frame), "sha256": sha(path)}
    manifest = {"schema_version": 1, "study_id": design["study_id"], "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": "derived_pending_audit", "code": {"analysis_sql.py": sha(HERE / "analysis_sql.py"), "study-catalog.json": sha(catalog_path)},
                "sources": source_hashes, "files": files,
                "coverage": {"instruments": len(design["campaigns"]), "configurations": len(configs), "cases": len(full),
                             "windows": sum(c["coverage"]["windows"] for c in contracts.values()),
                             "excluded_oos": sum(c["coverage"]["insufficient_oos_windows"] for c in contracts.values())},
                "common_interval": {"base_date": base_date, "first_date": common_start, "last_date": common_end, "observations": len(observed_dates), "duration_years": duration},
                "conventions": {"drawdown": "stored positive depth; show negative signed loss; observed IS/OOS difference is descriptive with unequal duration caveat",
                                "sign_changes": "strict opposite nonzero signs; transitions through zero counted separately",
                                "common_base": "previous session close, inherited holdings, no new simulation or trade",
                                "conditions": "own ETF; previous-close label; rolling population volatility; expanding past-only median; minimum 30 distinct dates"}}
    DB.put_document(relative(output / 'manifest.json'), manifest, 'analysis')
    DB.connection.commit()
    print(json.dumps({"output": str(output), "files": len(files), "coverage": manifest["coverage"], "common_interval": manifest["common_interval"]}, ensure_ascii=False))
