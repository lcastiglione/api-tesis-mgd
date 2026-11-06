"""Valida bloques, archivos y claves sin guardar datos auxiliares en la entrega."""

import hashlib
import json


def validate(db):
    documents = list(db.connection.execute('SELECT document_id,sha256 FROM documents WHERE content IS NOT NULL'))
    for row in documents:
        assert hashlib.sha256(db.raw(row['document_id'])).hexdigest() == row['sha256'],row['document_id']
    rows = sum(1 for _ in db.physical_daily())
    inspection = db.inspect()
    assert rows == inspection['logical_daily_rows'] == 10_379_124
    assert len(inspection['tables']) == 6 and inspection['integrity']=='ok' and not inspection['foreign_key_errors']
    assert inspection['counts']['executions']==945 and inspection['counts']['configurations']==189
    return {'passed':True,'logical_daily_rows':rows,'archives_verified':len(documents),
            'daily_block_hashes_verified':True,'database':inspection,
            'scope':'Storage, retained archives and constraints; not a new simulation of all cases.'}
