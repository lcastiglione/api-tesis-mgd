# Base analítica

GitHub conserva este documento y `manifest.json`; SQLite y gzip quedan excluidos
de Git. Docker instala la base en `/data/study.sqlite` dentro de un volumen
persistente. El volumen y sus permisos se preparan automáticamente.

Si falta la copia local en el volumen, el contenedor utiliza el gzip disponible o descarga
el archivo público indicado en `download_url` del manifiesto. `DATABASE_URL` es
un reemplazo opcional. La descarga no requiere cuenta ni credenciales de Google.
El enlace público de `study.sqlite` está incluido en `.env` y el manifiesto.
`download_format: sqlite` indica que el archivo público no está comprimido.

El usuario clona el repositorio y ejecuta Docker, sin editar archivos ni preparar
carpetas. Se verifican tamaño, SHA-256 e integridad antes de utilizar SQLite.

La base se abre en lectura. `daily_results` contiene 10.206 bloques físicos y
10.379.124 observaciones lógicas, recuperables por la API o con
`calculator.database.Database.daily_records`.
