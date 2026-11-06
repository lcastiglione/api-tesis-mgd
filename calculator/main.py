"""Consultas y comprobaciones del estudio sin modificar la base entregada."""

import argparse
from datetime import datetime,timezone
from pathlib import Path
import uuid

from .database import AnalysisWorkspace,Database,dumps


def analyze(database, identity=None):
    from . import analysis_sql
    from . import statistics_sql
    from . import matrix_sql
    from .verify_outputs import compare_analyses
    identity = identity or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    if not identity or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in identity):
        raise ValueError('Identificador de análisis inválido.')
    workspace = AnalysisWorkspace(database)
    try:
        namespace = 'analysis/v9/'+identity
        analysis_sql.run(workspace,namespace)
        statistics_sql.build(workspace,namespace)
        matrix_sql.main(workspace,namespace)
        result = compare_analyses(workspace,namespace)
        return {'analysis_id':identity,**result,'retention':'Temporary in-memory workspace; input unchanged.'}
    finally:
        workspace.close()


def main():
    parser = argparse.ArgumentParser(description='Consulta y comprobación de SQLite v2 compacto.')
    parser.add_argument('--database',type=Path,required=True)
    commands = parser.add_subparsers(dest='command',required=True)
    commands.add_parser('inspect')
    commands.add_parser('validate')
    analysis = commands.add_parser('analyze'); analysis.add_argument('--analysis-id')
    run = commands.add_parser('run-case')
    run.add_argument('--instrument',required=True); run.add_argument('--configuration',required=True)
    run.add_argument('--length',type=int,required=True); run.add_argument('--execution-id',required=True)
    args = parser.parse_args()
    db = Database(args.database)
    try:
        if args.command == 'inspect':
            result = db.inspect()
        elif args.command == 'validate':
            from .validate_database import validate
            result = validate(db)
        elif args.command == 'run-case':
            from .runner import run_case
            result = run_case(db,args.instrument,args.configuration,args.length,args.execution_id)
        elif args.command == 'analyze':
            result = analyze(db,args.analysis_id)
        print(dumps(result))
    finally:
        db.close()


if __name__ == '__main__':
    main()
