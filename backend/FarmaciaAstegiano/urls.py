"""
URL configuration for FarmaciaAstegiano project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from core.views import InicioView
from aboutUs.views import sobre_nosotros

urlpatterns = [
    path('admin/', admin.site.urls),
    #DEJAMOS LAS COMILLAS VACIAS PARA QUE SEA LA PAGINA PRINCIPAL
    path('', InicioView.as_view(), name='inicio'),
    path('sobre-nosotros/', sobre_nosotros, name='sobre_nosotros'),
    # include suma las URLs de catalogo debajo de /tienda/
    path('tienda/', include('catalogo.urls')),
    path('carrito/', include('carrito.urls')),
    path('pedidos/', include('pedidos.urls')),
    path('pagos/', include('pagos.urls')),
    # registro + login/logout/reseteo de contraseña (vistas built-in de Django)
    path('cuentas/', include('cuentas.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
