"""
streamlit_app.py – GUI Streamlit para el Calibrator
· Arrastra tus indicadores (.ex5), template BlockSettings.sqb y JSON de calibración
· Si no subes master_mapping.json se generará automáticamente
· Descarga un .zip con todos los outputs

Ejecuta:  streamlit run streamlit_app.py
"""

from pathlib import Path
import streamlit as st
import tempfile, os, sys, io, contextlib, logging, zipfile, shutil
from main import main as run_cli  # tu CLI

# ─────────────────── Estilo cabecera ────────────────────────────────────────
ICON_PATH = "./el-comercio-de-acciones.png"  # cambia por tu icono
SCRIPT_DIR = Path(__file__).resolve().parent

col_icon, col_title = st.columns([1, 8])
with col_icon:
    st.image(ICON_PATH, width=200)
with col_title:
    st.markdown("<h1 style='margin:0.3em 0'>Calibrator</h1>", unsafe_allow_html=True)

# ───────────────────── Entradas ─────────────────────────────────────────────
st.header("Entradas")

indicator_files = st.file_uploader(
    "**Indicadores MT5 (.ex5)** 📁 (Opcional)",
    type="ex5",
    accept_multiple_files=True,
    help="Se prioriza el tener un archivo JSON de mappeo de indicadores. Si no lo tienes, sube los .ex5 aquí.",
)
sbq_file = st.file_uploader(
    "**Archivo template BlockSettings.sqb** 📁",
    help="Archivo template procedente del Bulding Block de SQX",
)
calib_file = st.file_uploader(
    "**Archivo de calibración JSON** 📁",
    type="json",
    help="Archivo generado en MT5 tras realizar la calibración",
)
mapping_up = st.file_uploader("**Archivo JSON de mapeo** 📁", type="json")

activo = st.text_input("_Activo_", "NDX", help="Nombre del activo a calibrar")

regenerar = st.checkbox(
    "Regenerar mapping",
    value=False,
    help="Si marcas esto, se ignorará el mapping subido y se creará uno nuevo.",
)

log_placeholder = st.empty()

# ─────────────────── Ejecutar ───────────────────────────────────────────────
if st.button("Ejecutar"):
    if not (sbq_file and calib_file):
        st.warning("Debes subir mínimo: BlockSettings y calibración.")
        st.stop()

    with tempfile.TemporaryDirectory() as tmpdir, st.spinner("Procesando…"):
        tmp = Path(tmpdir)

        # 1) Guardar indicadores en tmp/Indicators/
        indicators_dir = tmp / "Indicators"
        indicators_dir.mkdir()
        for f in indicator_files:
            (indicators_dir / f.name).write_bytes(f.getbuffer())

        # 2) Guardar template SBQ y calibración JSON
        sbq_path = tmp / sbq_file.name
        calib_path = tmp / calib_file.name
        sbq_path.write_bytes(sbq_file.getbuffer())
        calib_path.write_bytes(calib_file.getbuffer())

        # 3) Determinar mapping
        mapping_path = tmp / "master_mapping.json"
        if mapping_up is not None and not regenerar:
            mapping_path.write_bytes(mapping_up.getbuffer())
            mapping_flag = []  # usar mapping subido
        else:
            mapping_flag = ["-m"]  # --generate-mapping (creará mapping_path)

        # 4) Construir flags para main.py
        args_cli = mapping_flag + [
            "--indicators",
            str(indicators_dir),
            "--block-settings",
            str(sbq_path),
            "--calibration-file",
            str(calib_path),
            "--mapping-file",
            str(mapping_path),
            "--activo",
            activo,
        ]

        # 5) Capturar stdout / stderr / logging
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            log_handler = logging.StreamHandler(buf)
            root_logger = logging.getLogger()
            prev_handlers = root_logger.handlers[:]
            root_logger.handlers = [log_handler]

            prev_cwd, prev_argv = os.getcwd(), sys.argv[:]
            os.chdir(tmp)
            sys.argv = ["calibrator_streamlit"] + args_cli
            try:
                run_cli()  # main() sin args
            except SystemExit as e:
                print(f"[exit code {e.code}]")
            finally:
                os.chdir(prev_cwd)
                sys.argv = prev_argv
                root_logger.handlers = prev_handlers

        log_placeholder.text_area("Salida del proceso", buf.getvalue(), height=420)

        # 6) Empaquetar outputs → ZIP  (excluye inputs y el propio zip)
        zip_path = tmp / "calibrator_outputs.zip"
        exclude = {sbq_path, calib_path, zip_path} | set(indicators_dir.glob("*"))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in tmp.rglob("*"):
                if p.is_file() and p not in exclude:
                    z.write(p, p.relative_to(tmp))

        # 7) Botón de descarga
        with zip_path.open("rb") as f:
            st.download_button(
                "📦 Descargar resultados (.zip)",
                data=f,
                file_name="calibrator_outputs.zip",
                mime="application/zip",
            )

    st.success("¡Proceso finalizado y paquete listo para descargar! ✅")
