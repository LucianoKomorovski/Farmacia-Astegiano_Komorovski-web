from django.db import models
from django.db.models import QuerySet
from django.utils.text import slugify


class Categoria(models.Model):
    """Agrupa productos del catálogo web (dermocosmética, higiene, etc.)."""

    nombre = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    activa = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(
        default=0,
        help_text='Menor número aparece primero en el listado.',
    )

    class Meta:
        ordering = ['orden', 'nombre']
        verbose_name = 'categoría'
        verbose_name_plural = 'categorías'

    def __str__(self) -> str:
        return str(self.nombre)

    def save(self, *args: object, **kwargs: object) -> None:
        # Si no cargaron slug a mano, lo armamos a partir del nombre.
        if not self.slug:
            self.slug = slugify(self.nombre)
        super().save(*args, **kwargs)


class ProductoQuerySet(QuerySet['Producto']):
    """Filtros reutilizables: el catálogo público nunca muestra receta."""

    def visibles_en_tienda(self) -> QuerySet['Producto']:
        return self.filter(activo=True, requiere_receta=False)


class Producto(models.Model):
    """Ítem del catálogo compartido entre ambas sucursales."""

    class Tipo(models.TextChoices):
        INMEDIATO = 'inmediato', 'Venta inmediata (con stock web)'
        ENCARGUE = 'encargue', 'A encargue (confirma staff, después se cobra)'

    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='productos',
    )
    # Django crea categoria_id en runtime; esto ayuda al type checker.
    categoria_id: int | None  # pyright: ignore[reportUninitializedInstanceVariable]

    nombre = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    descripcion = models.TextField(blank=True)

    sku = models.CharField(
        max_length=50,
        unique=True,
        help_text='Código interno de la web (único).',
    )
    codigo_barras = models.CharField(
        max_length=50,
        blank=True,
        help_text='Para cruzar con Praxys cuando haya sync.',
    )
    codigo_praxys = models.CharField(
        max_length=50,
        blank=True,
        help_text='Id del producto en Observer Praxys, si se conoce.',
    )

    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.INMEDIATO,
    )
    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Precio de venta en la web.',
    )
    imagen = models.ImageField(upload_to='catalogo/', blank=True, null=True)

    # Si es True, no se vende online (la receta queda fuera de alcance en v1).
    requiere_receta = models.BooleanField(default=False)
    activo = models.BooleanField(
        default=True,
        help_text='Desactivar oculta el producto en la tienda sin borrarlo.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects: ProductoQuerySet = ProductoQuerySet.as_manager()  # type: ignore[assignment]

    class Meta:
        ordering = ['nombre']
        verbose_name = 'producto'
        verbose_name_plural = 'productos'

    def __str__(self) -> str:
        return str(self.nombre)

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.slug:
            self.slug = slugify(self.nombre)
        super().save(*args, **kwargs)

    @property
    def es_encargue(self) -> bool:
        return self.tipo == self.Tipo.ENCARGUE

    @property
    def visible_en_tienda(self) -> bool:
        return self.activo and not self.requiere_receta
