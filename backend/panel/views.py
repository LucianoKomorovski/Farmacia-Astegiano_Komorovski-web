"""Vistas del panel: portada (dashboard), Analítica y su API.

Todas se registran en PanelAdminSite.get_urls() envueltas en admin_view(),
que exige usuario staff activo y redirige al login del panel si no lo es.
Por la regla del proyecto, los gráficos cargan sus datos desde una API
separada (api_analitica) en vez de recargar el template.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from typing import Any

from django.contrib import admin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from pedidos.models import Pedido
from sucursales.models import Sucursal

from . import services
from .services import Alerta, FiltroVentas

# Rangos rápidos ofrecidos en los selectores (días).
RANGOS_RAPIDOS: tuple[int, ...] = (7, 30, 90)
RANGO_POR_DEFECTO = 30
MAX_DIAS = 366


# ---------------------------------------------------------------------------
# Filtros desde la querystring
# ---------------------------------------------------------------------------


def _parse_fecha(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


def filtro_desde_request(request: HttpRequest) -> FiltroVentas:
    """Arma el FiltroVentas a partir de ?dias= o ?desde=&hasta=, más modo y sucursal.

    Cualquier valor inválido cae al rango por defecto: la pantalla nunca rompe
    por una URL mal escrita.
    """
    params = request.GET
    hoy = timezone.localdate()

    desde = _parse_fecha(params.get('desde'))
    hasta = _parse_fecha(params.get('hasta'))

    if desde is None or hasta is None:
        try:
            dias = int(params.get('dias', RANGO_POR_DEFECTO))
        except ValueError:
            dias = RANGO_POR_DEFECTO
        dias = max(1, min(dias, MAX_DIAS))
        hasta = hoy
        desde = hoy - timedelta(days=dias - 1)

    if desde > hasta:
        desde, hasta = hasta, desde
    if (hasta - desde).days + 1 > MAX_DIAS:
        desde = hasta - timedelta(days=MAX_DIAS - 1)

    modo = params.get('modo', '')
    if modo not in dict(Pedido.Modo.choices):
        modo = ''

    sucursal_id: int | None = None
    try:
        if params.get('sucursal'):
            sucursal_id = int(params['sucursal'])
    except ValueError:
        sucursal_id = None

    return FiltroVentas(desde=desde, hasta=hasta, modo=modo, sucursal_id=sucursal_id)


# ---------------------------------------------------------------------------
# Alertas "Requiere atención"
# ---------------------------------------------------------------------------


def _url_pedidos(estado: str) -> str:
    return f"{reverse('admin:pedidos_pedido_changelist')}?estado__exact={estado}"


def alertas_para(request: HttpRequest) -> list[Alerta]:
    """Tarjetas de la portada, filtradas por lo que el usuario puede ver."""
    conteos = services.pendientes_atencion()
    user = request.user

    todas = [
        Alerta(
            clave='transferencias',
            titulo='Transferencias por confirmar',
            cantidad=conteos['transferencias'],
            url=_url_pedidos(Pedido.Estado.PENDIENTE_TRANSFERENCIA),
            icono='bi-bank',
            ayuda='Revisá el home banking y confirmá el pago desde el pedido.',
        ),
        Alerta(
            clave='encargues',
            titulo='Encargues por aprobar',
            cantidad=conteos['encargues'],
            url=_url_pedidos(Pedido.Estado.PENDIENTE_ENCARGUE),
            icono='bi-clipboard-check',
            ayuda='Confirmá si se puede conseguir el producto para habilitar el cobro.',
        ),
        Alerta(
            clave='por_preparar',
            titulo='Pagados, por preparar',
            cantidad=conteos['por_preparar'],
            url=_url_pedidos(Pedido.Estado.CONFIRMADO),
            icono='bi-box-seam',
            ayuda='Pedidos ya cobrados que esperan armado.',
        ),
        Alerta(
            clave='listos_retiro',
            titulo='Listos para retirar',
            cantidad=conteos['listos_retiro'],
            url=_url_pedidos(Pedido.Estado.LISTO_RETIRO),
            icono='bi-shop',
            ayuda='Cuando el cliente pase por la sucursal, marcalos entregados.',
        ),
        Alerta(
            clave='stock_bajo',
            titulo='Productos con stock bajo',
            cantidad=conteos['stock_bajo'],
            url=reverse('admin:inventario_stockweb_changelist') + '?o=2',
            icono='bi-exclamation-triangle',
            ayuda=f'Stock web disponible de {services.UMBRAL_STOCK_BAJO} unidades o menos.',
        ),
        Alerta(
            clave='solicitudes_personal',
            titulo='Solicitudes de personal',
            cantidad=conteos['solicitudes_personal'],
            url=reverse('admin:cuentas_perfilstaff_changelist') + '?estado__exact=pendiente',
            icono='bi-person-plus',
            ayuda='Cuentas nuevas que esperan tu aprobación.',
            solo_super=True,
        ),
    ]

    visibles = []
    for alerta in todas:
        if alerta.solo_super and not user.is_superuser:
            continue
        # Solo mostramos tarjetas de módulos a los que la persona tiene acceso.
        if alerta.clave == 'stock_bajo' and not user.has_perm('inventario.view_stockweb'):
            continue
        if alerta.clave in ('transferencias', 'encargues', 'por_preparar', 'listos_retiro'):
            if not user.has_perm('pedidos.view_pedido'):
                continue
        visibles.append(alerta)
    return visibles


# ---------------------------------------------------------------------------
# Portada
# ---------------------------------------------------------------------------


def contexto_dashboard(request: HttpRequest) -> dict[str, Any]:
    """Datos que la portada suma al contexto estándar del admin."""
    puede_ver_ventas = request.user.has_perm('pedidos.view_pedido')

    contexto: dict[str, Any] = {
        'alertas': alertas_para(request),
        'puede_ver_ventas': puede_ver_ventas,
        'rangos_rapidos': RANGOS_RAPIDOS,
        'rango_por_defecto': RANGO_POR_DEFECTO,
        'url_api_analitica': reverse('admin:panel_api_analitica'),
        'url_analitica': reverse('admin:panel_analitica'),
    }
    if not puede_ver_ventas:
        return contexto

    contexto.update({
        'kpi_hoy': services.kpis(services.filtro_ultimos_dias(1)),
        'kpi_7': services.kpis(services.filtro_ultimos_dias(7)),
        'kpi_30': services.kpis(services.filtro_ultimos_dias(30)),
        'ultimos_pedidos': services.ultimos_pedidos(10),
        # Datos iniciales embebidos (json_script) para que los gráficos
        # aparezcan sin esperar la primera llamada a la API.
        'datos_iniciales': services.datos_analitica(
            services.filtro_ultimos_dias(RANGO_POR_DEFECTO)
        ),
    })
    return contexto


# ---------------------------------------------------------------------------
# Analítica (página completa)
# ---------------------------------------------------------------------------


def analitica(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm('pedidos.view_pedido'):
        return HttpResponse('No tenés permiso para ver la analítica de ventas.', status=403)

    filtro = filtro_desde_request(request)
    datos = services.datos_analitica(filtro, limite_productos=None)

    contexto = {
        **admin.site.each_context(request),
        'title': 'Analítica de ventas',
        'filtro': filtro,
        'datos': datos,
        'kpis': services.kpis(filtro),
        'tabla_productos': services.ventas_por_producto(filtro, limite=None),
        'tabla_categorias': services.ventas_por_categoria(filtro),
        'tabla_medios': services.ventas_por_medio_pago(filtro),
        'tabla_modalidades': services.ventas_por_modalidad(filtro),
        'sucursales': Sucursal.objects.all(),
        'modos': Pedido.Modo.choices,
        'rangos_rapidos': RANGOS_RAPIDOS,
        'url_api_analitica': reverse('admin:panel_api_analitica'),
        'querystring': request.GET.urlencode(),
    }
    return TemplateResponse(request, 'admin/panel/analitica.html', contexto)


# ---------------------------------------------------------------------------
# API para los gráficos (+ exportación CSV)
# ---------------------------------------------------------------------------


def _csv_analitica(filtro: FiltroVentas) -> HttpResponse:
    """Exporta ventas por producto y por categoría en un solo CSV."""
    nombre = f'ventas_{filtro.desde:%Y%m%d}_{filtro.hasta:%Y%m%d}.csv'
    respuesta = HttpResponse(content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    respuesta.write('\ufeff')  # BOM para que Excel abra bien los acentos

    escritor = csv.writer(respuesta, delimiter=';')
    escritor.writerow(['Ventas por producto', f'{filtro.desde:%d/%m/%Y} a {filtro.hasta:%d/%m/%Y}'])
    escritor.writerow(['Producto', 'Categoría', 'Unidades', 'Monto', '% del total'])
    for fila in services.ventas_por_producto(filtro, limite=None):
        escritor.writerow([
            fila['nombre'], fila['categoria'], fila['unidades'],
            f"{fila['monto']:.2f}".replace('.', ','), fila['porcentaje'],
        ])

    escritor.writerow([])
    escritor.writerow(['Ventas por categoría'])
    escritor.writerow(['Categoría', 'Productos distintos', 'Unidades', 'Monto', '% del total'])
    for fila in services.ventas_por_categoria(filtro):
        escritor.writerow([
            fila['categoria'], fila['productos'], fila['unidades'],
            f"{fila['monto']:.2f}".replace('.', ','), fila['porcentaje'],
        ])
    return respuesta


def api_analitica(request: HttpRequest) -> HttpResponse:
    if not request.user.has_perm('pedidos.view_pedido'):
        return JsonResponse({'error': 'Sin permiso.'}, status=403)

    filtro = filtro_desde_request(request)
    if request.GET.get('formato') == 'csv':
        return _csv_analitica(filtro)

    return JsonResponse(services.datos_analitica(filtro))
