"""Checks acotados al endurecimiento de seed y SECRET_KEY."""

import inspect
import os
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from FarmaciaAstegiano.settings import _resolve_secret_key
from core.management.commands.seed_datos import Command as SeedDatosCommand

User = get_user_model()


class SecretKeyTests(TestCase):
    """Django no debe arrancar con una SECRET_KEY vacía o de ejemplo."""

    def test_acepta_una_clave_real(self) -> None:
        self.assertEqual(
            _resolve_secret_key('dev-only-generated-key-please-rotate'),
            'dev-only-generated-key-please-rotate',
        )

    def test_rechaza_vacia_o_ausente(self) -> None:
        for raw in (None, '', '   '):
            with self.subTest(raw=raw), self.assertRaises(ImproperlyConfigured):
                _resolve_secret_key(raw)

    def test_rechaza_placeholders_obvios(self) -> None:
        for raw in (
            'cambia-esto-por-una-clave-secreta',
            'changeme',
            'SECRET',
            '<clave-larga-aleatoria>',
        ):
            with self.subTest(raw=raw), self.assertRaises(ImproperlyConfigured):
                _resolve_secret_key(raw)


class SeedStaffTests(TestCase):
    """seed_datos no debe inventar una contraseña conocida de staff."""

    def test_codigo_sin_password_hardcodeada(self) -> None:
        command_path = Path(inspect.getfile(SeedDatosCommand))
        texto = command_path.read_text(encoding='utf-8')
        self.assertNotIn('staff1234', texto)

    @override_settings(DEBUG=False)
    def test_no_crea_staff_si_debug_es_false(self) -> None:
        cmd = SeedDatosCommand(stdout=StringIO())
        cmd._seed_staff(username='staff', password='una-clave-local-de-prueba')
        self.assertFalse(User.objects.filter(username='staff').exists())

    @override_settings(DEBUG=True)
    def test_no_crea_staff_sin_password(self) -> None:
        cmd = SeedDatosCommand(stdout=StringIO())
        with (
            patch.dict(os.environ, {'SEED_STAFF_PASSWORD': ''}),
            patch('sys.stdin.isatty', return_value=False),
        ):
            cmd._seed_staff(username='staff', password='')
        self.assertFalse(User.objects.filter(username='staff').exists())

    @override_settings(DEBUG=True)
    def test_crea_staff_con_password_de_argumento(self) -> None:
        cmd = SeedDatosCommand(stdout=StringIO())
        cmd._seed_staff(username='staff', password='una-clave-local-de-prueba')
        user = User.objects.get(username='staff')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password('una-clave-local-de-prueba'))

    @override_settings(DEBUG=True)
    def test_crea_staff_con_password_de_entorno(self) -> None:
        cmd = SeedDatosCommand(stdout=StringIO())
        with patch.dict(os.environ, {'SEED_STAFF_PASSWORD': 'clave-desde-env-local'}):
            cmd._seed_staff(username='staff', password='')
        user = User.objects.get(username='staff')
        self.assertTrue(user.check_password('clave-desde-env-local'))

    @override_settings(DEBUG=True)
    def test_no_pisa_password_si_staff_ya_existe(self) -> None:
        existente = User.objects.create_user(
            'staff', 'staff@farmacia.local', 'password-original-local',
            is_staff=True, is_superuser=True,
        )
        cmd = SeedDatosCommand(stdout=StringIO())
        cmd._seed_staff(username='staff', password='otra-clave-nueva-local')
        existente.refresh_from_db()
        self.assertTrue(existente.check_password('password-original-local'))
