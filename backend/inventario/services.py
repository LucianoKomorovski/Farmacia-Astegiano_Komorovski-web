"""Reservas de stock: crear, consolidar, liberar y expirar."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from .models import ReservaStock, StockWeb


class StockError(Exception):
    """Error de stock (mensaje para el usuario o logs)."""


# Los tests de carrera esperan acá (reserva ya leída, stock todavía sin descontar).
# En producción queda en None y no cambia nada.
pausa_antes_de_descontar = None


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


def _bloquear_stock(producto_id: int) -> int:
    """Toma la fila de StockWeb antes de leer el disponible.

    En Postgres, SELECT FOR UPDATE alcanza. En SQLite Django no emite
    FOR UPDATE, así que dos checkouts leen el mismo número y reservan de
    más. Este UPDATE sí espera al otro y recién ahí se vuelve a contar.
    """
    return StockWeb.objects.filter(producto_id=producto_id).update(
        actualizado_en=timezone.now(),
    )


@transaction.atomic
def reservar_stock_para_pedido(pedido, lineas: list) -> None:
    """Crea reservas activas con TTL. No baja stock_web todavía."""
    expires_at = timezone.now() + ttl_reserva()

    # Mismo orden de productos en todos los pedidos: evita deadlock.
    for linea in sorted(lineas, key=lambda item: item.producto_id):
        if _bloquear_stock(linea.producto_id) == 0:
            raise StockError(f'No hay stock web de "{linea.producto.nombre}".')

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

        # Adentro del lock: el otro checkout espera y vuelve a contar.
        if pausa_antes_de_descontar is not None:
            pausa_antes_de_descontar()

        ReservaStock.objects.create(
            producto_id=linea.producto_id,
            pedido=pedido,
            cantidad=linea.cantidad,
            estado=ReservaStock.Estado.ACTIVA,
            expires_at=expires_at,
        )


@transaction.atomic
def consolidar_reservas_pedido(pedido) -> None:
    """Pago OK: baja stock_web y marca reservas como consolidadas.

    Solo reservas ACTIVA y vigentes (expires_at > ahora). Si no hay ninguna,
    falla: confirmar sin consolidar dejaría el pago OK y el stock sin descontar.
    """
    # list() ejecuta el SELECT FOR UPDATE; exists() no garantiza el lock.
    # En SQLite ese lock no existe: el UPDATE de abajo es el que serializa.
    ahora = timezone.now()
    reservas = list(
        ReservaStock.objects.select_for_update().filter(
            pedido=pedido,
            estado=ReservaStock.Estado.ACTIVA,
            expires_at__gt=ahora,
        ).order_by('producto_id')
    )
    if not reservas:
        raise StockError(
            f'No hay reserva de stock vigente para consolidar el pedido {pedido.numero}.'
        )

    for reserva in reservas:
        if pausa_antes_de_descontar is not None:
            pausa_antes_de_descontar()

        # Solo una transacción gana la reserva. La otra ve 0 filas y aborta
        # (si no, las dos descontarían el mismo stock).
        marcada = ReservaStock.objects.filter(
            pk=reserva.pk,
            estado=ReservaStock.Estado.ACTIVA,
            expires_at__gt=ahora,
        ).update(estado=ReservaStock.Estado.CONSOLIDADA)
        if marcada != 1:
            raise StockError(
                f'No hay reserva de stock vigente para consolidar el pedido {pedido.numero}.'
            )

        # cantidad = cantidad - N en una sola sentencia. Leer, restar en
        # Python y guardar pisa el descuento del otro pago (sobreventa).
        descontado = StockWeb.objects.filter(
            producto_id=reserva.producto_id,
            cantidad__gte=reserva.cantidad,
        ).update(
            cantidad=F('cantidad') - reserva.cantidad,
            actualizado_en=timezone.now(),
        )
        if descontado != 1:
            raise StockError(
                f'Stock insuficiente al confirmar pedido {pedido.numero}.'
            )


@transaction.atomic
def liberar_reservas_pedido(pedido, nuevo_estado: str = ReservaStock.Estado.LIBERADA) -> None:
    """Cancelación o timeout: libera reservas sin tocar stock_web."""
    ReservaStock.objects.filter(
        pedido=pedido,
        estado=ReservaStock.Estado.ACTIVA,
    ).update(estado=nuevo_estado)


def expirar_reservas_vencidas() -> int:
    """Job periódico: marca reservas vencidas y cancela pedidos afectados.

    Cada pedido va en su transacción. Si marcamos EXPIRADA y el proceso
    muere antes de cancelar, el próximo cron ya no ve la reserva y el
    pedido de transferencia queda cobrable para siempre.
    """
    from pedidos.models import Pedido
    from pedidos.services import cancelar_pedido

    ahora = timezone.now()
    pedido_ids = sorted({
        pedido_id
        for pedido_id in ReservaStock.objects.filter(
            estado=ReservaStock.Estado.ACTIVA,
            expires_at__lte=ahora,
        ).values_list('pedido_id', flat=True)
    })
    if not pedido_ids:
        return 0

    cancelados = 0
    for pedido_id in pedido_ids:
        with transaction.atomic():
            # Mismo orden que confirmar: primero el pedido, después la reserva.
            Pedido.objects.filter(pk=pedido_id).update(updated_at=timezone.now())
            try:
                pedido = Pedido.objects.select_for_update().get(pk=pedido_id)
            except Pedido.DoesNotExist:
                continue

            # estado=ACTIVA en el UPDATE: no pisar una reserva ya consolidada.
            hubo = ReservaStock.objects.filter(
                pedido_id=pedido_id,
                estado=ReservaStock.Estado.ACTIVA,
                expires_at__lte=ahora,
            ).update(estado=ReservaStock.Estado.EXPIRADA)
            if not hubo:
                continue

            if pedido.estado in (
                Pedido.Estado.PENDIENTE_PAGO,
                Pedido.Estado.PENDIENTE_TRANSFERENCIA,
            ):
                cancelar_pedido(pedido, motivo='Reserva de stock expirada (1 h).')
                cancelados += 1

    return cancelados
