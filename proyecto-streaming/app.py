

from flask import Flask, render_template, jsonify, request
import tkinter as tk
from tkinter import filedialog
from obswebsocket import obsws, requests, events
import random
import json
import os
import subprocess
import atexit
import signal
import threading

app = Flask(__name__)

# --- CONFIGURACIÓN OBS ---
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PWD = "jesus2103"
INPUT_NAME = "Publicidad"        # Fuente para videos
IMAGE_INPUT_NAME = "Cintillas"    # Fuente para imágenes
TRIGGER_SOURCE = "Elgato"         # Fuente que manda la visibilidad
SCENE_NAME = "TV"                 # Tu escena principal

ws = obsws(OBS_HOST, OBS_PORT, OBS_PWD)

# ==============================
# 🔄 MANEJADOR DE EVENTOS OBS
# ==============================
def on_event(event):
    """Detecta cambios de visibilidad en la fuente Elgato y replica en Cintillas"""
    if isinstance(event, events.SceneItemEnableStateChanged):
        # Verificamos si el cambio ocurrió en nuestra escena y en la fuente 'Elgato'
        if event.getSceneName() == SCENE_NAME:
            # Necesitamos obtener el nombre de la fuente por su ID para estar seguros
            try:
                item_id = event.getSceneItemId()
                # Consultamos si ese ID pertenece a "Elgato"
                source_resp = ws.call(requests.GetSceneItemSource(sceneName=SCENE_NAME, sceneItemId=item_id))
                source_name = source_resp.getSourceName()

                if source_name == TRIGGER_SOURCE:
                    nuevo_estado = event.getSceneItemEnabled()
                    print(f"[OBS] Sincronizando: {TRIGGER_SOURCE} -> {IMAGE_INPUT_NAME} (Estado: {nuevo_estado})")
                    
                    # Buscamos el ID de Cintillas para cambiar su estado
                    cintillas_id_resp = ws.call(requests.GetSceneItemId(sceneName=SCENE_NAME, sourceName=IMAGE_INPUT_NAME))
                    cintillas_id = cintillas_id_resp.getSceneItemId()
                    
                    ws.call(requests.SetSceneItemEnabled(
                        sceneName=SCENE_NAME,
                        sceneItemId=cintillas_id,
                        sceneItemEnabled=nuevo_estado
                    ))
            except Exception as e:
                print(f"[ERROR EVENTO] {e}")

ws.register(on_event)
ws.connect()

# --- ARCHIVO DE PERSISTENCIA ---
PLAYLIST_FILE = "playlist.json"

# --- VARIABLES EN MEMORIA ---
lista_videos = []
lista_cintillas = []
modo_reproduccion = "orden"
orden_actual = []


# ==============================
# 🚀 CONFIGURACIÓN FFMPEG AUTO
# ==============================
TEE_OUTPUTS = (
    "[f=mpegts:onfail=ignore]"
    "srt://0.0.0.0:5001?mode=listener&latency=80&peerlatency=80"
    "|[f=mpegts:onfail=ignore]"
    "srt://0.0.0.0:5002?mode=listener&latency=80&peerlatency=80"
)

FFMPEG_CMD = [
    "ffmpeg",
    "-fflags", "nobuffer",
    "-flags", "low_delay",
    "-i", "srt://0.0.0.0:1234?mode=listener",
    "-map", "0:v",
    "-map", "0:a?",
    "-c:v", "copy",
    "-c:a", "copy",
    "-f", "tee",
    TEE_OUTPUTS
]

ffmpeg_process = None

def start_ffmpeg():
    global ffmpeg_process
    if ffmpeg_process and ffmpeg_process.poll() is None:
        return
    try:
        ffmpeg_process = subprocess.Popen(FFMPEG_CMD, creationflags=subprocess.CREATE_NO_WINDOW)
        print("[FFMPEG] Proceso iniciado")
    except Exception as e:
        print(f"[ERROR FFMPEG] {e}")

def stop_ffmpeg():
    global ffmpeg_process
    if ffmpeg_process and ffmpeg_process.poll() is None:
        ffmpeg_process.send_signal(signal.SIGTERM)

# ==============================
# 🎯 DETECTOR DE LOGO
# ==============================
logo_process = None

def is_logo_detector_running():
    global logo_process
    return logo_process and logo_process.poll() is None

def start_logo_detector():
    global logo_process
    if is_logo_detector_running(): return
    try:
        logo_process = subprocess.Popen(["python", "main.py"], creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        print(f"[ERROR LOGO] {e}")

def stop_logo_detector():
    global logo_process
    if is_logo_detector_running():
        logo_process.send_signal(signal.SIGTERM)

atexit.register(stop_ffmpeg)
atexit.register(stop_logo_detector)


# ==============================
# 🎵 MANEJO DE CONTENIDO
# ==============================

def guardar_playlist():
    data = {
        "modo": modo_reproduccion,
        "videos": lista_videos,
        "cintillas": lista_cintillas 
    }
    with open(PLAYLIST_FILE, "w") as f:
        json.dump(data, f, indent=4)

def cargar_playlist_local():
    global lista_videos, modo_reproduccion, lista_cintillas
    if not os.path.exists(PLAYLIST_FILE): return
    with open(PLAYLIST_FILE, "r") as f:
        data = json.load(f)
    lista_videos = data.get("videos", [])
    lista_cintillas = data.get("cintillas", [])
    modo_reproduccion = data.get("modo", "orden")

def actualizar_obs_playlist():
    try:
        global lista_videos, modo_reproduccion, orden_actual
        videos = lista_videos.copy()
        if modo_reproduccion == "aleatorio":
            random.shuffle(videos)
        orden_actual = videos.copy()
        playlist = [{"value": v, "selected": False, "hidden": False} for v in orden_actual]
        ws.call(requests.SetInputSettings(inputName=INPUT_NAME, inputSettings={"playlist": playlist}))
        guardar_playlist()
    except Exception as e:
        print(f"[ERROR] OBS playlist videos: {e}")

def actualizar_obs_cintillas():
    try:
        global lista_cintillas
        slides = [{"value": img, "hidden": False} for img in lista_cintillas]
        ws.call(requests.SetInputSettings(
            inputName=IMAGE_INPUT_NAME,
            inputSettings={
                "files": slides,
                "loop": True,
                "slide_time": 8000
            }
        ))

        scene_item_id = ws.call(requests.GetSceneItemId(
            sceneName=SCENE_NAME, 
            sourceName=IMAGE_INPUT_NAME
        )).getSceneItemId()

        ws.call(requests.SetSceneItemTransform(
            sceneName=SCENE_NAME,
            sceneItemId=scene_item_id,
            sceneItemTransform={
                "positionX": 960,
                "positionY": 1900, # Ajustado a 1080 para estar en el borde real
                "alignment": 8,
                "boundsType": "OBS_BOUNDS_SCALE_INNER",
                "boundsWidth": 1920,
                "boundsHeight": 1800
            }
        ))
        guardar_playlist()
    except Exception as e:
        print(f"[ERROR] OBS cintillas: {e}")

# Cargas iniciales
cargar_playlist_local()
actualizar_obs_playlist()
actualizar_obs_cintillas()


# ==============================
# 🧩 FLASK ROUTES
# ==============================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/seleccionar_cintilla', methods=['POST'])
def seleccionar_cintilla():
    global lista_cintillas
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    file_path = filedialog.askopenfilename(
        title="Selecciona una cintilla (Imagen)",
        filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp")]
    )
    root.destroy()
    if file_path and file_path not in lista_cintillas:
        lista_cintillas.append(file_path)
        actualizar_obs_cintillas()
        return jsonify({"status": "success", "path": file_path})
    return jsonify({"status": "cancelado"})

@app.route('/remove_cintilla', methods=['POST'])
def remove_cintilla():
    global lista_cintillas
    path = request.json.get('path')
    if path in lista_cintillas:
        lista_cintillas.remove(path)
        actualizar_obs_cintillas()
    return jsonify({"status": "success"})

@app.route('/seleccionar_archivo', methods=['POST'])
def seleccionar_archivo():
    global lista_videos
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    file_path = filedialog.askopenfilename(
        title="Selecciona un video",
        filetypes=[("Videos", "*.mp4 *.avi *.mkv *.mov")]
    )
    root.destroy()
    if file_path and file_path not in lista_videos:
        lista_videos.append(file_path)
        actualizar_obs_playlist()
        return jsonify({"status": "success", "path": file_path})
    return jsonify({"status": "cancelado"})

@app.route('/remove_video', methods=['POST'])
def remove_video():
    global lista_videos
    path = request.json.get('path')
    if path in lista_videos:
        lista_videos.remove(path)
        actualizar_obs_playlist()
    return jsonify({"status": "success"})

@app.route('/status')
def status():
    return jsonify({
        "modo": modo_reproduccion,
        "videos": lista_videos,
        "cintillas": lista_cintillas,
        "orden_actual": orden_actual,
        "streaming": get_stream_status(),
        "logo_detector": is_logo_detector_running()
    })

@app.route('/toggle_logo_detector', methods=['POST'])
def toggle_logo_detector():
    if is_logo_detector_running():
        stop_logo_detector()
        return jsonify({"status": "stopped"})
    else:
        start_logo_detector()
        return jsonify({"status": "started"})

@app.route('/set_mode', methods=['POST'])
def set_mode():
    global modo_reproduccion
    modo = request.json.get("modo")
    if modo in ["orden", "aleatorio"]:
        modo_reproduccion = modo
        actualizar_obs_playlist()
        return jsonify({"status": "ok", "modo": modo})
    return jsonify({"status": "error"})

@app.route('/toggle_stream', methods=['POST'])
def toggle_stream():
    try:
        streaming = get_stream_status()
        if streaming:
            ws.call(requests.StopStream())
            return jsonify({"status": "stopped"})
        else:
            ws.call(requests.StartStream())
            return jsonify({"status": "started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

def get_stream_status():
    try:
        resp = ws.call(requests.GetStreamStatus())
        return resp.getOutputActive()
    except: return False

if __name__ == '__main__':
    start_ffmpeg()
    print("[API] Servidor iniciado en puerto 5000")
    # Importante: debug=False para evitar que el manejador de eventos se registre dos veces
    app.run(debug=False, port=5000)