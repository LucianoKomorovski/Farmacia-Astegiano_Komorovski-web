from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'
    # Nombre que ve el personal en el panel (agrupa banners y promos bancarias).
    verbose_name = 'Portada y promociones'
