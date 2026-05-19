"""
Script de descarga de modelos ONNX para YuNet y SFace.
Ejecutar una sola vez antes de iniciar el sistema.
"""
import urllib.request
import os
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx"
    ),
    "face_recognition_sface_2021dec.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx"
    ),
}


def download(name: str, url: str):
    dest = MODELS_DIR / name
    if dest.exists():
        print(f"[YA EXISTE] {name}")
        return
    print(f"[DESCARGANDO] {name} ...")
    try:
        urllib.request.urlretrieve(url, dest)
        size_kb = dest.stat().st_size // 1024
        print(f"[OK] {name} ({size_kb} KB)")
    except Exception as e:
        print(f"[ERROR] {name}: {e}")


if __name__ == "__main__":
    for model_name, model_url in MODELS.items():
        download(model_name, model_url)
    print("\nListo. Ahora ejecuta: register_faces.py")
