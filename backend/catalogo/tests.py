from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .models import Categoria, Producto


def crear_producto(
    nombre: str,
    sku: str,
    precio: str = '100',
    categoria: Categoria | None = None,
    activo: bool = True,
    requiere_receta: bool = False,
    descripcion: str = '',
) -> Producto:
    """Atajo para no repetir todos los campos en cada test."""
    return Producto.objects.create(
        nombre=nombre,
        slug=sku.lower(),
        sku=sku,
        descripcion=descripcion,
        categoria=categoria,
        tipo=Producto.Tipo.INMEDIATO,
        precio=Decimal(precio),
        activo=activo,
        requiere_receta=requiere_receta,
    )


class CatalogoListaTests(TestCase):
    """Búsqueda, filtro por categoría, orden y visibilidad en /tienda/."""

    @classmethod
    def setUpTestData(cls) -> None:
        # setUpTestData corre UNA vez para toda la clase (más rápido que setUp).
        cls.dermo = Categoria.objects.create(nombre='Dermocosmética', slug='dermo')
        cls.higiene = Categoria.objects.create(nombre='Higiene', slug='higiene')

        cls.crema = crear_producto(
            'Crema hidratante', 'CRE-001', '5000',
            categoria=cls.dermo, descripcion='Con ácido hialurónico',
        )
        cls.jabon = crear_producto('Jabón neutro', 'JAB-001', '1200', categoria=cls.higiene)
        cls.oculto = crear_producto('Producto inactivo', 'INA-001', activo=False)
        cls.receta = crear_producto('Antibiótico', 'REC-001', requiere_receta=True)

        cls.url = reverse('catalogo_lista')

    def test_solo_muestra_productos_visibles(self):
        resp = self.client.get(self.url)
        productos = list(resp.context['productos'])
        self.assertIn(self.crema, productos)
        self.assertIn(self.jabon, productos)
        self.assertNotIn(self.oculto, productos)
        self.assertNotIn(self.receta, productos)

    def test_busqueda_por_nombre(self):
        resp = self.client.get(self.url, {'q': 'crema'})
        self.assertEqual(list(resp.context['productos']), [self.crema])

    def test_busqueda_por_sku(self):
        resp = self.client.get(self.url, {'q': 'JAB-001'})
        self.assertEqual(list(resp.context['productos']), [self.jabon])

    def test_busqueda_por_descripcion(self):
        resp = self.client.get(self.url, {'q': 'hialurónico'})
        self.assertEqual(list(resp.context['productos']), [self.crema])

    def test_busqueda_sin_resultados(self):
        resp = self.client.get(self.url, {'q': 'no-existe-xyz'})
        self.assertEqual(list(resp.context['productos']), [])
        self.assertContains(resp, 'No encontramos productos')

    def test_busqueda_no_encuentra_ocultos(self):
        # Aunque el texto matchee, inactivos y con receta no aparecen.
        resp = self.client.get(self.url, {'q': 'inactivo'})
        self.assertEqual(list(resp.context['productos']), [])
        resp = self.client.get(self.url, {'q': 'antibiótico'})
        self.assertEqual(list(resp.context['productos']), [])

    def test_filtro_por_categoria(self):
        resp = self.client.get(self.url, {'categoria': 'dermo'})
        self.assertEqual(list(resp.context['productos']), [self.crema])

    def test_filtro_categoria_inexistente_no_rompe(self):
        resp = self.client.get(self.url, {'categoria': 'nada'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context['productos']), [])

    def test_orden_precio_descendente(self):
        resp = self.client.get(self.url, {'orden': 'precio_desc'})
        self.assertEqual(list(resp.context['productos']), [self.crema, self.jabon])

    def test_orden_invalido_usa_default(self):
        # Cualquier clave fuera de la whitelist cae al orden por nombre.
        resp = self.client.get(self.url, {'orden': 'id; DROP TABLE'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context['productos']), [self.crema, self.jabon])

    def test_solo_lista_categorias_con_productos_visibles(self):
        # "Vacía" no tiene productos → no debe aparecer en el select del filtro.
        Categoria.objects.create(nombre='Vacía', slug='vacia')
        resp = self.client.get(self.url)
        slugs = [c.slug for c in resp.context['categorias']]
        self.assertIn('dermo', slugs)
        self.assertNotIn('vacia', slugs)


class CatalogoPaginacionTests(TestCase):
    """La lista pagina de a 12 conservando los filtros en los links."""

    @classmethod
    def setUpTestData(cls) -> None:
        for i in range(15):
            crear_producto(f'Producto {i:02d}', f'SKU-{i:03d}')
        cls.url = reverse('catalogo_lista')

    def test_primera_pagina_tiene_12(self):
        resp = self.client.get(self.url)
        self.assertEqual(len(resp.context['productos']), 12)
        self.assertTrue(resp.context['is_paginated'])

    def test_segunda_pagina_tiene_el_resto(self):
        resp = self.client.get(self.url, {'page': '2'})
        self.assertEqual(len(resp.context['productos']), 3)

    def test_links_de_paginacion_conservan_filtros(self):
        resp = self.client.get(self.url, {'q': 'Producto'})
        # El link a la página 2 tiene que mantener q=Producto.
        self.assertContains(resp, 'q=Producto')
        self.assertContains(resp, 'page=2')
