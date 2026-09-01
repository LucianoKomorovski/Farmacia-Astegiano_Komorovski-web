from django.contrib import admin

from .models import Pago


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'medio', 'estado', 'monto', 'id_externo', 'created_at')
    list_filter = ('medio', 'estado')
    search_fields = ('pedido__numero', 'id_externo')
    readonly_fields = ('raw_payload', 'created_at', 'confirmado_en')
    raw_id_fields = ('pedido', 'confirmado_por')
