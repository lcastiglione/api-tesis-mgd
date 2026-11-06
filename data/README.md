# Base analítica

GitHub conserva este documento y `manifest.json`; SQLite y gzip quedan excluidos
de Git. La base se instala automáticamente en esta carpeta al arrancar Docker.

Si falta la copia local, el contenedor utiliza el gzip de esta carpeta o descarga
el archivo público indicado en `download_url` del manifiesto. `DATABASE_URL` es
un reemplazo opcional. La descarga no requiere cuenta ni credenciales de Google.
El enlace público de `study.sqlite` está incluido en `.env.example` y el manifiesto.
`download_format: sqlite` indica que el archivo público no está comprimido.

El usuario solo ejecuta Docker. También puede descargar manualmente `study.sqlite`
desde el enlace de Drive y colocarlo aquí. Se verifican tamaño, SHA-256 e integridad
antes de utilizar SQLite. Un gzip local de la versión indicada también se admite.

La base se abre en lectura. `daily_results` contiene 10.206 bloques físicos y
10.379.124 observaciones lógicas, recuperables por la API o con
`calculator.database.Database.daily_records`.
