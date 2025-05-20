#!/usr/bin/env python3
"""
main.py – Flujo completo: mapping.json  ➜  NEW_RANGES_<TF>.json  ➜  *.sbq

Ejecución típica:
    python main.py --indicators ./mt5_indicators \
                   --block-settings ./BlockSettings.sqb \
                   --xml config.xml \
                   --mapping-file ./master_mapping.json \
                   --calibration-file ./NDX_MULTI_2025.05.19_12-41.json \
                   --activo NDX
Añade -m/--generate-mapping si también deseas regenerar mapping.json.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from utils import (
    get_mt5_indicators,
    get_sqx_indicators,
    mapping_indicators,
    build_ranges_jsons,
    batch_generate_sqb,
)

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Paso opcional: crear mapping.json
# ──────────────────────────────────────────────────────────────
def build_mapping(
    mt5_indicators_path: Path,
    block_settings_path: Path,
    xml_path: str,
    output_file: Path,
) -> None:
    """Extrae indicadores MT5 y SQX y genera mapping.json."""
    log.info("Leyendo indicadores MT5 desde %s", mt5_indicators_path)
    mt5_indicators = get_mt5_indicators(indicators_path=mt5_indicators_path)

    log.info("Leyendo indicadores SQX desde %s", block_settings_path)
    sqx_indicators = get_sqx_indicators(
        block_settings_path=block_settings_path,
        xml_path=xml_path,
    )

    mapping_indicators(
        sqx_indicators=sqx_indicators,
        mt5_indicators=mt5_indicators,
        output_file=output_file,
    )
    log.info("✔ mapping.json actualizado → %s", output_file)


# ──────────────────────────────────────────────────────────────
# Paso principal: rangos + archivos .sbq
# ──────────────────────────────────────────────────────────────
def calibrate_block_settings(
    mapping_file: Path,
    calibration_file: Path,
    sbq_template: Path,
    activo: str,
) -> None:
    """
    1) Genera NEW_RANGES_<TF>.json en ./ranges_by_tf
    2) Crea un BlockSettings_<TF>.sbq por cada timeframe en ./calibrated_sbq
    """
    log.info("Generando JSON de rangos desde %s", calibration_file)
    build_ranges_jsons(
        mapping_file=mapping_file,
        calibration_file=calibration_file,
        activo=activo,
        out_dir="./ranges_by_tf",
        decimals=6,
    )

    log.info("Creando .sbq calibrados usando plantilla %s", sbq_template)
    batch_generate_sqb(
        ranges_dir="./ranges_by_tf",
        template_sbq=sbq_template,
        activo=activo,
        out_dir="./calibrated_sqb",
        xml_inside="config.xml",
    )
    log.info("✔ Todos los .sbq generados en ./calibrated_sqb/")


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera mapping.json, NEW_RANGES_<TF>.json y BlockSettings_<TF>.sbq"
    )

    parser.add_argument("--indicators", type=Path, default=Path("./mt5_indicators"))
    parser.add_argument(
        "--block-settings", type=Path, default=Path("./BlockSettings.sqb")
    )
    parser.add_argument("--xml", default="config.xml", help="Ruta del XML interno")
    parser.add_argument("--activo", default="NDX", help="Símbolo/activo a calibrar")
    parser.add_argument(
        "--mapping-file", type=Path, default=Path("./master_mapping.json")
    )
    parser.add_argument(
        "--calibration-file",
        type=Path,
        default=Path("./NDX_MULTI_2025.05.19_19-41.json"),
    )

    parser.add_argument(
        "-m",
        "--generate-mapping",
        action="store_true",  # ← default False
        help="Regenerar mapping.json antes de calibrar",
    )
    return parser.parse_args()


# ── flujo principal ──────────────────────────────────────────────
def main() -> None:
    args = parse_args()  # Namespace con generate_mapping=False por defecto

    if args.generate_mapping:  # Solo si el usuario pasó -m
        build_mapping(
            mt5_indicators_path=args.indicators,
            block_settings_path=args.block_settings,
            xml_path=args.xml,
            output_file=args.mapping_file,
        )

    calibrate_block_settings(
        mapping_file=args.mapping_file,
        calibration_file=args.calibration_file,
        sbq_template=args.block_settings,
        activo=args.activo,
    )


if __name__ == "__main__":
    main()
