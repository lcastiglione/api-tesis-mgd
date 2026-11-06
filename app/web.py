"""Sirve el panel ligero mientras la API y la base se preparan en paralelo."""
from contextlib import asynccontextmanager
import importlib
import logging
import os
from pathlib import Path
from threading import Event, Lock, Thread

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .preparation import DatabasePreparation

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


def load_api():
    """Importa FastAPI y sus rutas después de habilitar el puerto web."""
    return importlib.import_module('app.main').app


class ApiRuntime:
    """Mantiene separados el servidor web, la carga de la API y la base."""

    def __init__(self, preparation=None, api_loader=load_api) -> None:
        self.preparation = preparation or DatabasePreparation(
            Path(os.getenv('DATABASE_PATH',str(ROOT/'data/study.sqlite'))),
            url=os.getenv('DATABASE_URL',''))
        self.api_loader = api_loader
        self.backend = None
        self.error = None
        self.lock = Lock()
        self.stop_event = Event()
        self.api_ready = Event()
        self.started = False
        self.thread = Thread(target=self.load_backend,name='api-loader',daemon=True)
        self.version = (ROOT/'VERSION').read_text().strip()

    def start(self) -> None:
        with self.lock:
            if self.started:
                return
            self.started = True
        logger.info('Panel disponible. La API y la base se preparan en segundo plano.')
        self.thread.start()
        self.preparation.start()

    def close(self) -> None:
        self.stop_event.set()
        self.preparation.close()
        if self.thread.is_alive():
            self.thread.join(timeout=1)

    def load_backend(self) -> None:
        try:
            backend = self.api_loader()
            backend.state.preparation = self.preparation
            if self.stop_event.is_set():
                return
            with self.lock:
                self.backend = backend
                self.api_ready.set()
        except Exception:
            logger.exception('No se pudo cargar la API. El panel permanece disponible.')
            with self.lock:
                self.error = {'code':'api_initialization','message':'No se pudo iniciar la API de consultas.','source':'api'}

    def snapshot(self) -> dict:
        status = self.preparation.snapshot()
        with self.lock:
            api_loaded = self.backend is not None
            api_error = self.error
        status['ready'] = status['ready'] and api_loaded
        if api_error:
            status.update(phase='error',message=api_error['message'],error=api_error,retry_in_seconds=None)
        elif not api_loaded and status['database']['installed']:
            status.update(phase='starting',message='Se cargan las consultas de la API.')
        return {'api_version':self.version,'api_loaded':api_loaded,
                'services':{'api':'error' if api_error else 'ready' if api_loaded else 'loading',
                            'database':status['database']['phase']},**status}


class ApiDispatch:
    def __init__(self, runtime: ApiRuntime) -> None:
        self.runtime = runtime

    async def __call__(self, scope, receive, send) -> None:
        if self.runtime.backend is None:
            status = self.runtime.snapshot()
            response = JSONResponse({'detail':{'message':status['message'],'status_url':'/status'}},
                                    status_code=503,headers={'Retry-After':'1','Cache-Control':'no-store'})
            await response(scope,receive,send)
            return
        await self.runtime.backend(scope,receive,send)


def create_app(runtime: ApiRuntime, *, start_on_lifespan: bool = True) -> Starlette:
    """La ejecución Docker inicia los trabajadores únicamente después de abrir el puerto."""
    @asynccontextmanager
    async def lifespan(application):
        if start_on_lifespan:
            runtime.start()
        try:
            yield
        finally:
            runtime.close()

    async def home(request):
        return FileResponse(ROOT/'app/static/index.html',headers={'Cache-Control':'no-store'})

    async def status(request):
        return JSONResponse(runtime.snapshot(),headers={'Cache-Control':'no-store'})

    application = Starlette(routes=[Route('/',home),
        Mount('/assets',app=StaticFiles(directory=ROOT/'app/static')),
        Route('/status',status),Mount('/',app=ApiDispatch(runtime))],lifespan=lifespan)
    application.state.runtime = runtime
    return application
