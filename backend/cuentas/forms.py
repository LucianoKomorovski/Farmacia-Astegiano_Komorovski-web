from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class RegistroForm(UserCreationForm):
    """Alta de cliente: usuario + email obligatorio y único + contraseña (x2).

    UserCreationForm ya trae username, password1 y password2 con todas las
    validaciones de Django (largo mínimo, contraseñas comunes, etc.).
    """

    email = forms.EmailField(
        required=True,
        label='Email',
        help_text='Lo usamos para avisarte el estado de tus pedidos.',
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def clean_email(self) -> str:
        # iexact = comparar sin distinguir mayúsculas (Juan@x.com == juan@x.com).
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ya existe una cuenta con ese email.')
        return email