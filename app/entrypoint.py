"""Adapta el usuario al directorio de datos y ejecuta el servicio sin privilegios."""
import os
from pathlib import Path
import sys


def main() -> None:
    """Respeta el propietario del montaje Linux sin pedir UID ni GID al usuario."""
    if os.geteuid() == 0:
        directory = Path(os.getenv('DATABASE_PATH', '/data/study.sqlite')).parent
        directory.mkdir(parents=True, exist_ok=True)
        owner = directory.stat()
        user_id = owner.st_uid or 10001
        group_id = owner.st_gid if owner.st_uid else 10001
        if owner.st_uid == 0:
            os.chown(directory, user_id, group_id)
        os.setgroups([])
        os.setgid(group_id)
        os.setuid(user_id)
    if not sys.argv[1:]:
        raise SystemExit('Falta el comando del servicio.')
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == '__main__':
    main()
