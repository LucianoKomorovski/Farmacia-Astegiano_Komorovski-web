from django.db import models

class Sucursal(models.Model):
  nombre = models.CharField(max_length=100)
  descripcion = models.TextField(blank=True, null=True)
  imagen_fachada = models.ImageField(upload_to='sucursales/', blank=True, null=True)

  direccion = models.CharField(max_length=200)
  link_google_maps = models.URLField(max_length=500)
  telefono_fijo = models.CharField(max_length=15, blank=True, null=True)
  numero_whatsapp = models.CharField(max_length=15, blank=True, null=True, help_text='ingrese numero de país +54 9')

  horarios_atencion = models.TextField(blank=True, null=True)
  esta_de_turno = models.BooleanField(default=False)

  def __str__(self) -> str:  # cómo mostrar el objeto en el admin
    return str(self.nombre)





