"""Importación de stock desde CSV (espejo Praxys)."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from catalogo.models import Producto

from .models import ImportacionStock, StockWeb


@dataclass
class ResultadoImportacion:
    actualizados: int = 0
    omitidos: int = 0
    errores: list[str] = field(default_factory=list)


def calcular_stock_web(
    stock_praxys: int,
    margen_seguridad: int = 0,
    tope_web: int | None = None,
) -> int:
    """Fórmula del doc: min(tope_web, max(0, stock_praxys - margen))."""
    base = max(0, stock_praxys - margen_seguridad)
    if tope_web is not None:
        return min(tope_web, base)
    return base


def _buscar_producto(fila: dict[str, str]) -> Producto | None:
    """Cruce por sku → codigo_barras → codigo_praxys."""
    sku = fila.get('sku', '').strip()
    if sku:
        p = Producto.objects.filter(sku=sku).first()
        if p:
            return p

    barras = fila.get('codigo_barras', '').strip()
    if barras:
        p = Producto.objects.filter(codigo_barras=barras).first()
        if p:
            return p

    praxys = fila.get('codigo_praxys', '').strip()
    if praxys:
        return Producto.objects.filter(codigo_praxys=praxys).first()

    return None


def _parse_int(valor: str, default: int = 0) -> int:
    valor = (valor or '').strip()
    if not valor:
        return default
    return int(float(valor))


@transaction.atomic
def importar_stock_csv(ruta: str | Path) -> tuple[ImportacionStock, ResultadoImportacion]:
    """Lee CSV y actualiza StockWeb. No toca reservas activas."""
    path = Path(ruta)
    log = ImportacionStock.objects.create(
        fuente=ImportacionStock.Fuente.CSV,
        archivo=str(path.name),
    )
    resultado = ResultadoImportacion()

    try:
        with path.open(newline='', encoding='utf-8-sig') as archivo:
            reader = csv.DictReader(archivo)
            if not reader.fieldnames:
                raise ValueError('El CSV está vacío o sin encabezados.')

            for num, fila in enumerate(reader, start=2):
                try:
                    producto = _buscar_producto(fila)
                    if producto is None:
                        clave = (
                            fila.get('sku')
                            or fila.get('codigo_barras')
                            or fila.get('codigo_praxys')
                            or '?'
                        )
                        resultado.errores.append(f'Fila {num}: producto no encontrado ({clave})')
                        continue

                    if producto.tipo != Producto.Tipo.INMEDIATO:
                        resultado.omitidos += 1
                        continue

                    stock_praxys = _parse_int(fila.get('stock_praxys', '0'))
                    margen = _parse_int(fila.get('margen_seguridad', '0'))
                    tope_raw = (fila.get('tope_web') or '').strip()
                    tope = _parse_int(tope_raw) if tope_raw else None

                    cantidad = calcular_stock_web(stock_praxys, margen, tope)

                    stock, created = StockWeb.objects.get_or_create(
                        producto=producto,
                        defaults={'origen': StockWeb.Origen.CSV},
                    )
                    stock.cantidad = cantidad
                    stock.margen_seguridad = margen
                    if tope is not None:
                        stock.tope_web = tope
                    stock.origen = StockWeb.Origen.CSV
                    stock.save()
                    resultado.actualizados += 1

                except (ValueError, TypeError) as exc:
                    resultado.errores.append(f'Fila {num}: {exc}')

        log.ok = len(resultado.errores) == 0
        log.detalle = (
            f'Actualizados: {resultado.actualizados}\n'
            f'Omitidos (encargue): {resultado.omitidos}\n'
            + '\n'.join(resultado.errores[:50])
        )
        if len(resultado.errores) > 50:
            log.detalle += f'\n... y {len(resultado.errores) - 50} errores más.'

    except OSError as exc:
        log.ok = False
        log.detalle = str(exc)
        resultado.errores.append(str(exc))

    log.finalizada_en = timezone.now()
    log.save()
    return log, resultado
