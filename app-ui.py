"""
streamlit_app.py  –  GUI web local para tu calibrador
Ejecuta con:  streamlit run streamlit_app.py
"""

import streamlit as st
import tempfile, os, sys, io, contextlib, logging
from main import main as run_cli  # tu función principal

ICON_PATH = "./el-comercio-de-acciones.png"
# ---------- UI ----------------------------------------------------------------
# st.set_page_config(
#     page_title="Calibrator",
#     # layout="wide",
#     page_icon="./el-comercio-de-acciones.png",
# )
# st.image(ICON_PATH, width=200)
# st.title("Calibrator")

col_icon, col_title = st.columns([1, 8])  # 1/8 de ancho

with col_icon:
    st.image(ICON_PATH, width=220)

with col_title:
    # Ajusta `margin` para centrar verticalmente
    st.markdown("<h1 style='margin:0.3em 0'>Calibrator</h1>", unsafe_allow_html=True)


st.header("1️⃣  Entradas")
mt5_folder = st.text_input("**Carpeta con indicadores MT5**")
sbq_file = st.file_uploader(
    "**Template SQX BlockSettings.sqb**"
)  # acepta cualquier extensión
calib_file = st.file_uploader("**Archivo de calibración JSON**")
activo = st.text_input("**Activo**", "NDX")
genmap = st.checkbox("Generar/actualizar mapping.json", value=True)

# Contenedor donde luego pondremos los logs
log_placeholder = st.empty()

# ---------- Ejecución ---------------------------------------------------------
if st.button("Ejecutar"):
    if not (mt5_folder and sbq_file and calib_file):
        st.warning("Faltan datos: selecciona carpeta MT5, BlockSettings y calibración.")
        st.stop()

    with tempfile.TemporaryDirectory() as tmp, st.spinner("Procesando…"):
        # Guardar los ficheros subidos
        sbq_path = os.path.join(tmp, sbq_file.name)
        calib_path = os.path.join(tmp, calib_file.name)
        with open(sbq_path, "wb") as f:
            f.write(sbq_file.getbuffer())
        with open(calib_path, "wb") as f:
            f.write(calib_file.getbuffer())

        # Construir flags que espera parse_args()
        args_cli = []
        if genmap:
            args_cli.append("-m")  # --generate-mapping
        args_cli += [
            "--indicators",
            mt5_folder,
            "--block-settings",
            sbq_path,
            "--calibration-file",
            calib_path,
            "--activo",
            activo,
        ]

        # ----------------- Captura de stdout / stderr / logging -----------------
        buf = io.StringIO()

        # 1) stdout + stderr
        redir_out = contextlib.redirect_stdout(buf)
        redir_err = contextlib.redirect_stderr(buf)

        # 2) logging (root)
        log_handler = logging.StreamHandler(buf)
        log_handler.setLevel(logging.DEBUG)
        logging_root = logging.getLogger()  # raíz
        prev_handlers = logging_root.handlers[:]  # copia
        logging_root.handlers = [log_handler]

        # 3) simular línea de comandos
        prev_argv = sys.argv[:]
        sys.argv = ["calibrator_streamlit"] + args_cli

        try:
            with redir_out, redir_err:
                run_cli()  # main() sin args
        except SystemExit as e:
            print(f"[exit code {e.code}]")
        finally:
            # restaurar estado
            sys.argv = prev_argv
            logging_root.handlers = prev_handlers

        # -----------------------------------------------------------------------
        logs = buf.getvalue()
        log_placeholder.text_area("Salida del proceso", logs, height=400)

    st.success("Proceso finalizado ✅")
