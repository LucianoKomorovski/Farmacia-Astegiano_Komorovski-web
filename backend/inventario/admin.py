from django.contrib import admin
from django.http import HttpRequest

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

    # El alta y el borrado tampoco. Una reserva nace en
    # reservar_stock_para_pedido y se suelta con liberar / expirar (o se
    # consolida al cobrar). Borrar la fila a mano no pasa por ahí: el
    # disponible (cantidad − reservas activas vigentes) sube y el pedido
    # sigue pendiente de pago. Si queda otra reserva de ese pedido,
    # consolidar_reservas_pedido confirma y descuenta solo las que siguen;
    # el producto borrado no baja de StockWeb (sobreventa).
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ReservaStock | None = None,
    ) -> bool:
        return False


@admin.register(ImportacionStock)
class ImportacionStockAdmin(admin.ModelAdmin):
    list_display = ('id', 'fuente', 'ok', 'iniciada_en', 'finalizada_en')
    list_filter = ('fuente', 'ok')
    readonly_fields = ('iniciada_en', 'finalizada_en', 'detalle')
    search_fields = ('detalle',)
