from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import CreateView, TemplateView

from .forms import RegistroForm, SolicitudStaffForm
from .services import notificar_nueva_solicitud


class RegistroView(CreateView):
    """Alta de cuenta de cliente. Al crearla, inicia sesión automáticamente."""

    form_class = RegistroForm
    template_name = 'cuentas/registro.html'
    success_url = reverse_lazy('catalogo_lista')

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Alguien ya logueado no tiene nada que hacer en el registro.
        if request.user.is_authenticated:
            return redirect('catalogo_lista')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form: RegistroForm) -> HttpResponse:
        respuesta = super().form_valid(form)  # guarda el User en self.object
        # login() abre la sesión y dispara la señal user_logged_in,
        # que vincula los pedidos hechos como invitado (cuentas/signals.py).
        login(self.request, self.object)
        messages.success(self.request, '¡Cuenta creada! Ya iniciaste sesión.')
        return respuesta

    def get_success_url(self) -> str:
        # Si venían de una página protegida (?next=...), volver ahí.
        # url_has_allowed_host_and_scheme evita redirecciones a sitios ajenos.
        siguiente = self.request.POST.get('next') or self.request.GET.get('next')
        if siguiente and url_has_allowed_host_and_scheme(
            siguiente,
            allowed_hosts={self.request.get_host()},
        ):
            return siguiente
        return str(self.success_url)


class SolicitudStaffView(CreateView):
    """Registro de PERSONAL: crea la cuenta pero NO inicia sesión.

    La cuenta queda pendiente hasta que una super cuenta la apruebe desde el
    panel (Cuentas → Cuentas de personal). Mientras tanto, si intenta entrar
    al panel ve un mensaje explicando que está pendiente.
    """

    form_class = SolicitudStaffForm
    template_name = 'cuentas/solicitud_staff.html'
    success_url = reverse_lazy('solicitud_enviada')

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.user.is_authenticated and request.user.is_staff:
            # Ya tiene acceso al panel: lo mandamos directo.
            return redirect('admin:index')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form: SolicitudStaffForm) -> HttpResponse:
        # atomic: si falla la creación del perfil, tampoco queda el User a medias.
        with transaction.atomic():
            respuesta = super().form_valid(form)
            perfil = form.crear_perfil(self.object)
        notificar_nueva_solicitud(perfil)
        return respuesta


class SolicitudEnviadaView(TemplateView):
    template_name = 'cuentas/solicitud_enviada.html'
