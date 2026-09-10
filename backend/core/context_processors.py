"""Context processors: variables disponibles en TODOS los templates.

Cada función recibe el request y devuelve un dict que Django mezcla en el
contexto de cualquier template que se renderice (útil para header y footer).
Se registran en settings.TEMPLATES → OPTIONS → context_processors.
"""

from datetime import time
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from carrito.services import obtener_carrito
from catalogo.models import Categoria
from sucursales.models import Sucursal
from turnos.models import Turno

# Franja horaria en la que se muestra el letrero de turno.
# Si el inicio es mayor que el fin, la franja cruza la medianoche
# (ej: de 20:00 a 08:30 del día siguiente).
HORA_INICIO_BANNER = time(19, 50)
HORA_FIN_BANNER = time(8, 30)


def banner_turno(request: HttpRequest) -> dict[str, Any]:
    """Hace disponible en todos los templates el turno de hoy (según el
    calendario cargado en el admin), solo dentro de la franja horaria."""
    ahora = timezone.localtime().time()

    if HORA_INICIO_BANNER <= HORA_FIN_BANNER:
        dentro_de_franja = HORA_INICIO_BANNER <= ahora <= HORA_FIN_BANNER
    else:  # la franja cruza la medianoche
        dentro_de_franja = ahora >= HORA_INICIO_BANNER or ahora <= HORA_FIN_BANNER

    if not dentro_de_franja:
        return {'turno_hoy': None}

    turno = (
        Turno.objects.select_related('farmacia')
        .filter(fecha=timezone.localdate())
        .first()
    )
    return {'turno_hoy': turno}


# Cuenta de Instagram que se muestra en el footer.
INSTAGRAM_URL = 'https://www.instagram.com/farmaciaastegiano.komorovski/'


def datos_footer(request: HttpRequest) -> dict[str, Any]:
    """Sucursales (WhatsApp, Maps, horarios) e Instagram para el footer.

    También resuelve el WhatsApp del botón flotante: primero el configurado
    en settings.WHATSAPP_TIENDA; si está vacío, el de la primera sucursal.
    """
    sucursales = list(Sucursal.objects.all())
    whatsapp_flotante = settings.WHATSAPP_TIENDA or next(
        (s.numero_whatsapp for s in sucursales if s.numero_whatsapp),
        '',
    )
    return {
        'sucursales_footer': sucursales,
        'instagram_url': INSTAGRAM_URL,
        'whatsapp_flotante': whatsapp_flotante,
    }


def navegacion_tienda(request: HttpRequest) -> dict[str, Any]:
    """Categorías activas con al menos un producto visible, para la barra
    de navegación del header (fila 2) y el menú mobile."""
    categorias = (
        Categoria.objects.filter(
            activa=True,
            productos__activo=True,
            productos__requiere_receta=False,
        )
        .distinct()
    )
    return {'categorias_nav': categorias}


def carrito_resumen(request: HttpRequest) -> dict[str, Any]:
    """Cantidad de unidades en el carrito para el badge del header.

    crear=False: si el visitante nunca agregó nada, NO creamos un carrito
    (evita llenar la base con carritos vacíos por cada visita).
    """
    # El admin y algunas vistas de error no pasan por el middleware de sesión
    # completo; con getattr evitamos romper si falta request.user.
    if not hasattr(request, 'session'):
        return {'carrito_cantidad': 0}

    carrito = obtener_carrito(request, crear=False)
    cantidad = carrito.cantidad_items if carrito is not None else 0
    return {'carrito_cantidad': cantidad}
