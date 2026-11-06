"""Prepara la base en segundo plano y publica un estado sin bloquear el servidor."""
import json
import logging
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic

from .bootstrap import ROOT, ensure_database

logger = logging.getLogger(__name__)


class DatabasePreparation:
    """Coordina una sola preparación y repone una base eliminada del volumen."""

    def __init__(self, path: Path, url: str = '', *,
                 manifest_path: Path = ROOT/'data/manifest.json',
                 poll_interval: float = 1, retry_delay: float = 30) -> None:
        self.path = path
        self.url = url
        self.manifest_path = manifest_path
        self.manifest = json.loads(manifest_path.read_text())
        self.poll_interval = poll_interval
        self.retry_delay = retry_delay
        self.stop_event = Event()
        self.ready_event = Event()
        self.lock = Lock()
        self.phase = 'pending'
        self.message = 'El servidor está disponible. Se prepara la base de datos.'
        self.downloaded_bytes = 0
        expected = 'database' if self.manifest.get('download_format') == 'sqlite' else 'archive'
        self.total_bytes = self.manifest[expected]['bytes']
        self.next_retry = 0.0
        self.thread = Thread(target=self.run, name='database-preparation', daemon=True)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)

    def report(self, phase: str, message: str) -> None:
        with self.lock:
            self.phase = phase
            self.message = message
            if phase == 'ready':
                self.ready_event.set()
            else:
                self.ready_event.clear()

    def progress(self, downloaded_bytes: int, total_bytes: int) -> None:
        with self.lock:
            self.downloaded_bytes = downloaded_bytes
            self.total_bytes = total_bytes

    def snapshot(self) -> dict:
        with self.lock:
            phase, message = self.phase, self.message
            ready = phase == 'ready' and self.path.is_file()
            if phase == 'ready' and not ready:
                phase = 'pending'
                message = 'La base ya no está en data/. Se volverá a descargar automáticamente.'
            downloaded = self.downloaded_bytes
            total = self.total_bytes
            return {
                'phase': phase, 'message': message, 'ready': ready,
                'download': {
                    'received_bytes': downloaded, 'total_bytes': total,
                    'percent': round(min(downloaded / total * 100, 100), 1) if total else None,
                },
                'database': {
                    'installed': ready, 'bytes': self.manifest['database']['bytes'],
                    'version': self.manifest['database_version'],
                    'storage_revision': self.manifest['storage_revision'],
                    'read_only': True,
                },
                'retry_in_seconds': max(0, round(self.next_retry - monotonic())) if phase == 'error' else None,
            }

    def run(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                self.downloaded_bytes = 0
                self.next_retry = 0
            self.report('pending', 'Se comprueba si hay una base disponible en data/.')
            try:
                ensure_database(self.path, self.manifest_path, self.url,
                                report=self.report, progress=self.progress, cancel=self.stop_event)
            except Exception:
                if self.stop_event.is_set():
                    return
                logger.exception('No se pudo preparar la base. Se reintentará automáticamente.')
                with self.lock:
                    self.next_retry = monotonic() + self.retry_delay
                self.report('error', 'No se pudo completar la descarga o la verificación. '
                            'Se volverá a intentar automáticamente; el detalle está en los registros del contenedor.')
                if self.stop_event.wait(self.retry_delay):
                    return
                continue
            if self.stop_event.is_set():
                return
            self.report('ready', 'La base está descargada y verificada. La API ya admite consultas.')
            logger.info('Base preparada. La API ya admite consultas.')
            while not self.stop_event.wait(self.poll_interval):
                if not self.path.is_file():
                    self.report('pending', 'Se detectó que falta la base. Se iniciará una nueva descarga.')
                    break
