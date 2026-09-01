"""Simula pago MP aprobado en desarrollo (sin webhook ni credenciales reales).

Uso:
    python manage.py simular_pago FA-2026-000001

Solo funciona con DEBUG=True.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from pagos.models import Pago
from pedidos.models import Pedido
from pedidos.services import confirmar_pedido


class Command(BaseCommand):
    help = 'Simula un pago MP aprobado (solo DEBUG, para pruebas locales)'

    def add_arguments(self, parser):
        parser.add_argument('numero', help='Número de pedido, ej. FA-2026-000001')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Este comando solo está disponible con DEBUG=True.')

        numero = options['numero']
        try:
            pedido = Pedido.objects.get(numero=numero)
        except Pedido.DoesNotExist as exc:
            raise CommandError(f'Pedido no encontrado: {numero}') from exc

        if not pedido.puede_pagar_online:
            raise CommandError(
                f'El pedido {numero} no está pendiente de pago (estado: {pedido.estado}).'
            )

        pago, _ = Pago.objects.get_or_create(
            pedido=pedido,
            estado=Pago.Estado.PENDIENTE,
            defaults={
                'medio': pedido.medio_pago,
                'monto': pedido.total,
                'id_externo': f'sim-{numero}',
            },
        )
        pago.estado = Pago.Estado.APROBADO
        pago.confirmado_en = timezone.now()
        pago.raw_payload = {'simulado': True, 'status': 'approved'}
        pago.save()

        confirmar_pedido(pedido, via_pago=pago)
        self.stdout.write(
            self.style.SUCCESS(f'Pedido {numero} confirmado (pago simulado).')
        )
