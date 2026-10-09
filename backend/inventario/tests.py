"""Tests del importador CSV de stock y de consolidación de reservas."""

import threading
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from catalogo.models import Categoria, Producto
from inventario.importador import calcular_stock_web, importar_stock_csv
from inventario.models import ReservaStock, StockWeb
from inventario.services import (
    StockError,
    consolidar_reservas_pedido,
    expirar_reservas_vencidas,
)
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


class ExpirarReservasTests(TestCase):
    def setUp(self):
        cat = Categoria.objects.create(nombre='Exp', slug='exp')
        self.producto = Producto.objects.create(
            categoria=cat, nombre='Crema', slug='crema-exp', sku='CRE-EXP',
            descripcion='', tipo=Producto.Tipo.INMEDIATO, precio=Decimal('100'),
            activo=True,
        )
        self.stock = StockWeb.objects.create(producto=self.producto, cantidad=10)

    def _pedido(self, numero: str, estado: str) -> Pedido:
        return Pedido.objects.create(
            numero=numero,
            nombre_cliente='Ana', email='ana@test.com', telefono='1',
            estado=estado,
            modo=Pedido.Modo.INMEDIATO,
            modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
            medio_pago=Pedido.MedioPago.MERCADOPAGO,
            subtotal=Decimal('100'), total=Decimal('100'),
        )

    def test_expirar_cancela_pendiente_y_no_toca_cantidad(self):
        pedido = self._pedido('FA-2026-008001', Pedido.Estado.PENDIENTE_PAGO)
        ReservaStock.objects.create(
            producto=self.producto, pedido=pedido, cantidad=4,
            estado=ReservaStock.Estado.ACTIVA,
            expires_at=timezone.now() - timedelta(minutes=5),
        )

        cancelados = expirar_reservas_vencidas()

        pedido.refresh_from_db()
        self.stock.refresh_from_db()
        reserva = ReservaStock.objects.get(pedido=pedido)
        self.assertEqual(cancelados, 1)
        self.assertEqual(pedido.estado, Pedido.Estado.CANCELADO)
        self.assertEqual(self.stock.cantidad, 10)
        self.assertEqual(reserva.estado, ReservaStock.Estado.EXPIRADA)

    def test_expirar_no_pisa_una_reserva_ya_consolidada(self):
        pedido = self._pedido('FA-2026-008002', Pedido.Estado.CONFIRMADO)
        ReservaStock.objects.create(
            producto=self.producto, pedido=pedido, cantidad=4,
            estado=ReservaStock.Estado.CONSOLIDADA,
            expires_at=timezone.now() - timedelta(minutes=5),
        )
        self.stock.cantidad = 6
        self.stock.save(update_fields=['cantidad'])

        self.assertEqual(expirar_reservas_vencidas(), 0)

        pedido.refresh_from_db()
        self.stock.refresh_from_db()
        reserva = ReservaStock.objects.get(pedido=pedido)
        self.assertEqual(pedido.estado, Pedido.Estado.CONFIRMADO)
        self.assertEqual(self.stock.cantidad, 6)
        self.assertEqual(reserva.estado, ReservaStock.Estado.CONSOLIDADA)


class ConsolidarConcurrenteTests(TransactionTestCase):
    """Dos confirmaciones no pueden descontar el mismo stock dos veces."""

    def test_solo_una_consolidacion_descuenta(self):
        cat = Categoria.objects.create(nombre='Conc', slug='conc')
        producto = Producto.objects.create(
            categoria=cat, nombre='Jarabe', slug='jarabe-conc', sku='JAR-CONC',
            descripcion='', tipo=Producto.Tipo.INMEDIATO, precio=Decimal('100'),
            activo=True,
        )
        StockWeb.objects.create(producto=producto, cantidad=5)
        pedidos = []
        for numero in ('FA-2026-008101', 'FA-2026-008102'):
            pedido = Pedido.objects.create(
                numero=numero,
                nombre_cliente='Ana', email='ana@test.com', telefono='1',
                estado=Pedido.Estado.PENDIENTE_PAGO,
                modo=Pedido.Modo.INMEDIATO,
                modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
                medio_pago=Pedido.MedioPago.MERCADOPAGO,
                subtotal=Decimal('300'), total=Decimal('300'),
            )
            ReservaStock.objects.create(
                producto=producto, pedido=pedido, cantidad=3,
                estado=ReservaStock.Estado.ACTIVA,
                expires_at=timezone.now() + timedelta(hours=1),
            )
            pedidos.append(pedido)

        barrera = threading.Barrier(2)
        resultados: list[str] = []
        import inventario.services as servicios_stock

        # Pausa entre leer la reserva y descontar. Sin el UPDATE atómico
        # los dos leen cantidad=5 y los dos guardan 2.
        servicios_stock.pausa_antes_de_descontar = lambda: time.sleep(0.3)

        def correr(pedido: Pedido) -> None:
            try:
                barrera.wait(timeout=10)
                consolidar_reservas_pedido(pedido)
                resultados.append('ok')
            except StockError:
                resultados.append('error')
            except Exception as exc:
                resultados.append(f'boom:{type(exc).__name__}:{exc}')
            finally:
                connection.close()

        hilos = [threading.Thread(target=correr, args=(pedido,)) for pedido in pedidos]
        try:
            for hilo in hilos:
                hilo.start()
            for hilo in hilos:
                hilo.join(timeout=15)
                self.assertFalse(hilo.is_alive())
        finally:
            servicios_stock.pausa_antes_de_descontar = None

        stock = StockWeb.objects.get(producto=producto)
        self.assertEqual(sorted(resultados), ['error', 'ok'], resultados)
        self.assertEqual(stock.cantidad, 2)
        self.assertEqual(
            ReservaStock.objects.filter(estado=ReservaStock.Estado.CONSOLIDADA).count(),
            1,
        )
        self.assertEqual(
            ReservaStock.objects.filter(estado=ReservaStock.Estado.ACTIVA).count(),
            1,
        )
