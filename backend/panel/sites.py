"""AdminSite propio: el "Panel" de las farmacias.

Hereda TODO del admin de Django (changelists, formularios, acciones, permisos)
y agrega:
- textos en español y formulario de login con mensajes claros,
- orden de las secciones según la operativa diaria,
- portada tipo dashboard (alertas, KPIs, gráficos, últimos pedidos),
- páginas extra: Analítica de ventas y su API JSON/CSV.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.urls import URLPattern, path

from .forms import PanelLoginForm

# Orden de aparición de las apps en la portada y el menú lateral.
# Lo que no esté acá va al final, en orden alfabético.
ORDEN_APPS: tuple[str, ...] = (
    'pedidos',
    'catalogo',
    'inventario',
    'core',
    'turnos',
    'sucursales',
    'servicios',
    'aboutUs',
    'pagos',
    'carrito',
    'cuentas',
    'auth',
)


class PanelAdminSite(admin.AdminSite):
    site_header = 'Panel · Farmacias Astegiano y Komorovski'
    site_title = 'Panel de la farmacia'
    index_title = 'Resumen del día'
    site_url = '/'  # link "Ver sitio"
    login_form = PanelLoginForm
    login_template = 'admin/login.html'
    index_template = 'admin/index.html'
    enable_nav_sidebar = True

    def get_app_list(self, request: HttpRequest, app_label: str | None = None) -> list[dict[str, Any]]:
        """Reordena las apps según ORDEN_APPS (Django las devuelve alfabéticas)."""
        app_list = super().get_app_list(request, app_label)
        posicion = {label: i for i, label in enumerate(ORDEN_APPS)}

        def clave(app: dict[str, Any]) -> tuple[int, str]:
            return (posicion.get(app['app_label'], len(ORDEN_APPS)), app['name'])

        return sorted(app_list, key=clave)

    def get_urls(self) -> list[URLPattern]:
        # Import acá para evitar imports circulares (views importa services → modelos).
        from . import views

        propias = [
            path('analitica/', self.admin_view(views.analitica), name='panel_analitica'),
            path('api/analitica/', self.admin_view(views.api_analitica), name='panel_api_analitica'),
        ]
        # Las propias van ANTES: el admin tiene un catch-all para <app_label>/.
        return propias + super().get_urls()

    def index(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        """Portada: suma al contexto estándar los datos del dashboard."""
        from .views import contexto_dashboard

        contexto = {**(extra_context or {}), **contexto_dashboard(request)}
        return super().index(request, extra_context=contexto)
