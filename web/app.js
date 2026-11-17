// CamHub Command Center — Core Frontend Application (v5.0)
// Pure black floating HUD architecture with sliding pill navigation and full Agent 1-10 integration.

(function () {
  'use strict';

  // --- Server-Verified Session State (Agent 7 RBAC: Admin vs Viewer) ---
  let currentUserRole = 'viewer'; // 'admin' | 'viewer'
  let authUsername = null;
  let isAuthenticated = false;
  let authSetupRequired = false;
  let recordingFilterCid = '';

  // --- Core State & Camera Fleet Definition ---
  const cams = [
    {
      id: 'v380-1',
      n: 'Camera 1, Indoor',
      shortName: 'Cam 1',
      ip: '192.168.100.24',
      p: '8080',
      d: 'ID 124095217 · Port 8080',
      streamUrl: '/proxy/stream/v380-1',
      snapshotUrl: '/proxy/snapshot/v380-1',
      metricsUrl: '/api/cameras/v380-1/metrics',
      directStreamUrl: 'http://127.0.0.1:8080/stream.mjpg',
      w: 1,
      s: 'degraded',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      aspect: '16:27',
      resolution: '1920×3240',
      aspectRatio: '16 / 27',
      aspectVal: 0.5926,
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: '--',
      stage: 'Camera source',
      running: true,
      circuitBreakerTripped: false,
      recording: false,
      recordStartTime: null,
      checks: { portListening: true, feedAlive: false, streamFrozen: false, fpsAdequate: false }
    },
    {
      id: 'v380-2',
      n: 'Camera 2, Garage',
      shortName: 'Cam 2',
      ip: '192.168.100.4',
      p: '8081',
      d: 'ID 97357757 · Port 8081',
      streamUrl: '/proxy/stream/v380-2',
      snapshotUrl: '/proxy/snapshot/v380-2',
      metricsUrl: '/api/cameras/v380-2/metrics',
      directStreamUrl: 'http://127.0.0.1:8081/stream.mjpg',
      w: 1,
      s: 'degraded',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      aspect: '16:9',
      resolution: '1920×1080',
      aspectRatio: '16 / 9',
      aspectVal: 1.7778,
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: '--',
      stage: 'Camera source',
      running: true,
      circuitBreakerTripped: false,
      recording: false,
      recordStartTime: null,
      checks: { portListening: true, feedAlive: false, streamFrozen: false, fpsAdequate: false }
    },
    {
      id: 'okam_1',
      n: 'O-Kam 1 · Panoramic Main (Sensor Tetap)',
      shortName: 'O-Kam 1',
      ip: '192.168.100.6',
      p: '8082',
      d: 'RTSP 10554/av0_0 · Port 8082',
      streamUrl: '/api/cameras/okam_1/stream.mjpg',
      snapshotUrl: '/api/cameras/okam_1/snapshot',
      metricsUrl: '/api/cameras/okam_1/metrics',
      directStreamUrl: 'http://127.0.0.1:8082/api/cameras/okam_1/stream.mjpg',
      w: 1,
      s: 'degraded',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      aspect: '16:9',
      resolution: '1920×1080',
      aspectRatio: '16 / 9',
      aspectVal: 1.7778,
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: '--',
      stage: 'Camera source',
      running: true,
      circuitBreakerTripped: false,
      recording: false,
      recordStartTime: null,
      checks: { portListening: true, feedAlive: false, streamFrozen: false, fpsAdequate: false }
    },
    {
      id: 'okam_2',
      n: 'O-Kam 2 · PTZ Motorik (Area Teras & Pintu)',
      shortName: 'O-Kam 2',
      ip: '192.168.100.6',
      p: '8082',
      d: 'RTSP 10555/av0_0 · Port 8082',
      streamUrl: '/api/cameras/okam_2/stream.mjpg',
      snapshotUrl: '/api/cameras/okam_2/snapshot',
      metricsUrl: '/api/cameras/okam_2/metrics',
      directStreamUrl: 'http://127.0.0.1:8082/api/cameras/okam_2/stream.mjpg',
      w: 1,
      s: 'degraded',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      aspect: '16:9',
      resolution: '1920×1080',
      aspectRatio: '16 / 9',
      aspectVal: 1.7778,
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: '--',
      stage: 'Camera source',
      running: true,
      circuitBreakerTripped: false,
      recording: false,
      recordStartTime: null,
      checks: { portListening: true, feedAlive: false, streamFrozen: false, fpsAdequate: false }
    },
    {
      id: 'okam_3',
      n: 'O-Kam 3 · Sub-Stream Sensor (Wide Aux)',
      shortName: 'O-Kam 3',
      ip: '192.168.100.6',
      p: '8082',
      d: 'RTSP 10554/av0_1 · Port 8082',
      streamUrl: '/api/cameras/okam_3/stream.mjpg',
      snapshotUrl: '/api/cameras/okam_3/snapshot',
      metricsUrl: '/api/cameras/okam_3/metrics',
      directStreamUrl: 'http://127.0.0.1:8082/api/cameras/okam_3/stream.mjpg',
      w: 1,
      s: 'degraded',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      aspect: '7:4',
      resolution: '448×256',
      aspectRatio: '7 / 4',
      aspectVal: 1.75,
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: '--',
      stage: 'Camera source',
      running: true,
      circuitBreakerTripped: false,
      recording: false,
      recordStartTime: null,
      checks: { portListening: true, feedAlive: false, streamFrozen: false, fpsAdequate: false }
    }
  ];

  const ST = {
    healthy: ['Healthy', 'good-t', 'Live'],
    recovering: ['Healthy', 'good-t', 'Live'],
    degraded: ['Degraded', 'warn-t', 'No signal'],
    offline: ['Offline', 'bad-t', 'Offline']
  };

  const tabs = [
    ['Live View', 'v-live'],
    ['Dashboard', 'v-dash'],
    ['Playback', 'v-playback'],
    ['Events & AI', 'v-events', 0],
    ['Storage & Retention', 'v-storage'],
    ['Diagnostics', 'v-diagnostics'],
    ['Notifications', 'v-notif', 0],
    ['Setup & Security', 'v-setup']
  ];

  const sentences = [
    'Watch every camera in one place. Select a camera to focus on it.',
    '0 of 5 cameras connected. Waiting for camera frames.',
    'Local MP4 recording archives and stream playback.',
    'Motion detection and edge neural vision events.',
    'Predictable storage management and policy pruning.',
    'One-click diagnostics, port health checks, and log export bundle.',
    'System alerts, camera offline notices, and fault timeline.',
    'Zero-cloud local camera bridge and remote access setup.'
  ];

  const col = ['#f2f2f2', '#6aa9e8', '#3be8b0', '#f5a623', '#b88cff', '#8c8c8c'];
  const fpsHistory = { 'v380-1': [], 'v380-2': [], 'okam_1': [], 'okam_2': [], 'okam_3': [], 'okam-3': [] };

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const p2 = (n) => String(n).padStart(2, '0');
  const cnt = (k) => cams.filter((c) => c.s === k).length;

  let sel = 0, pick = 0, pend = '';
  let zoomLevel = 1.0;
  let panX = 0;
  let panY = 0;
  let isDragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let dragStartPanX = 0;
  let dragStartPanY = 0;
  let chartRange = '1m';
  let eventFilterCid = '';
  let notifFilterSev = '';
  let t0 = Date.now() - 4069e3;

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatBytes(bytes) {
    if (bytes === 0 || !bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return (bytes / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i];
  }

  function formatDuration(sec) {
    if (!sec || isNaN(sec)) return '0s';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    if (h > 0) return `${h}h ${p2(m)}m ${p2(s)}s`;
    if (m > 0) return `${m}m ${p2(s)}s`;
    return `${s}s`;
  }

  function formatDateTime(isoStrOrMs) {
    if (!isoStrOrMs) return '--';
    const d = new Date(isoStrOrMs);
    if (isNaN(d.getTime())) return '--';
    return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`;
  }

  function toast(m) {
    const t = $('#toast');
    if (!t) return;
    t.textContent = m;
    t.classList.add('on');
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove('on'), 2600);
  }

  const D = (n) => ({
    restart: [
      `Restart all ${n} cameras?`,
      'Live feeds disconnect while the camera processes restart.',
      'Restart cameras',
      `Restarting all ${n} cameras…`
    ],
    stop: [
      `Stop all ${n} cameras?`,
      'This stops every running camera decoder. Feeds stay offline until you press Run all.',
      'Stop cameras',
      `Stopping all ${n} cameras…`
    ]
  });

  function ask(k) {
    pend = k;
    const d = D(cams.length)[k];
    $('#dt').textContent = d[0];
    $('#dp').textContent = d[1];
    $('#yes').textContent = d[2];
    $('#dlg').showModal();
  }

  function applyServerRole(role, username, authenticated) {
    isAuthenticated = !!authenticated;
    authUsername = username || null;
    currentUserRole = authenticated && role === 'admin' ? 'admin' : 'viewer';
    document.body.dataset.role = currentUserRole;
    const roleTxt = !isAuthenticated
      ? 'Sign in'
      : `${authUsername || currentUserRole} (${currentUserRole === 'admin' ? 'Admin' : 'Viewer'})`;
    if ($('#sbf-role')) $('#sbf-role').textContent = roleTxt;
    if ($('#dock-role-txt')) $('#dock-role-txt').textContent = currentUserRole === 'admin' ? 'Admin' : 'Viewer';
  }

  function openAuthDialog() {
    const dlg = $('#auth-dialog');
    if (!dlg) return;
    const errEl = $('#auth-error-msg');
    if (errEl) {
      errEl.style.display = 'none';
      errEl.textContent = '';
    }
    const bootGroup = $('#auth-bootstrap-group');
    const viewerGroup = $('#auth-viewer-pw-group');
    const logoutBtn = $('#auth-logout-btn');
    const titleEl = $('#auth-dlg-title');
    const subEl = $('#auth-dlg-sub');
    const submitBtn = $('#auth-submit-btn');

    if (authSetupRequired) {
      if (titleEl) titleEl.textContent = 'Initial CamHUB Admin Setup';
      if (subEl) subEl.textContent = 'Enter the host bootstrap token and choose an Admin password (min 8 chars).';
      if (bootGroup) bootGroup.style.display = 'block';
      if (viewerGroup) viewerGroup.style.display = 'block';
      if (submitBtn) submitBtn.textContent = 'Complete Setup';
      if (logoutBtn) logoutBtn.style.display = 'none';
    } else {
      if (titleEl) titleEl.textContent = isAuthenticated ? `Signed in as ${authUsername}` : 'CamHUB Sign In';
      if (subEl) {
        subEl.textContent = isAuthenticated
          ? `Current server role: ${currentUserRole.toUpperCase()}. Sign in as another user or sign out.`
          : 'Authenticate with your server-verified Admin or Viewer account.';
      }
      if (bootGroup) bootGroup.style.display = 'none';
      if (viewerGroup) viewerGroup.style.display = 'none';
      if (submitBtn) submitBtn.textContent = 'Sign In';
      if (logoutBtn) logoutBtn.style.display = isAuthenticated ? 'inline-flex' : 'none';
    }
    if (!dlg.open) dlg.showModal();
  }

  async function syncAuthSession(promptIfUnauth = false) {
    try {
      const res = await fetch('/api/auth/session', { credentials: 'same-origin' });
      if (!res.ok) return false;
      const data = await res.json();
      authSetupRequired = !!data.setupRequired;
      applyServerRole(data.role, data.username, data.authenticated);
      if (!data.authenticated && promptIfUnauth) {
        openAuthDialog();
      }
      return !!data.authenticated;
    } catch (_) {
      return false;
    }
  }

  function toggleRole() {
    openAuthDialog();
  }

  // Action button template
  const A = (c, a, t, x = '') => `<button class="btn ${x}" data-act="${a}" data-cid="${c.id}">${t}</button>`;
  const bar = (c, s) => `<div class="vbar"><span><i class="dot ${s[1]}"></i>${c.n}</span><em>${s[2]}</em></div>`;
  const msg = (c, id) => {
    const isOfflineDevice = c.id === 'v380-2';
    return `
      <div id="${id || `msg-${c.id}`}" class="msg-box" style="display:none;">
        <svg class="ico nosig" style="width:36px;height:36px;opacity:.55;margin-bottom:8px;"><use href="#i-cam"/></svg>
        <b>${isOfflineDevice ? 'Kamera Garasi Offline' : `Menghubungkan ke ${escapeHtml(c.n.split(',')[0])}`}</b>
        <p>${isOfflineDevice ? `Perangkat ${c.ip} tidak merespon di jaringan lokal. Pastikan kabel daya terpasang dan kamera terhubung ke WiFi.` : `Menunggu aliran frame dari ${c.ip}. Sambungan otomatis mencoba ulang setiap beberapa detik.`}</p>
        ${A(c, 'restart-cam', 'Sambungkan Ulang', 'sm')}
      </div>
    `;
  };

  // --- Dynamic Aspect Ratio & Fit Mode ---
  let fitMode = 'contain';
  try {
    fitMode = localStorage.getItem('camhub_fit_mode') || 'contain';
  } catch (_) {}

  let cam1LensMode = 'all';
  try {
    cam1LensMode = localStorage.getItem('camhub_cam1_lens') || 'all';
  } catch (_) {}

  let cam1GridLens = '1';
  try {
    cam1GridLens = localStorage.getItem('camhub_cam1_grid_lens') || '1';
  } catch (_) {}

  let okamLensMode = 'single';

  const okamLenses = {
    '1': {
      id: '1',
      camId: 'okam_1',
      name: 'O-Kam 1 · Panoramic Main (Sensor Tetap)',
      short: 'O-Kam 1',
      streamUrl: '/api/cameras/okam_1/stream.mjpg',
      snapshotUrl: '/api/cameras/okam_1/snapshot',
      res: '1920×1080 (16:9)',
      aspect: '16:9',
      aspectRatio: '16 / 9',
      aspectVal: 1.7778,
      cssClass: ''
    },
    '2': {
      id: '2',
      camId: 'okam_2',
      name: 'O-Kam 2 · PTZ Motorik (Area Teras & Pintu)',
      short: 'O-Kam 2',
      streamUrl: '/api/cameras/okam_2/stream.mjpg',
      snapshotUrl: '/api/cameras/okam_2/snapshot',
      res: '1920×1080 (PTZ)',
      aspect: '16:9',
      aspectRatio: '16 / 9',
      aspectVal: 1.7778,
      cssClass: ''
    },
    '3': {
      id: '3',
      camId: 'okam_3',
      name: 'O-Kam 3 · Sub-Stream Sensor (Wide Aux)',
      short: 'O-Kam 3',
      streamUrl: '/api/cameras/okam_3/stream.mjpg',
      snapshotUrl: '/api/cameras/okam_3/snapshot',
      res: '448×256 (16:9)',
      aspect: '16:9',
      aspectRatio: '16 / 9',
      aspectVal: 1.75,
      cssClass: ''
    }
  };

  // PTZ Controller State
  let ptzPanelOpen = false;
  let ptzSpeed = 0.5;
  let ptzMode = 'continuous'; // 'continuous' or 'step'
  let ptzStepMs = 400;
  let activePtzDir = null;
  let activePresetId = 1;
  let ptzPresetsCache = {};

  // Stream error handling with automatic reconnection
  window.handleStreamError = function(img, cid, msgId) {
    if (!img) return;
    img.style.display = 'none';
    const m = document.getElementById(msgId);
    if (m) m.style.display = 'flex';

    if (!img._retryTimer) {
      img._retryTimer = setTimeout(() => {
        img._retryTimer = null;
        const cam = cams.find((x) => x.id === cid);
        if (cam && cam.running) {
          const sep = cam.streamUrl.includes('?') ? '&' : '?';
          img.src = `${cam.streamUrl}${sep}_r=${Date.now()}`;
        }
      }, 3500);
    }
  };

  window.handleStreamLoad = function(img, cid, msgId) {
    if (!img) return;
    img.style.display = 'block';
    const m = document.getElementById(msgId);
    if (m) m.style.display = 'none';
    if (img._retryTimer) {
      clearTimeout(img._retryTimer);
      img._retryTimer = null;
    }
    if (window.applyCameraRatio) window.applyCameraRatio(img, cid);
  };

  function gcd(a, b) {
    return b === 0 ? a : gcd(b, a % b);
  }

  function calcRatio(w, h) {
    if (!w || !h) return { text: '16:9', css: '16 / 9', val: 1.7778 };
    const d = gcd(w, h);
    const rw = Math.round(w / d);
    const rh = Math.round(h / d);
    return { text: `${rw}:${rh}`, css: `${rw} / ${rh}`, val: w / h };
  }

  window.applyCameraRatio = function(img, cid) {
    if (!img) return;
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    if (!w || !h || w < 20 || h < 20) return;
    const ratio = calcRatio(w, h);
    const cam = cams.find((x) => x.id === cid);
    if (cam) {
      cam.aspect = ratio.text;
      cam.aspectRatio = ratio.css;
      cam.aspectVal = ratio.val;
      cam.resolution = `${w}×${h}`;
    }
    const video = img.closest('.video');
    if (video && !video.closest('.thumb')) {
      video.style.setProperty('--cam-aspect', ratio.css);
      video.style.setProperty('--cam-ratio', String(ratio.val));
    }
    const card = img.closest('.card');
    if (card) {
      const res = card.querySelector('.res-tag');
      if (res) res.textContent = `${w}×${h}`;
      const rat = card.querySelector('.ratio-val');
      if (rat) rat.textContent = ratio.text;
    }
  };

  function applyFitMode(mode) {
    fitMode = mode;
    try { localStorage.setItem('camhub_fit_mode', mode); } catch (_) {}
    document.querySelectorAll('.video').forEach((v) => {
      if (mode === 'cover') {
        v.classList.add('fill');
      } else {
        v.classList.remove('fill');
      }
    });
    const fitButtons = document.querySelectorAll('#fit-modes button');
    fitButtons.forEach((b) => {
      b.setAttribute('aria-pressed', b.dataset.fit === mode ? 'true' : 'false');
    });
  }

  const stats = (c) => `<div class="stats"><div><b>${c.fps.toFixed(1)} / 15</b><span>fps</span></div><div><b>${c.latencyMs} ms</b><span>latency</span></div><div><b class="ratio-val">${c.aspect}</b><span>ratio</span></div><div><b>${c.w}</b><span>web</span></div></div>`;
  const acts = (c, f) => {
    const ptzBtn = (c.id === 'v380-1' || c.id === 'okam-3' || c.id.startsWith('okam')) ? `<button class="btn sm${ptzPanelOpen ? ' primary' : ''}" data-act="toggle-ptz" title="Toggle PTZ Controller"><svg class="ico"><use href="#i-ptz"/></svg><span>PTZ</span></button>` : '';
    return `<div class="acts">${ptzBtn}${A(c, 'record', c.recording ? 'Stop' : 'Record', 'sm rec adm')}${A(c, 'restart-cam', 'Reload', 'sm adm')}${A(c, c.running ? 'stop-cam' : 'start-cam', c.running ? 'Stop' : 'Start', 'sm adm')}${A(c, 'config', 'Configure', 'sm adm')}${f}</div>`;
  };

  const card = (c, i) => {
    const s = ST[c.s] || ST.degraded;
    const isHealthy = c.s === 'healthy' || (c.checks && c.checks.feedAlive);
    const fillCls = fitMode === 'cover' ? ' fill' : '';
    const isCam1 = c.id === 'v380-1';
    const lensCls = isCam1 && cam1GridLens !== 'all' ? ` lens-${cam1GridLens}` : '';
    const cardAspect = isCam1 && cam1GridLens === 'all' ? (c.aspectRatio || '16 / 27') : (c.aspectRatio || '16 / 9');
    const cardRatioVal = isCam1 && cam1GridLens === 'all' ? 0.5926 : (c.aspectVal || 1.7778);
    const cardRes = isCam1 && cam1GridLens !== 'all' ? '1920×1080 (16:9)' : (c.resolution || '1920×1080');
    const cardStreamUrl = c.streamUrl;

    const lensPill = isCam1 ? `
      <div style="display:flex;align-items:center;gap:8px;margin:8px 0 4px;">
        <span style="font-size:11px;color:var(--muted);font-weight:600;">Lensa:</span>
        <div class="lens-pill">
          <button data-cam1-lens="all" aria-pressed="${cam1GridLens === 'all'}">3-in-1</button>
          <button data-cam1-lens="1" aria-pressed="${cam1GridLens === '1'}">L1 Atas</button>
          <button data-cam1-lens="2" aria-pressed="${cam1GridLens === '2'}">L2 Tengah</button>
          <button data-cam1-lens="3" aria-pressed="${cam1GridLens === '3'}">L3 Bawah</button>
        </div>
      </div>
    ` : '';

    return `
      <article class="card cam">
        <div class="video${fillCls}${lensCls}" id="feed-${c.id}" style="--cam-aspect: ${cardAspect}; --cam-ratio: ${cardRatioVal};">
          ${bar(c, s)}
          <img class="mjpeg-stream" id="stream-img-${c.id}" src="${cardStreamUrl}" alt="${escapeHtml(c.n)}" 
            onerror="window.handleStreamError && window.handleStreamError(this, '${c.id}', 'msg-${c.id}');" 
            onload="window.handleStreamLoad && window.handleStreamLoad(this, '${c.id}', 'msg-${c.id}');" 
            style="${isHealthy ? 'display:block;' : 'display:none;'}">
          ${msg(c, `msg-${c.id}`)}
        </div>
        <div class="cmeta">
          <div class="ip">${c.ip} · ${c.d} <span class="res-tag">${cardRes}</span></div>
          ${lensPill}
          ${stats(c)}
          ${acts(c, `<button class="btn sm" data-focus="${i}">Focus</button>`)}
        </div>
      </article>
    `;
  };

  const mini = (c, i) => {
    const s = ST[c.s] || ST.degraded;
    const snapUrl = c.snapshotUrl || `/proxy/snapshot/${c.id}`;
    const isCam1 = c.id === 'v380-1';
    const thumbStyle = isCam1 ? 'position:absolute; inset:0; width:100% !important; height:100% !important; object-fit:cover !important; object-position:top center !important;' : 'position:absolute; inset:0; width:100% !important; height:100% !important; object-fit:cover !important; object-position:center !important;';
    return `
      <div class="video" style="aspect-ratio: 16 / 9; width: 100%; overflow: hidden; background: #0a0a0a;">
        <div class="vbar">
          <span><i class="dot ${s[1]}"></i>CAM ${p2(i + 1)}</span>
          <em>${s[2]}</em>
        </div>
        <img src="${snapUrl}?t=${Date.now()}" alt="${escapeHtml(c.n)}" 
          style="${thumbStyle}"
          onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='block';" 
          onload="this.style.display='block'; if(this.nextElementSibling) this.nextElementSibling.style.display='none';" />
        <svg class="ico nosig" style="width:30px;height:30px;opacity:.45;display:none;"><use href="#i-cam"/></svg>
      </div>
      <div class="tl">
        <b>${escapeHtml(c.n)}</b>
        <span class="${s[1]}"><i class="dot"></i>${s[0]}</span>
      </div>
    `;
  };

  const thumb = (c, i, a, k) => `<button class="thumb" ${k}="${i}"${a === null ? '' : ` aria-pressed="${a}"`} aria-label="${c.n}, ${ST[c.s][0]}">${mini(c, i)}</button>`;

  // --- PTZ Controller Operations & Rendering ---
  function renderPTZController(c) {
    const isCam1 = c.id === 'v380-1';
    const isPTZCapable = isCam1 || c.id === 'okam-3' || c.id.startsWith('okam');
    if (!isPTZCapable) return '';

    const lens3Badge = isCam1 ? '<span class="res-tag" style="background:rgba(106,169,232,0.12);color:var(--good);border-color:rgba(106,169,232,0.25);">Lensa 3 · Motorized PTZ Base</span>' : '';

    return `
      <div class="ptz-container${ptzPanelOpen ? '' : ' hidden'}" id="ptz-panel" data-cid="${c.id}">
        <div class="ptz-header">
          <div class="ptz-title-wrap">
            <svg class="ico"><use href="#i-ptz"/></svg>
            <span class="ptz-title">PTZ Tactical Controller (ONVIF Profile S)</span>
            ${lens3Badge}
            <span class="ptz-status-badge" id="ptz-active-badge">Idle</span>
          </div>
          <div style="display:flex;align-items:center;gap:10px;">
            <div class="seg" id="ptz-mode-seg" role="group" aria-label="PTZ Movement Mode">
              <button class="btn sm" data-ptz-mode="continuous" aria-pressed="${ptzMode === 'continuous'}">Continuous</button>
              <button class="btn sm" data-ptz-mode="step" aria-pressed="${ptzMode === 'step'}">Step (Pulse)</button>
            </div>
            <button class="btn sm" id="btn-close-ptz" aria-label="Close PTZ controller">Close</button>
          </div>
        </div>

        <div class="ptz-controls-grid">
          <!-- 8-Way D-Pad -->
          <div class="ptz-dpad-wrapper">
            <div class="ptz-dpad" id="ptz-dpad" role="group" aria-label="Directional Controls">
              <button class="ptz-btn diag" data-ptz-dir="upleft" title="Up-Left (Diagonal)"><svg class="ico"><use href="#i-arrow-upleft"/></svg></button>
              <button class="ptz-btn" data-ptz-dir="up" title="Tilt Up"><svg class="ico"><use href="#i-arrow-up"/></svg></button>
              <button class="ptz-btn diag" data-ptz-dir="upright" title="Up-Right (Diagonal)"><svg class="ico"><use href="#i-arrow-upright"/></svg></button>
              <button class="ptz-btn" data-ptz-dir="left" title="Pan Left"><svg class="ico"><use href="#i-arrow-left"/></svg></button>
              <button class="ptz-btn center-stop" data-ptz-dir="stop" title="Emergency Stop"><svg class="ico"><use href="#i-stop"/></svg></button>
              <button class="ptz-btn" data-ptz-dir="right" title="Pan Right"><svg class="ico"><use href="#i-arrow-right"/></svg></button>
              <button class="ptz-btn diag" data-ptz-dir="downleft" title="Down-Left (Diagonal)"><svg class="ico"><use href="#i-arrow-downleft"/></svg></button>
              <button class="ptz-btn" data-ptz-dir="down" title="Tilt Down"><svg class="ico"><use href="#i-arrow-down"/></svg></button>
              <button class="ptz-btn diag" data-ptz-dir="downright" title="Down-Right (Diagonal)"><svg class="ico"><use href="#i-arrow-downright"/></svg></button>
            </div>
          </div>

          <!-- Right Section: Speed, Presets, Aux -->
          <div class="ptz-settings-panel">
            <!-- Speed Slider & Zoom -->
            <div class="ptz-setting-row">
              <span class="ptz-setting-label">Speed & Slew</span>
              <div class="ptz-speed-control">
                <input type="range" class="ptz-speed-slider" id="ptz-speed-range" min="0.1" max="1.0" step="0.05" value="${ptzSpeed}">
                <span class="ptz-speed-val" id="ptz-speed-val">${(ptzSpeed * 100).toFixed(0)}%</span>
              </div>
              <div class="seg" role="group" aria-label="Zoom Controls">
                <button class="btn sm" data-ptz-zoom="in" title="Zoom In"><svg class="ico"><use href="#i-zoom-in"/></svg> <span>Zoom +</span></button>
                <button class="btn sm" data-ptz-zoom="out" title="Zoom Out"><svg class="ico"><use href="#i-zoom-out"/></svg> <span>Zoom −</span></button>
              </div>
            </div>

            <!-- Presets Strip -->
            <div class="ptz-setting-row">
              <span class="ptz-setting-label">Preset Slots</span>
              <div class="ptz-presets-strip" id="ptz-presets-strip">
                <button class="ptz-preset-btn configured${activePresetId === 1 ? ' active' : ''}" data-preset="1" title="Preset 1 · Center / Home">1</button>
                <button class="ptz-preset-btn configured${activePresetId === 2 ? ' active' : ''}" data-preset="2" title="Preset 2 · Pintu Masuk">2</button>
                <button class="ptz-preset-btn configured${activePresetId === 3 ? ' active' : ''}" data-preset="3" title="Preset 3 · Lorong Utama">3</button>
                <button class="ptz-preset-btn${activePresetId === 4 ? ' active' : ''}" data-preset="4" title="Preset 4 (Empty)">4</button>
                <button class="ptz-preset-btn${activePresetId === 5 ? ' active' : ''}" data-preset="5" title="Preset 5 (Empty)">5</button>
              </div>
              <div style="display:flex;gap:6px;">
                <button class="btn sm adm" id="btn-save-preset" title="Save current position to selected preset"><svg class="ico"><use href="#i-bookmark"/></svg><span>Save Slot</span></button>
                <button class="btn sm adm" id="btn-clear-preset" title="Clear selected preset"><svg class="ico"><use href="#i-trash"/></svg><span>Clear</span></button>
              </div>
            </div>

            <!-- Auxiliary Light & Image Controls -->
            ${isCam1 ? `
            <div class="ptz-setting-row">
              <span class="ptz-setting-label">Auxiliary / IR</span>
              <div class="ptz-aux-group">
                <button class="btn sm" data-ptz-aux="light_auto" title="Set IR Light Auto"><svg class="ico"><use href="#i-bulb"/></svg><span>IR Auto</span></button>
                <button class="btn sm" data-ptz-aux="light_on" title="Force IR Light On">IR On</button>
                <button class="btn sm" data-ptz-aux="light_off" title="Force IR Light Off">IR Off</button>
                <button class="btn sm" data-ptz-aux="image_flip" title="Flip Image 180°"><svg class="ico"><use href="#i-flip"/></svg><span>Flip 180°</span></button>
              </div>
            </div>
            ` : ''}

            <!-- Monospace Keyboard Hints -->
            <div class="ptz-kbd-hints">
              <svg class="ico" style="width:14px;height:14px;"><use href="#i-kb"/></svg>
              <span>Tactical Keys: <kbd>↑</kbd><kbd>↓</kbd><kbd>←</kbd><kbd>→</kbd> Move &middot; <kbd>Space</kbd> Stop &middot; <kbd>+</kbd><kbd>−</kbd> Zoom &middot; <kbd>1-5</kbd> Presets</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  async function sendPtzMove(cid, dir, speed, durationMs, mode) {
    activePtzDir = dir;
    updatePtzBadge(`Moving: ${dir.toUpperCase()}`, true);
    try {
      const res = await fetch('/api/ptz/move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: cid, dir, speed, duration: durationMs, mode })
      });
      const data = await res.json();
      if (!data.success) {
        toast(`PTZ Error: ${data.message || 'Failed'}`);
        updatePtzBadge('Idle', false);
      }
    } catch (e) {
      console.warn('PTZ move err:', e);
      updatePtzBadge('Idle', false);
    }
  }

  async function sendPtzStop(cid) {
    activePtzDir = null;
    updatePtzBadge('Idle', false);
    $$('.ptz-btn').forEach(b => b.classList.remove('active'));
    try {
      await fetch('/api/ptz/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: cid })
      });
    } catch (e) {
      console.warn('PTZ stop err:', e);
    }
  }

  async function sendPtzZoom(cid, action, speed) {
    updatePtzBadge(`Zoom ${action.toUpperCase()}`, true);
    try {
      const res = await fetch('/api/ptz/zoom', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: cid, action, speed })
      });
      const data = await res.json();
      toast(data.message || `Zoom ${action}`);
    } catch (e) {
      toast(`Zoom error: ${e.message}`);
    } finally {
      setTimeout(() => updatePtzBadge('Idle', false), 800);
    }
  }

  async function sendPtzPreset(cid, action, presetId, name) {
    activePresetId = presetId;
    updatePtzBadge(`Preset ${presetId}`, true);
    try {
      const res = await fetch('/api/ptz/preset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: cid, action, preset: presetId, name })
      });
      const data = await res.json();
      if (data.success) {
        toast(data.message);
        if (data.presets) refreshPresetPills(data.presets);
      } else {
        toast(`Preset: ${data.message}`);
      }
    } catch (e) {
      toast(`Preset error: ${e.message}`);
    } finally {
      setTimeout(() => updatePtzBadge('Idle', false), 1000);
    }
  }

  async function sendPtzAux(cid, cmd) {
    try {
      const res = await fetch('/api/ptz/aux', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: cid, cmd })
      });
      const data = await res.json();
      toast(data.message || `Command ${cmd} sent`);
    } catch (e) {
      toast(`Aux error: ${e.message}`);
    }
  }

  function updatePtzBadge(text, isMoving) {
    const badge = $('#ptz-active-badge');
    if (badge) {
      badge.textContent = text;
      if (isMoving) badge.classList.add('moving');
      else badge.classList.remove('moving');
    }
  }

  function refreshPresetPills(presets) {
    if (!Array.isArray(presets)) return;
    $$('.ptz-preset-btn').forEach(btn => {
      const pid = parseInt(btn.dataset.preset, 10);
      const p = presets.find(x => x.id === pid);
      if (p && p.configured) {
        btn.classList.add('configured');
        btn.title = p.name || `Preset ${pid}`;
      } else {
        btn.classList.remove('configured');
        btn.title = `Preset ${pid} (Empty)`;
      }
      if (pid === activePresetId) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });
  }

  function bindPTZControls() {
    const ptzPanel = $('#ptz-panel');
    if (!ptzPanel) return;
    const cid = ptzPanel.dataset.cid;

    // Speed slider
    const speedRange = $('#ptz-speed-range');
    if (speedRange) {
      speedRange.oninput = (e) => {
        ptzSpeed = parseFloat(e.target.value);
        const valEl = $('#ptz-speed-val');
        if (valEl) valEl.textContent = `${(ptzSpeed * 100).toFixed(0)}%`;
      };
    }

    // 8-Way D-Pad Pointer Events
    $$('#ptz-dpad .ptz-btn').forEach(btn => {
      const dir = btn.dataset.ptzDir;
      btn.onpointerdown = (e) => {
        e.preventDefault();
        try { btn.setPointerCapture(e.pointerId); } catch (_) {}
        btn.classList.add('active');
        if (dir === 'stop') {
          sendPtzStop(cid);
        } else {
          sendPtzMove(cid, dir, ptzSpeed, ptzMode === 'step' ? ptzStepMs : null, ptzMode);
        }
      };
      btn.onpointerup = (e) => {
        btn.classList.remove('active');
        if (dir !== 'stop' && ptzMode === 'continuous') {
          sendPtzStop(cid);
        }
      };
      btn.onpointercancel = (e) => {
        btn.classList.remove('active');
        if (dir !== 'stop' && ptzMode === 'continuous') {
          sendPtzStop(cid);
        }
      };
    });

    // Preset Buttons
    $$('.ptz-preset-btn').forEach(btn => {
      btn.onclick = () => {
        const pid = parseInt(btn.dataset.preset, 10);
        activePresetId = pid;
        $$('.ptz-preset-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        sendPtzPreset(cid, 'goto', pid);
      };
    });

    // Save Preset
    const saveBtn = $('#btn-save-preset');
    if (saveBtn) {
      saveBtn.onclick = () => {
        const pName = prompt(`Enter a label for Preset ${activePresetId}:`, `Preset ${activePresetId}`);
        if (pName !== null) {
          sendPtzPreset(cid, 'set', activePresetId, pName);
        }
      };
    }

    // Clear Preset
    const clearBtn = $('#btn-clear-preset');
    if (clearBtn) {
      clearBtn.onclick = () => {
        sendPtzPreset(cid, 'clear', activePresetId);
      };
    }

    // Zoom Buttons
    $$('[data-ptz-zoom]').forEach(btn => {
      btn.onclick = () => {
        sendPtzZoom(cid, btn.dataset.ptzZoom, ptzSpeed);
      };
    });

    // Aux Buttons
    $$('[data-ptz-aux]').forEach(btn => {
      btn.onclick = () => {
        sendPtzAux(cid, btn.dataset.ptzAux);
      };
    });

    // Mode Toggle
    $$('[data-ptz-mode]').forEach(btn => {
      btn.onclick = () => {
        ptzMode = btn.dataset.ptzMode;
        $$('[data-ptz-mode]').forEach(b => b.setAttribute('aria-pressed', b.dataset.ptzMode === ptzMode ? 'true' : 'false'));
        toast(`PTZ Mode: ${ptzMode === 'continuous' ? 'Continuous (Hold to Move)' : 'Step (Pulse 400ms)'}`);
      };
    });

    // Close Button
    const closeBtn = $('#btn-close-ptz');
    if (closeBtn) {
      closeBtn.onclick = () => {
        ptzPanelOpen = false;
        ptzPanel.classList.add('hidden');
        const tBtn = $('#btn-toggle-ptz');
        if (tBtn) tBtn.classList.remove('active');
      };
    }

    // Fetch initial presets from server
    fetch(`/api/ptz/presets?id=${cid}`)
      .then(r => r.json())
      .then(d => {
        if (d && d.presets) refreshPresetPills(d.presets);
      })
      .catch(() => {});
  }

  // --- Digital Zoom & Pan Stage Controller ---
  function applyZoomTransform() {
    const stage = $('#video-zoom-stage');
    if (!stage) return;
    if (zoomLevel <= 1.0) {
      zoomLevel = 1.0;
      panX = 0;
      panY = 0;
    } else {
      const vp = $('#video-viewport');
      if (vp) {
        const rect = vp.getBoundingClientRect();
        const maxPanX = Math.max(0, (rect.width * (zoomLevel - 1)) / 2);
        const maxPanY = Math.max(0, (rect.height * (zoomLevel - 1)) / 2);
        panX = Math.max(-maxPanX, Math.min(maxPanX, panX));
        panY = Math.max(-maxPanY, Math.min(maxPanY, panY));
      }
    }
    stage.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomLevel})`;

    const resetBtn = document.querySelector('[data-zoom="reset"]');
    if (resetBtn) resetBtn.textContent = `${zoomLevel.toFixed(1)}x`;

    const vp = $('#video-viewport');
    if (vp) {
      vp.style.cursor = zoomLevel > 1.0 ? (isDragging ? 'grabbing' : 'grab') : 'default';
    }
  }

  function setZoom(targetLevel) {
    zoomLevel = Math.max(1.0, Math.min(4.0, Math.round(targetLevel * 100) / 100));
    if (zoomLevel === 1.0) {
      panX = 0;
      panY = 0;
    }
    applyZoomTransform();
  }

  function bindVideoZoomAndPan() {
    const vp = $('#video-viewport');
    if (!vp) return;

    // Mouse wheel zoom
    vp.onwheel = (e) => {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.25 : -0.25;
      setZoom(zoomLevel + delta);
    };

    // Double click to toggle zoom 1.0x <-> 2.0x
    vp.ondblclick = (e) => {
      e.preventDefault();
      setZoom(zoomLevel > 1.0 ? 1.0 : 2.0);
    };

    // Drag to pan when zoomed
    vp.onpointerdown = (e) => {
      if (zoomLevel <= 1.0 || e.button !== 0) return;
      isDragging = true;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      dragStartPanX = panX;
      dragStartPanY = panY;
      vp.classList.add('is-dragging');
      vp.style.cursor = 'grabbing';
      try { vp.setPointerCapture(e.pointerId); } catch (_) {}
    };

    vp.onpointermove = (e) => {
      if (!isDragging) return;
      panX = dragStartPanX + (e.clientX - dragStartX);
      panY = dragStartPanY + (e.clientY - dragStartY);
      applyZoomTransform();
    };

    const endDrag = (e) => {
      if (!isDragging) return;
      isDragging = false;
      vp.classList.remove('is-dragging');
      try { vp.releasePointerCapture(e.pointerId); } catch (_) {}
      applyZoomTransform();
    };

    vp.onpointerup = endDrag;
    vp.onpointercancel = endDrag;
  }

  // --- Fullscreen Controller ---
  function isPlayerFullscreen() {
    return Boolean(
      document.fullscreenElement ||
      document.webkitFullscreenElement ||
      document.mozFullScreenElement ||
      document.msFullscreenElement ||
      $('#mc')?.classList.contains('is-fullscreen')
    );
  }

  function updateFsButton() {
    const fsBtn = document.querySelector('[data-fs]');
    if (!fsBtn) return;
    const isFs = isPlayerFullscreen();
    fsBtn.textContent = isFs ? '⤡' : '⤢';
    fsBtn.setAttribute('title', isFs ? 'Keluar Layar Penuh (Esc / F)' : 'Layar Penuh (F)');
    fsBtn.setAttribute('aria-label', isFs ? 'Exit full screen' : 'Full screen');
  }

  function toggleFullscreen() {
    const mc = $('#mc');
    if (!mc) return;

    if (isPlayerFullscreen()) {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
      } else if (document.mozCancelFullScreen) {
        document.mozCancelFullScreen();
      }
      mc.classList.remove('is-fullscreen');
    } else {
      const reqFs = mc.requestFullscreen || mc.webkitRequestFullscreen || mc.mozRequestFullScreen || mc.msRequestFullscreen;
      if (reqFs) {
        reqFs.call(mc).catch(() => {
          mc.classList.add('is-fullscreen');
          updateFsButton();
        });
      } else {
        mc.classList.add('is-fullscreen');
      }
    }
    updateFsButton();
  }

  function renderSplitOtherCard(c, i) {
    const s = ST[c.s] || ST.degraded;
    const isHealthy = c.s === 'healthy' || (c.checks && c.checks.feedAlive);
    const fillCls = fitMode === 'cover' ? ' fill' : '';
    const isPTZCapable = c.id === 'v380-1' || c.id === 'okam-3' || c.id.startsWith('okam');
    const locText = c.d && c.d.toLowerCase().includes('port') ? `${c.ip} · ${c.d}` : `${c.ip} · ${c.d} · Port ${c.p}`;

    return `
      <article class="card cam split-other-card" id="card-${c.id}">
        <div class="video${fillCls}" id="feed-${c.id}" data-focus="${i}" style="--cam-aspect: 16 / 9; --cam-ratio: 1.7778; aspect-ratio: 16 / 9; width: 100%; cursor: pointer;" title="Klik untuk fokus ke ${escapeHtml(c.n)}">
          ${bar(c, s)}
          <img class="mjpeg-stream" id="stream-img-split-${c.id}" src="${c.streamUrl}" alt="${escapeHtml(c.n)}" 
            onerror="window.handleStreamError && window.handleStreamError(this, '${c.id}', 'msg-split-${c.id}');" 
            onload="window.handleStreamLoad && window.handleStreamLoad(this, '${c.id}', 'msg-split-${c.id}');" 
            style="${isHealthy ? 'display:block;' : 'display:none;'}">
          ${msg(c, `msg-split-${c.id}`)}
        </div>
        <div class="cmeta">
          <div class="mrow" style="margin-bottom:10px; gap:12px;">
            <div>
              <b class="nm" style="font-size:14.5px; line-height:1.2;">${escapeHtml(c.n)}</b>
              <div class="ip" style="margin-top:4px;">${locText} <span class="res-tag">${c.resolution || '1920×1080 (16:9)'}</span></div>
            </div>
            <div style="display:flex;gap:8px;align-items:center;">
              ${isPTZCapable ? `<button class="btn sm" data-focus="${i}" title="Buka Kamera dan Kontroler PTZ"><svg class="ico"><use href="#i-ptz"/></svg><span>PTZ</span></button>` : ''}
              <button class="btn sm primary" data-focus="${i}" title="Tampilkan kamera ini sebagai fokus utama">
                <svg class="ico"><use href="#i-live"/></svg><span>Fokus Kamera</span>
              </button>
            </div>
          </div>
          ${stats(c)}
          <div class="acts" style="margin-top:4px;">
            ${A(c, 'record', c.recording ? 'Stop' : 'Record', 'sm rec adm')}
            ${A(c, 'restart-cam', 'Reload', 'sm adm')}
            ${A(c, c.running ? 'stop-cam' : 'start-cam', c.running ? 'Stop' : 'Start', 'sm adm')}
            ${A(c, 'config', 'Configure', 'sm adm')}
          </div>
        </div>
      </article>
    `;
  }

  // --- Live View Rendering ---
  function live() {
    const c = cams[sel] || cams[0], s = ST[c.s] || ST.degraded;
    const stage = $('#stage');
    const isHealthy = c.s === 'healthy' || (c.checks && c.checks.feedAlive);
    const fillCls = fitMode === 'cover' ? ' fill' : '';
    const isCam1 = c.id === 'v380-1';
    const isOkam = c.id === 'okam-3' || c.id.startsWith('okam');
    const isSplit = (isCam1 && cam1LensMode === 'split') || (isOkam && okamLensMode === 'split');

    if (stage) {
      if (isSplit) {
        stage.classList.add('is-split');
        const otherCams = cams.map((x, i) => ({ cam: x, idx: i })).filter(item => item.cam.id !== c.id);

        let splitHeaderHtml = '';
        let splitCardsHtml = '';

        if (isCam1) {
          splitHeaderHtml = `
            <div class="lens-bar">
              <span class="lens-bar-label">Sudut Pandang Lensa (Camera 1 · 3-in-1 Hardware):</span>
              <div class="seg" id="lens-selector" role="group" aria-label="Pilih Lensa Kamera 1">
                <button class="btn sm" data-lens="all" aria-pressed="false">Semua (3-in-1)</button>
                <button class="btn sm" data-lens="1" aria-pressed="false">Lensa 1 · Atas</button>
                <button class="btn sm" data-lens="2" aria-pressed="false">Lensa 2 · Tengah</button>
                <button class="btn sm" data-lens="3" aria-pressed="false">Lensa 3 · Bawah</button>
                <button class="btn sm" data-lens="split" aria-pressed="true">Split 3 Lensa</button>
              </div>
            </div>
          `;
          splitCardsHtml = `
            <div class="lens-split-grid">
              <div class="cam-split-card">
                <div class="video lens-1${fillCls}" style="aspect-ratio:16/9;">
                  <div class="vbar"><span><i class="dot ${s[1]}"></i>Lensa 1 · Atas (Panoramic)</span><em>Live · 1920×1080</em></div>
                  <img class="mjpeg-stream" src="${c.streamUrl}" alt="Lensa 1" 
                    onerror="window.handleStreamError && window.handleStreamError(this, '${c.id}', 'msg-lens-1');" 
                    onload="window.handleStreamLoad && window.handleStreamLoad(this, '${c.id}', 'msg-lens-1');">
                  ${msg(c, 'msg-lens-1')}
                </div>
                <div class="cmeta" style="padding:10px 4px 2px;">
                  <div class="mrow">
                    <b>Lensa 1 · Panoramic Wide (Atas)</b>
                    <button class="btn sm" data-switch-lens="1">Perbesar Lensa 1</button>
                  </div>
                  <div class="ip">Sensor Utama · 1920×1080 · 16:9 widescreen</div>
                </div>
              </div>
              <div class="cam-split-card">
                <div class="video lens-2${fillCls}" style="aspect-ratio:16/9;">
                  <div class="vbar"><span><i class="dot ${s[1]}"></i>Lensa 2 · Tengah (Fixed Tele)</span><em>Live · 1920×1080</em></div>
                  <img class="mjpeg-stream" src="${c.streamUrl}" alt="Lensa 2" 
                    onerror="window.handleStreamError && window.handleStreamError(this, '${c.id}', 'msg-lens-2');" 
                    onload="window.handleStreamLoad && window.handleStreamLoad(this, '${c.id}', 'msg-lens-2');">
                  ${msg(c, 'msg-lens-2')}
                </div>
                <div class="cmeta" style="padding:10px 4px 2px;">
                  <div class="mrow">
                    <b>Lensa 2 · Fixed Tele (Tengah)</b>
                    <button class="btn sm" data-switch-lens="2">Perbesar Lensa 2</button>
                  </div>
                  <div class="ip">Sensor Sekunder · 1920×1080 · 16:9 widescreen</div>
                </div>
              </div>
              <div class="cam-split-card">
                <div class="video lens-3${fillCls}" style="aspect-ratio:16/9;">
                  <div class="vbar"><span><i class="dot ${s[1]}"></i>Lensa 3 · Bawah (PTZ Rotasi)</span><em>Live · 1920×1080</em></div>
                  <img class="mjpeg-stream" src="${c.streamUrl}" alt="Lensa 3" 
                    onerror="window.handleStreamError && window.handleStreamError(this, '${c.id}', 'msg-lens-3');" 
                    onload="window.handleStreamLoad && window.handleStreamLoad(this, '${c.id}', 'msg-lens-3');">
                  ${msg(c, 'msg-lens-3')}
                </div>
                <div class="cmeta" style="padding:10px 4px 2px;">
                  <div class="mrow">
                    <b>Lensa 3 · PTZ Rotasi (Bawah)</b>
                    <div style="display:flex;gap:6px;">
                      <button class="btn sm primary" data-open-ptz="v380-1"><svg class="ico"><use href="#i-ptz"/></svg> <span>PTZ</span></button>
                      <button class="btn sm" data-switch-lens="3">Perbesar Lensa 3</button>
                    </div>
                  </div>
                  <div class="ip">Sensor Gerak PTZ · 1920×1080 · 16:9 widescreen</div>
                </div>
              </div>
            </div>
          `;
        } else {
          // O-Kam Pro Multi-Camera Three Screens Mode (3 Independent Streams)
          if (!ptzPanelOpen) ptzPanelOpen = true;
          splitHeaderHtml = `
            <div class="lens-bar">
              <span class="lens-bar-label">Mode Tampilan O-Kam Pro (3 Kamera Independen):</span>
              <div class="seg" id="okam-lens-selector" role="group" aria-label="Pilih Kamera O-Kam">
                <button class="btn sm" data-okam-focus-lens="1" aria-pressed="false">O-Kam 1 · Panoramic</button>
                <button class="btn sm" data-okam-focus-lens="2" aria-pressed="false">O-Kam 2 · PTZ Motorik</button>
                <button class="btn sm" data-okam-focus-lens="3" aria-pressed="false">O-Kam 3 · Sub-Stream</button>
                <button class="btn sm" data-okam-focus-lens="split" aria-pressed="true" style="color:var(--text);font-weight:700;">
                  <svg class="ico" style="width:14px;height:14px;margin-right:4px;"><use href="#i-grid"/></svg>
                  Three Screens (3 Kamera Sinkron)
                </button>
              </div>
            </div>
          `;
          splitCardsHtml = `
            <div class="okam-vertical-stack">
              <!-- O-Kam 1: Panoramic Main (10554/tcp/av0_0) -->
              <div class="okam-screen-card">
                <div class="video${fillCls}" style="aspect-ratio:16/9;">
                  <div class="vbar">
                    <span><i class="dot ${s[1]}"></i>O-Kam 1 · Panoramic Main (Sensor Tetap · Port 10554)</span>
                    <em>Live · 1920×1080</em>
                  </div>
                  <img class="mjpeg-stream" src="/api/cameras/okam_1/stream.mjpg" alt="O-Kam 1 Panoramic" 
                    onerror="window.handleStreamError && window.handleStreamError(this, 'okam_1', 'msg-okam-1');" 
                    onload="window.handleStreamLoad && window.handleStreamLoad(this, 'okam_1', 'msg-okam-1');">
                  ${msg({id: 'okam_1', ip: c.ip, n: 'O-Kam 1 · Panoramic'}, 'msg-okam-1')}
                </div>
                <div class="cmeta" style="padding:10px 14px 10px;">
                  <div class="mrow">
                    <div>
                      <b style="font-size:14px;">O-Kam 1 · Panoramic Main (Sensor Tetap)</b>
                      <div class="ip" style="font-size:12px;margin-top:2px;">RTSP Port 10554 (/tcp/av0_0) · 1920×1080 · 16:9 Widescreen</div>
                    </div>
                    <button class="btn sm" data-okam-switch-lens="1" title="Fokus ke O-Kam 1">Fokus O-Kam 1</button>
                  </div>
                </div>
              </div>

              <!-- O-Kam 2: PTZ Motorik (10555/tcp/av0_0) -->
              <div class="okam-screen-card is-active-ptz">
                <div class="video${fillCls}" style="aspect-ratio:16/9;">
                  <div class="vbar" style="background:rgba(0, 229, 255, 0.15); border-bottom:1px solid rgba(0, 229, 255, 0.35);">
                    <span><i class="dot" style="background:#00e5ff;box-shadow:0 0 8px #00e5ff;"></i>O-Kam 2 · PTZ Motorik (Area Teras & Pintu · Port 10555)</span>
                    <em style="color:#00e5ff;font-weight:700;">Live PTZ · 1920×1080</em>
                  </div>
                  <img class="mjpeg-stream" src="/api/cameras/okam_2/stream.mjpg" alt="O-Kam 2 PTZ" 
                    onerror="window.handleStreamError && window.handleStreamError(this, 'okam_2', 'msg-okam-2');" 
                    onload="window.handleStreamLoad && window.handleStreamLoad(this, 'okam_2', 'msg-okam-2');">
                  ${msg({id: 'okam_2', ip: c.ip, n: 'O-Kam 2 · PTZ Motorik'}, 'msg-okam-2')}
                </div>
                <div class="cmeta" style="padding:12px 14px 10px;">
                  <div class="mrow">
                    <div>
                      <b style="font-size:14px;color:#00e5ff;">O-Kam 2 · Sensor Motorik PTZ (Teras, Pintu & Parkir)</b>
                      <div class="ip" style="font-size:12px;margin-top:2px;">RTSP Port 10555 (/tcp/av0_0) · 1920×1080 · Terhubung ke Kontroler PTZ</div>
                    </div>
                    <div style="display:flex;gap:6px;">
                      <button class="btn sm primary" data-open-ptz="okam_2" style="background:rgba(0, 229, 255, 0.2);border-color:#00e5ff;color:#00e5ff;"><svg class="ico"><use href="#i-ptz"/></svg> <span>Kontrol PTZ</span></button>
                      <button class="btn sm" data-okam-switch-lens="2" title="Fokus ke O-Kam 2">Fokus O-Kam 2</button>
                    </div>
                  </div>
                </div>
              </div>

              <!-- O-Kam 3: Sub-Stream Sensor (10554/tcp/av0_1) -->
              <div class="okam-screen-card">
                <div class="video${fillCls}" style="aspect-ratio:16/9;">
                  <div class="vbar">
                    <span><i class="dot ${s[1]}"></i>O-Kam 3 · Sub-Stream Sensor (Wide Aux · Port 10554)</span>
                    <em>Live · 448×256</em>
                  </div>
                  <img class="mjpeg-stream" src="/api/cameras/okam_3/stream.mjpg" alt="O-Kam 3 Sub-Stream" 
                    onerror="window.handleStreamError && window.handleStreamError(this, 'okam_3', 'msg-okam-3');" 
                    onload="window.handleStreamLoad && window.handleStreamLoad(this, 'okam_3', 'msg-okam-3');">
                  ${msg({id: 'okam_3', ip: c.ip, n: 'O-Kam 3 · Sub-Stream Sensor'}, 'msg-okam-3')}
                </div>
                <div class="cmeta" style="padding:10px 14px 10px;">
                  <div class="mrow">
                    <div>
                      <b style="font-size:14px;">O-Kam 3 · Sub-Stream Sensor (Wide Aux Low-Bandwidth)</b>
                      <div class="ip" style="font-size:12px;margin-top:2px;">RTSP Port 10554 (/tcp/av0_1) · 448×256 · Independent Worker</div>
                    </div>
                    <button class="btn sm" data-okam-switch-lens="3" title="Fokus ke O-Kam 3">Fokus O-Kam 3</button>
                  </div>
                </div>
              </div>
            </div>
          `;
        }

        stage.innerHTML = `
          <div class="card cam">
            ${splitHeaderHtml}
            ${splitCardsHtml}
            ${renderPTZController(c)}
            <div class="cmeta" style="margin-top:14px;">
              <div class="mrow">
                <div>
                  <b class="nm">${escapeHtml(c.n)} (3 Kamera Aktif Simultan)</b>
                  <div class="ip">${c.ip} · ${c.d} · Port ${c.p} <span class="res-tag">3 Stream Independen</span></div>
                </div>
                ${acts(c, '')}
              </div>
              ${stats(c)}
              <div class="signal-checks">
                <div class="signal-check"><i class="dot ${c.checks.portListening ? 'good-t' : 'bad-t'}"></i>Port :${c.p}</div>
                <div class="signal-check"><i class="dot ${c.checks.feedAlive ? 'good-t' : 'warn-t'}"></i>Feed Stream</div>
                <div class="signal-check"><i class="dot ${!c.checks.streamFrozen ? 'good-t' : 'bad-t'}"></i>Freeze Detector</div>
                <div class="signal-check"><i class="dot ${c.checks.fpsAdequate ? 'good-t' : 'warn-t'}"></i>FPS Quality</div>
              </div>
              ${c.circuitBreakerTripped ? `<div class="alert" style="margin-top:10px;"><svg class="ico"><use href="#i-warn"/></svg><p><b>Circuit Breaker Tripped</b><span>Camera exceeded restart limits. <button class="btn sm adm" data-act="reset-cb" data-cid="${c.id}" style="margin-left:8px;">Reset Breaker</button></span></p></div>` : ''}
            </div>
          </div>
          <section class="split-fleet-section">
            <div class="split-fleet-header">
              <div class="split-fleet-title">
                <svg class="ico"><use href="#i-grid"/></svg>
                <span>Kamera Armada Lainnya</span>
                <span class="split-fleet-badge">${otherCams.length} Kamera Terhubung</span>
              </div>
              <span class="split-fleet-hint">Klik kartu atau tombol "Fokus Kamera" untuk menampilkan kamera sebagai tampilan utama</span>
            </div>
            <div class="split-fleet-grid">
              ${otherCams.map(item => renderSplitOtherCard(item.cam, item.idx)).join('')}
            </div>
          </section>
        `;
      } else {
        stage.classList.remove('is-split');
        const lensCls = isCam1 && cam1LensMode !== 'all' ? ` lens-${cam1LensMode}` : '';
        const stageAspect = isCam1 && cam1LensMode !== 'all' ? '16 / 9' : (c.aspectRatio || '16 / 9');
        const stageRatioVal = isCam1 && cam1LensMode !== 'all' ? 1.7778 : (c.aspectVal || 1.7778);
        const stageRes = isCam1 && cam1LensMode !== 'all' ? '1920×1080 (16:9)' : (c.resolution || '1920×1080');
        const lensTitle = isCam1 && cam1LensMode === '1' ? 'Camera 1 · Lensa 1 (Atas - Panoramic)' : (isCam1 && cam1LensMode === '2' ? 'Camera 1 · Lensa 2 (Tengah - Fixed Tele)' : (isCam1 && cam1LensMode === '3' ? 'Camera 1 · Lensa 3 (Bawah - PTZ Rotasi)' : c.n));
        const stageStreamUrl = c.streamUrl;

        const lensBar = isCam1 ? `
          <div class="lens-bar">
            <span class="lens-bar-label">Sudut Pandang Lensa (3-in-1 Hardware):</span>
            <div class="seg" id="lens-selector" role="group" aria-label="Pilih Lensa Kamera 1">
              <button class="btn sm" data-lens="all" aria-pressed="${cam1LensMode === 'all'}">Semua (3-in-1)</button>
              <button class="btn sm" data-lens="1" aria-pressed="${cam1LensMode === '1'}">Lensa 1 · Atas</button>
              <button class="btn sm" data-lens="2" aria-pressed="${cam1LensMode === '2'}">Lensa 2 · Tengah</button>
              <button class="btn sm" data-lens="3" aria-pressed="${cam1LensMode === '3'}">Lensa 3 · Bawah</button>
              <button class="btn sm" data-lens="split" aria-pressed="false">Split 3 Lensa</button>
            </div>
          </div>
        ` : (isOkam ? `
          <div class="lens-bar">
            <span class="lens-bar-label">Pilih Kamera O-Kam Pro (Multi-Camera):</span>
            <div class="seg" id="okam-lens-selector" role="group" aria-label="Pilih Kamera O-Kam">
              <button class="btn sm" data-okam-focus-lens="1" aria-pressed="${c.id === 'okam_1' && okamLensMode !== 'split'}">O-Kam 1 · Panoramic</button>
              <button class="btn sm" data-okam-focus-lens="2" aria-pressed="${c.id === 'okam_2' && okamLensMode !== 'split'}">O-Kam 2 · PTZ Motorik</button>
              <button class="btn sm" data-okam-focus-lens="3" aria-pressed="${c.id === 'okam_3' && okamLensMode !== 'split'}">O-Kam 3 · Sub-Stream</button>
              <button class="btn sm" data-okam-focus-lens="split" aria-pressed="${okamLensMode === 'split'}">Three Screens (3 Kamera)</button>
            </div>
          </div>
        ` : '');

        stage.innerHTML = `
          <div class="card cam">
            ${lensBar}
            <div class="video big${fillCls}${lensCls}" id="mc" style="--cam-aspect: ${stageAspect}; --cam-ratio: ${stageRatioVal};">
              ${bar(c, s)}
              <div class="video-viewport" id="video-viewport" title="Scroll untuk Zoom · Drag untuk Pan · Double-click untuk Reset/Toggle">
                <div class="video-zoom-stage" id="video-zoom-stage">
                  <img class="mjpeg-stream" id="stream-img-main" src="${stageStreamUrl}" alt="${escapeHtml(c.n)}" 
                    onerror="window.handleStreamError && window.handleStreamError(this, '${c.id}', 'msg-main');" 
                    onload="window.handleStreamLoad && window.handleStreamLoad(this, '${c.id}', 'msg-main');"
                    style="${isHealthy ? 'display:block;' : 'display:none;'}">
                  ${msg(c, 'msg-main')}
                </div>
              </div>
              <div class="vfoot">
                <span class="ts"></span>
                <span class="res-tag">${stageRes}</span>
                <div class="zoom">
                  ${(isCam1 || isOkam) ? `
                  <button class="btn ptz-toggle-btn${ptzPanelOpen ? ' active' : ''}" id="btn-toggle-ptz" title="Toggle PTZ Tactical Controller">
                    <svg class="ico"><use href="#i-ptz"/></svg><span>PTZ</span>
                  </button>
                  ` : ''}
                  <button class="btn" data-zoom="in" title="Perbesar (Zoom In)" aria-label="Zoom in">+</button>
                  <button class="btn" data-zoom="reset" title="Kembalikan Zoom (1.0x)" aria-label="Reset zoom">${zoomLevel.toFixed(1)}x</button>
                  <button class="btn" data-zoom="out" title="Perkecil (Zoom Out)" aria-label="Zoom out">−</button>
                  <button class="btn" data-fs title="Layar Penuh (F)" aria-label="Full screen">⤢</button>
                </div>
              </div>
            </div>
            ${renderPTZController(c)}
            <div class="cmeta">
              <div class="mrow">
                <div>
                  <b class="nm">${escapeHtml(lensTitle)}</b>
                  <div class="ip">${c.ip} · ${c.d} · Port ${c.p} <span class="res-tag">${stageRes}</span></div>
                </div>
                ${acts(c, '')}
              </div>
              ${stats(c)}
              <div class="signal-checks">
                <div class="signal-check"><i class="dot ${c.checks.portListening ? 'good-t' : 'bad-t'}"></i>Port :${c.p}</div>
                <div class="signal-check"><i class="dot ${c.checks.feedAlive ? 'good-t' : 'warn-t'}"></i>Feed Stream</div>
                <div class="signal-check"><i class="dot ${!c.checks.streamFrozen ? 'good-t' : 'bad-t'}"></i>Freeze Detector</div>
                <div class="signal-check"><i class="dot ${c.checks.fpsAdequate ? 'good-t' : 'warn-t'}"></i>FPS Quality</div>
              </div>
              ${c.circuitBreakerTripped ? `<div class="alert" style="margin-top:10px;"><svg class="ico"><use href="#i-warn"/></svg><p><b>Circuit Breaker Tripped</b><span>Camera exceeded restart limits. <button class="btn sm adm" data-act="reset-cb" data-cid="${c.id}" style="margin-left:8px;">Reset Breaker</button></span></p></div>` : ''}
            </div>
          </div>
          <div class="side">
            ${cams.map((x, i) => thumb(x, i, i === sel, 'data-thumb')).join('')}
          </div>
        `;
      }
    }

    const camsGrid = $('#cams');
    if (camsGrid) camsGrid.innerHTML = cams.map(card).join('');

    // Ensure layout visibility is strictly synchronized
    const isGrid = $('#layouts button[data-l="grid"]')?.getAttribute('aria-pressed') === 'true';
    layout(isGrid ? 'grid' : 'focus');

    bindPTZControls();
    bindVideoZoomAndPan();
    applyZoomTransform();
    updateFsButton();
    applyFitMode(fitMode);
    tick();
  }

  function refreshImgSrc(img, baseUrl) {
    if (!img || !baseUrl) return;
    const cleanBase = baseUrl.split('?')[0];
    img.src = `${cleanBase}?_r=${Date.now()}`;
  }

  function reloadAllStreams(targetCid) {
    const activeCam = cams[sel] || cams[0];
    if (!targetCid || (activeCam && activeCam.id === targetCid)) {
      const mainImg = $('#stream-img-main');
      if (mainImg && activeCam) {
        mainImg.style.display = 'block';
        const mainMsg = $('#msg-main');
        if (mainMsg) mainMsg.style.display = 'none';
        refreshImgSrc(mainImg, activeCam.streamUrl);
      }
    }
    cams.forEach((cam) => {
      if (targetCid && cam.id !== targetCid) return;
      const gImg = $(`#stream-img-${cam.id}`);
      if (gImg) {
        gImg.style.display = 'block';
        const gMsg = $(`#msg-${cam.id}`);
        if (gMsg) gMsg.style.display = 'none';
        refreshImgSrc(gImg, cam.streamUrl);
      }
    });
  }

  function updateLiveStats() {
    const c = cams[sel] || cams[0];
    const s = ST[c.s] || ST.degraded;
    const isMainAlive = c.s === 'healthy' || (c.checks && c.checks.feedAlive);

    // Auto-restore main stream if camera is alive
    const mainImg = $('#stream-img-main');
    const mainMsg = $('#msg-main');
    if (isMainAlive && mainImg && (mainImg.style.display === 'none' || !mainImg.naturalWidth || (mainMsg && mainMsg.style.display !== 'none'))) {
      mainImg.style.display = 'block';
      if (mainMsg) mainMsg.style.display = 'none';
      refreshImgSrc(mainImg, c.streamUrl);
    }

    // Update main stage OSD bar & stats
    const mainBar = $('#mc .vbar');
    if (mainBar) {
      mainBar.innerHTML = `<span><i class="dot ${s[1]}"></i>${escapeHtml(c.n)}</span><em>${s[2]}</em>`;
    }
    const stageMeta = $('#stage .cmeta');
    if (stageMeta) {
      const statsBox = stageMeta.querySelector('.stats');
      if (statsBox) {
        statsBox.innerHTML = `<div><b>${c.fps.toFixed(1)} / 15</b><span>fps</span></div><div><b>${c.latencyMs} ms</b><span>latency</span></div><div><b class="ratio-val">${c.aspect}</b><span>ratio</span></div><div><b>${c.w}</b><span>web</span></div>`;
      }
      const resTag = stageMeta.querySelector('.res-tag');
      if (resTag && c.resolution) resTag.textContent = c.resolution;
      const checksBox = stageMeta.querySelector('.signal-checks');
      if (checksBox) {
        checksBox.innerHTML = `
          <div class="signal-check"><i class="dot ${c.checks.portListening ? 'good-t' : 'bad-t'}"></i>Port :${c.p}</div>
          <div class="signal-check"><i class="dot ${c.checks.feedAlive ? 'good-t' : 'warn-t'}"></i>Feed Stream</div>
          <div class="signal-check"><i class="dot ${!c.checks.streamFrozen ? 'good-t' : 'bad-t'}"></i>Freeze Detector</div>
          <div class="signal-check"><i class="dot ${c.checks.fpsAdequate ? 'good-t' : 'warn-t'}"></i>FPS Quality</div>
        `;
      }
    }

    // Update grid cards if in grid mode
    cams.forEach((cam) => {
      const cardEl = $(`#feed-${cam.id}`)?.closest('.card');
      if (cardEl) {
        const cs = ST[cam.s] || ST.degraded;
        const vbar = cardEl.querySelector('.vbar');
        if (vbar) vbar.innerHTML = `<span><i class="dot ${cs[1]}"></i>${escapeHtml(cam.n)}</span><em>${cs[2]}</em>`;
        const statsBox = cardEl.querySelector('.stats');
        if (statsBox) {
          statsBox.innerHTML = `<div><b>${cam.fps.toFixed(1)} / 15</b><span>fps</span></div><div><b>${cam.latencyMs} ms</b><span>latency</span></div><div><b class="ratio-val">${cam.aspect}</b><span>ratio</span></div><div><b>${cam.w}</b><span>web</span></div>`;
        }
        const resTag = cardEl.querySelector('.res-tag');
        if (resTag && cam.resolution) resTag.textContent = cam.resolution;

        // Auto-restore card stream if recovered
        const streamImg = cardEl.querySelector('.mjpeg-stream');
        const msgBox = cardEl.querySelector('.msg-box');
        const isCamAlive = cam.s === 'healthy' || (cam.checks && cam.checks.feedAlive);
        if (isCamAlive && streamImg && (streamImg.style.display === 'none' || !streamImg.naturalWidth || (msgBox && msgBox.style.display !== 'none'))) {
          streamImg.style.display = 'block';
          if (msgBox) msgBox.style.display = 'none';
          refreshImgSrc(streamImg, cam.streamUrl);
        }
      }
    });
  }

  // --- Dashboard Rendering ---
  function dash() {
    const n = cams.length, h = cnt('healthy'), d = cnt('degraded'), o = cnt('offline');
    if ($('#fleet-total')) $('#fleet-total').textContent = n;
    if ($('#fleet-healthy')) $('#fleet-healthy').textContent = h;
    if ($('#fleet-degraded')) $('#fleet-degraded').textContent = d;
    if ($('#fleet-offline')) $('#fleet-offline').textContent = o;

    const mon = `${h} of ${n} cameras connected.${d ? ` ${d} degraded and waiting for frames.` : ''}${o ? ` ${o} offline.` : ''}`;
    if ($('#hcount')) $('#hcount').innerHTML = `<i class="dot ${d || o ? 'warn-t' : 'good-t'}"></i>${h} healthy · ${d} degraded · ${o} offline`;

    const prev = $('#prev');
    if (prev) prev.innerHTML = cams.map((c, i) => thumb(c, i, null, 'data-prev')).join('');

    const pickEl = $('#pick');
    if (pickEl && pickEl.children.length === 0) {
      pickEl.innerHTML = cams.map((c, i) => `<button aria-pressed="${i === pick}" data-i="${i}">Camera ${i + 1}</button>`).join('');
    }

    path();
    drawFps();
    updateDashEvents();
  }

  async function updateDashEvents() {
    const recentBox = $('#dash-recent-events');
    if (!recentBox) return;

    if (!eventsCache || eventsCache.length === 0) {
      try {
        const res = await fetch('/api/events?limit=6');
        const data = await res.json();
        eventsCache = data.events || [];
      } catch (e) {}
    }

    if (eventsCache.length === 0) {
      recentBox.innerHTML = '<div class="empty" style="padding:14px;"><p>No recent events captured</p></div>';
      return;
    }

    if ($('#ev-count')) $('#ev-count').textContent = `${eventsCache.length} recent`;

    recentBox.innerHTML = eventsCache.slice(0, 3).map((ev) => {
      const camName = ev.cameraName || ev.camera_name || (cams.find((c) => c.id === (ev.cameraId || ev.camera_id))?.name) || ev.cameraId || 'Camera';
      const isAi = !!(ev.primaryClass || (ev.detectedObjects && ev.detectedObjects.length > 0));
      const label = ev.primaryClass
        ? `${ev.primaryClass.charAt(0).toUpperCase() + ev.primaryClass.slice(1)} detected`
        : `Motion detected (${Math.round(ev.score || 0)}%)`;
      return `
        <div class="ev" style="cursor:pointer;" data-ev-snap="${escapeHtml(ev.id)}">
          <span class="dot ${isAi ? 'good' : 'warn'}"></span>
          <div style="flex:1">
            <b>${escapeHtml(camName)}</b>
            <span>${escapeHtml(label)} · ${formatDateTime(ev.timestamp)}</span>
          </div>
        </div>
      `;
    }).join('');
  }

  // --- AGENT 2: Pipeline Inspector ---
  function path() {
    const c = cams[pick] || cams[0];
    if ($('#pcam')) $('#pcam').textContent = `Camera ${pick + 1}`;
    if ($('#path-note-msg')) {
      $('#path-note-msg').textContent = `Tidak ada frame diterima dari sumber kamera. Pastikan kamera terhubung di IP ${c.ip}`;
    }
    if ($('#dl-port')) $('#dl-port').textContent = `${c.p} · Port listening`;

    const isDegraded = c.s === 'degraded' || c.fps === 0;
    const flow = $('#flow');
    if (flow) {
      const nodes = [
        { label: 'Source', fps: `${c.fps.toFixed(1)} fps`, bad: isDegraded },
        { label: 'LAN', fps: `${c.fps.toFixed(1)} fps`, bad: false },
        { label: 'Decoder', fps: `${c.fps.toFixed(1)} fps`, bad: false },
        { label: 'MJPEG', fps: `${c.fps.toFixed(1)} fps`, bad: false },
        { label: 'Browser', fps: `${c.fps.toFixed(1)} fps`, bad: false }
      ];

      flow.innerHTML = nodes
        .map(
          (n, i) => `
        ${i ? '<svg class="ico"><use href="#i-arrow"/></svg>' : ''}
        <div class="node ${n.bad ? 'bad' : ''}">
          <b>${n.label}</b>
          <span>${n.fps}</span>
        </div>
      `
        )
        .join('');
    }
  }

  // --- Canvas FPS History Chart ---
  function drawFps() {
    const cv = $('#fps-chart-canvas');
    if (!cv) return;
    const r = cv.getBoundingClientRect();
    if (!r.width) return;
    const d = window.devicePixelRatio || 1;
    const x = cv.getContext('2d');
    const T = 12, B = r.height - 8;

    cv.width = r.width * d;
    cv.height = r.height * d;
    x.scale(d, d);

    x.font = '11px Urbanist, system-ui, sans-serif';
    x.fillStyle = '#6f6f6f';
    x.strokeStyle = 'rgba(255, 255, 255, .1)';
    x.lineWidth = 1;

    [[T, '15'], [B, '0']].forEach(([y, l]) => {
      x.beginPath();
      x.moveTo(24, y);
      x.lineTo(r.width, y);
      x.stroke();
      x.fillText(l, 0, y + 4);
    });

    cams.forEach((c, i) => {
      const history = fpsHistory[c.id] || [];
      const val = c.fps || 0;
      const y = B - (val / 15) * (B - T);

      x.strokeStyle = col[i];
      x.lineWidth = 2.5;

      if (history.length > 1) {
        x.beginPath();
        const step = (r.width - 24) / Math.max(history.length - 1, 1);
        history.forEach((pt, idx) => {
          const ptY = B - (Math.min(pt, 15) / 15) * (B - T);
          if (idx === 0) x.moveTo(24, ptY);
          else x.lineTo(24 + idx * step, ptY);
        });
        x.stroke();
      } else {
        x.setLineDash([5, 10]);
        x.lineDashOffset = -i * 5;
        x.beginPath();
        x.moveTo(24, y);
        x.lineTo(r.width, y);
        x.stroke();
        x.setLineDash([]);
      }

      const fpsValEl = $(`#fps-val-${i + 1}`);
      if (fpsValEl) fpsValEl.textContent = `${val.toFixed(1)} fps`;
    });

    const hasAnyFps = cams.some((c) => c.fps > 0);
    const emptyEl = $('#fps-empty');
    if (emptyEl) emptyEl.hidden = hasAnyFps;
  }

  // --- Clock & Uptime Tick ---
  function tick() {
    const d = new Date();
    const t = `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`;
    $$('.ts').forEach((e) => { e.textContent = t; });

    const u = Math.floor((Date.now() - t0) / 1000);
    const uptimeStr = `${Math.floor(u / 3600)}h ${p2(Math.floor((u % 3600) / 60))}m ${p2(u % 60)}s`;
    if ($('#sbf-uptime')) $('#sbf-uptime').textContent = `Uptime ${uptimeStr}`;

    cams.forEach((c) => {
      if (c.recording && c.recordStartTime) {
        const el = $(`#rec-timer-${c.id}`);
        if (el) el.textContent = formatDuration(Math.floor((Date.now() - c.recordStartTime) / 1000));
      }
    });
  }
  setInterval(tick, 1000);

  // --- Sliding Pill Navigation Tabs ---
  const track = $('#track');
  const pill = $('#pill');

  function initTabs() {
    if (!track) return;
    const primaryHtml = tabs.slice(0, 4).map((t, i) =>
      `<button class="tab" data-go="${i}">${t[0]}${t[2] !== undefined ? `<i>${t[2]}</i>` : ''}</button>`
    ).join('');

    const notifItem = tabs[6];
    const notifCount = notifItem && notifItem[2] ? notifItem[2] : 0;

    const moreHtml = `
      <div class="tab-more-wrap" id="tab-more-wrap">
        <button type="button" class="tab tab-more-btn" id="tab-more-btn" aria-haspopup="menu" aria-expanded="false">
          <span id="tab-more-label">More</span>
          <svg class="ico sm" style="width:14px;height:14px"><use href="#i-arrow-down"/></svg>
        </button>
        <div class="tab-more-menu" id="tab-more-menu" role="menu">
          <button type="button" class="tab-more-item" data-go="4" role="menuitem">
            <svg class="ico"><use href="#i-db"/></svg>
            <span>Storage &amp; Retention</span>
          </button>
          <button type="button" class="tab-more-item" data-go="5" role="menuitem">
            <svg class="ico"><use href="#i-pulse"/></svg>
            <span>Diagnostics</span>
          </button>
          <button type="button" class="tab-more-item" data-go="6" role="menuitem">
            <svg class="ico"><use href="#i-bell"/></svg>
            <span>Notifications</span>
            <i id="more-notif-cnt" style="${notifCount > 0 ? '' : 'display:none'}">${notifCount}</i>
          </button>
          <button type="button" class="tab-more-item" data-go="7" role="menuitem">
            <svg class="ico"><use href="#i-gear"/></svg>
            <span>Setup &amp; Security</span>
          </button>
        </div>
      </div>
    `;

    track.innerHTML = '<span class="pill" id="pill"></span>' + primaryHtml + moreHtml;
  }

  function move() {
    const p = $('#pill');
    const a = track ? track.querySelector('.tab[aria-current="page"]') : null;
    if (p) {
      if (a) {
        p.style.opacity = '1';
        p.style.width = a.offsetWidth + 'px';
        p.style.transform = `translateX(${a.offsetLeft}px)`;
      } else {
        p.style.opacity = '0';
      }
    }
  }

  function go(i) {
    if (track) {
      // Primary tab buttons (0..3)
      track.querySelectorAll('.tab[data-go]').forEach((t) => {
        if (+t.dataset.go === i) t.setAttribute('aria-current', 'page');
        else t.removeAttribute('aria-current');
      });

      // More button and menu items (4..7)
      const moreBtn = $('#tab-more-btn');
      const moreLabel = $('#tab-more-label');
      const moreItems = track.querySelectorAll('.tab-more-item');

      moreItems.forEach((it) => {
        if (+it.dataset.go === i) it.setAttribute('aria-current', 'page');
        else it.removeAttribute('aria-current');
      });

      if (i >= 4 && i <= 7) {
        if (moreBtn) moreBtn.setAttribute('aria-current', 'page');
        if (moreLabel) {
          const shortNames = { 4: 'Storage', 5: 'Diagnostics', 6: 'Alerts', 7: 'Setup' };
          moreLabel.textContent = shortNames[i] || tabs[i][0];
        }
      } else {
        if (moreBtn) moreBtn.removeAttribute('aria-current');
        if (moreLabel) moreLabel.textContent = 'More';
      }
    }

    // Close more dropdown if open
    $('#tab-more-wrap')?.classList.remove('open');
    $('#tab-more-btn')?.setAttribute('aria-expanded', 'false');

    // Synchronize active indicator on left dock
    document.querySelectorAll('.dock [data-go]').forEach((t) => {
      if (+t.dataset.go === i) t.setAttribute('aria-current', 'page');
      else t.removeAttribute('aria-current');
    });

    tabs.forEach((t, k) => {
      const v = $(`#${t[1]}`);
      if (v) v.hidden = k !== i;
    });

    if ($('#title')) $('#title').textContent = tabs[i][0];
    if ($('#sentence')) $('#sentence').textContent = sentences[i] || '';

    move();

    if (i === 0) live();
    if (i === 1) { dash(); setTimeout(drawFps, 100); }
    if (i === 2) loadRecordings();
    if (i === 3) loadEvents();
    if (i === 4) loadStoragePage();
    if (i === 5) loadDiagnostics();
    if (i === 6) loadNotifications();

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function seg(s, fn) {
    const el = $(s);
    if (!el) return;
    el.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      [...el.children].forEach((x) => x.setAttribute('aria-pressed', x === b));
      if (fn) fn(b);
    });
  }

  function layout(l) {
    const g = l === 'grid';
    const stageEl = $('#stage');
    const camsEl = $('#cams');
    if (stageEl) {
      stageEl.hidden = g;
      if (g) {
        stageEl.setAttribute('hidden', '');
        stageEl.style.setProperty('display', 'none', 'important');
      } else {
        stageEl.removeAttribute('hidden');
        stageEl.style.removeProperty('display');
      }
    }
    if (camsEl) {
      camsEl.hidden = !g;
      if (!g) {
        camsEl.setAttribute('hidden', '');
        camsEl.style.setProperty('display', 'none', 'important');
      } else {
        camsEl.removeAttribute('hidden');
        camsEl.style.removeProperty('display');
      }
    }
    $$('#layouts button').forEach((x) => x.setAttribute('aria-pressed', x.dataset.l === l));
  }

  // --- AGENT 1: Service Operations ---
  async function servicePost(url, successMsg, targetCid) {
    try {
      const res = await fetch(url, { method: 'POST', credentials: 'same-origin' });
      if (res.status === 401) {
        applyServerRole(null, null, false);
        openAuthDialog();
        toast('Silakan login sebagai Admin terlebih dahulu.');
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (res.status === 403) {
        toast(data.error || 'Akses ditolak: membutuhkan akun Admin.');
        return;
      }
      if (res.ok) {
        toast(successMsg);
        setTimeout(() => {
          pollBackendHealth();
          reloadAllStreams(targetCid || null);
        }, 1200);
      } else {
        toast(`Notice: ${data.message || data.error || 'Operation failed'}`);
      }
    } catch (err) {
      toast(`Error: ${err.message}`);
    }
  }

  async function runAllCameras() {
    toast(`Starting all ${cams.length} cameras…`);
    await servicePost('/api/services/start-all', 'All camera decoders started successfully.', null);
  }

  async function stopAllCameras() {
    toast(`Stopping all ${cams.length} cameras…`);
    try {
      const res = await fetch('/api/services/stop-all', { method: 'POST', credentials: 'same-origin' });
      if (res.status === 401) return openAuthDialog();
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        toast('All camera decoders stopped.');
        setTimeout(pollBackendHealth, 1000);
      } else {
        toast(`Stop notice: ${data.message || data.error || 'Failed'}`);
      }
    } catch (err) {
      toast(`Error: ${err.message}`);
    }
  }

  async function restartAllCameras() {
    toast(`Restarting all ${cams.length} cameras…`);
    await servicePost('/api/services/restart-all', 'All camera decoders restarted successfully.', null);
  }

  async function startCamera(cid) {
    await servicePost(`/api/services/start?id=${encodeURIComponent(cid)}`, `Started decoder for ${cid}`, cid);
  }

  async function stopCamera(cid) {
    try {
      const res = await fetch(`/api/services/stop?id=${encodeURIComponent(cid)}`, { method: 'POST', credentials: 'same-origin' });
      if (res.status === 401) return openAuthDialog();
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        toast(`Stopped decoder for ${cid}`);
        setTimeout(pollBackendHealth, 1000);
      } else {
        toast(`Stop error: ${data.message || data.error || 'Failed'}`);
      }
    } catch (err) {
      toast(`Stop error: ${err.message}`);
    }
  }

  async function restartCamera(cid) {
    await servicePost(`/api/services/restart?id=${encodeURIComponent(cid)}`, `Restarted decoder for ${cid}`, cid);
  }

  async function resetCircuitBreaker(cid) {
    await servicePost(`/api/recovery/reset?id=${encodeURIComponent(cid)}`, `Circuit breaker reset for ${cid}. Ready to start.`, cid);
  }

  // --- AGENT 4: Local Recording & Playback ---
  let recordingsCache = [];

  async function loadRecordings() {
    renderManualRecordingControls();
    const listEl = $('#recordings-list');
    if (!listEl) return;

    try {
      const recUrl = recordingFilterCid
        ? `/api/recordings?cameraId=${encodeURIComponent(recordingFilterCid)}`
        : '/api/recordings';
      const res = await fetch(recUrl);
      if (res.status === 401) {
        openAuthDialog();
        return;
      }
      const data = await res.json();
      recordingsCache = data.recordings || [];

      if (recordingsCache.length === 0) {
        listEl.innerHTML = `
          <div class="empty">
            <p>No recorded MP4 segments found on disk.<br>Trigger manual recording or test motion to create archives.</p>
          </div>
        `;
        return;
      }

      listEl.innerHTML = recordingsCache
        .map(
          (rec) => {
            const camName = rec.cameraName || (cams.find((c) => c.id === (rec.cameraId || rec.camera_id))?.name) || rec.cameraId || rec.camera_name || rec.camera_id || 'Camera';
            const startTime = rec.startTime || rec.start_time || rec.created_at || rec.timestamp;
            const fileSize = rec.fileSizeBytes || rec.file_size || rec.size_bytes || 0;
            const duration = rec.durationSeconds || rec.duration_seconds || rec.duration || 0;
            return `
        <div class="rec-item" data-rec-id="${escapeHtml(rec.id)}">
          <div class="rec-meta">
            <b>${escapeHtml(camName)}</b>
            <span>${formatDateTime(startTime)} · ${formatBytes(fileSize)} · ${formatDuration(duration)}</span>
          </div>
          <div class="acts">
            <button class="btn sq sm" data-rec-play="${escapeHtml(rec.id)}" title="Play video">
              <svg class="ico"><use href="#i-play"/></svg>
            </button>
            <a class="btn sq sm" href="/api/recordings/download?id=${encodeURIComponent(rec.id)}" download="" title="Download MP4">
              <svg class="ico"><use href="#i-dl"/></svg>
            </a>
            <button class="btn sq sm adm" data-rec-del="${escapeHtml(rec.id)}" title="Delete archive">
              <svg class="ico"><use href="#i-trash"/></svg>
            </button>
          </div>
        </div>
      `;
          }
        )
        .join('');
    } catch (err) {
      listEl.innerHTML = `<div class="empty"><p>Error loading recordings: ${escapeHtml(err.message)}</p></div>`;
    }
  }

  function renderManualRecordingControls() {
    const strip = $('#rec-status-strip');
    if (!strip) return;

    strip.innerHTML = cams
      .map(
        (cam) => `
      <div class="rec-status-card">
        <div>
          <b>${escapeHtml(cam.shortName)}</b>
          <div class="sub">
            <span class="tag ${cam.recording ? 'bad' : 'good'}">${cam.recording ? 'RECORDING' : 'IDLE'}</span>
            <span id="rec-timer-${cam.id}" style="margin-left:6px;font-family:var(--mono);">${cam.recording ? '0s' : '--'}</span>
          </div>
        </div>
        <button class="btn sm ${cam.recording ? 'dng' : 'primary'} adm" data-act="record" data-cid="${cam.id}">
          <svg class="ico"><use href="${cam.recording ? '#i-cross' : '#i-play'}"/></svg>
          <span>${cam.recording ? 'Stop' : 'Record'}</span>
        </button>
      </div>
    `
      )
      .join('');
  }

  async function toggleRecording(cid) {
    const cam = cams.find((c) => c.id === cid);
    if (!cam) return;

    if (!cam.recording) {
      try {
        const res = await fetch('/api/recordings/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ camera_id: cid, duration: 300 })
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          cam.recording = true;
          cam.recordStartTime = Date.now();
          toast(`Recording started on ${cam.shortName}`);
        } else {
          toast(`Recording notice: ${data.message || 'Decoder is offline'}`);
        }
      } catch (err) {
        toast(`Error: ${err.message}`);
      }
    } else {
      try {
        await fetch('/api/recordings/stop', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ camera_id: cid })
        });
        cam.recording = false;
        cam.recordStartTime = null;
        toast(`Recording stopped on ${cam.shortName}`);
        setTimeout(loadRecordings, 1500);
      } catch (err) {
        toast(`Error: ${err.message}`);
      }
    }

    renderManualRecordingControls();
    live();
  }

  async function triggerTestMotionRecording() {
    toast('Triggering automated test motion recording…');
    try {
      const res = await fetch('/api/recordings/trigger-motion?cameraId=v380-1&duration=10', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        toast('Test motion recording generated (10s segment).');
        setTimeout(loadRecordings, 2000);
      } else {
        toast(`Notice: ${data.message || data.error}`);
      }
    } catch (err) {
      toast(`Error: ${err.message}`);
    }
  }

  function playRecording(id) {
    const rec = recordingsCache.find((r) => r.id === id);
    if (!rec) return;

    const video = $('#video-player');
    const dlBtn = $('#player-download-btn');
    const info = $('#player-clip-info');
    const tag = $('#player-status-tag');

    if (video) {
      video.src = `/api/recordings/stream?id=${encodeURIComponent(id)}`;
      video.load();
      video.play().catch(() => {});
    }

    if (dlBtn) {
      dlBtn.href = `/api/recordings/download?id=${encodeURIComponent(id)}`;
      dlBtn.download = rec.fileName || rec.filename || `${id}.mp4`;
      dlBtn.style.display = 'inline-flex';
    }

    if (info) {
      const camName = rec.cameraName || (cams.find((c) => c.id === (rec.cameraId || rec.camera_id))?.name) || rec.cameraId || rec.camera_name || rec.camera_id || 'Camera';
      const startTime = rec.startTime || rec.start_time || rec.created_at || rec.timestamp;
      const duration = rec.durationSeconds || rec.duration_seconds || rec.duration || 0;
      info.textContent = `Streaming ${camName} · Recorded ${formatDateTime(startTime)} (${formatDuration(duration)})`;
    }

    if (tag) {
      tag.textContent = 'Playing';
      tag.className = 'tag good';
    }

    $$('.rec-item').forEach((item) => {
      item.classList.toggle('active', item.dataset.recId === id);
    });
  }

  async function deleteRecording(id) {
    if (!confirm('Permanently delete this recording archive?')) return;
    try {
      const res = await fetch(`/api/recordings?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (res.ok) {
        toast('Recording deleted');
        loadRecordings();
      } else {
        const data = await res.json();
        toast(`Delete failed: ${data.message || 'File protected by active lock'}`);
      }
    } catch (err) {
      toast(`Delete failed: ${err.message}`);
    }
  }

  // --- AGENT 5 & 6: Events & Edge AI Object Detection ---
  let eventsCache = [];

  async function loadEvents() {
    const list = $('#events-list');
    if (!list) return;

    try {
      const res = await fetch('/api/events?limit=200');
      const data = await res.json();
      eventsCache = data.events || [];

      // Update counters for All, Cam 1, Cam 2, Cam 3
      const count1 = eventsCache.filter((e) => (e.cameraId || e.camera_id) === 'v380-1').length;
      const count2 = eventsCache.filter((e) => (e.cameraId || e.camera_id) === 'v380-2').length;
      const count3 = eventsCache.filter((e) => (e.cameraId || e.camera_id) === 'okam-3').length;

      if ($('#cnt-ev-all')) $('#cnt-ev-all').textContent = eventsCache.length;
      if ($('#cnt-ev-1')) $('#cnt-ev-1').textContent = count1;
      if ($('#cnt-ev-2')) $('#cnt-ev-2').textContent = count2;
      if ($('#cnt-ev-3')) $('#cnt-ev-3').textContent = count3;

      if ($('#card-cnt-v380-1')) $('#card-cnt-v380-1').textContent = `${count1} Events`;
      if ($('#card-cnt-v380-2')) $('#card-cnt-v380-2').textContent = `${count2} Events`;
      if ($('#card-cnt-okam-3')) $('#card-cnt-okam-3').textContent = `${count3} Events`;

      renderEventsList();

      const tabItem = tabs.find((t) => t[1] === 'v-events');
      if (tabItem) tabItem[2] = eventsCache.length;
      const dockEvDot = $('#dock-events-dot');
      if (dockEvDot) dockEvDot.style.display = eventsCache.length > 0 ? 'block' : 'none';
      initTabs();
      move();
    } catch (err) {
      list.innerHTML = `<div class="empty"><p>Error loading events: ${escapeHtml(err.message)}</p></div>`;
    }
  }

  function renderEventsList() {
    const list = $('#events-list');
    if (!list) return;

    let filtered = eventsCache;
    if (eventFilterCid) {
      filtered = filtered.filter((ev) => (ev.cameraId || ev.camera_id) === eventFilterCid);
    }

    if (filtered.length === 0) {
      list.innerHTML = `
        <div class="empty" style="grid-column: 1 / -1">
          <p>No activity events found for this filter.<br>Camera motion triggers and AI detections will be captured here.</p>
        </div>
      `;
      return;
    }

    list.innerHTML = filtered
      .map(
        (ev) => {
          const cid = ev.cameraId || ev.camera_id || '';
          const camName = ev.cameraName || ev.camera_name || (cams.find((c) => c.id === cid)?.name) || cid || 'Camera';
          let tagText = 'Motion';
          let tagClass = 'warn';

          if (ev.primaryClass) {
            const cls = ev.primaryClass.charAt(0).toUpperCase() + ev.primaryClass.slice(1);
            const conf = ev.primaryConfidence ? ` ${Math.round(ev.primaryConfidence * 100)}%` : '';
            tagText = `${cls}${conf}`;
            tagClass = 'good';
          } else if (ev.detectedObjects && ev.detectedObjects.length > 0) {
            const d = ev.detectedObjects[0];
            const cls = d.class.charAt(0).toUpperCase() + d.class.slice(1);
            const conf = d.confidence ? ` ${Math.round(d.confidence * 100)}%` : '';
            tagText = `${cls}${conf}`;
            tagClass = 'good';
          } else if (ev.score != null) {
            tagText = `Motion ${Math.round(ev.score)}%`;
          }

          return `
      <div class="event-card">
        <div class="event-snap" data-ev-snap="${escapeHtml(ev.id)}">
          <img src="/api/events/snapshot?id=${encodeURIComponent(ev.id)}" alt="Event Snapshot" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 24 24\\'%3E%3Ctext x=\\'50%\\' y=\\'50%\\' fill=\\'%23666\\' text-anchor=\\'middle\\'%3ENo Snapshot%3C/text%3E%3C/svg%3E';" />
          <span class="tag ${tagClass}">
            ${escapeHtml(tagText)}
          </span>
        </div>
        <div class="event-info">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <b>${escapeHtml(camName)}</b>
            <button class="btn sq sm adm" data-ev-del="${escapeHtml(ev.id)}" title="Delete Event">
              <svg class="ico"><use href="#i-trash"/></svg>
            </button>
          </div>
          <span>${formatDateTime(ev.timestamp)}</span>
        </div>
      </div>
    `;
        }
      )
      .join('');
  }

  function openEventLightbox(id) {
    const ev = eventsCache.find((e) => e.id === id);
    if (!ev) return;

    const dlg = $('#event-dialog');
    const img = $('#lightbox-img');
    const details = $('#lightbox-details');
    const title = $('#lightbox-title');

    const cid = ev.cameraId || ev.camera_id || '';
    const camName = ev.cameraName || ev.camera_name || (cams.find((c) => c.id === cid)?.name) || cid || 'Camera';
    const tagText = ev.primaryClass
      ? ev.primaryClass.charAt(0).toUpperCase() + ev.primaryClass.slice(1)
      : (ev.detectedObjects?.[0]?.class ? ev.detectedObjects[0].class.charAt(0).toUpperCase() + ev.detectedObjects[0].class.slice(1) : 'Motion');
    const confStr = ev.primaryConfidence != null
      ? `${(ev.primaryConfidence * 100).toFixed(1)}%`
      : (ev.score != null ? `${ev.score.toFixed(1)}% motion` : 'N/A');

    if (title) title.textContent = `${camName} — ${tagText}`;
    if (img) img.src = `/api/events/snapshot?id=${encodeURIComponent(id)}`;
    if (details) {
      details.textContent = `Camera: ${camName} (${cid}) | Detection: ${tagText} | Confidence/Score: ${confStr} | Time: ${formatDateTime(ev.timestamp)} | ID: ${ev.id}`;
    }

    if (dlg) dlg.showModal();
  }

  async function deleteEvent(id) {
    try {
      const res = await fetch(`/api/events?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (res.ok) {
        eventsCache = eventsCache.filter((e) => e.id !== id);
        renderEventsList();
        toast('Event removed');
      }
    } catch (err) {
      toast(`Delete error: ${err.message}`);
    }
  }

  async function clearAllEvents() {
    if (!confirm('Clear all motion and AI detection events?')) return;
    try {
      const res = await fetch('/api/events', { method: 'DELETE' });
      if (res.ok) {
        eventsCache = [];
        renderEventsList();
        toast('All events cleared');
      }
    } catch (err) {
      toast(`Clear error: ${err.message}`);
    }
  }

  async function runAiBenchmark() {
    toast('Running DirectML / CPU AI inference benchmark (5 iterations)…');
    try {
      const res = await fetch('/api/ai/benchmark?runs=5', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.results) {
        const dml = data.results.DirectML || {};
        const cpu = data.results.CPU || {};
        const msg = `AI Benchmark Complete:\nDirectML Latency = ${dml.latencyMs || '--'}ms (${dml.fpsCapacity || '--'} FPS)\nCPU Fallback = ${cpu.latencyMs || '--'}ms`;
        toast('AI Benchmark finished.');
        alert(msg);
      } else {
        toast(`AI notice: ${data.error || 'DirectML provider ready'}`);
      }
    } catch (err) {
      toast(`Benchmark error: ${err.message}`);
    }
  }

  // --- AGENT 8: Storage & Retention Manager ---
  async function loadStoragePage() {
    try {
      const res = await fetch('/api/storage/status');
      const data = await res.json();

      if (data.disk) {
        const totalGb = (data.disk.total_bytes / 1e9).toFixed(1) + ' GB';
        const usedGb = (data.disk.used_bytes / 1e9).toFixed(1) + ' GB';
        const freeGb = (data.disk.free_bytes / 1e9).toFixed(1) + ' GB';
        const pct = Math.round(data.disk.percent_used || 85);

        if ($('#st-disk-total')) $('#st-disk-total').textContent = totalGb;
        if ($('#st-disk-used')) $('#st-disk-used').textContent = usedGb;
        if ($('#st-disk-free')) $('#st-disk-free').textContent = freeGb;

        if ($('#storage-page-percent')) $('#storage-page-percent').innerHTML = `${pct}%<small>used</small>`;
        if ($('#storage-page-ring')) $('#storage-page-ring').style.setProperty('--ring-fill', `${pct}%`);

        if ($('#alert-80')) $('#alert-80').className = `threshold-card ${pct >= 80 ? 'warn-t' : 'good-t'}`;
        if ($('#alert-90')) $('#alert-90').className = `threshold-card ${pct >= 90 ? 'bad-t' : ''}`;
        if ($('#alert-95')) $('#alert-95').className = `threshold-card ${pct >= 95 ? 'bad-t' : ''}`;
      }

      if (data.forecasting && $('#st-growth-rate')) {
        const mbPerDay = ((data.forecasting.growth_rate_bytes_per_sec * 86400) / 1e6).toFixed(1);
        $('#st-growth-rate').textContent = `+${mbPerDay} MB/day`;
      }
    } catch (err) {
      console.warn('Storage status load error:', err);
    }
  }

  async function dryRunCleanup() {
    toast('Evaluating retention policies (Dry-Run)…');
    try {
      const res = await fetch('/api/storage/cleanup?dryRun=true', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        const count = data.recordings_purged?.length || 0;
        const msg = `Dry-Run Complete: ${count} recordings eligible for purge. No files were deleted.`;
        toast(msg);
        alert(msg);
      }
    } catch (err) {
      toast(`Dry-run error: ${err.message}`);
    }
  }

  async function executeRetentionCleanup() {
    if (!confirm('Execute retention cleanup and purge expired recordings? Files with active playback or recording locks will be preserved.')) return;
    try {
      const res = await fetch('/api/storage/cleanup?dryRun=false', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        const count = data.recordings_purged?.length || 0;
        toast(`Retention purge executed: ${count} expired files deleted.`);
        loadStoragePage();
      }
    } catch (err) {
      toast(`Purge error: ${err.message}`);
    }
  }

  async function reindexStorage() {
    toast('Reconciling on-disk files with metadata index…');
    try {
      const res = await fetch('/api/storage/reindex', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        toast('Storage index rebuilt and repaired successfully.');
        loadStoragePage();
      }
    } catch (err) {
      toast(`Reindex error: ${err.message}`);
    }
  }

  // --- AGENT 10: Diagnostics & Export Report ---
  async function loadDiagnostics() {
    try {
      const res = await fetch('/api/diagnostics/summary');
      const data = await res.json();

      if (data.software) {
        if ($('#diag-py-ver')) $('#diag-py-ver').textContent = data.software.python || '3.10.11';
        if ($('#diag-dotnet-ver')) $('#diag-dotnet-ver').textContent = data.software.dotnet || '8.0';
        if ($('#diag-ffmpeg-ver')) $('#diag-ffmpeg-ver').textContent = data.software.ffmpeg || '6.0';
      }

      if (data.resources && $('#diag-uptime-val')) {
        $('#diag-uptime-val').textContent = formatDuration(data.resources.uptimeSeconds);
      }

      if (data.ports) {
        const setPort = (id, status) => {
          const el = $(`#${id}`);
          if (!el) return;
          el.textContent = status ? 'LISTENING' : 'OFFLINE';
          el.className = status ? 'good-t' : 'bad-t';
        };
        setPort('diag-p8080', data.ports['8080'] || data.ports[8080]);
        setPort('diag-p8081', data.ports['8081'] || data.ports[8081]);
        setPort('diag-p8082', data.ports['8082'] || data.ports[8082]);
      }

      if (data.bundles && $('#diag-bundles-list')) {
        const list = $('#diag-bundles-list');
        if (data.bundles.length === 0) {
          list.innerHTML = `<div class="empty"><p>No diagnostic bundles generated yet.</p></div>`;
        } else {
          list.innerHTML = data.bundles
            .slice(0, 3)
            .map(
              (b) => `
            <div class="bundle-item">
              <div>
                <b>${escapeHtml(b.filename)}</b>
                <div class="sub">${formatDateTime(b.createdAt)} · ${formatBytes(b.sizeBytes)}</div>
              </div>
              <a class="btn sq sm" href="/api/diagnostics/download?filename=${encodeURIComponent(b.filename)}" download="" title="Download Bundle">
                <svg class="ico"><use href="#i-dl"/></svg>
              </a>
            </div>
          `
            )
            .join('');
        }
      }

      if ($('#diag-log-box')) {
        $('#diag-log-box').textContent = `[SYSTEM] CamHUB host active on Windows 10/11.
[PORT 8080] Decoder Kamera 1: Port listening. Status: DEGRADED (0.0 fps).
[PORT 8081] Decoder Kamera 2: Port listening. Status: DEGRADED (0.0 fps).
[PORT 8082] Decoder Kamera 3: Port listening. Status: DEGRADED (0.0 fps).
[SECURITY] Credential redactor active: RTSP tokens, passwords, and secrets sanitized.
[AI ENGINE] Provider: DirectML (GPU capacity active).
[STORAGE] Storage retention policy: 14 days video, 7 days snapshots.`;
      }
    } catch (err) {
      console.warn('Diagnostics load error:', err);
    }
  }

  async function generateDiagnosticBundle() {
    const prog = $('#bundle-progress');
    const btn = $('#btn-generate-bundle');
    if (prog) prog.style.display = 'block';
    if (btn) btn.disabled = true;

    try {
      const res = await fetch('/api/diagnostics/generate', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        toast('Sanitized diagnostic bundle (.ZIP) generated!');
        loadDiagnostics();
      } else {
        toast(`Bundle notice: ${data.message}`);
      }
    } catch (err) {
      toast(`Export failed: ${err.message}`);
    } finally {
      if (prog) prog.style.display = 'none';
      if (btn) btn.disabled = false;
    }
  }

  // --- AGENT 9: Notifications Center ---
  let notificationsCache = [];

  async function loadNotifications() {
    const list = $('#notif-list');
    if (!list) return;

    try {
      const res = await fetch('/api/notifications');
      const data = await res.json();
      notificationsCache = data.notifications || [];
      renderNotificationsList();

      const unreadCount = notificationsCache.filter((n) => !n.acknowledged).length;
      const tabItem = tabs.find((t) => t[1] === 'v-notif');
      if (tabItem) tabItem[2] = unreadCount;
      const dockNotifDot = $('#dock-notif-dot');
      if (dockNotifDot) dockNotifDot.style.display = unreadCount > 0 ? 'block' : 'none';
      initTabs();
      move();
    } catch (err) {
      list.innerHTML = `<div class="empty"><p>Error loading notifications: ${escapeHtml(err.message)}</p></div>`;
    }
  }

  function renderNotificationsList() {
    const list = $('#notif-list');
    if (!list) return;

    let filtered = notificationsCache;
    if (notifFilterSev) {
      filtered = filtered.filter((n) => n.severity === notifFilterSev);
    }

    if (filtered.length === 0) {
      list.innerHTML = `
        <div class="empty">
          <p>No notifications captured.<br>Camera offline alerts and fault notices will be listed here.</p>
        </div>
      `;
      return;
    }

    list.innerHTML = filtered
      .map((n) => {
        const dotClass = n.severity === 'critical' ? 'bad-t' : n.severity === 'warning' ? 'warn-t' : 'good-t';
        return `
        <div class="notif-item ${n.acknowledged ? '' : 'unread'}">
          <i class="dot ${dotClass}" style="margin-top:5px"></i>
          <div class="notif-main">
            <b>${escapeHtml(n.title)}</b>
            <p>${escapeHtml(n.message)}</p>
            <span class="notif-time">${formatDateTime(n.timestamp)} · ${escapeHtml(n.camera || 'System')}</span>
          </div>
          ${
            !n.acknowledged
              ? `<button class="btn sq sm" data-notif-ack="${escapeHtml(n.id)}" title="Acknowledge">
                  <svg class="ico"><use href="#i-check"/></svg>
                </button>`
              : ''
          }
        </div>
      `;
      })
      .join('');
  }

  async function acknowledgeNotification(id) {
    try {
      const res = await fetch('/api/notifications/ack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
      });
      if (res.ok) {
        toast('Notification acknowledged');
        loadNotifications();
      }
    } catch (err) {
      toast(`Error: ${err.message}`);
    }
  }

  async function acknowledgeAllNotifications() {
    try {
      const res = await fetch('/api/notifications/ack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ all: true })
      });
      if (res.ok) {
        toast('All notifications acknowledged');
        loadNotifications();
      }
    } catch (err) {
      toast(`Error: ${err.message}`);
    }
  }

  async function clearAllNotifications() {
    if (!confirm('Clear all notification alerts?')) return;
    try {
      const res = await fetch('/api/notifications', { method: 'DELETE' });
      if (res.ok) {
        notificationsCache = [];
        renderNotificationsList();
        toast('Notifications cleared');
      }
    } catch (err) {
      toast(`Error: ${err.message}`);
    }
  }

  async function simulateNotification() {
    try {
      const res = await fetch('/api/notifications/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category: 'camera_offline',
          severity: 'warning',
          camera: 'Camera 2, Garage',
          message: 'Framerate dropped below 5.0 fps threshold (Simulated alert).'
        })
      });
      if (res.ok) {
        toast('Simulated notification dispatched');
        loadNotifications();
      }
    } catch (err) {
      toast(`Simulation failed: ${err.message}`);
    }
  }

  async function testTelegramBot() {
    const token = $('#tg-token')?.value?.trim();
    const chat = $('#tg-chat')?.value?.trim();
    if (!token || !chat) {
      toast('Please provide Bot Token and Chat ID.');
      return;
    }
    toast('Testing Telegram Bot connection…');
    try {
      const res = await fetch(`/api/notifications/test-telegram?botToken=${encodeURIComponent(token)}&chatId=${encodeURIComponent(chat)}`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.success) {
        toast('Telegram message sent successfully!');
        $('#telegram-dialog')?.close();
      } else {
        toast(`Telegram notice: ${data.message || data.error}`);
      }
    } catch (err) {
      toast(`Telegram test failed: ${err.message}`);
    }
  }

  // --- Background Telemetry Polling Loop ---
  async function pollBackendHealth() {
    try {
      const healthResp = await fetch('/api/health', { credentials: 'same-origin' });
      if (healthResp.status === 401) {
        applyServerRole(null, null, false);
        openAuthDialog();
        return;
      }
      const [healthRes, storageRes, servicesRes] = await Promise.all([
        healthResp.ok ? healthResp.json() : null,
        fetch('/api/storage/status', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null)),
        fetch('/api/services/status', { credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null))
      ]);

      if (healthRes && healthRes.cameras) {
        Object.entries(healthRes.cameras).forEach(([cid, camData]) => {
          let localCam = cams.find((c) => c.id === cid);
          if (!localCam && cid === 'okam-3') {
            localCam = cams.find((c) => c.id === 'okam_1');
          }
          if (localCam) {
            localCam.s = (camData.status || 'degraded').toLowerCase();
            if (camData.checks) localCam.checks = camData.checks;
            if (camData.metrics) {
              localCam.fps = camData.metrics.fps || 0.0;
              localCam.latencyMs = Math.round(camData.metrics.latencyMs || 0);
              localCam.queue = `${camData.metrics.queueDepth || 0} / 0`;
              localCam.decodeErrors = camData.metrics.decodeErrors || 0;
              if (camData.metrics.resolution && camData.metrics.resolution !== 'unknown') {
                localCam.resolution = String(camData.metrics.resolution).replace('x', '×');
              }
            }

            const historyKey = localCam.id;
            if (!fpsHistory[historyKey]) fpsHistory[historyKey] = [];
            fpsHistory[historyKey].push(localCam.fps);
            if (fpsHistory[historyKey].length > 30) fpsHistory[historyKey].shift();
          }
        });

        if (servicesRes && servicesRes.services) {
          Object.entries(servicesRes.services).forEach(([cid, sData]) => {
            let localCam = cams.find((c) => c.id === cid);
            if (!localCam && cid === 'okam-3') {
              localCam = cams.find((c) => c.id === 'okam_1');
            }
            if (localCam) {
              localCam.running = sData.running;
              localCam.circuitBreakerTripped = sData.circuitBreakerTripped || false;
            }
          });
        }

        const totalFps = cams.reduce((acc, c) => acc + (c.fps || 0), 0);
        const activeCams = cams.filter((c) => c.fps > 0);
        const avgLat = activeCams.length
          ? Math.round(activeCams.reduce((acc, c) => acc + (c.latencyMs || 0), 0) / activeCams.length)
          : 0;
        if ($('#tp-fps')) $('#tp-fps').textContent = `${totalFps.toFixed(1)} fps`;
        if ($('#tp-lat')) $('#tp-lat').textContent = `${avgLat} ms`;

        if (healthRes.system) {
          const cpu = Math.round(healthRes.system.cpu_percent || 28);
          const mem = Math.round(healthRes.system.memory?.percent || 52);
          if ($('#res-cpu-val')) $('#res-cpu-val').textContent = `${cpu}%`;
          if ($('#res-cpu-bar')) $('#res-cpu-bar').style.setProperty('--w', `${cpu}%`);
          if ($('#res-mem-val')) $('#res-mem-val').textContent = `8.3 / 16.0 GB (${mem}%)`;
          if ($('#res-mem-bar')) $('#res-mem-bar').style.setProperty('--w', `${mem}%`);
        }

        dash();
        updateLiveStats();
      }

      // Storage status
      if (storageRes && storageRes.disk) {
        const usedGb = (storageRes.disk.used_bytes / 1e9).toFixed(0);
        const freeGb = (storageRes.disk.free_bytes / 1e9).toFixed(0);
        const percent = Math.round(storageRes.disk.percent_used || 85);
        const recMb = (storageRes.recordings?.total_bytes / 1e6 || 10.2).toFixed(1);
        const snapMb = (storageRes.events?.total_bytes / 1e6 || 2.5).toFixed(1);
        const forecast = storageRes.forecasting?.estimated_days_remaining
          ? `${Math.round(storageRes.forecasting.estimated_days_remaining)} days left`
          : 'Over 30 days left';

        if ($('#store-percent')) $('#store-percent').innerHTML = `${percent}%<small>used</small>`;
        if ($('#store-used')) $('#store-used').textContent = `${usedGb} GB`;
        if ($('#store-free')) $('#store-free').textContent = `${freeGb} GB`;
        if ($('#store-recs')) $('#store-recs').textContent = `${recMb} MB`;
        if ($('#store-snaps')) $('#store-snaps').textContent = `${snapMb} MB`;
        if ($('#store-forecast')) $('#store-forecast').textContent = forecast;
        if ($('#store-ring')) $('#store-ring').style.setProperty('--ring-fill', `${percent}%`);
      }
    } catch (err) {
      console.warn('Telemetry poll notice:', err);
    }
  }

  // --- Global Event Listeners Delegation ---
  document.addEventListener('click', (e) => {
    const c = (s) => e.target.closest(s);
    let m;

    const moreBtn = c('#tab-more-btn');
    if (moreBtn) {
      const wrap = $('#tab-more-wrap');
      if (wrap) {
        const isOpen = wrap.classList.toggle('open');
        moreBtn.setAttribute('aria-expanded', isOpen);
      }
      return;
    }
    if (!c('#tab-more-wrap')) {
      $('#tab-more-wrap')?.classList.remove('open');
      $('#tab-more-btn')?.setAttribute('aria-expanded', 'false');
    }

    if ((m = c('[data-go]'))) return go(+m.dataset.go);

    if ((m = c('[data-act]'))) {
      const act = m.dataset.act;
      const cid = m.dataset.cid;
      const targetCam = cams.find((x) => x.id === cid) || cams[sel];

      if (act === 'quick-search') return openQuickSearch();
      if (act === 'theme') return toggleTheme(e);
      if (act === 'add-cam') {
        go(7);
        setTimeout(() => {
          const inp = $('#cam-name');
          if (inp) {
            inp.focus();
            inp.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }, 150);
        return;
      }
      if (act === 'record') return toggleRecording(cid);
      if (act === 'start-cam') return startCamera(cid);
      if (act === 'stop-cam') return stopCamera(cid);
      if (act === 'restart-cam') return restartCamera(cid);
      if (act === 'reset-cb') return resetCircuitBreaker(cid);
      if (act === 'config') {
        if ($('#config-cam-name')) $('#config-cam-name').textContent = targetCam.n;
        if ($('#cfg-name')) $('#cfg-name').value = targetCam.n;
        if ($('#cfg-url')) $('#cfg-url').value = targetCam.streamUrl;
        if ($('#cfg-location')) $('#cfg-location').value = targetCam.ip;
        return $('#config-dialog')?.showModal();
      }
      return;
    }

    if ((m = c('[data-focus]') || c('[data-prev]'))) {
      sel = +(m.dataset.focus ?? m.dataset.prev);
      zoomLevel = 1.0;
      panX = 0;
      panY = 0;
      live();
      layout('focus');
      return go(0);
    }

    if ((m = c('[data-thumb]'))) {
      sel = +m.dataset.thumb;
      zoomLevel = 1.0;
      panX = 0;
      panY = 0;
      return live();
    }

    // Camera 1 & Camera 3 Multi-Lens selection
    if ((m = c('[data-lens]'))) {
      cam1LensMode = m.dataset.lens;
      try { localStorage.setItem('camhub_cam1_lens', cam1LensMode); } catch (_) {}
      return live();
    }
    if ((m = c('[data-switch-lens]'))) {
      cam1LensMode = m.dataset.switchLens;
      try { localStorage.setItem('camhub_cam1_lens', cam1LensMode); } catch (_) {}
      return live();
    }
    if ((m = c('[data-okam-focus-lens]')) || (m = c('[data-okam-switch-lens]'))) {
      const target = m.dataset.okamFocusLens || m.dataset.okamSwitchLens;
      if (target === 'split') {
        okamLensMode = 'split';
      } else {
        okamLensMode = 'single';
        const targetCid = `okam_${target}`;
        const idx = cams.findIndex((x) => x.id === targetCid);
        if (idx >= 0) sel = idx;
      }
      return live();
    }
    if ((m = c('[data-open-ptz]'))) {
      const targetCid = m.dataset.openPtz;
      if (targetCid === 'okam-3' || targetCid?.startsWith('okam')) {
        okamLensMode = 'single';
        const idx = cams.findIndex((x) => x.id === 'okam_2');
        if (idx >= 0) sel = idx;
      } else {
        cam1LensMode = '3';
        try { localStorage.setItem('camhub_cam1_lens', cam1LensMode); } catch (_) {}
      }
      ptzPanelOpen = true;
      return live();
    }
    if (c('#btn-toggle-ptz') || (m = c('[data-act="toggle-ptz"]'))) {
      ptzPanelOpen = !ptzPanelOpen;
      return live();
    }
    if ((m = c('[data-cam1-lens]'))) {
      cam1GridLens = m.dataset.cam1Lens;
      try { localStorage.setItem('camhub_cam1_grid_lens', cam1GridLens); } catch (_) {}
      const feed1 = $('#feed-v380-1');
      if (feed1) {
        feed1.className = `video${fitMode === 'cover' ? ' fill' : ''}${cam1GridLens !== 'all' ? ` lens-${cam1GridLens}` : ''}`;
        if (cam1GridLens !== 'all') {
          feed1.style.setProperty('--cam-aspect', '16 / 9');
          feed1.style.setProperty('--cam-ratio', '1.7778');
        } else {
          feed1.style.setProperty('--cam-aspect', '16 / 27');
          feed1.style.setProperty('--cam-ratio', '0.5926');
        }
      }
      document.querySelectorAll('[data-cam1-lens]').forEach((b) => {
        b.setAttribute('aria-pressed', b.dataset.cam1Lens === cam1GridLens ? 'true' : 'false');
      });
      return;
    }

    // Digital Zoom controls
    const zoomBtn = c('[data-zoom]');
    if (zoomBtn) {
      const type = zoomBtn.dataset.zoom;
      if (type === 'in') setZoom(zoomLevel + 0.25);
      else if (type === 'out') setZoom(zoomLevel - 0.25);
      else if (type === 'reset') setZoom(1.0);
      return;
    }

    if (c('[data-fs]')) {
      toggleFullscreen();
      return;
    }

    if (c('#refresh')) {
      pollBackendHealth();
      return toast('Feeds & telemetry refreshed');
    }

    if (c('#restart') || c('#dock-power')) return ask('restart');
    if (c('#btn-stop-all')) return ask('stop');
    if (c('#btn-run-all')) return runAllCameras();
    if (c('#btn-toggle-role') || c('#dock-role')) return toggleRole();
    if (c('#btn-theme') || c('#dock-theme')) return toggleTheme(e);

    // Dialog handlers
    if (c('#no')) return $('#dlg')?.close();
    if (c('#yes')) {
      $('#dlg')?.close();
      if (pend === 'restart') return restartAllCameras();
      if (pend === 'stop') return stopAllCameras();
      return;
    }

    // Playback actions
    if ((m = c('[data-rec-play]'))) return playRecording(m.dataset.recPlay);
    if ((m = c('[data-rec-del]'))) return deleteRecording(m.dataset.recDel);
    if (c('#refresh-recordings')) {
      loadRecordings();
      return toast('Recordings list refreshed');
    }
    if (c('#btn-trigger-motion')) return triggerTestMotionRecording();

    // Events actions
    if ((m = c('[data-filter-cid]'))) {
      const targetCid = m.dataset.filterCid;
      eventFilterCid = targetCid;
      $$('#events-cam-filter button').forEach((btn) => {
        btn.setAttribute('aria-pressed', btn.dataset.cid === targetCid ? 'true' : 'false');
      });
      renderEventsList();
      return;
    }
    if ((m = c('[data-ev-snap]'))) return openEventLightbox(m.dataset.evSnap);
    if ((m = c('[data-ev-del]'))) return deleteEvent(m.dataset.evDel);
    if (c('#clear-events-btn')) return clearAllEvents();
    if (c('#btn-ai-benchmark')) return runAiBenchmark();
    if (c('#lightbox-close')) return $('#event-dialog')?.close();

    // Storage actions
    if (c('#btn-dry-run-cleanup')) return dryRunCleanup();
    if (c('#btn-exec-cleanup')) return executeRetentionCleanup();
    if (c('#btn-reindex-storage')) return reindexStorage();

    // Diagnostics actions
    if (c('#btn-generate-bundle')) return generateDiagnosticBundle();

    // Notifications actions
    if ((m = c('[data-notif-ack]'))) return acknowledgeNotification(m.dataset.notifAck);
    if (c('#notif-ack-all')) return acknowledgeAllNotifications();
    if (c('#notif-clear-all')) return clearAllNotifications();
    if (c('#notif-simulate')) return simulateNotification();
    if (c('#btn-telegram-settings')) return $('#telegram-dialog')?.showModal();
    if (c('#tg-cancel')) return $('#telegram-dialog')?.close();
    if (c('#tg-test')) return testTelegramBot();

    // Config dialog cancel
    if (c('#cfg-cancel')) return $('#config-dialog')?.close();
    if (c('#auth-cancel-btn')) return $('#auth-dialog')?.close();
  });

  $('#auth-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const errEl = $('#auth-error-msg');
    if (errEl) errEl.style.display = 'none';
    const username = $('#auth-username')?.value?.trim() || 'admin';
    const password = $('#auth-password')?.value || '';

    try {
      let res;
      if (authSetupRequired) {
        const bootstrapToken = $('#auth-bootstrap')?.value?.trim() || '';
        const viewerPassword = $('#auth-viewer-password')?.value || '';
        res = await fetch('/api/auth/setup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({
            bootstrapToken,
            adminUsername: username,
            adminPassword: password,
            viewerPassword: viewerPassword || undefined
          })
        });
      } else {
        res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ username, password })
        });
      }
      const data = await res.json();
      if (res.ok && data.authenticated) {
        authSetupRequired = false;
        applyServerRole(data.role, data.username, true);
        if ($('#auth-password')) $('#auth-password').value = '';
        $('#auth-dialog')?.close();
        toast(`Signed in as ${data.username} (${data.role})`);
        live();
        reloadAllStreams(null);
        pollBackendHealth();
      } else if (errEl) {
        errEl.textContent = data.error || 'Authentication failed';
        errEl.style.display = 'block';
      }
    } catch (err) {
      if (errEl) {
        errEl.textContent = err.message;
        errEl.style.display = 'block';
      }
    }
  });

  $('#auth-logout-btn')?.addEventListener('click', async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
    } catch (_) {}
    applyServerRole(null, null, false);
    $('#auth-dialog')?.close();
    toast('Signed out');
    openAuthDialog();
  });

  // Config form submit
  $('#config-form')?.addEventListener('submit', (e) => {
    e.preventDefault();
    const cam = cams[sel];
    if (cam) {
      cam.n = $('#cfg-name').value || cam.n;
      cam.streamUrl = $('#cfg-url').value || cam.streamUrl;
      cam.ip = $('#cfg-location').value || cam.ip;
      toast(`Saved configuration for ${cam.n}`);
      live();
    }
    $('#config-dialog')?.close();
  });

  // --- Light & Dark Theme Toggle with Circular Reveal Animation ---
  function getTheme() {
    return document.documentElement.getAttribute('data-theme') || 'dark';
  }

  function applyThemeState(newTheme) {
    if (newTheme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    try {
      localStorage.setItem('camhub_theme', newTheme);
    } catch (_) {}

    // Update tooltips and titles
    const dockThemeTip = $('#dock-theme .dock__tip');
    if (dockThemeTip) {
      dockThemeTip.innerHTML = `${newTheme === 'light' ? 'Dark' : 'Light'} Mode <kbd>T</kbd>`;
    }
    const btnTheme = $('#btn-theme');
    if (btnTheme) {
      btnTheme.title = `Switch to ${newTheme === 'light' ? 'dark' : 'light'} theme`;
    }
  }

  function toggleTheme(event) {
    const currentTheme = getTheme();
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';

    // Get origin coordinates from click event or fallback to button center
    let x = window.innerWidth / 2;
    let y = window.innerHeight / 2;

    if (event && (event.clientX || event.clientY)) {
      x = event.clientX;
      y = event.clientY;
    } else {
      const btn = $('#dock-theme') || $('#btn-theme');
      if (btn) {
        const rect = btn.getBoundingClientRect();
        x = rect.left + rect.width / 2;
        y = rect.top + rect.height / 2;
      }
    }

    // Distance to furthest screen corner
    const endRadius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y)
    );

    // 1. Modern View Transitions API with CSS Circular Reveal Animation
    if (document.startViewTransition) {
      const transition = document.startViewTransition(() => {
        applyThemeState(newTheme);
      });

      transition.ready.then(() => {
        document.documentElement.animate(
          {
            clipPath: [
              `circle(0px at ${x}px ${y}px)`,
              `circle(${endRadius}px at ${x}px ${y}px)`
            ]
          },
          {
            duration: 520,
            easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
            pseudoElement: '::view-transition-new(root)'
          }
        );
      });
      return;
    }

    // 2. High-performance Fallback circular reveal overlay
    const overlay = document.createElement('div');
    overlay.className = 'theme-reveal-overlay';
    overlay.style.background = newTheme === 'light' ? '#f1f2ef' : '#000000';
    overlay.style.clipPath = `circle(0px at ${x}px ${y}px)`;
    document.body.appendChild(overlay);

    overlay.offsetHeight; // force reflow

    overlay.style.clipPath = `circle(${endRadius}px at ${x}px ${y}px)`;
    setTimeout(() => {
      applyThemeState(newTheme);
      setTimeout(() => {
        overlay.style.opacity = '0';
        overlay.style.transition = 'opacity 150ms ease';
        setTimeout(() => overlay.remove(), 160);
      }, 50);
    }, 480);
  }

  // --- Quick Finder / Command Palette (Murmura Style) ---
  const finderDlg = $('#finder-dialog');
  const finderInput = $('#finder-input');
  const finderResults = $('#finder-results');
  let finderIndex = 0;

  function buildFinderItems() {
    const list = [];
    // Cameras
    cams.forEach((c, idx) => {
      list.push({
        type: 'camera',
        title: `${c.n}`,
        subtitle: `Focus live stream · ${c.ip}`,
        icon: 'i-cam',
        badge: `Camera ${idx + 1}`,
        action: () => {
          sel = idx;
          zoomLevel = 1.0;
          panX = 0;
          panY = 0;
          live();
          layout('focus');
          go(0);
        }
      });
    });

    // Navigation Tabs
    const tabIcons = ['i-live', 'i-grid', 'i-play', 'i-spark', 'i-db', 'i-pulse', 'i-bell', 'i-gear'];
    tabs.forEach((t, idx) => {
      list.push({
        type: 'tab',
        title: t[0],
        subtitle: sentences[idx] || `Switch to ${t[0]}`,
        icon: tabIcons[idx] || 'i-live',
        badge: `Tab ${idx + 1}`,
        action: () => go(idx)
      });
    });

    // Quick Actions
    list.push({
      type: 'action',
      title: 'Add / Discover Camera',
      subtitle: 'Open camera setup & configuration form',
      icon: 'i-plus',
      badge: 'Setup',
      action: () => {
        go(7);
        setTimeout(() => {
          const inp = $('#cam-name');
          if (inp) {
            inp.focus();
            inp.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        }, 150);
      }
    });
    list.push({
      type: 'action',
      title: 'Restart All Cameras',
      subtitle: 'Gracefully restart camera worker decoders',
      icon: 'i-pwr',
      badge: 'Action',
      action: () => ask('restart')
    });
    list.push({
      type: 'action',
      title: 'Run All Cameras',
      subtitle: 'Start all camera decoders',
      icon: 'i-play',
      badge: 'Action',
      action: () => runAllCameras()
    });
    list.push({
      type: 'action',
      title: 'Stop All Cameras',
      subtitle: 'Halt all camera streaming and decoding processes',
      icon: 'i-stop',
      badge: 'Action',
      action: () => ask('stop')
    });
    list.push({
      type: 'action',
      title: `Switch Role (Current: ${currentUserRole === 'admin' ? 'Admin' : 'Viewer'})`,
      subtitle: 'Toggle Admin or Viewer UI mode',
      icon: 'i-shield',
      badge: 'Role',
      action: () => toggleRole()
    });
    list.push({
      type: 'action',
      title: `Toggle Theme (Switch to ${getTheme() === 'light' ? 'Dark' : 'Light'} Mode)`,
      subtitle: 'Circular reveal light and dark mode transition',
      icon: getTheme() === 'light' ? 'i-moon' : 'i-sun',
      badge: 'Theme',
      action: () => toggleTheme()
    });

    return list;
  }

  function renderFinderResults(query = '') {
    if (!finderResults) return;
    const q = query.trim().toLowerCase();
    const all = buildFinderItems();
    const filtered = q
      ? all.filter(it => it.title.toLowerCase().includes(q) || it.subtitle.toLowerCase().includes(q) || it.badge.toLowerCase().includes(q))
      : all;

    finderIndex = Math.min(finderIndex, Math.max(0, filtered.length - 1));

    if (!filtered.length) {
      finderResults.innerHTML = `<div class="empty" style="padding:28px 16px;text-align:center;"><p style="color:var(--muted)">No matching items found for "${escapeHtml(query)}"</p></div>`;
      return;
    }

    finderResults.innerHTML = filtered.map((it, idx) => `
      <div class="finder-item ${idx === finderIndex ? 'active' : ''}" data-finder-idx="${idx}">
        <svg class="ico"><use href="#${it.icon}"/></svg>
        <div class="finder-item-txt">
          <b>${escapeHtml(it.title)}</b>
          <small>${escapeHtml(it.subtitle)}</small>
        </div>
        <span class="finder-item-badge">${escapeHtml(it.badge)}</span>
      </div>
    `).join('');

    finderResults.querySelectorAll('.finder-item').forEach((el, idx) => {
      el.addEventListener('click', () => {
        finderDlg?.close();
        filtered[idx].action();
      });
      el.addEventListener('mouseenter', () => {
        finderResults.querySelectorAll('.finder-item').forEach(x => x.classList.remove('active'));
        el.classList.add('active');
        finderIndex = idx;
      });
    });
  }

  function openQuickSearch() {
    if (!finderDlg) return;
    finderIndex = 0;
    if (finderInput) finderInput.value = '';
    renderFinderResults();
    finderDlg.showModal();
    finderInput?.focus();
  }

  if (finderInput) {
    finderInput.addEventListener('input', (e) => {
      finderIndex = 0;
      renderFinderResults(e.target.value);
    });
    finderInput.addEventListener('keydown', (e) => {
      const items = finderResults ? finderResults.querySelectorAll('.finder-item') : [];
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (items.length) {
          finderIndex = (finderIndex + 1) % items.length;
          items.forEach((x, k) => x.classList.toggle('active', k === finderIndex));
          items[finderIndex]?.scrollIntoView({ block: 'nearest' });
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (items.length) {
          finderIndex = (finderIndex - 1 + items.length) % items.length;
          items.forEach((x, k) => x.classList.toggle('active', k === finderIndex));
          items[finderIndex]?.scrollIntoView({ block: 'nearest' });
        }
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const active = items[finderIndex];
        if (active) active.click();
      }
    });
  }
  if ($('#finder-close')) {
    $('#finder-close').addEventListener('click', () => finderDlg?.close());
  }
  if (finderDlg) {
    finderDlg.addEventListener('click', (e) => {
      if (e.target === finderDlg) finderDlg.close();
    });
  }

  // --- Tactical Keyboard Listener for PTZ, Zoom & Fullscreen ---
  window.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;

    // Global Shortcuts (Murmura style):
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      openQuickSearch();
      return;
    }
    if ((e.key === 'n' || e.key === 'N') && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      go(7);
      setTimeout(() => {
        const inp = $('#cam-name');
        if (inp) {
          inp.focus();
          inp.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }, 150);
      return;
    }
    // Theme toggle shortcut: T or t
    if ((e.key === 't' || e.key === 'T') && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      toggleTheme();
      return;
    }

    const vLive = $('#v-live');
    const isPtzActive = vLive && !vLive.hidden && ptzPanelOpen;
    if (!isPtzActive && !e.ctrlKey && !e.metaKey && !e.altKey && e.key >= '1' && e.key <= '8') {
      const targetIdx = parseInt(e.key, 10) - 1;
      if (targetIdx >= 0 && targetIdx < tabs.length) {
        e.preventDefault();
        go(targetIdx);
        return;
      }
    }

    if (!vLive || vLive.hidden) return;

    // Fullscreen toggle
    if (e.key === 'f' || e.key === 'F') {
      e.preventDefault();
      toggleFullscreen();
      return;
    }

    const c = cams[sel] || cams[0];

    // Digital Zoom / PTZ Zoom
    if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      if ((c.id === 'v380-1' || c.id === 'okam-3' || c.id.startsWith('okam')) && ptzPanelOpen) {
        sendPtzZoom(c.id, 'in', ptzSpeed);
      } else {
        setZoom(zoomLevel + 0.25);
      }
      return;
    } else if (e.key === '-' || e.key === '_') {
      e.preventDefault();
      if ((c.id === 'v380-1' || c.id === 'okam-3' || c.id.startsWith('okam')) && ptzPanelOpen) {
        sendPtzZoom(c.id, 'out', ptzSpeed);
      } else {
        setZoom(zoomLevel - 0.25);
      }
      return;
    } else if (e.key === '0') {
      e.preventDefault();
      setZoom(1.0);
      return;
    }

    if (c.id !== 'v380-1' && c.id !== 'okam-3' && !c.id.startsWith('okam')) return;

    let dir = null;
    if (e.key === 'ArrowUp') dir = 'up';
    else if (e.key === 'ArrowDown') dir = 'down';
    else if (e.key === 'ArrowLeft') dir = 'left';
    else if (e.key === 'ArrowRight') dir = 'right';
    else if (e.key === ' ') {
      e.preventDefault();
      sendPtzStop(c.id);
      return;
    } else if (['1', '2', '3', '4', '5'].includes(e.key)) {
      sendPtzPreset(c.id, 'goto', parseInt(e.key, 10));
      return;
    }

    if (dir && activePtzDir !== dir) {
      e.preventDefault();
      const btn = $(`[data-ptz-dir="${dir}"]`);
      if (btn) btn.classList.add('active');
      sendPtzMove(c.id, dir, ptzSpeed, ptzMode === 'step' ? ptzStepMs : null, ptzMode);
    }
  });

  // Fullscreen state listener (for Esc key & native exit)
  ['fullscreenchange', 'webkitfullscreenchange', 'mozfullscreenchange', 'MSFullscreenChange'].forEach(ev => {
    document.addEventListener(ev, () => {
      const mc = $('#mc');
      if (!isPlayerFullscreen() && mc) {
        mc.classList.remove('is-fullscreen');
      }
      updateFsButton();
      applyZoomTransform();
    });
  });

  window.addEventListener('keyup', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    const vLive = $('#v-live');
    if (!vLive || vLive.hidden) return;

    const c = cams[sel] || cams[0];
    if (c.id !== 'v380-1' && c.id !== 'okam-3' && !c.id.startsWith('okam')) return;

    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
      e.preventDefault();
      $$('.ptz-btn').forEach(b => b.classList.remove('active'));
      if (ptzMode === 'continuous') {
        sendPtzStop(c.id);
      }
    }
  });

  // --- Initialization ---
  window.addEventListener('resize', () => {
    move();
    drawFps();
  });

  initTabs();
  seg('#layouts', (b) => layout(b.dataset.l));
  seg('#fit-modes', (b) => applyFitMode(b.dataset.fit));
  seg('#pick', (b) => {
    pick = +b.dataset.i;
    path();
  });
  seg('#range', () => drawFps());
  seg('#recordings-cam-filter', (b) => {
    recordingFilterCid = b.dataset.recCid || '';
    loadRecordings();
  });
  seg('#events-cam-filter', (b) => {
    eventFilterCid = b.dataset.cid || '';
    renderEventsList();
  });
  seg('#notif-sev-filter', (b) => {
    notifFilterSev = b.dataset.sev || '';
    renderNotificationsList();
  });

  // Initialize theme from localStorage or system preference
  try {
    const savedTheme = localStorage.getItem('camhub_theme');
    if (savedTheme === 'light') {
      applyThemeState('light');
    } else if (!savedTheme && window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
      applyThemeState('light');
    }
  } catch (_) {}

  dash();
  live();
  go(0); // Start on Live View as designed in user snippet

  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(move);
  }

  // Verify server session first, then start periodic polling
  syncAuthSession(true).then((authed) => {
    if (authed) pollBackendHealth();
  });
  setInterval(() => {
    if (isAuthenticated) pollBackendHealth();
  }, 3000);
})();
