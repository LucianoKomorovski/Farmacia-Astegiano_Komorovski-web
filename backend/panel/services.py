"""Consultas de analítica para el panel (KPIs, series para gráficos, alertas).

Todo lo que se muestra en la portada del panel y en "Analítica" sale de acá.
Las funciones reciben un FiltroVentas (rango de fechas + filtros opcionales)
y devuelven listas/dicts simples, listos para el template o para JSON.

Qué cuenta como VENTA: un pedido en un estado posterior al pago
(confirmado, en preparación, listo para retiro, despachado, entregado).
La fecha de venta es confirmado_en; si por algún motivo está vacío usamos
created_at (Coalesce) para no perder el pedido.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, DecimalField, F, OuterRef, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from catalogo.models import Producto
from cuentas.models import PerfilStaff
from inventario.models import ReservaStock, StockWeb
from pedidos.models import LineaPedido, Pedido

# Estados que consideramos venta concretada.
ESTADOS_VENTA: tuple[str, ...] = (
    Pedido.Estado.CONFIRMADO,
    Pedido.Estado.EN_PREPARACION,
    Pedido.Estado.LISTO_RETIRO,
    Pedido.Estado.DESPACHADO,
    Pedido.Estado.ENTREGADO,
)

# Stock web disponible igual o menor a esto = alerta de "stock bajo".
UMBRAL_STOCK_BAJO = 3

CERO = Decimal('0')


@dataclass
class FiltroVentas:
    """Rango de fechas (ambos inclusive) + filtros opcionales."""

    desde: date
    hasta: date
    modo: str = ''  # '' = todos; 'inmediato' | 'encargue'
    sucursal_id: int | None = None  # sucursal de retiro

    @property
    def dias(self) -> int:
        return (self.hasta - self.desde).days + 1

    def anterior(self) -> 'FiltroVentas':
        """Mismo largo de período, inmediatamente antes (para comparar)."""
        return FiltroVentas(
            desde=self.desde - timedelta(days=self.dias),
            hasta=self.desde - timedelta(days=1),
            modo=self.modo,
            sucursal_id=self.sucursal_id,
        )


def filtro_ultimos_dias(dias: int, **extra: Any) -> FiltroVentas:
    """Ej: filtro_ultimos_dias(7) = hoy y los 6 días anteriores."""
    hoy = timezone.localdate()
    return FiltroVentas(desde=hoy - timedelta(days=dias - 1), hasta=hoy, **extra)


def _limites_datetime(filtro: FiltroVentas) -> tuple[datetime, datetime]:
    """Convierte fechas locales a datetimes con zona horaria [desde, hasta+1)."""
    tz = timezone.get_current_timezone()
    inicio = datetime.combine(filtro.desde, time.min, tzinfo=tz)
    fin = datetime.combine(filtro.hasta + timedelta(days=1), time.min, tzinfo=tz)
    return inicio, fin


def pedidos_vendidos(filtro: FiltroVentas) -> QuerySet[Pedido]:
    """Pedidos que cuentan como venta dentro del filtro."""
    inicio, fin = _limites_datetime(filtro)
    qs = (
        Pedido.objects.annotate(fecha_venta=Coalesce('confirmado_en', 'created_at'))
        .filter(estado__in=ESTADOS_VENTA, fecha_venta__gte=inicio, fecha_venta__lt=fin)
    )
    if filtro.modo:
        qs = qs.filter(modo=filtro.modo)
    if filtro.sucursal_id:
        qs = qs.filter(sucursal_retiro_id=filtro.sucursal_id)
    return qs


def _num(valor: Any) -> float:
    """Decimal/None → float para JSON y Chart.js."""
    return float(valor or 0)


def _porcentaje(parte: Decimal | float, total: Decimal | float) -> float:
    if not total:
        return 0.0
    return round(float(parte) / float(total) * 100, 1)


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------


def kpis(filtro: FiltroVentas) -> dict[str, Any]:
    """Monto, cantidad de pedidos, ticket promedio y variación vs. período anterior."""
    actual = pedidos_vendidos(filtro).aggregate(
        monto=Coalesce(Sum('total'), Value(CERO), output_field=DecimalField()),
        pedidos=Count('id'),
    )
    anterior = pedidos_vendidos(filtro.anterior()).aggregate(
        monto=Coalesce(Sum('total'), Value(CERO), output_field=DecimalField()),
        pedidos=Count('id'),
    )
    unidades = (
        LineaPedido.objects.filter(pedido__in=pedidos_vendidos(filtro).values('pk'))
        .aggregate(u=Coalesce(Sum('cantidad'), 0))['u']
    )

    monto: Decimal = actual['monto']
    cantidad: int = actual['pedidos']
    ticket = (monto / cantidad) if cantidad else CERO

    monto_ant: Decimal = anterior['monto']
    variacion: float | None
    if monto_ant > 0:
        variacion = round(float((monto - monto_ant) / monto_ant * 100), 1)
    else:
        variacion = None  # sin base de comparación

    return {
        'monto': monto,
        'pedidos': cantidad,
        'unidades': unidades,
        'ticket_promedio': ticket.quantize(Decimal('0.01')) if cantidad else CERO,
        'monto_anterior': monto_ant,
        'pedidos_anterior': anterior['pedidos'],
        'variacion_pct': variacion,
    }


# ---------------------------------------------------------------------------
# Series para gráficos
# ---------------------------------------------------------------------------


def ventas_por_dia(filtro: FiltroVentas) -> list[dict[str, Any]]:
    """Un punto por día del rango (rellena con 0 los días sin ventas)."""
    filas = (
        pedidos_vendidos(filtro)
        .annotate(dia=TruncDate('fecha_venta'))
        .values('dia')
        .annotate(monto=Sum('total'), pedidos=Count('id'))
        .order_by('dia')
    )
    por_dia = {fila['dia']: fila for fila in filas}

    serie = []
    dia = filtro.desde
    while dia <= filtro.hasta:
        fila = por_dia.get(dia)
        serie.append({
            'fecha': dia,
            'etiqueta': dia.strftime('%d/%m'),
            'monto': _num(fila['monto']) if fila else 0.0,
            'pedidos': fila['pedidos'] if fila else 0,
        })
        dia += timedelta(days=1)
    return serie


def ventas_por_producto(filtro: FiltroVentas, limite: int | None = 10) -> list[dict[str, Any]]:
    """Top productos por monto vendido (unidades, monto y % del total)."""
    lineas = LineaPedido.objects.filter(pedido__in=pedidos_vendidos(filtro).values('pk'))
    total = lineas.aggregate(t=Coalesce(Sum('subtotal'), Value(CERO), output_field=DecimalField()))['t']

    filas = (
        lineas.values('producto_id', 'nombre_snapshot', 'producto__categoria__nombre')
        .annotate(unidades=Sum('cantidad'), monto=Sum('subtotal'))
        .order_by('-monto', 'nombre_snapshot')
    )
    if limite:
        filas = filas[:limite]

    return [
        {
            'producto_id': fila['producto_id'],
            'nombre': fila['nombre_snapshot'],
            'categoria': fila['producto__categoria__nombre'] or 'Sin categoría',
            'unidades': fila['unidades'],
            'monto': fila['monto'],
            'porcentaje': _porcentaje(fila['monto'], total),
        }
        for fila in filas
    ]


def ventas_por_categoria(filtro: FiltroVentas) -> list[dict[str, Any]]:
    lineas = LineaPedido.objects.filter(pedido__in=pedidos_vendidos(filtro).values('pk'))
    total = lineas.aggregate(t=Coalesce(Sum('subtotal'), Value(CERO), output_field=DecimalField()))['t']

    filas = (
        lineas.values('producto__categoria__nombre')
        .annotate(unidades=Sum('cantidad'), monto=Sum('subtotal'), productos=Count('producto_id', distinct=True))
        .order_by('-monto')
    )
    return [
        {
            'categoria': fila['producto__categoria__nombre'] or 'Sin categoría',
            'unidades': fila['unidades'],
            'productos': fila['productos'],
            'monto': fila['monto'],
            'porcentaje': _porcentaje(fila['monto'], total),
        }
        for fila in filas
    ]


def _agrupar_pedidos(filtro: FiltroVentas, campo: str, etiquetas: dict[str, str]) -> list[dict[str, Any]]:
    filas = (
        pedidos_vendidos(filtro)
        .values(campo)
        .annotate(monto=Sum('total'), pedidos=Count('id'))
        .order_by('-monto')
    )
    total = sum((fila['monto'] for fila in filas), CERO)
    return [
        {
            'clave': fila[campo] or '',
            'etiqueta': etiquetas.get(fila[campo] or '', 'Sin dato'),
            'monto': fila['monto'],
            'pedidos': fila['pedidos'],
            'porcentaje': _porcentaje(fila['monto'], total),
        }
        for fila in filas
    ]


def ventas_por_medio_pago(filtro: FiltroVentas) -> list[dict[str, Any]]:
    return _agrupar_pedidos(filtro, 'medio_pago', dict(Pedido.MedioPago.choices))


def ventas_por_modalidad(filtro: FiltroVentas) -> list[dict[str, Any]]:
    return _agrupar_pedidos(filtro, 'modalidad_entrega', dict(Pedido.ModalidadEntrega.choices))


def ultimos_pedidos(cantidad: int = 10) -> QuerySet[Pedido]:
    return Pedido.objects.select_related('sucursal_retiro').order_by('-created_at')[:cantidad]


# ---------------------------------------------------------------------------
# Alertas operativas ("Requiere atención")
# ---------------------------------------------------------------------------


def stock_bajo_qs() -> QuerySet[StockWeb]:
    """Productos activos cuyo stock web disponible (cantidad − reservas activas)
    está en o bajo el umbral. Una sola consulta gracias a la Subquery."""
    reservas_activas = (
        ReservaStock.objects.filter(
            producto=OuterRef('producto'),
            estado=ReservaStock.Estado.ACTIVA,
            expires_at__gt=timezone.now(),
        )
        .values('producto')
        .annotate(s=Sum('cantidad'))
        .values('s')
    )
    return (
        StockWeb.objects.filter(producto__activo=True)
        .annotate(reservado=Coalesce(Subquery(reservas_activas), 0))
        .annotate(disponible=F('cantidad') - F('reservado'))
        .filter(disponible__lte=UMBRAL_STOCK_BAJO)
        .select_related('producto')
        .order_by('disponible', 'producto__nombre')
    )


@dataclass
class Alerta:
    """Una tarjeta de "Requiere atención" en la portada."""

    clave: str
    titulo: str
    cantidad: int
    url: str
    icono: str  # clase Bootstrap Icons
    ayuda: str = ''
    solo_super: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def pendientes_atencion() -> dict[str, int]:
    """Conteos crudos que alimentan las tarjetas de alerta."""
    por_estado = dict(
        Pedido.objects.filter(
            estado__in=[
                Pedido.Estado.PENDIENTE_TRANSFERENCIA,
                Pedido.Estado.PENDIENTE_ENCARGUE,
                Pedido.Estado.CONFIRMADO,
                Pedido.Estado.LISTO_RETIRO,
            ]
        )
        .values_list('estado')
        .annotate(c=Count('id'))
    )
    return {
        'transferencias': por_estado.get(Pedido.Estado.PENDIENTE_TRANSFERENCIA, 0),
        'encargues': por_estado.get(Pedido.Estado.PENDIENTE_ENCARGUE, 0),
        'por_preparar': por_estado.get(Pedido.Estado.CONFIRMADO, 0),
        'listos_retiro': por_estado.get(Pedido.Estado.LISTO_RETIRO, 0),
        'stock_bajo': stock_bajo_qs().count(),
        'solicitudes_personal': PerfilStaff.objects.filter(
            estado=PerfilStaff.Estado.PENDIENTE
        ).count(),
        'productos_sin_stock_web': Producto.objects.filter(activo=True, stock__isnull=True).count(),
    }


# ---------------------------------------------------------------------------
# Paquete completo para la API JSON / página de analítica
# ---------------------------------------------------------------------------


def datos_analitica(filtro: FiltroVentas, limite_productos: int | None = 10) -> dict[str, Any]:
    """Todo lo que necesitan los gráficos, con Decimals ya convertidos."""
    resumen = kpis(filtro)
    return {
        'rango': {
            'desde': filtro.desde.isoformat(),
            'hasta': filtro.hasta.isoformat(),
            'dias': filtro.dias,
            'modo': filtro.modo,
            'sucursal_id': filtro.sucursal_id,
        },
        'kpis': {
            'monto': _num(resumen['monto']),
            'pedidos': resumen['pedidos'],
            'unidades': resumen['unidades'],
            'ticket_promedio': _num(resumen['ticket_promedio']),
            'monto_anterior': _num(resumen['monto_anterior']),
            'pedidos_anterior': resumen['pedidos_anterior'],
            'variacion_pct': resumen['variacion_pct'],
        },
        'por_dia': [
            {**p, 'fecha': p['fecha'].isoformat()} for p in ventas_por_dia(filtro)
        ],
        'por_producto': [
            {**p, 'monto': _num(p['monto'])}
            for p in ventas_por_producto(filtro, limite_productos)
        ],
        'por_categoria': [
            {**c, 'monto': _num(c['monto'])} for c in ventas_por_categoria(filtro)
        ],
        'por_medio_pago': [
            {**m, 'monto': _num(m['monto'])} for m in ventas_por_medio_pago(filtro)
        ],
        'por_modalidad': [
            {**m, 'monto': _num(m['monto'])} for m in ventas_por_modalidad(filtro)
        ],
    }
