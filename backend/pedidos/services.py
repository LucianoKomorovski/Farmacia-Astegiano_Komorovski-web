from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from carrito.models import Carrito
from carrito.services import lineas_del_carrito
from inventario.services import (
    StockError,
    consolidar_reservas_pedido,
    liberar_reservas_pedido,
    reservar_stock_para_pedido,
    ttl_reserva,
)
from .models import EventoPedido, LineaPedido, Pedido, generar_numero_pedido


class PedidoError(Exception):
    """Error al confirmar el pedido (mensaje para el usuario)."""


def registrar_evento(
    pedido: Pedido,
    estado_anterior: str,
    estado_nuevo: str,
    actor=None,
    detalle: str = '',
) -> None:
    """Deja rastro en la auditoría del pedido (modelo EventoPedido).

    Se llama DENTRO de la transacción de cada transición: si la transición
    falla y se revierte, el evento también (nunca queda auditoría falsa).
    """
    # AnonymousUser no se puede guardar como FK; solo usuarios reales.
    if actor is not None and not getattr(actor, 'is_authenticated', False):
        actor = None
    EventoPedido.objects.create(
        pedido=pedido,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        actor=actor,
        detalle=detalle[:200],
    )


def calcular_costo_envio(subtotal: Decimal, modalidad: str) -> Decimal:
    """Costo de envío según settings (monto fijo; gratis desde umbral)."""
    if modalidad != Pedido.ModalidadEntrega.ENVIO:
        return Decimal('0')

    gratis_desde = getattr(settings, 'ENVIO_GRATIS_DESDE', Decimal('0'))
    if gratis_desde > 0 and subtotal >= gratis_desde:
        return Decimal('0')

    return getattr(settings, 'ENVIO_MONTO_FIJO', Decimal('0'))


def _estado_inicial(modo: str, medio_pago: str) -> str:
    if modo == Carrito.Modo.ENCARGUE:
        return Pedido.Estado.PENDIENTE_ENCARGUE
    if medio_pago == Pedido.MedioPago.TRANSFERENCIA:
        return Pedido.Estado.PENDIENTE_TRANSFERENCIA
    return Pedido.Estado.PENDIENTE_PAGO


def _vaciar_carrito(carrito: Carrito) -> None:
    carrito.lineas.all().delete()  # pyright: ignore[reportAttributeAccessIssue]
    carrito.modo = None
    carrito.save(update_fields=['modo', 'updated_at'])


@transaction.atomic
def crear_pedido_desde_carrito(
    request: HttpRequest,
    carrito: Carrito,
    datos: dict,
) -> Pedido:
    lineas = list(lineas_del_carrito(carrito))
    if not lineas:
        raise PedidoError('El carrito está vacío.')

    if carrito.modo is None:
        raise PedidoError('El carrito no tiene productos válidos.')

    assert carrito.modo is not None
    es_encargue = carrito.modo == Carrito.Modo.ENCARGUE

    modalidad = datos['modalidad_entrega']
    subtotal = carrito.subtotal
    costo_envio = calcular_costo_envio(subtotal, modalidad)
    total = subtotal + costo_envio

    medio_pago = datos['medio_pago'] if datos.get('medio_pago') else ''
    estado = _estado_inicial(carrito.modo, medio_pago)

    reservado_hasta = None
    if not es_encargue:
        reservado_hasta = timezone.now() + ttl_reserva()

    pedido = Pedido.objects.create(
        numero=generar_numero_pedido(),
        usuario=request.user if request.user.is_authenticated else None,
        nombre_cliente=datos['nombre_cliente'].strip(),
        email=datos['email'].strip().lower(),
        telefono=datos['telefono'].strip(),
        estado=estado,
        modo=carrito.modo,
        modalidad_entrega=modalidad,
        sucursal_retiro=datos.get('sucursal_retiro'),
        franja_envio=datos.get('franja_envio'),
        fecha_entrega=datos.get('fecha_entrega'),
        direccion_envio=datos.get('direccion_envio', '').strip(),
        medio_pago=medio_pago,
        notas=datos.get('notas', '').strip(),
        subtotal=subtotal,
        costo_envio=costo_envio,
        total=total,
        reservado_hasta=reservado_hasta,
    )

    for linea in lineas:
        LineaPedido.objects.create(
            pedido=pedido,
            producto=linea.producto,
            nombre_snapshot=linea.producto.nombre,
            sku_snapshot=linea.producto.sku,
            cantidad=linea.cantidad,
            precio_unitario=linea.precio_unitario,
            subtotal=linea.subtotal,
        )

    # Venta inmediata: reserva stock (TTL 1 h), no descuenta hasta confirmar pago.
    if not es_encargue:
        try:
            reservar_stock_para_pedido(pedido, lineas)
        except StockError as exc:
            raise PedidoError(str(exc)) from exc

        if medio_pago == Pedido.MedioPago.TRANSFERENCIA:
            from pagos.services import registrar_transferencia_pendiente

            registrar_transferencia_pendiente(pedido)

    registrar_evento(
        pedido,
        estado_anterior='',  # recién nace: no hay estado previo
        estado_nuevo=estado,
        actor=request.user if request.user.is_authenticated else None,
        detalle='Pedido creado desde el checkout.',
    )

    _vaciar_carrito(carrito)
    return pedido


def pedido_usa_pago_online(pedido: Pedido) -> bool:
    from pagos.services import MEDIOS_MP

    return pedido.medio_pago in MEDIOS_MP


@transaction.atomic
def confirmar_pedido(pedido: Pedido, via_pago=None, actor=None) -> None:
    """Auto-confirmación tras pago MP/tarjeta aprobado."""
    if pedido.estado == Pedido.Estado.CONFIRMADO:
        return

    estados_validos = (
        Pedido.Estado.PENDIENTE_PAGO,
        Pedido.Estado.PENDIENTE_PAGO_ENCARGUE,
    )
    if pedido.estado not in estados_validos:
        raise PedidoError(f'No se puede confirmar un pedido en estado "{pedido.estado}".')

    anterior = pedido.estado
    if pedido.modo == Pedido.Modo.INMEDIATO:
        consolidar_reservas_pedido(pedido)

    pedido.estado = Pedido.Estado.CONFIRMADO
    pedido.confirmado_en = timezone.now()
    pedido.reservado_hasta = None
    pedido.save(update_fields=['estado', 'confirmado_en', 'reservado_hasta', 'updated_at'])

    detalle = 'Pago aprobado.'
    if via_pago is not None:
        detalle = f'Pago aprobado ({via_pago.get_medio_display()}).'
    registrar_evento(pedido, anterior, pedido.estado, actor=actor, detalle=detalle)


@transaction.atomic
def confirmar_transferencia_staff(pedido: Pedido, actor, via_pago=None) -> None:
    """Staff confirma transferencia recibida."""
    if pedido.estado != Pedido.Estado.PENDIENTE_TRANSFERENCIA:
        raise PedidoError('El pedido no está pendiente de transferencia.')

    anterior = pedido.estado
    if pedido.modo == Pedido.Modo.INMEDIATO:
        consolidar_reservas_pedido(pedido)

    pedido.estado = Pedido.Estado.CONFIRMADO
    pedido.confirmado_en = timezone.now()
    pedido.reservado_hasta = None
    pedido.save(update_fields=['estado', 'confirmado_en', 'reservado_hasta', 'updated_at'])

    registrar_evento(
        pedido, anterior, pedido.estado,
        actor=actor, detalle='Transferencia confirmada por staff.',
    )


@transaction.atomic
def aprobar_encargue(pedido: Pedido, actor) -> None:
    """Staff confirma que se puede encargar → habilita el cobro."""
    if pedido.estado != Pedido.Estado.PENDIENTE_ENCARGUE:
        raise PedidoError('El pedido no está pendiente de confirmación de encargue.')

    anterior = pedido.estado
    if pedido.medio_pago == Pedido.MedioPago.TRANSFERENCIA:
        pedido.estado = Pedido.Estado.PENDIENTE_TRANSFERENCIA
        from pagos.services import registrar_transferencia_pendiente

        registrar_transferencia_pendiente(pedido)
    else:
        pedido.estado = Pedido.Estado.PENDIENTE_PAGO_ENCARGUE

    pedido.save(update_fields=['estado', 'updated_at'])

    registrar_evento(
        pedido, anterior, pedido.estado,
        actor=actor, detalle='Encargue aprobado por staff.',
    )


@transaction.atomic
def cancelar_pedido(pedido: Pedido, actor=None, motivo: str = '') -> None:
    """Cancela y libera reservas de stock."""
    if pedido.estado == Pedido.Estado.CANCELADO:
        return
    if pedido.estado == Pedido.Estado.ENTREGADO:
        raise PedidoError('No se puede cancelar un pedido ya entregado.')

    anterior = pedido.estado
    if pedido.modo == Pedido.Modo.INMEDIATO:
        liberar_reservas_pedido(pedido)

    pedido.estado = Pedido.Estado.CANCELADO
    pedido.reservado_hasta = None
    pedido.save(update_fields=['estado', 'reservado_hasta', 'updated_at'])

    registrar_evento(
        pedido, anterior, pedido.estado,
        actor=actor, detalle=motivo or 'Pedido cancelado.',
    )


@transaction.atomic
def avanzar_fulfillment(pedido: Pedido, nuevo_estado: str, actor=None) -> None:
    """Avanza estados de preparación/entrega (solo staff)."""
    transiciones = {
        Pedido.Estado.CONFIRMADO: {
            Pedido.Estado.EN_PREPARACION,
        },
        Pedido.Estado.EN_PREPARACION: {
            Pedido.Estado.LISTO_RETIRO,
            Pedido.Estado.DESPACHADO,
        },
        Pedido.Estado.LISTO_RETIRO: {Pedido.Estado.ENTREGADO},
        Pedido.Estado.DESPACHADO: {Pedido.Estado.ENTREGADO},
    }
    permitidos = transiciones.get(pedido.estado, set())
    if nuevo_estado not in permitidos:
        raise PedidoError(
            f'No se puede pasar de "{pedido.get_estado_display()}" '
            f'a "{Pedido.Estado(nuevo_estado).label}".'
        )
    anterior = pedido.estado
    pedido.estado = nuevo_estado
    pedido.save(update_fields=['estado', 'updated_at'])

    registrar_evento(pedido, anterior, nuevo_estado, actor=actor)
