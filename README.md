# API Tesis Robustez - MGD

Entrega **2.0.0** · API **2.0.0** · manual **v6**.

El proyecto permite consultar la base analítica por HTTP, repetir un caso con el
motor Python y comprobar los análisis en memoria. Incluye motor v9 y SQLite v2r3:
siete ETF, 189 configuraciones, 945 ejecuciones y 10.379.124 observaciones diarias.
Las consultas no modifican la base entregada.

## Inicio

Se necesitan Git, Docker con Compose y al menos 6GiB libres, además del espacio
de Docker. El repositorio es público y se clona sin iniciar sesión en GitHub:

```bash
git clone https://github.com/lcastiglione/api-tesis-mgd.git
cd api-tesis-mgd
cp .env.example .env
docker compose up --build -d
docker compose logs -f api
```

En Windows PowerShell, se utiliza `Copy-Item .env.example .env` en lugar de `cp`.
El archivo de ejemplo ya contiene el enlace público de la base. No se configuran
credenciales de Google. La primera descarga puede demorar; el mensaje
`Application startup complete` indica que la API está preparada.

| Dirección | Uso |
|---|---|
| http://localhost:8000/docs | Probar consultas con botones y parámetros. |
| http://localhost:8000/health | Comprobar que la API puede abrir la base verificada. |
| http://localhost:8000/tutorials/api | Descargar el manual de la API. |

`Ctrl+C` termina la lectura de registros; `docker compose down` detiene el servicio.
La base permanece en `data/`. El puerto predeterminado es **8000**.

Si la API corre en otro equipo, se puede reenviar su puerto por SSH:

```bash
ssh -N -L 8000:127.0.0.1:8000 usuario@equipo-remoto
```

El túnel se mantiene abierto mientras se usa http://localhost:8000/docs desde
el navegador local. Si ese puerto local está ocupado, se utiliza
`-L 18000:127.0.0.1:8000` y se abre http://localhost:18000/docs. El puerto del
servidor sigue siendo 8000. Desde un escritorio remoto, `localhost` identifica
al equipo donde se ejecuta ese navegador.

## Descarga automática de la base

La base se descarga desde [el archivo público de Google Drive](https://drive.google.com/file/d/16IpEVijsXvy_kTaYY7l2_zUHkxaDIr5g/view?usp=sharing).
El enlace está incluido en `.env.example` y en `data/manifest.json`.
El formato configurado es SQLite sin comprimir. La base y los archivos Excel
quedan fuera de GitHub y de la imagen Docker.

La descarga completa y el arranque de la API se verificaron sin credenciales.
El archivo conserva los 1.923.264.512 bytes y el SHA-256 del manifiesto, y SQLite
superó la comprobación de integridad. La evidencia está en
`docs/validation/public-download.json`.

El usuario solo ejecuta Docker: **no necesita cuenta de Google, OAuth, claves
de API, cookies del navegador ni configurar credenciales**. Docker instala las
dependencias.

En cada arranque se sigue este orden:

1. Si existe `data/study.sqlite`, se verifica y utiliza.
2. Si existe `data/study.sqlite.gz`, se verifica y expande.
3. Si faltan ambos, se descarga del enlace público a un archivo provisional. Se
   verifican tamaño, SHA-256 e integridad antes de instalar la copia definitiva.
   Si `download_format` indica `gzip`, también se verifica y expande el archivo.

Drive se invoca con `use_cookies=False`. Si limita temporalmente las descargas,
se puede descargar `study.sqlite` con el navegador y colocarlo en `data/`.
Una descarga incorrecta se rechaza; las huellas no se ajustan para aceptarla.

## Configuración opcional

Con la base local o el enlace en el manifiesto no hace falta crear un archivo de
configuración. Para cambiar la escucha o reemplazar el enlace se copia
`.env.example` a `.env`:

```dotenv
DATABASE_URL=https://drive.google.com/file/d/16IpEVijsXvy_kTaYY7l2_zUHkxaDIr5g/view?usp=sharing
API_HOST=127.0.0.1
API_PORT=8000
LOCAL_UID=1000
LOCAL_GID=1000
```

`DATABASE_URL` vacío conserva el enlace del manifiesto; otro enlace público lo
reemplaza. `API_HOST` puede ser la dirección del equipo para acceder desde otro
dispositivo. En Linux, `id -u` e `id -g` permiten completar los identificadores
locales si son distintos de 1000.

`git pull` no modifica un `.env` existente. Después de actualizar el proyecto,
se reemplaza la línea `DATABASE_URL` de ese archivo por el enlace vigente de
`.env.example`, conservando los demás ajustes. Si la base local ya es válida,
el arranque la reutiliza y no vuelve a descargarla.

## Consultas por parámetros

> **Advertencia:** la API recibe parámetros validados. Las consultas se definen
> en el servidor y los valores se envían por separado para prevenir inyecciones
> SQL. No se admite código SQL del cliente. Los campos adicionales se rechazan.

| Operación | Parámetros principales |
|---|---|
| `GET /api/v1/study` | Cantidades e identidad de la base. |
| `GET /api/v1/instruments` | Instrumentos y cantidades por instrumento. |
| `GET /api/v1/configuration-counts` | `instrument`, opcional; cuenta por familia. |
| `GET /api/v1/configurations` | `instrument`, `family`, `limit`, `offset`. |
| `GET /api/v1/executions` | `instrument`, `configuration`, `length`, `limit`, `offset`. |
| `GET /api/v1/executions/{execution_id}/indicators` | `segment`, `metric`, `limit`, `offset`. |
| `GET /api/v1/executions/{execution_id}/daily` | `segment`, `alternative`, `window_id`, `limit`, `offset`. |
| `GET /api/v1/executions/{execution_id}/operations` | `limit`, `offset`. |
| `POST /api/v1/verify-case` | JSON con `instrument`, `configuration` y `length`. |

En `/docs`, **Try it out** habilita la prueba y **Execute** envía la consulta.
Desde una terminal:

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/api/v1/configuration-counts?instrument=SPY"
curl "http://localhost:8000/api/v1/executions?instrument=SPY&configuration=sma200&length=1&limit=1"
```

La última consulta devuelve un `execution_id` para consultar indicadores,
observaciones diarias y operaciones. `limit` admite hasta 1000 resultados;
`offset` permite recorrer páginas y `has_more` indica si quedan resultados.
`exact_value` conserva el decimal original y `numeric_value` permite aproximaciones.
`fraction` representa fracciones: `0.10` equivale a `10%`. Se consulta `status`
antes de interpretar una ausencia como cero.

## Uso del motor

```bash
curl -X POST http://localhost:8000/api/v1/verify-case \
  -H 'Content-Type: application/json' \
  -d '{"instrument":"SPY","configuration":"sma200","length":1}'
```

El motor repite ese caso en memoria y compara detalle diario, operaciones e
indicadores con la ejecución original. `passed` y `comparisons` muestran el
resultado. Se admite una comprobación simultánea y un proceso Uvicorn.

```bash
docker compose exec api python -m calculator.main --database /data/study.sqlite inspect
docker compose exec api python -m calculator.main --database /data/study.sqlite run-case \
  --instrument SPY --configuration sma200 --length 1 --execution-id comprobacion-spy
docker compose exec api python -m calculator.main --database /data/study.sqlite analyze
```

`validate` comprueba todos los bloques y puede demorar. `analyze` utiliza un
espacio temporal en memoria; no vuelve a simular los 945 casos ni cambia SQLite.

## Archivos y distribución

| Ruta | Contenido |
|---|---|
| `app/` | API y descarga/verificación de la base. |
| `calculator/` | Motor y análisis Python v9. |
| `data/` | Base local y manifiesto de identidad/descarga. |
| `docs/` | Manual API, ejemplos HTTP y evidencia. |
| `scripts/` | Registro de ejemplos y generación del manual. |
| `tests/` | Pruebas con base real y descarga simulada. |
| `release/` | Paquetes locales, excluidos de Git. |

El repositorio es https://github.com/lcastiglione/api-tesis-mgd. `.gitignore`
excluye SQLite, gzip, Excel, `.env`, cachés y `release/`.
`docs/source-provenance.json` conserva la procedencia del motor.

## Pruebas y regeneración del manual

```bash
docker build --target test -t study-api:test .
docker run --rm -v "$(pwd)/data:/data:ro" study-api:test
```

Las pruebas consultan la base real y reproducen un caso. Las pruebas de descarga
también comprueban la instalación atómica, el rechazo de archivos alterados y la
reutilización de la copia local, tanto para SQLite como para gzip.

En un entorno de desarrollo:

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/record_api_examples.py --base-url http://localhost:8000
python3 scripts/build_tutorials.py
```

Los textos, la versión simple y los esquemas están en `docs/tutorial-content.json`.
El PDF se genera en `docs/api-tutorial-v6.pdf` y conserva el marco, la portada
ilustrada, consultas y respuestas con estilo, y el nombre del autor en cada pie.
No incluye fechas de edición ni fechas en sus metadatos.

Las palabras conservan espacio después del número: `176 sesiones`, `1 año`.
Los símbolos y abreviaturas de unidad se escriben junto al valor: `25%`,
`9.000USD`, `1,8GiB`.

Referencias técnicas: [descarga pública con gdown](https://github.com/wkentaro/gdown)
y [prevención de inyección SQL, OWASP](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html).
