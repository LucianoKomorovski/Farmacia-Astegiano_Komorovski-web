import json
import logging

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from pedidos.models import Pedido
from pedidos.views import SESSION_PEDIDOS_KEY, _puede_ver_pedido, _registrar_pedido_en_sesion

from .services import (
    PagoError,
    crear_preferencia_mp,
    mp_configurado,
    procesar_notificacion_mp,
    validar_firma_webhook,
)

logger = logging.getLogger(__name__)


def iniciar_pago(request: HttpRequest, numero: str) -> HttpResponse:
    """Redirige a Mercado Pago Checkout Pro."""
    pedido = get_object_or_404(Pedido.objects.prefetch_related('lineas'), numero=numero)

    if not _puede_ver_pedido(request, pedido):
        return HttpResponseForbidden('No tenés permiso para pagar este pedido.')

    if not pedido.puede_pagar_online:
        messages.error(request, 'Este pedido no está pendiente de pago.')
        return redirect('pedido_confirmacion', numero=numero)

    if not mp_configurado():
        messages.warning(
            request,
            'El pago online no está configurado. Contactá a la farmacia.',
        )
        return redirect('pedido_confirmacion', numero=numero)

    try:
        _, init_point = crear_preferencia_mp(request, pedido)
    except PagoError as exc:
        messages.error(request, str(exc))
        return redirect('pedido_confirmacion', numero=numero)

    return redirect(init_point)


def retorno_mp(request: HttpRequest, numero: str, resultado: str) -> HttpResponse:
    """Página de retorno desde Mercado Pago (success/failure/pending)."""
    pedido = get_object_or_404(Pedido, numero=numero)

    if not _puede_ver_pedido(request, pedido):
        return HttpResponseForbidden('No tenés permiso para ver este pedido.')

    _registrar_pedido_en_sesion(request, numero)

    mensajes = {
        'exito': '¡Pago recibido! Tu pedido se confirmará en breve.',
        'fallo': 'El pago no se completó. Podés intentar de nuevo.',
        'pendiente': 'Tu pago está en proceso. Te avisaremos cuando se acredite.',
    }
    if resultado in mensajes:
        nivel = messages.SUCCESS if resultado == 'exito' else messages.WARNING
        messages.add_message(request, nivel, mensajes[resultado])

    return redirect('pedido_confirmacion', numero=numero)


@csrf_exempt
@require_POST
def webhook_mp(request: HttpRequest) -> HttpResponse:
    """Notificaciones IPN de Mercado Pago (sin CSRF; validamos firma)."""
    if not validar_firma_webhook(request):
        logger.warning('Webhook MP rechazado: firma inválida')
        return HttpResponse(status=401)

    try:
        body = json.loads(request.body.decode() or '{}')
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    topic = request.GET.get('topic') or body.get('type', '')
    data_id = request.GET.get('data.id') or body.get('data', {}).get('id', '')

    if topic == 'payment' and data_id:
        try:
            procesar_notificacion_mp(str(data_id))
        except PagoError:
            logger.exception('Error procesando pago MP %s', data_id)

    return HttpResponse(status=200)
