"""Crea o actualiza el grupo "Empleadas" y los perfiles de las super cuentas.

Uso (desde backend, con el venv activo):
    python manage.py configurar_roles

Correrlo después de cada `migrate` si se agregan modelos nuevos que el
personal deba poder operar (los permisos se crean con las migraciones), y
después de crear super cuentas con `createsuperuser` en una base vieja.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from cuentas.services import asegurar_grupo_empleadas, asegurar_perfiles_super_cuentas


class Command(BaseCommand):
    help = 'Crea/actualiza el grupo Empleadas y los perfiles de las super cuentas'

    def handle(self, *args: object, **options: object) -> None:
        grupo = asegurar_grupo_empleadas()
        cantidad = grupo.permissions.count()
        self.stdout.write(
            self.style.SUCCESS(f'Grupo "{grupo.name}" listo con {cantidad} permisos.')
        )
        creados = asegurar_perfiles_super_cuentas()
        self.stdout.write(f'Perfiles de super cuenta creados: {creados}.')
