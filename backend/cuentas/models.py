"""Modelos de la app cuentas.

Los CLIENTES usan el User estándar de Django sin nada extra.
El PERSONAL de la farmacia (empleadas y dueños) tiene además un PerfilStaff
que guarda el rol, la sucursal y, sobre todo, el estado de aprobación:
una empleada recién registrada queda PENDIENTE hasta que una super cuenta
(dueño / is_superuser) la apruebe desde el panel.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class PerfilStaff(models.Model):
    """Datos extra y estado de aprobación de una cuenta de personal."""

    class Rol(models.TextChoices):
        EMPLEADA = 'empleada', 'Empleada / empleado'
        DUENIO = 'duenio', 'Dueño (super cuenta)'

    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente de aprobación'
        APROBADO = 'aprobado', 'Aprobado'
        RECHAZADO = 'rechazado', 'Rechazado'

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil_staff',
    )
    usuario_id: int  # pyright: ignore[reportUninitializedInstanceVariable]

    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.EMPLEADA)
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    sucursal = models.ForeignKey(
        'sucursales.Sucursal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='personal',
        help_text='Sucursal donde trabaja habitualmente (informativo).',
    )
    sucursal_id: int | None  # pyright: ignore[reportUninitializedInstanceVariable]

    telefono = models.CharField(max_length=20, blank=True)
    mensaje = models.CharField(
        max_length=300,
        blank=True,
        help_text='Texto que dejó la persona al solicitar acceso.',
    )

    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='perfiles_aprobados',
    )
    aprobado_por_id: int | None  # pyright: ignore[reportUninitializedInstanceVariable]
    aprobado_en = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'cuenta de personal'
        verbose_name_plural = 'cuentas de personal'

    def __str__(self) -> str:
        return f'{self.usuario} ({self.get_estado_display()})'

    @property
    def esta_pendiente(self) -> bool:
        return self.estado == self.Estado.PENDIENTE

    @property
    def esta_aprobado(self) -> bool:
        return self.estado == self.Estado.APROBADO
