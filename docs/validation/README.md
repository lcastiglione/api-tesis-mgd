# Validación del motor y la API 2.3.0

Comprobaciones realizadas en Linux con Docker.

| Comprobación | Resultado y evidencia |
|---|---|
| Motor, API y transporte | 19 pruebas aprobadas; `api-tests-github.txt`. |
| Página inicial | Panel oscuro sin desplazamiento en 84 combinaciones de tamaño y estado; salud real y trece accesos; `status-page-review.json`. |
| Reposición de SQLite | Dos descargas íntegras, sin reiniciar; `database-recovery.json`. |
| Cotizaciones guardadas | Selector probado en Swagger con siete ETF, fechas y precios originales; `quotes-review.json`. |
| Contrato por parámetros | Rutas y esquemas vigentes; `openapi.json`. |
| Ejemplos HTTP | Cuerpos originales conservados; `../api-examples.json`. |
| Manual API v10 | Selector y ejemplo de cotizaciones, captura e indicadores; `manual-v10-review.json`. |
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

## Reproducir las pruebas

Con la API iniciada y su base preparada:

```bash
docker build --target test -t api-tesis-mgd:test .
docker run --rm --volumes-from "$(docker compose ps -q api):ro" api-tesis-mgd:test
```
