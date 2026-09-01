from decimal import Decimal
from itertools import count

from django.contrib.auth.models import User
from django.test import TestCase

from carrito.models import Carrito, LineaCarrito
from catalogo.models import Categoria, Producto
from inventario.models import StockWeb
from pedidos.models import Pedido
from pedidos.services import (
    aprobar_encargue,
    avanzar_fulfillment,
    cancelar_pedido,
    confirmar_pedido,
    confirmar_transferencia_staff,
    crear_pedido_desde_carrito,
)

_secuencia = count(1)


def request_anonimo():
    """Request falso con usuario anónimo (alcanza para los services)."""
    return type('R', (), {'user': type('U', (), {'is_authenticated': False})()})()


class EventoPedidoTests(TestCase):
    """Cada transición de estado deja un registro de auditoría (EventoPedido)."""

    def setUp(self):
        cat = Categoria.objects.create(nombre='Test', slug='test')
        self.inmediato = Producto.objects.create(
            categoria=cat, nombre='Jabón', slug='jabon', sku='JAB-001',
            tipo=Producto.Tipo.INMEDIATO, precio=Decimal('100'), activo=True,
        )
        StockWeb.objects.create(producto=self.inmediato, cantidad=10)
        self.encargue = Producto.objects.create(
            categoria=cat, nombre='Perfume', slug='perfume', sku='PER-001',
            tipo=Producto.Tipo.ENCARGUE, precio=Decimal('500'), activo=True,
        )
        self.staff = User.objects.create_user(
            'staff', 'staff@test.com', 'x12345678', is_staff=True,
        )

    def _crear_pedido(self, producto: Producto, medio: str) -> Pedido:
        """Arma un carrito de un producto y lo convierte en pedido."""
        modo = Carrito.Modo.ENCARGUE if producto.es_encargue else Carrito.Modo.INMEDIATO
        carrito = Carrito.objects.create(session_key=f'sesion-{next(_secuencia)}')
        carrito.modo = modo
        carrito.save()
        LineaCarrito.objects.create(
            carrito=carrito, producto=producto,
            cantidad=1, precio_unitario=producto.precio,
        )
        datos = {
            'nombre_cliente': 'Juan',
            'email': 'juan@test.com',
            'telefono': '3510000000',
            'modalidad_entrega': Pedido.ModalidadEntrega.A_COORDINAR,
            'medio_pago': medio,
            'notas': '',
        }
        return crear_pedido_desde_carrito(request_anonimo(), carrito, datos)

    def _ultimo_evento(self, pedido: Pedido):
        # order_by('pk'): dos eventos pueden compartir el mismo created_at.
        return pedido.eventos.order_by('pk').last()

    def test_crear_pedido_registra_evento_inicial(self):
        pedido = self._crear_pedido(self.inmediato, Pedido.MedioPago.MERCADOPAGO)

        evento = pedido.eventos.get()  # debe haber exactamente uno
        self.assertEqual(evento.estado_anterior, '')
        self.assertEqual(evento.estado_nuevo, Pedido.Estado.PENDIENTE_PAGO)
        self.assertIsNone(evento.actor)  # compró como invitado

    def test_confirmar_pedido_registra_evento_de_sistema(self):
        pedido = self._crear_pedido(self.inmediato, Pedido.MedioPago.MERCADOPAGO)
        confirmar_pedido(pedido)

        evento = self._ultimo_evento(pedido)
        assert evento is not None
        self.assertEqual(evento.estado_anterior, Pedido.Estado.PENDIENTE_PAGO)
        self.assertEqual(evento.estado_nuevo, Pedido.Estado.CONFIRMADO)
        self.assertIsNone(evento.actor)  # webhook/simulación = sistema

    def test_confirmar_transferencia_registra_actor_staff(self):
        pedido = self._crear_pedido(self.inmediato, Pedido.MedioPago.TRANSFERENCIA)
        confirmar_transferencia_staff(pedido, self.staff)

        evento = self._ultimo_evento(pedido)
        assert evento is not None
        self.assertEqual(evento.estado_anterior, Pedido.Estado.PENDIENTE_TRANSFERENCIA)
        self.assertEqual(evento.estado_nuevo, Pedido.Estado.CONFIRMADO)
        self.assertEqual(evento.actor, self.staff)

    def test_aprobar_encargue_registra_actor_staff(self):
        pedido = self._crear_pedido(self.encargue, Pedido.MedioPago.MERCADOPAGO)
        aprobar_encargue(pedido, self.staff)

        evento = self._ultimo_evento(pedido)
        assert evento is not None
        self.assertEqual(evento.estado_anterior, Pedido.Estado.PENDIENTE_ENCARGUE)
        self.assertEqual(evento.estado_nuevo, Pedido.Estado.PENDIENTE_PAGO_ENCARGUE)
        self.assertEqual(evento.actor, self.staff)

    def test_cancelar_guarda_motivo_en_detalle(self):
        pedido = self._crear_pedido(self.inmediato, Pedido.MedioPago.TRANSFERENCIA)
        cancelar_pedido(pedido, motivo='Reserva de stock expirada (1 h).')

        evento = self._ultimo_evento(pedido)
        assert evento is not None
        self.assertEqual(evento.estado_nuevo, Pedido.Estado.CANCELADO)
        self.assertIn('expirada', evento.detalle)
        self.assertIsNone(evento.actor)  # lo canceló el sistema, no una persona

    def test_fulfillment_registra_cada_paso(self):
        pedido = self._crear_pedido(self.inmediato, Pedido.MedioPago.MERCADOPAGO)
        confirmar_pedido(pedido)
        avanzar_fulfillment(pedido, Pedido.Estado.EN_PREPARACION, actor=self.staff)
        avanzar_fulfillment(pedido, Pedido.Estado.LISTO_RETIRO, actor=self.staff)

        eventos = list(pedido.eventos.order_by('pk'))
        # creación + confirmación + 2 pasos de fulfillment = 4 eventos
        self.assertEqual(len(eventos), 4)
        self.assertEqual(eventos[-1].estado_anterior, Pedido.Estado.EN_PREPARACION)
        self.assertEqual(eventos[-1].estado_nuevo, Pedido.Estado.LISTO_RETIRO)
        self.assertEqual(eventos[-1].actor, self.staff)
