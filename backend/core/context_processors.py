from datetime import time

from django.utils import timezone

from sucursales.models import Sucursal

# Franja horaria en la que se muestra el letrero de turno.
# Si el inicio es mayor que el fin, la franja cruza la medianoche
# (ej: de 20:00 a 08:30 del día siguiente).
HORA_INICIO_BANNER = time(10, 0)
HORA_FIN_BANNER = time(16, 30)


def banner_turno(request):
    """Hace disponible en todos los templates la sucursal de turno,
    solo dentro de la franja horaria configurada."""
    ahora = timezone.localtime().time()

    if HORA_INICIO_BANNER <= HORA_FIN_BANNER:
        dentro_de_franja = HORA_INICIO_BANNER <= ahora <= HORA_FIN_BANNER
    else:  # la franja cruza la medianoche
        dentro_de_franja = ahora >= HORA_INICIO_BANNER or ahora <= HORA_FIN_BANNER

    if not dentro_de_franja:
        return {'sucursal_de_turno': None}

    return {'sucursal_de_turno': Sucursal.objects.filter(esta_de_turno=True).first()}


# Cuenta de Instagram que se muestra en el footer.
INSTAGRAM_URL = 'https://www.instagram.com/farmaciaastegiano.komorovski/'


def datos_footer(request):
    """Hace disponibles en todos los templates las sucursales (para los
    links de WhatsApp y Google Maps del footer) y la cuenta de Instagram."""
    return {
        'sucursales_footer': Sucursal.objects.all(),
        'instagram_url': INSTAGRAM_URL,
    }
