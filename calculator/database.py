"""Lectura autónoma de SQLite compacto; las comprobaciones no escriben la entrega."""

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3

HERE = Path(__file__).resolve().parent
DAILY_FIELDS = ('execution_id window_id segment alternative session_date observed_at row_kind '
                'signal_date signal_close sma_200 signal_mean signal_sd momentum_reference '
                'signal_value signal_valid target_exposure operation operation_reason '
                'adjusted_open adjusted_close cash units equity previous_equity daily_return '
                'normalized_equity drawdown_signed commission vat spread_cost slippage_cost '
                'total_cost rate_id rf_daily excess_return').split()
OP_EXTRA = 'operation_source_id operation_source_row operation_id executed_at execution_price quantity notional'.split()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str, allow_nan=False)


def fingerprint(rows, fields):
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        digest.update((dumps([str(row.get(k, '')) if row.get(k) is not None else '' for k in fields])+'\n').encode())
        count += 1
    return count, digest.hexdigest()


class Database:
    def __init__(self, path, readonly=True, reference=None):
        self.path = Path(path)
        self.readonly = readonly
        self.reference = reference
        self.connection = (sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True)
                           if readonly else sqlite3.connect(str(path)))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.execute('PRAGMA busy_timeout=30000')
        self.connection.execute('PRAGMA cache_size=-65536')
        if readonly:
            self.connection.execute('PRAGMA query_only=ON')
        self._documents = None
        self._executions = None
        self._verified_sources = set()

    def close(self):
        self.connection.close()

    def document(self, key):
        row = self.connection.execute('SELECT * FROM documents WHERE document_id=?', (key,)).fetchone()
        if row is None:
            if self.reference is not None:
                return self.reference.document(key)
            raise KeyError(key)
        return dict(row)

    def raw(self, key):
        row = self.document(key)
        if row['content'] is None:
            raise ValueError('La representación original no se duplica; utilizar records o daily_records: '+key)
        return gzip.decompress(row['content'])

    def json(self, key):
        row = self.document(key)
        return json.loads(row['json_content']) if row['json_content'] is not None else json.loads(self.raw(key))

    def put_document(self, key, value, kind='record', media_type='application/json', metadata=None):
        if self.readonly:
            raise sqlite3.OperationalError('La entrega se consulta en modo de solo lectura.')
        raw = value if isinstance(value, bytes) else dumps(value).encode()
        text = raw.decode('utf-8-sig') if media_type == 'application/json' else None
        self.connection.execute('''INSERT INTO documents
            (document_id,kind,media_type,sha256,original_bytes,content,metadata,json_content)
            VALUES(?,?,?,?,?,?,?,?)''', (key,kind,media_type,hashlib.sha256(raw).hexdigest(),len(raw),
            gzip.compress(raw,compresslevel=6,mtime=0),dumps(metadata or {}),text))

    def records(self, key):
        if self.reference is not None and self.connection.execute(
                'SELECT 1 FROM documents WHERE document_id=?', (key,)).fetchone() is None:
            yield from self.reference.records(key)
            return
        document = self.document(key)
        meta = json.loads(document['metadata'])
        storage, fields = meta.get('storage','archive'),meta.get('fields',[])
        if storage == 'market_data':
            mapping = {'instrument_id':'series_id','session_date':'observation_date'}
            cursor = self.connection.execute('SELECT * FROM market_data WHERE source_id=? ORDER BY source_row',(key,))
            for row in cursor:
                yield {name:'' if row[mapping.get(name,name)] is None else str(row[mapping.get(name,name)]) for name in fields}
        elif storage in ('configurations','executions'):
            if storage == 'configurations':
                cursor = self.connection.execute('SELECT * FROM configurations WHERE source_id=? ORDER BY source_row',(key,))
                mapping = {}
            else:
                cursor = self.connection.execute('''SELECT e.*,c.config_key,c.family,c.label AS rule_label,
                    d.sha256 AS dataset_manifest_sha256 FROM executions e
                    JOIN configurations c USING(configuration_id) JOIN documents d ON d.document_id=e.dataset_id
                    WHERE e.source_id=? ORDER BY e.source_row''',(key,))
                mapping = {'calculator_version':'engine_version'}
            for row in cursor:
                yield {name:'' if row[mapping.get(name,name)] is None else str(row[mapping.get(name,name)]) for name in fields}
        elif storage == 'daily_blocks':
            for row in self.daily_records(source_id=key):
                yield {name:'' if row[name] is None else str(row[name]) for name in fields}
        else:
            raw = self.raw(key)
            if key.endswith('.gz'):
                raw = gzip.decompress(raw)
            yield from csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''))

    def physical_daily(self, execution_id=None, source_id=None):
        sql = '''SELECT b.* FROM daily_results b JOIN executions e USING(execution_key)
            JOIN documents d ON d.document_key=b.source_key'''
        where, parameters = [],[]
        if execution_id is not None:
            where.append('e.execution_id=?'); parameters.append(execution_id)
        if source_id is not None:
            where.append('d.document_id=?'); parameters.append(source_id)
        sql += (' WHERE '+' AND '.join(where) if where else '')+' ORDER BY b.source_key,b.first_source_row'
        fields = self.json('system/daily-block-layout')['fields']
        for block in self.connection.execute(sql,parameters):
            raw = gzip.decompress(block['payload'])
            if hashlib.sha256(raw).hexdigest() != block['payload_sha256']:
                raise ValueError('Huella de bloque distinta: '+str(block['block_id']))
            records = json.loads(raw)
            if len(records) != block['row_count']:
                raise ValueError('Cobertura de bloque distinta: '+str(block['block_id']))
            for values in records:
                yield dict(zip(fields,values)),block

    def daily_records(self, execution_id=None, source_id=None):
        if self.reference is not None:
            yield from self.reference.daily_records(execution_id,source_id)
            return
        if self._documents is None:
            self._documents = dict(self.connection.execute('SELECT document_key,document_id FROM documents'))
            self._executions = {r['execution_key']:dict(r) for r in self.connection.execute('''SELECT e.*,c.config_key,
                c.family,c.label AS rule_label FROM executions e JOIN configurations c USING(configuration_id)''')}
        for row,block in self.physical_daily(execution_id,source_id):
            execution = self._executions[block['execution_key']]
            row.update(execution_id=execution['execution_id'],window_id=block['window_id'],
                       source_id=self._documents[block['source_key']])
            for code,target,values in [('segment_code','segment',('IS','OOS')),
                    ('alternative_code','alternative',('buy_hold','strategy')),
                    ('row_kind_code','row_kind',('base','observation')),
                    ('operation_code','operation',('none','buy','sell'))]:
                row[target] = values[row.pop(code)]
            for code,target in [('signal_valid_code','signal_valid'),('target_exposure_code','target_exposure')]:
                value = row.pop(code)
                row[target] = None if value is None else '' if value == -1 else str(value)
            key = row.pop('operation_source_key')
            row['operation_source_id'] = self._documents[key] if key is not None else None
            row.update({name:execution[name] for name in ('case_key','case_id','config_key','family','length_years','rule_label')})
            yield row

    def operation_records(self, execution_id):
        execution = self.connection.execute('SELECT campaign_id FROM executions WHERE execution_id=?',(execution_id,)).fetchone()
        if execution is None:
            raise KeyError(execution_id)
        for row in self.records('campaigns/'+execution['campaign_id']+'/operations.csv'):
            if row['execution_id'] == execution_id:
                yield row

    def frame(self, key):
        import pandas as pd
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream,fieldnames=json.loads(self.document(key)['metadata'])['fields'])
        writer.writeheader(); writer.writerows(self.records(key)); stream.seek(0)
        return pd.read_csv(stream,float_precision='round_trip',keep_default_na=True)

    def add_evaluations(self, key, rows, kind='analysis'):
        rows = list(rows)
        if not rows:
            raise ValueError('El conjunto debe tener al menos una fila: '+key)
        fields = list(rows[0])
        normalized = [{name:'' if row[name] is None else str(row[name]) for name in fields} for row in rows]
        stream = io.StringIO(newline=''); writer = csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader(); writer.writerows(normalized)
        self.put_document(key,stream.getvalue().encode(),kind,'text/csv',
                          {'storage':'archive','fields':fields,'rows':len(rows)})

    def verify_source(self, key, expected):
        document = self.document(key)
        if document['sha256'] != expected:
            raise ValueError('Identidad de procedencia distinta: '+key)
        if key in self._verified_sources:
            return
        if document['content'] is not None:
            if hashlib.sha256(self.raw(key)).hexdigest() != expected:
                raise ValueError('Contenido de procedencia distinto: '+key)
        elif json.loads(document['metadata']).get('storage') == 'daily_blocks':
            # La comparación completa contra el origen queda en el recibo de conservación.
            count = sum(1 for _ in self.physical_daily(source_id=key))
            if count != document['row_count']:
                raise ValueError('Cantidad de observaciones distinta: '+key)
        else:
            raise ValueError('Contenido no retenido: '+key)
        self._verified_sources.add(key)

    def finish(self):
        if not self.readonly:
            self.connection.commit()

    def inspect(self):
        tables = [r[0] for r in self.connection.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")]
        return {'tables':tables,'counts':{name:self.connection.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in tables},
                'logical_daily_rows':self.connection.execute('SELECT sum(row_count) FROM daily_results').fetchone()[0],
                'integrity':self.connection.execute('PRAGMA integrity_check').fetchone()[0],
                'foreign_key_errors':[tuple(r) for r in self.connection.execute('PRAGMA foreign_key_check')]}


class AnalysisWorkspace(Database):
    def __init__(self, reference):
        super().__init__(':memory:',readonly=False,reference=reference)
        self.connection.executescript((HERE/'schema.sql').read_text())
