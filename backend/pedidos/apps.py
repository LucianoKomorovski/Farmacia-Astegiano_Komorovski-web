from django.apps import AppConfig


class PedidosConfig(AppConfig):
    name = 'pedidos'
    verbose_name = 'Pedidos'

    def ready(self) -> None:
        import pedidos.signals  # noqa: F401
