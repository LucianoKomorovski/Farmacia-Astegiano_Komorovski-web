from typing import Any

from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.http import HttpRequest

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