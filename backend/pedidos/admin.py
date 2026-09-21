from django.contrib import admin, messages
from django.http import HttpRequest
from django.utils.html import format_html

from pagos.services import confirmar_transferencia
from panel.templatetags.panel_extras import clase_estado

from .models import EventoPedido, FranjaEnvio, LineaPedido, Pedido
from .services import PedidoError, aprobar_encargue, avanzar_fulfillment, cancelar_pedido


class LineaPedidoInline(admin.TabularInline):
    model = LineaPedido
    extra = 0
    readonly_fields = (
        'producto',
        'nombre_snapshot',
        'sku_snapshot',
        'cantidad',
        'precio_unitario',
        'subtotal',
    )
    can_delete = False


class EventoPedidoInline(admin.TabularInline):
    """Historial de cambios de estado, solo lectura (la auditoría no se edita)."""

    model = EventoPedido
    extra = 0
    can_delete = False
    readonly_fields = ('created_at', 'estado_anterior', 'estado_nuevo', 'actor', 'detalle')

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(FranjaEnvio)
class FranjaEnvioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'hora_desde', 'hora_hasta', 'cupo_max', 'activa', 'orden')
    list_editable = ('activa', 'orden')
    search_fields = ('nombre',)


@admin.action(description='✓ Confirmar transferencia recibida')
def accion_confirmar_transferencia(modeladmin, request, queryset):
    for pedido in queryset:
        if pedido.estado != Pedido.Estado.PENDIENTE_TRANSFERENCIA:
            messages.warning(request, f'{pedido.numero}: no está pendiente de transferencia.')
            continue
        try:
            confirmar_transferencia(pedido, request.user)
            messages.success(request, f'{pedido.numero}: transferencia confirmada.')
        except Exception as exc:
            messages.error(request, f'{pedido.numero}: {exc}')


@admin.action(description='✓ Aprobar encargue (habilitar pago)')
def accion_aprobar_encargue(modeladmin, request, queryset):
    for pedido in queryset:
        if pedido.estado != Pedido.Estado.PENDIENTE_ENCARGUE:
            messages.warning(request, f'{pedido.numero}: no está pendiente de encargue.')
            continue
        try:
            aprobar_encargue(pedido, request.user)
            messages.success(request, f'{pedido.numero}: encargue aprobado. Cliente puede pagar.')
        except PedidoError as exc:
            messages.error(request, f'{pedido.numero}: {exc}')


@admin.action(description='✗ Cancelar pedido (libera stock)')
def accion_cancelar_pedido(modeladmin, request, queryset):
    for pedido in queryset:
        try:
            cancelar_pedido(pedido, actor=request.user)
            messages.success(request, f'{pedido.numero}: cancelado.')
        except PedidoError as exc:
            messages.error(request, f'{pedido.numero}: {exc}')


@admin.action(description='→ Marcar en preparación')
def accion_en_preparacion(modeladmin, request, queryset):
    for pedido in queryset:
        try:
            avanzar_fulfillment(pedido, Pedido.Estado.EN_PREPARACION, actor=request.user)
        except PedidoError as exc:
            messages.error(request, f'{pedido.numero}: {exc}')


@admin.action(description='→ Marcar listo para retiro')
def accion_listo_retiro(modeladmin, request, queryset):
    for pedido in queryset:
        try:
            avanzar_fulfillment(pedido, Pedido.Estado.LISTO_RETIRO, actor=request.user)
        except PedidoError as exc:
            messages.error(request, f'{pedido.numero}: {exc}')


@admin.action(description='→ Marcar despachado')
def accion_despachado(modeladmin, request, queryset):
    for pedido in queryset:
        try:
            avanzar_fulfillment(pedido, Pedido.Estado.DESPACHADO, actor=request.user)
        except PedidoError as exc:
            messages.error(request, f'{pedido.numero}: {exc}')


@admin.action(description='→ Marcar entregado')
def accion_entregado(modeladmin, request, queryset):
    for pedido in queryset:
        try:
            avanzar_fulfillment(pedido, Pedido.Estado.ENTREGADO, actor=request.user)
        except PedidoError as exc:
            messages.error(request, f'{pedido.numero}: {exc}')


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = (
        'numero',
        'nombre_cliente',
        'estado_badge',
        'modo',
        'modalidad_entrega',
        'medio_pago',
        'total',
        'reservado_hasta',
        'created_at',
    )
    list_filter = ('estado', 'modo', 'modalidad_entrega', 'medio_pago', 'sucursal_retiro')
    search_fields = ('numero', 'nombre_cliente', 'email', 'telefono')
    readonly_fields = ('numero', 'estado', 'created_at', 'updated_at', 'confirmado_en')
    inlines = (LineaPedidoInline, EventoPedidoInline)
    raw_id_fields = ('sucursal_retiro', 'franja_envio', 'usuario')
    # Evita una consulta por fila al mostrar la sucursal / franja en el listado.
    list_select_related = ('sucursal_retiro', 'franja_envio')
    list_per_page = 25
    save_on_top = True
    actions = (
        accion_confirmar_transferencia,
        accion_aprobar_encargue,
        accion_cancelar_pedido,
        accion_en_preparacion,
        accion_listo_retiro,
        accion_despachado,
        accion_entregado,
    )
    date_hierarchy = 'created_at'

    @admin.display(description='Estado', ordering='estado')
    def estado_badge(self, obj: Pedido) -> str:
        """Etiqueta de color plano según el estado (clases en panel.css)."""
        return format_html(
            '<span class="{}">{}</span>',
            clase_estado(obj.estado),
            obj.get_estado_display(),
        )

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
        # Un pedido no se borra: se cancela (queda la auditoría). Solo una
        # super cuenta puede eliminarlo, por ejemplo para limpiar pruebas.
        return request.user.is_superuser
