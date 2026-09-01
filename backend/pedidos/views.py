from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from carrito.services import lineas_del_carrito, obtener_carrito

from .forms import CheckoutForm
from .models import Pedido
from .services import PedidoError, crear_pedido_desde_carrito, pedido_usa_pago_online

# Clave de sesión: números de pedido que este visitante puede ver.
SESSION_PEDIDOS_KEY = 'pedidos_vistos'


def _registrar_pedido_en_sesion(request: HttpRequest, numero: str) -> None:
    vistos = request.session.get(SESSION_PEDIDOS_KEY, [])
    if numero not in vistos:
        vistos.append(numero)
        request.session[SESSION_PEDIDOS_KEY] = vistos
        request.session.modified = True


def _puede_ver_pedido(request: HttpRequest, pedido: Pedido) -> bool:
    if request.user.is_staff:
        return True
    if request.user.is_authenticated and pedido.usuario_id == request.user.pk:
        return True
    return pedido.numero in request.session.get(SESSION_PEDIDOS_KEY, [])


def checkout(request: HttpRequest) -> HttpResponse:
    carrito = obtener_carrito(request, crear=False)
    lineas = lineas_del_carrito(carrito) if carrito else []

    if not carrito or not lineas.exists():
        messages.info(request, 'Agregá productos al carrito antes de continuar.')
        return redirect('carrito_ver')

    assert carrito is not None
    es_encargue = carrito.modo == carrito.Modo.ENCARGUE

    if request.method == 'POST':
        form = CheckoutForm(request.POST, es_encargue=es_encargue)
        if form.is_valid():
            try:
                pedido = crear_pedido_desde_carrito(request, carrito, form.cleaned_data)
                _registrar_pedido_en_sesion(request, pedido.numero)

                # Pago online → redirigir a Mercado Pago.
                if pedido_usa_pago_online(pedido):
                    return redirect('pagos_iniciar', numero=pedido.numero)

                return redirect('pedido_confirmacion', numero=pedido.numero)
            except PedidoError as exc:
                messages.error(request, str(exc))
    else:
        inicial: dict[str, object] = {}
        if request.user.is_authenticated:
            inicial['email'] = request.user.email
            inicial['nombre_cliente'] = request.user.get_username()
        form = CheckoutForm(initial=inicial, es_encargue=es_encargue)

    return render(
        request,
        'pedidos/checkout.html',
        {
            'form': form,
            'carrito': carrito,
            'lineas': lineas,
            'subtotal': carrito.subtotal,
            'es_encargue': es_encargue,
        },
    )


def confirmacion(request: HttpRequest, numero: str) -> HttpResponse:
    pedido = get_object_or_404(
        Pedido.objects.prefetch_related('lineas'),
        numero=numero,
    )
    if not _puede_ver_pedido(request, pedido):
        return HttpResponseForbidden('No tenés permiso para ver este pedido.')

    from django.conf import settings
    from pagos.services import mp_configurado, mp_modo_local
    from pedidos.notifications import url_whatsapp_pedido

    return render(
        request,
        'pedidos/confirmacion.html',
        {
            'pedido': pedido,
            'mp_configurado': mp_configurado(),
            'mp_modo_local': mp_modo_local(),
            'transferencia_cbu': getattr(settings, 'TRANSFERENCIA_CBU', ''),
            'transferencia_alias': getattr(settings, 'TRANSFERENCIA_ALIAS', ''),
            'whatsapp_url': url_whatsapp_pedido(pedido),
        },
    )


@login_required
def mis_pedidos(request: HttpRequest) -> HttpResponse:
    """Historial de pedidos del usuario logueado.

    @login_required manda a los anónimos a LOGIN_URL con ?next=/pedidos/mis-pedidos/
    para volver acá después de iniciar sesión.
    """
    pedidos = Pedido.objects.filter(usuario=request.user).prefetch_related('lineas')[:50]
    return render(request, 'pedidos/mis_pedidos.html', {'pedidos': pedidos})
