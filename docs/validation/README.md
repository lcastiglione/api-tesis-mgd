# Validación del motor y la API 2.0.0

Comprobaciones realizadas en Linux con Docker.

| Comprobación | Resultado y evidencia |
|---|---|
| Motor, API y transporte | 11 pruebas aprobadas; `api-tests-github.txt`. |
| Contrato por parámetros | Rutas y esquemas vigentes; `openapi.json`. |
| Ejemplos HTTP | Cuerpos originales conservados; `../api-examples.json`. |
| Manual API v6 | 15 páginas, clonación y configuración documentadas; `manual-v6-review.json`. |
| Descarga pública | Transporte anónimo probado; archivo publicado incompleto; `public-download.json`. |

Las pruebas de descarga usan bases mínimas y comprueban SQLite directo, gzip,
instalación atómica, reutilización local y rechazo de archivos alterados. El
transporte de Drive se invoca con `use_cookies=False`, sin una cuenta de Google.
Las pruebas funcionales usan la base íntegra de la entrega y reproducen un caso
real sin modificarla.

El archivo de Drive descargado tiene 1.703.673.856 bytes; la base esperada tiene
1.923.264.512 bytes. Su SHA-256 difiere y SQLite informa que está dañado.
La instalación automática queda pendiente de reemplazar ese archivo por la copia
completa. El manifiesto conserva la identidad esperada; no se debilita su validación.

El manual usa una ilustración de portada y esquemas vectoriales. No incluye
fechas de edición y conserva el nombre del autor en los pies de página.
