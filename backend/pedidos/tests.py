import threading
import time
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Categoria, Producto
from inventario.models import ReservaStock, StockWeb
from pedidos.admin import PedidoAdmin
from pedidos.forms import CheckoutForm
from pedidos.models import FranjaEnvio, Pedido
from pedidos.services import (
    PedidoError,
    aprobar_encargue,
    avanzar_fulfillment,
    cancelar_pedido,
    confirmar_pedido,
    confirmar_transferencia_staff,
    crear_pedido_desde_carrito,
)
from pagos.models import Pago
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

    def test_transferencia_no_se_autoconfirma_aunque_figure_pendiente_pago(self):
        """Regla: la transferencia nunca pasa a confirmado por el camino del pago online."""
        pedido = self._crear_pedido_inmediato(Pedido.MedioPago.TRANSFERENCIA)
        pedido.estado = Pedido.Estado.PENDIENTE_PAGO
        pedido.save(update_fields=['estado'])

        with self.assertRaises(PedidoError):
            confirmar_pedido(pedido)

        pedido.refresh_from_db()
        stock = StockWeb.objects.get(producto=self.producto)
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE_PAGO)
        self.assertEqual(stock.cantidad, 10)
        self.assertTrue(
            ReservaStock.objects.filter(
                pedido=pedido, estado=ReservaStock.Estado.ACTIVA,
            ).exists()
        )


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


class CrearPedidoEnvioCupoTests(TestCase):
    """El servicio revalida franja, fecha y cupo: el form no alcanza."""

    def setUp(self):
        cat = Categoria.objects.create(nombre='Envio', slug='envio-cupo')
        self.producto = Producto.objects.create(
            categoria=cat,
            nombre='Crema',
            slug='crema-envio',
            sku='CRE-ENV',
            descripcion='',
            tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('100.00'),
            activo=True,
        )
        StockWeb.objects.create(producto=self.producto, cantidad=10)
        self.franja = FranjaEnvio.objects.create(
            nombre='Mañana',
            hora_desde='09:00',
            hora_hasta='13:00',
            cupo_max=1,
        )
        self.fecha = timezone.localdate()
        self.carrito = Carrito.objects.create(
            session_key='envio-cupo',
            modo=Carrito.Modo.INMEDIATO,
        )
        LineaCarrito.objects.create(
            carrito=self.carrito,
            producto=self.producto,
            cantidad=1,
            precio_unitario=Decimal('100.00'),
        )

    def _datos_envio(self, **extra) -> dict:
        datos = _datos_checkout(
            modalidad_entrega=Pedido.ModalidadEntrega.ENVIO,
            direccion_envio='Calle Falsa 123',
            franja_envio=self.franja,
            fecha_entrega=self.fecha,
        )
        datos.update(extra)
        return datos

    def test_envio_sin_franja_ni_fecha_rechaza(self):
        incompletos = (
            self._datos_envio(franja_envio=None, fecha_entrega=None),
            self._datos_envio(franja_envio=None),
            self._datos_envio(fecha_entrega=None),
        )
        for datos in incompletos:
            with self.assertRaises(PedidoError):
                crear_pedido_desde_carrito(_request_anonimo(), self.carrito, datos)
        self.assertEqual(Pedido.objects.count(), 0)

    def test_envio_fecha_pasada_rechaza(self):
        with self.assertRaises(PedidoError):
            crear_pedido_desde_carrito(
                _request_anonimo(),
                self.carrito,
                self._datos_envio(fecha_entrega=self.fecha - timedelta(days=1)),
            )
        self.assertEqual(Pedido.objects.count(), 0)

    def test_envio_sin_cupo_rechaza(self):
        Pedido.objects.create(
            numero='FA-2026-000040',
            nombre_cliente='B',
            email='b@t.com',
            telefono='1',
            estado=Pedido.Estado.CONFIRMADO,
            modo=Pedido.Modo.INMEDIATO,
            modalidad_entrega=Pedido.ModalidadEntrega.ENVIO,
            franja_envio=self.franja,
            fecha_entrega=self.fecha,
            medio_pago=Pedido.MedioPago.MERCADOPAGO,
            subtotal=Decimal('50'),
            total=Decimal('50'),
        )
        with self.assertRaises(PedidoError):
            crear_pedido_desde_carrito(
                _request_anonimo(),
                self.carrito,
                self._datos_envio(),
            )
        self.assertEqual(Pedido.objects.count(), 1)

    def test_envio_con_cupo_crea_pedido(self):
        pedido = crear_pedido_desde_carrito(
            _request_anonimo(),
            self.carrito,
            self._datos_envio(),
        )
        self.assertEqual(pedido.modalidad_entrega, Pedido.ModalidadEntrega.ENVIO)
        self.assertEqual(pedido.franja_envio_id, self.franja.pk)
        self.assertEqual(pedido.fecha_entrega, self.fecha)
        self.assertEqual(Pedido.objects.count(), 1)

    def test_envio_franja_inactiva_rechaza(self):
        self.franja.activa = False
        self.franja.save(update_fields=['activa'])
        with self.assertRaises(PedidoError):
            crear_pedido_desde_carrito(
                _request_anonimo(),
                self.carrito,
                self._datos_envio(),
            )
        self.assertEqual(Pedido.objects.count(), 0)


class PedidoAdminEstadoTests(TestCase):
    def test_estado_es_readonly(self):
        self.assertIn('estado', PedidoAdmin.readonly_fields)

    def test_modo_y_medio_pago_son_readonly(self):
        self.assertIn('modo', PedidoAdmin.readonly_fields)
        self.assertIn('medio_pago', PedidoAdmin.readonly_fields)

    def test_formulario_admin_no_edita_estado_modo_ni_medio_pago(self):
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
        self.assertNotContains(resp, 'name="modo"')
        self.assertNotContains(resp, 'name="medio_pago"')


class TransicionConCopiaViejaTests(TestCase):
    """Una copia en memoria no puede pisar el estado que otra acción ya guardó."""

    def setUp(self):
        cat = Categoria.objects.create(nombre='Estados', slug='estados-lock')
        self.inmediato = Producto.objects.create(
            categoria=cat, nombre='Jabón', slug='jabon-lock', sku='JAB-LOCK',
            descripcion='', tipo=Producto.Tipo.INMEDIATO, precio=Decimal('100'),
            activo=True,
        )
        StockWeb.objects.create(producto=self.inmediato, cantidad=10)
        self.encargue = Producto.objects.create(
            categoria=cat, nombre='Perfume', slug='perfume-lock', sku='PER-LOCK',
            descripcion='', tipo=Producto.Tipo.ENCARGUE, precio=Decimal('500'),
            activo=True,
        )
        self.staff = User.objects.create_user(
            'staff-lock', 'staff-lock@test.com', 'x12345678', is_staff=True,
        )

    def _pedido(self, producto: Producto, medio: str) -> Pedido:
        modo = (
            Carrito.Modo.ENCARGUE if producto.es_encargue else Carrito.Modo.INMEDIATO
        )
        carrito = Carrito.objects.create(session_key=f'lock-{producto.sku}', modo=modo)
        LineaCarrito.objects.create(
            carrito=carrito, producto=producto,
            cantidad=1, precio_unitario=producto.precio,
        )
        return crear_pedido_desde_carrito(
            _request_anonimo(),
            carrito,
            _datos_checkout(medio_pago=medio),
        )

    def test_no_cancela_un_entregado_con_copia_anterior(self):
        pedido = self._pedido(self.inmediato, Pedido.MedioPago.MERCADOPAGO)
        confirmar_pedido(pedido)
        avanzar_fulfillment(pedido, Pedido.Estado.EN_PREPARACION, actor=self.staff)
        avanzar_fulfillment(pedido, Pedido.Estado.LISTO_RETIRO, actor=self.staff)
        copia = Pedido.objects.get(pk=pedido.pk)
        avanzar_fulfillment(pedido, Pedido.Estado.ENTREGADO, actor=self.staff)

        with self.assertRaises(PedidoError):
            cancelar_pedido(copia, actor=self.staff)

        copia.refresh_from_db()
        self.assertEqual(copia.estado, Pedido.Estado.ENTREGADO)

    def test_no_salta_de_listo_retiro_a_despachado(self):
        pedido = self._pedido(self.inmediato, Pedido.MedioPago.MERCADOPAGO)
        confirmar_pedido(pedido)
        avanzar_fulfillment(pedido, Pedido.Estado.EN_PREPARACION, actor=self.staff)
        copia_a = Pedido.objects.get(pk=pedido.pk)
        copia_b = Pedido.objects.get(pk=pedido.pk)
        avanzar_fulfillment(copia_a, Pedido.Estado.LISTO_RETIRO, actor=self.staff)

        with self.assertRaises(PedidoError):
            avanzar_fulfillment(copia_b, Pedido.Estado.DESPACHADO, actor=self.staff)

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, Pedido.Estado.LISTO_RETIRO)

    def test_aprobar_encargue_dos_veces_no_duplica_el_pago(self):
        pedido = self._pedido(self.encargue, Pedido.MedioPago.TRANSFERENCIA)
        copia_a = Pedido.objects.get(pk=pedido.pk)
        copia_b = Pedido.objects.get(pk=pedido.pk)
        aprobar_encargue(copia_a, self.staff)

        with self.assertRaises(PedidoError):
            aprobar_encargue(copia_b, self.staff)

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE_TRANSFERENCIA)
        self.assertEqual(Pago.objects.filter(pedido=pedido).count(), 1)

    def test_no_confirma_encargue_ya_cancelado(self):
        pedido = self._pedido(self.encargue, Pedido.MedioPago.MERCADOPAGO)
        aprobar_encargue(pedido, self.staff)
        copia = Pedido.objects.get(pk=pedido.pk)
        cancelar_pedido(pedido, actor=self.staff)

        with self.assertRaises(PedidoError):
            confirmar_pedido(copia)

        copia.refresh_from_db()
        self.assertEqual(copia.estado, Pedido.Estado.CANCELADO)


def _checkout_en_hilo(carrito: Carrito, datos: dict, resultados: list[str], barrera: threading.Barrier) -> None:
    """Corre un checkout en otro hilo. Cierra la conexión al terminar."""
    try:
        barrera.wait(timeout=10)
        crear_pedido_desde_carrito(_request_anonimo(), carrito, datos)
        resultados.append('ok')
    except PedidoError:
        resultados.append('error')
    except Exception as exc:
        resultados.append(f'boom:{type(exc).__name__}:{exc}')
    finally:
        connection.close()


class ConcurrenciaCheckoutTests(TransactionTestCase):
    """SQLite ignora SELECT FOR UPDATE: el lock tiene que ser un UPDATE real."""

    def _producto(self, sku: str, stock: int) -> Producto:
        cat, _ = Categoria.objects.get_or_create(nombre='Race', defaults={'slug': 'race'})
        producto = Producto.objects.create(
            categoria=cat, nombre=sku, slug=sku.lower(), sku=sku,
            descripcion='', tipo=Producto.Tipo.INMEDIATO, precio=Decimal('100'),
            activo=True,
        )
        StockWeb.objects.create(producto=producto, cantidad=stock)
        return producto

    def _carrito(self, clave: str, producto: Producto, cantidad: int = 1) -> Carrito:
        carrito = Carrito.objects.create(session_key=clave, modo=Carrito.Modo.INMEDIATO)
        LineaCarrito.objects.create(
            carrito=carrito, producto=producto,
            cantidad=cantidad, precio_unitario=producto.precio,
        )
        return carrito

    def _correr(self, trabajos: list) -> list[str]:
        # Pausa con el carrito ya bloqueado. Si el lock no espera, los dos
        # hilos arman el pedido con la misma foto y los dos devuelven ok.
        import pedidos.services as servicios_pedido

        real = servicios_pedido.bloquear_carrito

        def bloquear_y_esperar(carrito_a_bloquear: Carrito) -> Carrito:
            bloqueado = real(carrito_a_bloquear)
            time.sleep(0.3)
            return bloqueado

        servicios_pedido.bloquear_carrito = bloquear_y_esperar
        barrera = threading.Barrier(len(trabajos))
        resultados: list[str] = []
        hilos = [
            threading.Thread(target=trabajo, args=(barrera, resultados))
            for trabajo in trabajos
        ]
        try:
            for hilo in hilos:
                hilo.start()
            for hilo in hilos:
                hilo.join(timeout=15)
                self.assertFalse(hilo.is_alive(), 'un checkout quedó colgado')
        finally:
            servicios_pedido.bloquear_carrito = real
        return resultados

    def test_dos_checkouts_no_reservan_la_ultima_unidad_dos_veces(self):
        producto = self._producto('RACE-1', stock=1)
        carritos = [
            self._carrito('race-a', producto),
            self._carrito('race-b', producto),
        ]

        def trabajo(carrito):
            def correr(barrera, resultados):
                _checkout_en_hilo(carrito, _datos_checkout(), resultados, barrera)
            return correr

        resultados = self._correr([trabajo(c) for c in carritos])
        self.assertEqual(sorted(resultados), ['error', 'ok'], resultados)
        self.assertEqual(
            ReservaStock.objects.filter(estado=ReservaStock.Estado.ACTIVA).count(),
            1,
        )
        self.assertEqual(Pedido.objects.count(), 1)

    def test_doble_click_en_el_mismo_carrito_crea_un_solo_pedido(self):
        producto = self._producto('RACE-2', stock=10)
        carrito = self._carrito('race-doble', producto)

        def correr(barrera, resultados):
            _checkout_en_hilo(carrito, _datos_checkout(), resultados, barrera)

        resultados = self._correr([correr, correr])
        self.assertEqual(sorted(resultados), ['error', 'ok'], resultados)
        self.assertEqual(Pedido.objects.count(), 1)
        self.assertEqual(
            ReservaStock.objects.filter(estado=ReservaStock.Estado.ACTIVA).count(),
            1,
        )

    def test_dos_envios_no_superan_el_cupo(self):
        producto = self._producto('RACE-3', stock=10)
        franja = FranjaEnvio.objects.create(
            nombre='Tarde', hora_desde='14:00', hora_hasta='18:00', cupo_max=1,
        )
        fecha = timezone.localdate()
        datos = _datos_checkout(
            modalidad_entrega=Pedido.ModalidadEntrega.ENVIO,
            direccion_envio='Calle Falsa 123',
            franja_envio=franja,
            fecha_entrega=fecha,
        )
        carritos = [
            self._carrito('race-c', producto),
            self._carrito('race-d', producto),
        ]

        def trabajo(carrito):
            def correr(barrera, resultados):
                _checkout_en_hilo(carrito, datos, resultados, barrera)
            return correr

        resultados = self._correr([trabajo(c) for c in carritos])
        self.assertEqual(sorted(resultados), ['error', 'ok'], resultados)
        self.assertEqual(
            Pedido.objects.filter(franja_envio=franja, fecha_entrega=fecha).count(),
            1,
        )
