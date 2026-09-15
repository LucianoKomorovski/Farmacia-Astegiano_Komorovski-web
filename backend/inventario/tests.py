"""Tests del importador CSV de stock y de consolidación de reservas."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.test import TestCase
from django.utils import timezone

from catalogo.models import Categoria, Producto
from inventario.importador import calcular_stock_web, importar_stock_csv
from inventario.models import ReservaStock, StockWeb
from inventario.services import StockError, consolidar_reservas_pedido
from pedidos.models import Pedido


class ImportadorStockTests(TestCase):
    def setUp(self):
        cat = Categoria.objects.create(nombre='T', slug='t')
        self.producto = Producto.objects.create(
            categoria=cat,
            nombre='Jabón',
            slug='jabon',
            sku='HIG-001',
            codigo_barras='7790001001003',
            descripcion='',
            tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('100'),
            activo=True,
        )

    def test_calcular_stock_web(self):
        self.assertEqual(calcular_stock_web(50, margen_seguridad=5, tope_web=40), 40)
        self.assertEqual(calcular_stock_web(10, margen_seguridad=15), 0)

    def test_importar_csv_actualiza_stock(self):
        csv_content = (
            'sku,codigo_barras,codigo_praxys,stock_praxys,margen_seguridad,tope_web\n'
            'HIG-001,7790001001003,,50,5,40\n'
        )
        with NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            path = f.name

        log, resultado = importar_stock_csv(path)
        Path(path).unlink()

        self.assertTrue(log.ok)
        self.assertEqual(resultado.actualizados, 1)
        stock = StockWeb.objects.get(producto=self.producto)
        self.assertEqual(stock.cantidad, 40)
        self.assertEqual(stock.origen, StockWeb.Origen.CSV)


class ConsolidarReservasTests(TestCase):
    """Consolidar solo con reserva ACTIVA vigente; si no, no toca StockWeb."""

    def setUp(self):
        cat = Categoria.objects.create(nombre='T', slug='t')
        self.producto = Producto.objects.create(
            categoria=cat,
            nombre='Jabón',
            slug='jabon',
            sku='HIG-002',
            descripcion='',
            tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('100'),
            activo=True,
        )
        self.stock = StockWeb.objects.create(producto=self.producto, cantidad=10)

    def _pedido_con_reserva(self, estado: str, expires_at) -> Pedido:
        pedido = Pedido.objects.create(
            numero='FA-2026-009900',
            nombre_cliente='Ana',
            email='ana@test.com',
            telefono='1',
            estado=Pedido.Estado.PENDIENTE_PAGO,
            modo=Pedido.Modo.INMEDIATO,
            modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
            medio_pago=Pedido.MedioPago.MERCADOPAGO,
            subtotal=Decimal('300'),
            total=Decimal('300'),
        )
        ReservaStock.objects.create(
            producto=self.producto,
            pedido=pedido,
            cantidad=3,
            estado=estado,
            expires_at=expires_at,
        )
        return pedido

    def test_consolidar_reserva_vigente_descuenta_stock(self):
        pedido = self._pedido_con_reserva(
            ReservaStock.Estado.ACTIVA,
            timezone.now() + timedelta(hours=1),
        )
        consolidar_reservas_pedido(pedido)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.cantidad, 7)
        reserva = ReservaStock.objects.get(pedido=pedido)
        self.assertEqual(reserva.estado, ReservaStock.Estado.CONSOLIDADA)

    def test_consolidar_reserva_expirada_falla_sin_descontar(self):
        pedido = self._pedido_con_reserva(
            ReservaStock.Estado.EXPIRADA,
            timezone.now() - timedelta(minutes=5),
        )
        with self.assertRaises(StockError):
            consolidar_reservas_pedido(pedido)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.cantidad, 10)
        reserva = ReservaStock.objects.get(pedido=pedido)
        self.assertEqual(reserva.estado, ReservaStock.Estado.EXPIRADA)

    def test_consolidar_activa_con_ttl_vencido_falla_sin_descontar(self):
        # El job de TTL todavía no la marcó EXPIRADA, pero ya no es consolidable.
        pedido = self._pedido_con_reserva(
            ReservaStock.Estado.ACTIVA,
            timezone.now() - timedelta(minutes=1),
        )
        with self.assertRaises(StockError):
            consolidar_reservas_pedido(pedido)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.cantidad, 10)
        reserva = ReservaStock.objects.get(pedido=pedido)
        self.assertEqual(reserva.estado, ReservaStock.Estado.ACTIVA)
