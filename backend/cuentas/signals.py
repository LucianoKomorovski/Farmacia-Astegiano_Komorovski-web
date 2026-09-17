from typing import Any

from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import HttpRequest

from .models import PerfilStaff
from .services import vincular_pedidos_de_sesion


@receiver(user_logged_in)
def al_iniciar_sesion(
    sender: Any,
    request: HttpRequest,
    user: User,
    **kwargs: Any,
) -> None:
    """Se dispara en CADA inicio de sesión (login clásico o auto-login del
    registro) y reclama los pedidos hechos como invitado en esta sesión."""
    vincular_pedidos_de_sesion(request, user)


@receiver(post_save, sender=User)
def perfil_para_super_cuentas(
    sender: Any,
    instance: User,
    **kwargs: Any,
) -> None:
    """Toda super cuenta (createsuperuser, seed, admin) recibe automáticamente
    un PerfilStaff de dueño ya aprobado, así aparece en "Cuentas de personal"
    sin pasos manuales."""
    if not instance.is_superuser:
        return
    PerfilStaff.objects.get_or_create(
        usuario=instance,
        defaults={
            'rol': PerfilStaff.Rol.DUENIO,
            'estado': PerfilStaff.Estado.APROBADO,
        },
    )
