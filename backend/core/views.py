from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from sucursales.models import Sucursal
from servicios.models import Servicio
from turnos.models import Turno

def inicio(request):
  #Traemos todas las sucursales y servicios de la base de datos 
  sucursales = Sucursal.objects.all()
  servicios = Servicio.objects.all()

  # Turnos de los próximos 7 días (hoy incluido) para el widget.
  # Armamos una entrada por día aunque falte cargar alguno en el calendario.
  hoy = timezone.localdate()
  turnos_cargados = {
    turno.fecha: turno
    for turno in Turno.objects.select_related('farmacia').filter(
      fecha__range=(hoy, hoy + timedelta(days=6))
    )
  }
  proximos_turnos = []
  for i in range(7):
    dia = hoy + timedelta(days=i)
    proximos_turnos.append({
      'fecha': dia,
      'turno': turnos_cargados.get(dia),
      'es_hoy': i == 0,
    })

  # Si hoy le toca a una de nuestras sucursales, guardamos su id
  # para mostrar el badge "¡De Turno Hoy!" en su tarjeta.
  turno_hoy = turnos_cargados.get(hoy)
  id_sucursal_de_turno = turno_hoy.farmacia.sucursal_id if turno_hoy else None

  # Empaquetamos los datos en un diccionario llamado CONTEXTO:
  context = {
    'sucursales': sucursales,
    'servicios': servicios,
    'proximos_turnos': proximos_turnos,
    'id_sucursal_de_turno': id_sucursal_de_turno,
  }
  #Le decimos a django que renderice el html enviandoles los datos:
  return render(request,'core/index.html', context)
