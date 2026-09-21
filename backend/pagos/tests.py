"""Tests de pagos con mock de Mercado Pago."""

import hashlib
import hmac
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from catalogo.models import Categoria, Producto
from inventario.models import ReservaStock, StockWeb
from pagos.services import (
    PagoError,
    confirmar_transferencia,
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
        """MP llega tarde (TTL ya canceló): no confirmar, no 500; se registra el cobro."""
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
        self.assertFalse(self.pedido.puede_pagar_online)
        pago = Pago.objects.get(pedido=self.pedido)
        # El dinero llegó: staff ve APROBADO + _webhook_tarde para reembolsar.
        self.assertEqual(pago.estado, Pago.Estado.APROBADO)
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
        """INMEDIATO con reservas EXPIRADA: no confirma, no queda pagable, no 500."""
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
        # Si queda PENDIENTE_PAGO, la UI ofrece pagos_iniciar → segundo cobro.
        self.assertFalse(self.pedido.puede_pagar_online)
        self.assertEqual(self.pedido.estado, Pedido.Estado.CANCELADO)
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
            1,
        )
        pago = Pago.objects.get(pedido=self.pedido)
        self.assertTrue(pago.raw_payload.get('_webhook_tarde'))
        self.assertEqual(pago.raw_payload.get('_pedido_estado'), Pedido.Estado.PENDIENTE_PAGO)

        request = self.factory.get('/')
        with self.assertRaises(PagoError):
            crear_preferencia_mp(request, self.pedido)

        # Reintento del mismo payment_id: un solo APROBADO, no cancela dos veces.
        procesar_notificacion_mp('777')
        self.assertEqual(
            Pago.objects.filter(pedido=self.pedido, estado=Pago.Estado.APROBADO).count(),
            1,
        )
        self.assertEqual(
            self.pedido.eventos.filter(estado_nuevo=Pedido.Estado.CANCELADO).count(),
            1,
        )

    @patch('pagos.services._sdk')
    def test_reintentar_preferencia_reusa_la_misma(self, mock_sdk_fn):
        """Dos clics en Pagar no deben abrir dos Checkout Pro cobrables."""
        mock_sdk = MagicMock()
        mock_sdk_fn.return_value = mock_sdk
        mock_sdk.preference.return_value.create.return_value = {
            'status': 201,
            'response': {
                'id': 'pref-unica',
                'sandbox_init_point': 'https://sandbox.mp/unica',
            },
        }
        request = self.factory.get('/')

        pago1, url1 = crear_preferencia_mp(request, self.pedido)
        pago2, url2 = crear_preferencia_mp(request, self.pedido)

        self.assertEqual(pago1.pk, pago2.pk)
        self.assertEqual(url1, url2)
        self.assertEqual(url1, 'https://sandbox.mp/unica')
        self.assertEqual(mock_sdk.preference.return_value.create.call_count, 1)
        self.assertEqual(Pago.objects.filter(pedido=self.pedido).count(), 1)

    def _crear_preferencia_mock(self, mock_sdk_fn, pref_id='pref-unica', url='https://sandbox.mp/unica'):
        mock_sdk = MagicMock()
        mock_sdk_fn.return_value = mock_sdk
        mock_sdk.preference.return_value.create.return_value = {
            'status': 201,
            'response': {
                'id': pref_id,
                'sandbox_init_point': url,
            },
        }
        return mock_sdk

    def _mock_payment_get(self, mock_sdk, status, payment_id, preference_id):
        mock_sdk.payment.return_value.get.return_value = {
            'status': 200,
            'response': {
                'status': status,
                'external_reference': self.pedido.numero,
                'id': payment_id,
                'preference_id': preference_id,
                'transaction_amount': 100,
            },
        }

    def _assert_reusa_tras_webhook(self, mock_sdk, pago, url, payment_id, pref_id):
        """Pagar de nuevo no debe abrir otra preference cobrable en MP."""
        pago.refresh_from_db()
        self.assertEqual(pago.raw_payload.get('id'), payment_id)
        self.assertNotIn('sandbox_init_point', pago.raw_payload)
        self.assertEqual(pago.raw_payload.get('_mp_preference_id'), pref_id)
        self.assertEqual(pago.raw_payload.get('_mp_sandbox_init_point'), url)
        self.assertEqual(pago.id_externo, str(payment_id))

        request = self.factory.get('/')
        pago2, url2 = crear_preferencia_mp(request, self.pedido)
        self.assertEqual(pago2.pk, pago.pk)
        self.assertEqual(url2, url)
        self.assertEqual(mock_sdk.preference.return_value.create.call_count, 1)
        self.assertEqual(Pago.objects.filter(pedido=self.pedido).count(), 1)

    @patch('pagos.services._sdk')
    def test_webhook_pendiente_reusa_la_misma_preferencia(self, mock_sdk_fn):
        """pending pisa raw_payload; Pagar otra vez debe reusar el init_point."""
        url = 'https://sandbox.mp/unica'
        pref_id = 'pref-unica'
        mock_sdk = self._crear_preferencia_mock(mock_sdk_fn, pref_id, url)
        request = self.factory.get('/')
        pago, init_point = crear_preferencia_mp(request, self.pedido)
        self.assertEqual(init_point, url)
        self.assertEqual(pago.raw_payload.get('_mp_preference_id'), pref_id)
        self.assertEqual(pago.raw_payload.get('_mp_sandbox_init_point'), url)

        self._mock_payment_get(mock_sdk, 'pending', 9001, pref_id)
        procesar_notificacion_mp('9001')
        self._assert_reusa_tras_webhook(mock_sdk, pago, url, 9001, pref_id)

    @patch('pagos.services._sdk')
    def test_webhook_in_process_reusa_la_misma_preferencia(self, mock_sdk_fn):
        url = 'https://sandbox.mp/unica'
        pref_id = 'pref-unica'
        mock_sdk = self._crear_preferencia_mock(mock_sdk_fn, pref_id, url)
        request = self.factory.get('/')
        pago, _ = crear_preferencia_mp(request, self.pedido)

        self._mock_payment_get(mock_sdk, 'in_process', 9002, pref_id)
        procesar_notificacion_mp('9002')
        self._assert_reusa_tras_webhook(mock_sdk, pago, url, 9002, pref_id)

    @patch('pagos.services._sdk')
    def test_webhook_rechazado_reusa_la_misma_preferencia(self, mock_sdk_fn):
        """rejected también pisa el payload; no crear un 2º Checkout Pro vivo."""
        url = 'https://sandbox.mp/unica'
        pref_id = 'pref-unica'
        mock_sdk = self._crear_preferencia_mock(mock_sdk_fn, pref_id, url)
        request = self.factory.get('/')
        pago, _ = crear_preferencia_mp(request, self.pedido)

        self._mock_payment_get(mock_sdk, 'rejected', 9003, pref_id)
        procesar_notificacion_mp('9003')
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.RECHAZADO)
        self._assert_reusa_tras_webhook(mock_sdk, pago, url, 9003, pref_id)

    @patch('pagos.services._sdk')
    def test_rechazado_no_pisa_pago_ya_aprobado(self, mock_sdk_fn):
        """Misma preference: approved + rejected tardío no degrada el cobro."""
        self._reserva_vigente()
        Pago.objects.create(
            pedido=self.pedido,
            medio=Pago.Medio.MERCADOPAGO,
            estado=Pago.Estado.PENDIENTE,
            monto=self.pedido.total,
            id_externo='pref-1',
        )
        self._mock_pago_aprobado(mock_sdk_fn, payment_id=222, preference_id='pref-1')
        procesar_notificacion_mp('222')

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.CONFIRMADO)

        mock_sdk_fn.return_value.payment.return_value.get.return_value = {
            'status': 200,
            'response': {
                'status': 'rejected',
                'external_reference': self.pedido.numero,
                'id': 111,
                'preference_id': 'pref-1',
                'transaction_amount': 100,
            },
        }
        procesar_notificacion_mp('111')

        self.assertEqual(
            Pago.objects.filter(pedido=self.pedido, estado=Pago.Estado.APROBADO).count(),
            1,
        )
        pago = Pago.objects.get(pedido=self.pedido, estado=Pago.Estado.APROBADO)
        self.assertEqual(pago.id_externo, '222')
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.CONFIRMADO)

    @patch('pagos.services._sdk')
    def test_segundo_payment_approved_en_confirmado_se_flaggea(self, mock_sdk_fn):
        """Dos preferences cobradas: el pedido no se reconfirma; se marca duplicado."""
        self._reserva_vigente()
        Pago.objects.create(
            pedido=self.pedido,
            medio=Pago.Medio.MERCADOPAGO,
            estado=Pago.Estado.PENDIENTE,
            monto=self.pedido.total,
            id_externo='pref-a',
        )
        Pago.objects.create(
            pedido=self.pedido,
            medio=Pago.Medio.MERCADOPAGO,
            estado=Pago.Estado.PENDIENTE,
            monto=self.pedido.total,
            id_externo='pref-b',
        )
        self._mock_pago_aprobado(mock_sdk_fn, payment_id=1001, preference_id='pref-a')
        procesar_notificacion_mp('1001')

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.CONFIRMADO)
        stock = StockWeb.objects.get(producto=self.producto)
        self.assertEqual(stock.cantidad, 9)

        self._mock_pago_aprobado(mock_sdk_fn, payment_id=1002, preference_id='pref-b')
        procesar_notificacion_mp('1002')

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.CONFIRMADO)
        stock.refresh_from_db()
        self.assertEqual(stock.cantidad, 9)
        self.assertEqual(
            Pago.objects.filter(pedido=self.pedido, estado=Pago.Estado.APROBADO).count(),
            2,
        )
        duplicado = Pago.objects.get(pedido=self.pedido, id_externo='1002')
        self.assertTrue(duplicado.raw_payload.get('_cobro_duplicado'))
        original = Pago.objects.get(pedido=self.pedido, id_externo='1001')
        self.assertFalse(original.raw_payload.get('_cobro_duplicado'))

    @override_settings(MERCADOPAGO_WEBHOOK_SECRET='s3cret', DEBUG=False)
    def test_webhook_hmac_acepta_firma_valida_con_espacios(self):
        data_id = '12345'
        request_id = 'req-1'
        ts = '1704908010'
        manifest = f'id:{data_id};request-id:{request_id};ts:{ts};'
        digest = hmac.new(b's3cret', manifest.encode(), hashlib.sha256).hexdigest()
        request = MagicMock()
        request.headers = {
            'x-signature': f'ts={ts}, v1={digest}',
            'x-request-id': request_id,
        }
        request.GET = {'data.id': data_id}
        self.assertTrue(validar_firma_webhook(request))

    @override_settings(MERCADOPAGO_WEBHOOK_SECRET='s3cret', DEBUG=False)
    def test_webhook_hmac_sin_firma_devuelve_false(self):
        request = MagicMock()
        request.headers = {}
        request.GET = {}
        self.assertFalse(validar_firma_webhook(request))

    @patch('pagos.services._sdk')
    def test_webhook_http_reserva_expirada_devuelve_200(self, mock_sdk_fn):
        """La vista del webhook no debe 500 si no se puede confirmar."""
        from pagos.views import webhook_mp

        StockWeb.objects.create(producto=self.producto, cantidad=10)
        ReservaStock.objects.create(
            producto=self.producto,
            pedido=self.pedido,
            cantidad=1,
            estado=ReservaStock.Estado.EXPIRADA,
            expires_at=timezone.now() - timedelta(minutes=5),
        )
        self._mock_pago_aprobado(mock_sdk_fn, payment_id=888)

        request = self.factory.post(
            '/pagos/webhook/?topic=payment&data.id=888',
            data=b'{"type":"payment","data":{"id":"888"}}',
            content_type='application/json',
        )
        resp = webhook_mp(request)
        self.assertEqual(resp.status_code, 200)
        self.pedido.refresh_from_db()
        self.assertFalse(self.pedido.puede_pagar_online)


class TransferenciaConfirmTests(TestCase):
    """Staff confirma transferencia: si consolidar falla, el Pago no queda APROBADO."""

    def setUp(self):
        cat = Categoria.objects.create(nombre='T', slug='t')
        prod = Producto.objects.create(
            categoria=cat, nombre='P', slug='p-tr', sku='PTR1',
            descripcion='', tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('100'), activo=True,
        )
        StockWeb.objects.create(producto=prod, cantidad=10)
        self.staff = User.objects.create_user(
            'staff', 'staff@test.com', 'x12345678', is_staff=True,
        )
        self.pedido = Pedido.objects.create(
            numero='FA-2026-000098',
            nombre_cliente='Test', email='t@test.com', telefono='1',
            estado=Pedido.Estado.PENDIENTE_TRANSFERENCIA,
            modo=Pedido.Modo.INMEDIATO,
            modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
            medio_pago=Pedido.MedioPago.TRANSFERENCIA,
            subtotal=Decimal('100'), total=Decimal('100'),
        )
        LineaPedido.objects.create(
            pedido=self.pedido, producto=prod,
            nombre_snapshot='P', sku_snapshot='PTR1',
            cantidad=1, precio_unitario=Decimal('100'), subtotal=Decimal('100'),
        )
        ReservaStock.objects.create(
            producto=prod,
            pedido=self.pedido,
            cantidad=1,
            estado=ReservaStock.Estado.EXPIRADA,
            expires_at=timezone.now() - timedelta(minutes=5),
        )
        Pago.objects.create(
            pedido=self.pedido,
            medio=Pago.Medio.TRANSFERENCIA,
            estado=Pago.Estado.PENDIENTE,
            monto=self.pedido.total,
        )

    def test_reserva_expirada_revierte_pago_y_no_duplica_en_reintento(self):
        with self.assertRaises(PedidoError):
            confirmar_transferencia(self.pedido, self.staff)

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PENDIENTE_TRANSFERENCIA)
        self.assertEqual(
            Pago.objects.filter(pedido=self.pedido, estado=Pago.Estado.APROBADO).count(),
            0,
        )

        with self.assertRaises(PedidoError):
            confirmar_transferencia(self.pedido, self.staff)

        self.assertEqual(
            Pago.objects.filter(pedido=self.pedido, estado=Pago.Estado.APROBADO).count(),
            0,
        )
        self.assertEqual(Pago.objects.filter(pedido=self.pedido).count(), 1)
