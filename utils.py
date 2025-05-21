from __future__ import annotations

import os
import zipfile
import xml.etree.ElementTree as ET
import re, json, difflib
import json
import logging
import io

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
        # Guardar indicadores en un archivo .txt
        with open("indicators.txt", "w", encoding="utf-8") as f:
            for indicator in sorted(indicators):
                f.write(f"{indicator}\n")
    return sorted(indicators)


def extract_indicators_from_sqb(
    sqb_file: str | Path, extra_indicators: list[str] | None = None
) -> list[str]:
    """
    Lee un archivo .sqb generado por StrategyQuant / AlgoWizard, localiza
    el archivo config.xml que contiene la definición de bloques
    y extrae todas las entradas cuyo atributo category=\"indicators\".

    :param sqb_file: Ruta al archivo .sqb
    :param extra_indicators: Lista opcional de nombres adicionales
                             (p.e. los que ves en la imagen)
    :return: Lista de nombres de indicadores, sin duplicados y ordenada
    """
    extras = set(extra_indicators or [])
    indicators = set()

    # -- 1. abrir el contenedor ZIP (.sqb) --
    with zipfile.ZipFile(sqb_file) as z:
        # el .sqb siempre contiene un único config.xml
        if "config.xml" not in z.namelist():
            raise ValueError("config.xml no encontrado dentro del .sqb")
        xml_bytes = z.read("config.xml")

    # -- 2. parsear el XML de manera incremental (consume poca RAM) --
    for event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("start",)):
        if elem.tag == "Block" and elem.get("category") == "indicators":
            key = elem.get("key")
            if key:
                indicators.add(key)

    # -- 3. incorporar los indicadores extra y devolver la lista ordenada --
    indicators.update(extras)
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


def _is_true(value: str | None) -> bool:
    return bool(value and value.lower() in {"1", "true", "yes"})


def _patch_block(
    block: ET.Element,
    mapping: dict[str, str],
    datos_map: dict[str, tuple[float, float, float]],
) -> None:
    """
    Parchar un <Block> tanto de categoría "indicators" como "stopLimitBlocks",
    usando mapping para convertir raw_key -> nombre en datos_map,
    y actualiza los atributos indicatorMin, indicatorMax, indicatorStep.
    """
    cat = block.get("category", "")
    raw_key = block.get("key", "")
    # Normalizar la clave:
    # - indicators suelen venir como "Indicators.<Name>" o solo "<Name>"
    # - stopLimitBlocks como "Stop/Limit Price Ranges.<Name>"
    if "." in raw_key:
        raw_key = raw_key.split(".", 1)[1]

    # Ahora raw_key coincide con las claves de mapping.json
    if raw_key not in mapping:
        return

    val_name = mapping[raw_key]
    if val_name not in datos_map:
        return

    minimo, maximo, paso = datos_map[val_name]

    # Para diagnóstico
    in_use = (
        _is_true(block.get("use"))
        or _is_true(block.get("enabled"))
        or _is_true(block.get("selected"))
    )
    log.debug(
        "Patching %s (cat=%s, in_use=%s): min=%s max=%s step=%s",
        raw_key,
        cat,
        in_use,
        minimo,
        maximo,
        paso,
    )

    # Reemplaza los atributos en el propio <Block>
    block.set("indicatorMin", str(minimo))
    block.set("indicatorMax", str(maximo))
    block.set("indicatorStep", str(paso))


def generate_sqb_per_timeframe(
    template_sqb: Path,
    mapping_json: Path,
    mt5_calibrated_json: Path,
    output_dir: Path,
    activo: str,
) -> list[Path]:
    """
    Lee template_sqb, master mapping y valores.json, y genera un .sqb
    por cada timeframe, parchando los atributos indicatorMin/Max/Step
    en cada <Block> de categorías "indicators" y "stopLimitBlocks".
    """
    # 1) Cargar mapping y valores
    mapping = json.loads(mapping_json.read_text(encoding="utf-8"))
    valores = json.loads(mt5_calibrated_json.read_text(encoding="utf-8"))

    # Construir dict de timeframes -> { indicador_en_valores.json: (min, max, step) }
    tf_dict: dict[str, dict[str, tuple[float, float, float]]] = {}
    for tf_block in valores.get("timeframes", []):
        tf = tf_block.get("timeframe")
        datos_map = {
            d["indicador"]: (d["minimo"], d["maximo"], d["paso"])
            for d in tf_block.get("datos", [])
        }
        tf_dict[tf] = datos_map

    # 2) Leer config.xml original y resto de archivos
    with zipfile.ZipFile(template_sqb, "r") as zin:
        xml_bytes = zin.read("config.xml")
        other_files = {
            item.filename: zin.read(item.filename)
            for item in zin.infolist()
            if item.filename != "config.xml"
        }

    # Prepara carpeta de salida
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = []

    # 3) Para cada timeframe, parchear y escribir nuevo .sqb
    for tf, datos_map in tf_dict.items():
        root = ET.fromstring(xml_bytes)
        for block in root.findall(".//Block"):
            cat = block.get("category", "")
            if cat in ("indicators", "stopLimitBlocks"):
                _patch_block(block, mapping, datos_map)

        new_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        out_path = output_dir / f"{template_sqb.stem}_{activo}_{tf}.sqb"

        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            zout.writestr("config.xml", new_xml)
            for name, data in other_files.items():
                zout.writestr(name, data)

        log.info("Generado %s", out_path.name)
        generated.append(out_path)

    log.info("Total: %d archivos .sqb creados en '%s'", len(generated), output_dir)
    return generated
