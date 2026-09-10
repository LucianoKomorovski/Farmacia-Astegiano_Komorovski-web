from typing import Any

from django.db.models import Q, QuerySet
from django.views.generic import DetailView, ListView

from .models import Categoria, Producto

# Whitelist de órdenes permitidos: clave que viaja en la URL → campo real del ORM.
# Así nadie puede ordenar por campos arbitrarios metiendo ?orden=lo_que_sea.
ORDENES_VALIDOS: dict[str, str] = {
    'nombre': 'nombre',
    'precio_asc': 'precio',
    'precio_desc': '-precio',
}

# Cuántos productos relacionados se muestran al pie de la ficha.
MAX_RELACIONADOS = 4


def _categorias_con_productos() -> QuerySet[Categoria]:
    """Categorías activas con al menos un producto visible en la tienda.

    distinct evita repetidas cuando una categoría tiene varios productos.
    """
    return (
        Categoria.objects.filter(
            activa=True,
            productos__activo=True,
            productos__requiere_receta=False,
        )
        .distinct()
    )


class ProductoListView(ListView):
    """Lista pública: solo productos activos y sin receta.

    Filtros por querystring (todos opcionales y combinables):
      ?q=texto        → busca en nombre, SKU y descripción
      ?categoria=slug → filtra por categoría activa
      ?oferta=1       → solo productos con precio anterior mayor al actual
      ?orden=clave    → nombre | precio_asc | precio_desc
      ?page=N         → paginación (12 por página)
    """

    template_name = 'catalogo/lista.html'
    context_object_name = 'productos'
    paginate_by = 12

    def get_queryset(self) -> QuerySet[Producto]:
        # select_related evita una consulta extra por cada categoría/stock (N+1).
        qs = (
            Producto.objects.visibles_en_tienda()
            .select_related('categoria', 'stock')
        )

        # Búsqueda: icontains = "contiene el texto, sin distinguir mayúsculas".
        # Q(...) | Q(...) arma un OR: alcanza con que matchee uno de los campos.
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q)
                | Q(sku__icontains=q)
                | Q(descripcion__icontains=q)
            )

        # Filtro por categoría: llega el slug en la URL.
        categoria_slug = self.request.GET.get('categoria', '').strip()
        if categoria_slug:
            qs = qs.filter(categoria__slug=categoria_slug, categoria__activa=True)

        # Solo ofertas (?oferta=1). Cualquier valor "verdadero" alcanza.
        if self.request.GET.get('oferta'):
            qs = qs.en_oferta()  # type: ignore[attr-defined]

        # Orden: solo claves de la whitelist; cualquier otra cosa usa el
        # orden por defecto del modelo (Meta.ordering = nombre).
        orden = self.request.GET.get('orden', '')
        if orden in ORDENES_VALIDOS:
            qs = qs.order_by(ORDENES_VALIDOS[orden])

        return qs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)

        contexto['categorias'] = _categorias_con_productos()

        # Valores actuales de los filtros, para que el formulario los recuerde.
        contexto['q_actual'] = self.request.GET.get('q', '').strip()
        contexto['categoria_actual'] = self.request.GET.get('categoria', '').strip()
        contexto['orden_actual'] = self.request.GET.get('orden', '')
        contexto['oferta_actual'] = bool(self.request.GET.get('oferta'))
        contexto['hay_filtros'] = bool(
            contexto['q_actual']
            or contexto['categoria_actual']
            or contexto['orden_actual']
            or contexto['oferta_actual']
        )

        # Objeto Categoria activa (para el título y el breadcrumb), si hay filtro.
        contexto['categoria_objeto'] = None
        if contexto['categoria_actual']:
            contexto['categoria_objeto'] = (
                Categoria.objects.filter(slug=contexto['categoria_actual']).first()
            )

        # Rango de páginas "elidido": 1 … 4 5 [6] 7 8 … 20
        # (el template no puede llamar métodos con argumentos, por eso va acá).
        paginator = contexto.get('paginator')
        page_obj = contexto.get('page_obj')
        if paginator is not None and page_obj is not None:
            contexto['rango_paginas'] = paginator.get_elided_page_range(
                page_obj.number, on_each_side=2, on_ends=1,
            )

        return contexto


class ProductoDetailView(DetailView):
    """Ficha de un producto. Si está oculto o con receta, da 404."""

    template_name = 'catalogo/detalle.html'
    context_object_name = 'producto'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_queryset(self) -> QuerySet[Producto]:
        return (
            Producto.objects.visibles_en_tienda()
            .select_related('categoria', 'stock')
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        producto: Producto = contexto['producto']

        # "También te puede interesar": misma categoría, excluyendo este producto.
        relacionados: QuerySet[Producto] = Producto.objects.none()
        if producto.categoria_id is not None:
            relacionados = (
                Producto.objects.visibles_en_tienda()
                .select_related('categoria', 'stock')
                .filter(categoria_id=producto.categoria_id)
                .exclude(pk=producto.pk)[:MAX_RELACIONADOS]
            )
        contexto['relacionados'] = relacionados
        return contexto
