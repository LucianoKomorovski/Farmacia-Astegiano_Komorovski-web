"""Lógica de negocio de cuentas: vinculación de pedidos y personal.

Las vistas y el admin llaman a estas funciones; así la regla vive en un
solo lugar y se puede testear sin pasar por HTTP.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from pedidos.models import Pedido
from pedidos.views import SESSION_PEDIDOS_KEY

from .models import PerfilStaff

logger = logging.getLogger(__name__)

# Nombre del grupo de Django que reúne los permisos operativos del personal.
GRUPO_EMPLEADAS = 'Empleadas'

# Permisos que recibe una empleada aprobada, como (app_label, codename).
# Regla: opera pedidos y edita catálogo/stock/marketing/turnos; NO ve pagos
# crudos, carritos ni cuentas, y NO borra pedidos.
PERMISOS_EMPLEADAS: tuple[tuple[str, str], ...] = (
    # Pedidos: ver y cambiar (las acciones de estado van por change_pedido).
    ('pedidos', 'view_pedido'),
    ('pedidos', 'change_pedido'),
    ('pedidos', 'view_lineapedido'),
    ('pedidos', 'view_eventopedido'),
    ('pedidos', 'view_franjaenvio'),
    ('pedidos', 'change_franjaenvio'),
    ('pedidos', 'add_franjaenvio'),
    # Catálogo.
    ('catalogo', 'view_producto'),
    ('catalogo', 'add_producto'),
    ('catalogo', 'change_producto'),
    ('catalogo', 'view_categoria'),
    ('catalogo', 'add_categoria'),
    ('catalogo', 'change_categoria'),
    # Inventario: el stock se edita; reservas e importaciones solo se consultan.
    ('inventario', 'view_stockweb'),
    ('inventario', 'add_stockweb'),
    ('inventario', 'change_stockweb'),
    ('inventario', 'view_reservastock'),
    ('inventario', 'view_importacionstock'),
    # Marketing.
    ('core', 'view_banner'),
    ('core', 'add_banner'),
    ('core', 'change_banner'),
    ('core', 'view_promocionbancaria'),
    ('core', 'add_promocionbancaria'),
    ('core', 'change_promocionbancaria'),
    # Turnos y sucursales.
    ('turnos', 'view_farmacia'),
    ('turnos', 'add_farmacia'),
    ('turnos', 'change_farmacia'),
    ('turnos', 'view_turno'),
    ('turnos', 'add_turno'),
    ('turnos', 'change_turno'),
    ('sucursales', 'view_sucursal'),
    ('sucursales', 'change_sucursal'),
    # Contenido institucional.
    ('servicios', 'view_servicio'),
    ('servicios', 'change_servicio'),
    ('aboutUs', 'view_sobrenosotros'),
    ('aboutUs', 'change_sobrenosotros'),
)


class CuentaError(Exception):
    """Error de negocio al operar cuentas de personal (mensaje para el usuario)."""


def vincular_pedidos_de_sesion(request: HttpRequest, user: User) -> int:
    """Asocia al usuario los pedidos que hizo como invitado en este navegador.

    La sesión guarda los números de pedido creados sin estar logueado
    (SESSION_PEDIDOS_KEY). Al iniciar sesión, esos pedidos pasan a la cuenta.

    Importante: solo se toman pedidos SIN dueño (usuario NULL). Nunca se
    re-asigna un pedido que ya pertenece a otra cuenta.

    Devuelve cuántos pedidos se vincularon.
    """
    numeros: list[str] = request.session.get(SESSION_PEDIDOS_KEY, [])
    if not numeros:
        return 0
    return Pedido.objects.filter(
        numero__in=numeros,
        usuario__isnull=True,
    ).update(usuario=user)


# ---------------------------------------------------------------------------
# Personal: roles, aprobación y avisos
# ---------------------------------------------------------------------------


def es_super_cuenta(user) -> bool:
    """Las 3 super cuentas (dueños + desarrollador) son los superusers."""
    return bool(getattr(user, 'is_authenticated', False) and user.is_superuser)


def asegurar_grupo_empleadas() -> Group:
    """Crea (o actualiza) el grupo Empleadas con sus permisos.

    Es idempotente: se puede correr todas las veces que haga falta
    (comando configurar_roles, seed_datos, al aprobar una cuenta).
    """
    grupo, _ = Group.objects.get_or_create(name=GRUPO_EMPLEADAS)

    permisos = []
    for app_label, codename in PERMISOS_EMPLEADAS:
        permiso = Permission.objects.filter(
            content_type__app_label=app_label,
            codename=codename,
        ).first()
        if permiso is None:
            # Puede pasar si todavía no corrió la migración de esa app.
            logger.warning('Permiso inexistente: %s.%s', app_label, codename)
            continue
        permisos.append(permiso)

    # set() deja el grupo exactamente con esta lista (quita los que sobren).
    grupo.permissions.set(permisos)
    return grupo


def asegurar_perfiles_super_cuentas() -> int:
    """Crea el PerfilStaff (dueño, aprobado) a superusers que no lo tengan.

    La señal post_save lo hace para cuentas nuevas; esto cubre las que ya
    existían antes de agregar el modelo. Devuelve cuántos perfiles creó.
    """
    creados = 0
    for user in User.objects.filter(is_superuser=True, perfil_staff__isnull=True):
        PerfilStaff.objects.create(
            usuario=user,
            rol=PerfilStaff.Rol.DUENIO,
            estado=PerfilStaff.Estado.APROBADO,
        )
        creados += 1
    return creados


def emails_super_cuentas() -> list[str]:
    return list(
        User.objects.filter(is_superuser=True, is_active=True)
        .exclude(email='')
        .values_list('email', flat=True)
    )


def notificar_nueva_solicitud(perfil: PerfilStaff) -> None:
    """Avisa por email a las super cuentas que hay una solicitud nueva."""
    destinatarios = emails_super_cuentas()
    if not destinatarios:
        return
    usuario = perfil.usuario
    nombre = usuario.get_full_name() or usuario.get_username()
    cuerpo = (
        f'{nombre} (usuario "{usuario.get_username()}", {usuario.email}) '
        'solicitó acceso al panel de la farmacia.\n\n'
        f'Sucursal: {perfil.sucursal or "sin especificar"}\n'
        f'Teléfono: {perfil.telefono or "-"}\n'
        f'Mensaje: {perfil.mensaje or "-"}\n\n'
        'Ingresá al panel → Cuentas de personal para aprobarla o rechazarla.'
    )
    # fail_silently: un problema de SMTP no debe romper el registro.
    send_mail(
        subject='[Panel farmacia] Nueva solicitud de acceso de personal',
        message=cuerpo,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        recipient_list=destinatarios,
        fail_silently=True,
    )


def _avisar_resultado(perfil: PerfilStaff, aprobado: bool) -> None:
    usuario = perfil.usuario
    if not usuario.email:
        return
    if aprobado:
        asunto = 'Tu acceso al panel de la farmacia fue aprobado'
        cuerpo = (
            f'Hola {usuario.first_name or usuario.get_username()}, ya podés ingresar '
            'al panel con tu usuario y contraseña.'
        )
    else:
        asunto = 'Tu solicitud de acceso al panel fue rechazada'
        cuerpo = (
            f'Hola {usuario.first_name or usuario.get_username()}, tu solicitud de '
            'acceso al panel no fue aprobada. Si creés que es un error, hablá con '
            'los dueños de la farmacia.'
        )
    send_mail(
        subject=asunto,
        message=cuerpo,
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        recipient_list=[usuario.email],
        fail_silently=True,
    )


@transaction.atomic
def aprobar_solicitud(perfil: PerfilStaff, actor: User) -> None:
    """Una super cuenta aprueba el acceso: habilita is_staff y asigna el rol."""
    if not es_super_cuenta(actor):
        raise CuentaError('Solo una super cuenta puede aprobar solicitudes.')
    if perfil.esta_aprobado:
        raise CuentaError('La cuenta ya estaba aprobada.')

    usuario = perfil.usuario
    usuario.is_active = True
    usuario.is_staff = True  # is_staff = puede entrar al panel
    if perfil.rol == PerfilStaff.Rol.DUENIO:
        usuario.is_superuser = True
    usuario.save(update_fields=['is_active', 'is_staff', 'is_superuser'])

    if perfil.rol == PerfilStaff.Rol.EMPLEADA:
        usuario.groups.add(asegurar_grupo_empleadas())

    perfil.estado = PerfilStaff.Estado.APROBADO
    perfil.aprobado_por = actor
    perfil.aprobado_en = timezone.now()
    perfil.save(update_fields=['estado', 'aprobado_por', 'aprobado_en'])

    _avisar_resultado(perfil, aprobado=True)


@transaction.atomic
def rechazar_solicitud(perfil: PerfilStaff, actor: User) -> None:
    """Rechaza (o revoca) el acceso al panel. La cuenta sigue existiendo
    pero sin is_staff, así que no puede entrar."""
    if not es_super_cuenta(actor):
        raise CuentaError('Solo una super cuenta puede rechazar solicitudes.')

    usuario = perfil.usuario
    if usuario.is_superuser:
        raise CuentaError('No se puede rechazar una super cuenta.')

    usuario.is_staff = False
    usuario.save(update_fields=['is_staff'])
    usuario.groups.remove(*Group.objects.filter(name=GRUPO_EMPLEADAS))

    perfil.estado = PerfilStaff.Estado.RECHAZADO
    perfil.aprobado_por = actor
    perfil.aprobado_en = timezone.now()
    perfil.save(update_fields=['estado', 'aprobado_por', 'aprobado_en'])

    _avisar_resultado(perfil, aprobado=False)
