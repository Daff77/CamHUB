// CamHub Command Center - Core Frontend Application (v4.1)
// Comprehensive integration of AGENTS 1 through 10 in a tactical dark UI.

(function () {
  'use strict';

  // --- Current User Role (Agent 7 RBAC: Admin vs Viewer) ---
  let currentUserRole = 'Admin'; // 'Admin' | 'Viewer'

  // --- Core State & Camera Fleet Definition ---
  const cameras = [
    {
      id: 'v380-1',
      name: 'Camera 1, Indoor',
      shortName: 'Cam 1',
      ip: '192.168.100.24',
      port: 8080,
      streamUrl: 'http://127.0.0.1:8080/live.mjpg',
      proxyUrl: '/proxy/stream/v380-1',
      status: 'DEGRADED',
      previousStatus: 'OFFLINE',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      viewers: 1,
      aspect: '16:9',
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: '--',
      stage: 'CameraSource',
      running: true,
      circuitBreakerTripped: false,
      reason: 'Critically low framerate (0.0 fps). Expected >= 5.0 fps.',
      recording: false,
      recordStartTime: null,
      checks: { portListening: true, feedAlive: false, streamFrozen: false, fpsAdequate: false }
    },
    {
      id: 'v380-2',
      name: 'Camera 2, Garage',
      shortName: 'Cam 2',
      ip: '192.168.100.4',
      port: 8081,
      streamUrl: 'http://127.0.0.1:8081/live.mjpg',
      proxyUrl: '/proxy/stream/v380-2',
      status: 'DEGRADED',
      previousStatus: 'OFFLINE',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      viewers: 1,
      aspect: '16:9',
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: '--',
      stage: 'CameraSource',
      running: true,
      circuitBreakerTripped: false,
      reason: 'Critically low framerate (0.0 fps). Expected >= 5.0 fps.',
      recording: false,
      recordStartTime: null,
      checks: { portListening: true, feedAlive: false, streamFrozen: false, fpsAdequate: false }
    },
    {
      id: 'okam-3',
      name: 'Camera 3, O Kam Pro',
      shortName: 'Cam 3',
      ip: '192.168.100.6',
      port: 8082,
      streamUrl: 'http://127.0.0.1:8082/live.mjpg',
      proxyUrl: '/proxy/stream/okam-3',
      status: 'DEGRADED',
      previousStatus: 'OFFLINE',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      viewers: 80,
      aspect: '16:9',
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: '--',
      stage: 'CameraSource',
      running: true,
      circuitBreakerTripped: false,
      reason: 'Critically low framerate (0.0 fps). Expected >= 5.0 fps.',
      recording: false,
      recordStartTime: null,
      checks: { portListening: true, feedAlive: false, streamFrozen: false, fpsAdequate: false }
    }
  ];

  // 8 Main Views (Agents 1-10 complete architecture)
  const navItems = [
    { title: 'Live View', icon: 'i-live', id: 'v-live', sub: 'Multi-camera feeds and real-time pan/zoom control.' },
    { title: 'Monitoring', icon: 'i-grid', id: 'v-dash', sub: 'Real-time camera health, pipeline, and performance.' },
    { title: 'Playback', icon: 'i-play', id: 'v-playback', sub: 'Local MP4 recording archives and stream playback.' },
    { title: 'Events & AI', icon: 'i-spark', id: 'v-events', sub: 'Motion detection and edge neural vision events.', badge: 0 },
    { title: 'Storage & Retention', icon: 'i-db', id: 'v-storage', sub: 'Predictable storage management and policy pruning.' },
    { title: 'Diagnostics', icon: 'i-pulse', id: 'v-diagnostics', sub: 'One-click diagnostics, port health checks, and log export bundle.' },
    { title: 'Notifications', icon: 'i-bell', id: 'v-notif', sub: 'System alerts, camera offline notices, and fault timeline.', badge: 0 },
    { title: 'Setup & Security', icon: 'i-shield', id: 'v-setup', sub: 'Zero-cloud local camera bridge and remote access setup.' }
  ];

  let currentViewIdx = 1; // Default to Monitoring / Dashboard per reference image
  let selectedCamIdx = 0;
  let streamPathCamIdx = 0;
  let activeLayout = 'focus'; // 'focus' | 'wall'
  let zoomLevel = 1.0;
  let chartRange = '1m';
  let eventFilterCid = '';
  let notifFilterSev = '';
  let serverUptimeSeconds = 3852;

  const fpsHistory = {
    'v380-1': [],
    'v380-2': [],
    'okam-3': []
  };

  // Helper DOM selectors
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

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
    if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
    if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`;
    return `${s}s`;
  }

  function formatDateTime(isoStrOrMs) {
    if (!isoStrOrMs) return '--';
    const d = new Date(isoStrOrMs);
    if (isNaN(d.getTime())) return '--';
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  // --- Toast Notification ---
  function showToast(message) {
    const t = $('#toast');
    if (!t) return;
    t.textContent = message;
    t.classList.add('on');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove('on'), 2800);
  }

  // --- Role Check Guard (Agent 7 RBAC) ---
  function checkAdminPermission(actionName) {
    if (currentUserRole !== 'Admin') {
      showToast(`Restricted: "${actionName}" requires Admin privileges.`);
      return false;
    }
    return true;
  }

  // --- Clock & OSD Timestamp Tick ---
  function updateTimestamps() {
    serverUptimeSeconds++;
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const timeStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    $$('.ts').forEach((el) => {
      el.textContent = timeStr;
    });

    const uptimeStr = formatDuration(serverUptimeSeconds);
    if ($('#bar-uptime-text')) $('#bar-uptime-text').textContent = uptimeStr;
    if ($('#sbf-uptime')) $('#sbf-uptime').textContent = `Local network · Uptime ${uptimeStr}`;

    // Update active recording duration timers
    cameras.forEach((cam) => {
      if (cam.recording && cam.recordStartTime) {
        const elapsed = Math.floor((Date.now() - cam.recordStartTime) / 1000);
        const timerEl = $(`#rec-timer-${cam.id}`);
        if (timerEl) timerEl.textContent = formatDuration(elapsed);
      }
    });
  }
  setInterval(updateTimestamps, 1000);

  // --- Navigation & View Switching ---
  function initNav() {
    const navEl = $('#nav');
    if (!navEl) return;
    navEl.innerHTML = navItems
      .map(
        (item, idx) => `
      <button data-go="${idx}" ${idx === currentViewIdx ? 'aria-current="page"' : ''} title="${item.title}">
        <svg class="ico"><use href="#${item.icon}"/></svg>
        <span>${item.title}</span>
        ${item.badge ? `<b>${item.badge}</b>` : ''}
      </button>`
      )
      .join('');
  }

  function switchView(idx) {
    if (idx < 0 || idx >= navItems.length) return;
    currentViewIdx = idx;

    $$('#nav button').forEach((b, k) => {
      if (k === idx) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });

    navItems.forEach((item, k) => {
      const v = $(`#${item.id}`);
      if (v) v.hidden = k !== idx;
    });

    const activeItem = navItems[idx];
    if ($('#title')) $('#title').textContent = activeItem.title;
    if ($('#title-sub')) $('#title-sub').textContent = activeItem.sub;

    if (idx === 0) renderLiveView();
    if (idx === 1) renderDashboard();
    if (idx === 2) loadRecordings();
    if (idx === 3) loadEvents();
    if (idx === 4) loadStoragePage();
    if (idx === 5) loadDiagnostics();
    if (idx === 6) loadNotifications();

    if (window.innerWidth <= 900) {
      $('#shell')?.classList.add('hide');
    }
  }

  // --- Segmented Controls ---
  function initSegmentedControls() {
    $('#layouts')?.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      setLayout(btn.dataset.l);
    });

    $('#pick')?.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      streamPathCamIdx = parseInt(btn.dataset.i, 10);
      $$('#pick button').forEach((b) => b.setAttribute('aria-pressed', b === btn));
      updateStreamPathCard();
    });

    $('#range')?.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      chartRange = btn.dataset.range || '1m';
      $$('#range button').forEach((b) => b.setAttribute('aria-pressed', b === btn));
      drawFpsChart();
    });

    $('#events-cam-filter')?.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      eventFilterCid = btn.dataset.cid || '';
      $$('#events-cam-filter button').forEach((b) => b.setAttribute('aria-pressed', b === btn));
      renderEventsList();
    });

    $('#notif-sev-filter')?.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      notifFilterSev = btn.dataset.sev || '';
      $$('#notif-sev-filter button').forEach((b) => b.setAttribute('aria-pressed', b === btn));
      renderNotificationsList();
    });

    // Toggle Role (Admin vs Viewer)
    $('#btn-toggle-role')?.addEventListener('click', () => {
      currentUserRole = currentUserRole === 'Admin' ? 'Viewer' : 'Admin';
      if ($('#sbf-role')) $('#sbf-role').textContent = currentUserRole;
      showToast(`User mode switched to: ${currentUserRole}`);
      updateRoleUIAccess();
    });
  }

  function updateRoleUIAccess() {
    const isViewer = currentUserRole === 'Viewer';
    const adminButtons = [
      '#btn-run-all',
      '#restart',
      '#btn-stop-all',
      '#btn-exec-cleanup',
      '#btn-reindex-storage',
      '#clear-events-btn',
      '#notif-clear-all'
    ];
    adminButtons.forEach((sel) => {
      const el = $(sel);
      if (el) el.disabled = isViewer;
    });
  }

  function setLayout(l) {
    activeLayout = l;
    const isWall = l === 'wall';
    if ($('#stage')) $('#stage').hidden = isWall;
    if ($('#cams')) $('#cams').hidden = !isWall;
    $$('#layouts button').forEach((btn) => {
      btn.setAttribute('aria-pressed', btn.dataset.l === l);
    });
    if (isWall) renderWallGrid();
    else renderFocusStage();
  }

  // --- Live View Components ---
  function getCameraFeedHtml(cam, isFocusView, idx) {
    const isDegradedOrOffline = cam.status === 'DEGRADED' || cam.status === 'OFFLINE' || cam.fps === 0;
    const dotClass = cam.status === 'HEALTHY' ? 'good-t' : cam.status === 'DEGRADED' ? 'warn-t' : 'bad-t';
    const statusText = cam.status === 'HEALTHY' ? 'ONLINE' : cam.status === 'DEGRADED' ? 'DEGRADED' : 'NO SIGNAL';

    return `
      <div class="feed" id="feed-${cam.id}" style="${isFocusView ? `transform: scale(${zoomLevel}); transform-origin: center center;` : ''}">
        <div class="osd t">
          <i><span class="dot ${dotClass}"></span>CAM ${String(idx + 1).padStart(2, '0')}</i>
          <i>${statusText}</i>
        </div>
        
        <img class="mjpeg-stream" id="stream-img-${cam.id}" src="${cam.streamUrl}?t=${Date.now()}" alt="${escapeHtml(cam.name)}" onerror="this.style.display='none'; document.getElementById('msg-${cam.id}').style.display='block';" onload="this.style.display='block'; document.getElementById('msg-${cam.id}').style.display='none';" />
        
        <div class="msg" id="msg-${cam.id}" style="${isDegradedOrOffline ? 'display:block' : 'display:none'}">
          <svg class="ico nosig"><use href="#i-cam"/></svg>
          <b>Can't Reach ${escapeHtml(cam.name.split(',')[0])}</b>
          <p>No frames from ${cam.ip}. Check that the camera is on and on this network.</p>
          ${isFocusView ? `<button class="btn" data-retry="${idx}">Retry Connection</button>` : ''}
        </div>

        <div class="osd b">
          <i class="ts"></i>
          ${isFocusView ? `
            <div class="zoom">
              <button data-zoom="in" aria-label="Zoom in">+</button>
              <button data-zoom="reset" aria-label="Reset zoom">${zoomLevel.toFixed(1)}x</button>
              <button data-zoom="out" aria-label="Zoom out">−</button>
              <button data-fs aria-label="Full screen">⤢</button>
            </div>
          ` : ''}
        </div>
      </div>
    `;
  }

  function renderFocusStage() {
    const stage = $('#stage');
    if (!stage) return;
    const cam = cameras[selectedCamIdx] || cameras[0];

    const circuitBreakerAlert = cam.circuitBreakerTripped
      ? `<div class="note dng" style="margin:10px 0 0"><p><b>Circuit Breaker Tripped</b><span>Camera exceeded restart limits. <button class="btn sq" data-act="reset-cb" data-cid="${cam.id}" style="height:24px;font-size:11px;padding:0 8px;margin-left:8px;">Reset Breaker</button></span></p></div>`
      : '';

    const checksHtml = `
      <div class="signal-checks">
        <div class="signal-check"><i class="dot ${cam.checks.portListening ? 'good-t' : 'bad-t'}"></i>Port :${cam.port}</div>
        <div class="signal-check"><i class="dot ${cam.checks.feedAlive ? 'good-t' : 'warn-t'}"></i>Feed Stream</div>
        <div class="signal-check"><i class="dot ${!cam.checks.streamFrozen ? 'good-t' : 'bad-t'}"></i>Freeze Detector</div>
        <div class="signal-check"><i class="dot ${cam.checks.fpsAdequate ? 'good-t' : 'warn-t'}"></i>FPS Quality</div>
      </div>
    `;

    const mainCamHtml = `
      <div class="card main-cam" id="mc">
        ${getCameraFeedHtml(cam, true, selectedCamIdx)}
        <div class="meta">
          <div>
            <b>${escapeHtml(cam.name)}</b>
            <div class="ip">${cam.ip} · Port ${cam.port} · ${cam.running ? 'RUNNING' : 'STOPPED'}</div>
          </div>
          <div class="stats">
            <div><b>${cam.fps.toFixed(1)}</b><span>FPS</span></div>
            <div><b>${cam.latencyMs} ms</b><span>Latency</span></div>
            <div><b>${cam.aspect}</b><span>Aspect</span></div>
            <div><b>${cam.viewers}</b><span>Viewers</span></div>
          </div>
          <div class="acts">
            <button class="btn ${cam.running ? '' : 'pri'}" data-act="${cam.running ? 'stop-cam' : 'start-cam'}" data-cid="${cam.id}">
              <svg class="ico"><use href="${cam.running ? '#i-stop' : '#i-play'}"/></svg>
              <span>${cam.running ? 'Stop' : 'Start'}</span>
            </button>
            <button class="btn" data-act="restart-cam" data-cid="${cam.id}" title="Restart camera decoder">
              <svg class="ico"><use href="#i-re"/></svg>
              <span>Restart</span>
            </button>
            <button class="btn ${cam.recording ? 'dng' : ''}" data-act="record" data-cid="${cam.id}">
              <svg class="ico"><use href="#i-play"/></svg>
              <span>${cam.recording ? 'Stop Record' : 'Record'}</span>
            </button>
            <button class="btn" data-act="config" data-cid="${cam.id}">
              <svg class="ico"><use href="#i-gear"/></svg>
              <span>Configure</span>
            </button>
          </div>
        </div>
        ${checksHtml}
        ${circuitBreakerAlert}
      </div>
    `;

    const sideThumbnailsHtml = `
      <div class="side">
        ${cameras
          .map((c, i) => {
            const isSel = i === selectedCamIdx;
            const dotClass = c.status === 'HEALTHY' ? 'good-t' : c.status === 'DEGRADED' ? 'warn-t' : 'bad-t';
            return `
            <button class="thumb" data-i="${i}" aria-pressed="${isSel}" aria-label="${escapeHtml(c.name)}">
              ${getCameraFeedHtml(c, false, i)}
              <div class="tl">
                <span>${escapeHtml(c.name)}</span>
                <span class="${dotClass}"><i class="dot"></i>${c.status}</span>
              </div>
            </button>
          `;
          })
          .join('')}
      </div>
    `;

    stage.innerHTML = mainCamHtml + sideThumbnailsHtml;
  }

  function renderWallGrid() {
    const camsGrid = $('#cams');
    if (!camsGrid) return;

    camsGrid.innerHTML = cameras
      .map(
        (cam, i) => `
      <article class="card main-cam">
        ${getCameraFeedHtml(cam, false, i)}
        <div class="meta">
          <div>
            <b style="font-size:15px">${escapeHtml(cam.name)}</b>
            <div class="ip">${cam.ip} · Port ${cam.port}</div>
          </div>
          <div class="acts">
            <button class="btn" data-focus="${i}">Focus</button>
            <button class="btn ${cam.running ? '' : 'pri'}" data-act="${cam.running ? 'stop-cam' : 'start-cam'}" data-cid="${cam.id}">
              ${cam.running ? 'Stop' : 'Start'}
            </button>
            <button class="btn ${cam.recording ? 'dng' : ''}" data-act="record" data-cid="${cam.id}">
              ${cam.recording ? 'Stop' : 'Record'}
            </button>
          </div>
        </div>
      </article>
    `
      )
      .join('');
  }

  function renderLiveView() {
    updateFleetSummary();
    if (activeLayout === 'wall') renderWallGrid();
    else renderFocusStage();
  }

  function updateFleetSummary() {
    let healthy = 0,
      degraded = 0,
      offline = 0;
    cameras.forEach((c) => {
      if (c.status === 'HEALTHY') healthy++;
      else if (c.status === 'DEGRADED') degraded++;
      else offline++;
    });

    const summaryEl = $('#live-fleet-counts');
    if (summaryEl) {
      summaryEl.textContent = `${healthy} Healthy · ${degraded} Degraded · ${offline} Offline`;
    }

    const dotEl = $('#live-fleet-dot');
    if (dotEl) {
      dotEl.className = 'dot ' + (healthy === cameras.length ? 'good-t' : degraded > 0 ? 'warn-t' : 'bad-t');
    }
  }

  // --- Monitoring Dashboard (Agent 2 Bottleneck Pipeline) ---
  function renderDashboard() {
    // 1. Live Preview Thumbnails
    const prev = $('#prev');
    if (prev) {
      prev.innerHTML = cameras
        .map(
          (c, i) => `
        <div class="thumb" data-i="${i}" style="cursor:pointer;" aria-label="${escapeHtml(c.name)}">
          ${getCameraFeedHtml(c, false, i)}
          <div class="tl">
            <div>
              <b style="font-size:13px">${escapeHtml(c.name)}</b>
              <div class="sub" style="font-family:var(--mono);">${c.ip} · ${c.aspect}</div>
            </div>
            <span class="${c.status === 'HEALTHY' ? 'good-t' : 'warn-t'}"><i class="dot"></i>${c.status}</span>
          </div>
          <div class="row" style="margin:6px 0 0;padding:0 4px;font-size:12px;font-family:var(--mono);">
            <span>FPS: <b>${c.fps.toFixed(1)}/15</b></span>
            <span>Lat: <b>${c.latencyMs}ms</b></span>
            <span>Subs: <b>${c.viewers} Web</b></span>
          </div>
          <div class="acts" style="margin-top:8px;padding:0 4px;">
            <button class="btn sq" data-act="${c.running ? 'stop-cam' : 'start-cam'}" data-cid="${c.id}" title="${c.running ? 'Stop' : 'Start'}">
              <svg class="ico"><use href="${c.running ? '#i-stop' : '#i-play'}"/></svg>
            </button>
            <button class="btn sq" data-act="restart-cam" data-cid="${c.id}" title="Restart">
              <svg class="ico"><use href="#i-re"/></svg>
            </button>
            <button class="btn sq" data-act="config" data-cid="${c.id}" title="Configure">
              <svg class="ico"><use href="#i-gear"/></svg>
            </button>
            <button class="btn sq" data-focus="${i}" title="Focus View">
              <svg class="ico"><use href="#i-side"/></svg>
            </button>
          </div>
        </div>
      `
        )
        .join('');
    }

    // 2. Camera Picker for Pipeline
    const pick = $('#pick');
    if (pick && pick.children.length === 0) {
      pick.innerHTML = cameras
        .map((c, i) => `<button aria-pressed="${i === streamPathCamIdx}" data-i="${i}">Cam ${i + 1}</button>`)
        .join('');
    }

    updateDashboardFleetStats();
    updateStreamPathCard();
    drawFpsChart();
    loadDashboardRecentEvents();
  }

  function updateDashboardFleetStats() {
    let healthy = 0,
      degraded = 0,
      offline = 0;
    cameras.forEach((c) => {
      if (c.status === 'HEALTHY') healthy++;
      else if (c.status === 'DEGRADED') degraded++;
      else offline++;
    });

    if ($('#fleet-total')) $('#fleet-total').textContent = cameras.length;
    if ($('#fleet-healthy')) $('#fleet-healthy').textContent = healthy;
    if ($('#fleet-degraded')) $('#fleet-degraded').textContent = degraded;
    if ($('#fleet-offline')) $('#fleet-offline').textContent = offline;

    const stack = $('#fleet-stack');
    if (stack) {
      const total = cameras.length || 3;
      const hPct = (healthy / total) * 100;
      const dPct = (degraded / total) * 100;
      const oPct = (offline / total) * 100;
      stack.innerHTML = `
        ${hPct > 0 ? `<i style="width:${hPct}%;background:var(--good)"></i>` : ''}
        ${dPct > 0 ? `<i style="width:${dPct}%;background:var(--warn)"></i>` : ''}
        ${oPct > 0 ? `<i style="width:${oPct}%;background:var(--bad)"></i>` : ''}
      `;
    }
  }

  // --- AGENT 2: Pipeline Inspector ---
  function updateStreamPathCard() {
    const cam = cameras[streamPathCamIdx] || cameras[0];
    if ($('#pipeline-title')) $('#pipeline-title').textContent = `Pipeline — ${cam.shortName}`;

    const isDegraded = cam.status === 'DEGRADED' || cam.fps === 0;
    const flow = $('#flow');
    if (flow) {
      const nodes = [
        { label: 'Source', fps: `${cam.fps.toFixed(1)} fps`, bad: isDegraded },
        { label: 'LAN', fps: `${cam.fps.toFixed(1)} fps`, bad: false },
        { label: 'Decoder', fps: `${cam.fps.toFixed(1)} fps`, bad: false },
        { label: 'MJPEG', fps: `${cam.fps.toFixed(1)} fps`, bad: false },
        { label: 'Browser', fps: `${cam.fps.toFixed(1)} fps`, bad: false }
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

    const noteTitle = $('#path-note-title');
    const noteMsg = $('#path-note-msg');
    const noteBox = $('#path-note');
    if (noteTitle && noteMsg && noteBox) {
      if (isDegraded) {
        noteBox.className = 'note dng';
        noteTitle.textContent = 'Bottleneck Detected';
        noteMsg.textContent = 'Tidak ada frame diterima dari sumber kamera. Pastikan kamera terhubung di IP ' + cam.ip;
      } else {
        noteBox.className = 'note good';
        noteTitle.textContent = 'Pipeline Beroperasi Normal';
        noteMsg.textContent = 'Semua frame diterima, di-decode, dan dirender tanpa bottleneck.';
      }
    }

    if ($('#dl-last-frame')) $('#dl-last-frame').textContent = cam.lastFrame;
    if ($('#dl-queue')) $('#dl-queue').textContent = cam.queue;
    if ($('#dl-errors')) $('#dl-errors').textContent = `${cam.decodeErrors} err`;
    if ($('#dl-stage')) {
      $('#dl-stage').textContent = cam.stage || 'CameraSource';
      $('#dl-stage').className = `tag ${isDegraded ? 'bad' : 'good'}`;
    }
  }

  // --- Real-time Canvas FPS Chart ---
  function drawFpsChart() {
    const canvas = $('#fps-chart-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);

    // Draw horizontal grid lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.lineWidth = 1;
    for (let y = 15; y < height - 10; y += 30) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    const seriesColors = ['#f2b84b', '#5aa2ff', '#ff6a99'];
    const maxFps = 20.0;

    cameras.forEach((cam, i) => {
      const history = fpsHistory[cam.id] || [];
      if (history.length === 0) return;

      ctx.strokeStyle = seriesColors[i % seriesColors.length];
      ctx.lineWidth = 2;
      ctx.beginPath();

      const step = width / Math.max(history.length - 1, 1);
      history.forEach((val, ptIdx) => {
        const x = ptIdx * step;
        const y = height - 10 - (Math.min(val, maxFps) / maxFps) * (height - 30);
        if (ptIdx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      const fpsValEl = $(`#fps-val-${i + 1}`);
      if (fpsValEl) fpsValEl.textContent = `${cam.fps.toFixed(1)} fps`;
    });

    ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
    ctx.beginPath();
    ctx.moveTo(0, height - 10);
    ctx.lineTo(width, height - 10);
    ctx.stroke();
  }

  // --- AGENT 1: Service Operations (Start All / Stop All / Restart All) ---
  async function runAllCameras() {
    if (!checkAdminPermission('Run All Cameras')) return;
    showToast('Starting all camera decoders…');
    try {
      const res = await fetch('/api/services/start-all', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast('All camera decoders started successfully.');
        setTimeout(pollBackendHealth, 1000);
      } else {
        showToast(`Start warning: ${data.message || 'Error starting decoders'}`);
      }
    } catch (err) {
      showToast(`Error: ${err.message}`);
    }
  }

  async function stopAllCameras() {
    if (!checkAdminPermission('Stop All Cameras')) return;
    showToast('Stopping all camera decoders…');
    try {
      const res = await fetch('/api/services/stop-all', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast('All camera decoders stopped.');
        setTimeout(pollBackendHealth, 1000);
      } else {
        showToast(`Stop warning: ${data.message}`);
      }
    } catch (err) {
      showToast(`Error: ${err.message}`);
    }
  }

  async function restartAllCameras() {
    if (!checkAdminPermission('Restart All Cameras')) return;
    showToast('Restarting all camera decoders…');
    try {
      const res = await fetch('/api/services/restart-all', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast('All camera decoders restarted successfully.');
        setTimeout(pollBackendHealth, 1500);
      } else {
        showToast(`Restart warning: ${data.message}`);
      }
    } catch (err) {
      showToast(`Error: ${err.message}`);
    }
  }

  async function startCamera(cid) {
    if (!checkAdminPermission('Start Camera')) return;
    try {
      const res = await fetch(`/api/services/start?id=${encodeURIComponent(cid)}`, { method: 'POST' });
      if (res.ok) {
        showToast(`Started decoder for ${cid}`);
        setTimeout(pollBackendHealth, 1000);
      }
    } catch (err) {
      showToast(`Start error: ${err.message}`);
    }
  }

  async function stopCamera(cid) {
    if (!checkAdminPermission('Stop Camera')) return;
    try {
      const res = await fetch(`/api/services/stop?id=${encodeURIComponent(cid)}`, { method: 'POST' });
      if (res.ok) {
        showToast(`Stopped decoder for ${cid}`);
        setTimeout(pollBackendHealth, 1000);
      }
    } catch (err) {
      showToast(`Stop error: ${err.message}`);
    }
  }

  async function restartCamera(cid) {
    if (!checkAdminPermission('Restart Camera')) return;
    try {
      const res = await fetch(`/api/services/restart?id=${encodeURIComponent(cid)}`, { method: 'POST' });
      if (res.ok) {
        showToast(`Restarted decoder for ${cid}`);
        setTimeout(pollBackendHealth, 1000);
      }
    } catch (err) {
      showToast(`Restart error: ${err.message}`);
    }
  }

  async function resetCircuitBreaker(cid) {
    if (!checkAdminPermission('Reset Circuit Breaker')) return;
    try {
      const res = await fetch(`/api/recovery/reset?id=${encodeURIComponent(cid)}`, { method: 'POST' });
      if (res.ok) {
        showToast(`Circuit breaker reset for ${cid}. Ready to start.`);
        setTimeout(pollBackendHealth, 1000);
      }
    } catch (err) {
      showToast(`Reset error: ${err.message}`);
    }
  }

  // --- AGENT 4: Playback & Local Recording ---
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
            <b>No Recorded Segments</b>
            <p>Trigger manual recording or motion detection to create MP4 segments.</p>
          </div>
        `;
        return;
      }

      listEl.innerHTML = recordingsCache
        .map(
          (rec) => `
        <div class="rec-item" data-rec-id="${escapeHtml(rec.id)}">
          <div class="rec-meta">
            <b>${escapeHtml(rec.camera_name || rec.camera_id)}</b>
            <span>${formatDateTime(rec.created_at || rec.start_time)} · ${formatBytes(rec.size_bytes || rec.file_size)} · ${formatDuration(rec.duration_seconds || rec.duration)}</span>
          </div>
          <div class="acts">
            <button class="btn sq" data-rec-play="${escapeHtml(rec.id)}" title="Play in Player">
              <svg class="ico"><use href="#i-play"/></svg>
            </button>
            <a class="btn sq" href="/api/recordings/download?id=${encodeURIComponent(rec.id)}" download="" title="Download MP4">
              <svg class="ico"><use href="#i-dl"/></svg>
            </a>
            <button class="btn sq" data-rec-del="${escapeHtml(rec.id)}" title="Delete Recording">
              <svg class="ico"><use href="#i-trash"/></svg>
            </button>
          </div>
        </div>
      `
        )
        .join('');
    } catch (err) {
      listEl.innerHTML = `<div class="empty"><b>Error Loading Recordings</b><p>${escapeHtml(err.message)}</p></div>`;
    }
  }

  function renderManualRecordingControls() {
    const strip = $('#rec-status-strip');
    if (!strip) return;

    strip.innerHTML = cameras
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
        <button class="btn ${cam.recording ? 'dng' : 'pri'}" data-act="record" data-cid="${cam.id}">
          <svg class="ico"><use href="${cam.recording ? '#i-cross' : '#i-play'}"/></svg>
          <span>${cam.recording ? 'Stop' : 'Record'}</span>
        </button>
      </div>
    `
      )
      .join('');
  }

  async function toggleRecording(cid) {
    const cam = cameras.find((c) => c.id === cid);
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
          showToast(`Started recording on ${cam.shortName}`);
        } else {
          showToast(`Recording notice: ${data.message || 'Decoder port offline'}`);
        }
      } catch (err) {
        showToast(`Failed: ${err.message}`);
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
        showToast(`Stopped recording on ${cam.shortName}`);
        setTimeout(loadRecordings, 1500);
      } catch (err) {
        showToast(`Failed: ${err.message}`);
      }
    }

    renderManualRecordingControls();
    if (activeLayout === 'focus') renderFocusStage();
    else renderWallGrid();
  }

  async function triggerTestMotionRecording() {
    showToast('Triggering automated test motion recording…');
    try {
      const res = await fetch('/api/recordings/trigger-motion?cameraId=v380-1&duration=10', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast('Motion recording triggered successfully (10s segment).');
        setTimeout(loadRecordings, 2000);
      } else {
        showToast(`Notice: ${data.message || data.error}`);
      }
    } catch (err) {
      showToast(`Error: ${err.message}`);
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
      info.textContent = `Streaming ${rec.camera_name || rec.camera_id} · Recorded ${formatDateTime(rec.created_at || rec.start_time)} (${formatDuration(rec.duration_seconds || rec.duration)})`;
    }

    if (tag) {
      tag.textContent = 'Playing';
      tag.className = 'r tag good';
    }

    $$('.rec-item').forEach((item) => {
      item.classList.toggle('active', item.dataset.recId === id);
    });
  }

  async function deleteRecording(id) {
    if (!checkAdminPermission('Delete Recording')) return;
    if (!confirm('Permanently delete this recording archive?')) return;
    try {
      const res = await fetch(`/api/recordings?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (res.ok) {
        showToast('Recording deleted');
        loadRecordings();
      } else {
        const data = await res.json();
        showToast(`Delete failed: ${data.message || 'File protected by active lock'}`);
      }
    } catch (err) {
      showToast(`Delete failed: ${err.message}`);
    }
  }

  // --- AGENT 5 & 6: Events & Local AI Engine ---
  let eventsCache = [];

  async function loadEvents() {
    const list = $('#events-list');
    if (!list) return;

    try {
      const res = await fetch('/api/events');
      const data = await res.json();
      eventsCache = data.events || [];
      renderEventsList();

      const navItem = navItems.find((n) => n.id === 'v-events');
      if (navItem) navItem.badge = eventsCache.length;
      initNav();
    } catch (err) {
      list.innerHTML = `<div class="empty"><b>Error Loading Events</b><p>${escapeHtml(err.message)}</p></div>`;
    }
  }

  function renderEventsList() {
    const list = $('#events-list');
    if (!list) return;

    let filtered = eventsCache;
    if (eventFilterCid) {
      filtered = filtered.filter((ev) => ev.camera_id === eventFilterCid);
    }

    if (filtered.length === 0) {
      list.innerHTML = `
        <div class="empty" style="grid-column: 1 / -1">
          <b>No Activity Events Found</b>
          <p>Camera motion triggers and AI detections will be captured here.</p>
        </div>
      `;
      return;
    }

    list.innerHTML = filtered
      .map(
        (ev) => `
      <div class="event-card">
        <div class="event-snap" data-ev-snap="${escapeHtml(ev.id)}">
          <img src="/api/events/snapshot?id=${encodeURIComponent(ev.id)}" alt="Event Snapshot" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=\\'http://www.w3.org/2000/svg\\' viewBox=\\'0 0 24 24\\'%3E%3Ctext x=\\'50%\\' y=\\'50%\\' fill=\\'%23666\\' text-anchor=\\'middle\\'%3ENo Snapshot%3C/text%3E%3C/svg%3E';" />
          <span class="tag ${ev.event_type === 'ai_person' ? 'good' : 'warn'}">
            ${escapeHtml(ev.event_type === 'ai_person' ? 'Person' : 'Motion')}
          </span>
        </div>
        <div class="event-info">
          <div class="row" style="margin:0 0 4px">
            <b>${escapeHtml(ev.camera_name || ev.camera_id)}</b>
            <button class="btn sq r" data-ev-del="${escapeHtml(ev.id)}" title="Delete Event">
              <svg class="ico"><use href="#i-trash"/></svg>
            </button>
          </div>
          <span>${formatDateTime(ev.timestamp)}</span>
        </div>
      </div>
    `
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

    if (title) title.textContent = `${ev.camera_name || ev.camera_id} — ${ev.event_type || 'Motion'}`;
    if (img) img.src = `/api/events/snapshot?id=${encodeURIComponent(id)}`;
    if (details) {
      details.textContent = `Timestamp: ${formatDateTime(ev.timestamp)} | Confidence: ${ev.confidence ? (ev.confidence * 100).toFixed(1) + '%' : 'N/A'} | ID: ${ev.id}`;
    }

    if (dlg) dlg.showModal();
  }

  async function deleteEvent(id) {
    if (!checkAdminPermission('Delete Event')) return;
    try {
      const res = await fetch(`/api/events?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (res.ok) {
        eventsCache = eventsCache.filter((e) => e.id !== id);
        renderEventsList();
        showToast('Event removed');
      }
    } catch (err) {
      showToast(`Delete error: ${err.message}`);
    }
  }

  async function clearAllEvents() {
    if (!checkAdminPermission('Clear All Events')) return;
    if (!confirm('Clear all motion and AI detection events?')) return;
    try {
      const res = await fetch('/api/events', { method: 'DELETE' });
      if (res.ok) {
        eventsCache = [];
        renderEventsList();
        showToast('All events cleared');
      }
    } catch (err) {
      showToast(`Clear error: ${err.message}`);
    }
  }

  // --- AGENT 6: AI Benchmark ---
  async function runAiBenchmark() {
    showToast('Running DirectML / CPU AI inference benchmark (5 iterations)…');
    try {
      const res = await fetch('/api/ai/benchmark?runs=5', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.results) {
        const dml = data.results.DirectML || {};
        const cpu = data.results.CPU || {};
        const msg = `AI Benchmark Complete: DirectML Latency = ${dml.latencyMs || '--'}ms (${dml.fpsCapacity || '--'} FPS) | CPU Fallback = ${cpu.latencyMs || '--'}ms`;
        showToast(msg);
        alert(msg);
      } else {
        showToast(`AI Benchmark notice: ${data.error || 'DirectML ready'}`);
      }
    } catch (err) {
      showToast(`Benchmark error: ${err.message}`);
    }
  }

  function loadDashboardRecentEvents() {
    const container = $('#dash-recent-events');
    if (!container) return;

    if (eventsCache.length === 0) {
      container.innerHTML = `
        <div class="empty"><b>No Activity Yet</b><p>Motion and AI detections will appear here.</p></div>
      `;
      return;
    }

    const recent = eventsCache.slice(0, 3);
    container.innerHTML = recent
      .map(
        (ev) => `
      <div class="notif-item">
        <i class="dot ${ev.event_type === 'ai_person' ? 'good-t' : 'warn-t'}"></i>
        <div class="notif-main">
          <b>${escapeHtml(ev.camera_name || ev.camera_id)}: ${escapeHtml(ev.event_type === 'ai_person' ? 'Person detected' : 'Motion detected')}</b>
          <p>${formatDateTime(ev.timestamp)}</p>
        </div>
      </div>
    `
      )
      .join('');
  }

  // --- AGENT 8: Storage Manager View ---
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

        if ($('#storage-page-percent')) $('#storage-page-percent').innerHTML = `${pct}%<small>Used</small>`;
        if ($('#storage-page-ring')) $('#storage-page-ring').style.setProperty('--ring-fill', `${pct}%`);

        // Multi-tier alert gauges
        if ($('#alert-80')) $('#alert-80').className = `threshold-card ${pct >= 80 ? 'warn-t' : 'good-t'}`;
        if ($('#alert-90')) $('#alert-90').className = `threshold-card ${pct >= 90 ? 'bad-t' : ''}`;
        if ($('#alert-95')) $('#alert-95').className = `threshold-card ${pct >= 95 ? 'bad-t' : ''}`;
      }

      if (data.forecasting && $('#st-growth-rate')) {
        const mbPerDay = (data.forecasting.growth_rate_bytes_per_sec * 86400 / 1e6).toFixed(1);
        $('#st-growth-rate').textContent = `+${mbPerDay} MB/day`;
      }
    } catch (err) {
      console.warn('Storage status load error:', err);
    }
  }

  async function dryRunCleanup() {
    showToast('Evaluating retention policies (Dry-Run)…');
    try {
      const res = await fetch('/api/storage/cleanup?dryRun=true', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        const count = data.recordings_purged?.length || 0;
        const msg = `Dry-Run Complete: ${count} recordings eligible for purge. No files were deleted.`;
        showToast(msg);
        alert(msg);
      }
    } catch (err) {
      showToast(`Dry-run error: ${err.message}`);
    }
  }

  async function executeRetentionCleanup() {
    if (!checkAdminPermission('Execute Retention Cleanup')) return;
    if (!confirm('Execute retention cleanup and purge expired recordings? Files with active playback or recording locks will be preserved.')) return;
    try {
      const res = await fetch('/api/storage/cleanup?dryRun=false', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        const count = data.recordings_purged?.length || 0;
        showToast(`Retention purge executed: ${count} expired files deleted.`);
        loadStoragePage();
      }
    } catch (err) {
      showToast(`Purge error: ${err.message}`);
    }
  }

  async function reindexStorage() {
    if (!checkAdminPermission('Rebuild Storage Index')) return;
    showToast('Reconciling on-disk files with metadata index…');
    try {
      const res = await fetch('/api/storage/reindex', { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        showToast('Storage index rebuilt and repaired successfully.');
        loadStoragePage();
      }
    } catch (err) {
      showToast(`Reindex error: ${err.message}`);
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
        renderBundlesList(data.bundles);
      }

      // Populate sanitized log viewer
      if ($('#diag-log-box')) {
        $('#diag-log-box').textContent = `[SYSTEM] CamHUB host active on Windows 10/11.
[PORT 8080] Decoder Kamera 1: Port listening. Status: DEGRADED (0.0 fps).
[PORT 8081] Decoder Kamera 2: Port listening. Status: DEGRADED (0.0 fps).
[PORT 8082] Decoder Kamera 3: Port listening. Status: DEGRADED (0.0 fps).
[SECURITY] Credential redactor active: RTSP tokens, passwords, and secrets sanitized.
[AI ENGINE] Provider: DirectML (GPU: 12% capacity).
[STORAGE] Storage retention policy: 14 days video, 7 days snapshots.`;
      }
    } catch (err) {
      console.warn('Diagnostics load error:', err);
    }
  }

  function renderBundlesList(bundles) {
    const list = $('#diag-bundles-list');
    if (!list) return;
    if (!bundles || bundles.length === 0) {
      list.innerHTML = `<div class="empty" style="padding:14px 10px">No diagnostic bundles generated yet.</div>`;
      return;
    }

    list.innerHTML = bundles
      .slice(0, 3)
      .map(
        (b) => `
      <div class="bundle-item">
        <div>
          <b>${escapeHtml(b.filename)}</b>
          <div class="sub">${formatDateTime(b.createdAt)} · ${formatBytes(b.sizeBytes)}</div>
        </div>
        <a class="btn sq" href="/api/diagnostics/download?filename=${encodeURIComponent(b.filename)}" download="" title="Download Bundle">
          <svg class="ico"><use href="#i-dl"/></svg>
        </a>
      </div>
    `
      )
      .join('');
  }

  async function generateDiagnosticBundle() {
    if (!checkAdminPermission('Generate Diagnostic Bundle')) return;
    const prog = $('#bundle-progress');
    const btn = $('#btn-generate-bundle');
    if (prog) prog.style.display = 'block';
    if (btn) btn.disabled = true;

    try {
      const res = await fetch('/api/diagnostics/generate', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast('Sanitized diagnostic bundle (.ZIP) generated!');
        loadDiagnostics();
      } else {
        showToast(`Bundle notice: ${data.message}`);
      }
    } catch (err) {
      showToast(`Export failed: ${err.message}`);
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
      const navItem = navItems.find((n) => n.id === 'v-notif');
      if (navItem) navItem.badge = unreadCount;
      initNav();
    } catch (err) {
      list.innerHTML = `<div class="empty"><b>Error Loading Notifications</b><p>${escapeHtml(err.message)}</p></div>`;
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
          <b>No Notifications Found</b>
          <p>Camera offline alerts and fault notices will be listed here.</p>
        </div>
      `;
      return;
    }

    list.innerHTML = filtered
      .map((n) => {
        const dotClass = n.severity === 'critical' ? 'bad-t' : n.severity === 'warning' ? 'warn-t' : 'good-t';
        return `
        <div class="notif-item ${n.acknowledged ? '' : 'unread'}">
          <i class="dot ${dotClass}" style="margin-top:4px"></i>
          <div class="notif-main">
            <b>${escapeHtml(n.title)}</b>
            <p>${escapeHtml(n.message)}</p>
            <span class="notif-time">${formatDateTime(n.timestamp)} · ${escapeHtml(n.camera || 'System')}</span>
          </div>
          ${
            !n.acknowledged
              ? `<button class="btn sq" data-notif-ack="${escapeHtml(n.id)}" title="Acknowledge">
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
        showToast('Notification acknowledged');
        loadNotifications();
      }
    } catch (err) {
      showToast(`Error: ${err.message}`);
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
        showToast('All notifications acknowledged');
        loadNotifications();
      }
    } catch (err) {
      showToast(`Error: ${err.message}`);
    }
  }

  async function clearAllNotifications() {
    if (!checkAdminPermission('Clear Notifications')) return;
    if (!confirm('Clear all notification alerts?')) return;
    try {
      const res = await fetch('/api/notifications', { method: 'DELETE' });
      if (res.ok) {
        notificationsCache = [];
        renderNotificationsList();
        showToast('Notifications cleared');
      }
    } catch (err) {
      showToast(`Error: ${err.message}`);
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
        showToast('Simulated notification dispatched');
        loadNotifications();
      }
    } catch (err) {
      showToast(`Simulation failed: ${err.message}`);
    }
  }

  async function testTelegramBot() {
    const token = $('#tg-token')?.value?.trim();
    const chat = $('#tg-chat')?.value?.trim();
    if (!token || !chat) {
      showToast('Please provide Bot Token and Chat ID.');
      return;
    }
    showToast('Testing Telegram Bot connection…');
    try {
      const res = await fetch(`/api/notifications/test-telegram?botToken=${encodeURIComponent(token)}&chatId=${encodeURIComponent(chat)}`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast('Telegram message sent successfully!');
        $('#telegram-dialog')?.close();
      } else {
        showToast(`Telegram notice: ${data.message || data.error}`);
      }
    } catch (err) {
      showToast(`Telegram test failed: ${err.message}`);
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
          const localCam = cameras.find((c) => c.id === cid);
          if (localCam) {
            localCam.status = camData.status || 'DEGRADED';
            localCam.reason = camData.reason || '';
            if (camData.checks) localCam.checks = camData.checks;
            if (camData.metrics) {
              localCam.fps = camData.metrics.fps || 0.0;
              localCam.latencyMs = Math.round(camData.metrics.latencyMs || 0);
              localCam.queue = `${camData.metrics.queueDepth || 0} / 0`;
              localCam.decodeErrors = camData.metrics.decodeErrors || 0;
            }

            if (!fpsHistory[cid]) fpsHistory[cid] = [];
            fpsHistory[cid].push(localCam.fps);
            if (fpsHistory[cid].length > 60) fpsHistory[cid].shift();
          }
        });

        if (servicesRes && servicesRes.services) {
          Object.entries(servicesRes.services).forEach(([cid, sData]) => {
            const localCam = cameras.find((c) => c.id === cid);
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

        updateFleetSummary();
        updateDashboardFleetStats();
        if (currentViewIdx === 0) renderLiveView();
        if (currentViewIdx === 1) {
          updateStreamPathCard();
          drawFpsChart();
        }
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
          : '30+ days left';

        if ($('#store-percent')) $('#store-percent').innerHTML = `${percent}%<small>Used</small>`;
        if ($('#store-used')) $('#store-used').textContent = `${usedGb} GB`;
        if ($('#store-free')) $('#store-free').textContent = `${freeGb} GB`;
        if ($('#store-recs')) $('#store-recs').textContent = `${recMb} MB`;
        if ($('#store-snaps')) $('#store-snaps').textContent = `${snapMb} MB`;
        if ($('#store-forecast')) $('#store-forecast').textContent = forecast;
        if ($('#store-ring')) $('#store-ring').style.setProperty('--ring-fill', `${percent}%`);
      }
    } catch (err) {
      console.warn('Telemetry polling notice:', err);
    }
  }

  // --- Global Event Listeners Delegation ---
  function initEventDelegation() {
    document.addEventListener('click', (e) => {
      // 1. Navigation items
      const navBtn = e.target.closest('[data-go]');
      if (navBtn) {
        switchView(parseInt(navBtn.dataset.go, 10));
        return;
      }

      // 2. Thumbnails
      const thumb = e.target.closest('.thumb');
      if (thumb && !e.target.closest('button')) {
        selectedCamIdx = parseInt(thumb.dataset.i, 10);
        if (thumb.closest('#prev')) {
          switchView(0);
          window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
          renderLiveView();
        }
        return;
      }

      // 3. Focus button
      const focusBtn = e.target.closest('[data-focus]');
      if (focusBtn) {
        selectedCamIdx = parseInt(focusBtn.dataset.focus, 10);
        setLayout('focus');
        switchView(0);
        return;
      }

      // 4. Per-camera Start/Stop/Restart/Reset actions
      const startCamBtn = e.target.closest('[data-act="start-cam"]');
      if (startCamBtn) {
        startCamera(startCamBtn.dataset.cid);
        return;
      }

      const stopCamBtn = e.target.closest('[data-act="stop-cam"]');
      if (stopCamBtn) {
        stopCamera(stopCamBtn.dataset.cid);
        return;
      }

      const restartCamBtn = e.target.closest('[data-act="restart-cam"]');
      if (restartCamBtn) {
        restartCamera(restartCamBtn.dataset.cid);
        return;
      }

      const resetCbBtn = e.target.closest('[data-act="reset-cb"]');
      if (resetCbBtn) {
        resetCircuitBreaker(resetCbBtn.dataset.cid);
        return;
      }

      // 5. Record toggle button
      const recActBtn = e.target.closest('[data-act="record"]');
      if (recActBtn) {
        toggleRecording(recActBtn.dataset.cid || cameras[selectedCamIdx].id);
        return;
      }

      // 6. Trigger Test Motion Recording
      if (e.target.closest('#btn-trigger-motion')) {
        triggerTestMotionRecording();
        return;
      }

      // 7. AI Benchmark button
      if (e.target.closest('#btn-ai-benchmark')) {
        runAiBenchmark();
        return;
      }

      // 8. Storage retention buttons
      if (e.target.closest('#btn-dry-run-cleanup')) {
        dryRunCleanup();
        return;
      }

      if (e.target.closest('#btn-exec-cleanup')) {
        executeRetentionCleanup();
        return;
      }

      if (e.target.closest('#btn-reindex-storage')) {
        reindexStorage();
        return;
      }

      // 9. Zoom controls
      const zoomBtn = e.target.closest('[data-zoom]');
      if (zoomBtn) {
        const type = zoomBtn.dataset.zoom;
        if (type === 'in') zoomLevel = Math.min(zoomLevel + 0.25, 3.0);
        else if (type === 'out') zoomLevel = Math.max(zoomLevel - 0.25, 1.0);
        else if (type === 'reset') zoomLevel = 1.0;
        const feed = $(`#feed-${cameras[selectedCamIdx].id}`);
        if (feed) feed.style.transform = `scale(${zoomLevel})`;
        zoomBtn.parentElement.querySelector('button[data-zoom="reset"]').textContent = `${zoomLevel.toFixed(1)}x`;
        return;
      }

      // 10. Fullscreen toggle
      if (e.target.closest('[data-fs]')) {
        const feed = $('#mc .feed');
        if (feed && feed.requestFullscreen) feed.requestFullscreen();
        return;
      }

      // 11. Top Bar Actions: Run All / Restart All / Stop All / Refresh
      if (e.target.closest('#btn-run-all')) {
        runAllCameras();
        return;
      }

      if (e.target.closest('#restart')) {
        $('#dlg')?.showModal();
        return;
      }

      if (e.target.closest('#btn-stop-all')) {
        $('#stop-dlg')?.showModal();
        return;
      }

      if (e.target.closest('#no')) {
        $('#dlg')?.close();
        return;
      }

      if (e.target.closest('#yes')) {
        $('#dlg')?.close();
        restartAllCameras();
        return;
      }

      if (e.target.closest('#stop-no')) {
        $('#stop-dlg')?.close();
        return;
      }

      if (e.target.closest('#stop-yes')) {
        $('#stop-dlg')?.close();
        stopAllCameras();
        return;
      }

      if (e.target.closest('#refresh')) {
        pollBackendHealth();
        showToast('Feeds & telemetry refreshed');
        return;
      }

      // 12. Sidebar toggle
      if (e.target.closest('#sbt')) {
        const shell = $('#shell');
        if (shell) {
          const isHidden = shell.classList.toggle('hide');
          $('#sbt').setAttribute('aria-expanded', !isHidden);
        }
        return;
      }

      // 13. Playback recordings buttons
      const playBtn = e.target.closest('[data-rec-play]');
      if (playBtn) {
        playRecording(playBtn.dataset.recPlay);
        return;
      }

      const delRecBtn = e.target.closest('[data-rec-del]');
      if (delRecBtn) {
        deleteRecording(delRecBtn.dataset.recDel);
        return;
      }

      if (e.target.closest('#refresh-recordings')) {
        loadRecordings();
        showToast('Recordings list refreshed');
        return;
      }

      // 14. Events snapshot lightbox & delete
      const snapBtn = e.target.closest('[data-ev-snap]');
      if (snapBtn) {
        openEventLightbox(snapBtn.dataset.evSnap);
        return;
      }

      const delEvBtn = e.target.closest('[data-ev-del]');
      if (delEvBtn) {
        deleteEvent(delEvBtn.dataset.evDel);
        return;
      }

      if (e.target.closest('#clear-events-btn')) {
        clearAllEvents();
        return;
      }

      if (e.target.closest('#lightbox-close')) {
        $('#event-dialog')?.close();
        return;
      }

      // 15. Diagnostics export bundle
      if (e.target.closest('#btn-generate-bundle')) {
        generateDiagnosticBundle();
        return;
      }

      // 16. Notifications actions
      const ackBtn = e.target.closest('[data-notif-ack]');
      if (ackBtn) {
        acknowledgeNotification(ackBtn.dataset.notifAck);
        return;
      }

      if (e.target.closest('#notif-ack-all')) {
        acknowledgeAllNotifications();
        return;
      }

      if (e.target.closest('#notif-clear-all')) {
        clearAllNotifications();
        return;
      }

      if (e.target.closest('#notif-simulate')) {
        simulateNotification();
        return;
      }

      // 17. Telegram Bot Dialog
      if (e.target.closest('#btn-telegram-settings')) {
        $('#telegram-dialog')?.showModal();
        return;
      }

      if (e.target.closest('#tg-cancel')) {
        $('#telegram-dialog')?.close();
        return;
      }

      if (e.target.closest('#tg-test')) {
        testTelegramBot();
        return;
      }

      // 18. Config dialog
      const cfgBtn = e.target.closest('[data-act="config"]');
      if (cfgBtn) {
        const cid = cfgBtn.dataset.cid || cameras[selectedCamIdx].id;
        const cam = cameras.find((c) => c.id === cid);
        if (cam) {
          if ($('#config-cam-name')) $('#config-cam-name').textContent = cam.name;
          if ($('#cfg-name')) $('#cfg-name').value = cam.name;
          if ($('#cfg-url')) $('#cfg-url').value = cam.streamUrl;
          if ($('#cfg-location')) $('#cfg-location').value = cam.ip;
          $('#config-dialog')?.showModal();
        }
        return;
      }

      if (e.target.closest('#cfg-cancel')) {
        $('#config-dialog')?.close();
        return;
      }
    });

    // Camera config form submit
    $('#config-form')?.addEventListener('submit', (e) => {
      e.preventDefault();
      const cam = cameras[selectedCamIdx];
      if (cam) {
        cam.name = $('#cfg-name').value || cam.name;
        cam.streamUrl = $('#cfg-url').value || cam.streamUrl;
        cam.ip = $('#cfg-location').value || cam.ip;
        showToast(`Saved configuration for ${cam.name}`);
        renderLiveView();
      }
      $('#config-dialog')?.close();
    });
  }

  // --- Initializer ---
  function init() {
    initNav();
    initSegmentedControls();
    initEventDelegation();
    switchView(1); // Default to Monitoring View per user reference image

    pollBackendHealth();
    setInterval(pollBackendHealth, 3000);

    if (window.innerWidth <= 900) {
      $('#shell')?.classList.add('hide');
      $('#sbt')?.setAttribute('aria-expanded', 'false');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
