from django.db import models

class SobreNosotros(models.Model):
  titulo = models.CharField(max_length=100)
  descripcion = models.TextField(help_text='Ingrese una descripción breve de la empresa')
  imagen = models.ImageField(upload_to='aboutUs/', help_text='Suba una imagen de la empresa')

  def __str__(self) -> str:
    return str(self.titulo)
