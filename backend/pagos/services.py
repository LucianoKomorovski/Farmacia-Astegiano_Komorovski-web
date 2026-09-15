"""Integración Mercado Pago Checkout Pro y confirmación de pagos."""

from __future__ import annotations

import hashlib
import hmac
import logging
from decimal import Decimal
from typing import Any

import mercadopago
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from pedidos.models import Pedido
from pedidos.services import (
    PedidoError,
    cancelar_pedido,
    confirmar_pedido,
    confirmar_transferencia_staff,
)

from .models import Pago

logger = logging.getLogger(__name__)

MEDIOS_MP = {
    Pedido.MedioPago.MERCADOPAGO,
    Pedido.MedioPago.CREDITO,
    Pedido.MedioPago.DEBITO,
}


class PagoError(Exception):
    """Error al iniciar o procesar un pago."""


def mp_configurado() -> bool:
    return bool(getattr(settings, 'MERCADOPAGO_ACCESS_TOKEN', ''))


def mp_modo_local() -> bool:
    """True si no hay SITE_URL HTTPS (solo 127.0.0.1 / localhost)."""
    site = getattr(settings, 'SITE_URL', '')
    return not site.startswith('https://')


def _sdk() -> mercadopago.SDK:
    token = getattr(settings, 'MERCADOPAGO_ACCESS_TOKEN', '')
    if not token:
        raise PagoError('Mercado Pago no está configurado (falta MERCADOPAGO_ACCESS_TOKEN).')
    return mercadopago.SDK(token)


def _base_url(request) -> str:
    """URL absoluta del sitio (para back_urls y webhook)."""
    site = getattr(settings, 'SITE_URL', '').rstrip('/')
    if site:
        return site
    return request.build_absolute_uri('/')[:-1]


def _urls_publicas_https(base: str) -> bool:
    return base.startswith('https://')


def _init_point_mp(data: dict[str, Any]) -> str:
    """Sandbox usa sandbox_init_point; producción usa init_point."""
    token = getattr(settings, 'MERCADOPAGO_ACCESS_TOKEN', '')
    if token.startswith('TEST-'):
        return data.get('sandbox_init_point') or data.get('init_point', '')
    return data.get('init_point') or data.get('sandbox_init_point', '')


def _mensaje_error_mp(response: dict) -> str:
    detalle = response.get('response', {})
    if isinstance(detalle, dict):
        msg = detalle.get('message') or detalle.get('error', '')
        if msg:
            return f'Mercado Pago: {msg}'
    return 'No se pudo iniciar el pago. Intentá de nuevo.'


def _exclusiones_mp(medio: str) -> dict[str, list[dict[str, str]]]:
    """Filtra tipos de pago según lo que eligió el cliente."""
    if medio == Pedido.MedioPago.CREDITO:
        return {'excluded_payment_types': [{'id': 'debit_card'}]}
    if medio == Pedido.MedioPago.DEBITO:
        return {'excluded_payment_types': [{'id': 'credit_card'}]}
    return {}


@transaction.atomic
def crear_preferencia_mp(request, pedido: Pedido) -> tuple[Pago, str]:
    """Crea preferencia MP y devuelve (Pago, init_point URL)."""
    if pedido.medio_pago not in MEDIOS_MP:
        raise PagoError('Este pedido no usa pago online.')

    estados_pagables = (
        Pedido.Estado.PENDIENTE_PAGO,
        Pedido.Estado.PENDIENTE_PAGO_ENCARGUE,
    )
    if pedido.estado not in estados_pagables:
        raise PagoError('Este pedido no está pendiente de pago.')

    pago = Pago.objects.create(
        pedido=pedido,
        medio=pedido.medio_pago,
        estado=Pago.Estado.PENDIENTE,
        monto=pedido.total,
    )

    base = _base_url(request)
    success_url = f'{base}{reverse("pagos_retorno", kwargs={"numero": pedido.numero, "resultado": "exito"})}'
    failure_url = f'{base}{reverse("pagos_retorno", kwargs={"numero": pedido.numero, "resultado": "fallo"})}'
    pending_url = f'{base}{reverse("pagos_retorno", kwargs={"numero": pedido.numero, "resultado": "pendiente"})}'
    webhook_url = f'{base}{reverse("pagos_webhook")}'

    items = [
        {
            'id': linea.sku_snapshot,
            'title': linea.nombre_snapshot[:256],
            'quantity': linea.cantidad,
            'unit_price': float(linea.precio_unitario),
            'currency_id': 'ARS',
        }
        for linea in pedido.lineas.all()
    ]
    if pedido.costo_envio > 0:
        items.append({
            'id': 'envio',
            'title': 'Costo de envío',
            'quantity': 1,
            'unit_price': float(pedido.costo_envio),
            'currency_id': 'ARS',
        })

    preference_data: dict[str, Any] = {
        'items': items,
        'payer': {'email': pedido.email},
        'external_reference': pedido.numero,
        'statement_descriptor': 'FARMACIA ASTEGIANO',
        **_exclusiones_mp(pedido.medio_pago),
    }
    # En local (http://127.0.0.1) MP rechaza back_urls, notification_url y auto_return.
    # Solo items + external_reference → redirect al checkout sandbox.
    if _urls_publicas_https(base):
        preference_data['back_urls'] = {
            'success': success_url,
            'failure': failure_url,
            'pending': pending_url,
        }
        preference_data['notification_url'] = webhook_url
        preference_data['auto_return'] = 'approved'

    sdk = _sdk()
    response = sdk.preference().create(preference_data)
    data = response.get('response', {})

    if response.get('status') not in (200, 201) or 'id' not in data:
        logger.error('MP preference error: %s', response)
        raise PagoError(_mensaje_error_mp(response))

    pago.id_externo = str(data['id'])
    pago.raw_payload = data
    pago.save(update_fields=['id_externo', 'raw_payload'])

    init_point = _init_point_mp(data)
    if not init_point:
        raise PagoError('Mercado Pago no devolvió URL de pago.')

    return pago, init_point


def validar_firma_webhook(request) -> bool:
    """Valida x-signature de Mercado Pago (HMAC SHA256)."""
    secret = getattr(settings, 'MERCADOPAGO_WEBHOOK_SECRET', '')
    if not secret:
        # Sin secret configurado: solo aceptamos en DEBUG (desarrollo).
        return settings.DEBUG

    x_signature = request.headers.get('x-signature', '')
    x_request_id = request.headers.get('x-request-id', '')
    data_id = request.GET.get('data.id', request.GET.get('id', ''))

    parts = dict(p.split('=', 1) for p in x_signature.split(',') if '=' in p)
    ts = parts.get('ts', '')
    received_hash = parts.get('v1', '')

    manifest = f'id:{data_id};request-id:{x_request_id};ts:{ts};'
    expected = hmac.new(
        secret.encode(),
        manifest.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, received_hash)


def _buscar_pago_mp(pedido: Pedido, payment_id: str, data: dict[str, Any]) -> Pago | None:
    """Reintenta de MP: primero payment_id, después preference_id."""
    ids_pago = {str(payment_id)}
    data_id = data.get('id')
    if data_id is not None and str(data_id):
        ids_pago.add(str(data_id))

    pago = (
        Pago.objects.filter(pedido=pedido, id_externo__in=ids_pago)
        .order_by('-created_at')
        .first()
    )
    if pago is not None:
        return pago

    preference_id = data.get('preference_id') or ''
    if not preference_id:
        return None
    return (
        Pago.objects.filter(pedido=pedido, id_externo=str(preference_id))
        .order_by('-created_at')
        .first()
    )


def _persistir_webhook_tarde(
    pago: Pago,
    data: dict[str, Any],
    estado_pedido: str,
) -> None:
    """Guarda el cobro de MP sin confirmar el pedido (conciliación / reembolso).

    El dinero llegó (status approved) pero no se consolidó stock. Marcamos el
    Pago APROBADO para que staff lo vea, con _webhook_tarde para no confundirlo
    con una confirmación exitosa.
    """
    payload = dict(data)
    payload['_webhook_tarde'] = True
    payload['_pedido_estado'] = estado_pedido
    pago.raw_payload = payload
    campos = ['raw_payload', 'id_externo']
    # Idempotente: el mismo payment_id no vuelve a "aprobar" un Pago ya marcado.
    if pago.estado != Pago.Estado.APROBADO:
        pago.estado = Pago.Estado.APROBADO
        pago.confirmado_en = timezone.now()
        campos.extend(['estado', 'confirmado_en'])
    pago.save(update_fields=campos)


def _cancelar_si_sigue_pagable_online(pedido: Pedido, motivo: str) -> None:
    """Saca el pedido de pendiente_pago para que no se abra otro Checkout Pro."""
    if pedido.estado not in (
        Pedido.Estado.PENDIENTE_PAGO,
        Pedido.Estado.PENDIENTE_PAGO_ENCARGUE,
    ):
        return
    try:
        cancelar_pedido(pedido, motivo=motivo)
    except PedidoError as exc:
        # No re-lanzamos: el webhook debe responder 200 igual.
        logger.warning(
            'No se pudo cancelar pedido %s tras webhook tarde: %s',
            pedido.numero,
            exc,
        )


@transaction.atomic
def procesar_notificacion_mp(payment_id: str) -> None:
    """Consulta el pago en MP y actualiza pedido si fue aprobado."""
    sdk = _sdk()
    response = sdk.payment().get(payment_id)
    data = response.get('response', {})

    if response.get('status') != 200:
        logger.warning('MP payment get failed: %s', response)
        return

    external_ref = data.get('external_reference', '')
    if not external_ref:
        return

    try:
        pedido = Pedido.objects.select_for_update().get(numero=external_ref)
    except Pedido.DoesNotExist:
        logger.warning('Pedido no encontrado para MP ref: %s', external_ref)
        return

    estado_mp = data.get('status', '')
    payment_id_str = str(data.get('id', payment_id))
    pago = _buscar_pago_mp(pedido, payment_id, data)
    if pago is None:
        pago = Pago.objects.create(
            pedido=pedido,
            medio=pedido.medio_pago,
            monto=Decimal(str(data.get('transaction_amount', pedido.total))),
            id_externo=payment_id_str,
        )

    pago.raw_payload = data
    pago.id_externo = payment_id_str

    estados_pagables = (
        Pedido.Estado.PENDIENTE_PAGO,
        Pedido.Estado.PENDIENTE_PAGO_ENCARGUE,
    )

    if estado_mp == 'approved':
        # Reintento después de confirmar: sincronizar Pago y no volver a confirmar.
        if pedido.estado == Pedido.Estado.CONFIRMADO:
            if pago.estado != Pago.Estado.APROBADO:
                pago.estado = Pago.Estado.APROBADO
                pago.confirmado_en = timezone.now()
                pago.save()
            else:
                pago.save(update_fields=['raw_payload', 'id_externo'])
            return

        # TTL / cancelado / otro estado: no confirmar (evita 500 → retry MP).
        if pedido.estado not in estados_pagables:
            logger.warning(
                'Webhook MP tarde: pedido %s en estado %s (payment_id=%s). '
                'Se registra el cobro para conciliar; no se confirma el pedido.',
                pedido.numero,
                pedido.estado,
                payment_id_str,
            )
            _persistir_webhook_tarde(pago, data, pedido.estado)
            return

        try:
            confirmar_pedido(pedido, via_pago=pago)
        except PedidoError as exc:
            # Reserva EXPIRADA/LIBERADA: no dejar el pedido pagable (doble cobro).
            # refresh: el savepoint de confirmar_pedido se revirtió; la instancia
            # en memoria podría haber quedado a medio camino.
            pedido.refresh_from_db()
            estado_al_fallar = pedido.estado
            logger.warning(
                'Webhook MP no pudo confirmar pedido %s (estado=%s, payment_id=%s): %s',
                pedido.numero,
                estado_al_fallar,
                payment_id_str,
                exc,
            )
            _cancelar_si_sigue_pagable_online(
                pedido,
                motivo='Webhook Mercado Pago tarde: no se pudo confirmar (reserva expirada).',
            )
            _persistir_webhook_tarde(pago, data, estado_al_fallar)
            return

        if pago.estado != Pago.Estado.APROBADO:
            pago.estado = Pago.Estado.APROBADO
            pago.confirmado_en = timezone.now()
            pago.save()
        else:
            pago.save(update_fields=['raw_payload', 'id_externo'])
    elif estado_mp in ('rejected', 'cancelled'):
        pago.estado = Pago.Estado.RECHAZADO
        pago.save(update_fields=['estado', 'raw_payload', 'id_externo'])
    else:
        pago.save(update_fields=['raw_payload', 'id_externo'])


@transaction.atomic
def registrar_transferencia_pendiente(pedido: Pedido) -> Pago:
    """Crea registro de pago por transferencia (staff confirma después)."""
    return Pago.objects.create(
        pedido=pedido,
        medio=Pago.Medio.TRANSFERENCIA,
        estado=Pago.Estado.PENDIENTE,
        monto=pedido.total,
    )


@transaction.atomic
def confirmar_transferencia(pedido: Pedido, staff_user) -> None:
    """Staff confirma que llegó la transferencia.

    Toda la confirmación va en una transacción (como el webhook): si
    consolidar falla (reserva EXPIRADA), se revierte el Pago APROBADO.
    Si no, un reintento no encuentra PENDIENTE y crea un segundo APROBADO.
    """
    pago = (
        pedido.pagos.filter(medio=Pago.Medio.TRANSFERENCIA, estado=Pago.Estado.PENDIENTE)
        .order_by('-created_at')
        .first()
    )
    if pago is None:
        pago = registrar_transferencia_pendiente(pedido)

    pago.estado = Pago.Estado.APROBADO
    pago.confirmado_por = staff_user
    pago.confirmado_en = timezone.now()
    pago.save()

    confirmar_transferencia_staff(pedido, staff_user, via_pago=pago)
