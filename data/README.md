# Base analítica

GitHub conserva este documento y `manifest.json`; SQLite y gzip quedan excluidos
de Git y del contexto de construcción Docker. La base se descarga en
`data/study.sqlite` de la carpeta del proyecto; Docker monta esa misma carpeta
como `/data`. El servicio adapta automáticamente su usuario al propietario del
directorio, sin pedir ajustes de permisos ni cambios en `.env`.

Si falta la copia local, el contenedor utiliza el gzip disponible o descarga
el archivo público indicado en `download_url` del manifiesto. `DATABASE_URL` es
un reemplazo opcional. La descarga no requiere cuenta ni credenciales de Google.
El enlace público de `study.sqlite` está incluido en `.env` y el manifiesto.
`download_format: sqlite` indica que el archivo público no está comprimido.

El usuario clona el repositorio y ejecuta Docker, sin editar archivos ni preparar
carpetas. Se verifican tamaño, SHA-256 e integridad antes de utilizar SQLite.
La página inicial muestra el avance mientras la preparación se ejecuta en segundo
plano. Si se elimina `data/study.sqlite`, el servicio detecta su ausencia y vuelve a
obtener la base, sin reiniciar el contenedor. Los archivos `manifest.json` y
`README.md` se conservan.

La base se abre en lectura. `daily_results` contiene 10.206 bloques físicos y
10.379.124 observaciones lógicas, recuperables por la API o con
`calculator.database.Database.daily_records`.
