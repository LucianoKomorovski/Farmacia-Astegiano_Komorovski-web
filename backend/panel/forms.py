"""Formulario de login del panel con mensajes claros para el personal."""

from __future__ import annotations

from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm

from cuentas.models import PerfilStaff


class PanelLoginForm(AdminAuthenticationForm):
    """Igual al login del admin, pero si la persona tiene una solicitud
    pendiente o rechazada se lo decimos en vez del genérico
    "usuario o contraseña incorrectos" (que confunde a las empleadas)."""

    error_messages = {
        **AdminAuthenticationForm.error_messages,
        'invalid_login': (
            'Usuario o contraseña incorrectos, o la cuenta no tiene acceso al panel. '
            'Recordá que distingue mayúsculas y minúsculas.'
        ),
        'pendiente': (
            'Tu solicitud de acceso todavía está pendiente de aprobación. '
            'Cuando un dueño la apruebe vas a recibir un email.'
        ),
        'rechazado': (
            'Tu solicitud de acceso al panel fue rechazada. '
            'Si creés que es un error, hablá con los dueños de la farmacia.'
        ),
    }

    def confirm_login_allowed(self, user) -> None:
        # La clase padre exige is_active + is_staff. Antes de eso miramos si
        # hay un perfil de personal para explicar mejor el motivo del rechazo.
        perfil = PerfilStaff.objects.filter(usuario=user).first()
        if perfil is not None and not user.is_staff:
            if perfil.estado == PerfilStaff.Estado.PENDIENTE:
                raise forms.ValidationError(
                    self.error_messages['pendiente'],
                    code='pendiente',
                )
            if perfil.estado == PerfilStaff.Estado.RECHAZADO:
                raise forms.ValidationError(
                    self.error_messages['rechazado'],
                    code='rechazado',
                )
        super().confirm_login_allowed(user)
