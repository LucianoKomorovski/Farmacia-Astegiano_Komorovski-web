from django.shortcuts import render

from .models import SobreNosotros


def sobre_nosotros(request):
    context = {
        'items': SobreNosotros.objects.all(),
    }
    return render(request, 'aboutUs/sobre_nosotros.html', context)
