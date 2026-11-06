"""Comprueba el contrato público con la base real, sin escribir resultados."""
import gzip
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.bootstrap import download_archive,ensure_database


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(main.app)
        cls.client.__enter__()
        if not main.app.state.preparation.ready_event.wait(timeout=120):
            raise AssertionError('La base real no quedó preparada: '+str(main.app.state.preparation.snapshot()))
        cls.execution = cls.client.get('/api/v1/executions',params={
            'instrument':'SPY','configuration':'sma200','length':1}).json()['items'][0]['execution_id']

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None,None,None)

    def test_study_counts_and_readonly(self) -> None:
        result = self.client.get('/api/v1/study').json()
        self.assertEqual(result['physical_rows']['executions'],945)
        self.assertEqual(result['physical_rows']['configurations'],189)
        self.assertEqual(result['physical_rows']['daily_results'],10206)
        self.assertEqual(result['logical_daily_rows'],10379124)
        self.assertEqual(result['logical_total_rows'],10786437)
        with main.open_database() as database:
            with self.assertRaises(sqlite3.OperationalError):
                database.connection.execute('DELETE FROM configurations')

    def test_pagination_and_details_match_database(self) -> None:
        result = self.client.get('/api/v1/configurations',params={'instrument':'SPY','limit':2}).json()
        self.assertEqual(len(result['items']),2)
        self.assertTrue(result['has_more'])
        result = self.client.get(f'/api/v1/executions/{self.execution}/daily',params={
            'segment':'OOS','alternative':'strategy','limit':2,'offset':1}).json()
        with main.open_database() as database:
            original = [row for row in database.daily_records(execution_id=self.execution)
                        if row['segment']=='OOS' and row['alternative']=='strategy'][1:3]
        self.assertEqual(result['items'],original)
        response = self.client.get(f'/api/v1/executions/{self.execution}/indicators',params={'limit':2})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json()['items']),2)
        self.assertEqual(self.client.get(f'/api/v1/executions/{self.execution}/operations?limit=2').status_code,200)

    def test_configuration_counts_with_fixed_filters(self) -> None:
        result=self.client.get('/api/v1/configuration-counts').json()
        self.assertEqual(result['items'],[{'family':'MOM','total':35},{'family':'MR-Z','total':119},{'family':'P-SMA','total':35}])
        result=self.client.get('/api/v1/configuration-counts',params={'instrument':'SPY'}).json()
        self.assertEqual(result['items'],[{'family':'MOM','total':5},{'family':'MR-Z','total':17},{'family':'P-SMA','total':5}])

    def test_client_sql_and_unlisted_parameters_are_rejected(self) -> None:
        self.assertEqual(self.client.post('/api/v1/query',json={'sql':'SELECT * FROM configurations'}).status_code,404)
        self.assertEqual(self.client.get('/api/v1/schema').status_code,404)
        for path in ['/api/v1/configurations','/api/v1/executions','/api/v1/configuration-counts',
                     f'/api/v1/executions/{self.execution}/indicators',
                     f'/api/v1/executions/{self.execution}/daily',
                     f'/api/v1/executions/{self.execution}/operations']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path,params={'sql':'DELETE FROM configurations'}).status_code,422)
        self.assertEqual(self.client.post('/api/v1/verify-case',json={'sql':'SELECT 1'}).status_code,422)

    def test_validation_and_missing_execution(self) -> None:
        self.assertEqual(self.client.get('/api/v1/configurations?limit=1001').status_code,422)
        self.assertEqual(self.client.get('/api/v1/executions?instrument=INVALID').status_code,422)
        self.assertEqual(self.client.get('/api/v1/executions/missing/daily').status_code,404)
        self.assertEqual(self.client.post('/api/v1/verify-case',json={'length':4}).status_code,422)
        main.SIMULATION_LOCK.acquire()
        try:
            self.assertEqual(self.client.post('/api/v1/verify-case',json={}).status_code,429)
        finally:
            main.SIMULATION_LOCK.release()

    def test_injection_text_does_not_change_query_scope(self) -> None:
        before=self.client.get('/api/v1/study').json()['physical_rows']
        attacks=[('/api/v1/configuration-counts',{'instrument':"SPY' OR 1=1 --"}),
                 ('/api/v1/executions',{'configuration':"sma200'; DROP TABLE configurations; --"}),
                 (f'/api/v1/executions/{self.execution}/indicators',{'metric':"return_annualized' OR 1=1 --"})]
        for path,parameters in attacks:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path,params=parameters).status_code,422)
        self.assertEqual(self.client.get('/api/v1/study').json()['physical_rows'],before)

    def test_one_real_case_matches_original(self) -> None:
        before = self.client.get('/api/v1/study').json()['physical_rows']
        response = self.client.post('/api/v1/verify-case',json={'instrument':'SPY','configuration':'sma200','length':1})
        self.assertEqual(response.status_code,200,response.text)
        result = response.json()
        self.assertTrue(result['passed'])
        self.assertTrue(all(check['equivalent'] for check in result['comparisons'].values()))
        self.assertEqual(self.client.get('/api/v1/study').json()['physical_rows'],before)
        output = os.getenv('TEST_EVIDENCE_DIR')
        if output:
            Path(output).mkdir(parents=True,exist_ok=True)
            Path(output,'verify-case.json').write_text(json.dumps(result,indent=2)+'\n')

    def test_api_manual_and_parameter_only_contract(self) -> None:
        self.assertEqual(self.client.get('/viewer/').status_code,404)
        self.assertEqual(self.client.get('/tutorials/powerbi').status_code,404)
        response=self.client.get('/tutorials/api')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertEqual(response.headers['content-type'],'application/pdf')
        catalog=json.loads((main.ROOT/'docs/tutorial-content.json').read_text())
        version=catalog['api']['version']
        self.assertEqual(response.content,(main.ROOT/'docs'/f'api-tutorial-v{version}.pdf').read_bytes())
        contract=self.client.get('/openapi.json').json()
        self.assertEqual(contract['info']['version'],'2.2.0')
        self.assertNotIn('/api/v1/query',contract['paths'])
        self.assertNotIn('/api/v1/schema',contract['paths'])
        self.assertIn('inyecciones SQL',contract['info']['description'])
        self.assertEqual(len(self.client.get('/api/v1/instruments').json()['items']),7)


class DownloadTests(unittest.TestCase):
    def test_raw_sqlite_download_is_verified_and_reused(self) -> None:
        """Acepta SQLite público sin comprimir y rechaza una copia con otra huella."""
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            seed=root/'seed.sqlite'
            with closing(sqlite3.connect(seed)) as connection:
                connection.execute('CREATE TABLE example (number INTEGER)')
                connection.execute('INSERT INTO example VALUES (7)')
                connection.commit()
            raw=seed.read_bytes()
            manifest={'download_url':'https://drive.google.com/file/d/example/view',
                      'download_format':'sqlite',
                      'database':{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}
            manifest_path=root/'manifest.json'
            manifest_path.write_text(json.dumps(manifest))
            destination=root/'data/study.sqlite'
            def fake_download(url: str, target: Path, max_bytes: int, **options) -> None:
                self.assertEqual(max_bytes,len(raw))
                target.write_bytes(raw)
            with patch('app.bootstrap.download_archive',side_effect=fake_download) as download:
                ensure_database(destination,manifest_path)
                self.assertEqual(destination.read_bytes(),raw)
                ensure_database(destination,manifest_path)
                self.assertEqual(download.call_count,1)
            destination.unlink()
            invalid=raw[:-1]+bytes([raw[-1]^1])
            with patch('app.bootstrap.download_archive',side_effect=lambda url,target,max_bytes,**options:target.write_bytes(invalid)):
                with self.assertRaisesRegex(ValueError,'SHA-256'):
                    ensure_database(destination,manifest_path)
            self.assertFalse(destination.exists())
            self.assertFalse((destination.parent/'study.sqlite.download').exists())

    def test_public_download_is_atomic_and_checksum_verified(self) -> None:
        """Ensaya el transporte con una base mínima, sin conexión a una cuenta Drive."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            seed = root/'seed.sqlite'
            with closing(sqlite3.connect(seed)) as connection:
                connection.execute('CREATE TABLE example (number INTEGER)')
                connection.execute('INSERT INTO example VALUES (7)')
                connection.commit()
            raw = seed.read_bytes()
            packed = gzip.compress(raw,mtime=0)
            manifest = {'download_url':'https://drive.google.com/file/d/example/view',
                        'database':{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},
                        'archive':{'bytes':len(packed),'sha256':hashlib.sha256(packed).hexdigest()}}
            manifest_path = root/'manifest.json'
            manifest_path.write_text(json.dumps(manifest))
            destination = root/'data/study.sqlite'
            def fake_download(url: str, target: Path, max_bytes: int, **options) -> None:
                target.write_bytes(packed)
            with patch('app.bootstrap.download_archive',side_effect=fake_download) as download:
                ensure_database(destination,manifest_path)
                self.assertEqual(destination.read_bytes(),raw)
                ensure_database(destination,manifest_path)
                self.assertEqual(download.call_count,1)
                self.assertEqual(download.call_args.args[0],manifest['download_url'])
            destination.unlink()
            with patch('app.bootstrap.download_archive',side_effect=lambda url,target,max_bytes,**options:target.write_bytes(b'<html>Drive error</html>')):
                with self.assertRaises(ValueError):
                    ensure_database(destination,manifest_path,'https://drive.google.com/file/d/example/view')
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix('.partial').exists())

    def test_google_drive_transport_uses_no_account_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'download'
            def write_public_file(**options):
                Path(options['output']).write_bytes(b'public-file')
            with patch('gdown.download',side_effect=write_public_file) as transport:
                download_archive('https://drive.google.com/file/d/example/view',target,100)
                self.assertFalse(transport.call_args.kwargs['use_cookies'])
                self.assertNotIn('cookies_from_browser',transport.call_args.kwargs)
                self.assertEqual(target.read_bytes(),b'public-file')


if __name__ == '__main__':
    unittest.main()
