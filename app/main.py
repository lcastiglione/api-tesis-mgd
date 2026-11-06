"""API de consulta y comprobación del estudio; la SQLite entregada es inmutable."""
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from itertools import islice
import json
import os
from pathlib import Path
from threading import Lock
from typing import Annotated, Iterator, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from calculator.database import Database
from .preparation import DatabasePreparation

ROOT = Path(__file__).resolve().parents[1]
API_TITLE = 'API Tesis Robustez - MGD'
VERSION = (ROOT/'VERSION').read_text().strip()
DATABASE_PATH = Path(os.getenv('DATABASE_PATH',str(ROOT/'data/study.sqlite')))
SIMULATION_LOCK = Lock()
Instrument = Literal['SPY','QQQ','IWM','EFA','EEM','TLT','GLD']
Length = Literal[1,2,3,5,7]
LengthQuery = Literal['1','2','3','5','7']
Family = Literal['P-SMA','MOM','MR-Z']
Identifier = Annotated[str,Field(pattern=r'^[A-Za-z0-9_.:-]{1,100}$')]
TABLES = ('documents','market_data','configurations','executions','daily_results','evaluation_results')


@contextmanager
def open_database() -> Iterator[Database]:
    """Crea y cierra una conexión de lectura en el mismo hilo de la consulta."""
    if not DATABASE_PATH.is_file():
        raise HTTPException(503,'La base se está preparando; consultar el estado en /.',headers={'Retry-After':'2'})
    database = Database(DATABASE_PATH,readonly=True)
    try:
        yield database
    finally:
        database.close()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Abre la página de estado mientras se descarga y verifica la base."""
    preparation = DatabasePreparation(DATABASE_PATH,url=os.getenv('DATABASE_URL',''))
    application.state.preparation = preparation
    preparation.start()
    try:
        yield
    finally:
        preparation.close()


app = FastAPI(title=API_TITLE,version=VERSION,lifespan=lifespan,docs_url=None,redoc_url=None,
             description='Consulta de datos históricos y comprobación de casos. La base se abre en modo de solo lectura. '
             'Las fracciones se conservan: 0.10 representa 10%.\n\n'
             '⚠️ **Advertencia:** la API recibe únicamente parámetros validados. '
             'Las consultas se definen en el servidor y los valores se envían por separado para prevenir inyecciones SQL. '
             'No se admite código SQL del cliente.')
app.mount('/assets',StaticFiles(directory=ROOT/'app/static'),name='assets')


def require_ready(request: Request) -> None:
    """Responde 503 mientras la base falta, se descarga o se verifica."""
    status = request.app.state.preparation.snapshot()
    if not status['ready']:
        raise HTTPException(503,detail={'message':status['message'],'phase':status['phase'],
                                       'status_url':'/status'},headers={'Retry-After':'2'})


api = APIRouter(dependencies=[Depends(require_ready)])


class Pagination(BaseModel):
    """Parámetros admitidos: cualquier campo adicional se rechaza."""
    model_config = ConfigDict(extra='forbid')
    limit: int = Field(default=100,ge=1,le=1000)
    offset: int = Field(default=0,ge=0,le=1000000)


class ConfigurationFilters(Pagination):
    instrument: Instrument | None = None
    family: Family | None = None


class QuoteFilters(Pagination):
    """Limita las cotizaciones a los siete ETF y a un intervalo de fechas válido."""
    ticker: Instrument = Field(description='ETF disponible en la base del estudio.')
    start_date: date | None = Field(default=None,description='Fecha inicial incluida, en formato AAAA-MM-DD.')
    end_date: date | None = Field(default=None,description='Fecha final incluida, en formato AAAA-MM-DD.')

    @model_validator(mode='after')
    def validate_date_range(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError('start_date debe ser anterior o igual a end_date.')
        return self


class ExecutionFilters(Pagination):
    instrument: Instrument | None = None
    configuration: Identifier | None = None
    length: LengthQuery | None = None


class IndicatorFilters(Pagination):
    segment: Identifier | None = None
    metric: Identifier | None = None


class DailyFilters(Pagination):
    segment: Literal['IS','OOS'] | None = None
    alternative: Literal['strategy','buy_hold'] | None = None
    window_id: Identifier | None = None


class CountFilters(BaseModel):
    model_config = ConfigDict(extra='forbid')
    instrument: Instrument | None = None


class VerificationRequest(BaseModel):
    """Caso registrado que se vuelve a calcular y compara en memoria."""
    model_config = ConfigDict(extra='forbid')
    instrument: Instrument = 'SPY'
    configuration: str = Field(default='sma200',pattern=r'^[a-z0-9.-]{1,40}$')
    length: Length = 1


@app.get('/',include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(ROOT/'app/static/index.html',headers={'Cache-Control':'no-store'})


@app.get('/status',tags=['Estado'])
def status(request: Request) -> JSONResponse:
    """Informa avance real y preparación, incluso mientras la base no existe."""
    return JSONResponse({'api_version':VERSION,**request.app.state.preparation.snapshot()},
                        headers={'Cache-Control':'no-store'})


@app.get('/docs',include_in_schema=False)
@app.get('/redoc',include_in_schema=False)
def documentation() -> RedirectResponse:
    """Conserva los enlaces anteriores y abre la consola personalizada."""
    return RedirectResponse('/')


@app.get('/health',tags=['Estado'],dependencies=[Depends(require_ready)])
def health() -> dict:
    """Indica preparación real: consulta un registro de la base verificada."""
    with open_database() as database:
        current = database.json('system/current')
    return {'status':'ok','api_version':VERSION,'database_version':current['database_version'],
            'storage_revision':current['storage_revision'],'read_only':True}


@api.get('/api/v1/study',tags=['Estudio'])
def study() -> dict:
    with open_database() as database:
        counts = {name:database.connection.execute('SELECT count(*) FROM '+name).fetchone()[0]
                  for name in TABLES}
        logical = database.connection.execute('SELECT sum(row_count) FROM daily_results').fetchone()[0]
        return {'current':database.json('system/current'),'physical_rows':counts,'logical_daily_rows':logical,
                'logical_total_rows':sum(counts.values())-counts['daily_results']+logical,
                'scope':'Campaña histórica; sin agregar casos ni modificar los resultados.'}


@api.get('/api/v1/instruments',tags=['Estudio'])
def instruments() -> dict:
    with open_database() as database:
        return {'items':[dict(row) for row in database.connection.execute('''SELECT c.instrument_id,
            count(DISTINCT c.configuration_id) AS configurations,count(e.execution_id) AS executions
            FROM configurations c LEFT JOIN executions e USING(configuration_id)
            GROUP BY c.instrument_id ORDER BY c.instrument_id''')]}


@api.get('/api/v1/quotes',tags=['Cotizaciones'],summary='Consultar las cotizaciones guardadas')
def quotes(filters: Annotated[QuoteFilters,Query()]) -> dict:
    """Devuelve precios históricos de SQLite; ticker se elige en un selector cerrado.

    Las fechas son inclusivas y los registros se ordenan desde el más antiguo.
    Los precios conservan el texto decimal original. open, high, low y close
    corresponden a OHLC; adj_close y adj_open/adj_high/adj_low son precios ajustados.
    La consulta no descarga precios nuevos ni modifica la base.
    """
    start_date = filters.start_date.isoformat() if filters.start_date else None
    end_date = filters.end_date.isoformat() if filters.end_date else None
    with open_database() as database:
        rows = database.connection.execute('''
            SELECT dataset_id,series_id AS ticker,observation_date AS date,
                   open,high,low,close,adj_close,volume,dividends,stock_splits,
                   capital_gains,adjustment_factor,adj_open,adj_high,adj_low
            FROM market_data
            WHERE record_type='prices' AND series_id=?
              AND (? IS NULL OR observation_date>=?)
              AND (? IS NULL OR observation_date<=?)
            ORDER BY observation_date,source_id,source_row LIMIT ? OFFSET ?''',
            (filters.ticker,start_date,start_date,end_date,end_date,filters.limit+1,filters.offset)).fetchall()
    return {'ticker':filters.ticker,'start_date':start_date,'end_date':end_date,
            'items':[dict(row) for row in rows[:filters.limit]],
            'limit':filters.limit,'offset':filters.offset,'has_more':len(rows)>filters.limit,
            'scope':'Cotizaciones históricas guardadas; precios originales como texto exacto y volumen como entero.'}


@api.get('/api/v1/configuration-counts',tags=['Estudio'])
def configuration_counts(filters: Annotated[CountFilters,Query()]) -> dict:
    """Cuenta por familia mediante una consulta definida íntegramente en el servidor."""
    with open_database() as database:
        rows=database.connection.execute('''SELECT family,count(*) AS total FROM configurations
            WHERE (? IS NULL OR instrument_id=?) GROUP BY family ORDER BY family''',
            (filters.instrument,filters.instrument)).fetchall()
        return {'instrument':filters.instrument,'items':[dict(row) for row in rows]}


@api.get('/api/v1/configurations',tags=['Estudio'])
def configurations(filters: Annotated[ConfigurationFilters,Query()]) -> dict:
    instrument,family,limit,offset=filters.instrument,filters.family,filters.limit,filters.offset
    with open_database() as database:
        where,parameters = [],[]
        for column,value in [('instrument_id',instrument),('family',family)]:
            if value is not None:
                where.append(column+'=?');parameters.append(value)
        sql = 'SELECT * FROM configurations'+(' WHERE '+' AND '.join(where) if where else '')
        rows = database.connection.execute(sql+' ORDER BY configuration_key LIMIT ? OFFSET ?',parameters+[limit+1,offset]).fetchall()
        return {'items':[dict(row) for row in rows[:limit]],'limit':limit,'offset':offset,'has_more':len(rows)>limit}


@api.get('/api/v1/executions',tags=['Estudio'])
def executions(filters: Annotated[ExecutionFilters,Query()]) -> dict:
    instrument,configuration,length=filters.instrument,filters.configuration,filters.length
    limit,offset=filters.limit,filters.offset
    with open_database() as database:
        where,parameters = [],[]
        for column,value in [('c.instrument_id',instrument),('c.config_key',configuration),('e.length_years',length)]:
            if value is not None:
                where.append(column+'=?');parameters.append(value)
        sql = '''SELECT e.execution_id,e.campaign_id,e.case_key,e.length_years,e.engine_version,e.status,
                 c.instrument_id,c.config_key,c.family FROM executions e JOIN configurations c USING(configuration_id)'''
        rows = database.connection.execute(sql+(' WHERE '+' AND '.join(where) if where else '')+
            ' ORDER BY e.execution_key LIMIT ? OFFSET ?',parameters+[limit+1,offset]).fetchall()
        return {'items':[dict(row) for row in rows[:limit]],'limit':limit,'offset':offset,'has_more':len(rows)>limit}


def require_execution(database: Database, execution_id: str) -> None:
    """Distingue un identificador inexistente de un caso sin filas para un filtro."""
    if database.connection.execute('SELECT 1 FROM executions WHERE execution_id=?',(execution_id,)).fetchone() is None:
        raise HTTPException(404,'Ejecución no encontrada; consultar /api/v1/executions.')


@api.get('/api/v1/executions/{execution_id}/indicators',tags=['Detalle'])
def indicators(execution_id: str,filters: Annotated[IndicatorFilters,Query()]) -> dict:
    segment,metric,limit,offset=filters.segment,filters.metric,filters.limit,filters.offset
    with open_database() as database:
        require_execution(database,execution_id)
        clauses,parameters = ['execution_id=?'],[execution_id]
        for column,value in [('segment',segment),('metric',metric)]:
            if value is not None:
                clauses.append(column+'=?');parameters.append(value)
        rows = database.connection.execute('SELECT * FROM indicators WHERE '+' AND '.join(clauses)+
            ' ORDER BY source_id,source_row,metric LIMIT ? OFFSET ?',parameters+[limit+1,offset]).fetchall()
        return {'items':[dict(row) for row in rows[:limit]],'limit':limit,'offset':offset,'has_more':len(rows)>limit,
                'units':'fraction = fracción (0.10 = 10%); exact_value conserva el texto original; consultar status antes de interpretar.'}


@api.get('/api/v1/executions/{execution_id}/daily',tags=['Detalle'])
def daily(execution_id: str,filters: Annotated[DailyFilters,Query()]) -> dict:
    segment,alternative,window_id=filters.segment,filters.alternative,filters.window_id
    limit,offset=filters.limit,filters.offset
    with open_database() as database:
        require_execution(database,execution_id)
        records = (row for row in database.daily_records(execution_id=execution_id)
                   if (segment is None or row['segment']==segment) and
                   (alternative is None or row['alternative']==alternative) and
                   (window_id is None or row['window_id']==window_id))
        rows = list(islice(records,offset,offset+limit+1))
        return {'items':rows[:limit],'limit':limit,'offset':offset,'has_more':len(rows)>limit,
                'scope':'Observaciones recuperadas de bloques comprimidos; se conservan decimales, vacíos y estados.'}


@api.get('/api/v1/executions/{execution_id}/operations',tags=['Detalle'])
def operations(execution_id: str,filters: Annotated[Pagination,Query()]) -> dict:
    limit,offset=filters.limit,filters.offset
    with open_database() as database:
        require_execution(database,execution_id)
        rows = list(islice(database.operation_records(execution_id),offset,offset+limit+1))
        return {'items':rows[:limit],'limit':limit,'offset':offset,'has_more':len(rows)>limit}


@api.post('/api/v1/verify-case',tags=['Comprobación'])
def verify_case(request: VerificationRequest) -> dict:
    """Recalcula un caso registrado en memoria; no crea una ejecución persistida."""
    if not SIMULATION_LOCK.acquire(blocking=False):
        raise HTTPException(429,'Ya hay una comprobación en curso; intentar al finalizar.')
    try:
        from calculator.runner import run_case
        with open_database() as database:
            try:
                return run_case(database,request.instrument,request.configuration,request.length,
                                'api-check-'+uuid4().hex,verify=True)
            except ValueError as error:
                raise HTTPException(400,str(error)) from error
            except AssertionError as error:
                raise HTTPException(409,'La comprobación encontró diferencias: '+str(error)) from error
    finally:
        SIMULATION_LOCK.release()


@app.get('/tutorials/api',include_in_schema=False)
def tutorial() -> FileResponse:
    catalog = json.loads((ROOT/'docs/tutorial-content.json').read_text())
    version = int(catalog['api'].get('version',catalog['version']))
    return FileResponse(ROOT/'docs'/f'api-tutorial-v{version}.pdf',media_type='application/pdf')


app.include_router(api)
