from __future__ import annotations

from django import forms
from django.utils import timezone

from sucursales.models import Sucursal

from .models import FranjaEnvio, Pedido


class CheckoutForm(forms.Form):
    """Datos del cliente y entrega. La validación de stock va en services.py."""

    nombre_cliente = forms.CharField(
        max_length=100,
        label='Nombre y apellido',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )
    telefono = forms.CharField(
        max_length=20,
        label='Teléfono / WhatsApp',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    modalidad_entrega = forms.ChoiceField(
        label='¿Cómo querés recibirlo?',
        choices=Pedido.ModalidadEntrega.choices,
        widget=forms.RadioSelect,
    )
    sucursal_retiro = forms.ModelChoiceField(
        label='Sucursal de retiro',
        queryset=Sucursal.objects.all(),
        required=False,
        empty_label='Elegí una sucursal',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    direccion_envio = forms.CharField(
        label='Dirección de envío',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )
    fecha_entrega = forms.DateField(
        label='Fecha de envío',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    franja_envio = forms.ModelChoiceField(
        label='Franja horaria',
        queryset=FranjaEnvio.objects.filter(activa=True),
        required=False,
        empty_label='Elegí un horario',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    medio_pago = forms.ChoiceField(
        label='Medio de pago',
        choices=Pedido.MedioPago.choices,
        required=False,
        widget=forms.RadioSelect,
    )
    notas = forms.CharField(
        label='Notas (opcional)',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def __init__(self, *args: object, es_encargue: bool = False, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.es_encargue = es_encargue
        if es_encargue:
            self.fields['medio_pago'].label = 'Medio de pago (cuando confirmemos el encargue)'
            self.fields['medio_pago'].required = True

    def clean(self) -> dict:
        datos = super().clean()
        if not isinstance(datos, dict):
            return datos

        modalidad = datos.get('modalidad_entrega')

        if modalidad == Pedido.ModalidadEntrega.RETIRO_SUCURSAL:
            if not datos.get('sucursal_retiro'):
                self.add_error('sucursal_retiro', 'Elegí una sucursal.')

        elif modalidad == Pedido.ModalidadEntrega.ENVIO:
            if not datos.get('direccion_envio', '').strip():
                self.add_error('direccion_envio', 'Ingresá la dirección.')
            if not datos.get('fecha_entrega'):
                self.add_error('fecha_entrega', 'Elegí una fecha.')
            elif datos['fecha_entrega'] < timezone.localdate():
                self.add_error('fecha_entrega', 'La fecha no puede ser anterior a hoy.')
            if not datos.get('franja_envio'):
                self.add_error('franja_envio', 'Elegí una franja horaria.')
            else:
                franja = datos['franja_envio']
                fecha = datos.get('fecha_entrega')
                if fecha and not franja.tiene_cupo(fecha):
                    self.add_error(
                        'franja_envio',
                        f'No hay cupo disponible en "{franja.nombre}" para esa fecha.',
                    )

        if not self.es_encargue and not datos.get('medio_pago'):
            self.add_error('medio_pago', 'Elegí un medio de pago.')
        if self.es_encargue and not datos.get('medio_pago'):
            self.add_error('medio_pago', 'Elegí cómo vas a pagar cuando confirmemos el encargue.')

        return datos
