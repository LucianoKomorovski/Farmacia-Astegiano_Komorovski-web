"""Filtros de template del panel (formato de dinero y variaciones).

Uso en templates: {% load panel_extras %} y luego {{ monto|moneda }}.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

register = template.Library()


@register.filter
def moneda(valor: object) -> str:
    """Formato argentino: $ 12.345,67 (punto de miles, coma decimal)."""
    try:
        numero = Decimal(str(valor or 0))
    except (InvalidOperation, ValueError):
        return str(valor)
    entero, _, decimales = f'{numero:,.2f}'.partition('.')
    entero = entero.replace(',', '.')
    return f'$ {entero},{decimales}'


@register.filter
def variacion(pct: object) -> SafeString | str:
    """Etiqueta coloreada con la variación porcentual vs. el período anterior."""
    if pct is None:
        return mark_safe('<span class="panel-variacion panel-variacion--igual">sin comparación</span>')
    try:
        valor = float(pct)  # pyright: ignore[reportArgumentType]
    except (TypeError, ValueError):
        return ''
    if valor > 0:
        clase, flecha = 'sube', '▲'
    elif valor < 0:
        clase, flecha = 'baja', '▼'
    else:
        clase, flecha = 'igual', '='
    return format_html(
        '<span class="panel-variacion panel-variacion--{}" aria-label="Variación {} por ciento">{} {}%</span>',
        clase,
        valor,
        flecha,
        f'{abs(valor):g}',
    )


# Mapa estado del pedido → variante visual de .badge-estado (colores planos).
CLASES_ESTADO_PEDIDO = {
    'pendiente_pago': 'pendiente',
    'pendiente_transferencia': 'pendiente',
    'pendiente_encargue': 'pendiente',
    'pendiente_pago_encargue': 'pendiente',
    'confirmado': 'ok',
    'en_preparacion': 'info',
    'listo_retiro': 'listo',
    'despachado': 'info',
    'entregado': 'entregado',
    'cancelado': 'cancelado',
}


@register.filter
def clase_estado(estado: str) -> str:
    return 'badge-estado badge-estado--' + CLASES_ESTADO_PEDIDO.get(estado, 'info')


@register.filter
def split(valor: str, separador: str = '|') -> list[str]:
    """'a|b|c' → ['a', 'b', 'c']. Sirve para pasar listas cortas a un include.

    Un sufijo '#' marca columna numérica (alineada a la derecha): 'Monto#'.
    """
    return [parte.strip() for parte in str(valor).split(separador) if parte.strip()]


@register.filter
def es_numerica(cabecera: str) -> bool:
    return cabecera.endswith('#')


@register.filter
def sin_marca(cabecera: str) -> str:
    return cabecera.rstrip('#')
