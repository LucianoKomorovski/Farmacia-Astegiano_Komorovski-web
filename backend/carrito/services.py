"""Lógica del carrito (buscar, agregar, validar). Separada de las vistas."""

from __future__ import annotations

from django.db.models import QuerySet
from django.http import HttpRequest

from catalogo.models import Producto

from .models import Carrito, LineaCarrito


class CarritoError(Exception):
    """Error de negocio al modificar el carrito (mensaje para el usuario)."""


def obtener_carrito(request: HttpRequest, crear: bool = True) -> Carrito | None:
    """Devuelve el carrito de este visitante (usuario logueado o sesión).

    crear=True: si no existe, lo crea.
    crear=False: si no existe, devuelve None (útil para solo mirar).
    """
    if request.user.is_authenticated:
        carrito, _ = Carrito.objects.get_or_create(usuario=request.user)
        return carrito

    # Sin sesión no hay cookie que nos identifique.
    if not request.session.session_key:
        if not crear:
            return None
        request.session.create()

    session_key = request.session.session_key
    assert session_key is not None

    if crear:
        carrito, _ = Carrito.objects.get_or_create(session_key=session_key)
        return carrito

    return Carrito.objects.filter(session_key=session_key).first()


def lineas_del_carrito(carrito: Carrito) -> QuerySet[LineaCarrito]:
    # select_related evita N+1 al mostrar nombre/imagen del producto.
    return carrito.lineas.select_related(  # pyright: ignore[reportAttributeAccessIssue]
        'producto',
        'producto__stock',
    )


def _stock_disponible(producto: Producto) -> int:
    from inventario.services import cantidad_disponible

    return cantidad_disponible(producto.pk)


def agregar_producto(carrito: Carrito, producto: Producto, cantidad: int = 1) -> LineaCarrito:
    """Agrega (o suma) un producto. Respeta modo único y stock inmediato."""
    if cantidad < 1:
        raise CarritoError('La cantidad debe ser al menos 1.')

    if not producto.visible_en_tienda:
        raise CarritoError('Ese producto no está disponible en la tienda.')

    # Primer ítem: fija el modo del carrito.
    if carrito.modo is None:
        carrito.modo = (
            Carrito.Modo.ENCARGUE
            if producto.es_encargue
            else Carrito.Modo.INMEDIATO
        )
        carrito.save(update_fields=['modo', 'updated_at'])
    elif carrito.modo != producto.tipo:
        raise CarritoError(
            'Este carrito es solo de productos '
            f'"{Carrito.Modo(carrito.modo).label}". '
            'Vaciá el carrito para comprar el otro tipo.'
        )

    linea = carrito.lineas.filter(producto=producto).first()  # pyright: ignore[reportAttributeAccessIssue]
    nueva_cantidad = cantidad if linea is None else linea.cantidad + cantidad

    if carrito.modo == Carrito.Modo.INMEDIATO:
        disponible = _stock_disponible(producto)
        if nueva_cantidad > disponible:
            raise CarritoError(
                f'Solo hay {disponible} unidad(es) disponibles de "{producto.nombre}".'
            )

    if linea is None:
        return LineaCarrito.objects.create(
            carrito=carrito,
            producto=producto,
            cantidad=nueva_cantidad,
            precio_unitario=producto.precio,
        )

    linea.cantidad = nueva_cantidad
    linea.precio_unitario = producto.precio
    linea.save(update_fields=['cantidad', 'precio_unitario'])
    carrito.save(update_fields=['updated_at'])
    return linea


def actualizar_cantidad(linea: LineaCarrito, cantidad: int) -> None:
    if cantidad < 1:
        raise CarritoError('La cantidad debe ser al menos 1. Para quitar, usá Eliminar.')

    carrito = linea.carrito
    producto = linea.producto

    if carrito.modo == Carrito.Modo.INMEDIATO:
        disponible = _stock_disponible(producto)
        if cantidad > disponible:
            raise CarritoError(
                f'Solo hay {disponible} unidad(es) disponibles de "{producto.nombre}".'
            )

    linea.cantidad = cantidad
    linea.save(update_fields=['cantidad'])
    carrito.save(update_fields=['updated_at'])


def quitar_linea(linea: LineaCarrito) -> None:
    carrito = linea.carrito
    linea.delete()
    # Si quedó vacío, liberamos el modo para poder empezar de nuevo.
    if not carrito.lineas.exists():  # pyright: ignore[reportAttributeAccessIssue]
        carrito.modo = None
        carrito.save(update_fields=['modo', 'updated_at'])
    else:
        carrito.save(update_fields=['updated_at'])
