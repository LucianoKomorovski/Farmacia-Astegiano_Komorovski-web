from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalogo.models import Producto

from .models import LineaCarrito
from .services import (
    CarritoError,
    actualizar_cantidad,
    agregar_producto,
    lineas_del_carrito,
    obtener_carrito,
    quitar_linea,
)


def ver_carrito(request: HttpRequest) -> HttpResponse:
    carrito = obtener_carrito(request, crear=False)
    lineas = lineas_del_carrito(carrito) if carrito else LineaCarrito.objects.none()
    return render(
        request,
        'carrito/ver.html',
        {
            'carrito': carrito,
            'lineas': lineas,
            'subtotal': carrito.subtotal if carrito else 0,
        },
    )


@require_POST
def agregar_al_carrito(request: HttpRequest, slug: str) -> HttpResponse:
    """POST: agrega 1 (o la cantidad del form) y vuelve al carrito."""
    producto = get_object_or_404(
        Producto.objects.visibles_en_tienda().select_related('stock'),
        slug=slug,
    )
    try:
        cantidad = int(request.POST.get('cantidad', '1'))
    except ValueError:
        cantidad = 1

    carrito = obtener_carrito(request, crear=True)
    assert carrito is not None

    try:
        agregar_producto(carrito, producto, cantidad)
        messages.success(request, f'Se agregó "{producto.nombre}" al carrito.')
    except CarritoError as exc:
        messages.error(request, str(exc))
        return redirect('catalogo_detalle', slug=producto.slug)

    return redirect('carrito_ver')


@require_POST
def actualizar_linea(request: HttpRequest, linea_id: int) -> HttpResponse:
    carrito = obtener_carrito(request, crear=False)
    linea = get_object_or_404(
        LineaCarrito.objects.select_related('producto', 'producto__stock', 'carrito'),
        pk=linea_id,
        carrito=carrito,
    )
    try:
        cantidad = int(request.POST.get('cantidad', '1'))
        actualizar_cantidad(linea, cantidad)
        messages.success(request, 'Cantidad actualizada.')
    except (ValueError, CarritoError) as exc:
        messages.error(request, str(exc))

    return redirect('carrito_ver')


@require_POST
def eliminar_linea(request: HttpRequest, linea_id: int) -> HttpResponse:
    carrito = obtener_carrito(request, crear=False)
    linea = get_object_or_404(LineaCarrito, pk=linea_id, carrito=carrito)
    nombre = str(linea.producto)
    quitar_linea(linea)
    messages.success(request, f'Se quitó "{nombre}" del carrito.')
    return redirect('carrito_ver')
