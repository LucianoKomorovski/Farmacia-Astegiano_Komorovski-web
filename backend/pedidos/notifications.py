"""Emails al cliente cuando cambia el estado del pedido."""

from __future__ import annotations

import logging
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail

from .models import Pedido

logger = logging.getLogger(__name__)

ESTADOS_CON_EMAIL = {
    Pedido.Estado.CONFIRMADO: (
        'Pedido {numero} confirmado',
        'Hola {nombre},\n\nTu pedido {numero} fue confirmado. '
        'Estamos preparándolo.\n\nTotal: ${total}\n\nGracias por tu compra.',
    ),
    Pedido.Estado.LISTO_RETIRO: (
        'Pedido {numero} listo para retiro',
        'Hola {nombre},\n\nTu pedido {numero} está listo para retirar.\n\n'
        'Presentate con tu número de pedido.',
    ),
    Pedido.Estado.DESPACHADO: (
        'Pedido {numero} despachado',
        'Hola {nombre},\n\nTu pedido {numero} fue despachado y está en camino.',
    ),
    Pedido.Estado.ENTREGADO: (
        'Pedido {numero} entregado',
        'Hola {nombre},\n\nTu pedido {numero} fue entregado. ¡Gracias!',
    ),
    Pedido.Estado.CANCELADO: (
        'Pedido {numero} cancelado',
        'Hola {nombre},\n\nTu pedido {numero} fue cancelado. '
        'Si tenés dudas, contactanos.',
    ),
}


def url_whatsapp_pedido(pedido: Pedido) -> str:
    """Link wa.me con mensaje prellenado (vacío si no hay WHATSAPP_TIENDA)."""
    numero = getattr(settings, 'WHATSAPP_TIENDA', '')
    if not numero:
        return ''
    texto = quote(
        f'Hola, consulto por mi pedido {pedido.numero} '
        f'({pedido.get_estado_display()}).'
    )
    return f'https://wa.me/{numero}?text={texto}'


def enviar_email_cambio_estado(pedido: Pedido, estado_anterior: str | None) -> None:
    """Envía email si el estado cambió a uno notificable."""
    if estado_anterior == pedido.estado:
        return

    plantilla = ESTADOS_CON_EMAIL.get(pedido.estado)
    if plantilla is None:
        return

    asunto_tpl, cuerpo_tpl = plantilla
    ctx = {
        'numero': pedido.numero,
        'nombre': pedido.nombre_cliente,
        'total': pedido.total,
    }
    try:
        send_mail(
            subject=asunto_tpl.format(**ctx),
            message=cuerpo_tpl.format(**ctx),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[pedido.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception('No se pudo enviar email del pedido %s', pedido.numero)
