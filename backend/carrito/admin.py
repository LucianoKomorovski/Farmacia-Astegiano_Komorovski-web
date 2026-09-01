from django.contrib import admin

from .models import Carrito, LineaCarrito


class LineaCarritoInline(admin.TabularInline):
    model = LineaCarrito
    extra = 0
    autocomplete_fields = ('producto',)


@admin.register(Carrito)
class CarritoAdmin(admin.ModelAdmin):
    list_display = ('id', 'usuario', 'session_key', 'modo', 'updated_at')
    list_filter = ('modo',)
    search_fields = ('session_key', 'usuario__username')
    inlines = (LineaCarritoInline,)


@admin.register(LineaCarrito)
class LineaCarritoAdmin(admin.ModelAdmin):
    list_display = ('carrito', 'producto', 'cantidad', 'precio_unitario')
    search_fields = ('producto__nombre', 'producto__sku')
    autocomplete_fields = ('carrito', 'producto')
