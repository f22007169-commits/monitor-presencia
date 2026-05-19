from flask import Flask, render_template, jsonify, send_from_directory, abort, request
from face_engine import engine, PROFS_DIR
import threading
import atexit
import os
import json
from werkzeug.utils import secure_filename

app = Flask(__name__)


@app.route('/')
def dashboard():
    teachers = engine.get_status()
    present_count = sum(1 for t in teachers if t['status'] == 'present')
    absent_count  = len(teachers) - present_count
    return render_template(
        'index.html',
        teachers=teachers,
        present_count=present_count,
        absent_count=absent_count,
    )


@app.route('/api/status')
def api_status():
    return jsonify(engine.get_status())


@app.route('/profesor-avatar/<folder>/<filename>')
def profesor_avatar(folder, filename):
    """Sirve la imagen de avatar del profesor de forma segura."""
    if '..' in folder or '..' in filename or '/' in folder or '/' in filename:
        abort(403)
    prof_dir = PROFS_DIR / folder
    if not prof_dir.is_dir():
        abort(404)
    return send_from_directory(str(prof_dir), filename)


@app.route('/admin')
def admin():
    return render_template('admin.html')


@app.route('/api/admin/teacher', methods=['POST'])
def add_teacher():
    try:
        prof_id = request.form.get('prof_id', '').strip()
        if not prof_id:
            return jsonify({"error": "ID del profesor es requerido."}), 400
            
        prof_id = secure_filename(prof_id)
        target_dir = PROFS_DIR / prof_id
        target_dir.mkdir(parents=True, exist_ok=True)
        
        info = {
            "nombre_display": request.form.get('nombre_display', prof_id),
            "asignatura": request.form.get('asignatura', ''),
            "avatar_color": request.form.get('avatar_color', '#10b981')
        }
        
        with open(target_dir / "info.json", "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
            
        fotos = request.files.getlist('fotos')
        saved_count = 0
        
        for i, foto in enumerate(fotos):
            if foto.filename == '':
                continue
            ext = os.path.splitext(foto.filename)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                continue
                
            filename = f"avatar{ext}" if i == 0 else f"foto_{i}{ext}"
            foto.save(str(target_dir / filename))
            saved_count += 1
            
        if saved_count == 0:
            return jsonify({"error": "No se subieron imágenes válidas."}), 400
            
        # Refrescar metadatos del motor inmediatamente (para verlo en Ausentes)
        with engine.lock:
            engine._load_all_teacher_meta()
            
        return jsonify({"success": True, "msg": f"Profesor guardado con {saved_count} fotos."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/admin/train', methods=['POST'])
def train_engine():
    try:
        # Ejecutar en hilo separado para no bloquear la interfaz HTTP
        def run_training():
            with engine.lock:
                # 1) Generar nuevos embeddings y guardar embeddings.pkl
                engine.register_faces()

                # 2) Recargar metadatos de profesores nuevos en memoria
                engine._load_all_teacher_meta()

                # 3) Recargar embeddings desde disco → los workers los usan en el próximo frame
                engine._load_embeddings()

            print("[TRAIN] Motor actualizado en memoria con nuevos profesores.")

        threading.Thread(target=run_training, daemon=True).start()
        return jsonify({"success": True, "msg": "Entrenamiento iniciado en segundo plano."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/admin/reset', methods=['PATCH'])
def reset_presence():
    """Fuerza la salida (absent) de TODOS los profesores en memoria."""
    try:
        with engine.lock:
            for folder_name in engine.presence_state:
                engine.presence_state[folder_name]["present"] = False
                engine.presence_state[folder_name]["hits_in"] = 0
                engine.presence_state[folder_name]["hits_out"] = 0
        return jsonify({"success": True, "msg": "Se ha marcado a todos como ausentes."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_flask():
    """Flask corre en hilo secundario para que el hilo principal pueda manejar la ventana."""
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


if __name__ == '__main__':
    # Flask en hilo secundario
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("[OK] Flask iniciado en hilo secundario → http://127.0.0.1:5000")

    # Cámara + ventana OpenCV en hilo principal (requerido por Windows)
    engine.start_camera()
