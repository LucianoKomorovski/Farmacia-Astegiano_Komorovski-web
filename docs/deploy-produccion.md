# Guía — Deploy en producción (Fase 2)

## Variables de entorno obligatorias

```text
SECRET_KEY=<clave-larga-aleatoria>
DEBUG=False
ALLOWED_HOSTS=tudominio.com,www.tudominio.com
CSRF_TRUSTED_ORIGINS=https://tudominio.com,https://www.tudominio.com

MERCADOPAGO_ACCESS_TOKEN=<token-produccion>
MERCADOPAGO_WEBHOOK_SECRET=<secret-del-panel-MP>
TRANSFERENCIA_ALIAS=<alias-real>
TRANSFERENCIA_CBU=<cbu-real>
WHATSAPP_TIENDA=5493471543210

ENVIO_MONTO_FIJO=1500
ENVIO_GRATIS_DESDE=15000

# Email SMTP (opcional pero recomendado)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.tuproveedor.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DEFAULT_FROM_EMAIL=tienda@tudominio.com
```

## Checklist Django

```bash
cd backend
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
```

## Webhook Mercado Pago

URL fija en el panel de MP:

```text
https://tudominio.com/pagos/webhook/
```

Eventos: `payment` (pagos).

## Cron — expirar reservas de stock

Cada 15 minutos en el servidor:

```cron
*/15 * * * * cd /ruta/al/proyecto/backend && /ruta/venv/bin/python manage.py expirar_reservas >> /var/log/farmacia-expirar.log 2>&1
```

## Capacitación staff (5 min)

1. Entrar a `/admin/` con usuario staff
2. **Pedidos** → filtrar por `pendiente_transferencia` o `pendiente_encargue`
3. Seleccionar pedidos → acción correspondiente:
   - Confirmar transferencia recibida
   - Aprobar encargue
   - Marcar en preparación → listo retiro / despachado → entregado

## Servidor WSGI (ejemplo gunicorn)

```bash
gunicorn FarmaciaAstegiano.wsgi:application --bind 0.0.0.0:8000 --chdir backend
```

Nginx (o similar) debe servir `/static/` y `/media/` y hacer proxy HTTPS al socket de gunicorn.
