"""Tests de pagos con mock de Mercado Pago."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase, override_settings

from catalogo.models import Categoria, Producto
from pagos.services import (
    PagoError,
    crear_preferencia_mp,
    procesar_notificacion_mp,
    validar_firma_webhook,
)
from pagos.models import Pago
from pedidos.models import LineaPedido, Pedido


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
