from datetime import timedelta
from typing import Any

from django.utils import timezone
from django.views.generic import TemplateView

from catalogo.models import Categoria, Producto
from servicios.models import Servicio
from sucursales.models import Sucursal
from turnos.models import Turno

from .models import Banner

# Límites de la portada: "publicidad sí, pero sin exceso".
MAX_BANNERS = 3
MAX_PRODUCTOS_SECCION = 8


class InicioView(TemplateView):
    """Portada híbrida: tienda arriba (banners, categorías, ofertas, destacados)
    y lo institucional abajo (turnos, sucursales, servicios)."""

    template_name = 'core/index.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)

        # --- Bloque tienda ---
        # select_related trae categoría y stock en la misma consulta (evita N+1
        # al renderizar cada tarjeta).
        productos_visibles = (
            Producto.objects.visibles_en_tienda()
            .select_related('categoria', 'stock')
        )
        contexto['banners'] = Banner.objects.vigentes()[:MAX_BANNERS]
        contexto['ofertas'] = productos_visibles.en_oferta()[:MAX_PRODUCTOS_SECCION]
        contexto['destacados'] = productos_visibles.destacados()[:MAX_PRODUCTOS_SECCION]
        contexto['categorias'] = (
            Categoria.objects.filter(
                activa=True,
                productos__activo=True,
                productos__requiere_receta=False,
            )
            .distinct()
        )

        # --- Bloque institucional ---
        contexto['sucursales'] = Sucursal.objects.all()
        contexto['servicios'] = Servicio.objects.all()

        # Turnos de los próximos 7 días (hoy incluido) para el widget.
        # Armamos una entrada por día aunque falte cargar alguno en el calendario.
        hoy = timezone.localdate()
        turnos_cargados = {
            turno.fecha: turno
            for turno in Turno.objects.select_related('farmacia').filter(
                fecha__range=(hoy, hoy + timedelta(days=6)),
            )
        }
        contexto['proximos_turnos'] = [
            {
                'fecha': hoy + timedelta(days=i),
                'turno': turnos_cargados.get(hoy + timedelta(days=i)),
                'es_hoy': i == 0,
            }
            for i in range(7)
        ]

        # Si hoy le toca a una de nuestras sucursales, guardamos su id para
        # mostrar el badge "De turno hoy" en su tarjeta.
        turno_hoy = turnos_cargados.get(hoy)
        contexto['turno_de_hoy'] = turno_hoy
        contexto['id_sucursal_de_turno'] = (
            turno_hoy.farmacia.sucursal_id if turno_hoy else None
        )
        return contexto
