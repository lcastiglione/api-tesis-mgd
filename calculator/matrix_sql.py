"""Calcula una puntuación exploratoria de condiciones históricas por estrategia y ETF."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'analysis/v9/chapter5'
STAT = ROOT / 'analysis/v9/statistics'
OUT = ROOT / 'analysis/v9/matrix'
DB = None
ASSETS = ('SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'TLT', 'GLD')
CENTERS = {'P-SMA': 'sma200', 'MOM': 'mom252', 'MR-Z': 'mrz20-2'}
LENGTHS = ('1', '2', '3', '5', '7')
EXPECTED = {'1': 27, '2': 12, '3': 8, '5': 4, '7': 2}
TOL = 1e-10
WEIGHTS = {'benchmark': .20, 'volatility': .15, 'drawdown': .15,
           'temporal': .20, 'local': .15, 'broad': .15}
ALTERNATIVES = {
    'equal': {k: 1/6 for k in WEIGHTS},
    'return_first': {'benchmark': .35, 'volatility': .10, 'drawdown': .10,
                     'temporal': .15, 'local': .15, 'broad': .15},
}


def read(path):
    return list(DB.records(path.relative_to(ROOT).as_posix()))


def campaign(asset):
    return ROOT / ('campaigns/p05-spy-sensitivity-20261024' if asset == 'SPY'
                   else f'campaigns/p06-{asset.lower()}-sensitivity-20261025')


def write(name, values):
    DB.add_evaluations((OUT / name).relative_to(ROOT).as_posix(), values, 'matrix')


def main(database, namespace='analysis/v9'):
    global DB, WEIGHTS, DATA, STAT, OUT
    DB = database
    DATA, STAT, OUT = (ROOT / namespace / part for part in ('chapter5','statistics','matrix'))
    WEIGHTS = DB.json('system/protocol')['weights']
    common = read(DATA / 'common-metrics.csv')
    windows = read(DATA / 'window-comparisons.csv')
    psr = read(STAT / 'psr.csv')
    dsr = read(STAT / 'dsr-evidence.csv')
    assert len(common) == 945 and all(r['observations'] == '942' for r in common)
    result, trace = [], []
    for asset in ASSETS:
        members = read(campaign(asset) / 'scale-membership.csv')
        for family, center in CENTERS.items():
            center_rows = {r['length_years']: r for r in common
                           if r['ETF'] == asset and r['config_key'] == center}
            assert set(center_rows) == set(LENGTHS)
            # Se compara cada estrategia con la referencia correspondiente a sus fechas y costos.
            def pass_metric(r, a, b, larger):
                x, y = float(r[a]), float(r[b])
                return x >= y-TOL if larger else x <= y+TOL
            benchmark = sum(pass_metric(r, 'strategy_return_cumulative', 'buy_hold_return_cumulative', True) for r in center_rows.values())/5
            vol = sum(pass_metric(r, 'strategy_volatility_annualized', 'buy_hold_volatility_annualized', False) for r in center_rows.values())/5
            draw = sum(pass_metric(r, 'strategy_max_drawdown', 'buy_hold_max_drawdown', False) for r in center_rows.values())/5
            temporal_values = []
            for length in LENGTHS:
                w = [r for r in windows if r['ETF'] == asset and r['config_key'] == center
                     and r['length_years'] == length and r['metric'] == 'return_annualized'
                     and r['status'] == 'calculated']
                assert len(w) == EXPECTED[length], (asset, family, length, len(w))
                positives = sum(float(r['oos_value']) > 0 for r in w)
                temporal_values.append(positives/len(w))
                trace.append(dict(ETF=asset, family=family, length=length,
                                  positive_windows=positives, calculated_windows=len(w),
                                  return_cumulative=center_rows[length]['strategy_return_cumulative'],
                                  reference_return=center_rows[length]['buy_hold_return_cumulative'],
                                  volatility=center_rows[length]['strategy_volatility_annualized'],
                                  reference_volatility=center_rows[length]['buy_hold_volatility_annualized'],
                                  max_drawdown=center_rows[length]['strategy_max_drawdown'],
                                  reference_max_drawdown=center_rows[length]['buy_hold_max_drawdown']))
            temporal = sum(temporal_values)/5
            sens = {}
            for scale in ('local', 'broad'):
                keys = {r['config_key'] for r in members if r['scale'] == scale}
                subset = [r for r in common if r['ETF'] == asset and r['family'] == family and r['config_key'] in keys]
                assert len(subset) == 5*(9 if family == 'MR-Z' else 3)
                sens[scale] = sum(float(r['strategy_return_cumulative']) > 0 for r in subset)/len(subset)
            components = {'benchmark': benchmark, 'volatility': vol, 'drawdown': draw,
                          'temporal': temporal, 'local': sens['local'], 'broad': sens['broad']}
            assert abs(sum(WEIGHTS.values())-1) < 1e-12
            score = 100*sum(WEIGHTS[k]*v for k,v in components.items())
            other = {name:100*sum(weight[k]*v for k,v in components.items()) for name,weight in ALTERNATIVES.items()}
            essential = all(float(r['strategy_return_cumulative']) > 0
                            and pass_metric(r, 'strategy_return_cumulative', 'buy_hold_return_cumulative', True)
                            for r in center_rows.values())
            ps = [r for r in psr if r['instrument_id'] == asset and r['config_key'] == center]
            ds = [r for r in dsr if r['instrument_id'] == asset and r['config_key'] == center]
            assert len(ps) == 54 and len(ds) == 108
            pc = [r for r in ps if r['psr_status'] == 'calculated']
            dc = [r for r in ds if r['status'] == 'calculated']
            result.append(dict(ETF=asset,family=family,config_key=center,essential=essential,
                               **components,score=score,equal=other['equal'],return_first=other['return_first'],
                               score_min=min(score,*other.values()),score_max=max(score,*other.values()),
                               psr_above=sum(r['psr_above']=='1' for r in pc),psr_calculated=len(pc),psr_expected=54,
                               dsr_above=sum(r['above_threshold']=='1' for r in dc),dsr_calculated=len(dc),dsr_expected=108))
    assert len(result)==21 and len(trace)==105
    write('summary.csv',result)
    write('lengths.csv',trace)
    DB.connection.commit()
    print(json.dumps({'combinations':len(result),'eligible':sum(r['essential'] for r in result)}))
