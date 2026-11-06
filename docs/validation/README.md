# Validación del motor y la API 2.0.0

Comprobaciones realizadas en Linux con Docker.

| Comprobación | Resultado y evidencia |
|---|---|
| Motor, API y transporte | 11 pruebas aprobadas; `api-tests-github.txt`. |
| Contrato por parámetros | Rutas y esquemas vigentes; `openapi.json`. |
| Ejemplos HTTP | Cuerpos originales conservados; `../api-examples.json`. |
| Manual API v6 | 15 páginas, clonación y configuración documentadas; `manual-v6-review.json`. |
| Descarga pública | Arranque desde carpeta vacía, base completa y consultas HTTP verificados; `public-download.json`. |

Las pruebas de descarga usan bases mínimas y comprueban SQLite directo, gzip,
instalación atómica, reutilización local y rechazo de archivos alterados. El
transporte de Drive se invoca con `use_cookies=False`, sin una cuenta de Google.
Las pruebas funcionales usan la base íntegra de la entrega y reproducen un caso
real sin modificarla.

El nuevo archivo de Drive se descargó sin credenciales desde una carpeta de datos
vacía. Coincide con los 1.923.264.512 bytes y el SHA-256 esperados y supera
`PRAGMA quick_check`. La API arrancó, respondió consultas y reprodujo el caso
SPY/sma200/L1 con resultados equivalentes. El manifiesto conserva la identidad
original de la base; las verificaciones permanecen intactas.

El manual usa una ilustración de portada y esquemas vectoriales. No incluye
fechas de edición y conserva el nombre del autor en los pies de página.
