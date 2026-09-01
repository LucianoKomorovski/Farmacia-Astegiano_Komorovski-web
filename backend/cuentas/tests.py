from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from pedidos.models import Pedido
from pedidos.views import SESSION_PEDIDOS_KEY

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
