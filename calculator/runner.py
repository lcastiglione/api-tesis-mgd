"""Comprueba un caso desde SQLite en memoria, sin persistir ensayos."""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import platform
import sqlite3

from .database import DAILY_FIELDS, OP_EXTRA, dumps
from . import engine
from .metrics import METRICS, attach_references, measure_trajectory, prepare_references
from .quality import inspect_tables


def as_text(value):
    return '' if value is None else str(value)


def run_case(db,instrument,config_key,length,execution_id,verify=True):
    if db.connection.execute('SELECT 1 FROM executions WHERE execution_id=?',(execution_id,)).fetchone():
        raise ValueError('La ejecución ya existe: '+execution_id)
    config = db.connection.execute('SELECT * FROM configurations WHERE instrument_id=? AND config_key=?',
                                   (instrument,config_key)).fetchone()
    if config is None:
        raise ValueError('Configuración no registrada.')
    catalog = db.json('system/database')['authoritative_study']
    campaign = catalog['campaigns'][instrument]
    manifest = db.json('campaigns/'+campaign+'/manifest.json')
    parameters = manifest['parameters']
    settings = {'INITIAL_CASH':'initial_cash_usd','COMMISSION_RATE':'commission_rate',
                'MIN_COMMISSION':'minimum_commission_usd','VAT_RATE':'vat_rate',
                'HALF_SPREAD':'half_spread','SLIPPAGE':'slippage','STEP':'quantity_step'}
    for attribute,key in settings.items():
        setattr(engine,attribute,Decimal(parameters[key]))
    engine.RULES[config_key]=(config['family'],config['sessions'],
                              Decimal(config['entry_threshold']) if config['entry_threshold'] else None)
    tables = {name:list(db.records('db/'+name+'.csv')) for name in
              ('instruments','calendar','prices','rates','rate-trace','dictionary')}
    quality = inspect_tables(db.json('db/manifest.json'),tables)
    raw = [row for row in tables['prices'] if row['instrument_id']==instrument]
    prices,signals = engine.prepare_prices(raw,config_key)
    windows = engine.make_windows(len(prices),length)
    references = {r['session_date']:r for r in prepare_references(tables)}
    case_key = config_key+f'-L{length}'
    identity = {'case_key':case_key,'case_id':config['configuration_id']+f'-L{length}',
                'config_key':config_key,'family':config['family'],'length_years':length,'rule_label':config['label']}
    record = {**identity,'execution_id':execution_id,'calculator_version':9,'campaign_id':campaign,
              'dataset_manifest_sha256':db.document('db/manifest.json')['sha256'],'status':'verification_pending'}
    runtime={'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,
             'code':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                     for name in ('engine.py','metrics.py','design.py','quality.py','runner.py','database.py')}}
    histories = {'strategy':[],'buy_hold':[]}
    states = dict.fromkeys(histories)
    all_daily,all_operations,metrics,window_records = [],[],[],[]
    for window in windows:
        wid = window['window_id']
        window_records.append({**identity,'window_id':wid,'status':window['oos_status'],
            'is_start':prices[window['is_start']]['date'],'is_end':prices[window['is_stop']-1]['date'],
            'oos_start':prices[window['oos_start']]['date'],'oos_end':prices[window['oos_stop']-1]['date']})
        for segment in ('IS','OOS'):
            for alternative in states:
                if segment=='OOS' and window['oos_status']!='evaluable':
                    measured={'values':dict.fromkeys(METRICS),'states':{m:window['oos_status'] for m in METRICS},
                              'observations':window['oos_stop']-window['oos_start'],'rate_observations':0,'duration_years':None}
                else:
                    rows,orders,state = engine.simulate(prices,signals,tables['calendar'],window[segment.lower()+'_start'],
                        window[segment.lower()+'_stop'],alternative,wid,segment,execution_id,
                        states[alternative] if segment=='OOS' else None,config_key)
                    attach_references(rows,references)
                    for row in rows+orders:
                        row.update(identity)
                    all_daily.extend(rows)
                    all_operations.extend(orders)
                    measured=measure_trajectory(rows)
                    if segment=='OOS':
                        states[alternative]=state
                        histories[alternative].extend(rows if not histories[alternative] else rows[1:])
                for metric in METRICS:
                    metrics.append({**identity,'execution_id':execution_id,'window_id':wid,'segment':segment,
                        'alternative':alternative,'metric':metric,'value':measured['values'][metric],
                        'status':measured['states'][metric],'observations':measured['observations'],
                        'rate_observations':measured['rate_observations'],'duration_years':measured['duration_years'],
                        'unit':'USD' if 'capital' in metric else 'ratio' if metric=='sharpe_annualized' else 'fraction'})
    for alternative,rows in histories.items():
        measured=measure_trajectory(rows)
        for metric in METRICS:
            metrics.append({**identity,'execution_id':execution_id,'window_id':'all_oos','segment':'OOS_continuous',
                'alternative':alternative,'metric':metric,'value':measured['values'][metric],
                'status':measured['states'][metric],'observations':measured['observations'],
                'rate_observations':measured['rate_observations'],'duration_years':measured['duration_years'],
                'unit':'USD' if 'capital' in metric else 'ratio' if metric=='sharpe_annualized' else 'fraction'})
    report={'execution_id':execution_id,'engine_version':9,'instrument':instrument,'config_key':config_key,
            'length_years':length,'created_at':datetime.now(timezone.utc).isoformat(),
            'runtime':runtime,
            'daily_rows':len(all_daily),'operations':len(all_operations),'metrics':len(metrics),
            'inputs_quality_checks':len(quality['checks']),'passed':True}
    if verify:
        original_id = campaign+'-'+case_key
        # Se comparan todos los campos; solo cambian la identidad y la versión de ejecución.
        comparisons={}
        for name,actual in [('daily-results.csv.gz',all_daily),('operations.csv',all_operations),('metrics.csv',metrics)]:
            if name=='daily-results.csv.gz':
                fields=json.loads(db.document('campaigns/'+campaign+'/'+name)['metadata'])['fields']
                original=[{k:r[k] for k in fields} for r in db.daily_records(execution_id=original_id)]
            elif name=='operations.csv':
                fields=list(actual[0]) if actual else []
                original=[{k:r[k] for k in fields} for r in db.operation_records(original_id)]
            else:
                original=[r for r in db.records('campaigns/'+campaign+'/'+name) if r['execution_id']==original_id]
            if len(original)!=len(actual):
                raise AssertionError((name,len(original),len(actual)))
            float_differences=0
            for before,after in zip(original,actual):
                for field,left in before.items():
                    if field=='execution_id':
                        continue
                    right=after[field]
                    if as_text(left)==as_text(right):
                        continue
                    try:
                        a,b=float(left),float(right)
                    except (ValueError,TypeError):
                        raise AssertionError((name,field,left,right)) from None
                    if not math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12):
                        raise AssertionError((name,field,left,right))
                    float_differences+=1
            comparisons[name]={'rows':len(original),'equivalent':True,'representation_differences_within_1e_12':float_differences}
        report['comparisons']=comparisons
    return report
