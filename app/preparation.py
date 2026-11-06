"""Prepara la base en segundo plano y publica estado y fallos sin bloquear la vista."""
import json
import logging
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic

from .bootstrap import ROOT, ensure_database

logger = logging.getLogger(__name__)


def describe_error(error: Exception) -> dict:
    """Traduce causas conocidas sin enviar trazas internas al navegador."""
    detail = str(error).lower()
    if 'network is unreachable' in detail or 'no route to host' in detail:
        code, message = 'network_unreachable', 'Sin conexión de red para descargar la base de Google Drive.'
    elif any(text in detail for text in ['name resolution', 'name or service not known', 'getaddrinfo']):
        code, message = 'dns_error', 'No se pudo resolver la dirección de Google Drive.'
    elif 'timeout' in detail or 'timed out' in detail:
        code, message = 'network_timeout', 'Google Drive no respondió dentro del tiempo de espera.'
    elif 'sha-256' in detail or 'tamaño' in detail or 'quick_check' in detail:
        code, message = 'database_integrity', 'La base recibida no superó la verificación de integridad.'
    elif isinstance(error, PermissionError):
        code, message = 'data_permissions', 'No se puede leer o escribir en la carpeta data.'
    elif isinstance(error, (json.JSONDecodeError, KeyError, FileNotFoundError)):
        code, message = 'database_configuration', 'No se pudo leer la configuración de la base.'
    else:
        code, message = 'database_preparation', 'No se pudo completar la preparación de la base.'
    return {'code':code, 'message':message, 'source':'database'}


class DatabasePreparation:
    """Conserva el estado en memoria; el manifiesto y SQLite se leen en el trabajador."""

    def __init__(self, path: Path, url: str = '', *,
                 manifest_path: Path = ROOT/'data/manifest.json',
                 poll_interval: float = 1, retry_delay: float = 30) -> None:
        self.path = path
        self.url = url
        self.manifest_path = manifest_path
        self.manifest = {}
        self.poll_interval = poll_interval
        self.retry_delay = retry_delay
        self.stop_event = Event()
        self.ready_event = Event()
        self.lock = Lock()
        self.phase = 'pending'
        self.message = 'Se prepara la base en segundo plano.'
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.next_retry = 0.0
        self.error = None
        self.thread = Thread(target=self.run, name='database-preparation', daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=2)

    def report(self, phase: str, message: str) -> None:
        with self.lock:
            self.phase = phase
            self.message = message
            if phase == 'ready':
                self.error = None
                self.ready_event.set()
            else:
                self.ready_event.clear()

    def progress(self, downloaded_bytes: int, total_bytes: int) -> None:
        with self.lock:
            self.downloaded_bytes = downloaded_bytes
            self.total_bytes = total_bytes

    def snapshot(self) -> dict:
        with self.lock:
            ready = self.phase == 'ready'
            return {
                'phase':self.phase, 'message':self.message, 'ready':ready,
                'download': {
                    'received_bytes':self.downloaded_bytes, 'total_bytes':self.total_bytes,
                    'percent':round(min(self.downloaded_bytes / self.total_bytes * 100,100),1) if self.total_bytes else None,
                },
                'database': {
                    'installed':ready, 'phase':self.phase,
                    'bytes':self.manifest.get('database',{}).get('bytes',0),
                    'version':self.manifest.get('database_version'),
                    'storage_revision':self.manifest.get('storage_revision'), 'read_only':True,
                },
                'error':self.error,
                'retry_in_seconds':max(0,round(self.next_retry - monotonic())) if self.phase == 'error' else None,
            }

    def run(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                self.downloaded_bytes = 0
                self.next_retry = 0
            self.report('pending','Se comprueba la base disponible en data/.')
            try:
                manifest = json.loads(self.manifest_path.read_text())
                expected = 'database' if manifest.get('download_format') == 'sqlite' else 'archive'
                with self.lock:
                    self.manifest = manifest
                    self.total_bytes = manifest[expected]['bytes']
                ensure_database(self.path,self.manifest_path,self.url,
                                report=self.report,progress=self.progress,cancel=self.stop_event)
            except Exception as error:
                if self.stop_event.is_set():
                    return
                logger.exception('No se pudo preparar la base. Se reintentará automáticamente.')
                with self.lock:
                    self.next_retry = monotonic() + self.retry_delay
                    self.error = describe_error(error)
                self.report('error',self.error['message'])
                if self.stop_event.wait(self.retry_delay):
                    return
                continue
            if self.stop_event.is_set():
                return
            self.report('ready','La base está verificada y disponible para consultar.')
            logger.info('Base preparada. La API ya admite consultas.')
            while not self.stop_event.wait(self.poll_interval):
                if not self.path.is_file():
                    self.report('pending','Falta la base. Se iniciará otra descarga.')
                    break
