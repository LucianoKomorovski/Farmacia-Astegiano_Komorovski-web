from django.db import models
from django.db.models import Q, QuerySet
from django.utils import timezone

# weekday() de Python: lunes=0 … domingo=6. Coincide con timezone.localdate().
CAMPOS_DIA = (
    'lunes',
    'martes',
    'miercoles',
    'jueves',
    'viernes',
    'sabado',
    'domingo',
)
NOMBRES_DIA = (
    'Lunes',
    'Martes',
    'Miércoles',
    'Jueves',
    'Viernes',
    'Sábado',
    'Domingo',
)
ETIQUETAS_DIA = ('Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom')


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


class PromocionBancariaQuerySet(QuerySet['PromocionBancaria']):
    """Filtros reutilizables para las promos de bancos y tarjetas."""

    def vigentes(self) -> QuerySet['PromocionBancaria']:
        """Activas y dentro del rango de fechas (si se cargó alguno).

        Misma idea que Banner: fecha vacía = sin límite de ese lado.
        """
        hoy = timezone.localdate()
        return self.filter(activo=True).filter(
            Q(vigente_desde__isnull=True) | Q(vigente_desde__lte=hoy),
        ).filter(
            Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=hoy),
        )

    def del_dia(self, weekday: int) -> QuerySet['PromocionBancaria']:
        """Vigentes que aplican un día de la semana (0=lunes … 6=domingo)."""
        campo = CAMPOS_DIA[weekday]
        return self.vigentes().filter(**{campo: True})


class PromocionBancaria(models.Model):
    """Descuento o cuotas de un banco/tarjeta, según día y vigencia.

    En el home solo se muestran las del día de hoy; la página de la semana
    lista todas las vigentes agrupadas de lunes a domingo.
    """

    banco = models.CharField(
        max_length=80,
        help_text='Nombre del banco o tarjeta, ej. Banco Nación.',
    )
    beneficio = models.CharField(
        max_length=120,
        help_text='Lo que ve el cliente, ej. 20% de descuento / 3 y 6 cuotas sin interés.',
    )
    condiciones = models.TextField(
        blank=True,
        help_text='Letra chica: tope, tarjetas, no acumulable, etc.',
    )
    logo = models.ImageField(
        upload_to='promos_bancarias/',
        blank=True,
        null=True,
        help_text='Logo del banco. Si se deja vacío se usa un ícono genérico.',
    )
    lunes = models.BooleanField('Lunes', default=False)
    martes = models.BooleanField('Martes', default=False)
    miercoles = models.BooleanField('Miércoles', default=False)
    jueves = models.BooleanField('Jueves', default=False)
    viernes = models.BooleanField('Viernes', default=False)
    sabado = models.BooleanField('Sábado', default=False)
    domingo = models.BooleanField('Domingo', default=False)
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(
        default=0,
        help_text='Menor número aparece primero.',
    )
    vigente_desde = models.DateField(null=True, blank=True)
    vigente_hasta = models.DateField(null=True, blank=True)

    objects: PromocionBancariaQuerySet = PromocionBancariaQuerySet.as_manager()  # type: ignore[assignment]

    class Meta:
        ordering = ['orden', 'banco']
        verbose_name = 'promoción bancaria'
        verbose_name_plural = 'promociones bancarias'

    def __str__(self) -> str:
        return f'{self.banco} — {self.beneficio}'

    def aplica_en(self, weekday: int) -> bool:
        """True si esta promo corre el día indicado (0=lunes … 6=domingo)."""
        if weekday < 0 or weekday > 6:
            return False
        return bool(getattr(self, CAMPOS_DIA[weekday]))

    @property
    def etiquetas_dias(self) -> str:
        """Resumen corto para las cards: 'Lun · Mié · Vie'."""
        etiquetas = [
            ETIQUETAS_DIA[i]
            for i, campo in enumerate(CAMPOS_DIA)
            if getattr(self, campo)
        ]
        return ' · '.join(etiquetas) if etiquetas else 'Sin días asignados'

    @property
    def texto_vigencia(self) -> str:
        """Frase lista para mostrar: 'Vigente del 01/09 al 30/09', etc."""
        desde = self.vigente_desde
        hasta = self.vigente_hasta
        if desde and hasta:
            return f'Vigente del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}'
        if hasta:
            return f'Vigente hasta el {hasta:%d/%m/%Y}'
        if desde:
            return f'Vigente desde el {desde:%d/%m/%Y}'
        return 'Vigente'
