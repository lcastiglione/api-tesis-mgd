# Validación del motor y la API 2.1.0

Comprobaciones realizadas en Linux con Docker.

| Comprobación | Resultado y evidencia |
|---|---|
| Motor, API y transporte | 16 pruebas aprobadas; `api-tests-github.txt`. |
| Página inicial | Escritorio y móvil, descarga real y estado disponible; `status-page-review.json`. |
| Reposición de SQLite | Dos descargas íntegras, sin reiniciar; `database-recovery.json`. |
| Contrato por parámetros | Rutas y esquemas vigentes; `openapi.json`. |
| Ejemplos HTTP | Cuerpos originales conservados; `../api-examples.json`. |
| Manual API v8 | Página inicial, captura, progreso y almacenamiento local; `manual-v8-review.json`. |
| Descarga pública | `.env` incluido, volumen vacío, descarga completa y consultas HTTP verificados; `public-download.json`. |

Las pruebas de descarga usan bases mínimas y comprueban SQLite directo, gzip,
instalación atómica, reutilización local y rechazo de archivos alterados. El
transporte de Drive se invoca con `use_cookies=False`, sin una cuenta de Google.
Las pruebas funcionales usan la base íntegra de la entrega y reproducen un caso
real sin modificarla.

La descarga vigente en data/ se comprobó dos veces, incluida la reposición automática
tras borrar SQLite sin reiniciar el contenedor. Ambas copias coinciden en tamaño,
SHA-256 e integridad; `database-recovery.json`.

La evidencia anterior de public-download.json corresponde a la entrega con volumen
de Docker, conservada como antecedente. En esa prueba el archivo de Drive se descargó sin credenciales en un volumen nuevo de Docker.
El archivo `.env` incluido se carga automáticamente; no se copian archivos ni se
configuran usuarios del equipo. El volumen permite escribir al usuario de la API
sin ajustes de permisos. La base coincide con los 1.923.264.512 bytes y el SHA-256 esperados y supera
`PRAGMA quick_check`. La API arrancó, respondió consultas y reprodujo el caso
SPY/sma200/L1 con resultados equivalentes. El manifiesto conserva la identidad
original de la base; las verificaciones permanecen intactas.

El manual usa una ilustración de portada, una captura real de la página inicial
y esquemas vectoriales. No incluye
fechas de edición y conserva el nombre del autor en los pies de página.
