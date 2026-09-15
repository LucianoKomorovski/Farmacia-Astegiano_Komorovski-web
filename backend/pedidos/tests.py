from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Categoria, Producto
from inventario.models import ReservaStock, StockWeb
from pedidos.models import Pedido
from pedidos.services import (
    PedidoError,
    cancelar_pedido,
    confirmar_pedido,
    confirmar_transferencia_staff,
    crear_pedido_desde_carrito,
)
from carrito.models import Carrito, LineaCarrito


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
