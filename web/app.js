// CamHub Command Center — Core Frontend Application (v5.0)
// Pure black floating HUD architecture with sliding pill navigation and full Agent 1-10 integration.

(function () {
  'use strict';

  // --- Current User Role (Agent 7 RBAC: Admin vs Viewer) ---
  let currentUserRole = 'admin'; // 'admin' | 'viewer'

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
      id: 'okam-3',
      n: 'Camera 3, O Kam Pro',
      shortName: 'Cam 3',
      ip: '192.168.100.6',
      p: '10554',
      d: 'Port 10554 · VStarcam',
      streamUrl: '/proxy/stream/okam-3',
      snapshotUrl: '/proxy/snapshot/okam-3',
      directStreamUrl: 'http://127.0.0.1:8082/stream.mjpg',
      w: 80,
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
    }
  ];

  const ST = {
    healthy: ['Healthy', 'good-t', 'Live'],
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
    '0 of 3 cameras connected. All three are waiting for frames.',
    'Local MP4 recording archives and stream playback.',
    'Motion detection and edge neural vision events.',
    'Predictable storage management and policy pruning.',
    'One-click diagnostics, port health checks, and log export bundle.',
    'System alerts, camera offline notices, and fault timeline.',
    'Zero-cloud local camera bridge and remote access setup.'
  ];

  const col = ['#f2f2f2', '#6aa9e8', '#8c8c8c'];
  const fpsHistory = { 'v380-1': [], 'v380-2': [], 'okam-3': [] };

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const p2 = (n) => String(n).padStart(2, '0');
  const cnt = (k) => cams.filter((c) => c.s === k).length;

  let sel = 0, pick = 0, pend = '';
  let zoomLevel = 1.0;
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

  function toggleRole() {
    currentUserRole = currentUserRole === 'admin' ? 'viewer' : 'admin';
    document.body.dataset.role = currentUserRole;
    $('#sbf-role').textContent = currentUserRole === 'admin' ? 'Admin' : 'Viewer';
    toast(currentUserRole === 'admin' ? 'Admin mode: controls are visible' : 'Viewer mode: controls are hidden');
  }

  // Action button template
  const A = (c, a, t, x = '') => `<button class="btn ${x}" data-act="${a}" data-cid="${c.id}">${t}</button>`;
  const bar = (c, s) => `<div class="vbar"><span><i class="dot ${s[1]}"></i>${c.n}</span><em>${s[2]}</em></div>`;
  const msg = (c, id) => `
    <div id="${id || `msg-${c.id}`}" class="msg-box" style="display:none;">
      <svg class="ico nosig" style="width:36px;height:36px;opacity:.55;margin-bottom:8px;"><use href="#i-cam"/></svg>
      <b>Can't reach ${escapeHtml(c.n.split(',')[0])}</b>
      <p>No frames from ${c.ip}. Check that the camera is powered on and connected.</p>
      ${A(c, 'restart-cam', 'Retry connection', 'sm')}
    </div>
  `;

  // --- Dynamic Aspect Ratio & Fit Mode ---
  let fitMode = 'contain';
  try {
    fitMode = localStorage.getItem('camhub_fit_mode') || 'contain';
  } catch (_) {}

  let cam1LensMode = 'all';
  try {
    cam1LensMode = localStorage.getItem('camhub_cam1_lens') || 'all';
  } catch (_) {}

  let cam1GridLens = 'all';
  try {
    cam1GridLens = localStorage.getItem('camhub_cam1_grid_lens') || 'all';
  } catch (_) {}

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
    if (video) {
      video.style.setProperty('--cam-aspect', ratio.css);
      video.style.setProperty('--cam-ratio', String(ratio.val));
    }
    const card = img.closest('.card') || img.closest('.thumb');
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
  const acts = (c, f) => `<div class="acts">${A(c, 'record', c.recording ? 'Stop' : 'Record', 'sm rec adm')}${A(c, 'restart-cam', 'Reload', 'sm adm')}${A(c, c.running ? 'stop-cam' : 'start-cam', c.running ? 'Stop' : 'Start', 'sm adm')}${A(c, 'config', 'Configure', 'sm adm')}${f}</div>`;

  const card = (c, i) => {
    const s = ST[c.s] || ST.degraded;
    const isHealthy = c.s === 'healthy' || (c.checks && c.checks.feedAlive);
    const fillCls = fitMode === 'cover' ? ' fill' : '';
    const isCam1 = c.id === 'v380-1';
    const lensCls = isCam1 && cam1GridLens !== 'all' ? ` lens-${cam1GridLens}` : '';
    const cardAspect = isCam1 && cam1GridLens !== 'all' ? '16 / 9' : (c.aspectRatio || '16 / 9');
    const cardRatioVal = isCam1 && cam1GridLens !== 'all' ? 1.7778 : (c.aspectVal || 1.7778);
    const cardRes = isCam1 && cam1GridLens !== 'all' ? '1920×1080 (16:9)' : (c.resolution || '');

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
          <img class="mjpeg-stream" id="stream-img-${c.id}" src="${c.streamUrl}" alt="${escapeHtml(c.n)}" 
            onerror="this.style.display='none'; const m=document.getElementById('msg-${c.id}'); if(m) m.style.display='flex';" 
            onload="this.style.display='block'; const m=document.getElementById('msg-${c.id}'); if(m) m.style.display='none'; window.applyCameraRatio && window.applyCameraRatio(this, '${c.id}');" 
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
    const fillCls = fitMode === 'cover' ? ' fill' : '';
    return `
      <div class="video${fillCls}" style="--cam-aspect: ${c.aspectRatio || '16 / 9'}; --cam-ratio: ${c.aspectVal || 1.7778};">
        <div class="vbar">
          <span><i class="dot ${s[1]}"></i>CAM ${p2(i + 1)}</span>
          <em>${s[2]}</em>
        </div>
        <img src="${snapUrl}?t=${Date.now()}" alt="${escapeHtml(c.n)}" 
          onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='block';" 
          onload="this.style.display='block'; if(this.nextElementSibling) this.nextElementSibling.style.display='none'; window.applyCameraRatio && window.applyCameraRatio(this, '${c.id}');" />
        <svg class="ico nosig" style="width:30px;height:30px;opacity:.45;display:none;"><use href="#i-cam"/></svg>
      </div>
      <div class="tl">
        <b>${escapeHtml(c.n)}</b>
        <span class="${s[1]}"><i class="dot"></i>${s[0]}</span>
      </div>
    `;
  };

  const thumb = (c, i, a, k) => `<button class="thumb" ${k}="${i}"${a === null ? '' : ` aria-pressed="${a}"`} aria-label="${c.n}, ${ST[c.s][0]}">${mini(c, i)}</button>`;

  // --- Live View Rendering ---
  function live() {
    const c = cams[sel] || cams[0], s = ST[c.s] || ST.degraded;
    const stage = $('#stage');
    const isHealthy = c.s === 'healthy' || (c.checks && c.checks.feedAlive);
    const fillCls = fitMode === 'cover' ? ' fill' : '';
    const isCam1 = c.id === 'v380-1';

    if (stage) {
      if (isCam1 && cam1LensMode === 'split') {
        // Multi-Lens Split 3-Channel Grid View
        stage.innerHTML = `
          <div class="card cam" style="grid-column: 1 / -1;">
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
            <div class="lens-split-grid">
              <div class="cam-split-card">
                <div class="video lens-1${fillCls}" style="aspect-ratio:16/9;">
                  <div class="vbar"><span><i class="dot ${s[1]}"></i>Lensa 1 · Atas (Panoramic)</span><em>Live · 1920×1080</em></div>
                  <img class="mjpeg-stream" src="${c.streamUrl}" alt="Lensa 1" style="${isHealthy ? 'display:block;' : 'display:none;'}">
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
                  <img class="mjpeg-stream" src="${c.streamUrl}" alt="Lensa 2" style="${isHealthy ? 'display:block;' : 'display:none;'}">
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
                  <img class="mjpeg-stream" src="${c.streamUrl}" alt="Lensa 3" style="${isHealthy ? 'display:block;' : 'display:none;'}">
                  ${msg(c, 'msg-lens-3')}
                </div>
                <div class="cmeta" style="padding:10px 4px 2px;">
                  <div class="mrow">
                    <b>Lensa 3 · PTZ Rotasi (Bawah)</b>
                    <button class="btn sm" data-switch-lens="3">Perbesar Lensa 3</button>
                  </div>
                  <div class="ip">Sensor Gerak PTZ · 1920×1080 · 16:9 widescreen</div>
                </div>
              </div>
            </div>
            <div class="cmeta" style="margin-top:14px;">
              <div class="mrow">
                <div>
                  <b class="nm">${escapeHtml(c.n)} (3 Lensa Aktif Simultan)</b>
                  <div class="ip">${c.ip} · ${c.d} · Port ${c.p} <span class="res-tag">3x 1920×1080</span></div>
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
      } else {
        const lensCls = isCam1 && cam1LensMode !== 'all' ? ` lens-${cam1LensMode}` : '';
        const stageAspect = isCam1 && cam1LensMode !== 'all' ? '16 / 9' : (c.aspectRatio || '16 / 9');
        const stageRatioVal = isCam1 && cam1LensMode !== 'all' ? 1.7778 : (c.aspectVal || 1.7778);
        const stageRes = isCam1 && cam1LensMode !== 'all' ? '1920×1080 (16:9)' : (c.resolution || '');
        const lensTitle = isCam1 && cam1LensMode === '1' ? 'Camera 1 · Lensa 1 (Atas - Panoramic)' : (isCam1 && cam1LensMode === '2' ? 'Camera 1 · Lensa 2 (Tengah - Fixed Tele)' : (isCam1 && cam1LensMode === '3' ? 'Camera 1 · Lensa 3 (Bawah - PTZ Rotasi)' : c.n));

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
        ` : '';

        stage.innerHTML = `
          <div class="card cam">
            ${lensBar}
            <div class="video big${fillCls}${lensCls}" id="mc" style="--cam-aspect: ${stageAspect}; --cam-ratio: ${stageRatioVal}; transform:scale(${zoomLevel});transform-origin:center center;">
              ${bar(c, s)}
              <img class="mjpeg-stream" id="stream-img-main" src="${c.streamUrl}" alt="${escapeHtml(c.n)}" 
                onerror="this.style.display='none'; const m=document.getElementById('msg-main'); if(m) m.style.display='flex';" 
                onload="this.style.display='block'; const m=document.getElementById('msg-main'); if(m) m.style.display='none'; window.applyCameraRatio && window.applyCameraRatio(this, '${c.id}');"
                style="${isHealthy ? 'display:block;' : 'display:none;'}">
              ${msg(c, 'msg-main')}
              <div class="vfoot">
                <span class="ts"></span>
                <span class="res-tag">${stageRes}</span>
                <div class="zoom">
                  <button class="btn" data-zoom="in" aria-label="Zoom in">+</button>
                  <button class="btn" data-zoom="reset" aria-label="Reset zoom">${zoomLevel.toFixed(1)}x</button>
                  <button class="btn" data-zoom="out" aria-label="Zoom out">−</button>
                  <button class="btn" data-fs aria-label="Full screen">⤢</button>
                </div>
              </div>
            </div>
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
    applyFitMode(fitMode);
    tick();
  }

  function updateLiveStats() {
    const c = cams[sel] || cams[0];
    const s = ST[c.s] || ST.degraded;

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
    track.innerHTML = '<span class="pill" id="pill"></span>' + tabs
      .map((t, i) => `<button class="tab" data-go="${i}">${t[0]}${t[2] !== undefined ? `<i>${t[2]}</i>` : ''}</button>`)
      .join('');
  }

  function move() {
    const p = $('#pill');
    const a = track ? track.querySelector('[aria-current="page"]') : null;
    if (p && a) {
      p.style.width = a.offsetWidth + 'px';
      p.style.transform = `translateX(${a.offsetLeft}px)`;
    }
  }

  function go(i) {
    if (!track) return;
    track.querySelectorAll('.tab').forEach((t, k) => {
      if (k === i) t.setAttribute('aria-current', 'page');
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
    if ($('#stage')) $('#stage').hidden = g;
    if ($('#cams')) $('#cams').hidden = !g;
    $$('#layouts button').forEach((x) => x.setAttribute('aria-pressed', x.dataset.l === l));
  }

  // --- AGENT 1: Service Operations ---
  async function runAllCameras() {
    toast(`Starting all ${cams.length} cameras…`);
    try {
      const res = await fetch('/api/services/start-all', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        toast('All camera decoders started successfully.');
        setTimeout(pollBackendHealth, 1000);
      } else {
        toast(`Start notice: ${data.message || 'Starting workers'}`);
      }
    } catch (err) {
      toast(`Error: ${err.message}`);
    }
  }

  async function stopAllCameras() {
    toast(`Stopping all ${cams.length} cameras…`);
    try {
      const res = await fetch('/api/services/stop-all', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        toast('All camera decoders stopped.');
        setTimeout(pollBackendHealth, 1000);
      }
    } catch (err) {
      toast(`Error: ${err.message}`);
    }
  }

  async function restartAllCameras() {
    toast(`Restarting all ${cams.length} cameras…`);
    try {
      const res = await fetch('/api/services/restart-all', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        toast('All camera decoders restarted successfully.');
        setTimeout(pollBackendHealth, 1500);
      }
    } catch (err) {
      toast(`Error: ${err.message}`);
    }
  }

  async function startCamera(cid) {
    try {
      const res = await fetch(`/api/services/start?id=${encodeURIComponent(cid)}`, { method: 'POST' });
      if (res.ok) {
        toast(`Started decoder for ${cid}`);
        setTimeout(pollBackendHealth, 1000);
      }
    } catch (err) {
      toast(`Start error: ${err.message}`);
    }
  }

  async function stopCamera(cid) {
    try {
      const res = await fetch(`/api/services/stop?id=${encodeURIComponent(cid)}`, { method: 'POST' });
      if (res.ok) {
        toast(`Stopped decoder for ${cid}`);
        setTimeout(pollBackendHealth, 1000);
      }
    } catch (err) {
      toast(`Stop error: ${err.message}`);
    }
  }

  async function restartCamera(cid) {
    try {
      const res = await fetch(`/api/services/restart?id=${encodeURIComponent(cid)}`, { method: 'POST' });
      if (res.ok) {
        toast(`Restarted decoder for ${cid}`);
        setTimeout(pollBackendHealth, 1000);
      }
    } catch (err) {
      toast(`Restart error: ${err.message}`);
    }
  }

  async function resetCircuitBreaker(cid) {
    try {
      const res = await fetch(`/api/recovery/reset?id=${encodeURIComponent(cid)}`, { method: 'POST' });
      if (res.ok) {
        toast(`Circuit breaker reset for ${cid}. Ready to start.`);
        setTimeout(pollBackendHealth, 1000);
      }
    } catch (err) {
      toast(`Reset error: ${err.message}`);
    }
  }

  // --- AGENT 4: Local Recording & Playback ---
  let recordingsCache = [];

  async function loadRecordings() {
    renderManualRecordingControls();
    const listEl = $('#recordings-list');
    if (!listEl) return;

    try {
      const res = await fetch('/api/recordings');
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
      dlBtn.download = rec.filename || `${id}.mp4`;
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
      const [healthRes, storageRes, servicesRes] = await Promise.all([
        fetch('/api/health').then((r) => (r.ok ? r.json() : null)),
        fetch('/api/storage/status').then((r) => (r.ok ? r.json() : null)),
        fetch('/api/services/status').then((r) => (r.ok ? r.json() : null))
      ]);

      if (healthRes && healthRes.cameras) {
        Object.entries(healthRes.cameras).forEach(([cid, camData]) => {
          const localCam = cams.find((c) => c.id === cid);
          if (localCam) {
            localCam.s = (camData.status || 'degraded').toLowerCase();
            if (camData.checks) localCam.checks = camData.checks;
            if (camData.metrics) {
              localCam.fps = camData.metrics.fps || 0.0;
              localCam.latencyMs = Math.round(camData.metrics.latencyMs || 0);
              localCam.queue = `${camData.metrics.queueDepth || 0} / 0`;
              localCam.decodeErrors = camData.metrics.decodeErrors || 0;
            }

            if (!fpsHistory[cid]) fpsHistory[cid] = [];
            fpsHistory[cid].push(localCam.fps);
            if (fpsHistory[cid].length > 30) fpsHistory[cid].shift();
          }
        });

        if (servicesRes && servicesRes.services) {
          Object.entries(servicesRes.services).forEach(([cid, sData]) => {
            const localCam = cams.find((c) => c.id === cid);
            if (localCam) {
              localCam.running = sData.running;
              localCam.circuitBreakerTripped = sData.circuitBreakerTripped || false;
            }
          });
        }

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

    if ((m = c('[data-go]'))) return go(+m.dataset.go);

    if ((m = c('[data-act]'))) {
      const act = m.dataset.act;
      const cid = m.dataset.cid;
      const targetCam = cams.find((x) => x.id === cid) || cams[sel];

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
      live();
      layout('focus');
      return go(0);
    }

    if ((m = c('[data-thumb]'))) {
      sel = +m.dataset.thumb;
      return live();
    }

    // Camera 1 Multi-Lens selection
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

    // Zoom controls
    const zoomBtn = c('[data-zoom]');
    if (zoomBtn) {
      const type = zoomBtn.dataset.zoom;
      if (type === 'in') zoomLevel = Math.min(zoomLevel + 0.25, 3.0);
      else if (type === 'out') zoomLevel = Math.max(zoomLevel - 0.25, 1.0);
      else if (type === 'reset') zoomLevel = 1.0;
      const mc = $('#mc');
      if (mc) mc.style.transform = `scale(${zoomLevel})`;
      const resetBtn = zoomBtn.parentElement.querySelector('[data-zoom="reset"]');
      if (resetBtn) resetBtn.textContent = `${zoomLevel.toFixed(1)}x`;
      return;
    }

    if (c('[data-fs]')) {
      const f = $('#mc');
      if (f && f.requestFullscreen) f.requestFullscreen();
      return;
    }

    if (c('#refresh')) {
      pollBackendHealth();
      return toast('Feeds & telemetry refreshed');
    }

    if (c('#restart')) return ask('restart');
    if (c('#btn-stop-all')) return ask('stop');
    if (c('#btn-run-all')) return runAllCameras();
    if (c('#btn-toggle-role')) return toggleRole();

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
  seg('#events-cam-filter', (b) => {
    eventFilterCid = b.dataset.cid || '';
    renderEventsList();
  });
  seg('#notif-sev-filter', (b) => {
    notifFilterSev = b.dataset.sev || '';
    renderNotificationsList();
  });

  dash();
  live();
  go(0); // Start on Live View as designed in user snippet

  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(move);
  }

  // Periodic polling
  pollBackendHealth();
  setInterval(pollBackendHealth, 3000);
})();
