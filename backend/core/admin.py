from django.contrib import admin

from .models import Banner, PromocionBancaria


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


@admin.register(PromocionBancaria)
class PromocionBancariaAdmin(admin.ModelAdmin):
    list_display = (
        'banco',
        'beneficio',
        'dias_aplica',
        'activo',
        'orden',
        'vigente_desde',
        'vigente_hasta',
    )
    list_editable = ('activo', 'orden')
    list_filter = (
        'activo',
        'lunes',
        'martes',
        'miercoles',
        'jueves',
        'viernes',
        'sabado',
        'domingo',
    )
    search_fields = ('banco', 'beneficio', 'condiciones')
    fieldsets = (
        (None, {
            'fields': ('banco', 'beneficio', 'condiciones', 'logo'),
        }),
        ('Días en que aplica', {
            'fields': (
                ('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo'),
            ),
            'description': (
                'Marcá uno o más días. En el home (carrusel y sección) solo se '
                'muestran las vigentes del día de hoy.'
            ),
        }),
        ('Publicación', {
            'fields': ('activo', 'orden', 'vigente_desde', 'vigente_hasta'),
        }),
    )

    @admin.display(description='Días')
    def dias_aplica(self, obj: PromocionBancaria) -> str:
        return obj.etiquetas_dias
