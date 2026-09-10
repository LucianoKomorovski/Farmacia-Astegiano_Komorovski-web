from django.contrib import admin

from .models import Banner


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'activo', 'orden', 'vigente_desde', 'vigente_hasta')
    list_editable = ('activo', 'orden')
    list_filter = ('activo',)
    search_fields = ('titulo', 'subtitulo')
    fieldsets = (
        (None, {
            'fields': ('titulo', 'subtitulo', 'imagen'),
        }),
        ('Botón', {
            'fields': ('link', 'texto_boton'),
        }),
        ('Publicación', {
            'fields': ('activo', 'orden', 'vigente_desde', 'vigente_hasta'),
            'description': 'En la portada se muestran como máximo 3 banners vigentes.',
        }),
    )
