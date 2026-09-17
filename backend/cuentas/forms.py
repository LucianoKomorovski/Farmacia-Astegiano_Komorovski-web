from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from sucursales.models import Sucursal

from .models import PerfilStaff


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


class SolicitudStaffForm(RegistroForm):
    """Solicitud de acceso al panel para PERSONAL de la farmacia.

    Crea el User (sin is_staff) y, aparte, la vista crea el PerfilStaff en
    estado PENDIENTE con los campos extra de este formulario.
    """

    first_name = forms.CharField(label='Nombre', max_length=150)
    last_name = forms.CharField(label='Apellido', max_length=150)
    telefono = forms.CharField(
        label='Teléfono / WhatsApp',
        max_length=20,
        required=False,
        help_text='Para que los dueños puedan contactarte si hace falta.',
    )
    sucursal = forms.ModelChoiceField(
        label='Sucursal donde trabajás',
        queryset=Sucursal.objects.all(),
        required=False,
        empty_label='Ambas / no aplica',
    )
    mensaje = forms.CharField(
        label='Mensaje para los dueños',
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Ej: "Soy la nueva empleada de la tarde en Komorovski".',
    )

    class Meta(RegistroForm.Meta):
        fields = ('username', 'first_name', 'last_name', 'email')

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        # El texto de ayuda del email heredado habla de pedidos; acá es otro contexto.
        self.fields['email'].help_text = 'Te avisamos por acá cuando aprueben tu acceso.'

    def save(self, commit: bool = True) -> User:
        # El User se crea como cliente común: sin is_staff hasta ser aprobado.
        user = super().save(commit=False)
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user

    def crear_perfil(self, user: User) -> PerfilStaff:
        """PerfilStaff pendiente con los datos extra del formulario."""
        return PerfilStaff.objects.create(
            usuario=user,
            rol=PerfilStaff.Rol.EMPLEADA,
            estado=PerfilStaff.Estado.PENDIENTE,
            sucursal=self.cleaned_data.get('sucursal'),
            telefono=self.cleaned_data.get('telefono', '').strip(),
            mensaje=self.cleaned_data.get('mensaje', '').strip(),
        )
