from django.contrib import admin

from inventario.admin import StockWebInline

from .models import Categoria, Producto


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activa', 'orden')
    list_editable = ('activa', 'orden')
    prepopulated_fields = {'slug': ('nombre',)}
    search_fields = ('nombre',)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'sku',
        'categoria',
        'tipo',
        'precio',
        'activo',
        'requiere_receta',
    )
    list_filter = ('tipo', 'activo', 'requiere_receta', 'categoria')
    list_editable = ('activo',)
    search_fields = ('nombre', 'sku', 'codigo_barras', 'codigo_praxys')
    prepopulated_fields = {'slug': ('nombre',)}
    autocomplete_fields = ('categoria',)
    inlines = (StockWebInline,)
    # El staff ve receta en admin, pero esos productos no salen al público.
    fieldsets = (
        (None, {
            'fields': (
                'nombre',
                'slug',
                'categoria',
                'descripcion',
                'imagen',
            ),
        }),
        ('Códigos', {
            'fields': ('sku', 'codigo_barras', 'codigo_praxys'),
            'description': 'sku es de la web; los otros sirven para cruzar con Praxys.',
        }),
        ('Venta', {
            'fields': ('tipo', 'precio', 'activo', 'requiere_receta'),
        }),
    )
