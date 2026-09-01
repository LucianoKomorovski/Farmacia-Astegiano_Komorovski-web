from django.urls import path

from .views import ProductoDetailView, ProductoListView

# name= es el alias para {% url 'catalogo_lista' %} en los templates.
urlpatterns = [
    path('', ProductoListView.as_view(), name='catalogo_lista'),
    path('<slug:slug>/', ProductoDetailView.as_view(), name='catalogo_detalle'),
]
