from django.db import models


class Farmacia(models.Model):
    """Cualquier farmacia del pueblo que entra en la rotación de turnos.
    Si está vinculada a una de nuestras sucursales, se considera propia
    y la página la destaca (banner con link, badge en la tarjeta, etc.)."""

    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200, help_text='Dirección literal, ej: Avenida 18 758')
    sucursal = models.OneToOneField(
        'sucursales.Sucursal',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='farmacia_turno',
        help_text='Vincular solo si es una de nuestras sucursales (Astegiano / Komorovski)',
    )
    # Django crea este atributo en tiempo de ejecución para toda ForeignKey;
    # la anotación se lo hace saber al chequeador de tipos.
    sucursal_id: int | None  # pyright: ignore[reportUninitializedInstanceVariable]

    class Meta:
        verbose_name_plural = 'Farmacias'

    @property
    def es_propia(self) -> bool:
        return self.sucursal_id is not None

    def __str__(self) -> str:
        return str(self.nombre)


class Turno(models.Model):
    """Un día del calendario: qué farmacia está de turno esa fecha."""

    fecha = models.DateField(unique=True)
    farmacia = models.ForeignKey(Farmacia, on_delete=models.CASCADE, related_name='turnos')

    class Meta:
        ordering = ['fecha']
        verbose_name_plural = 'Turnos'

    def __str__(self) -> str:
        return f'{self.fecha} — {self.farmacia.nombre}'
