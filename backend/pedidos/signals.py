"""Señales: notificar al cliente cuando cambia el estado del pedido."""

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import Pedido
from .notifications import enviar_email_cambio_estado


@receiver(pre_save, sender=Pedido)
def guardar_estado_anterior(sender, instance: Pedido, **kwargs) -> None:
    if instance.pk:
        instance._estado_anterior = (  # type: ignore[attr-defined]
            Pedido.objects.filter(pk=instance.pk).values_list('estado', flat=True).first()
        )
    else:
        instance._estado_anterior = None  # type: ignore[attr-defined]


@receiver(post_save, sender=Pedido)
def notificar_cambio_estado(sender, instance: Pedido, created: bool, **kwargs) -> None:
    if created:
        return
    anterior = getattr(instance, '_estado_anterior', None)
    enviar_email_cambio_estado(instance, anterior)
