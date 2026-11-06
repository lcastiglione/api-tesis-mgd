"""Abre el servidor antes de iniciar la carga de consultas y la preparación de SQLite."""
import uvicorn

from .web import ApiRuntime, create_app


class ImmediateServer(uvicorn.Server):
    """El puerto queda enlazado antes de lanzar cualquier trabajador de la aplicación."""
    def __init__(self, config: uvicorn.Config, runtime: ApiRuntime) -> None:
        super().__init__(config)
        self.runtime = runtime

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        if self.started and not self.should_exit:
            self.runtime.start()


def main() -> None:
    runtime = ApiRuntime()
    application = create_app(runtime,start_on_lifespan=False)
    server = ImmediateServer(uvicorn.Config(application,host='0.0.0.0',port=8000,workers=1),runtime)
    server.run()


if __name__ == '__main__':
    main()
