"""Configuración de la app panel.

Hay DOS AppConfig acá a propósito:

- PanelConfig: la app "panel" en sí (templates, static, servicios de analítica).
- PanelAdminConfig: reemplaza a 'django.contrib.admin' en INSTALLED_APPS.
  Su atributo default_site hace que `admin.site` (el objeto que usan todos
  los `@admin.register` del proyecto) sea NUESTRA clase PanelAdminSite.
  Así no hay que tocar ningún admin.py existente para que aparezcan en el panel.
"""

from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class PanelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'panel'
    verbose_name = 'Panel'


class PanelAdminConfig(AdminConfig):
    default_site = 'panel.sites.PanelAdminSite'


# Ojo: en settings.INSTALLED_APPS las dos van con ruta completa
# ('panel.apps.PanelAdminConfig' y 'panel.apps.PanelConfig'); si pusiéramos
# solo 'panel', Django no sabría cuál de las dos clases usar.
