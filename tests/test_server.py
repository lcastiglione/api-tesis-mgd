"""Verifica el servidor real con trabajadores lentos o fallidos, sin depender de Drive."""
import json
from pathlib import Path
import socket
import tempfile
from threading import Event, Thread
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import urlopen
import unittest

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
import uvicorn

from app.preparation import DatabasePreparation, describe_error
from app.server import ImmediateServer
from app.web import ApiRuntime, create_app


class SlowPreparation:
    """No toca archivos: retiene la base hasta que la prueba la libera."""
    def __init__(self):
        self.started = Event()
        self.closed = False

    def start(self):
        self.started.set()

    def close(self):
        self.closed = True

    def snapshot(self):
        return {'phase':'downloading','ready':False,'message':'Descarga de prueba.',
                'database':{'phase':'downloading','installed':False,'bytes':100,'read_only':True},
                'download':{'percent':50,'received_bytes':50,'total_bytes':100},
                'error':None,'retry_in_seconds':None}


class ServerTests(unittest.TestCase):
    def test_listener_and_ui_are_available_before_slow_workers_finish(self):
        release = Event()
        loading = Event()
        preparation = SlowPreparation()

        async def example(request):
            return JSONResponse({'forwarded':True})

        def loader():
            loading.set()
            release.wait(5)
            return Starlette(routes=[Route('/example',example)])

        runtime = ApiRuntime(preparation=preparation,api_loader=loader)
        application = create_app(runtime,start_on_lifespan=False)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            port = listener.getsockname()[1]
        server = ImmediateServer(uvicorn.Config(application,host='127.0.0.1',port=port,log_level='error'),runtime)
        worker = Thread(target=server.run,daemon=True)
        original_start = runtime.start
        listening = []

        def start():
            # La conexión TCP debe existir antes de iniciar ambos trabajadores.
            with socket.create_connection(('127.0.0.1',port),timeout=1):
                listening.append(True)
            original_start()

        runtime.start = start
        worker.start()
        start_time = monotonic()
        try:
            self.assertTrue(loading.wait(5))
            self.assertTrue(preparation.started.wait(5))
            self.assertEqual(listening,[True])
            base = f'http://127.0.0.1:{port}'
            for path in ['/','/assets/status.js','/status']:
                with urlopen(base+path,timeout=2) as response:
                    self.assertEqual(response.status,200)
            with urlopen(base+'/status',timeout=2) as response:
                status = json.load(response)
            self.assertFalse(status['api_loaded'])
            self.assertEqual(status['download']['percent'],50)
            with self.assertRaises(HTTPError) as raised:
                urlopen(base+'/example',timeout=2)
            self.assertEqual(raised.exception.code,503)
            self.assertLess(monotonic()-start_time,3)
            release.set()
            self.assertTrue(runtime.api_ready.wait(3))
            with urlopen(base+'/example',timeout=2) as response:
                self.assertEqual(json.load(response),{'forwarded':True})
        finally:
            release.set()
            server.should_exit = True
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(preparation.closed)

    def test_backend_failure_does_not_remove_home_or_status(self):
        def fail():
            raise RuntimeError('Fallo controlado de importación.')
        runtime = ApiRuntime(preparation=SlowPreparation(),api_loader=fail)
        with TestClient(create_app(runtime)) as client:
            deadline = monotonic()+3
            while not runtime.error and monotonic()<deadline:
                sleep(.01)
            self.assertEqual(client.get('/').status_code,200)
            status = client.get('/status').json()
            self.assertEqual(status['error']['code'],'api_initialization')
            self.assertEqual(status['services']['api'],'error')
            self.assertEqual(client.get('/api/v1/study').status_code,503)

    def test_missing_manifest_is_reported_in_status_after_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            preparation = DatabasePreparation(Path(folder)/'study.sqlite',
                manifest_path=Path(folder)/'missing.json',retry_delay=30)
            runtime = ApiRuntime(preparation=preparation,api_loader=lambda:Starlette())
            with TestClient(create_app(runtime)) as client:
                deadline = monotonic()+3
                while preparation.snapshot()['phase']!='error' and monotonic()<deadline:
                    sleep(.01)
                self.assertEqual(client.get('/').status_code,200)
                status = client.get('/status').json()
                self.assertEqual(status['error']['code'],'database_configuration')
                self.assertIsNotNone(status['retry_in_seconds'])

    def test_network_cause_is_visible_and_retained_until_recovery(self):
        preparation = DatabasePreparation(Path('/unused.sqlite'))
        preparation.error = describe_error(OSError('[Errno 101] Network is unreachable'))
        preparation.report('error',preparation.error['message'])
        self.assertEqual(preparation.snapshot()['error']['code'],'network_unreachable')
        self.assertIn('Sin conexión de red',preparation.snapshot()['error']['message'])
        preparation.report('downloading','Se reintenta.')
        self.assertIsNotNone(preparation.snapshot()['error'])
        preparation.report('ready','Lista')
        self.assertIsNone(preparation.snapshot()['error'])
