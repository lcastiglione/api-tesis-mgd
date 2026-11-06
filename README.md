# API Tesis Robustez - MGD

Consulta de la base del estudio y comprobación de casos con el motor Python.

## Inicio

Se necesitan Git, Docker con Compose y al menos 6GiB libres.

```bash
git clone https://github.com/lcastiglione/api-tesis-mgd.git
cd api-tesis-mgd
docker compose up --build -d
```

Abrir **http://localhost:8000/**. El panel muestra la salud de la API, el avance
de la descarga y los accesos a las consultas y al manual.

`.env` ya está configurado. La base se descarga automáticamente, sin credenciales
de Google, en `data/study.sqlite`. Se verifica antes de habilitar las consultas
y se reutiliza en los próximos arranques. La base queda fuera de Git y de la imagen.

Si se elimina `data/study.sqlite`, el servicio vuelve a descargarla.

## Manual

[Manual de uso de la API v9](docs/api-tutorial-v9.pdf).

Para detener el servicio: `docker compose down`.
