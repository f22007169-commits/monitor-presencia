"""
Script de registro de rostros.
Detecta caras en las fotos de profesores/ y genera embeddings.pkl
Ejecutar una sola vez (o cuando se agreguen nuevos profesores).
"""
from face_engine import engine

if __name__ == "__main__":
    print("=" * 55)
    print("  REGISTRO DE ROSTROS - Teacher Monitor")
    print("=" * 55)
    result = engine.register_faces()
    if result:
        print(f"\n[LISTO] {len(result)} profesor(es) registrados.")
        print("  Ahora puedes iniciar el sistema con:  python app.py")
    else:
        print("\n[ERROR] No se registró ningún profesor.")
        print("  Verifica que la carpeta 'profesores/' tiene fotos válidas.")
