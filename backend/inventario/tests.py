"""Tests del importador CSV de stock."""

from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.test import TestCase

from catalogo.models import Categoria, Producto
from inventario.importador import calcular_stock_web, importar_stock_csv
from inventario.models import StockWeb


class ImportadorStockTests(TestCase):
    def setUp(self):
        cat = Categoria.objects.create(nombre='T', slug='t')
        self.producto = Producto.objects.create(
            categoria=cat,
            nombre='Jabón',
            slug='jabon',
            sku='HIG-001',
            codigo_barras='7790001001003',
            descripcion='',
            tipo=Producto.Tipo.INMEDIATO,
            precio=Decimal('100'),
            activo=True,
        )

    def test_calcular_stock_web(self):
        self.assertEqual(calcular_stock_web(50, margen_seguridad=5, tope_web=40), 40)
        self.assertEqual(calcular_stock_web(10, margen_seguridad=15), 0)

    def test_importar_csv_actualiza_stock(self):
        csv_content = (
            'sku,codigo_barras,codigo_praxys,stock_praxys,margen_seguridad,tope_web\n'
            'HIG-001,7790001001003,,50,5,40\n'
        )
        with NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            path = f.name

        log, resultado = importar_stock_csv(path)
        Path(path).unlink()

        self.assertTrue(log.ok)
        self.assertEqual(resultado.actualizados, 1)
        stock = StockWeb.objects.get(producto=self.producto)
        self.assertEqual(stock.cantidad, 40)
        self.assertEqual(stock.origen, StockWeb.Origen.CSV)
