from django.shortcuts import render
from sucursales.models import Sucursal
from servicios.models import Servicio

def inicio(request):
  #Traemos todas las sucursales y servicios de la base de datos 
  sucursales = Sucursal.objects.all()
  servicios = Servicio.objects.all()

  # Empaquetamos los datos en un diccionario llamado CONTEXTO:
  context = {
    'sucursales': sucursales,
    'servicios': servicios,
  }
  #Le decimos a django que renderice el html enviandoles los daots:
  return render(request,'core/index.html', context)
