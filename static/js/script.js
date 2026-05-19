/**
 * Teacher Monitor Dashboard
 * Polling al endpoint /api/status cada 3 segundos → actualiza DOM sin recargar.
 */

// ─── Reloj y fecha en vivo ───────────────────────────────────────────────────
function updateClock() {
    const now = new Date();

    const elTime = document.getElementById('live-clock');
    if (elTime) {
        elTime.textContent = now.toLocaleTimeString('es-ES', {
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
    }

    const elWeekday = document.getElementById('live-weekday');
    const elDate    = document.getElementById('live-date');
    if (elWeekday) {
        const wd = now.toLocaleDateString('es-ES', { weekday: 'long' });
        elWeekday.textContent = wd.charAt(0).toUpperCase() + wd.slice(1);
    }
    if (elDate) {
        elDate.textContent = now.toLocaleDateString('es-ES', {
            day: 'numeric', month: 'long', year: 'numeric'
        });
    }
}
setInterval(updateClock, 1000);
updateClock();

// ─── Helpers de DOM ──────────────────────────────────────────────────────────
function safeId(str) {
    // Convierte nombre de carpeta en id CSS válido (igual que Jinja)
    return str.replace(/\s+/g, '-').replace(/\./g, '');
}

function buildPresentCard(t) {
    const avatarHtml = t.avatar_url
        ? `<img class="avatar-photo" src="${t.avatar_url}" alt="${t.nombre}" style="--accent: ${t.avatar_color}" onerror="this.outerHTML='<div class=\'avatar-initials\' style=\'--accent:${t.avatar_color}\'>${t.nombre[0].toUpperCase()}</div>'">`
        : `<div class="avatar-initials" style="--accent: ${t.avatar_color}">${t.nombre[0].toUpperCase()}</div>`;

    return `
    <div class="teacher-card present-card fade-in" id="card-${safeId(t.id)}">
        <div class="avatar-container">
            ${avatarHtml}
            <div class="status-ring present-ring"></div>
        </div>
        <div class="teacher-info">
            <h3>${t.nombre}</h3>
            <p>${t.asignatura}</p>
        </div>
    </div>`;
}

function buildAbsentCard(t) {
    const avatarHtml = t.avatar_url
        ? `<img class="avatar-photo-md" src="${t.avatar_url}" alt="${t.nombre}" style="--accent: ${t.avatar_color}" onerror="this.outerHTML='<div class=\'avatar-initials-md\' style=\'--accent:${t.avatar_color}\'>${t.nombre[0].toUpperCase()}</div>'">`
        : `<div class="avatar-initials-md" style="--accent: ${t.avatar_color}">${t.nombre[0].toUpperCase()}</div>`;

    return `
    <div class="absent-avatar fade-in" title="${t.nombre} • ${t.asignatura}">
        ${avatarHtml}
    </div>`;
}

// ─── Paginación de Presentes ──────────────────────────────────────────────────
let globalPresentTeachers = [];
let currentPresentPage = 0;
const PAGE_SIZE = 33; // Exactamente 3 filas de 11 para que no se corte hacia abajo
const PAGE_FLIP_MS = 6000;

function renderPresentPage() {
    const listPresent = document.getElementById('list-present');
    if (!listPresent) return;

    if (globalPresentTeachers.length === 0) {
        const emptyHtml = `<div class="empty-state" id="empty-present">
                <span class="empty-icon">📷</span>
                <p>Ningún profesor detectado aún</p>
                <small>La cámara está analizando...</small>
               </div>`;
        if (listPresent.innerHTML !== emptyHtml) listPresent.innerHTML = emptyHtml;
        return;
    }

    const totalPages = Math.ceil(globalPresentTeachers.length / PAGE_SIZE);
    if (currentPresentPage >= totalPages) currentPresentPage = 0;

    const start = currentPresentPage * PAGE_SIZE;
    const items = globalPresentTeachers.slice(start, start + PAGE_SIZE);

    const newHTML = items.map(buildPresentCard).join('');
    // Evitar parpadeos innecesarios por el fade-in css
    if (listPresent.innerHTML !== newHTML) {
        listPresent.innerHTML = newHTML;
    }
}

setInterval(() => {
    if (globalPresentTeachers.length > PAGE_SIZE) {
        currentPresentPage++;
        renderPresentPage();
    }
}, PAGE_FLIP_MS);

// ─── Actualizar dashboard con datos frescos ───────────────────────────────────
function applyStatus(teachers) {
    globalPresentTeachers = teachers.filter(t => t.status === 'present');
    const absent  = teachers.filter(t => t.status === 'absent');

    // Contadores
    document.getElementById('count-present').textContent = globalPresentTeachers.length;
    document.getElementById('count-absent').textContent  = absent.length;

    // Panel PRESENTES
    renderPresentPage();

    // Panel AUSENTES
    const listAbsent = document.getElementById('list-absent');
    if (listAbsent) {
        listAbsent.innerHTML = absent.length > 0
            ? absent.map(buildAbsentCard).join('')
            : `<div class="empty-state" style="width: 100%">
                <span class="empty-icon">🎉</span>
                <p>¡Todos los profesores están presentes!</p>
               </div>`;
    }
}

// ─── Label de tiempo desde último refresh ────────────────────────────────────
let lastRefreshTime = Date.now();
let refreshFailed   = false;

setInterval(() => {
    const el = document.getElementById('refresh-label');
    if (!el) return;
    const sec = Math.round((Date.now() - lastRefreshTime) / 1000);
    if (refreshFailed) {
        el.textContent = `⚠ Sin conexión (${sec}s)`;
        el.style.color = '#ef4444';
    } else if (sec < 2) {
        el.textContent = 'Actualizado ahora';
        el.style.color = '#10b981';
    } else {
        el.textContent = `Hace ${sec}s`;
        el.style.color = '#94a3b8';
    }
}, 1000);

// ─── Polling principal ────────────────────────────────────────────────────────
async function pollStatus() {
    try {
        const res  = await fetch('/api/status');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        let data = await res.json();
        
        applyStatus(data);
        lastRefreshTime = Date.now();
        refreshFailed   = false;

        // Indicador de cámara verde
        const cam = document.getElementById('cam-indicator');
        if (cam) cam.classList.remove('cam-error');
    } catch (err) {
        refreshFailed = true;
        console.warn('[Monitor] Error polling /api/status:', err.message);
        const cam = document.getElementById('cam-indicator');
        if (cam) cam.classList.add('cam-error');
        
        // Forzar a todos a estar ausentes si se pierde la conexión
        if (window.TEACHER_META) {
            const allAbsent = window.TEACHER_META.map(t => ({ ...t, status: 'absent' }));
            applyStatus(allAbsent);
        }
    }
}

// Primera llamada inmediata, luego cada 2 segundos
pollStatus();
setInterval(pollStatus, 2000);

console.log('[Teacher Monitor] Dashboard iniciado con polling activo');
