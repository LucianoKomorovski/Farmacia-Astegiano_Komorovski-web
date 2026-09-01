from django.urls import path

from . import views

urlpatterns = [
    path('checkout/', views.checkout, name='pedido_checkout'),
    path('mis-pedidos/', views.mis_pedidos, name='pedido_mis_pedidos'),
    path('<str:numero>/confirmacion/', views.confirmacion, name='pedido_confirmacion'),
]
