from django.contrib import admin

from .models import ImportacionStock, ReservaStock, StockWeb


class StockWebInline(admin.StackedInline):
    """Muestra el stock en la misma pantalla del producto (admin)."""

    model = StockWeb
    extra = 1  # si no hay stock, ofrece 1 formulario vacío para crearlo
    max_num = 1  # OneToOne: nunca más de un stock por producto


@admin.register(StockWeb)
class StockWebAdmin(admin.ModelAdmin):
    list_display = ('producto', 'cantidad', 'tope_web', 'margen_seguridad', 'origen', 'actualizado_en')
    list_filter = ('origen',)
    search_fields = ('producto__nombre', 'producto__sku')
    autocomplete_fields = ('producto',)
    list_editable = ('cantidad',)


@admin.register(ReservaStock)
class ReservaStockAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'producto', 'cantidad', 'estado', 'expires_at', 'created_at')
    list_filter = ('estado',)
    search_fields = ('pedido__numero', 'producto__nombre')
    # expires_at es el TTL real de 1 h que usan consolidar_reservas_pedido y
    # expirar_reservas_vencidas. Si el staff lo estira, un webhook approved
    # tardío de Mercado Pago confirmaría el pedido en vez de quedar como
    # _webhook_tarde.
    #
    # cantidad, estado, pedido y producto tampoco se tocan a mano. StockWeb
    # es espejo: disponible = cantidad − reservas activas vigentes, y la
    # consolidación descuenta exactamente reserva.cantidad del producto de
    # esa reserva. Si el staff cambia uno de esos campos, la reserva queda
    # desfasada de las líneas del pedido y el espejo descuenta mal
    # (sobreventa o cupo perdido). Las transiciones siguen en los services
    # de inventario (reservar, consolidar, liberar, expirar).
    readonly_fields = (
        'created_at',
        'expires_at',
        'cantidad',
        'estado',
        'pedido',
        'producto',
    )


@admin.register(ImportacionStock)
class ImportacionStockAdmin(admin.ModelAdmin):
    list_display = ('id', 'fuente', 'ok', 'iniciada_en', 'finalizada_en')
    list_filter = ('fuente', 'ok')
    readonly_fields = ('iniciada_en', 'finalizada_en', 'detalle')
    search_fields = ('detalle',)
