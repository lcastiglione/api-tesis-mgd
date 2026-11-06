# Validación de la API 2.4.0

Comprobaciones realizadas en Linux con Docker y Chromium.

| Comprobación | Evidencia |
|---|---|
| API, motor y preparación | 23 pruebas y 25 subpruebas; `api-tests-github.txt`. |
| Arranque antes de los trabajadores | Puerto disponible con carga de API retenida; `tests/test_server.py`. |
| Arranque sin acceso a Internet | Página HTTP 200, avance y error de conexión visible; `startup-review.json`. |
| Consola adaptable | Doce resoluciones y cinco estados, consultas reales y JSON/tabla; `status-page-review.json`. |
| Cotizaciones | Siete tickers, fechas, paginación y precisión original; `quotes-review.json`. |
| Contrato de parámetros | Esquema vigente; `openapi.json`. |
| Manual v11 | Captura real, instrucciones de consola y revisión de márgenes; `manual-v11-review.json`. |

Las pruebas funcionales utilizan la base íntegra, abierta en lectura, y reproducen
el caso SPY/sma200/L1. Los ejemplos HTTP están en `../api-examples.json`.
Las pruebas de preparación usan bases mínimas para comprobar descarga, instalación
atómica, rechazo de archivos alterados y reposición al borrar SQLite.

La prueba visual combina consultas HTTP reales con estados controlados para revisar
descarga, verificación, fallos y carga de la API. La página ocupa la pantalla; los
resultados y, si hace falta, el menú tienen desplazamiento interno.

`database-recovery.json` conserva dos descargas completas y verificadas del enlace
vigente, incluida la reposición sin reiniciar. `public-download.json` conserva una
prueba histórica con volumen Docker, anterior al montaje actual de `./data`.
La descarga usa `use_cookies=False`, sin credenciales de Google.

## Reproducir las pruebas

Con la base preparada:

```bash
docker build --target test -t api-tesis-mgd:test .
docker run --rm --volumes-from "$(docker compose ps -q api):ro" api-tesis-mgd:test
```
