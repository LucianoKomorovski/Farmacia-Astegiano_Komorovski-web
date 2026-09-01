# Modelo de datos — Tienda online

Estado de implementación (ago 2026).  
Alineado a [arquitectura-tienda.md](./arquitectura-tienda.md).

**Leyenda:** ✅ implementado · ⏳ parcial · ❌ pendiente

Convenciones:

- Prefijo mental de app entre paréntesis.  
- `sucursales.Sucursal` ya existe; se reutiliza.  
- IDs internos Django; `sku` / `codigo_barras` para cruzar con Praxys.

---

## Diagrama (relaciones)

```text
Categoria 1──* Producto
Producto 1──0..1 StockWeb
Producto 1──* ReservaStock
Producto 1──* LineaCarrito ──* Carrito
Producto 1──* LineaPedido ──* Pedido
Pedido 1──* Pago
Pedido 0..1── Sucursal (retiro; null si a_coordinar o envío)
Pedido 0..1── FranjaEnvio (solo si modalidad=envio)
ImportacionStock (log de importaciones CSV)
```

---

## Estado por entidad

| Entidad | App | Estado |
|---------|-----|--------|
| `Categoria` | `catalogo` | ✅ |
| `Producto` | `catalogo` | ✅ |
| `StockWeb` | `inventario` | ✅ |
| `ReservaStock` | `inventario` | ✅ |
| `ImportacionStock` | `inventario` | ✅ (CSV; API Praxys ❌) |
| `Carrito` / `LineaCarrito` | `carrito` | ✅ |
| `FranjaEnvio` | `pedidos` | ✅ (+ `cupo_max`) |
| `Pedido` / `LineaPedido` | `pedidos` | ✅ |
| `Pago` | `pagos` | ✅ |
| `EventoPedido` | — | ❌ (opcional v1) |
| `ConfigEnvio` | — | ⏳ (settings `ENVIO_MONTO_FIJO` / `ENVIO_GRATIS_DESDE`) |

---

## 1. Catálogo ✅

### `Categoria` (`catalogo`)

| Campo | Tipo | Notas |
|-------|------|--------|
| nombre | CharField | |
| slug | SlugField | unique |
| activa | Boolean | default True |
| orden | PositiveInt | |

### `Producto` (`catalogo`)

| Campo | Tipo | Notas |
|-------|------|--------|
| categoria | FK → Categoria | null/blank OK |
| nombre | CharField | |
| slug | SlugField | unique |
| descripcion | TextField | |
| sku | CharField | unique; código interno web |
| codigo_barras | CharField | null; cruce Praxys |
| codigo_praxys | CharField | null; id del sistema de gestión |
| tipo | CharField choices | `inmediato` \| `encargue` |
| precio | Decimal | precio web |
| imagen | ImageField | null |
| requiere_receta | Boolean | default False; si True no vender online |
| activo | Boolean | visible en tienda |
| created_at / updated_at | DateTime | |

**Reglas implementadas:**

- Si `requiere_receta=True` → excluido del catálogo público (`visibles_en_tienda()`).  
- `tipo=encargue` → no exige stock para agregar al carrito.  
- `tipo=inmediato` → exige stock disponible (cantidad − reservas activas).

---

## 2. Inventario ✅

### `StockWeb` (`inventario`)

| Campo | Tipo | Notas |
|-------|------|--------|
| producto | OneToOne → Producto | |
| cantidad | PositiveInt | unidades publicables |
| tope_web | PositiveInt | null; máximo a publicar |
| margen_seguridad | PositiveInt | default 0; usado al importar |
| actualizado_en | DateTime | |
| origen | CharField | `manual` \| `csv` \| `api` |

**Disponible para vender** = `cantidad − sum(reservas activas no vencidas)`.

### `ReservaStock` (`inventario`) ✅

| Campo | Tipo | Notas |
|-------|------|--------|
| producto | FK → Producto | |
| pedido | FK → Pedido | |
| cantidad | PositiveInt | |
| estado | CharField | `activa` \| `consolidada` \| `liberada` \| `expirada` |
| expires_at | DateTime | **now + 1 hora** al crear |
| created_at | DateTime | |

Comando: `python manage.py expirar_reservas` (cron cada ~15 min).

### `ImportacionStock` (`inventario`) ✅

| Campo | Tipo | Notas |
|-------|------|--------|
| fuente | CharField | `csv` \| `api` |
| archivo | CharField | nombre del archivo importado |
| iniciada_en / finalizada_en | DateTime | |
| ok | Boolean | |
| detalle | TextField | errores / conteos |

Comando: `python manage.py importar_stock_csv docs/ejemplo-stock.csv`  
CSV ejemplo: [ejemplo-stock.csv](./ejemplo-stock.csv)

---

## 3. Carrito ✅

### `Carrito` (`carrito`)

| Campo | Tipo | Notas |
|-------|------|--------|
| usuario | FK User | null si anónimo |
| session_key | CharField | null; carritos guest |
| modo | CharField | `inmediato` \| `encargue` (fijo en v1) |
| updated_at | DateTime | |

### `LineaCarrito`

| Campo | Tipo | Notas |
|-------|------|--------|
| carrito | FK | |
| producto | FK | |
| cantidad | PositiveInt | |
| precio_unitario | Decimal | snapshot al agregar |

Unique `(carrito, producto)`.

---

## 4. Pedidos ✅

### `FranjaEnvio` (`pedidos`)

| Campo | Tipo | Notas |
|-------|------|--------|
| nombre | CharField | ej. “Mañana”, “Tarde” |
| hora_desde | Time | |
| hora_hasta | Time | |
| cupo_max | PositiveInt | null = sin límite; validado en checkout |
| activa | Boolean | |
| orden | PositiveInt | |

### `Pedido` (`pedidos`)

| Campo | Tipo | Notas |
|-------|------|--------|
| numero | CharField | unique legible (ej. FA-2026-000123) |
| usuario | FK User | null OK (guest + email) |
| email | EmailField | contacto |
| telefono | CharField | |
| nombre_cliente | CharField | |
| estado | CharField | ver enum abajo |
| modo | CharField | `inmediato` \| `encargue` |
| modalidad_entrega | CharField | `retiro_sucursal` \| `a_coordinar` \| `envio` |
| sucursal_retiro | FK Sucursal | null si no aplica |
| franja_envio | FK FranjaEnvio | null si no envío |
| fecha_entrega | Date | null |
| direccion_envio | TextField | null |
| medio_pago | CharField | mercadopago / credito / debito / transferencia |
| notas | TextField | blank |
| subtotal / costo_envio / total | Decimal | |
| reservado_hasta | DateTime | null; TTL reserva stock |
| confirmado_en | DateTime | null |
| created_at / updated_at | DateTime | |

#### Estados (`estado`) — todos implementados

| Valor | Quién lo setea |
|-------|----------------|
| `pendiente_pago` | checkout |
| `pendiente_transferencia` | eligió transferencia |
| `pendiente_encargue` | modo encargue |
| `pendiente_pago_encargue` | staff OK encargue |
| `confirmado` | auto (MP) o staff (transferencia) |
| `en_preparacion` | staff |
| `listo_retiro` | staff |
| `despachado` | staff |
| `entregado` | staff |
| `cancelado` | staff / sistema (TTL) |

Vista historial: `/pedidos/mis-pedidos/` (usuario logueado).

---

## 5. Pagos ✅

### `Pago` (`pagos`)

| Campo | Tipo | Notas |
|-------|------|--------|
| pedido | FK | |
| medio | CharField | `mercadopago` \| `credito` \| `debito` \| `transferencia` |
| estado | CharField | `pendiente` \| `aprobado` \| `rechazado` \| `reembolsado` |
| monto | Decimal | |
| id_externo | CharField | id MP |
| raw_payload | JSONField | webhook / respuesta |
| confirmado_por | FK User | null; staff en transferencia |
| confirmado_en | DateTime | null |
| created_at | DateTime | |

Integración: Mercado Pago Checkout Pro + webhook `/pagos/webhook/`.  
Dev: `python manage.py simular_pago FA-2026-000001` (solo DEBUG).

---

## 6. Configuración (.env)

```text
MERCADOPAGO_ACCESS_TOKEN=
MERCADOPAGO_WEBHOOK_SECRET=
TRANSFERENCIA_ALIAS=
TRANSFERENCIA_CBU=
RESERVA_STOCK_TTL_MINUTOS=60
ENVIO_MONTO_FIJO=1500
ENVIO_GRATIS_DESDE=15000
WHATSAPP_TIENDA=5493471543210
EMAIL_HOST=...
DEFAULT_FROM_EMAIL=tienda@tudominio.com
```

Plantilla: `backend/.env.example`  
Guías: [guia-sandbox-mp.md](./guia-sandbox-mp.md) · [deploy-produccion.md](./deploy-produccion.md)

---

## 7. Invariantes (respetadas en código)

1. Carrito/pedido v1: un solo `modo`. ✅  
2. Inmediato: no confirmar sin reservas consolidables. ✅  
3. TTL reservas = 1 hora (configurable). ✅  
4. Encargue: no crear `Pago` cobrable hasta OK staff. ✅  
5. `requiere_receta=True` nunca en listados públicos. ✅  
6. Transferencia: `confirmado` solo con staff. ✅  

---

## 8. Pendiente futuro

- `EventoPedido` (auditoría staff)  
- Importador API Praxys (hoy solo CSV)  
- Stock por sucursal  
- Modelo `ConfigEnvio` en DB (hoy en settings)
