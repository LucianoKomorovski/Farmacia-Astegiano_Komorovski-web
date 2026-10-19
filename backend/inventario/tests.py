"""Tests del importador CSV de stock y de consolidación de reservas."""

import threading
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.contrib.auth.models import Permission, User
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
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


class ReservaStockAdminTests(TestCase):
    def test_post_no_cambia_expires_at(self):
        """Un POST del staff no puede estirar el TTL de la reserva.

        expires_at es el TTL real de 1 h que usan consolidar_reservas_pedido
        y expirar_reservas_vencidas. Si el admin dejara editarlo, un webhook
        approved tardío de Mercado Pago confirmaría el pedido en vez de
        quedar registrado como _webhook_tarde.
        """
        # El grupo Empleadas solo consulta reservas. Este permiso de cambio
        # es el del dueño en el panel: sin él el POST ni llega al formulario
        # y el test no probaría que el campo es de solo lectura.
        staff = User.objects.create_user(
            'staff-reserva', 'staff-reserva@test.com', 'x12345678', is_staff=True,
        )
        staff.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='inventario',
                codename='change_reservastock',
            ),
        )
        self.client.force_login(staff)

        cat = Categoria.objects.create(nombre='Admin', slug='admin-reserva')
        producto = Producto.objects.create(
            categoria=cat,
            nombre='Jabón',
            slug='jabon-admin',
            sku='JAB-ADMIN',
            descripcion='',
            tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('100'),
            activo=True,
        )
        pedido = Pedido.objects.create(
            numero='FA-2026-009901',
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
        vence = timezone.now() + timedelta(hours=1)
        reserva = ReservaStock.objects.create(
            producto=producto,
            pedido=pedido,
            cantidad=3,
            estado=ReservaStock.Estado.ACTIVA,
            expires_at=vence,
        )
        url = reverse('admin:inventario_reservastock_change', args=[reserva.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        data = self._datos_change(resp)
        # El staff manda otra fecha de vencimiento. Ya no queda ningún campo
        # editable en el formulario (cantidad, estado, pedido y producto
        # también son de solo lectura), así que el control no puede ser
        # "este otro campo sí cambió": el POST tiene que responder OK y
        # dejar la reserva igual.
        data['expires_at_0'] = '2099-12-31'
        data['expires_at_1'] = '23:59:59'
        data['_save'] = 'Guardar'
        antes = self._foto_reserva(reserva)

        resp = self.client.post(url, data)
        self.assertRedirects(
            resp,
            reverse('admin:inventario_reservastock_changelist'),
            fetch_redirect_response=False,
        )

        reserva.refresh_from_db()
        self.assertEqual(self._foto_reserva(reserva), antes)
        self.assertEqual(reserva.expires_at, vence)

    def test_post_no_cambia_cantidad_estado_pedido_producto(self):
        """Un POST del staff no desfasa la reserva de las líneas del pedido.

        StockWeb es espejo: disponible = cantidad − reservas activas
        vigentes, y la consolidación descuenta reserva.cantidad. Si el admin
        dejara editar cantidad, estado, pedido o producto, el espejo
        descontaría de más, de menos, o contra otro producto.
        """
        staff = User.objects.create_user(
            'staff-reserva-campos', 'staff-reserva-campos@test.com', 'x12345678',
            is_staff=True,
        )
        staff.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='inventario',
                codename='change_reservastock',
            ),
        )
        self.client.force_login(staff)

        cat = Categoria.objects.create(nombre='Admin campos', slug='admin-reserva-campos')
        producto = Producto.objects.create(
            categoria=cat,
            nombre='Jabón',
            slug='jabon-admin-campos',
            sku='JAB-ADMIN-CAMPOS',
            descripcion='',
            tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('100'),
            activo=True,
        )
        otro_producto = Producto.objects.create(
            categoria=cat,
            nombre='Crema',
            slug='crema-admin-campos',
            sku='CRE-ADMIN-CAMPOS',
            descripcion='',
            tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('200'),
            activo=True,
        )
        pedido = Pedido.objects.create(
            numero='FA-2026-009902',
            nombre_cliente='Ana',
            email='ana-campos@test.com',
            telefono='1',
            estado=Pedido.Estado.PENDIENTE_PAGO,
            modo=Pedido.Modo.INMEDIATO,
            modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
            medio_pago=Pedido.MedioPago.MERCADOPAGO,
            subtotal=Decimal('300'),
            total=Decimal('300'),
        )
        otro_pedido = Pedido.objects.create(
            numero='FA-2026-009903',
            nombre_cliente='Luis',
            email='luis-campos@test.com',
            telefono='2',
            estado=Pedido.Estado.PENDIENTE_PAGO,
            modo=Pedido.Modo.INMEDIATO,
            modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
            medio_pago=Pedido.MedioPago.MERCADOPAGO,
            subtotal=Decimal('200'),
            total=Decimal('200'),
        )
        reserva = ReservaStock.objects.create(
            producto=producto,
            pedido=pedido,
            cantidad=3,
            estado=ReservaStock.Estado.ACTIVA,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        url = reverse('admin:inventario_reservastock_change', args=[reserva.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        data = self._datos_change(resp)
        # Valores válidos y distintos: si el campo siguiera en el formulario,
        # el admin los guardaría. Al ser solo lectura, el POST los ignora.
        data['cantidad'] = '9'
        data['estado'] = ReservaStock.Estado.LIBERADA
        data['pedido'] = str(otro_pedido.pk)
        data['producto'] = str(otro_producto.pk)
        data['_save'] = 'Guardar'
        antes = self._foto_reserva(reserva)

        resp = self.client.post(url, data)
        self.assertRedirects(
            resp,
            reverse('admin:inventario_reservastock_changelist'),
            fetch_redirect_response=False,
        )

        reserva.refresh_from_db()
        self.assertEqual(reserva.cantidad, 3)
        self.assertEqual(reserva.estado, ReservaStock.Estado.ACTIVA)
        self.assertEqual(reserva.pedido_id, pedido.pk)
        self.assertEqual(reserva.producto_id, producto.pk)
        self.assertEqual(self._foto_reserva(reserva), antes)

    def _foto_reserva(self, reserva: ReservaStock) -> dict[str, object]:
        """Valores que el admin no debe poder cambiar."""
        return {
            'cantidad': reserva.cantidad,
            'estado': reserva.estado,
            'pedido_id': reserva.pedido_id,
            'producto_id': reserva.producto_id,
            'expires_at': reserva.expires_at,
            'created_at': reserva.created_at,
        }

    def _datos_change(self, response) -> dict[str, str]:
        """Copia el formulario de cambio (y los inlines) para reenviarlo."""
        data: dict[str, str] = {}
        form = response.context['adminform'].form
        for name in form.fields:
            valor = form[name].value()
            data[name] = '' if valor is None else str(valor)

        for inline_formset in response.context['inline_admin_formsets']:
            formset = inline_formset.formset
            prefijo = formset.prefix
            for clave, valor in formset.management_form.initial.items():
                data[f'{prefijo}-{clave}'] = '' if valor is None else str(valor)
            for form_inline in formset.forms:
                for name in form_inline.fields:
                    valor = form_inline[name].value()
                    clave = form_inline.add_prefix(name)
                    data[clave] = '' if valor is None else str(valor)
        return data
