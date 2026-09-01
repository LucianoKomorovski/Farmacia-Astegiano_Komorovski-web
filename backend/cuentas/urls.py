from django.urls import include, path

from .views import RegistroView

urlpatterns = [
    path('registro/', RegistroView.as_view(), name='registro'),
    # Vistas built-in de Django bajo /cuentas/:
    #   login/  logout/  password_change/  password_reset/  (y sus "done")
    # Los nombres de URL son: login, logout, password_change, password_reset...
    path('', include('django.contrib.auth.urls')),
]