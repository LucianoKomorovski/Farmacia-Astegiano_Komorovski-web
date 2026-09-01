from django.urls import path

from . import views

urlpatterns = [
    path('pagar/<str:numero>/', views.iniciar_pago, name='pagos_iniciar'),
    path(
        'retorno/<str:numero>/<str:resultado>/',
        views.retorno_mp,
        name='pagos_retorno',
    ),
    path('webhook/', views.webhook_mp, name='pagos_webhook'),
]
