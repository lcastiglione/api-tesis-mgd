"""Comprueba el estado público durante descarga, fallos y reposición de la base."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.bootstrap import download_archive
from app.preparation import DatabasePreparation


def wait_for(check, timeout: float = 5) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if check():
            return
        sleep(.01)
    raise AssertionError('No se observó el estado esperado dentro del plazo.')


class PreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        seed = self.root/'seed.sqlite'
        with closing(sqlite3.connect(seed)) as connection:
            connection.execute('CREATE TABLE example (number INTEGER)')
        self.raw = seed.read_bytes()
        self.path = self.root/'data/study.sqlite'
        self.manifest = self.root/'manifest.json'
        self.manifest.write_text(json.dumps({
            'download_format':'sqlite', 'download_url':'https://drive.google.com/file/d/example/view',
            'database_version':2, 'storage_revision':3,
            'database':{'bytes':len(self.raw),'sha256':hashlib.sha256(self.raw).hexdigest()},
        }))

    def tearDown(self) -> None:
        self.folder.cleanup()

    def preparation(self, path=None, url='') -> DatabasePreparation:
        return DatabasePreparation(path or self.path, url, manifest_path=self.manifest,
                                   poll_interval=.01, retry_delay=.15)

    def test_home_and_status_work_during_download_and_after_deletion(self) -> None:
        """La página responde antes de tener base; el borrado dispara otra descarga."""
        entered = [Event(), Event()]
        release = [Event(), Event()]
        calls = []

        def download(url, target, max_bytes, *, progress, cancel):
            index = len(calls)
            calls.append(url)
            target.write_bytes(self.raw[:len(self.raw)//2])
            progress(len(self.raw)//2, len(self.raw))
            entered[index].set()
            while not release[index].wait(.01):
                if cancel.is_set():
                    raise InterruptedError('Prueba interrumpida.')
            target.write_bytes(self.raw)
            progress(len(self.raw), len(self.raw))

        with patch.object(main,'DATABASE_PATH',self.path), \
             patch.object(main,'DatabasePreparation',side_effect=self.preparation), \
             patch('app.bootstrap.download_archive',side_effect=download), TestClient(main.app) as client:
            self.assertTrue(entered[0].wait(5))
            self.assertEqual(client.get('/').status_code,200)
            self.assertIn('API Tesis Robustez - MGD',client.get('/').text)
            self.assertEqual(client.get('/assets/status.js').status_code,200)
            self.assertEqual(client.get('/docs').status_code,200)
            self.assertEqual(client.get('/tutorials/api').status_code,200)
            status = client.get('/status')
            self.assertIn('no-store',status.headers['cache-control'])
            self.assertEqual(status.json()['phase'],'downloading')
            self.assertEqual(status.json()['download']['percent'],50)
            self.assertFalse(status.json()['ready'])
            for route in ['/health','/api/v1/study','/api/v1/instruments']:
                result = client.get(route)
                self.assertEqual(result.status_code,503)
                self.assertEqual(result.headers['Retry-After'],'2')
            self.assertEqual(client.post('/api/v1/verify-case',json={}).status_code,503)
            release[0].set()
            wait_for(lambda:client.get('/status').json()['ready'])
            self.assertTrue(client.get('/status').json()['database']['installed'])
            self.path.unlink()
            self.assertFalse(client.get('/status').json()['ready'])
            self.assertTrue(entered[1].wait(5))
            self.assertEqual(client.get('/status').json()['phase'],'downloading')
            self.assertEqual(client.get('/api/v1/study').status_code,503)
            release[1].set()
            wait_for(lambda:client.get('/status').json()['ready'])
            self.assertEqual(self.path.read_bytes(),self.raw)
            self.assertEqual(len(calls),2)

    def test_failed_download_stays_visible_and_retries_automatically(self) -> None:
        attempts = []
        def download(url,target,max_bytes,**options):
            attempts.append(url)
            if len(attempts) == 1:
                raise OSError('Sin conexión en la prueba.')
            target.write_bytes(self.raw)
        preparation = self.preparation()
        with patch('app.bootstrap.download_archive',side_effect=download):
            preparation.start()
            try:
                wait_for(lambda:preparation.snapshot()['phase']=='error')
                self.assertFalse(preparation.snapshot()['ready'])
                self.assertIsNotNone(preparation.snapshot()['retry_in_seconds'])
                wait_for(lambda:preparation.snapshot()['ready'])
                self.assertEqual(len(attempts),2)
            finally:
                preparation.close()

    def test_existing_base_is_verified_without_download(self) -> None:
        self.path.parent.mkdir()
        self.path.write_bytes(self.raw)
        with patch('app.bootstrap.download_archive') as download:
            preparation = self.preparation()
            preparation.start()
            try:
                self.assertTrue(preparation.ready_event.wait(5))
                self.assertTrue(preparation.snapshot()['ready'])
                download.assert_not_called()
            finally:
                preparation.close()

    def test_altered_base_never_enables_queries(self) -> None:
        self.path.parent.mkdir()
        self.path.write_bytes(self.raw[:-1] + bytes([self.raw[-1] ^ 1]))
        preparation = self.preparation()
        preparation.start()
        try:
            wait_for(lambda:preparation.snapshot()['phase']=='error')
            self.assertFalse(preparation.snapshot()['ready'])
            self.assertEqual(self.path.stat().st_size,len(self.raw))
        finally:
            preparation.close()

    def test_drive_progress_uses_received_bytes_and_checks_limit(self) -> None:
        observed = []
        def fake_download(**options):
            options['progress'](4,8)
            options['progress'](8,8)
            Path(options['output']).write_bytes(b'12345678')
        target = self.root/'download'
        with patch('gdown.download',side_effect=fake_download):
            download_archive('https://drive.google.com/file/d/example/view',target,8,
                             progress=lambda received,total:observed.append((received,total)))
        self.assertEqual(observed,[(4,8),(8,8)])
        with patch('gdown.download',side_effect=fake_download):
            with self.assertRaisesRegex(ValueError,'tamaño declarado'):
                download_archive('https://drive.google.com/file/d/example/view',target,7)


if __name__ == '__main__':
    unittest.main()
