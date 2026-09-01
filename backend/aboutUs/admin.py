from django.contrib import admin

from .models import SobreNosotros

# Registramos el modelo para poder cargar textos e imágenes
# de la página "Sobre Nosotros" desde el admin.
admin.site.register(SobreNosotros)
