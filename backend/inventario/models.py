from django.db import models
from django.db.models import Sum
from django.utils import timezone


class StockWeb(models.Model):
    """Cupo de unidades que la WEB puede vender. No es el stock de Praxys.

    Un producto tiene como máximo un StockWeb (relación 1 a 1).
    """

    class Origen(models.TextChoices):
        MANUAL = 'manual', 'Carga manual (admin)'
        CSV = 'csv', 'Importación CSV'
        API = 'api', 'API Praxys'

    producto = models.OneToOneField(
        'catalogo.Producto',
        on_delete=models.CASCADE,
        related_name='stock',
    )
    producto_id: int  # pyright: ignore[reportUninitializedInstanceVariable]

    cantidad = models.PositiveIntegerField(
        default=0,
        help_text='Unidades publicables ahora.',
    )
    tope_web = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Máximo a publicar. Vacío = sin tope. Se usa al importar.',
    )
    margen_seguridad = models.PositiveIntegerField(
        default=0,
        help_text='Al importar: stock_web = stock_praxys − este número.',
    )
    origen = models.CharField(
        max_length=10,
        choices=Origen.choices,
        default=Origen.MANUAL,
    )
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'stock web'
        verbose_name_plural = 'stocks web'

    def __str__(self) -> str:
        return f'{self.producto} — {self.cantidad} u.'

    @property
    def cantidad_reservada(self) -> int:
        """Suma de reservas activas (aún no vencidas)."""
        ahora = timezone.now()
        total = (
            ReservaStock.objects.filter(
                producto_id=self.producto_id,
                estado=ReservaStock.Estado.ACTIVA,
                expires_at__gt=ahora,
            ).aggregate(s=Sum('cantidad'))['s']
        )
        return total or 0

    @property
    def cantidad_disponible(self) -> int:
        return max(0, self.cantidad - self.cantidad_reservada)


class ReservaStock(models.Model):
    """Bloqueo temporal de stock al crear un pedido inmediato (TTL 1 h)."""

    class Estado(models.TextChoices):
        ACTIVA = 'activa', 'Activa'
        CONSOLIDADA = 'consolidada', 'Consolidada (vendida)'
        LIBERADA = 'liberada', 'Liberada (cancelación)'
        EXPIRADA = 'expirada', 'Expirada (timeout)'

    producto = models.ForeignKey(
        'catalogo.Producto',
        on_delete=models.CASCADE,
        related_name='reservas',
    )
    producto_id: int  # pyright: ignore[reportUninitializedInstanceVariable]

    pedido = models.ForeignKey(
        'pedidos.Pedido',
        on_delete=models.CASCADE,
        related_name='reservas',
    )
    pedido_id: int  # pyright: ignore[reportUninitializedInstanceVariable]

    cantidad = models.PositiveIntegerField()
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.ACTIVA)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'reserva de stock'
        verbose_name_plural = 'reservas de stock'
        indexes = [
            models.Index(fields=['estado', 'expires_at']),
        ]

    def __str__(self) -> str:
        return f'{self.cantidad} u. → {self.pedido} ({self.estado})'


class ImportacionStock(models.Model):
    """Log de cada importación de stock (CSV o API Praxys)."""

    class Fuente(models.TextChoices):
        CSV = 'csv', 'CSV'
        API = 'api', 'API'

    fuente = models.CharField(max_length=10, choices=Fuente.choices)
    archivo = models.FileField(upload_to='importaciones/', blank=True, null=True)
    iniciada_en = models.DateTimeField(auto_now_add=True)
    finalizada_en = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    detalle = models.TextField(blank=True)

    class Meta:
        ordering = ['-iniciada_en']
        verbose_name = 'importación de stock'
        verbose_name_plural = 'importaciones de stock'

    def __str__(self) -> str:
        estado = 'OK' if self.ok else 'error'
        return f'{self.get_fuente_display()} {self.iniciada_en:%d/%m/%Y %H:%M} ({estado})'
