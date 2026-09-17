from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from pedidos.models import Pedido
from pedidos.views import SESSION_PEDIDOS_KEY

from .models import PerfilStaff
from .services import (
    GRUPO_EMPLEADAS,
    CuentaError,
    aprobar_solicitud,
    asegurar_grupo_empleadas,
    rechazar_solicitud,
)

CLAVE = 'farmacia-2026-segura'


def crear_pedido(numero: str, usuario: User | None = None) -> Pedido:
    """Pedido mínimo para los tests (sin pasar por carrito ni checkout)."""
    return Pedido.objects.create(
        numero=numero,
        usuario=usuario,
        nombre_cliente='Invitado',
        email='invitado@test.com',
        telefono='3510000000',
        estado=Pedido.Estado.PENDIENTE_PAGO,
        modo=Pedido.Modo.INMEDIATO,
        modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
        medio_pago=Pedido.MedioPago.MERCADOPAGO,
        subtotal=Decimal('100'),
        total=Decimal('100'),
    )


class RegistroTests(TestCase):
    def test_registro_crea_usuario_y_deja_logueado(self):
        resp = self.client.post(reverse('registro'), {
            'username': 'cliente',
            'email': 'Cliente@Test.com',
            'password1': CLAVE,
            'password2': CLAVE,
        })
        self.assertRedirects(resp, reverse('catalogo_lista'))

        user = User.objects.get(username='cliente')
        self.assertEqual(user.email, 'cliente@test.com')  # normalizado a minúsculas
        # _auth_user_id en la sesión = quedó logueado automáticamente.
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_email_duplicado_es_rechazado(self):
        User.objects.create_user('otro', 'cliente@test.com', CLAVE)
        resp = self.client.post(reverse('registro'), {
            'username': 'cliente',
            'email': 'cliente@test.com',
            'password1': CLAVE,
            'password2': CLAVE,
        })
        # 200 = vuelve a mostrar el formulario con el error, sin crear nada.
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ya existe una cuenta con ese email')
        self.assertFalse(User.objects.filter(username='cliente').exists())

    def test_usuario_logueado_no_ve_el_registro(self):
        User.objects.create_user('cliente', 'c@test.com', CLAVE)
        self.client.login(username='cliente', password=CLAVE)
        resp = self.client.get(reverse('registro'))
        self.assertRedirects(resp, reverse('catalogo_lista'))

    def test_registro_respeta_next(self):
        destino = reverse('pedido_mis_pedidos')
        resp = self.client.post(reverse('registro'), {
            'username': 'cliente',
            'email': 'cliente@test.com',
            'password1': CLAVE,
            'password2': CLAVE,
            'next': destino,
        })
        self.assertRedirects(resp, destino)


class VinculacionPedidosTests(TestCase):
    """Al iniciar sesión, los pedidos hechos como invitado pasan a la cuenta."""

    def test_login_vincula_pedidos_de_la_sesion(self):
        pedido = crear_pedido('FA-2026-000101')
        user = User.objects.create_user('cliente', 'c@test.com', CLAVE)

        # Simula que este navegador creó el pedido como invitado.
        session = self.client.session
        session[SESSION_PEDIDOS_KEY] = [pedido.numero]
        session.save()

        self.client.post(reverse('login'), {'username': 'cliente', 'password': CLAVE})

        pedido.refresh_from_db()
        self.assertEqual(pedido.usuario, user)

    def test_no_reasigna_pedidos_de_otra_cuenta(self):
        otro = User.objects.create_user('otro', 'o@test.com', CLAVE)
        pedido = crear_pedido('FA-2026-000102', usuario=otro)
        User.objects.create_user('cliente', 'c@test.com', CLAVE)

        session = self.client.session
        session[SESSION_PEDIDOS_KEY] = [pedido.numero]
        session.save()

        self.client.post(reverse('login'), {'username': 'cliente', 'password': CLAVE})

        pedido.refresh_from_db()
        self.assertEqual(pedido.usuario, otro)  # sigue siendo del dueño original

    def test_registro_tambien_vincula(self):
        pedido = crear_pedido('FA-2026-000103')
        session = self.client.session
        session[SESSION_PEDIDOS_KEY] = [pedido.numero]
        session.save()

        self.client.post(reverse('registro'), {
            'username': 'cliente',
            'email': 'cliente@test.com',
            'password1': CLAVE,
            'password2': CLAVE,
        })

        pedido.refresh_from_db()
        self.assertIsNotNone(pedido.usuario)
        assert pedido.usuario is not None
        self.assertEqual(pedido.usuario.username, 'cliente')


class MisPedidosTests(TestCase):
    def test_anonimo_redirige_al_login(self):
        url = reverse('pedido_mis_pedidos')
        resp = self.client.get(url)
        self.assertRedirects(resp, f"{reverse('login')}?next={url}")

    def test_logueado_ve_solo_sus_pedidos(self):
        user = User.objects.create_user('cliente', 'c@test.com', CLAVE)
        mio = crear_pedido('FA-2026-000104', usuario=user)
        ajeno = crear_pedido('FA-2026-000105')

        self.client.force_login(user)
        resp = self.client.get(reverse('pedido_mis_pedidos'))

        self.assertContains(resp, mio.numero)
        self.assertNotContains(resp, ajeno.numero)


# ---------------------------------------------------------------------------
# Personal: solicitud, aprobación y acceso al panel
# ---------------------------------------------------------------------------


def crear_super(username: str = 'duenio') -> User:
    return User.objects.create_superuser(username, f'{username}@test.com', CLAVE)


DATOS_SOLICITUD = {
    'username': 'empleada',
    'first_name': 'Ana',
    'last_name': 'Pérez',
    'email': 'ana@test.com',
    'telefono': '3471555555',
    'mensaje': 'Soy la nueva de la tarde.',
    'password1': CLAVE,
    'password2': CLAVE,
}


class SolicitudStaffTests(TestCase):
    def test_solicitud_crea_usuario_pendiente_sin_staff_y_sin_login(self):
        crear_super()  # para que haya a quién avisar por email
        resp = self.client.post(reverse('solicitud_staff'), DATOS_SOLICITUD)
        self.assertRedirects(resp, reverse('solicitud_enviada'))

        user = User.objects.get(username='empleada')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.first_name, 'Ana')

        perfil = user.perfil_staff
        self.assertEqual(perfil.estado, PerfilStaff.Estado.PENDIENTE)
        self.assertEqual(perfil.rol, PerfilStaff.Rol.EMPLEADA)
        self.assertEqual(perfil.mensaje, 'Soy la nueva de la tarde.')

        # NO queda logueada (a diferencia del registro de clientes).
        self.assertNotIn('_auth_user_id', self.client.session)
        # Aviso a las super cuentas.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('duenio@test.com', mail.outbox[0].to)

    def test_email_duplicado_no_crea_solicitud(self):
        User.objects.create_user('otro', 'ana@test.com', CLAVE)
        resp = self.client.post(reverse('solicitud_staff'), DATOS_SOLICITUD)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='empleada').exists())

    def test_staff_logueado_va_al_panel(self):
        user = User.objects.create_user('emp', 'e@test.com', CLAVE, is_staff=True)
        self.client.force_login(user)
        resp = self.client.get(reverse('solicitud_staff'))
        self.assertRedirects(resp, reverse('admin:index'), fetch_redirect_response=False)


class AprobacionTests(TestCase):
    def setUp(self):
        self.duenio = crear_super()
        self.user = User.objects.create_user('empleada', 'ana@test.com', CLAVE)
        self.perfil = PerfilStaff.objects.create(usuario=self.user)

    def test_superuser_recibe_perfil_de_duenio_automaticamente(self):
        perfil = self.duenio.perfil_staff
        self.assertEqual(perfil.rol, PerfilStaff.Rol.DUENIO)
        self.assertEqual(perfil.estado, PerfilStaff.Estado.APROBADO)

    def test_aprobar_da_staff_grupo_y_registra_quien(self):
        aprobar_solicitud(self.perfil, self.duenio)
        self.user.refresh_from_db()
        self.perfil.refresh_from_db()

        self.assertTrue(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertTrue(self.user.groups.filter(name=GRUPO_EMPLEADAS).exists())
        self.assertEqual(self.perfil.estado, PerfilStaff.Estado.APROBADO)
        self.assertEqual(self.perfil.aprobado_por, self.duenio)
        self.assertIsNotNone(self.perfil.aprobado_en)
        # Email de aviso a la empleada.
        self.assertTrue(any('ana@test.com' in m.to for m in mail.outbox))

    def test_aprobar_rol_duenio_lo_hace_superuser(self):
        self.perfil.rol = PerfilStaff.Rol.DUENIO
        self.perfil.save()
        aprobar_solicitud(self.perfil, self.duenio)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_superuser)

    def test_solo_super_cuenta_puede_aprobar(self):
        otro_staff = User.objects.create_user('staff2', 's@test.com', CLAVE, is_staff=True)
        with self.assertRaises(CuentaError):
            aprobar_solicitud(self.perfil, otro_staff)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)

    def test_rechazar_quita_acceso(self):
        aprobar_solicitud(self.perfil, self.duenio)
        rechazar_solicitud(self.perfil, self.duenio)
        self.user.refresh_from_db()
        self.perfil.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.groups.exists())
        self.assertEqual(self.perfil.estado, PerfilStaff.Estado.RECHAZADO)

    def test_no_se_puede_rechazar_una_super_cuenta(self):
        with self.assertRaises(CuentaError):
            rechazar_solicitud(self.duenio.perfil_staff, self.duenio)

    def test_accion_admin_aprobar(self):
        self.client.force_login(self.duenio)
        url = reverse('admin:cuentas_perfilstaff_changelist')
        resp = self.client.post(url, {
            'action': 'accion_aprobar',
            '_selected_action': [self.perfil.pk],
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_staff)

    def test_grupo_empleadas_tiene_permisos_operativos_y_no_de_pagos(self):
        grupo = asegurar_grupo_empleadas()
        codigos = set(grupo.permissions.values_list('codename', flat=True))
        self.assertIn('change_pedido', codigos)
        self.assertIn('change_producto', codigos)
        self.assertIn('change_stockweb', codigos)
        self.assertNotIn('delete_pedido', codigos)
        self.assertNotIn('view_pago', codigos)
        self.assertNotIn('view_user', codigos)


class LoginPanelTests(TestCase):
    """El login del panel explica por qué no puede entrar el personal."""

    def setUp(self):
        self.user = User.objects.create_user('empleada', 'ana@test.com', CLAVE)
        self.perfil = PerfilStaff.objects.create(usuario=self.user)

    def _login(self):
        return self.client.post(reverse('admin:login'), {
            'username': 'empleada',
            'password': CLAVE,
            'next': reverse('admin:index'),
        })

    def test_pendiente_ve_mensaje_claro(self):
        resp = self._login()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'pendiente de aprobación')

    def test_rechazada_ve_mensaje_claro(self):
        self.perfil.estado = PerfilStaff.Estado.RECHAZADO
        self.perfil.save()
        resp = self._login()
        self.assertContains(resp, 'fue rechazada')

    def test_aprobada_entra_al_panel(self):
        aprobar_solicitud(self.perfil, crear_super())
        resp = self._login()
        self.assertRedirects(resp, reverse('admin:index'), fetch_redirect_response=False)

    def test_login_muestra_link_para_solicitar_acceso(self):
        resp = self.client.get(reverse('admin:login'))
        self.assertContains(resp, reverse('solicitud_staff'))


class PermisosPanelTests(TestCase):
    """Qué ve una empleada aprobada vs. una super cuenta."""

    def setUp(self):
        self.duenio = crear_super()
        self.empleada = User.objects.create_user('empleada', 'ana@test.com', CLAVE)
        aprobar_solicitud(PerfilStaff.objects.create(usuario=self.empleada), self.duenio)

    def test_empleada_no_ve_pagos_ni_usuarios_ni_cuentas(self):
        self.client.force_login(self.empleada)
        resp = self.client.get(reverse('admin:index'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('admin:pedidos_pedido_changelist'))
        self.assertNotContains(resp, reverse('admin:pagos_pago_changelist'))
        self.assertNotContains(resp, reverse('admin:auth_user_changelist'))
        self.assertNotContains(resp, reverse('admin:cuentas_perfilstaff_changelist'))

        self.assertEqual(self.client.get(reverse('admin:pagos_pago_changelist')).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin:auth_user_changelist')).status_code, 403)

    def test_super_ve_todo(self):
        self.client.force_login(self.duenio)
        resp = self.client.get(reverse('admin:index'))
        self.assertContains(resp, reverse('admin:pagos_pago_changelist'))
        self.assertContains(resp, reverse('admin:auth_user_changelist'))
        self.assertContains(resp, reverse('admin:cuentas_perfilstaff_changelist'))

    def test_empleada_no_puede_borrar_pedidos(self):
        pedido = crear_pedido('FA-2026-000200')
        self.client.force_login(self.empleada)
        resp = self.client.get(reverse('admin:pedidos_pedido_delete', args=[pedido.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_no_se_puede_borrar_una_super_cuenta(self):
        otro = crear_super('otro_duenio')
        self.client.force_login(self.duenio)
        resp = self.client.get(reverse('admin:auth_user_delete', args=[otro.pk]))
        self.assertEqual(resp.status_code, 403)
