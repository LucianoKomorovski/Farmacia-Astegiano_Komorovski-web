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


class ProductoListView(ListView):
    """Lista pública: solo productos activos y sin receta.

    Filtros por querystring (todos opcionales y combinables):
      ?q=texto        → busca en nombre, SKU y descripción
      ?categoria=slug → filtra por categoría activa
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

        # Orden: solo claves de la whitelist; cualquier otra cosa usa el
        # orden por defecto del modelo (Meta.ordering = nombre).
        orden = self.request.GET.get('orden', '')
        if orden in ORDENES_VALIDOS:
            qs = qs.order_by(ORDENES_VALIDOS[orden])

        return qs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)

        # Solo categorías activas con al menos un producto visible
        # (distinct evita repetidas cuando una categoría tiene varios productos).
        contexto['categorias'] = (
            Categoria.objects.filter(
                activa=True,
                productos__activo=True,
                productos__requiere_receta=False,
            )
            .distinct()
        )

        # Valores actuales de los filtros, para que el formulario los recuerde.
        contexto['q_actual'] = self.request.GET.get('q', '').strip()
        contexto['categoria_actual'] = self.request.GET.get('categoria', '').strip()
        contexto['orden_actual'] = self.request.GET.get('orden', '')
        contexto['hay_filtros'] = bool(
            contexto['q_actual']
            or contexto['categoria_actual']
            or contexto['orden_actual']
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
