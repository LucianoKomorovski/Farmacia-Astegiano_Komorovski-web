from django.db import models
from django.db.models import Q, QuerySet
from django.utils import timezone


class BannerQuerySet(QuerySet['Banner']):
    """Filtros reutilizables para los banners de la portada."""

    def vigentes(self) -> QuerySet['Banner']:
        """Activos y dentro del rango de fechas (si se cargó alguno).

        Q(...) | Q(...) arma un OR: la fecha límite está vacía O todavía no pasó.
        """
        hoy = timezone.localdate()
        return self.filter(activo=True).filter(
            Q(vigente_desde__isnull=True) | Q(vigente_desde__lte=hoy),
        ).filter(
            Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=hoy),
        )


class Banner(models.Model):
    """Slide del carrusel principal de la portada (se muestran hasta 3).

    Puede ir sin imagen: en ese caso se dibuja con el degradé de la marca,
    así se puede publicar una promo rápida solo con texto.
    """

    titulo = models.CharField(max_length=80)
    subtitulo = models.CharField(max_length=160, blank=True)
    imagen = models.ImageField(
        upload_to='banners/',
        blank=True,
        null=True,
        help_text='Recomendado 1400×450 px. Si se deja vacío se usa un fondo de marca.',
    )
    link = models.CharField(
        max_length=300,
        blank=True,
        help_text='Adónde lleva el botón. Puede ser una ruta interna (/tienda/?oferta=1) o una URL.',
    )
    texto_boton = models.CharField(max_length=40, blank=True, default='Ver más')
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(
        default=0,
        help_text='Menor número aparece primero.',
    )
    vigente_desde = models.DateField(null=True, blank=True)
    vigente_hasta = models.DateField(null=True, blank=True)

    objects: BannerQuerySet = BannerQuerySet.as_manager()  # type: ignore[assignment]

    class Meta:
        ordering = ['orden', '-id']
        verbose_name = 'banner de portada'
        verbose_name_plural = 'banners de portada'

    def __str__(self) -> str:
        return str(self.titulo)
