"""Admin de cuentas: solicitudes de personal y usuarios.

Solo las super cuentas (is_superuser) ven esta sección. Las empleadas no
tienen permisos de auth/cuentas, así que ni siquiera aparece en su menú.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as UserAdminBase
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.utils.html import format_html

from .models import PerfilStaff
from .services import CuentaError, aprobar_solicitud, rechazar_solicitud


# Colores planos por estado (clases definidas en static/panel/css/panel.css).
CLASE_ESTADO = {
    PerfilStaff.Estado.PENDIENTE: 'badge-estado badge-estado--pendiente',
    PerfilStaff.Estado.APROBADO: 'badge-estado badge-estado--ok',
    PerfilStaff.Estado.RECHAZADO: 'badge-estado badge-estado--cancelado',
}


@admin.action(description='Aprobar solicitud (habilita el acceso al panel)')
def accion_aprobar(modeladmin: admin.ModelAdmin, request: HttpRequest, queryset) -> None:
    for perfil in queryset.select_related('usuario'):
        try:
            aprobar_solicitud(perfil, request.user)
            messages.success(request, f'{perfil.usuario}: acceso aprobado.')
        except CuentaError as exc:
            messages.warning(request, f'{perfil.usuario}: {exc}')


@admin.action(description='Rechazar / revocar acceso')
def accion_rechazar(modeladmin: admin.ModelAdmin, request: HttpRequest, queryset) -> None:
    for perfil in queryset.select_related('usuario'):
        try:
            rechazar_solicitud(perfil, request.user)
            messages.success(request, f'{perfil.usuario}: acceso rechazado.')
        except CuentaError as exc:
            messages.warning(request, f'{perfil.usuario}: {exc}')


class SoloSuperMixin:
    """Restringe un ModelAdmin a las super cuentas."""

    def has_module_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser

    def has_view_permission(self, request: HttpRequest, obj=None) -> bool:
        return request.user.is_superuser

    def has_add_permission(self, request: HttpRequest) -> bool:
        return request.user.is_superuser

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        return request.user.is_superuser


@admin.register(PerfilStaff)
class PerfilStaffAdmin(SoloSuperMixin, admin.ModelAdmin):
    list_display = (
        'usuario',
        'nombre_completo',
        'email',
        'rol',
        'sucursal',
        'estado_badge',
        'created_at',
        'aprobado_por',
    )
    list_filter = ('estado', 'rol', 'sucursal')
    search_fields = ('usuario__username', 'usuario__first_name', 'usuario__last_name', 'usuario__email')
    list_select_related = ('usuario', 'sucursal', 'aprobado_por')
    readonly_fields = ('estado', 'aprobado_por', 'aprobado_en', 'created_at')
    autocomplete_fields = ('usuario',)
    actions = (accion_aprobar, accion_rechazar)
    list_per_page = 25
    fieldsets = (
        (None, {'fields': ('usuario', 'rol', 'sucursal', 'telefono', 'mensaje')}),
        ('Aprobación', {
            'fields': ('estado', 'aprobado_por', 'aprobado_en', 'created_at'),
            'description': (
                'El estado se cambia con las acciones "Aprobar" / "Rechazar" del listado, '
                'así queda registrado quién lo hizo y cuándo.'
            ),
        }),
    )

    @admin.display(description='Nombre', ordering='usuario__last_name')
    def nombre_completo(self, obj: PerfilStaff) -> str:
        return obj.usuario.get_full_name() or '—'

    @admin.display(description='Email', ordering='usuario__email')
    def email(self, obj: PerfilStaff) -> str:
        return obj.usuario.email or '—'

    @admin.display(description='Estado', ordering='estado')
    def estado_badge(self, obj: PerfilStaff) -> str:
        return format_html(
            '<span class="{}">{}</span>',
            CLASE_ESTADO.get(obj.estado, 'badge-estado'),
            obj.get_estado_display(),
        )

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
        # No se borra el perfil de una super cuenta desde acá.
        if obj is not None and obj.usuario.is_superuser:
            return False
        return request.user.is_superuser


class PerfilStaffInline(admin.StackedInline):
    model = PerfilStaff
    extra = 0
    max_num = 1
    can_delete = False
    fk_name = 'usuario'
    readonly_fields = ('estado', 'aprobado_por', 'aprobado_en')
    fields = ('rol', 'estado', 'sucursal', 'telefono', 'mensaje', 'aprobado_por', 'aprobado_en')
    verbose_name = 'perfil de personal'
    verbose_name_plural = 'perfil de personal'


# Reemplazamos el UserAdmin estándar por uno restringido y con el perfil inline.
# (auth se carga antes que cuentas en INSTALLED_APPS, pero por las dudas...)
if admin.site.is_registered(User):
    admin.site.unregister(User)


@admin.register(User)
class UsuarioAdmin(SoloSuperMixin, UserAdminBase):
    """Usuarios (clientes y personal). Solo para super cuentas.

    Protección de las 3 super cuentas: nadie puede borrarlas ni quitarles
    is_superuser / is_active desde el panel (evita bloquearse entre sí).
    """

    inlines = (PerfilStaffInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'tipo_cuenta', 'is_active', 'date_joined')
    list_filter = ('is_superuser', 'is_staff', 'is_active', 'groups')
    list_select_related = ('perfil_staff',)
    list_per_page = 25
    ordering = ('-date_joined',)

    @admin.display(description='Tipo de cuenta')
    def tipo_cuenta(self, obj: User) -> str:
        if obj.is_superuser:
            return 'Super cuenta'
        if obj.is_staff:
            return 'Personal'
        perfil = getattr(obj, 'perfil_staff', None)
        if perfil is not None and perfil.esta_pendiente:
            return 'Personal (pendiente)'
        return 'Cliente'

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
        if obj is not None and obj.is_superuser:
            return False
        return request.user.is_superuser

    def get_readonly_fields(self, request: HttpRequest, obj=None) -> tuple[str, ...]:
        campos = tuple(super().get_readonly_fields(request, obj))
        if obj is not None and obj.is_superuser:
            # Ni siquiera otra super cuenta puede degradar o desactivar a una super cuenta.
            campos += ('is_superuser', 'is_active', 'is_staff')
        return campos

    def get_inline_instances(self, request: HttpRequest, obj=None):
        # El inline de perfil solo tiene sentido al editar (no al crear).
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)
