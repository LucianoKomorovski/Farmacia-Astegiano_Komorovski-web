"""Tests de pagos con mock de Mercado Pago."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from catalogo.models import Categoria, Producto
from inventario.models import ReservaStock, StockWeb
from pagos.services import (
    PagoError,
    crear_preferencia_mp,
    procesar_notificacion_mp,
    validar_firma_webhook,
)
from pagos.models import Pago
from pedidos.models import LineaPedido, Pedido
from pedidos.services import PedidoError, confirmar_pedido


@override_settings(MERCADOPAGO_ACCESS_TOKEN='TEST-token', DEBUG=True, SITE_URL='')
class MercadoPagoMockTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        cat = Categoria.objects.create(nombre='T', slug='t')
        prod = Producto.objects.create(
            categoria=cat, nombre='P', slug='p', sku='P1',
            descripcion='', tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('100'), activo=True,
        )
        self.pedido = Pedido.objects.create(
            numero='FA-2026-000099',
            nombre_cliente='Test', email='t@test.com', telefono='1',
            estado=Pedido.Estado.PENDIENTE_PAGO,
            modo=Pedido.Modo.INMEDIATO,
            modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
            medio_pago=Pedido.MedioPago.MERCADOPAGO,
            subtotal=Decimal('100'), total=Decimal('100'),
        )
        LineaPedido.objects.create(
            pedido=self.pedido, producto=prod,
            nombre_snapshot='P', sku_snapshot='P1',
            cantidad=1, precio_unitario=Decimal('100'), subtotal=Decimal('100'),
        )
        self.producto = prod

    def _reserva_vigente(self) -> None:
        """Inmediato solo confirma si hay reserva ACTIVA con TTL vigente."""
        StockWeb.objects.get_or_create(producto=self.producto, defaults={'cantidad': 10})
        ReservaStock.objects.create(
            producto=self.producto,
            pedido=self.pedido,
            cantidad=1,
            estado=ReservaStock.Estado.ACTIVA,
            expires_at=timezone.now() + timedelta(hours=1),
        )

    @patch('pagos.services._sdk')
    def test_preferencia_local_sin_auto_return(self, mock_sdk_fn):
        mock_sdk = MagicMock()
        mock_sdk_fn.return_value = mock_sdk
        mock_sdk.preference.return_value.create.return_value = {
            'status': 201,
            'response': {
                'id': 'pref-1',
                'sandbox_init_point': 'https://sandbox.mp/test',
            },
        }
        request = self.factory.get('/')

        _, init_point = crear_preferencia_mp(request, self.pedido)

        preference_data = mock_sdk.preference.return_value.create.call_args[0][0]
        self.assertNotIn('auto_return', preference_data)
        self.assertNotIn('notification_url', preference_data)
        self.assertNotIn('back_urls', preference_data)
        self.assertEqual(init_point, 'https://sandbox.mp/test')

    @override_settings(SITE_URL='https://abc.ngrok-free.app')
    @patch('pagos.services._sdk')
    def test_preferencia_https_con_auto_return(self, mock_sdk_fn):
        mock_sdk = MagicMock()
        mock_sdk_fn.return_value = mock_sdk
        mock_sdk.preference.return_value.create.return_value = {
            'status': 201,
            'response': {
                'id': 'pref-2',
                'sandbox_init_point': 'https://sandbox.mp/test2',
            },
        }
        request = self.factory.get('/')

        crear_preferencia_mp(request, self.pedido)

        preference_data = mock_sdk.preference.return_value.create.call_args[0][0]
        self.assertEqual(preference_data.get('auto_return'), 'approved')
        self.assertIn('notification_url', preference_data)
        self.assertTrue(
            preference_data['back_urls']['success'].startswith('https://abc.ngrok-free.app')
        )

    @patch('pagos.services._sdk')
    def test_preferencia_error_mp_muestra_mensaje(self, mock_sdk_fn):
        mock_sdk = MagicMock()
        mock_sdk_fn.return_value = mock_sdk
        mock_sdk.preference.return_value.create.return_value = {
            'status': 400,
            'response': {
                'message': 'auto_return invalid. back_url.success must be defined',
                'error': 'invalid_auto_return',
            },
        }
        request = self.factory.get('/')

        with self.assertRaises(PagoError) as ctx:
            crear_preferencia_mp(request, self.pedido)
        self.assertIn('auto_return invalid', str(ctx.exception))

    @patch('pagos.services._sdk')
    def test_procesar_notificacion_aprobada(self, mock_sdk_fn):
        self._reserva_vigente()
        mock_sdk = MagicMock()
        mock_sdk_fn.return_value = mock_sdk
        mock_sdk.payment.return_value.get.return_value = {
            'status': 200,
            'response': {
                'status': 'approved',
                'external_reference': 'FA-2026-000099',
                'id': 12345,
                'transaction_amount': 100,
            },
        }

        procesar_notificacion_mp('12345')

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.CONFIRMADO)
        pago = Pago.objects.filter(pedido=self.pedido, estado=Pago.Estado.APROBADO).first()
        self.assertIsNotNone(pago)

    def test_webhook_sin_secret_acepta_en_debug(self):
        request = MagicMock()
        request.headers = {}
        request.GET = {}
        self.assertTrue(validar_firma_webhook(request))

    @override_settings(DEBUG=False, MERCADOPAGO_WEBHOOK_SECRET='')
    def test_webhook_sin_secret_rechaza_en_prod(self):
        request = MagicMock()
        request.headers = {}
        request.GET = {}
        self.assertFalse(validar_firma_webhook(request))

    @override_settings(MERCADOPAGO_ACCESS_TOKEN='')
    def test_sdk_sin_token_lanza_error(self):
        from pagos.services import _sdk
        with self.assertRaises(PagoError):
            _sdk()

    def _mock_pago_aprobado(self, mock_sdk_fn, payment_id, preference_id=''):
        mock_sdk = MagicMock()
        mock_sdk_fn.return_value = mock_sdk
        response = {
            'status': 'approved',
            'external_reference': self.pedido.numero,
            'id': payment_id,
            'transaction_amount': 100,
        }
        if preference_id:
            response['preference_id'] = preference_id
        mock_sdk.payment.return_value.get.return_value = {
            'status': 200,
            'response': response,
        }
        return mock_sdk

    @patch('pagos.services._sdk')
    def test_webhook_aprobado_pedido_cancelado_no_confirma(self, mock_sdk_fn):
        """MP llega tarde (TTL ya canceló): no confirmar, no 500, no Pago aprobado."""
        Pago.objects.create(
            pedido=self.pedido,
            medio=Pago.Medio.MERCADOPAGO,
            estado=Pago.Estado.PENDIENTE,
            monto=self.pedido.total,
            id_externo='pref-tarde',
        )
        self.pedido.estado = Pedido.Estado.CANCELADO
        self.pedido.save(update_fields=['estado'])
        self._mock_pago_aprobado(mock_sdk_fn, payment_id=555, preference_id='pref-tarde')

        try:
            procesar_notificacion_mp('555')
        except PedidoError as exc:
            self.fail(f'procesar_notificacion_mp no debe lanzar PedidoError: {exc}')

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.CANCELADO)
        self.assertEqual(
            Pago.objects.filter(pedido=self.pedido, estado=Pago.Estado.APROBADO).count(),
            0,
        )
        pago = Pago.objects.get(pedido=self.pedido)
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)
        self.assertTrue(pago.raw_payload.get('_webhook_tarde'))
        self.assertEqual(pago.raw_payload.get('_pedido_estado'), Pedido.Estado.CANCELADO)

    @patch('pagos.services._sdk')
    def test_doble_webhook_mismo_payment_id_un_solo_pago_aprobado(self, mock_sdk_fn):
        """Reintento de MP no crea un segundo Pago aprobado ni re-confirma el pedido."""
        self._reserva_vigente()
        Pago.objects.create(
            pedido=self.pedido,
            medio=Pago.Medio.MERCADOPAGO,
            estado=Pago.Estado.PENDIENTE,
            monto=self.pedido.total,
            id_externo='pref-dup',
        )
        self._mock_pago_aprobado(mock_sdk_fn, payment_id=12345, preference_id='pref-dup')

        procesar_notificacion_mp('12345')
        procesar_notificacion_mp('12345')

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.CONFIRMADO)
        self.assertEqual(Pago.objects.filter(pedido=self.pedido).count(), 1)
        self.assertEqual(
            Pago.objects.filter(pedido=self.pedido, estado=Pago.Estado.APROBADO).count(),
            1,
        )
        pago = Pago.objects.get(pedido=self.pedido)
        self.assertEqual(pago.id_externo, '12345')

    @patch('pagos.services._sdk')
    def test_inmediato_solo_reservas_expiradas_webhook_no_confirma(self, mock_sdk_fn):
        """INMEDIATO con reservas ya EXPIRADA: no queda confirmado sin consolidar stock."""
        producto = Producto.objects.get(sku='P1')
        stock = StockWeb.objects.create(producto=producto, cantidad=10)
        ReservaStock.objects.create(
            producto=producto,
            pedido=self.pedido,
            cantidad=1,
            estado=ReservaStock.Estado.EXPIRADA,
            expires_at=timezone.now() - timedelta(minutes=5),
        )
        self._mock_pago_aprobado(mock_sdk_fn, payment_id=777)

        with self.assertRaises(PedidoError):
            confirmar_pedido(self.pedido)

        try:
            procesar_notificacion_mp('777')
        except PedidoError as exc:
            self.fail(f'procesar_notificacion_mp no debe lanzar PedidoError: {exc}')

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PENDIENTE_PAGO)
        stock.refresh_from_db()
        self.assertEqual(stock.cantidad, 10)
        self.assertEqual(
            ReservaStock.objects.filter(
                pedido=self.pedido, estado=ReservaStock.Estado.CONSOLIDADA,
            ).count(),
            0,
        )
        self.assertEqual(
            Pago.objects.filter(pedido=self.pedido, estado=Pago.Estado.APROBADO).count(),
            0,
        )
        pago = Pago.objects.filter(pedido=self.pedido).first()
        self.assertIsNotNone(pago)
        self.assertTrue(pago.raw_payload.get('_webhook_tarde'))
