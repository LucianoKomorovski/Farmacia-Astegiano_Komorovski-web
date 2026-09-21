from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Categoria, Producto
from inventario.models import ReservaStock, StockWeb
from pedidos.admin import PedidoAdmin
from pedidos.forms import CheckoutForm
from pedidos.models import FranjaEnvio, Pedido
from pedidos.services import (
    PedidoError,
    cancelar_pedido,
    confirmar_pedido,
    confirmar_transferencia_staff,
    crear_pedido_desde_carrito,
)
from carrito.models import Carrito, LineaCarrito
from sucursales.models import Sucursal


class ReservaStockTests(TestCase):
    def setUp(self):
        cat = Categoria.objects.create(nombre='Test', slug='test', activa=True)
        self.producto = Producto.objects.create(
            categoria=cat,
            nombre='Jabón',
            slug='jabon',
            sku='JAB-001',
            descripcion='',
            tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('100.00'),
            activo=True,
        )
        StockWeb.objects.create(producto=self.producto, cantidad=10)
        self.carrito = Carrito.objects.create(session_key='test-session')
        self.carrito.modo = Carrito.Modo.INMEDIATO
        self.carrito.save()
        LineaCarrito.objects.create(
            carrito=self.carrito,
            producto=self.producto,
            cantidad=3,
            precio_unitario=Decimal('100.00'),
        )

    def test_crear_pedido_reserva_stock_sin_descontar(self):
        request = type('R', (), {'user': type('U', (), {'is_authenticated': False})()})()
        datos = {
            'nombre_cliente': 'Juan',
            'email': 'juan@test.com',
            'telefono': '3510000000',
            'modalidad_entrega': Pedido.ModalidadEntrega.A_COORDINAR,
            'medio_pago': Pedido.MedioPago.MERCADOPAGO,
            'notas': '',
        }
        pedido = crear_pedido_desde_carrito(request, self.carrito, datos)

        stock = StockWeb.objects.get(producto=self.producto)
        self.assertEqual(stock.cantidad, 10)
        self.assertEqual(
            ReservaStock.objects.filter(pedido=pedido, estado=ReservaStock.Estado.ACTIVA).count(),
            1,
        )
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE_PAGO)

    def test_confirmar_pedido_descuenta_stock(self):
        request = type('R', (), {'user': type('U', (), {'is_authenticated': False})()})()
        datos = {
            'nombre_cliente': 'Juan',
            'email': 'juan@test.com',
            'telefono': '3510000000',
            'modalidad_entrega': Pedido.ModalidadEntrega.A_COORDINAR,
            'medio_pago': Pedido.MedioPago.MERCADOPAGO,
            'notas': '',
        }
        pedido = crear_pedido_desde_carrito(request, self.carrito, datos)
        confirmar_pedido(pedido)

        stock = StockWeb.objects.get(producto=self.producto)
        self.assertEqual(stock.cantidad, 7)
        self.assertEqual(pedido.estado, Pedido.Estado.CONFIRMADO)

    def test_cancelar_libera_reserva(self):
        request = type('R', (), {'user': type('U', (), {'is_authenticated': False})()})()
        datos = {
            'nombre_cliente': 'Juan',
            'email': 'juan@test.com',
            'telefono': '3510000000',
            'modalidad_entrega': Pedido.ModalidadEntrega.A_COORDINAR,
            'medio_pago': Pedido.MedioPago.TRANSFERENCIA,
            'notas': '',
        }
        pedido = crear_pedido_desde_carrito(request, self.carrito, datos)
        cancelar_pedido(pedido)

        stock = StockWeb.objects.get(producto=self.producto)
        self.assertEqual(stock.cantidad, 10)
        disponible = stock.cantidad_disponible
        self.assertEqual(disponible, 10)

    def _crear_pedido_inmediato(self, medio_pago: str) -> Pedido:
        request = type('R', (), {'user': type('U', (), {'is_authenticated': False})()})()
        datos = {
            'nombre_cliente': 'Juan',
            'email': 'juan@test.com',
            'telefono': '3510000000',
            'modalidad_entrega': Pedido.ModalidadEntrega.A_COORDINAR,
            'medio_pago': medio_pago,
            'notas': '',
        }
        return crear_pedido_desde_carrito(request, self.carrito, datos)

    def test_confirmar_pedido_falla_si_reserva_expirada(self):
        pedido = self._crear_pedido_inmediato(Pedido.MedioPago.MERCADOPAGO)
        ReservaStock.objects.filter(pedido=pedido).update(
            estado=ReservaStock.Estado.EXPIRADA,
        )

        with self.assertRaises(PedidoError):
            confirmar_pedido(pedido)

        pedido.refresh_from_db()
        stock = StockWeb.objects.get(producto=self.producto)
        self.assertEqual(stock.cantidad, 10)
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE_PAGO)

    def test_confirmar_pedido_falla_si_reserva_ttl_vencido(self):
        pedido = self._crear_pedido_inmediato(Pedido.MedioPago.MERCADOPAGO)
        ReservaStock.objects.filter(pedido=pedido).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        with self.assertRaises(PedidoError):
            confirmar_pedido(pedido)

        pedido.refresh_from_db()
        stock = StockWeb.objects.get(producto=self.producto)
        self.assertEqual(stock.cantidad, 10)
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE_PAGO)

    def test_confirmar_transferencia_falla_si_reserva_expirada(self):
        staff = User.objects.create_user('staff', 'staff@test.com', 'x12345678', is_staff=True)
        pedido = self._crear_pedido_inmediato(Pedido.MedioPago.TRANSFERENCIA)
        ReservaStock.objects.filter(pedido=pedido).update(
            estado=ReservaStock.Estado.EXPIRADA,
        )

        with self.assertRaises(PedidoError):
            confirmar_transferencia_staff(pedido, staff)

        pedido.refresh_from_db()
        stock = StockWeb.objects.get(producto=self.producto)
        self.assertEqual(stock.cantidad, 10)
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE_TRANSFERENCIA)


class PedidoAccesoTests(TestCase):
    def test_confirmacion_requiere_sesion(self):
        cat = Categoria.objects.create(nombre='T', slug='t', activa=True)
        prod = Producto.objects.create(
            categoria=cat, nombre='P', slug='p', sku='P1', descripcion='',
            tipo=Producto.Tipo.ENCARGUE, precio=Decimal('50'), activo=True,
        )
        pedido = Pedido.objects.create(
            numero='FA-2026-000001',
            nombre_cliente='Ana', email='a@t.com', telefono='1',
            estado=Pedido.Estado.PENDIENTE_ENCARGUE,
            modo=Pedido.Modo.ENCARGUE,
            modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
            medio_pago=Pedido.MedioPago.MERCADOPAGO,
            subtotal=Decimal('50'), total=Decimal('50'),
        )
        client = Client()
        url = reverse('pedido_confirmacion', kwargs={'numero': pedido.numero})
        resp = client.get(url)
        self.assertEqual(resp.status_code, 403)


def _datos_checkout(**extra) -> dict:
    datos = {
        'nombre_cliente': 'Juan',
        'email': 'juan@test.com',
        'telefono': '3510000000',
        'modalidad_entrega': Pedido.ModalidadEntrega.A_COORDINAR,
        'medio_pago': Pedido.MedioPago.MERCADOPAGO,
        'notas': '',
    }
    datos.update(extra)
    return datos


def _request_anonimo():
    return type('R', (), {'user': type('U', (), {'is_authenticated': False})()})()


class CrearPedidoRevalidacionTests(TestCase):
    def setUp(self):
        cat = Categoria.objects.create(nombre='Test', slug='test-reval')
        self.producto = Producto.objects.create(
            categoria=cat,
            nombre='Jabón',
            slug='jabon-reval',
            sku='JAB-REV',
            descripcion='',
            tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('100.00'),
            activo=True,
        )
        StockWeb.objects.create(producto=self.producto, cantidad=10)
        self.carrito = Carrito.objects.create(session_key='reval-session')
        self.carrito.modo = Carrito.Modo.INMEDIATO
        self.carrito.save()
        LineaCarrito.objects.create(
            carrito=self.carrito,
            producto=self.producto,
            cantidad=1,
            precio_unitario=Decimal('100.00'),
        )

    def test_rechaza_producto_oculto(self):
        self.producto.activo = False
        self.producto.save()
        with self.assertRaises(PedidoError):
            crear_pedido_desde_carrito(_request_anonimo(), self.carrito, _datos_checkout())
        self.assertEqual(Pedido.objects.count(), 0)

    def test_rechaza_producto_con_receta(self):
        self.producto.requiere_receta = True
        self.producto.save()
        with self.assertRaises(PedidoError):
            crear_pedido_desde_carrito(_request_anonimo(), self.carrito, _datos_checkout())
        self.assertEqual(Pedido.objects.count(), 0)

    def test_rechaza_tipo_distinto_al_modo_del_carrito(self):
        self.producto.tipo = Producto.Tipo.ENCARGUE
        self.producto.save()
        with self.assertRaises(PedidoError):
            crear_pedido_desde_carrito(_request_anonimo(), self.carrito, _datos_checkout())
        self.assertEqual(Pedido.objects.count(), 0)


class CheckoutFormTests(TestCase):
    def setUp(self):
        self.sucursal = Sucursal.objects.create(
            nombre='Centro',
            direccion='Calle 1',
            link_google_maps='https://maps.google.com/?q=test',
        )
        self.franja = FranjaEnvio.objects.create(
            nombre='Mañana', hora_desde='09:00', hora_hasta='13:00',
        )

    def test_encargue_exige_medio_pago(self):
        form = CheckoutForm(
            data={
                'nombre_cliente': 'Ana',
                'email': 'ana@test.com',
                'telefono': '3510000000',
                'modalidad_entrega': Pedido.ModalidadEntrega.A_COORDINAR,
            },
            es_encargue=True,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('medio_pago', form.errors)

    def test_encargue_acepta_medio_pago(self):
        form = CheckoutForm(
            data={
                'nombre_cliente': 'Ana',
                'email': 'ana@test.com',
                'telefono': '3510000000',
                'modalidad_entrega': Pedido.ModalidadEntrega.A_COORDINAR,
                'medio_pago': Pedido.MedioPago.TRANSFERENCIA,
            },
            es_encargue=True,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['medio_pago'], Pedido.MedioPago.TRANSFERENCIA)

    def test_retiro_anula_campos_de_envio(self):
        form = CheckoutForm(
            data={
                'nombre_cliente': 'Ana',
                'email': 'ana@test.com',
                'telefono': '3510000000',
                'modalidad_entrega': Pedido.ModalidadEntrega.RETIRO_SUCURSAL,
                'sucursal_retiro': self.sucursal.pk,
                'direccion_envio': 'Debería ignorarse',
                'fecha_entrega': timezone.localdate().isoformat(),
                'franja_envio': self.franja.pk,
                'medio_pago': Pedido.MedioPago.MERCADOPAGO,
            },
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['sucursal_retiro'], self.sucursal)
        self.assertEqual(form.cleaned_data['direccion_envio'], '')
        self.assertIsNone(form.cleaned_data['fecha_entrega'])
        self.assertIsNone(form.cleaned_data['franja_envio'])

    def test_envio_anula_sucursal(self):
        form = CheckoutForm(
            data={
                'nombre_cliente': 'Ana',
                'email': 'ana@test.com',
                'telefono': '3510000000',
                'modalidad_entrega': Pedido.ModalidadEntrega.ENVIO,
                'sucursal_retiro': self.sucursal.pk,
                'direccion_envio': 'Calle Falsa 123',
                'fecha_entrega': timezone.localdate().isoformat(),
                'franja_envio': self.franja.pk,
                'medio_pago': Pedido.MedioPago.MERCADOPAGO,
            },
        )
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data['sucursal_retiro'])
        self.assertEqual(form.cleaned_data['direccion_envio'], 'Calle Falsa 123')


class CheckoutVistaTests(TestCase):
    def setUp(self):
        cat = Categoria.objects.create(nombre='Test', slug='test-checkout')
        self.encargue = Producto.objects.create(
            categoria=cat, nombre='Perfume', slug='perfume-co', sku='PER-CO',
            descripcion='', tipo=Producto.Tipo.ENCARGUE, precio=Decimal('500'),
            activo=True,
        )
        self.inmediato = Producto.objects.create(
            categoria=cat, nombre='Jabón', slug='jabon-co', sku='JAB-CO',
            descripcion='', tipo=Producto.Tipo.INMEDIATO, precio=Decimal('100'),
            activo=True,
        )
        StockWeb.objects.create(producto=self.inmediato, cantidad=5)

    def _carrito_en_sesion(self, producto: Producto, modo: str) -> Carrito:
        session = self.client.session
        session.save()
        carrito = Carrito.objects.create(session_key=session.session_key, modo=modo)
        LineaCarrito.objects.create(
            carrito=carrito,
            producto=producto,
            cantidad=1,
            precio_unitario=producto.precio,
        )
        return carrito

    def test_encargue_muestra_radios_de_medio_pago(self):
        self._carrito_en_sesion(self.encargue, Carrito.Modo.ENCARGUE)
        resp = self.client.get(reverse('pedido_checkout'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="medio_pago"')
        self.assertContains(resp, 'cuando confirmemos')

    def test_encargue_no_redirige_a_pagar(self):
        self._carrito_en_sesion(self.encargue, Carrito.Modo.ENCARGUE)
        resp = self.client.post(
            reverse('pedido_checkout'),
            {
                'nombre_cliente': 'Ana',
                'email': 'ana@test.com',
                'telefono': '3510000000',
                'modalidad_entrega': Pedido.ModalidadEntrega.A_COORDINAR,
                'medio_pago': Pedido.MedioPago.MERCADOPAGO,
            },
        )
        pedido = Pedido.objects.get()
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE_ENCARGUE)
        self.assertFalse(pedido.puede_pagar_online)
        self.assertEqual(pedido.medio_pago, Pedido.MedioPago.MERCADOPAGO)
        self.assertRedirects(
            resp,
            reverse('pedido_confirmacion', kwargs={'numero': pedido.numero}),
            fetch_redirect_response=False,
        )

    def test_inmediato_mercadopago_redirige_a_pagar(self):
        self._carrito_en_sesion(self.inmediato, Carrito.Modo.INMEDIATO)
        resp = self.client.post(
            reverse('pedido_checkout'),
            {
                'nombre_cliente': 'Ana',
                'email': 'ana@test.com',
                'telefono': '3510000000',
                'modalidad_entrega': Pedido.ModalidadEntrega.A_COORDINAR,
                'medio_pago': Pedido.MedioPago.MERCADOPAGO,
            },
        )
        pedido = Pedido.objects.get()
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE_PAGO)
        self.assertTrue(pedido.puede_pagar_online)
        self.assertRedirects(
            resp,
            reverse('pagos_iniciar', kwargs={'numero': pedido.numero}),
            fetch_redirect_response=False,
        )


class PedidoAdminEstadoTests(TestCase):
    def test_estado_es_readonly(self):
        self.assertIn('estado', PedidoAdmin.readonly_fields)

    def test_formulario_admin_no_edita_estado(self):
        admin_user = User.objects.create_superuser(
            'duenio', 'd@test.com', 'farmacia-2026-segura',
        )
        self.client.force_login(admin_user)
        pedido = Pedido.objects.create(
            numero='FA-2026-000030',
            nombre_cliente='Ana', email='a@t.com', telefono='1',
            estado=Pedido.Estado.PENDIENTE_ENCARGUE,
            modo=Pedido.Modo.ENCARGUE,
            modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
            medio_pago=Pedido.MedioPago.MERCADOPAGO,
            subtotal=Decimal('50'), total=Decimal('50'),
        )
        resp = self.client.get(reverse('admin:pedidos_pedido_change', args=[pedido.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="estado"')
