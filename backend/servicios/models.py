from django.db import models
from sucursales.models import Sucursal

class Servicio(models.Model):
  titulo = models.CharField(max_length=100)
  descripcion = models.TextField(help_text='Ingrese una descripción breve del servicio')
  # GUARDAMOS EL NOMBRE DE UNA CLASE CSS DE UN ICONO (EJ. BOOTSTRAP ICONS)
  icono = models.CharField(max_length=100, help_text='Ingrese el nombre de la clase CSS del icono')

  # RELACION: UNA SUCURSAL PUEDE TENER MUCHOS SERVICIOS, ACA ESTUVO FLOR BRAVI, UN SERVICIO PUEDE ESTAR EN MUCHAS SUCURSALES: 
  sucursales_disponibles = models.ManyToManyField(Sucursal, related_name='servicios')

  def __str__(self) -> str: # ESTE METODO LE DICE A DJANGO COMO MOSTRAR EL OBJETO EN EL ADMIN
    return str(self.titulo)

# Create your models here.
