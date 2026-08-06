from datetime import time

from django.utils import timezone

from sucursales.models import Sucursal
from turnos.models import Turno

# Franja horaria en la que se muestra el letrero de turno.
# Si el inicio es mayor que el fin, la franja cruza la medianoche
# (ej: de 20:00 a 08:30 del día siguiente).
HORA_INICIO_BANNER = time(19, 50)
HORA_FIN_BANNER = time(8, 30)


def banner_turno(request):
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


def datos_footer(request):
    """Hace disponibles en todos los templates las sucursales (para los
    links de WhatsApp y Google Maps del footer) y la cuenta de Instagram."""
    return {
        'sucursales_footer': Sucursal.objects.all(),
        'instagram_url': INSTAGRAM_URL,
    }
