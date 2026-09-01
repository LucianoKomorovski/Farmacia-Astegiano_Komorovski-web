from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum


class Carrito(models.Model):
    """Canasta de compra. En v1 es solo inmediato O solo encargue (no mixto)."""

    class Modo(models.TextChoices):
        INMEDIATO = 'inmediato', 'Venta inmediata'
        ENCARGUE = 'encargue', 'A encargue'

    # null = visitante sin cuenta; lo identificamos por session_key.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='carritos',
    )
    usuario_id: int | None  # pyright: ignore[reportUninitializedInstanceVariable]

    # Clave de la sesión del navegador (cookie). Sirve para guests.
    session_key = models.CharField(max_length=40, blank=True, db_index=True)

    # null mientras el carrito está vacío; se fija con el primer producto.
    modo = models.CharField(
        max_length=20,
        choices=Modo.choices,
        null=True,
        blank=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'carrito'
        verbose_name_plural = 'carritos'

    def __str__(self) -> str:
        dueño = self.usuario or self.session_key or 'sin dueño'
        return f'Carrito {self.pk} ({dueño})'

    @property
    def cantidad_items(self) -> int:
        """Suma de unidades en todas las líneas."""
        # related_name='lineas' en LineaCarrito → carrito.lineas
        total = self.lineas.aggregate(t=Sum('cantidad'))['t']  # pyright: ignore[reportAttributeAccessIssue]
        return int(total or 0)

    @property
    def subtotal(self) -> Decimal:
        return sum(
            (linea.subtotal for linea in self.lineas.all()),  # pyright: ignore[reportAttributeAccessIssue]
            Decimal('0'),
        )


class LineaCarrito(models.Model):
    """Una fila del carrito: producto + cantidad + precio congelado."""

    carrito = models.ForeignKey(
        Carrito,
        on_delete=models.CASCADE,
        related_name='lineas',
    )
    carrito_id: int  # pyright: ignore[reportUninitializedInstanceVariable]

    producto = models.ForeignKey(
        'catalogo.Producto',
        on_delete=models.CASCADE,
        related_name='lineas_carrito',
    )
    producto_id: int  # pyright: ignore[reportUninitializedInstanceVariable]

    cantidad = models.PositiveIntegerField(default=1)
    # Snapshot: si mañana cambia el precio del producto, esta línea no cambia.
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = 'línea de carrito'
        verbose_name_plural = 'líneas de carrito'
        # Un producto aparece una sola vez por carrito (se suma cantidad).
        constraints = [
            models.UniqueConstraint(
                fields=['carrito', 'producto'],
                name='unica_linea_producto_por_carrito',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.cantidad} × {self.producto}'

    @property
    def subtotal(self) -> Decimal:
        return self.precio_unitario * self.cantidad
