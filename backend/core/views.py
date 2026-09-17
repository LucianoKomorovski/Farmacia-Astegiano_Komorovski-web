from datetime import timedelta
from typing import Any

from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from catalogo.models import Categoria, Producto
from servicios.models import Servicio
from sucursales.models import Sucursal
from turnos.models import Turno

from .models import NOMBRES_DIA, Banner, PromocionBancaria

# Límites de la portada: "publicidad sí, pero sin exceso".
MAX_BANNERS = 3
MAX_PROMOS_CARRUSEL = 3
MAX_PRODUCTOS_SECCION = 8


def _imagen_o_nada(campo: Any) -> Any:
    """FieldFile vacío es truthy-raro en templates; devolvemos None si no hay archivo."""
    return campo if campo else None


class InicioView(TemplateView):
    """Portada híbrida: tienda arriba (banners, categorías, ofertas, destacados)
    y lo institucional abajo (turnos, sucursales, servicios)."""

    template_name = 'core/index.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        hoy = timezone.localdate()

        # --- Bloque tienda ---
        # Filtros custom (en_oferta / destacados) ANTES de select_related:
        # los stubs de Django tipan select_related como QuerySet genérico y
        # Pyright dejaría de ver esos métodos.
        visibles = Producto.objects.visibles_en_tienda()

        # Carrusel de portada: 1) ofertas  2) un solo slide con las promos
        # de hoy  3) el resto de banners (en el seed: "Tu farmacia...").
        banners = list(Banner.objects.vigentes()[:MAX_BANNERS])
        promos_hoy = list(
            PromocionBancaria.objects.del_dia(hoy.weekday())[:MAX_PROMOS_CARRUSEL]
        )
        url_promos = reverse('promociones_bancarias')

        def slide_banner(banner: Banner) -> dict[str, Any]:
            """Convierte un Banner del admin en el dict que usa el template."""
            return {
                'tipo': 'banner',
                'titulo': banner.titulo,
                'subtitulo': banner.subtitulo,
                'imagen': _imagen_o_nada(banner.imagen),
                'link': banner.link,
                'texto_boton': banner.texto_boton or 'Ver más',
                'promos': [],
            }

        # next(...) devuelve el primer banner cuyo link apunta a ofertas,
        # o None si nadie cargó ese banner.
        banner_ofertas = next(
            (b for b in banners if 'oferta=1' in (b.link or '')),
            None,
        )
        otros_banners = [b for b in banners if b is not banner_ofertas]

        slides: list[dict[str, Any]] = []
        if banner_ofertas:
            slides.append(slide_banner(banner_ofertas))
        if promos_hoy:
            # Un único slide: el template recorre slide.promos adentro.
            slides.append({
                'tipo': 'promo',
                'titulo': 'Promos bancarias de hoy',
                'subtitulo': '',
                'imagen': None,
                'link': url_promos,
                'texto_boton': 'Ver la semana',
                'promos': promos_hoy,
            })
        for banner in otros_banners:
            slides.append(slide_banner(banner))

        contexto['slides'] = slides
        contexto['promos_hoy'] = promos_hoy
        contexto['nombre_dia_hoy'] = NOMBRES_DIA[hoy.weekday()]
        contexto['ofertas'] = (
            visibles.en_oferta()
            .select_related('categoria', 'stock')[:MAX_PRODUCTOS_SECCION]
        )
        contexto['destacados'] = (
            visibles.destacados()
            .select_related('categoria', 'stock')[:MAX_PRODUCTOS_SECCION]
        )
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


class PromocionesBancariasView(TemplateView):
    """Todas las promos vigentes, agrupadas de lunes a domingo.

    Los días sin ninguna promo se omiten. El día de hoy va resaltado.
    """

    template_name = 'core/promociones_bancarias.html'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        contexto = super().get_context_data(**kwargs)
        hoy = timezone.localdate()
        weekday_hoy = hoy.weekday()
        vigentes = list(PromocionBancaria.objects.vigentes())

        grupos: list[dict[str, Any]] = []
        for indice, nombre in enumerate(NOMBRES_DIA):
            del_dia = [promo for promo in vigentes if promo.aplica_en(indice)]
            if not del_dia:
                continue
            grupos.append({
                'indice': indice,
                'nombre': nombre,
                'promociones': del_dia,
                'es_hoy': indice == weekday_hoy,
            })

        contexto['grupos_dias'] = grupos
        contexto['nombre_dia_hoy'] = NOMBRES_DIA[weekday_hoy]
        return contexto
