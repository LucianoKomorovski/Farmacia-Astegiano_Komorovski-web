"""Carga datos iniciales para desarrollo local.

Uso (desde la carpeta backend, con el venv activo):
    python manage.py seed_datos

Es idempotente: si ya existen las sucursales, no duplica.

Usuario staff (solo con DEBUG=True; no hay contraseña por defecto):
    # Opción 1: variable de entorno local (no la subas al repo)
    SEED_STAFF_PASSWORD='elegí-una-propia' python manage.py seed_datos
    # Opción 2: argumento (visible en el historial de la terminal)
    python manage.py seed_datos --staff-password 'elegí-una-propia'
    # Opción 3: en una terminal interactiva, el comando pide la contraseña
    # Opción 4: crear el superusuario a mano
    python manage.py createsuperuser

Con DEBUG=False no se crea ni actualiza ese usuario (no-op).

Alternativa desde fixture versionada (misma data de ejemplo):
    python manage.py loaddata datos_iniciales
"""

from __future__ import annotations

import getpass
import os
import sys
from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from aboutUs.models import SobreNosotros
from catalogo.models import Categoria, Producto
from core.models import Banner
from inventario.models import StockWeb
from pedidos.models import FranjaEnvio
from servicios.models import Servicio
from sucursales.models import Sucursal
from turnos.models import Farmacia, Turno

User = get_user_model()


class Command(BaseCommand):
    help = 'Carga sucursales, servicios, farmacias de turno, tienda de ejemplo y usuario staff'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--staff-username',
            default=os.environ.get('SEED_STAFF_USERNAME', 'staff'),
            help='Usuario staff de sandbox (también SEED_STAFF_USERNAME).',
        )
        parser.add_argument(
            '--staff-password',
            default='',
            help=(
                'Contraseña del staff. Si se omite, usa SEED_STAFF_PASSWORD; '
                'si tampoco está, pide por consola o no crea el usuario.'
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        self._seed_sucursales()
        self._seed_farmacias_turno()
        self._seed_servicios()
        self._seed_turnos()
        self._seed_sobre_nosotros()
        self._seed_tienda()
        self._seed_staff(
            username=str(options.get('staff_username') or 'staff'),
            password=str(options.get('staff_password') or ''),
        )
        self.stdout.write(self.style.SUCCESS('Datos iniciales listos.'))

    def _seed_sucursales(self) -> None:
        datos = [
            {
                'nombre': 'Farmacia Astegiano',
                'descripcion': (
                    'Atención personalizada en el centro de Las Parejas. '
                    'Medicamentos, dermocosmética y consejos de salud.'
                ),
                'direccion': 'San Martín 850, Las Parejas, Santa Fe',
                'link_google_maps': 'https://maps.google.com/?q=San+Martin+850+Las+Parejas',
                'telefono_fijo': '03471421234',
                'numero_whatsapp': '5493471543210',
                'horarios_atencion': 'Lun a Vie 8:00–20:00 · Sáb 8:00–13:00',
            },
            {
                'nombre': 'Farmacia Komorovski',
                'descripcion': (
                    'Tu farmacia de confianza en Las Parejas. '
                    'Amplio stock, obras sociales y atención cercana.'
                ),
                'direccion': 'Belgrano 420, Las Parejas, Santa Fe',
                'link_google_maps': 'https://maps.google.com/?q=Belgrano+420+Las+Parejas',
                'telefono_fijo': '03471425678',
                'numero_whatsapp': '5493471654321',
                'horarios_atencion': 'Lun a Vie 8:30–20:30 · Sáb 8:30–13:30',
            },
        ]

        for item in datos:
            obj, created = Sucursal.objects.update_or_create(
                nombre=item['nombre'],
                defaults=item,
            )
            estado = 'creada' if created else 'actualizada'
            self.stdout.write(f'  Sucursal {estado}: {obj.nombre}')

    def _seed_farmacias_turno(self) -> None:
        """Farmacias del calendario de turnos (propias + algunas del pueblo)."""
        propias = [
            ('Farmacia Astegiano', 'San Martín 850', 'Farmacia Astegiano'),
            ('Farmacia Komorovski', 'Belgrano 420', 'Farmacia Komorovski'),
        ]
        for nombre, direccion, nombre_sucursal in propias:
            sucursal = Sucursal.objects.get(nombre=nombre_sucursal)
            obj, created = Farmacia.objects.update_or_create(
                nombre=nombre,
                defaults={'direccion': direccion, 'sucursal': sucursal},
            )
            estado = 'creada' if created else 'actualizada'
            self.stdout.write(f'  Farmacia {estado}: {obj.nombre} (propia)')

        # Otras farmacias del pueblo para completar la rotación de turnos
        ajenas = [
            ('Farmacia del Pueblo', 'Avenida 18 758'),
            ('Farmacia Central', 'Mitre 210'),
        ]
        for nombre, direccion in ajenas:
            obj, created = Farmacia.objects.update_or_create(
                nombre=nombre,
                defaults={'direccion': direccion, 'sucursal': None},
            )
            estado = 'creada' if created else 'actualizada'
            self.stdout.write(f'  Farmacia {estado}: {obj.nombre}')

    def _seed_servicios(self) -> None:
        servicios = [
            {
                'titulo': 'Inyectables',
                'descripcion': 'Aplicación de inyecciones con profesional de la salud.',
                'icono': 'bi bi-droplet-half',
            },
            {
                'titulo': 'Toma de presión',
                'descripcion': 'Control de presión arterial sin turno previo.',
                'icono': 'bi bi-heart-pulse',
            },
            {
                'titulo': 'Dermocosmética',
                'descripcion': 'Asesoramiento en cuidado de la piel y productos de farmacia.',
                'icono': 'bi bi-flower1',
            },
            {
                'titulo': 'Obras sociales',
                'descripcion': 'Atención con las principales obras sociales y prepagas.',
                'icono': 'bi bi-card-checklist',
            },
        ]
        sucursales = list(Sucursal.objects.all())
        for item in servicios:
            obj, created = Servicio.objects.update_or_create(
                titulo=item['titulo'],
                defaults={
                    'descripcion': item['descripcion'],
                    'icono': item['icono'],
                },
            )
            obj.sucursales_disponibles.set(sucursales)
            estado = 'creado' if created else 'actualizado'
            self.stdout.write(f'  Servicio {estado}: {obj.titulo}')

    def _seed_turnos(self) -> None:
        """Asigna turnos para los próximos 7 días (rotación simple)."""
        farmacias = list(Farmacia.objects.order_by('id'))
        if not farmacias:
            self.stdout.write(self.style.WARNING('  Sin farmacias: no se crean turnos.'))
            return

        hoy = timezone.localdate()
        for i in range(7):
            fecha = hoy + timedelta(days=i)
            farmacia = farmacias[i % len(farmacias)]
            obj, created = Turno.objects.update_or_create(
                fecha=fecha,
                defaults={'farmacia': farmacia},
            )
            estado = 'creado' if created else 'actualizado'
            self.stdout.write(f'  Turno {estado}: {obj.fecha} → {farmacia.nombre}')

    def _seed_sobre_nosotros(self) -> None:
        obj, created = SobreNosotros.objects.update_or_create(
            titulo='Una historia familiar en Las Parejas',
            defaults={
                'descripcion': (
                    'Farmacia Astegiano y Farmacia Komorovski son dos sucursales '
                    'unidas por el mismo compromiso: acompañar a las familias de '
                    'Las Parejas con atención cercana, stock confiable y turnos '
                    'rotativos para que siempre haya una farmacia disponible.'
                ),
            },
        )
        estado = 'creado' if created else 'actualizado'
        self.stdout.write(f'  Sobre Nosotros {estado}: {obj.titulo}')
        self.stdout.write(
            self.style.NOTICE(
                '  Tip: podés subir la imagen desde el admin cuando quieras.'
            )
        )

    def _seed_tienda(self) -> None:
        """Catálogo, stock y franjas para probar checkout local."""
        # Categorías con ícono (Bootstrap Icons) para los chips de la portada.
        cat, _ = Categoria.objects.update_or_create(
            slug='dermocosmetica',
            defaults={'nombre': 'Dermocosmética', 'activa': True, 'orden': 1, 'icono': 'bi bi-droplet'},
        )
        cat_hig, _ = Categoria.objects.update_or_create(
            slug='higiene',
            defaults={'nombre': 'Higiene', 'activa': True, 'orden': 2, 'icono': 'bi bi-water'},
        )
        cat_sol, _ = Categoria.objects.update_or_create(
            slug='solares',
            defaults={'nombre': 'Solares', 'activa': True, 'orden': 3, 'icono': 'bi bi-sun'},
        )
        cat_sup, _ = Categoria.objects.update_or_create(
            slug='suplementos',
            defaults={'nombre': 'Suplementos', 'activa': True, 'orden': 4, 'icono': 'bi bi-capsule'},
        )
        cat_bebe, _ = Categoria.objects.update_or_create(
            slug='bebes',
            defaults={'nombre': 'Bebés', 'activa': True, 'orden': 5, 'icono': 'bi bi-balloon-heart'},
        )

        productos = [
            {
                'sku': 'DERM-001',
                'nombre': 'Protector solar FPS 50',
                'slug': 'protector-solar-fps-50',
                'categoria': cat_sol,
                'tipo': Producto.Tipo.INMEDIATO,
                'precio': Decimal('8500.00'),
                'precio_anterior': Decimal('11200.00'),  # → sale como oferta (-24%)
                'destacado': True,
                'codigo_barras': '7790001001001',
                'stock': 25,
            },
            {
                'sku': 'DERM-002',
                'nombre': 'Crema hidratante facial',
                'slug': 'crema-hidratante-facial',
                'categoria': cat,
                'tipo': Producto.Tipo.INMEDIATO,
                'precio': Decimal('6200.00'),
                'precio_anterior': None,
                'destacado': True,
                'codigo_barras': '7790001001002',
                'stock': 15,
            },
            {
                'sku': 'HIG-001',
                'nombre': 'Jabón líquido antibacterial',
                'slug': 'jabon-liquido-antibacterial',
                'categoria': cat_hig,
                'tipo': Producto.Tipo.INMEDIATO,
                'precio': Decimal('2800.00'),
                'precio_anterior': Decimal('3500.00'),  # → oferta (-20%)
                'destacado': False,
                'codigo_barras': '7790001001003',
                'stock': 40,
            },
            {
                'sku': 'ENC-001',
                'nombre': 'Suplemento vitamina D (encargue)',
                'slug': 'suplemento-vitamina-d',
                'categoria': cat_sup,
                'tipo': Producto.Tipo.ENCARGUE,
                'precio': Decimal('4500.00'),
                'precio_anterior': None,
                'destacado': True,
                'codigo_praxys': 'PRX-99001',
                'stock': 0,
            },
            {
                'sku': 'BEBE-001',
                'nombre': 'Óleo calcáreo 200 ml',
                'slug': 'oleo-calcareo-200',
                'categoria': cat_bebe,
                'tipo': Producto.Tipo.INMEDIATO,
                'precio': Decimal('3900.00'),
                'precio_anterior': None,
                'destacado': True,
                'codigo_barras': '7790001001005',
                'stock': 12,
            },
        ]

        for item in productos:
            stock_qty = item.pop('stock', 0)
            prod, created = Producto.objects.update_or_create(
                sku=item['sku'],
                defaults={k: v for k, v in item.items() if k != 'sku'},
            )
            if prod.tipo == Producto.Tipo.INMEDIATO:
                StockWeb.objects.update_or_create(
                    producto=prod,
                    defaults={'cantidad': stock_qty, 'origen': StockWeb.Origen.MANUAL},
                )
            estado = 'creado' if created else 'actualizado'
            self.stdout.write(f'  Producto {estado}: {prod.nombre}')

        franjas = [
            {'nombre': 'Mañana', 'hora_desde': time(9, 0), 'hora_hasta': time(13, 0), 'orden': 1},
            {'nombre': 'Tarde', 'hora_desde': time(16, 0), 'hora_hasta': time(20, 0), 'orden': 2},
        ]
        for f in franjas:
            obj, created = FranjaEnvio.objects.update_or_create(
                nombre=f['nombre'],
                defaults=f,
            )
            estado = 'creada' if created else 'actualizada'
            self.stdout.write(f'  Franja {estado}: {obj.nombre}')

        # Banners de portada sin imagen: se dibujan con el fondo de marca.
        banners = [
            {
                'titulo': 'Tu farmacia de Las Parejas, ahora online',
                'subtitulo': 'Comprá desde casa y retirá gratis en Astegiano o Komorovski, o recibilo en tu domicilio.',
                'link': '/tienda/',
                'texto_boton': 'Ver la tienda',
                'orden': 1,
            },
            {
                'titulo': 'Ofertas de la semana en solares e higiene',
                'subtitulo': 'Descuentos reales, sin letra chica. Pagá con Mercado Pago o transferencia.',
                'link': '/tienda/?oferta=1',
                'texto_boton': 'Ver ofertas',
                'orden': 2,
            },
        ]
        for b in banners:
            obj, created = Banner.objects.update_or_create(
                titulo=b['titulo'],
                defaults={**b, 'activo': True},
            )
            estado = 'creado' if created else 'actualizado'
            self.stdout.write(f'  Banner {estado}: {obj.titulo}')

    def _password_staff(self, password: str) -> str:
        """Contraseña desde argumento, env, o consola interactiva. Nunca un default."""
        if password.strip():
            return password.strip()
        env_password = os.environ.get('SEED_STAFF_PASSWORD', '').strip()
        if env_password:
            return env_password
        # Solo pedimos por teclado en una terminal real; en tests/CI no bloqueamos.
        if sys.stdin.isatty():
            try:
                return getpass.getpass(
                    'Contraseña para el usuario staff (Enter para omitir): '
                ).strip()
            except (EOFError, KeyboardInterrupt):
                self.stdout.write('')
                return ''
        return ''

    def _seed_staff(self, username: str = 'staff', password: str = '') -> None:
        """Usuario staff para probar transferencias y encargues en admin.

        No crea nada si DEBUG=False o si no hay contraseña (env / flag / consola).
        """
        if not settings.DEBUG:
            self.stdout.write(
                self.style.WARNING(
                    '  Staff omitido: seed_datos no crea usuarios cuando DEBUG=False.'
                )
            )
            return

        username = username.strip() or 'staff'
        password = self._password_staff(password)
        if not password:
            self.stdout.write(
                self.style.WARNING(
                    '  Staff omitido: no hay contraseña. Definí SEED_STAFF_PASSWORD, '
                    'pasá --staff-password, o creá el usuario con createsuperuser.'
                )
            )
            return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': f'{username}@farmacia.local',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        if created:
            user.set_password(password)
            user.save()
            # No imprimimos la contraseña: queda solo en el entorno local.
            self.stdout.write(
                self.style.SUCCESS(f'  Staff creado: usuario={username}')
            )
        else:
            self.stdout.write(f'  Staff ya existía: usuario={username}')
