# Bots de revisión — Farmacia Astegiano & Komorovski

Tres system prompts para pegar en Grok Bot. No reemplazan al tester ni al de seguridad: cubren **reglas de la farmacia**, **dinero** y **calidad Django**.

| Orden | Archivo | Nombre sugerido en Grok | Cuándo |
|-------|---------|-------------------------|--------|
| 1 | [01-negocio.md](./01-negocio.md) | Farmacia · Reglas de negocio | Cada cambio en catálogo, carrito, inventario o pedidos |
| 2 | [02-pagos.md](./02-pagos.md) | Farmacia · Pagos / Mercado Pago | Si toca `pagos/`, webhooks, estados de pedido o `expirar_reservas` |
| 3 | [03-django-calidad.md](./03-django-calidad.md) | Farmacia · Django / calidad | Cualquier cambio de código Python o templates |

## Cómo cargarlos

1. Creá un bot nuevo.
2. Nombre y descripción: los del archivo.
3. Pegá **todo** el bloque `text` que dice **System prompt**.
4. El bot necesita permiso de escritura al repo (rama + pull request). Sin eso solo puede informar.

## Orden de uso

1. Negocio → si viola una regla de la farmacia, corrige y PR (o bloqueá el merge).
2. Pagos → solo si el diff toca plata o estados de cobro.
3. Django / calidad.
4. Tester (el que ya tenés).
5. Seguridad (el que ya tenés).

## Revisar y, si hace falta, abrir PR

El bot **siempre** entrega un informe (veredicto + hallazgos).

No abre PR por opiniones, nits de estilo, ni features de v1 fuera de alcance.

**Sí** abre PR cuando hay un defecto real (`BLOQUEA` o `RIESGO` que se arregla con código):

1. Rama nueva, nunca `main` / `master`.
2. Fix mínimo (no reescribir la feature).
3. Tests o ajuste de tests si el bug es cubrible.
4. Pull request con qué se rompía, qué cambió y cómo probarlo.

Convención de rama: `bot/<negocio|pagos|calidad>/<slug-corto>`
