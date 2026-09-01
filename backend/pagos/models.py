from __future__ import annotations

from django.conf import settings
from django.db import models


class Pago(models.Model):
    """Intento de pago de un pedido (puede haber varios si falla y reintenta)."""

    class Medio(models.TextChoices):
        MERCADOPAGO = 'mercadopago', 'Mercado Pago'
        CREDITO = 'credito', 'Tarjeta de crédito'
        DEBITO = 'debito', 'Tarjeta de débito'
        TRANSFERENCIA = 'transferencia', 'Transferencia bancaria'

    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        APROBADO = 'aprobado', 'Aprobado'
        RECHAZADO = 'rechazado', 'Rechazado'
        REEMBOLSADO = 'reembolsado', 'Reembolsado'

    pedido = models.ForeignKey(
        'pedidos.Pedido',
        on_delete=models.CASCADE,
        related_name='pagos',
    )
    pedido_id: int  # pyright: ignore[reportUninitializedInstanceVariable]

    medio = models.CharField(max_length=20, choices=Medio.choices)
    estado = models.CharField(
        max_length=15,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    monto = models.DecimalField(max_digits=10, decimal_places=2)

    # preference_id o payment_id de Mercado Pago.
    id_externo = models.CharField(max_length=100, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    confirmado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pagos_confirmados',
    )
    confirmado_por_id: int | None  # pyright: ignore[reportUninitializedInstanceVariable]
    confirmado_en = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'pago'
        verbose_name_plural = 'pagos'

    def __str__(self) -> str:
        return f'{self.pedido} — {self.get_medio_display()} ({self.estado})'
