from django.apps import AppConfig


class CuentasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'cuentas'
    verbose_name = 'Cuentas de clientes'

    def ready(self) -> None:
        # Importar el módulo acá conecta las señales al arrancar Django.
        from . import signals  # noqa: F401