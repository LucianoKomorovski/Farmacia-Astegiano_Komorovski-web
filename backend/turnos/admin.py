from django.contrib import admin

from .models import Farmacia, Turno


@admin.register(Farmacia)
class FarmaciaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'direccion', 'sucursal')


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    # date_hierarchy da la navegación por año/mes arriba de la lista:
    # el "calendario mensual" editable.
    date_hierarchy = 'fecha'
    list_display = ('fecha', 'farmacia')
    list_editable = ('farmacia',)
    list_per_page = 31
    ordering = ('fecha',)
