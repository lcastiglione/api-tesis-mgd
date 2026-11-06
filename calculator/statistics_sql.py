"""Evalúa PSR y limitaciones DSR a partir de campañas verificadas, sin modificarlas."""

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CATALOG = ROOT / "calculators/v6/study-catalog.json"
OUTPUT = ROOT / "analysis/v9/statistics"
DB = None
NORMAL = NormalDist()


def sha(path):
    return DB.document(path.relative_to(ROOT).as_posix())['sha256']


def probability(sharpe, skewness, kurtosis, observations, benchmark=0.0):
    """PSR no anualizado; curtosis Pearson. No estima independencia temporal."""
    denominator = 1 - skewness * sharpe + (kurtosis - 1) * sharpe**2 / 4
    if observations < 30 or not math.isfinite(denominator) or denominator <= 0:
        return None
    return NORMAL.cdf((sharpe - benchmark) * math.sqrt((observations - 1) / denominator))


def key(row):
    return (row["instrument_id"], row["length_years"], row["window_id"], row["config_key"])


def load_rows(path):
    return list(DB.records(path.relative_to(ROOT).as_posix()))


def write_csv(path, rows):
    DB.add_evaluations(path.relative_to(ROOT).as_posix(), rows, 'statistical')


def build(database, namespace='analysis/v9'):
    global DB, OUTPUT
    DB = database
    OUTPUT = ROOT / namespace / 'statistics'
    catalog = DB.json(CATALOG.relative_to(ROOT).as_posix())
    source_hashes, evaluations, individuals = {}, [], {}
    coverage = Counter()
    for asset, campaign in catalog["campaigns"].items():
        directory = ROOT / "campaigns" / campaign
        manifest = DB.json((directory / 'manifest.json').relative_to(ROOT).as_posix())
        validation = DB.json((directory / 'validation.json').relative_to(ROOT).as_posix())
        assert manifest["status"] == "verified" and validation["passed"]
        assert manifest["parameters"]["instrument"] == asset
        for name in ("manifest.json", "validation.json", "dsr.csv", "operations.csv"):
            path = directory / name
            digest = sha(path)
            if name in manifest["files"]:
                assert digest == manifest["files"][name]["sha256"], str(path)
            source_hashes[path.relative_to(ROOT).as_posix()] = digest
        operations = Counter()
        for row in load_rows(directory / "operations.csv"):
            if row["segment"] == "IS" and row["alternative"] == "strategy":
                operations[(asset, row["length_years"], row["window_id"], row["config_key"])] += 1
        asset_rows = load_rows(directory / "dsr.csv")
        assert len(asset_rows) == 1620
        group_cash = defaultdict(bool)
        for row in asset_rows:
            group_cash[row["group_id"]] |= operations[key(row)] == 0
        for row in asset_rows:
            ident = key(row)
            assert row["instrument_id"] == asset
            sr = float(row["sharpe_daily"])
            value = probability(sr, float(row["skewness"]), float(row["kurtosis_pearson"]), int(row["common_observations"]))
            assert value is not None
            cash = operations[ident] == 0
            individual = {"instrument_id":asset, "length_years":row["length_years"], "window_id":row["window_id"],
                          "config_key":row["config_key"], "family":row["family"], "observations":row["common_observations"],
                          "first_date":row["first_common_date"], "last_date":row["last_common_date"],
                          "sharpe_daily":sr, "skewness":float(row["skewness"]), "kurtosis_pearson":float(row["kurtosis_pearson"]),
                          "operations_is":operations[ident], "cash_only":int(cash), "psr_zero":value,
                          "psr_threshold":0.95, "psr_above":int(value >= 0.95), "psr_status":"calculated",
                          "interpretation":"sin_operaciones" if cash else "limitado_sin_ajuste_serial",
                          "source_campaign":campaign, "analysis_version":9}
            if ident in individuals:
                assert individuals[ident] == individual, f"La serie difiere entre escalas: {ident}"
            else:
                individuals[ident] = individual
            enriched = {**row, "psr_zero":value, "psr_above":int(value >= 0.95),
                        "operations_is":operations[ident], "cash_only":int(cash),
                        "group_has_cash_only":int(group_cash[row["group_id"]]),
                        "dsr_interpretation":"grupo_con_variante_sin_operaciones" if group_cash[row["group_id"]] else "limitado_grilla_pequena_y_dependencia_serial"}
            if row["status"] == "calculated":
                se = math.sqrt((1 - float(row["skewness"]) * sr + (float(row["kurtosis_pearson"]) - 1) * sr**2 / 4) / (int(row["common_observations"]) - 1))
                reconstructed = NORMAL.cdf((sr - float(row["expected_max_sharpe"])) / se)
                assert abs(reconstructed - float(row["probability"])) < 1e-12
                assert int(row["above_threshold"]) == int(float(row["probability"]) >= .95)
            evaluations.append(enriched)
            coverage[(asset, row["scale"], row["length_years"])] += 1
        print(f"{asset}: {len(asset_rows)} evaluaciones verificadas", flush=True)
    assert len(evaluations) == 11340 and len(individuals) == 10206
    individual_rows = sorted(individuals.values(), key=lambda r:(r["instrument_id"], int(r["length_years"]), r["window_id"], r["config_key"]))
    write_csv(OUTPUT / "psr.csv", individual_rows)
    write_csv(OUTPUT / "dsr-evidence.csv", evaluations)
    summaries = []
    for (asset, scale, length), total in sorted(coverage.items()):
        selected = [r for r in evaluations if (r["instrument_id"], r["scale"], r["length_years"]) == (asset, scale, length)]
        calc = [r for r in selected if r["status"] == "calculated"]
        summaries.append({"instrument_id":asset,"scale":scale,"length_years":length,"evaluations":total,
                          "dsr_calculated":len(calc),"dsr_above":sum(int(r["above_threshold"]) for r in calc),
                          "dsr_unavailable":total-len(calc),"psr_above":sum(r["psr_above"] for r in selected),
                          "cash_only":sum(r["cash_only"] for r in selected),
                          "dsr_calculated_cash_group":sum(r["group_has_cash_only"] for r in calc),
                          "source":"IS; valores por escala; centros repetidos en ambas escalas"})
    write_csv(OUTPUT / "statistical-summary.csv", summaries)
    calculated = [r for r in evaluations if r["status"] == "calculated"]
    report = {"status":"verified_numerical_with_methodological_limits", "analysis_version":9,
              "generated_at":datetime.now(timezone.utc).isoformat(), "catalog_sha256":sha(CATALOG),
              "source_hashes":source_hashes,"dsr_evaluations":len(evaluations),"individual_psr":len(individual_rows),
              "psr_above":sum(r["psr_above"] for r in individual_rows),
              "cash_only_individual":sum(r["cash_only"] for r in individual_rows),
              "psr_above_cash_only":sum(r["psr_above"] for r in individual_rows if r["cash_only"]),
              "dsr_calculated":len(calculated),"dsr_above":sum(int(r["above_threshold"]) for r in calculated),
              "dsr_calculated_cash_group":sum(r["group_has_cash_only"] for r in calculated),
              "dsr_above_cash_group":sum(int(r["above_threshold"]) for r in calculated if r["group_has_cash_only"]),
              "joint":dict(Counter("both_above" if int(r["above_threshold"]) else "psr_only" if r["psr_above"] else "both_below" for r in calculated)),
              "files":{name:{"sha256":sha(OUTPUT / name),"rows":len(rows)} for name,rows in (("psr.csv",individual_rows),("dsr-evidence.csv",evaluations),("statistical-summary.csv",summaries))},
              "limitations":["PSR y DSR sin corrección por dependencia serial", "grillas pequeñas", "grupos con variantes sin operaciones identificados", "ventanas solapadas y centros compartidos no son pruebas independientes"],
              "preserves_financial_campaigns":True}
    DB.put_document((OUTPUT / 'manifest.json').relative_to(ROOT).as_posix(), report, 'analysis')
    DB.connection.commit()
    print(json.dumps({k:v for k,v in report.items() if k not in ("source_hashes","files")}, ensure_ascii=False, indent=2))
