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
    readonly_fields = ('created_at',)


@admin.register(ImportacionStock)
class ImportacionStockAdmin(admin.ModelAdmin):
    list_display = ('id', 'fuente', 'ok', 'iniciada_en', 'finalizada_en')
    list_filter = ('fuente', 'ok')
    readonly_fields = ('iniciada_en', 'finalizada_en', 'detalle')
    search_fields = ('detalle',)
