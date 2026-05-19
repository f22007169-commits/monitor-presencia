"""
Motor de Reconocimiento Facial
Usa OpenCV YuNet (detección) + SFace (reconocimiento)
Corre en un hilo de fondo y actualiza el estado de presencia en tiempo real.
"""
import cv2
import numpy as np
import os
import pickle
import threading
import time
import json
import concurrent.futures
from pathlib import Path

BASE_DIR     = Path(__file__).parent
MODELS_DIR   = BASE_DIR / "models"
PROFS_DIR    = BASE_DIR / "profesores"
EMBEDDINGS_F = BASE_DIR / "embeddings.pkl"

YUNET_MODEL  = str(MODELS_DIR / "face_detection_yunet_2023mar.onnx")
SFACE_MODEL  = str(MODELS_DIR / "face_recognition_sface_2021dec.onnx")

COSINE_THRESHOLD   = 0.55   # Umbral MUY estricto — evita falsos positivos
MAX_CAMERAS        = 10     
IGNORE_CAMS        = [2]    # Ahora el 2 es tu PC
ENTRY_CAM_INDEX    = 0      # USB 1 como ENTRADA
ENTRY_HITS         = 3      # Frames consecutivos requeridos para confirmar ENTRADA
EXIT_HITS          = 3      # Frames consecutivos requeridos para confirmar SALIDA
HITS_GAP_RESET     = 1.0    # Segundos de gap → reinicia contador de hits


def _detect_cameras(max_index: int = MAX_CAMERAS) -> list[int]:
    """
    Detecta todas las cámaras disponibles probando índices 0..max_index EN PARALELO.
    Usa CAP_DSHOW (DirectShow) en Windows para evitar timeouts lentos.
    Tiempo total: ≤3 segundos sin importar cuántos índices sin cámara existan.
    """
    def _try_cam(i: int):
        try:
            # CAP_DSHOW es más rápido en Windows para índices sin cámara
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                if ret:
                    print(f"[DETECT] Cámara {i} disponible")
                    return i
        except Exception:
            pass
        return None

    available = []
    print(f"[DETECT] Buscando cámaras en paralelo (índices 0..{max_index})...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_index + 1) as executor:
        futures = {executor.submit(_try_cam, i): i for i in range(max_index + 1)}
        try:
            # Aumentamos a 8 segundos para dar tiempo a las USB externas
            for future in concurrent.futures.as_completed(futures, timeout=8.0):
                try:
                    result = future.result()
                    if result is not None:
                        available.append(result)
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            print("[DETECT] Aviso: Algunas cámaras tardaron demasiado en responder, continuando con las encontradas.")

    return sorted(available) if available else [0]  # Fallback a índice 0


class CameraWorker:
    """
    Hilo de captura y reconocimiento facial para UNA cámara.
    Cada worker tiene su propio FaceDetectorYN y FaceRecognizerSF
    (las instancias de OpenCV no son thread-safe entre hilos).
    """

    def __init__(self, cam_index: int, engine: 'FaceEngine'):
        self.cam_index = cam_index
        # Cámara de ENTRADA: la cámara del PC (índice configurado)
        # Cámara(s) de SALIDA: cualquier otra cámara conectada
        self.role      = "IN" if cam_index == ENTRY_CAM_INDEX else "OUT"
        self.engine    = engine
        self.running   = False
        self._thread   = None
        self._latest_frame = None
        self._frame_lock   = threading.Lock()

        # Instancias privadas — no compartidas con otros hilos
        self.detector   = cv2.FaceDetectorYN.create(YUNET_MODEL, "", (320, 320), 0.6, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(SFACE_MODEL, "")

    # ── Ciclo de vida ──────────────────────────────────────────────────

    def start(self):
        self.running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True,
            name=f"cam-worker-{self.cam_index}"
        )
        self._thread.start()

    def stop(self):
        self.running = False

    def get_frame(self):
        """Retorna copia del último frame anotado (thread-safe)."""
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    # ── Reconocimiento ────────────────────────────────────────────────

    def _identify_face(self, img, face) -> tuple[str, float]:
        if not self.engine.known_embeddings:
            return "Desconocido", 0.0
        try:
            aligned    = self.recognizer.alignCrop(img, face)
            query_feat = self.recognizer.feature(aligned)
        except Exception:
            return "Desconocido", 0.0

        best_name  = "Desconocido"
        best_score = -1.0
        for folder_name, emb_list in self.engine.known_embeddings.items():
            for known_feat in emb_list:
                score = self.recognizer.match(
                    query_feat, known_feat, cv2.FaceRecognizerSF_FR_COSINE
                )
                if score > best_score:
                    best_score = score
                    best_name  = folder_name if score >= COSINE_THRESHOLD else "Desconocido"
        return best_name, best_score

    # ── Bucle principal del hilo ──────────────────────────────────────

    def _loop(self):
        cap = cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW)  # CAP_DSHOW = más rápido en Windows
        if not cap.isOpened():
            print(f"[CAM {self.cam_index}] ERROR: No se pudo abrir")
            return

        print(f"[CAM {self.cam_index}] Iniciada y procesando...")

        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            display = frame.copy()
            h, w    = frame.shape[:2]
            self.detector.setInputSize((w, h))
            _, faces = self.detector.detect(frame)

            detected = set()
            now = time.time()
            if faces is not None:
                for face in faces:
                    name, score = self._identify_face(frame, face)
                    self.engine._draw_face_box(display, face, name, score)
                    if name != "Desconocido":
                        detected.add(name)

                with self.engine.lock:
                    for name in detected:
                        if name not in self.engine.presence_state:
                            continue
                        state = self.engine.presence_state[name]

                        if self.role == "IN":
                            # ── Cámara de ENTRADA ─────────────────────────────
                            # Reiniciar contador si hay gap entre detecciones
                            if (now - state.get("last_seen_in", 0)) > HITS_GAP_RESET:
                                state["hits_in"] = 1
                            else:
                                state["hits_in"] += 1
                            state["last_seen_in"] = now

                            # Confirmar ENTRADA con N hits consecutivos
                            if state["hits_in"] >= ENTRY_HITS and not state["present"]:
                                state["present"]  = True
                                state["hits_out"] = 0   # resetear contador de salida
                                print(f"[ENTRADA] {name} → PRESENTE")

                        elif self.role == "OUT":
                            # ── Cámara de SALIDA ──────────────────────────────
                            # Solo actúa sobre quienes ya están marcados como presentes
                            if not state["present"]:
                                continue
                            if (now - state.get("last_seen_out", 0)) > HITS_GAP_RESET:
                                state["hits_out"] = 1
                            else:
                                state["hits_out"] += 1
                            state["last_seen_out"] = now

                            # Confirmar SALIDA con N hits consecutivos
                            if state["hits_out"] >= EXIT_HITS:
                                state["present"]  = False
                                state["hits_in"]  = 0   # resetear contador de entrada
                                print(f"[SALIDA]  {name} → AUSENTE")

            # Etiqueta con número de cámara y ROL
            label = f" Cam {self.cam_index} [{'ENTRADA' if self.role == 'IN' else 'SALIDA'}] "
            label_color = (80, 220, 130) if self.role == "IN" else (80, 130, 255)  # Verde=entrada, Azul=salida
            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(display, (8, h - lh - 14), (8 + lw, h - 6), (15, 20, 40), cv2.FILLED)
            cv2.putText(display, label, (8, h - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, label_color, 1, cv2.LINE_AA)

            with self._frame_lock:
                self._latest_frame = display

        cap.release()
        print(f"[CAM {self.cam_index}] Liberada")


AVATAR_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

def _find_avatar(prof_dir: Path) -> str | None:
    """Busca una imagen de perfil llamada 'avatar' (cualquier extensión soportada)."""
    for ext in AVATAR_EXTENSIONS:
        candidate = prof_dir / f"avatar{ext}"
        if candidate.exists():
            return candidate.name
    return None


def _load_teacher_meta(prof_dir: Path) -> dict:
    """Lee info.json del profesor si existe, si no infiere desde el nombre de carpeta."""
    info_path = prof_dir / "info.json"
    avatar_file = _find_avatar(prof_dir)
    # La URL se construye en get_status para incluir el folder name
    if info_path.exists():
        with open(info_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "nombre_display": data.get("nombre_display", prof_dir.name),
            "asignatura":     data.get("asignatura", "Sin asignar"),
            "avatar_color":   data.get("avatar_color", "#6366f1"),
            "avatar_file":    avatar_file,   # nombre del archivo o None
        }
    return {
        "nombre_display": prof_dir.name,
        "asignatura":     "Sin asignar",
        "avatar_color":   "#6366f1",
        "avatar_file":    avatar_file,
    }


class FaceEngine:
    def __init__(self):
        self.detector   = None
        self.recognizer = None
        self.known_embeddings: dict[str, list] = {}   # key = folder name
        self.teacher_meta:    dict[str, dict]  = {}   # key = folder name
        self.presence_state:  dict[str, dict]  = {}   # key = folder name
        self.lock          = threading.Lock()
        self.running        = False
        self._models_ok     = False

        self.camera_workers: list[CameraWorker] = []  # uno por cámara

        self._init_models()
        self._load_all_teacher_meta()
        self._load_embeddings()

    # ------------------------------------------------------------------
    # Inicialización
    # ------------------------------------------------------------------

    def _init_models(self):
        if not Path(YUNET_MODEL).exists() or not Path(SFACE_MODEL).exists():
            print("[WARN] Modelos ONNX no encontrados. Ejecuta download_models.py primero.")
            return
        try:
            self.detector   = cv2.FaceDetectorYN.create(YUNET_MODEL, "", (320, 320), 0.6, 0.3, 5000)
            self.recognizer = cv2.FaceRecognizerSF.create(SFACE_MODEL, "")
            self._models_ok = True
            print("[OK] Modelos cargados correctamente")
        except Exception as e:
            print(f"[ERROR] Cargando modelos: {e}")

    def _load_all_teacher_meta(self):
        if not PROFS_DIR.exists():
            return
        for d in sorted(PROFS_DIR.iterdir()):
            if d.is_dir():
                meta = _load_teacher_meta(d)
                self.teacher_meta[d.name] = meta
                if d.name not in self.presence_state:
                    self.presence_state[d.name] = {
                        "present":      False,
                        "hits_in":      0,
                        "hits_out":     0,
                        "last_seen_in": 0.0,
                        "last_seen_out": 0.0,
                    }

    def _load_embeddings(self):
        if EMBEDDINGS_F.exists():
            with open(EMBEDDINGS_F, "rb") as f:
                self.known_embeddings = pickle.load(f)
            print(f"[OK] Embeddings cargados: {list(self.known_embeddings.keys())}")

    # ------------------------------------------------------------------
    # Registro de rostros (corre una sola vez)
    # ------------------------------------------------------------------

    def register_faces(self):
        """
        Recorre profesores/, detecta caras y genera embeddings.
        Guarda el resultado en embeddings.pkl.
        """
        if not self._models_ok:
            print("[ERROR] Modelos no cargados. No se puede registrar.")
            return {}

        embeddings = {}
        for prof_dir in sorted(PROFS_DIR.iterdir()):
            if not prof_dir.is_dir():
                continue

            name = prof_dir.name
            prof_embs = []

            img_files = [
                f for f in prof_dir.iterdir()
                if f.suffix.lower() in (".jpg", ".jpeg", ".png") and f.name != "avatar.jpg"
            ]

            for img_file in img_files:
                img = cv2.imread(str(img_file))
                if img is None:
                    continue

                # Redimensionar imágenes muy grandes para mejor detección
                h, w = img.shape[:2]
                max_dim = 1280
                if max(h, w) > max_dim:
                    scale = max_dim / max(h, w)
                    img = cv2.resize(img, (int(w * scale), int(h * scale)))
                    h, w = img.shape[:2]

                self.detector.setInputSize((w, h))
                _, faces = self.detector.detect(img)

                if faces is None or len(faces) == 0:
                    print(f"  [SKIP] {img_file.name}: sin cara detectada")
                    continue

                # La cara más confiable
                face = sorted(faces, key=lambda x: x[4], reverse=True)[0]

                # ── Filtro de frontalidad ─────────────────────────────────
                # YuNet retorna 5 landmarks: ojo_der, ojo_izq, nariz, boca_der, boca_izq
                # Si la diferencia vertical entre ojos es grande → foto de perfil/inclinada
                try:
                    lm      = face[4:14].reshape(5, 2)
                    ojo_der = lm[0]; ojo_izq = lm[1]
                    diff_y  = abs(float(ojo_der[1]) - float(ojo_izq[1]))
                    dist_oj = abs(float(ojo_der[0]) - float(ojo_izq[0]))
                    if dist_oj > 0 and diff_y / dist_oj > 0.35:
                        print(f"  [SKIP] {img_file.name}: foto de perfil/inclinada")
                        continue
                except Exception:
                    pass  # Si falla el filtro, procesar igual

                try:
                    aligned   = self.recognizer.alignCrop(img, face)
                    embedding = self.recognizer.feature(aligned)
                    prof_embs.append(embedding)
                except Exception as e:
                    print(f"  [ERR] {img_file.name}: {e}")

            if prof_embs:
                embeddings[name] = prof_embs
                print(f"[OK] {name}: {len(prof_embs)} embedding(s) generados")
            else:
                print(f"[WARN] {name}: No se encontraron caras válidas")

        with open(EMBEDDINGS_F, "wb") as f:
            pickle.dump(embeddings, f)

        self.known_embeddings = embeddings
        print(f"\n[DONE] embeddings.pkl guardado con {len(embeddings)} profesor(es)")
        return embeddings

    # ------------------------------------------------------------------
    # Identificación
    # ------------------------------------------------------------------

    def _identify_face(self, img, face) -> tuple[str, float]:
        """Retorna (nombre_carpeta, score) del profesor más parecido."""
        if not self._models_ok or not self.known_embeddings:
            return "Desconocido", 0.0
        try:
            aligned    = self.recognizer.alignCrop(img, face)
            query_feat = self.recognizer.feature(aligned)
        except Exception:
            return "Desconocido", 0.0

        best_name  = "Desconocido"
        best_score = -1.0

        for folder_name, emb_list in self.known_embeddings.items():
            for known_feat in emb_list:
                score = self.recognizer.match(
                    query_feat, known_feat, cv2.FaceRecognizerSF_FR_COSINE
                )
                if score > best_score:
                    best_score = score
                    best_name  = folder_name if score >= COSINE_THRESHOLD else "Desconocido"

        return best_name, best_score

    # ------------------------------------------------------------------
    # Estado de presencia
    # ------------------------------------------------------------------

    def get_status(self) -> list[dict]:
        """
        Retorna lista de profesores con su estado actual PERSISTENTE.
        La auto-ausencia se maneja en el hilo watchdog (_presence_watchdog).
        Formato listo para JSON/API.
        """
        result = []

        with self.lock:
            for folder_name, state in self.presence_state.items():
                is_present = state["present"]

                meta = self.teacher_meta.get(folder_name, {})
                avatar_file = meta.get("avatar_file")
                avatar_url  = (
                    f"/profesor-avatar/{folder_name}/{avatar_file}"
                    if avatar_file else None
                )
                result.append({
                    "id":           folder_name,
                    "nombre":       meta.get("nombre_display", folder_name),
                    "asignatura":   meta.get("asignatura", "Sin asignar"),
                    "avatar_color": meta.get("avatar_color", "#6366f1"),
                    "avatar_url":   avatar_url,
                    "status":       "present" if is_present else "absent",
                })

        # Ordenar: presentes primero
        result.sort(key=lambda x: (0 if x["status"] == "present" else 1, x["nombre"]))
        return result

    # (Sin watchdog: el estado es persistente y solo cambia por detección en cámara de salida)

    # ------------------------------------------------------------------
    # Hilo de cámara
    # ------------------------------------------------------------------

    def _draw_face_box(self, frame, face, name: str, score: float):
        """Dibuja cuadro + etiqueta sobre una cara detectada."""
        x, y, w, h = int(face[0]), int(face[1]), int(face[2]), int(face[3])

        if name == "Desconocido":
            color     = (80, 80, 80)       # Gris oscuro
            dot_color = (100, 100, 100)
        else:
            color     = (16, 185, 129)     # Verde (BGR)
            dot_color = (16, 185, 129)

        # Rectángulo del rostro
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2, cv2.LINE_AA)

        # Fondo de la etiqueta
        label      = name if name != "Desconocido" else "?"
        conf_text  = f"{score:.2f}" if name != "Desconocido" else ""
        full_label = f" {label}  {conf_text} "

        (tw, th), baseline = cv2.getTextSize(full_label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        label_y = max(y - 8, th + 10)

        cv2.rectangle(
            frame,
            (x, label_y - th - baseline - 4),
            (x + tw, label_y + baseline - 4),
            color, cv2.FILLED
        )
        cv2.putText(
            frame, full_label,
            (x, label_y - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6,
            (0, 0, 0), 2, cv2.LINE_AA
        )

    def _draw_overlay(self, frame):
        """Barra superior con título y hora."""
        h_bar = 38
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (frame.shape[1], h_bar), (15, 20, 40), cv2.FILLED)
        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

        cv2.putText(
            frame, "Monitor Docente  |  Reconocimiento Facial en Vivo",
            (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
            (180, 200, 255), 1, cv2.LINE_AA
        )
        hora = time.strftime("%H:%M:%S")
        cv2.putText(
            frame, hora,
            (frame.shape[1] - 90, 26),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55,
            (100, 200, 140), 1, cv2.LINE_AA
        )

    # ── Utilidades de display ─────────────────────────────────────────

    def _tile_frames(self, frames: list) -> np.ndarray:
        """
        Combina múltiples frames en un mosaico:
        - 1 cámara  → solo ese frame
        - 2 cámaras → lado a lado
        - 3-4 cámaras → grilla 2x2
        """
        n = len(frames)
        if n == 1:
            return frames[0]

        # Igualar tamaños al frame más pequeño
        h = min(f.shape[0] for f in frames)
        w = min(f.shape[1] for f in frames)
        resized = [cv2.resize(f, (w, h)) for f in frames]

        if n == 2:
            return np.hstack(resized)

        # 3 o 4 → grilla 2x2 (rellenar con negro si son 3)
        while len(resized) < 4:
            resized.append(np.zeros_like(resized[0]))
        top    = np.hstack(resized[:2])
        bottom = np.hstack(resized[2:4])
        return np.vstack([top, bottom])

    def _display_loop(self):
        """Bucle de display en el hilo principal (requerido por Windows + OpenCV)."""
        WINDOW = "Monitor Docente - Camaras en Vivo"
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

        n = len(self.camera_workers)
        base_w, base_h = (800, 500) if n == 1 else (1280 if n == 2 else 1280, 720)
        cv2.resizeWindow(WINDOW, base_w, base_h)

        while self.running:
            frames = [w.get_frame() for w in self.camera_workers]
            frames = [f for f in frames if f is not None]

            if frames:
                combined = self._tile_frames(frames)
                self._draw_overlay(combined)
                cv2.imshow(WINDOW, combined)

            key = cv2.waitKey(30) & 0xFF
            if key == ord('q') or key == 27:
                self.running = False
                break

        # Detener todos los workers
        for w in self.camera_workers:
            w.stop()

        cv2.destroyAllWindows()
        print("[DISPLAY] Ventana cerrada")

    def start_camera(self):
        """
        Detecta automáticamente todas las cámaras disponibles,
        arranca un CameraWorker por cada una en hilos de fondo,
        y corre el bucle de display en el hilo principal.
        """
        if not self._models_ok:
            print("[WARN] Modelos no cargados. La cámara no iniciará.")
            return
        if not self.known_embeddings:
            print("[WARN] Sin embeddings. Ejecuta register_faces primero.")
            return

        # ── Detección automática de cámaras ──────────────────────────
        all_indices = _detect_cameras()
        
        # Filtrar cámaras ignoradas (PC)
        cam_indices = [idx for idx in all_indices if idx not in IGNORE_CAMS]
        
        if not cam_indices:
            print(f"[WARN] No se encontraron cámaras USB externas.")
            return

        print(f"[OK] {len(cam_indices)} cámara(s) USB activas: {cam_indices}")

        # ── Crear y arrancar un worker por cámara ─────────────────────
        self.camera_workers = []
        for idx in cam_indices:
            try:
                worker = CameraWorker(idx, self)
                self.camera_workers.append(worker)
            except Exception as e:
                print(f"[CAM {idx}] Error al crear worker: {e}")

        if not self.camera_workers:
            print("[ERROR] No se pudo inicializar ninguna cámara.")
            return

        # Resetear contadores al inicio (presencia se mantiene hasta detección de salida)
        with self.lock:
            for state in self.presence_state.values():
                state["hits_in"]       = 0
                state["hits_out"]      = 0
                state["last_seen_in"]  = 0.0
                state["last_seen_out"] = 0.0
                state["present"]       = False   # todos ausentes al arrancar

        self.running = True

        for w in self.camera_workers:
            w.start()

        roles = [f"Cam{w.cam_index}={'ENTRADA' if w.role=='IN' else 'SALIDA'}" for w in self.camera_workers]
        print(f"[OK] {len(self.camera_workers)} worker(s) iniciados → {', '.join(roles)}")
        print(f"[OK] Abriendo ventana...")

        # ── Display en hilo principal (bloquea hasta que el usuario cierre) ──
        self._display_loop()

    def stop_camera(self):
        self.running = False
        for w in self.camera_workers:
            w.stop()


# Instancia global (singleton)
engine = FaceEngine()
