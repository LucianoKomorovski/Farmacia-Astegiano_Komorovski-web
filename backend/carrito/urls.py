from django.urls import path

from . import views

urlpatterns = [
    path('', views.ver_carrito, name='carrito_ver'),
    path('agregar/<slug:slug>/', views.agregar_al_carrito, name='carrito_agregar'),
    path('linea/<int:linea_id>/actualizar/', views.actualizar_linea, name='carrito_actualizar'),
    path('linea/<int:linea_id>/eliminar/', views.eliminar_linea, name='carrito_eliminar'),
]
