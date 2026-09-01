# Guía — Probar pagos en local (Fase 1)

## 1. Datos de prueba

```bash
cd backend
python manage.py migrate
python manage.py seed_datos
```

Crea productos con stock, franjas de envío y usuario staff (`staff` / `staff1234`).

## 2. Mercado Pago sandbox

1. Crear cuenta en [developers.mercadopago.com](https://www.mercadopago.com.ar/developers)
2. Crear aplicación → copiar **Access Token de prueba**
3. En `backend/.env`:

```text
MERCADOPAGO_ACCESS_TOKEN=TEST-...
TRANSFERENCIA_ALIAS=farmacia.test
TRANSFERENCIA_CBU=0000000000000000000000
```

4. Reiniciar `runserver`

## 2b. Por qué no redirige a MP en localhost

Si en la consola del `runserver` ves:

```text
MP preference error: auto_return invalid. back_url.success must be defined
```

**No es un problema de credenciales.** Mercado Pago rechaza `back_urls`, `notification_url` y `auto_return` con `http://127.0.0.1`. En local el código crea la preferencia **solo con items** (sin URLs de retorno); podés pagar en el sandbox y volver manualmente a la página de confirmación.

| Modo | `SITE_URL` | URLs en preferencia | Confirmación del pedido |
|------|------------|---------------------|------------------------|
| Local rápido | vacío | ninguna (solo checkout MP) | `python manage.py simular_pago FA-...` |
| Local completo | ngrok HTTPS | back_urls + webhook | automática vía webhook |
| Producción | dominio real | back_urls + webhook | automática |

Si el pedido quedó en `pendiente_pago`, usá el botón **Pagar con Mercado Pago** en la página de confirmación (no hace falta recomprar).

## 3. Probar los 3 flujos

| Flujo | Pasos |
|-------|-------|
| **Inmediato + MP** | `/tienda/` → carrito → checkout → MP sandbox (tarjeta de prueba) |
| **Inmediato + transferencia** | Checkout con transferencia → admin confirma |
| **Encargue** | Producto encargue → checkout → admin aprueba → cliente paga |

Tarjetas de prueba MP: [documentación oficial](https://www.mercadopago.com.ar/developers/es/docs/checkout-pro/additional-content/test-cards).

## 4. Webhook en local (ngrok)

Mercado Pago necesita HTTPS público para notificar pagos:

```bash
# Terminal 1
python manage.py runserver

# Terminal 2
ngrok http 8000
```

1. Copiar URL HTTPS de ngrok (ej. `https://abc123.ngrok-free.app`)
2. En `.env` agregar:

```text
SITE_URL=https://abc123.ngrok-free.app
EXTRA_ALLOWED_HOSTS=abc123.ngrok-free.app
```

3. Reiniciar runserver
4. En MP Developers → Webhooks → URL: `https://abc123.ngrok-free.app/pagos/webhook/`
5. Copiar secret → `MERCADOPAGO_WEBHOOK_SECRET=...`

Sin webhook, el redirect del navegador muestra éxito pero el pedido puede quedar en `pendiente_pago` hasta que llegue la notificación.

## 5. Simular pago sin MP (solo DEBUG)

```bash
python manage.py simular_pago FA-2026-000001
```

Confirma el pedido sin pasar por Mercado Pago (útil para probar stock y admin).

## 6. Probar TTL de reservas

```bash
python manage.py expirar_reservas
```

Cancela pedidos `pendiente_pago` / `pendiente_transferencia` con reserva vencida y libera stock.
