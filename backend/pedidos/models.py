from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class FranjaEnvio(models.Model):
    """Franja horaria para envíos (ej. mañana / tarde). Configurable en admin."""

    nombre = models.CharField(max_length=50)
    hora_desde = models.TimeField()
    hora_hasta = models.TimeField()
    activa = models.BooleanField(default=True)
    cupo_max = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Máximo de pedidos por día en esta franja. Vacío = sin límite.',
    )
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['orden', 'hora_desde']
        verbose_name = 'franja de envío'
        verbose_name_plural = 'franjas de envío'

    def __str__(self) -> str:
        return f'{self.nombre} ({self.hora_desde:%H:%M}–{self.hora_hasta:%H:%M})'

    def pedidos_en_fecha(self, fecha) -> int:
        """Pedidos activos asignados a esta franja en una fecha."""
        estados_activos = [
            Pedido.Estado.PENDIENTE_PAGO,
            Pedido.Estado.PENDIENTE_TRANSFERENCIA,
            Pedido.Estado.PENDIENTE_ENCARGUE,
            Pedido.Estado.PENDIENTE_PAGO_ENCARGUE,
            Pedido.Estado.CONFIRMADO,
            Pedido.Estado.EN_PREPARACION,
            Pedido.Estado.LISTO_RETIRO,
            Pedido.Estado.DESPACHADO,
            Pedido.Estado.ENTREGADO,
        ]
        return Pedido.objects.filter(
            franja_envio=self,
            fecha_entrega=fecha,
            estado__in=estados_activos,
        ).count()

    def cupo_restante(self, fecha) -> int | None:
        """None = sin límite; 0 o más = cupos libres."""
        if self.cupo_max is None:
            return None
        return max(0, self.cupo_max - self.pedidos_en_fecha(fecha))

    def tiene_cupo(self, fecha) -> bool:
        restante = self.cupo_restante(fecha)
        return restante is None or restante > 0


class Pedido(models.Model):
    """Pedido creado desde el carrito."""

    class Estado(models.TextChoices):
        PENDIENTE_PAGO = 'pendiente_pago', 'Pendiente de pago'
        PENDIENTE_TRANSFERENCIA = 'pendiente_transferencia', 'Pendiente transferencia'
        PENDIENTE_ENCARGUE = 'pendiente_encargue', 'Pendiente confirmación encargue'
        PENDIENTE_PAGO_ENCARGUE = 'pendiente_pago_encargue', 'Encargue aprobado — pendiente pago'
        CONFIRMADO = 'confirmado', 'Confirmado'
        EN_PREPARACION = 'en_preparacion', 'En preparación'
        LISTO_RETIRO = 'listo_retiro', 'Listo para retiro'
        DESPACHADO = 'despachado', 'Despachado'
        ENTREGADO = 'entregado', 'Entregado'
        CANCELADO = 'cancelado', 'Cancelado'

    class Modo(models.TextChoices):
        INMEDIATO = 'inmediato', 'Venta inmediata'
        ENCARGUE = 'encargue', 'A encargue'

    class ModalidadEntrega(models.TextChoices):
        RETIRO_SUCURSAL = 'retiro_sucursal', 'Retiro en sucursal'
        A_COORDINAR = 'a_coordinar', 'A coordinar'
        ENVIO = 'envio', 'Envío a domicilio'

    class MedioPago(models.TextChoices):
        MERCADOPAGO = 'mercadopago', 'Mercado Pago'
        CREDITO = 'credito', 'Tarjeta de crédito'
        DEBITO = 'debito', 'Tarjeta de débito'
        TRANSFERENCIA = 'transferencia', 'Transferencia bancaria'

    numero = models.CharField(max_length=20, unique=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pedidos',
    )
    usuario_id: int | None  # pyright: ignore[reportUninitializedInstanceVariable]

    nombre_cliente = models.CharField(max_length=100)
    email = models.EmailField()
    telefono = models.CharField(max_length=20)

    estado = models.CharField(max_length=30, choices=Estado.choices)
    modo = models.CharField(max_length=20, choices=Modo.choices)
    modalidad_entrega = models.CharField(max_length=20, choices=ModalidadEntrega.choices)

    sucursal_retiro = models.ForeignKey(
        'sucursales.Sucursal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pedidos_retiro',
    )
    sucursal_retiro_id: int | None  # pyright: ignore[reportUninitializedInstanceVariable]

    franja_envio = models.ForeignKey(
        FranjaEnvio,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pedidos',
    )
    franja_envio_id: int | None  # pyright: ignore[reportUninitializedInstanceVariable]

    fecha_entrega = models.DateField(null=True, blank=True)
    direccion_envio = models.TextField(blank=True)

    medio_pago = models.CharField(
        max_length=20,
        choices=MedioPago.choices,
        blank=True,
    )
    notas = models.TextField(blank=True)

    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    costo_envio = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    total = models.DecimalField(max_digits=10, decimal_places=2)

    reservado_hasta = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Hasta cuándo se reserva el stock (pedidos inmediatos).',
    )
    confirmado_en = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'pedido'
        verbose_name_plural = 'pedidos'

    def __str__(self) -> str:
        return self.numero

    @property
    def es_encargue(self) -> bool:
        return self.modo == self.Modo.ENCARGUE

    @property
    def puede_pagar_online(self) -> bool:
        return self.estado in (
            self.Estado.PENDIENTE_PAGO,
            self.Estado.PENDIENTE_PAGO_ENCARGUE,
        )


class LineaPedido(models.Model):
    """Copia congelada de cada ítem del carrito al crear el pedido."""

    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name='lineas',
    )
    pedido_id: int  # pyright: ignore[reportUninitializedInstanceVariable]

    producto = models.ForeignKey(
        'catalogo.Producto',
        on_delete=models.PROTECT,
        related_name='lineas_pedido',
    )
    producto_id: int  # pyright: ignore[reportUninitializedInstanceVariable]

    nombre_snapshot = models.CharField(max_length=150)
    sku_snapshot = models.CharField(max_length=50)
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = 'línea de pedido'
        verbose_name_plural = 'líneas de pedido'

    def __str__(self) -> str:
        return f'{self.cantidad} × {self.nombre_snapshot}'


class EventoPedido(models.Model):
    """Auditoría: cada cambio de estado del pedido queda registrado.

    Responde "¿quién movió este pedido, cuándo y por qué vía?".
    actor NULL = acción automática del sistema (webhook de MP, expiración...).
    """

    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name='eventos',
    )
    pedido_id: int  # pyright: ignore[reportUninitializedInstanceVariable]

    # blank=True: el evento de creación no tiene estado anterior.
    estado_anterior = models.CharField(
        max_length=30,
        choices=Pedido.Estado.choices,
        blank=True,
    )
    estado_nuevo = models.CharField(max_length=30, choices=Pedido.Estado.choices)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='eventos_pedido',
        help_text='Vacío = acción automática del sistema.',
    )
    actor_id: int | None  # pyright: ignore[reportUninitializedInstanceVariable]

    detalle = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'evento de pedido'
        verbose_name_plural = 'eventos de pedido'

    def __str__(self) -> str:
        origen = self.estado_anterior or '(nuevo)'
        return f'{self.pedido} — {origen} → {self.estado_nuevo}'


def generar_numero_pedido() -> str:
    """Número legible: FA-2026-000042 (año + secuencia del año)."""
    año = timezone.localdate().year
    prefijo = f'FA-{año}-'
    ultimo = (
        Pedido.objects.filter(numero__startswith=prefijo)
        .order_by('-numero')
        .values_list('numero', flat=True)
        .first()
    )
    if ultimo:
        secuencia = int(ultimo.split('-')[-1]) + 1
    else:
        secuencia = 1
    return f'{prefijo}{secuencia:06d}'
