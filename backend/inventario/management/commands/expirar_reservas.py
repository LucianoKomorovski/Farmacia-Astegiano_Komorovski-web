from django.core.management.base import BaseCommand

from inventario.services import expirar_reservas_vencidas


class Command(BaseCommand):
    help = 'Expira reservas de stock vencidas y cancela pedidos sin pago (cron cada ~15 min).'

    def handle(self, *args, **options):
        cancelados = expirar_reservas_vencidas()
        self.stdout.write(self.style.SUCCESS(f'Pedidos cancelados por TTL: {cancelados}'))
