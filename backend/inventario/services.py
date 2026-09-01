"""Reservas de stock: crear, consolidar, liberar y expirar."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import ReservaStock, StockWeb


class StockError(Exception):
    """Error de stock (mensaje para el usuario o logs)."""


def ttl_reserva() -> timedelta:
    minutos = getattr(settings, 'RESERVA_STOCK_TTL_MINUTOS', 60)
    return timedelta(minutes=minutos)


def _reservas_activas_qs(producto_id: int):
    return ReservaStock.objects.filter(
        producto_id=producto_id,
        estado=ReservaStock.Estado.ACTIVA,
        expires_at__gt=timezone.now(),
    )


def cantidad_disponible(producto_id: int) -> int:
    """Unidades vendibles ahora (stock − reservas activas)."""
    stock = StockWeb.objects.filter(producto_id=producto_id).first()
    if stock is None:
        return 0
    return stock.cantidad_disponible


@transaction.atomic
def reservar_stock_para_pedido(pedido, lineas: list) -> None:
    """Crea reservas activas con TTL. No baja stock_web todavía."""
    expires_at = timezone.now() + ttl_reserva()

    for linea in lineas:
        stock = (
            StockWeb.objects.select_for_update()
            .filter(producto_id=linea.producto_id)
            .first()
        )
        if stock is None:
            raise StockError(f'No hay stock web de "{linea.producto.nombre}".')

        # Recalculamos reservas con la fila bloqueada para evitar sobreventa.
        reservado = (
            _reservas_activas_qs(linea.producto_id).aggregate(s=Sum('cantidad'))['s'] or 0
        )
        disponible = stock.cantidad - reservado
        if linea.cantidad > disponible:
            raise StockError(
                f'No hay stock suficiente de "{linea.producto.nombre}" '
                f'(disponible: {disponible}).'
            )

        ReservaStock.objects.create(
            producto_id=linea.producto_id,
            pedido=pedido,
            cantidad=linea.cantidad,
            estado=ReservaStock.Estado.ACTIVA,
            expires_at=expires_at,
        )


@transaction.atomic
def consolidar_reservas_pedido(pedido) -> None:
    """Pago OK: baja stock_web y marca reservas como consolidadas."""
    reservas = ReservaStock.objects.select_for_update().filter(
        pedido=pedido,
        estado=ReservaStock.Estado.ACTIVA,
    )

    for reserva in reservas:
        stock = (
            StockWeb.objects.select_for_update()
            .filter(producto_id=reserva.producto_id)
            .first()
        )
        if stock is None or stock.cantidad < reserva.cantidad:
            raise StockError(
                f'Stock insuficiente al confirmar pedido {pedido.numero}.'
            )
        stock.cantidad -= reserva.cantidad
        stock.save(update_fields=['cantidad', 'actualizado_en'])
        reserva.estado = ReservaStock.Estado.CONSOLIDADA
        reserva.save(update_fields=['estado'])


@transaction.atomic
def liberar_reservas_pedido(pedido, nuevo_estado: str = ReservaStock.Estado.LIBERADA) -> None:
    """Cancelación o timeout: libera reservas sin tocar stock_web."""
    ReservaStock.objects.filter(
        pedido=pedido,
        estado=ReservaStock.Estado.ACTIVA,
    ).update(estado=nuevo_estado)


def expirar_reservas_vencidas() -> int:
    """Job periódico: marca reservas vencidas y cancela pedidos afectados."""
    from pedidos.models import Pedido
    from pedidos.services import cancelar_pedido

    ahora = timezone.now()
    reservas = list(
        ReservaStock.objects.filter(
            estado=ReservaStock.Estado.ACTIVA,
            expires_at__lte=ahora,
        ).select_related('pedido')
    )
    if not reservas:
        return 0

    pedidos_ids = {r.pedido_id for r in reservas}
    ReservaStock.objects.filter(
        id__in=[r.id for r in reservas],
    ).update(estado=ReservaStock.Estado.EXPIRADA)

    cancelados = 0
    for pedido_id in pedidos_ids:
        pedido = Pedido.objects.get(pk=pedido_id)
        if pedido.estado in (
            Pedido.Estado.PENDIENTE_PAGO,
            Pedido.Estado.PENDIENTE_TRANSFERENCIA,
        ):
            cancelar_pedido(pedido, motivo='Reserva de stock expirada (1 h).')
            cancelados += 1

    return cancelados
