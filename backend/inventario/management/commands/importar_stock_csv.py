"""Importa stock web desde un archivo CSV exportado de Praxys (o manual).

Columnas esperadas (encabezado):
    sku,codigo_barras,codigo_praxys,stock_praxys,margen_seguridad,tope_web

Al menos una columna identificadora (sku, codigo_barras o codigo_praxys) por fila.

Uso:
    python manage.py importar_stock_csv ruta/al/archivo.csv
"""

from django.core.management.base import BaseCommand, CommandError

from inventario.importador import importar_stock_csv


class Command(BaseCommand):
    help = 'Importa stock web desde CSV (cruce por sku/barras/praxys)'

    def add_arguments(self, parser):
        parser.add_argument('archivo', help='Ruta al archivo .csv')

    def handle(self, *args, **options):
        try:
            log, resultado = importar_stock_csv(options['archivo'])
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc

        if log.ok:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Importación OK: {resultado.actualizados} productos actualizados, '
                    f'{resultado.omitidos} omitidos.'
                )
            )
        else:
            self.stdout.write(self.style.ERROR(f'Importación con errores (log #{log.pk}):'))
            self.stdout.write(log.detalle)
            raise CommandError('Revisá el detalle en admin → Importaciones de stock.')
