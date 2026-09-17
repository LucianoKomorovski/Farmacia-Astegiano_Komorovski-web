from django.urls import include, path

from .views import RegistroView, SolicitudEnviadaView, SolicitudStaffView

urlpatterns = [
    path('registro/', RegistroView.as_view(), name='registro'),
    # Personal de la farmacia: solicitud de acceso al panel (requiere aprobación).
    path('personal/solicitar/', SolicitudStaffView.as_view(), name='solicitud_staff'),
    path('personal/enviada/', SolicitudEnviadaView.as_view(), name='solicitud_enviada'),
    # Vistas built-in de Django bajo /cuentas/:
    #   login/  logout/  password_change/  password_reset/  (y sus "done")
    # Los nombres de URL son: login, logout, password_change, password_reset...
    path('', include('django.contrib.auth.urls')),
]
