"""Obtiene y verifica únicamente la base declarada en el manifiesto."""
import gzip
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlparse
from urllib.request import urlopen

from .utils.files import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def verify_database(path: Path, manifest: dict) -> None:
    """Rechaza bases truncadas, de otra versión o con integridad inválida."""
    if path.stat().st_size != manifest['database']['bytes']:
        raise ValueError('El tamaño de study.sqlite no coincide con data/manifest.json.')
    if sha256_file(path) != manifest['database']['sha256']:
        raise ValueError('SHA-256 de study.sqlite incorrecto. Se conserva el archivo para revisión.')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as connection:
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite no superó quick_check.')


def download_archive(url: str, destination: Path, max_bytes: int) -> None:
    """Descarga por HTTPS; Drive utiliza gdown sin cookies ni credenciales."""
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise ValueError('DATABASE_URL debe ser un enlace HTTPS público al archivo.')
    if parsed.hostname in {'drive.google.com','docs.google.com'}:
        import gdown
        gdown.download(url=url,output=str(destination),use_cookies=False,quiet=False,timeout=60,retries=2)
    else:
        with urlopen(url,timeout=60) as response, destination.open('wb') as output:
            total = 0
            for block in iter(lambda: response.read(1024*1024),b''):
                total += len(block)
                if total > max_bytes:
                    raise ValueError('La descarga supera el tamaño declarado.')
                output.write(block)
    if not destination.is_file() or destination.stat().st_size > max_bytes:
        raise ValueError('La descarga no corresponde al archivo esperado.')


def ensure_database(path: Path, manifest_path: Path = ROOT/'data/manifest.json', url: str = '') -> Path:
    """Usa la copia local o instala una descarga validada mediante reemplazo atómico."""
    manifest = json.loads(manifest_path.read_text())
    url = url or manifest.get('download_url') or ''
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        verify_database(path,manifest)
        return path
    download_format = manifest.get('download_format','gzip')
    if download_format not in {'sqlite','gzip'}:
        raise ValueError('download_format debe ser sqlite o gzip en data/manifest.json.')
    archive = path.parent/'study.sqlite.gz'
    download = path.parent/('study.sqlite.download' if download_format == 'sqlite' else 'study.sqlite.gz.download')
    candidate = path.parent/'study.sqlite.partial'
    downloaded = False
    try:
        if not archive.exists():
            if not url:
                raise FileNotFoundError('Falta data/study.sqlite. Colocar study.sqlite.gz en data/ o configurar DATABASE_URL; ver README.md.')
            print('Descargando la base pública; el primer arranque puede demorar.',flush=True)
            expected = manifest['database'] if download_format == 'sqlite' else manifest['archive']
            download_archive(url,download,expected['bytes'])
            if download_format == 'sqlite':
                verify_database(download,manifest)
                download.replace(path)
                print('Base verificada. La API consultará esta copia local en modo de lectura.',flush=True)
                return path
            archive_input = download
            downloaded = True
        else:
            archive_input = archive
        if archive_input.stat().st_size != manifest['archive']['bytes'] or sha256_file(archive_input) != manifest['archive']['sha256']:
            raise ValueError('La descarga no coincide con la versión esperada (tamaño o SHA-256).')
        with gzip.open(archive_input,'rb') as source, candidate.open('wb') as output:
            total = 0
            for block in iter(lambda: source.read(1024*1024),b''):
                total += len(block)
                if total > manifest['database']['bytes']:
                    raise ValueError('El archivo expandido supera el tamaño esperado.')
                output.write(block)
        verify_database(candidate,manifest)
        candidate.replace(path)
        if downloaded:
            download.unlink()
        print('Base verificada. La API consultará esta copia local en modo de lectura.',flush=True)
        return path
    finally:
        candidate.unlink(missing_ok=True)
        download.unlink(missing_ok=True)


if __name__ == '__main__':
    ensure_database(Path(os.getenv('DATABASE_PATH',ROOT/'data/study.sqlite')),url=os.getenv('DATABASE_URL',''))
