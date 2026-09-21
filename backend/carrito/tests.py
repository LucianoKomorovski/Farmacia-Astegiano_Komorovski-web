from decimal import Decimal

from django.test import TestCase

from catalogo.models import Categoria, Producto
from inventario.models import StockWeb

from .models import Carrito
from .services import CarritoError, agregar_producto


class AgregarProductoTests(TestCase):
    def setUp(self):
        cat = Categoria.objects.create(nombre='Test', slug='test-carrito')
        self.inmediato = Producto.objects.create(
            categoria=cat, nombre='Jabón', slug='jabon-c', sku='JAB-C01',
            tipo=Producto.Tipo.INMEDIATO, precio=Decimal('100'), activo=True,
        )
        StockWeb.objects.create(producto=self.inmediato, cantidad=5)
        self.encargue = Producto.objects.create(
            categoria=cat, nombre='Perfume', slug='perfume-c', sku='PER-C01',
            tipo=Producto.Tipo.ENCARGUE, precio=Decimal('500'), activo=True,
        )
        self.carrito = Carrito.objects.create(session_key='carrito-test')

    def test_primer_item_fija_modo(self):
        agregar_producto(self.carrito, self.inmediato)
        self.carrito.refresh_from_db()
        self.assertEqual(self.carrito.modo, Carrito.Modo.INMEDIATO)

    def test_no_mezcla_modos(self):
        agregar_producto(self.carrito, self.inmediato)
        with self.assertRaises(CarritoError):
            agregar_producto(self.carrito, self.encargue)
        self.carrito.refresh_from_db()
        self.assertEqual(self.carrito.modo, Carrito.Modo.INMEDIATO)
        self.assertEqual(self.carrito.lineas.count(), 1)

    def test_rechaza_producto_oculto(self):
        self.inmediato.activo = False
        self.inmediato.save()
        with self.assertRaises(CarritoError):
            agregar_producto(self.carrito, self.inmediato)

    def test_releer_modo_ignora_instancia_stale(self):
        """select_for_update relee modo: una instancia vieja no puede mezclar tipos."""
        agregar_producto(self.carrito, self.inmediato)
        stale = Carrito.objects.get(pk=self.carrito.pk)
        stale.modo = None
        with self.assertRaises(CarritoError):
            agregar_producto(stale, self.encargue)
        self.carrito.refresh_from_db()
        self.assertEqual(self.carrito.modo, Carrito.Modo.INMEDIATO)
        self.assertEqual(self.carrito.lineas.count(), 1)
