"""Tests del panel: servicios de analítica, API JSON/CSV y portada."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Categoria, Producto
from cuentas.models import PerfilStaff
from cuentas.services import aprobar_solicitud
from inventario.models import StockWeb
from pedidos.models import LineaPedido, Pedido

from . import services

CLAVE = 'farmacia-2026-segura'


def crear_producto(nombre: str, categoria: Categoria | None, precio: str) -> Producto:
    return Producto.objects.create(
        nombre=nombre,
        slug=nombre.lower().replace(' ', '-'),
        sku=f'SKU-{nombre[:6].upper().replace(" ", "")}',
        categoria=categoria,
        precio=Decimal(precio),
    )


def crear_venta(
    numero: str,
    lineas: list[tuple[Producto, int]],
    estado: str = Pedido.Estado.CONFIRMADO,
    hace_dias: int = 0,
    medio: str = Pedido.MedioPago.MERCADOPAGO,
) -> Pedido:
    """Pedido con líneas y confirmado_en = ahora − hace_dias."""
    subtotal = sum((p.precio * c for p, c in lineas), Decimal('0'))
    momento = timezone.now() - timedelta(days=hace_dias)
    pedido = Pedido.objects.create(
        numero=numero,
        nombre_cliente='Cliente',
        email='c@test.com',
        telefono='1',
        estado=estado,
        modo=Pedido.Modo.INMEDIATO,
        modalidad_entrega=Pedido.ModalidadEntrega.RETIRO_SUCURSAL,
        medio_pago=medio,
        subtotal=subtotal,
        total=subtotal,
        confirmado_en=momento,
    )
    for producto, cantidad in lineas:
        LineaPedido.objects.create(
            pedido=pedido,
            producto=producto,
            nombre_snapshot=producto.nombre,
            sku_snapshot=producto.sku,
            cantidad=cantidad,
            precio_unitario=producto.precio,
            subtotal=producto.precio * cantidad,
        )
    return pedido


class AnaliticaServiciosTests(TestCase):
    def setUp(self):
        self.derma = Categoria.objects.create(nombre='Dermocosmética', slug='derma')
        self.higiene = Categoria.objects.create(nombre='Higiene', slug='higiene')
        self.crema = crear_producto('Crema solar', self.derma, '1000')
        self.jabon = crear_producto('Jabon suave', self.higiene, '200')
        self.sin_cat = crear_producto('Producto suelto', None, '50')

        # Ventas de hoy y de ayer.
        crear_venta('FA-2026-000001', [(self.crema, 2), (self.jabon, 1)])                 # 2200 hoy
        crear_venta('FA-2026-000002', [(self.jabon, 3)], hace_dias=1,
                    estado=Pedido.Estado.ENTREGADO, medio=Pedido.MedioPago.TRANSFERENCIA)  # 600 ayer
        # No cuentan: pendiente y cancelado.
        crear_venta('FA-2026-000003', [(self.crema, 5)], estado=Pedido.Estado.PENDIENTE_PAGO)
        crear_venta('FA-2026-000004', [(self.crema, 5)], estado=Pedido.Estado.CANCELADO)
        # Venta vieja (fuera de los últimos 7 días, dentro del período anterior).
        crear_venta('FA-2026-000005', [(self.sin_cat, 4)], hace_dias=10)                   # 200

    def test_kpis_solo_cuentan_estados_de_venta(self):
        k = services.kpis(services.filtro_ultimos_dias(7))
        self.assertEqual(k['monto'], Decimal('2800'))
        self.assertEqual(k['pedidos'], 2)
        self.assertEqual(k['unidades'], 6)
        self.assertEqual(k['ticket_promedio'], Decimal('1400.00'))
        # Período anterior (7 días antes): la venta de hace 10 días.
        self.assertEqual(k['monto_anterior'], Decimal('200'))
        self.assertEqual(k['variacion_pct'], 1300.0)

    def test_variacion_sin_base_es_none(self):
        # Rango sin ventas ni en el período ni en el anterior → no hay con qué comparar.
        hoy = timezone.localdate()
        filtro = services.FiltroVentas(desde=hoy - timedelta(days=40), hasta=hoy - timedelta(days=31))
        k = services.kpis(filtro)
        self.assertEqual(k['monto'], Decimal('0'))
        self.assertIsNone(k['variacion_pct'])

    def test_variacion_con_base_de_ayer(self):
        # Hoy 2200 vs. ayer 600 → +266.7 %
        k = services.kpis(services.filtro_ultimos_dias(1))
        self.assertEqual(k['monto_anterior'], Decimal('600'))
        self.assertAlmostEqual(k['variacion_pct'], 266.7, places=1)

    def test_ventas_por_producto_ordena_por_monto_y_calcula_porcentaje(self):
        filas = services.ventas_por_producto(services.filtro_ultimos_dias(7))
        self.assertEqual([f['nombre'] for f in filas], ['Crema solar', 'Jabon suave'])
        self.assertEqual(filas[0]['unidades'], 2)
        self.assertEqual(filas[0]['monto'], Decimal('2000'))
        self.assertAlmostEqual(filas[0]['porcentaje'], 71.4, places=1)
        self.assertEqual(filas[1]['unidades'], 4)

    def test_ventas_por_categoria_incluye_sin_categoria(self):
        filas = services.ventas_por_categoria(services.filtro_ultimos_dias(30))
        por_nombre = {f['categoria']: f for f in filas}
        self.assertEqual(por_nombre['Dermocosmética']['monto'], Decimal('2000'))
        self.assertEqual(por_nombre['Higiene']['monto'], Decimal('800'))
        self.assertEqual(por_nombre['Sin categoría']['monto'], Decimal('200'))

    def test_ventas_por_dia_rellena_dias_vacios(self):
        serie = services.ventas_por_dia(services.filtro_ultimos_dias(7))
        self.assertEqual(len(serie), 7)
        self.assertEqual(serie[-1]['monto'], 2200.0)  # hoy
        self.assertEqual(serie[-2]['monto'], 600.0)   # ayer
        self.assertEqual(serie[0]['monto'], 0.0)

    def test_ventas_por_medio_pago(self):
        filas = services.ventas_por_medio_pago(services.filtro_ultimos_dias(7))
        etiquetas = {f['etiqueta']: f for f in filas}
        self.assertEqual(etiquetas['Mercado Pago']['monto'], Decimal('2200'))
        self.assertEqual(etiquetas['Transferencia bancaria']['pedidos'], 1)

    def test_filtro_por_modo(self):
        f = services.filtro_ultimos_dias(7, modo=Pedido.Modo.ENCARGUE)
        self.assertEqual(services.kpis(f)['pedidos'], 0)

    def test_pendientes_atencion_y_stock_bajo(self):
        StockWeb.objects.create(producto=self.crema, cantidad=2)   # bajo
        StockWeb.objects.create(producto=self.jabon, cantidad=50)  # ok
        User.objects.create_user('x', 'x@test.com', CLAVE)
        PerfilStaff.objects.create(usuario=User.objects.get(username='x'))

        conteos = services.pendientes_atencion()
        self.assertEqual(conteos['por_preparar'], 2)          # confirmados: hoy y hace 10 días
        self.assertEqual(conteos['stock_bajo'], 1)
        self.assertEqual(conteos['solicitudes_personal'], 1)
        self.assertEqual(conteos['productos_sin_stock_web'], 1)  # 'Producto suelto'

    def test_datos_analitica_es_serializable(self):
        import json

        datos = services.datos_analitica(services.filtro_ultimos_dias(7))
        texto = json.dumps(datos)  # no debe fallar por Decimals/fechas
        self.assertIn('"por_producto"', texto)
        self.assertEqual(datos['kpis']['monto'], 2800.0)


class PanelVistasTests(TestCase):
    def setUp(self):
        self.duenio = User.objects.create_superuser('duenio', 'd@test.com', CLAVE)
        self.empleada = User.objects.create_user('emp', 'e@test.com', CLAVE)
        aprobar_solicitud(PerfilStaff.objects.create(usuario=self.empleada), self.duenio)
        self.cliente = User.objects.create_user('cli', 'c@test.com', CLAVE)
        cat = Categoria.objects.create(nombre='Higiene', slug='higiene')
        crear_venta('FA-2026-000010', [(crear_producto('Jabon', cat, '200'), 2)])

    def test_anonimo_redirige_al_login_del_panel(self):
        resp = self.client.get(reverse('admin:index'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('admin:login'), resp.url)

    def test_portada_muestra_dashboard_a_super(self):
        self.client.force_login(self.duenio)
        resp = self.client.get(reverse('admin:index'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Requiere atención')
        self.assertContains(resp, 'Solicitudes de personal')
        self.assertContains(resp, 'Últimos pedidos')
        self.assertContains(resp, 'FA-2026-000010')
        self.assertContains(resp, 'datos-analitica')
        self.assertContains(resp, 'Gestión')

    def test_portada_empleada_sin_tarjeta_de_solicitudes(self):
        self.client.force_login(self.empleada)
        resp = self.client.get(reverse('admin:index'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Transferencias por confirmar')
        self.assertNotContains(resp, 'Solicitudes de personal')

    def test_analitica_renderiza_con_filtros(self):
        self.client.force_login(self.duenio)
        resp = self.client.get(reverse('admin:panel_analitica'), {'dias': 30, 'modo': 'inmediato'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ventas por producto')
        self.assertContains(resp, 'Jabon')
        self.assertEqual(resp.context['filtro'].modo, 'inmediato')

    def test_analitica_filtros_invalidos_no_rompen(self):
        self.client.force_login(self.duenio)
        resp = self.client.get(
            reverse('admin:panel_analitica'),
            {'desde': 'x', 'hasta': '2026-99-99', 'dias': 'abc', 'sucursal': 'z', 'modo': 'raro'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['filtro'].dias, 30)

    def test_api_devuelve_json_a_staff(self):
        self.client.force_login(self.empleada)
        resp = self.client.get(reverse('admin:panel_api_analitica'), {'dias': 7})
        self.assertEqual(resp.status_code, 200)
        datos = resp.json()
        self.assertEqual(datos['rango']['dias'], 7)
        self.assertEqual(datos['kpis']['monto'], 400.0)
        self.assertEqual(datos['por_producto'][0]['nombre'], 'Jabon')

    def test_api_exige_staff(self):
        resp = self.client.get(reverse('admin:panel_api_analitica'))
        self.assertEqual(resp.status_code, 302)  # al login del panel
        self.client.force_login(self.cliente)
        resp = self.client.get(reverse('admin:panel_api_analitica'))
        self.assertEqual(resp.status_code, 302)

    def test_api_csv(self):
        self.client.force_login(self.duenio)
        resp = self.client.get(reverse('admin:panel_api_analitica'), {'dias': 7, 'formato': 'csv'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp['Content-Type'])
        contenido = resp.content.decode('utf-8')
        self.assertIn('Ventas por producto', contenido)
        self.assertIn('Jabon', contenido)
        self.assertIn('Ventas por categoría', contenido)

    def test_pedidos_changelist_muestra_badge_de_estado(self):
        self.client.force_login(self.empleada)
        resp = self.client.get(reverse('admin:pedidos_pedido_changelist'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'badge-estado--ok')
