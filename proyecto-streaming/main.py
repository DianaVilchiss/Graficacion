import numpy as np
import cv2
import base64
import os
from obswebsocket import obsws, requests

# --- CONFIGURACIÓN OBS ---
OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PWD = "jesus2103"
ESCENA_TV = "TV"
FUENTE_A_ANALIZAR = "Elgato"  
FUENTE_PUBLICIDAD = "Publicidad"
ARCHIVO_LOGO_7 = "images.png" 

# --- VARIABLES DE SENSIBILIDAD ---
UMBRAL_REF = 0.18        
UMBRAL_ARCHIVO = 0.15    
MARGEN_TOTAL = 100      
MARGEN_SUPERIOR = 80    
MARGEN_INFERIOR = 20    
PESO_ACIERTO = 50       
PESO_DESACIERTO = 10    

# --- VARIABLES GLOBALES ---
logo_referencia_bordes = None
logo_7_bordes = None 
contador_aciertos = 100 
bandera_publicidad = False

ws = obsws(OBS_HOST, OBS_PORT, OBS_PWD)
ws.connect()
print("✅ Conectado a OBS")

def procesar_bordes_estricto(img):
    if img is None or img.size == 0: return None
    if len(img.shape) == 3 and img.shape[2] == 4:
        img = img[:, :, :3]
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gris = cv2.GaussianBlur(gris, (3, 3), 0)
    bordes = cv2.Canny(gris, 50, 150)
    kernel = np.ones((3,3), np.uint8)
    return cv2.dilate(bordes, kernel, iterations=1)

def obtener_frame_obs(nombre_fuente):
    try:
        response = ws.call(requests.GetSourceScreenshot(
            sourceName=nombre_fuente, imageFormat="jpg", imageWidth=1920, imageHeight=1080
        ))
        img_bytes = base64.b64decode(response.getImageData().split(",")[1])
        return cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    except: return None

# --- CALIBRACIÓN CON SELECTOR VISUAL (ROI) ---
print("\n--- CALIBRACIÓN ---")
print("1. Se abrirá una ventana.")
print("2. Dibuja un rectángulo sobre el logo con el mouse.")
print("3. Pulsa ENTER para confirmar o c para cancelar.")

frame_calib = obtener_frame_obs(FUENTE_A_ANALIZAR)
if frame_calib is None:
    print("❌ Error: No se pudo obtener imagen de OBS.")
    ws.disconnect()
    exit()

# Redimensionamos solo para visualización
display_calib = cv2.resize(frame_calib, (960, 540))
roi = cv2.selectROI("Selecciona el Logo", display_calib, fromCenter=False, showCrosshair=True)
cv2.destroyWindow("Selecciona el Logo")

# Escalamos las coordenadas de vuelta a 1080p (multiplicamos por 2 ya que 1920/960 = 2)
x, y, w, h = [int(v * 2) for v in roi]

# Definir límites de recorte
y_min, y_max = y, y + h
x_min, x_max = x, x + w
ancho_ref, alto_ref = w, h

# Capturar el logo de referencia inmediatamente
recorte_ref = frame_calib[y_min:y_max, x_min:x_max]
logo_referencia_bordes = procesar_bordes_estricto(recorte_ref)

if os.path.exists(ARCHIVO_LOGO_7):
    img_l7 = cv2.imread(ARCHIVO_LOGO_7, cv2.IMREAD_UNCHANGED)
    if img_l7 is not None:
        img_l7_res = cv2.resize(img_l7, (ancho_ref, alto_ref))
        logo_7_bordes = procesar_bordes_estricto(img_l7_res)
        print("✅ Archivo logo de referencia cargado.")

# Obtener ID de la fuente de publicidad
scene_item_id_publicidad = None
items = ws.call(requests.GetSceneItemList(sceneName=ESCENA_TV)).getSceneItems()
for item in items:
    if item["sourceName"] == FUENTE_PUBLICIDAD:
        scene_item_id_publicidad = item["sceneItemId"]

print("✅ Calibración completada. Iniciando monitoreo...")

# --- BUCLE PRINCIPAL ---
try:
    while True:
        frame = obtener_frame_obs(FUENTE_A_ANALIZAR)
        if frame is None: continue

        recorte = frame[y_min:y_max, x_min:x_max]
        bordes_actual = procesar_bordes_estricto(recorte)
        
        if bordes_actual is None: continue

        # Comparación con Logo de Calibración
        res_ref = cv2.matchTemplate(bordes_actual, logo_referencia_bordes, cv2.TM_CCOEFF_NORMED)
        _, m_ref, _, _ = cv2.minMaxLoc(res_ref)

        # Comparación con Logo de Archivo
        m_l7 = 0
        if logo_7_bordes is not None:
            res_l7 = cv2.matchTemplate(bordes_actual, logo_7_bordes, cv2.TM_CCOEFF_NORMED)
            _, m_l7, _, _ = cv2.minMaxLoc(res_l7)

        # Lógica de detección
        detectado = (m_ref > UMBRAL_REF) or (m_l7 > UMBRAL_ARCHIVO)

        if detectado:
            contador_aciertos = min(MARGEN_TOTAL, contador_aciertos + PESO_ACIERTO)
        else:
            contador_aciertos = max(0, contador_aciertos - PESO_DESACIERTO)

        # Control de OBS
        if contador_aciertos <= MARGEN_INFERIOR and not bandera_publicidad:
            if scene_item_id_publicidad:
                ws.call(requests.SetSceneItemEnabled(sceneName=ESCENA_TV, sceneItemId=scene_item_id_publicidad, sceneItemEnabled=True))
            ws.call(requests.SetInputMute(inputName=FUENTE_A_ANALIZAR, inputMuted=True))
            bandera_publicidad = True
            print(f"\n[CORTE] Publicidad ACTIVADA")

        elif contador_aciertos >= MARGEN_SUPERIOR and bandera_publicidad:
            if scene_item_id_publicidad:
                ws.call(requests.SetSceneItemEnabled(sceneName=ESCENA_TV, sceneItemId=scene_item_id_publicidad, sceneItemEnabled=False))
            ws.call(requests.SetInputMute(inputName=FUENTE_A_ANALIZAR, inputMuted=False))
            bandera_publicidad = False
            print(f"\n[VUELTA] TV ACTIVADA")

        print(f"Detección: {max(m_ref, m_l7):.2f} | Estabilidad: {contador_aciertos}  ", end="\r")
        
        cv2.imshow("Monitor de Bordes (Logo)", bordes_actual)
        if cv2.waitKey(1) & 0xFF == ord("q"): break

finally:
    ws.disconnect()
    cv2.destroyAllWindows()
