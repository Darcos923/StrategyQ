from __future__ import annotations

import os
import zipfile
import xml.etree.ElementTree as ET
import re, json, difflib
import json
import logging

from pathlib import Path
from typing import Dict, List, Tuple


# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)


def get_mt5_indicators(indicators_path: str = None) -> list[str]:
    # Define the path to the Indicators folder
    indicators_path = Path(indicators_path) if indicators_path else Path("./Indicators")

    # List to store .ex5 file names
    mt5_indicators = []

    try:
        # Check if the directory exists
        if os.path.exists(indicators_path):
            # Walk through the directory
            for _, _, files in os.walk(indicators_path):
                # Filter files with .ex5 extension
                mt5_indicators.extend(
                    [file.split(".")[0] for file in files if file.endswith(".ex5")]
                )

        return mt5_indicators
    except Exception as e:
        print(f"Error accessing Indicators folder or creating txt file: {str(e)}")
        return []


def get_sqx_indicators(
    block_settings_path: str | Path,
    xml_path: str,
    include_only_used: bool = False,
) -> list[str]:
    """
    Devuelve la lista de indicadores SQX presentes en un BlockSettings.sqb.

    Args:
        block_settings_path: Ruta al archivo .sqb.
        xml_path:            Ruta interna del XML dentro del zip.
        include_only_used:   Si True, sólo devuelve los marcados con use="true".
    """
    # — leer XML —
    try:
        with zipfile.ZipFile(block_settings_path, "r") as z:
            xml_bytes = z.read(xml_path)
    except KeyError as exc:
        raise FileNotFoundError(
            f"'{xml_path}' no encontrado en {block_settings_path}"
        ) from exc

    root = ET.fromstring(xml_bytes)

    indicators: set[str] = set()

    # — recorrer bloques —
    for block in root.findall(".//Block"):
        key = block.get("key", "")
        if not key.startswith("Indicators."):
            continue

        attrs = {k.lower(): v.lower() for k, v in block.attrib.items()}
        flag = attrs.get("use") or attrs.get("enabled") or attrs.get("selected")

        if include_only_used and flag not in {"true", "1"}:
            continue  # ignoramos los no marcados

        indicators.add(key.split(".", 1)[1])  # quitamos 'Indicators.'

    return sorted(indicators)


def mapping_indicators(
    sqx_indicators: list, mt5_indicators: list, output_file: str | Path
) -> dict:
    OUT_FILE = Path(output_file)

    # ───────────────────────────── util ─────────────────────────────
    def normalize(s: str) -> str:
        """Minúsculas y solo letras-dígitos para comparar sin ruido."""
        return re.sub(r"[^a-z0-9]", "", s.lower().strip())

    # quitar prefijo Sq para comparar, pero guardamos el *original* para el valor
    mt5_tuples = [
        (normalize(ln[2:] if ln.lower().startswith("sq") else ln), ln)
        for ln in mt5_indicators
    ]
    norm_to_mt5 = dict(mt5_tuples)  # normalizado → original
    all_norm_keys = list(norm_to_mt5.keys())

    # ───────────── alias manual (claves y valores normalizados) ─────────────
    RAW_MANUAL = {
        "WilliamsPR": "SqWpr",
        "LinearRegression": "LinReg",
        "SMA": "Custom Moving Average",
        "SMMA": "null",
        "EMA": "null",
        "LWMA": "null",
        "CRSI": "ConnorsRSI",
        # … añade más si los necesitas …
    }
    MANUAL = {normalize(k): normalize(v) for k, v in RAW_MANUAL.items()}

    # ───────────── parámetros de los dos filtros difusos ─────────────
    FUZZY_PASSES = [
        {"n": 4, "cutoff": 0.30},  # 1.ª pasada amplia
        {"n": 1, "cutoff": 0.60},  # 2.ª pasada sobre los 4 candidatos
    ]

    # ───────────────────────── mapeo final ─────────────────────────
    mapping: dict[str, str | None] = {}

    for ind in sqx_indicators:
        n_ind = normalize(ind)
        match_original = norm_to_mt5.get(n_ind)  # 0) exacto

        # 1) alias manual
        if n_ind in MANUAL:
            alias_norm = MANUAL[n_ind]
            match_original = norm_to_mt5.get(alias_norm)

        # 2) fuzzy doble
        if not match_original:
            first = difflib.get_close_matches(n_ind, all_norm_keys, **FUZZY_PASSES[0])
            if first:
                second = difflib.get_close_matches(n_ind, first, **FUZZY_PASSES[1])
                if second:
                    match_original = norm_to_mt5[second[0]]

        mapping[ind] = match_original  # ← valor original de MT5 o None

    # ───────────────────────── guardar / mostrar ─────────────────────────
    OUT_FILE.write_text(
        json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"🏁 Mapeo completado: {OUT_FILE}")


# ──────────────────────────────────────────────────────────────
# 1. Generar NEW_RANGES_<TF>.json
# ──────────────────────────────────────────────────────────────
def build_ranges_jsons(
    mapping_file: str | Path,
    calibration_file: str | Path,
    activo: str,
    out_dir: str | Path = "./ranges_by_tf",
    decimals: int = 6,
) -> None:
    """
    Crea un JSON de rangos por timeframe con claves *externas* (ADX, ATR…).

    Ej.: ``ranges_by_tf/NDX_M15.json``

    Args:
        mapping_file:      Path al mapping maestro {externo: interno}.
        calibration_file:  JSON con los datos MT5 multi-timeframe.
        activo:            Prefijo del archivo de salida (NDX, SPX, …).
        out_dir:           Carpeta de destino para los JSON.
        decimals:          Nº de decimales a redondear.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True)

    mapping: Dict[str, str] = json.loads(Path(mapping_file).read_text())
    mt5_multi = json.loads(Path(calibration_file).read_text())

    for idx, tf in enumerate(mt5_multi["timeframes"], start=1):
        tf_name = tf.get("tf") or tf.get("timeframe") or tf.get("name") or f"tf{idx}"

        # Agrupar registros por código interno
        by_code: Dict[str, List[dict]] = {}
        for rec in tf["datos"]:
            by_code.setdefault(rec["indicador"], []).append(rec)

        # Construir rangos con claves externas
        ranges: Dict[str, Tuple[float, float, float]] = {}
        for ext, internal in mapping.items():
            registros = by_code.get(internal)
            if not registros:
                continue
            mins = [r["minimo"] for r in registros]
            maxs = [r["maximo"] for r in registros]
            pasos = [r["paso"] for r in registros]
            ranges[ext] = (
                round(min(mins), decimals),
                round(max(maxs), decimals),
                round(min(pasos), decimals),
            )

        out_path = out_dir / f"{activo}_{tf_name}.json"
        out_path.write_text(
            json.dumps(ranges, indent=2, sort_keys=True, ensure_ascii=False)
        )
        log.info("Creado %s (%d indicadores)", out_path, len(ranges))


# ──────────────────────────────────────────────────────────────
# 2. Helpers para parchear config.xml
# ──────────────────────────────────────────────────────────────
_TRUE_VALUES = {"1", "true", "yes"}


def _is_true(value: str | None) -> bool:
    return value and value.lower() in _TRUE_VALUES


def _patch_block(
    block: ET.Element, ranges: Dict[str, Tuple[float, float, float]]
) -> None:
    """
    Sustituye indicatorMin/Max/Step siempre que el indicador figure en `ranges`,
    tanto si está activado (use="true") como si no.

    Args:
        block:  Nodo <Block> del XML.
        ranges: Diccionario {nombre_externo: (min, max, step)}.
    """
    key = block.get("key", "")
    if not key.startswith("Indicators."):
        return

    # Nombre externo (ADX, ATR, …)
    name = key.split(".", 1)[1]

    rng = ranges.get(name)
    if not rng:
        log.debug("  %s sin rango definido (se deja intacto)", name)
        return

    # Solo para log: saber si estaba marcado como 'usado'
    attrs = {k.lower(): v for k, v in block.attrib.items()}
    in_use = _is_true(attrs.get("use") or attrs.get("enabled") or attrs.get("selected"))

    # Parchear los atributos de rango
    block.set("indicatorMin", str(rng[0]))
    block.set("indicatorMax", str(rng[1]))
    block.set("indicatorStep", str(rng[2]))

    log.debug(
        "  %s (%s) → min=%s  max=%s  step=%s",
        name,
        "ON" if in_use else "OFF",
        *rng,
    )


# ──────────────────────────────────────────────────────────────
# 3. Generar .sbq a partir de un dict de rangos
# ──────────────────────────────────────────────────────────────
def generate_sqb(
    template: str | Path,
    output: str | Path,
    ranges: Dict[str, Tuple[float, float, float]],
    xml_inside: str = "config.xml",
) -> None:
    """Escribe *output* copiando *template* y parcheando sus rangos."""
    template = Path(template)
    output = Path(output)

    with zipfile.ZipFile(template, "r") as zin, zipfile.ZipFile(
        output, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)

            if item.filename == xml_inside:
                root = ET.fromstring(data)
                for blk in root.findall(".//Block"):
                    _patch_block(blk, ranges)
                data = ET.tostring(root, encoding="utf-8")

            zout.writestr(item, data)

    log.info("✔  Generado %s", output)


# ──────────────────────────────────────────────────────────────
# 4. Orquestador: un .sbq por timeframe
# ──────────────────────────────────────────────────────────────
def batch_generate_sqb(
    ranges_dir: str | Path,
    template_sbq: str | Path,
    activo: str,
    out_dir: str | Path = "./calibrated_sqb",
    xml_inside: str = "config.xml",
) -> None:
    """
    Recorre todos los JSON de rangos y produce un .sqb calibrado por cada uno.
    """
    ranges_dir = Path(ranges_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True)

    json_files = sorted(ranges_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"No hay JSON de rangos en {ranges_dir}")

    log.info("Plantilla usada: %s", template_sbq)
    log.info("Encontrados %d timeframes", len(json_files))

    for jf in json_files:
        tf_name = jf.stem.split("_")[-1]  # p.e. NDX_M15 → M15
        ranges = json.loads(jf.read_text())
        out_sbq = out_dir / f"{Path(template_sbq).stem}_{activo}_{tf_name}.sqb"
        log.info("→ Timeframe %s", tf_name)
        generate_sqb(template_sbq, out_sbq, ranges, xml_inside)
