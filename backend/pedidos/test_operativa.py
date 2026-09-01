"""Tests de notificaciones y costo de envío."""

from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings

from pedidos.models import FranjaEnvio, Pedido
from pedidos.notifications import enviar_email_cambio_estado, url_whatsapp_pedido
from pedidos.services import calcular_costo_envio


@override_settings(
    ENVIO_MONTO_FIJO=Decimal('1500'),
    ENVIO_GRATIS_DESDE=Decimal('10000'),
    WHATSAPP_TIENDA='5493471543210',
)
class OperativaTests(TestCase):
    def test_costo_envio_gratis_desde_umbral(self):
        self.assertEqual(
            calcular_costo_envio(Decimal('5000'), Pedido.ModalidadEntrega.ENVIO),
            Decimal('1500'),
        )
        self.assertEqual(
            calcular_costo_envio(Decimal('12000'), Pedido.ModalidadEntrega.ENVIO),
            Decimal('0'),
        )
        self.assertEqual(
            calcular_costo_envio(Decimal('5000'), Pedido.ModalidadEntrega.A_COORDINAR),
            Decimal('0'),
        )

    def test_whatsapp_url(self):
        pedido = Pedido(
            numero='FA-2026-000001',
            estado=Pedido.Estado.CONFIRMADO,
        )
        url = url_whatsapp_pedido(pedido)
        self.assertIn('wa.me/5493471543210', url)
        self.assertIn('FA-2026-000001', url)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_al_confirmar(self):
        pedido = Pedido.objects.create(
            numero='FA-2026-000010',
            nombre_cliente='Ana', email='ana@test.com', telefono='1',
            estado=Pedido.Estado.CONFIRMADO,
            modo=Pedido.Modo.INMEDIATO,
            modalidad_entrega=Pedido.ModalidadEntrega.A_COORDINAR,
            medio_pago=Pedido.MedioPago.MERCADOPAGO,
            subtotal=Decimal('100'), total=Decimal('100'),
        )
        enviar_email_cambio_estado(pedido, Pedido.Estado.PENDIENTE_PAGO)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('FA-2026-000010', mail.outbox[0].subject)


class FranjaCupoTests(TestCase):
    def test_cupo_max(self):
        franja = FranjaEnvio.objects.create(
            nombre='Mañana', hora_desde='09:00', hora_hasta='13:00', cupo_max=1,
        )
        from django.utils import timezone

        fecha = timezone.localdate()
        self.assertTrue(franja.tiene_cupo(fecha))

        Pedido.objects.create(
            numero='FA-2026-000020',
            nombre_cliente='B', email='b@t.com', telefono='1',
            estado=Pedido.Estado.CONFIRMADO,
            modo=Pedido.Modo.INMEDIATO,
            modalidad_entrega=Pedido.ModalidadEntrega.ENVIO,
            franja_envio=franja,
            fecha_entrega=fecha,
            medio_pago=Pedido.MedioPago.MERCADOPAGO,
            subtotal=Decimal('50'), total=Decimal('50'),
        )
        self.assertFalse(franja.tiene_cupo(fecha))
        self.assertEqual(franja.cupo_restante(fecha), 0)
