from django.contrib import admin

from inventario.admin import StockWebInline

from .models import Categoria, Producto


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activa', 'orden', 'icono')
    list_editable = ('activa', 'orden', 'icono')
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
        'precio_anterior',
        'destacado',
        'activo',
        'requiere_receta',
    )
    list_filter = ('tipo', 'activo', 'destacado', 'requiere_receta', 'categoria')
    list_editable = ('activo', 'destacado', 'precio_anterior')
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
            'fields': ('tipo', 'precio', 'precio_anterior', 'destacado', 'activo', 'requiere_receta'),
            'description': (
                'Si "precio anterior" es mayor que "precio", el producto sale como OFERTA '
                'con el porcentaje calculado automáticamente.'
            ),
        }),
    )
