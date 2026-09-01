from datetime import time

from django.db import migrations


def crear_franjas(apps, schema_editor):
    FranjaEnvio = apps.get_model('pedidos', 'FranjaEnvio')
    FranjaEnvio.objects.bulk_create([
        FranjaEnvio(
            nombre='Mañana',
            hora_desde=time(9, 0),
            hora_hasta=time(13, 0),
            activa=True,
            orden=1,
        ),
        FranjaEnvio(
            nombre='Tarde',
            hora_desde=time(14, 0),
            hora_hasta=time(18, 0),
            activa=True,
            orden=2,
        ),
    ])


def borrar_franjas(apps, schema_editor):
    FranjaEnvio = apps.get_model('pedidos', 'FranjaEnvio')
    FranjaEnvio.objects.filter(nombre__in=['Mañana', 'Tarde']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('pedidos', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crear_franjas, borrar_franjas),
    ]
