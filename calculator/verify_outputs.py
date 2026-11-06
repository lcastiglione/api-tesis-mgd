"""Comprueba los resultados analíticos derivados de la base histórica."""

import math


def compare_rows(expected,actual,ignored=()):
    if len(expected)!=len(actual):
        raise AssertionError(('rows',len(expected),len(actual)))
    tolerance_matches=0
    for number,(left,right) in enumerate(zip(expected,actual),1):
        if set(left)!=set(right):
            raise AssertionError(('fields',set(left),set(right)))
        for key,a in left.items():
            if key in ignored or str(a)==str(right[key]):
                continue
            b=right[key]
            if a in ('',None) and b in ('',None):
                continue
            try:
                first,second=float(a),float(b)
            except (TypeError,ValueError):
                raise AssertionError((number,key,a,b)) from None
            if not math.isclose(first,second,rel_tol=1e-11,abs_tol=1e-10):
                raise AssertionError((number,key,a,b))
            tolerance_matches+=1
    return {'rows':len(actual),'passed':True,'numeric_representation_matches_within_tolerance':tolerance_matches}


def compare_analyses(db,namespace='analysis/v9'):
    result={}
    manifest=db.json('work/chapter5-results-20261025/manifest.json')
    for name in manifest['files']:
        before='work/chapter5-results-20261025/'+name
        after=namespace+'/chapter5/'+name
        result[name]=compare_rows(list(db.records(before)),list(db.records(after)))
    for name in ('psr.csv','dsr-evidence.csv','statistical-summary.csv'):
        result['statistics/'+name]=compare_rows(list(db.records('work/statistical-v6-20261027/'+name)),
             list(db.records(namespace+'/statistics/'+name)),ignored=('analysis_version',))
    for name in ('summary.csv','lengths.csv'):
        result['matrix/'+name]=compare_rows(list(db.records('work/robustness-score-20261027/'+name)),
                                           list(db.records(namespace+'/matrix/'+name)))
    report={'passed':True,'outputs_compared':len(result),'tables':result,
            'tolerance':{'absolute':1e-10,'relative':1e-11},
            'analysis_version_change':'Historical source version to 9 is expected; financial values and states are preserved.'}
    db.put_document('checks/'+namespace,report,'validation')
    db.connection.commit()
    return report
