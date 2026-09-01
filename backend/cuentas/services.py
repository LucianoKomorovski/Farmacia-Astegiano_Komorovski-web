from django.contrib.auth.models import User
from django.http import HttpRequest

from pedidos.models import Pedido
from pedidos.views import SESSION_PEDIDOS_KEY


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