// admin.js

document.getElementById('add-teacher-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('btn-submit');
    const msgBox = document.getElementById('form-msg');
    const form = e.target;
    
    btn.disabled = true;
    btn.textContent = 'Guardando...';
    msgBox.style.display = 'none';
    
    const formData = new FormData(form);
    
    try {
        const response = await fetch('/api/admin/teacher', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (response.ok) {
            msgBox.className = 'message-box msg-success';
            msgBox.textContent = '✅ Profesor guardado correctamente.';
            msgBox.style.display = 'block';
            form.reset();
            // Restaurar color por defecto
            document.getElementById('avatar_color').value = '#10b981';
        } else {
            throw new Error(data.error || 'Error desconocido.');
        }
    } catch (err) {
        msgBox.className = 'message-box msg-error';
        msgBox.textContent = `❌ Error: ${err.message}`;
        msgBox.style.display = 'block';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Guardar Profesor';
    }
});

document.getElementById('btn-train').addEventListener('click', async (e) => {
    const btn = e.target;
    const msgBox = document.getElementById('train-msg');
    
    btn.disabled = true;
    btn.textContent = 'Reescanenando caras (puede tardar)...';
    msgBox.style.display = 'none';
    
    try {
        const response = await fetch('/api/admin/train', { method: 'POST' });
        const data = await response.json();
        
        if (response.ok) {
            msgBox.className = 'message-box msg-success';
            msgBox.textContent = `✅ Listo. Modelos re-entrenados con éxito.`;
        } else {
            throw new Error(data.error || 'Error al entrenar.');
        }
    } catch (err) {
        msgBox.className = 'message-box msg-error';
        msgBox.textContent = `❌ Error: ${err.message}`;
    } finally {
        msgBox.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Reescanear y Entrenar Modelos';
    }
});

document.getElementById('btn-reset').addEventListener('click', async (e) => {
    const btn = e.target;
    const msgBox = document.getElementById('reset-msg');
    
    if (!confirm("¿Seguro que deseas vaciar la Sala de Profesores de golpe?")) return;
    
    btn.disabled = true;
    btn.textContent = 'Borrando sala...';
    msgBox.style.display = 'none';
    
    try {
        const response = await fetch('/api/admin/reset', { method: 'PATCH' });
        const data = await response.json();
        
        if (response.ok) {
            msgBox.className = 'message-box msg-success';
            msgBox.textContent = `✅ Sala de Profesores vaciada exitosamente.`;
        } else {
            throw new Error(data.error || 'Error al resetear.');
        }
    } catch (err) {
        msgBox.className = 'message-box msg-error';
        msgBox.textContent = `❌ Error: ${err.message}`;
    } finally {
        msgBox.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Marcar todos Ausentes';
    }
});
