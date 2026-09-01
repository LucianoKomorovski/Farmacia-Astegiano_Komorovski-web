# Arquitectura — Tienda online (Farmacias Astegiano & Komorovski)

Documento vivo. Refleja las decisiones acordadas (ago 2026).  
Relacionado: [modelo-datos-tienda.md](./modelo-datos-tienda.md)

---

## 1. Contexto

El sitio actual es institucional (sucursales, turnos, servicios, sobre nosotros).  
Se agregó una **tienda Django nativa** en el mismo proyecto, sin mezclar la lógica de turnos/contenido con pedidos/pagos/stock.

**Restricción fuerte:** probablemente no hay acceso de escritura (ni tal vez lectura en tiempo real) a la DB del sistema de gestión farmacéutico (Observer Praxys). El stock de la web será un **espejo conservador** (API si existe, o CSV periódico).

---

## 2. Decisiones cerradas

| Tema | Decisión |
|------|----------|
| Stack | Django nativo (mismo repo / mismo sitio) |
| Catálogo | Compartido entre ambas sucursales (v1) |
| Productos | Solo **sin receta** (OTC / parafarmacia). Receta fuera de alcance |
| Efectivo | **No** (evita reservas fantasmas todo el día) |
| Pagos | Online: crédito, débito, Mercado Pago, transferencia |
| Venta inmediata | Cierre automático si pago MP/tarjeta OK |
| Transferencia | Queda pendiente hasta que **cualquier staff** confirme |
| Encargue | Staff confirma que se puede → **recién ahí** se cobra |
| Mixto inmediato+encargue | **Evitar en v1** (un modo por carrito) |
| Retiro | Cliente elige sucursal **o** “a coordinar” |
| Envío | Sí, con **2 franjas horarias por día** |
| Reserva de stock | TTL **1 hora** máximo |
| Confirmación pedidos | Auto salvo transferencia o encargue |
| Staff | Cualquier usuario staff puede confirmar |

---

## 3. Mapa del sistema

```text
┌─────────────────────────────────────────────────────────────┐
│  Sitio público (existente)                                  │
│  home · turnos · sucursales · servicios · about             │
└─────────────────────────────────────────────────────────────┘
                              │
                              │  nav “Tienda”
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Tienda                                                     │
│  catálogo → carrito → checkout → pago → pedido → fulfillment│
└───────────────┬─────────────────────────────┬───────────────┘
                │                             │
                ▼                             ▼
        ┌───────────────┐            ┌────────────────┐
        │ Inventario web│            │ Panel staff    │
        │ (espejo)      │            │ Django admin   │
        └───────▲───────┘            └────────────────┘
                │
     API Praxys / CSV (~1h) — pendiente
                │
        ┌───────┴───────┐
        │ Observer Praxys│  (fuente real del mostrador)
        └───────────────┘
```

### Apps Django (implementadas)

| App | Responsabilidad | Estado |
|-----|-----------------|--------|
| `catalogo` | Productos, categorías, precios, tipo inmediato/encargue | ✅ |
| `inventario` | `StockWeb`, `ReservaStock` (TTL 1 h), importador CSV, admin | ✅ parcial (API Praxys pendiente) |
| `carrito` | Líneas de sesión/usuario, modo único | ✅ |
| `pedidos` | Pedido, líneas, checkout, franjas, estados | ✅ |
| `pagos` | Mercado Pago Checkout Pro, webhooks, transferencias | ✅ |
| (existente) `sucursales` | Puntos de retiro | ✅ reutilizado |

**URLs públicas**

| Ruta | Vista |
|------|-------|
| `/tienda/` | Catálogo |
| `/carrito/` | Ver / editar carrito |
| `/pedidos/checkout/` | Formulario de entrega y pago |
| `/pedidos/<numero>/confirmacion/` | Estado del pedido |
| `/pagos/pagar/<numero>/` | Redirige a Mercado Pago |
| `/pagos/webhook/` | Notificaciones IPN (MP) |

---

## 4. Tipos de producto y de pedido

### Producto

- **Inmediato:** vende contra `stock_web` disponible (cantidad − reservas activas).
- **Encargue:** no exige stock web; requiere confirmación humana antes del cobro.

### Pedido (v1)

- Carrito **solo inmediato** o **solo encargue** (sin mixto).
- Simplifica pagos y estados.

---

## 5. Modalidad de entrega (checkout)

El cliente elige **una**:

1. **Retiro en sucursal** → elige Astegiano o Komorovski.  
2. **A coordinar** → sin sucursal fija; staff contacta.  
3. **Envío a domicilio** → fecha + **una de dos franjas** del día.

Las franjas son configuración en admin (`FranjaEnvio`). Migración inicial crea “Mañana” y “Tarde”.

---

## 6. Máquina de estados del pedido

```text
carrito
  → pendiente_pago                 # reserva stock inmediato (TTL 1h)
       │
       ├─ MP/tarjeta OK (solo inmediato) ──→ confirmado
       │
       ├─ transferencia ──→ pendiente_transferencia
       │                      └─ staff OK ──→ confirmado
       │                      └─ timeout/rechazo ──→ cancelado (libera)
       │
       └─ (solo encargue: aún sin cobro) ──→ pendiente_encargue
              └─ staff OK ──→ pendiente_pago_encargue (o pendiente_transferencia)
                    └─ cliente paga MP/tarjeta/transf* ──→ confirmado

confirmado → en_preparacion → listo_retiro | despachado → entregado
```

### Regla de auto-confirmación

Auto → `confirmado` **solo si**:

1. Pedido solo inmediato (o encargue ya aprobado),  
2. Medio ≠ transferencia,  
3. Pago aprobado por Mercado Pago (webhook),  
4. Reserva de stock vigente y consolidable.

En cualquier otro caso: cola staff (admin).

---

## 7. Pagos

| Medio | Cómo confirma |
|-------|----------------|
| Crédito / débito / Mercado Pago | Checkout Pro + webhook (`/pagos/webhook/`) |
| Transferencia | Staff en admin (acción “Confirmar transferencia”) |

**Encargue:** no se cobra al crear el pedido. Flujo: staff aprueba encargue → cliente paga → `confirmado`.

**Transferencia + TTL:** si en 1 hora no hay confirmación, `expirar_reservas` cancela el pedido y libera stock.

### Variables de entorno (`backend/.env`)

```text
MERCADOPAGO_ACCESS_TOKEN=
MERCADOPAGO_PUBLIC_KEY=
MERCADOPAGO_WEBHOOK_SECRET=
TRANSFERENCIA_ALIAS=
TRANSFERENCIA_CBU=
RESERVA_STOCK_TTL_MINUTOS=60
```

Plantilla documentada en `backend/.env.example`.

### Seguridad pagos

- Webhook **sin CSRF** pero con validación **HMAC** (`x-signature`) si hay `MERCADOPAGO_WEBHOOK_SECRET`.
- Confirmación de pedido **idempotente** (reintentos de webhook no duplican).
- Vista de pedido protegida: solo dueño de sesión, usuario logueado o staff.

---

## 8. Inventario espejo

```text
Praxys  →  (API o CSV ~cada 1h)  →  importador Django  [pendiente]
                                      → stock_web = f(stock_real)
```

**Implementado hoy:**

- `StockWeb`: cupo manual en admin (inline en producto).
- `ReservaStock`: al checkout inmediato se **reserva** (no descuenta); al confirmar pago se **consolida** (baja `cantidad`).
- Comando cron: `python manage.py expirar_reservas` (cada ~15 min).

Disponible para vender ≈ `cantidad − sum(reservas activas no vencidas)`.

---

## 9. Roles y panel staff

| Actor | Puede |
|-------|--------|
| Cliente | Navegar, comprar, elegir entrega, pagar |
| Staff (cualquiera) | Admin: confirmar transferencias, aprobar encargues, avanzar fulfillment, cancelar |
| Sistema | Auto-confirmar ventas con pago MP OK; expirar reservas 1h |

**Acciones en admin → Pedidos:**

- Confirmar transferencia recibida  
- Aprobar encargue (habilitar pago)  
- Cancelar pedido (libera stock)  
- Marcar en preparación / listo retiro / despachado / entregado  

---

## 10. Fuera de alcance (v1)

- Stock por sucursal  
- Escritura/reserva en Praxys  
- Venta con receta  
- Carritos mixtos inmediato + encargue  
- Efectivo  
- Importador CSV/API Praxys  
- Costo de envío dinámico (hoy en `ENVIO_MONTO_FIJO` / `ENVIO_GRATIS_DESDE` en settings)

---

## 11. Criterios de éxito v1

| Criterio | Estado |
|----------|--------|
| Pedido inmediato + MP se confirma solo y descuenta stock web | ✅ (con credenciales MP) |
| Transferencia no confirma sin staff; libera a la 1h | ✅ |
| Encargue no cobra hasta OK de staff | ✅ |
| Checkout permite sucursal, “a coordinar” o envío con franja | ✅ |
| Catálogo sin productos con receta | ✅ |

---

## 12. Próximos pasos sugeridos

1. Reunión Praxys → importador API de stock (CSV ya disponible: `importar_stock_csv`)  
2. Configurar credenciales MP en producción + webhook público HTTPS → [deploy-produccion.md](./deploy-produccion.md)  
3. Cron `expirar_reservas` en el servidor  
4. `EventoPedido` (auditoría opcional)  
5. Notificaciones push / SMS (email y WhatsApp ya implementados)  

Guía sandbox local: [guia-sandbox-mp.md](./guia-sandbox-mp.md)
