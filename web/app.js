// CamHub Command Center - Core Frontend Application (v4.0)
// High-density tactical CCTV operations and telemetry console.

(function () {
  'use strict';

  // --- Core State & Camera Fleet Definition ---
  const cameras = [
    {
      id: 'v380-1',
      name: 'Camera 1, Indoor',
      shortName: 'Cam 1',
      ip: '192.168.100.24',
      port: 8080,
      streamUrl: 'http://127.0.0.1:8080/live.mjpg',
      status: 'DEGRADED',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      viewers: 1,
      aspect: '16:9',
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: 'None yet',
      recording: false,
      recordStartTime: null
    },
    {
      id: 'v380-2',
      name: 'Camera 2, Garage',
      shortName: 'Cam 2',
      ip: '192.168.100.4',
      port: 8081,
      streamUrl: 'http://127.0.0.1:8081/live.mjpg',
      status: 'DEGRADED',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      viewers: 1,
      aspect: '16:9',
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: 'None yet',
      recording: false,
      recordStartTime: null
    },
    {
      id: 'okam-3',
      name: 'Camera 3, O Kam Pro',
      shortName: 'Cam 3',
      ip: '192.168.100.6',
      port: 8082,
      streamUrl: 'http://127.0.0.1:8082/live.mjpg',
      status: 'DEGRADED',
      fps: 0.0,
      targetFps: 15.0,
      latencyMs: 0,
      viewers: 80,
      aspect: '16:9',
      queue: '0 / 0',
      decodeErrors: 0,
      lastFrame: 'None yet',
      recording: false,
      recordStartTime: null
    }
  ];

  const navItems = [
    { title: 'Live View', icon: 'i-live', id: 'v-live', lede: 'Watch every camera in one place. Select a camera to focus on it.' },
    { title: 'Dashboard', icon: 'i-grid', id: 'v-dash', lede: 'Real-time camera health, pipeline, and hardware performance.' },
    { title: 'Playback', icon: 'i-play', id: 'v-playback', lede: 'Play and export recorded video archives directly from local storage.' },
    { title: 'Events & AI', icon: 'i-spark', id: 'v-events', lede: 'Motion events and edge neural vision activity timeline.', badge: 0 },
    { title: 'Diagnostics', icon: 'i-pulse', id: 'v-diagnostics', lede: 'One-click diagnostics, port health checks, and log export bundle.' },
    { title: 'Notifications', icon: 'i-bell', id: 'v-notif', lede: 'System alerts, camera offline notices, and fault timeline.', badge: 0 },
    { title: 'Setup Guide', icon: 'i-book', id: 'v-setup', lede: 'Zero-cloud local camera bridge and hardware configuration.' }
  ];

  let currentViewIdx = 0;
  let selectedCamIdx = 0;
  let streamPathCamIdx = 0;
  let activeLayout = 'focus'; // 'focus' | 'wall'
  let zoomLevel = 1.0;
  let chartRange = '1m';
  let eventFilterCid = '';
  let notifFilterSev = '';
  let fpsHistory = {
    'v380-1': [],
    'v380-2': [],
    'okam-3': []
  };

  // Helper DOM selector
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
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    if (m === 0) return `${s}s`;
    return `${m}m ${s}s`;
  }

  function formatTime(isoStrOrMs) {
    if (!isoStrOrMs) return '--:--:--';
    const d = new Date(isoStrOrMs);
    if (isNaN(d.getTime())) return '--:--:--';
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
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

  // --- Clock & OSD Timestamp Tick ---
  function updateTimestamps() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const timeStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    $$('.ts').forEach((el) => {
      el.textContent = timeStr;
    });

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

    // Update nav active states
    $$('#nav button').forEach((b, k) => {
      if (k === idx) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });

    // Toggle views visibility
    navItems.forEach((item, k) => {
      const v = $(`#${item.id}`);
      if (v) v.hidden = k !== idx;
    });

    // Update Bar Title & Lede
    const activeItem = navItems[idx];
    if ($('#title')) $('#title').textContent = activeItem.title;
    if ($('#lede')) {
      $('#lede').textContent = activeItem.lede;
      $('#lede').hidden = idx === 1; // Le de hidden on dashboard to save space
    }

    // Refresh view specific data
    if (idx === 0) renderLiveView();
    if (idx === 1) renderDashboard();
    if (idx === 2) loadRecordings();
    if (idx === 3) loadEvents();
    if (idx === 4) loadDiagnostics();
    if (idx === 5) loadNotifications();

    if (window.innerWidth <= 900) {
      const shell = $('#shell');
      if (shell) shell.classList.add('hide');
    }
  }

  // --- Segmented Controls ---
  function initSegmentedControls() {
    // Layout switcher (Focus / Wall)
    $('#layouts')?.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      const l = btn.dataset.l;
      setLayout(l);
    });

    // Stream Path Camera Picker
    $('#pick')?.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      streamPathCamIdx = parseInt(btn.dataset.i, 10);
      $$('#pick button').forEach((b) => b.setAttribute('aria-pressed', b === btn));
      updateStreamPathCard();
    });

    // Chart Range Picker
    $('#range')?.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      chartRange = btn.dataset.range || '1m';
      $$('#range button').forEach((b) => b.setAttribute('aria-pressed', b === btn));
      drawFpsChart();
    });

    // Events Camera Filter
    $('#events-cam-filter')?.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      eventFilterCid = btn.dataset.cid || '';
      $$('#events-cam-filter button').forEach((b) => b.setAttribute('aria-pressed', b === btn));
      renderEventsList();
    });

    // Notifications Severity Filter
    $('#notif-sev-filter')?.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      notifFilterSev = btn.dataset.sev || '';
      $$('#notif-sev-filter button').forEach((b) => b.setAttribute('aria-pressed', b === btn));
      renderNotificationsList();
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

    const mainCamHtml = `
      <div class="card main-cam" id="mc">
        ${getCameraFeedHtml(cam, true, selectedCamIdx)}
        <div class="meta">
          <div>
            <b>${escapeHtml(cam.name)}</b>
            <div class="ip">${cam.ip} · Port ${cam.port}</div>
          </div>
          <div class="stats">
            <div><b>${cam.fps.toFixed(1)}</b><span>Frame rate</span></div>
            <div><b>${cam.latencyMs} ms</b><span>Latency</span></div>
            <div><b>${cam.aspect}</b><span>Aspect</span></div>
            <div><b>${cam.viewers}</b><span>Viewers</span></div>
          </div>
          <div class="acts">
            <button class="btn ${cam.recording ? 'dng' : ''}" data-act="record" data-cid="${cam.id}">
              <svg class="ico"><use href="#i-play"/></svg>
              <span>${cam.recording ? 'Stop Record' : 'Record'}</span>
            </button>
            <button class="btn" data-act="reload" data-cid="${cam.id}">
              <svg class="ico"><use href="#i-re"/></svg>
              <span>Reload</span>
            </button>
            <button class="btn" data-act="config" data-cid="${cam.id}">
              <svg class="ico"><use href="#i-gear"/></svg>
              <span>Configure</span>
            </button>
          </div>
        </div>
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
            <button class="btn ${cam.recording ? 'dng' : ''}" data-act="record" data-cid="${cam.id}">
              ${cam.recording ? 'Stop' : 'Record'}
            </button>
            <button class="btn" data-act="reload" data-cid="${cam.id}">Reload</button>
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

  // --- Dashboard Components & Real-time Chart ---
  function renderDashboard() {
    // 1. Live Preview Thumbnails
    const prev = $('#prev');
    if (prev) {
      prev.innerHTML = cameras
        .map(
          (c, i) => `
        <button class="thumb" data-i="${i}" aria-pressed="false" aria-label="${escapeHtml(c.name)}">
          ${getCameraFeedHtml(c, false, i)}
          <div class="tl">
            <span>${escapeHtml(c.name)}</span>
            <span class="${c.status === 'HEALTHY' ? 'good-t' : 'warn-t'}"><i class="dot"></i>${c.status}</span>
          </div>
        </button>
      `
        )
        .join('');
    }

    // 2. Stream Path Camera Selector
    const pick = $('#pick');
    if (pick && pick.children.length === 0) {
      pick.innerHTML = cameras
        .map((c, i) => `<button aria-pressed="${i === streamPathCamIdx}" data-i="${i}">Camera ${i + 1}</button>`)
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

  function updateStreamPathCard() {
    const cam = cameras[streamPathCamIdx] || cameras[0];
    if ($('#pc')) $('#pc').textContent = `Camera ${streamPathCamIdx + 1}`;

    const isDegraded = cam.status === 'DEGRADED' || cam.fps === 0;
    const flow = $('#flow');
    if (flow) {
      const nodes = [
        { label: 'Camera', status: isDegraded ? 'No frames' : 'OK', bad: isDegraded },
        { label: 'Network', status: isDegraded ? 'Waiting' : 'Connected', bad: false },
        { label: 'Decoder', status: isDegraded ? 'Idle' : 'Active', bad: false },
        { label: 'Stream', status: isDegraded ? 'Degraded' : 'Active', bad: false },
        { label: 'Browser', status: 'Rendering', bad: false }
      ];

      flow.innerHTML = nodes
        .map(
          (n, i) => `
        ${i ? '<svg class="ico"><use href="#i-arrow"/></svg>' : ''}
        <div class="node ${n.bad ? 'bad' : ''}">
          <b>${n.label}</b>
          <span>${n.status}</span>
        </div>
      `
        )
        .join('');
    }

    const noteTitle = $('#path-note-title');
    const noteMsg = $('#path-note-msg');
    if (noteTitle && noteMsg) {
      if (isDegraded) {
        noteTitle.textContent = 'Camera Source Is Silent';
        noteMsg.textContent = `No frames received from ${cam.name.split(',')[0]} (${cam.ip}). Check that it is powered on and reachable on the local network, then retry.`;
      } else {
        noteTitle.textContent = 'All Pipeline Nodes Operating';
        noteMsg.textContent = `${cam.name} stream packets are being ingested, decoded, and rendered with 0 decode errors.`;
      }
    }

    if ($('#dl-last-frame')) $('#dl-last-frame').textContent = cam.lastFrame;
    if ($('#dl-queue')) $('#dl-queue').textContent = cam.queue;
    if ($('#dl-errors')) $('#dl-errors').textContent = `${cam.decodeErrors}`;
    if ($('#dl-port')) $('#dl-port').textContent = `${cam.port}`;
  }

  // --- Real-time Canvas Frame Rate Chart ---
  function drawFpsChart() {
    const canvas = $('#fps-chart-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);

    // Draw grid lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.lineWidth = 1;
    for (let y = 20; y < height - 10; y += 30) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    // Colors per camera: Cam 1 = yellow (#f2b84b), Cam 2 = cyan (#5aa2ff), Cam 3 = pink (#ff6a99)
    const seriesColors = ['#f2b84b', '#5aa2ff', '#ff6a99'];
    const maxFps = 25.0;

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
    });

    // Baseline axis
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
    ctx.beginPath();
    ctx.moveTo(0, height - 10);
    ctx.lineTo(width, height - 10);
    ctx.stroke();
  }

  // --- Playback Module ---
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
          showToast(`Recording error: ${data.message || 'Decoder is offline'}`);
        }
      } catch (err) {
        showToast(`Failed to start recording: ${err.message}`);
      }
    } else {
      try {
        const res = await fetch('/api/recordings/stop', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ camera_id: cid })
        });
        const data = await res.json();
        cam.recording = false;
        cam.recordStartTime = null;
        showToast(`Stopped recording on ${cam.shortName}`);
        setTimeout(loadRecordings, 1500);
      } catch (err) {
        showToast(`Failed to stop recording: ${err.message}`);
      }
    }

    renderManualRecordingControls();
    if (activeLayout === 'focus') renderFocusStage();
    else renderWallGrid();
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
    if (!confirm('Permanently delete this recording archive?')) return;
    try {
      const res = await fetch(`/api/recordings?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (res.ok) {
        showToast('Recording deleted');
        loadRecordings();
      } else {
        const data = await res.json();
        showToast(`Delete failed: ${data.message}`);
      }
    } catch (err) {
      showToast(`Delete failed: ${err.message}`);
    }
  }

  // --- Events & AI Module ---
  let eventsCache = [];

  async function loadEvents() {
    const list = $('#events-list');
    if (!list) return;

    try {
      const res = await fetch('/api/events');
      const data = await res.json();
      eventsCache = data.events || [];
      renderEventsList();

      // Update badge in sidebar
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
    try {
      const res = await fetch(`/api/events?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (res.ok) {
        eventsCache = eventsCache.filter((e) => e.id !== id);
        renderEventsList();
        showToast('Event removed');
      }
    } catch (err) {
      showToast(`Failed to delete event: ${err.message}`);
    }
  }

  async function clearAllEvents() {
    if (!confirm('Clear all motion and AI detection events?')) return;
    try {
      const res = await fetch('/api/events', { method: 'DELETE' });
      if (res.ok) {
        eventsCache = [];
        renderEventsList();
        showToast('All events cleared');
      }
    } catch (err) {
      showToast(`Failed to clear events: ${err.message}`);
    }
  }

  function loadDashboardRecentEvents() {
    const container = $('#dash-recent-events');
    if (!container) return;

    if (eventsCache.length === 0) {
      container.innerHTML = `
        <div class="empty"><b>No Activity Yet</b><p>Motion and AI detections from your cameras will appear here.</p></div>
      `;
      return;
    }

    const recent = eventsCache.slice(0, 4);
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

  // --- Diagnostics Module ---
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
    } catch (err) {
      console.error('Diagnostics load error:', err);
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
    const prog = $('#bundle-progress');
    const btn = $('#btn-generate-bundle');
    if (prog) prog.style.display = 'block';
    if (btn) btn.disabled = true;

    try {
      const res = await fetch('/api/diagnostics/generate', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        showToast('Diagnostic bundle generated!');
        loadDiagnostics();
      } else {
        showToast(`Bundle error: ${data.message}`);
      }
    } catch (err) {
      showToast(`Export failed: ${err.message}`);
    } finally {
      if (prog) prog.style.display = 'none';
      if (btn) btn.disabled = false;
    }
  }

  // --- Notifications Center Module ---
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
          message: 'Frame rate dropped below 5 fps threshold (Simulated test).'
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

  // --- Restart Services Modal ---
  async function restartAllCameras() {
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
      showToast(`Restart failed: ${err.message}`);
    }
  }

  // --- Background Polling Loop ---
  async function pollBackendHealth() {
    try {
      const [healthRes, storageRes] = await Promise.all([
        fetch('/api/health').then((r) => (r.ok ? r.json() : null)),
        fetch('/api/storage/status').then((r) => (r.ok ? r.json() : null))
      ]);

      if (healthRes && healthRes.cameras) {
        Object.entries(healthRes.cameras).forEach(([cid, camData]) => {
          const localCam = cameras.find((c) => c.id === cid);
          if (localCam) {
            localCam.status = camData.status || 'DEGRADED';
            if (camData.metrics) {
              localCam.fps = camData.metrics.fps || 0.0;
              localCam.latencyMs = Math.round(camData.metrics.latencyMs || 0);
              localCam.queue = `${camData.metrics.queueDepth || 0} / 0`;
              localCam.decodeErrors = camData.metrics.decodeErrors || 0;
            }

            // Record FPS history for Canvas chart
            if (!fpsHistory[cid]) fpsHistory[cid] = [];
            fpsHistory[cid].push(localCam.fps);
            if (fpsHistory[cid].length > 60) fpsHistory[cid].shift();
          }
        });

        // Update Host resources & throughput
        if (healthRes.system) {
          const cpu = Math.round(healthRes.system.cpu_percent || 28);
          const mem = Math.round(healthRes.system.memory?.percent || 52);
          if ($('#res-cpu-val')) $('#res-cpu-val').textContent = `${cpu}%`;
          if ($('#res-cpu-bar')) $('#res-cpu-bar').style.setProperty('--w', `${cpu}%`);
          if ($('#res-mem-val')) $('#res-mem-val').textContent = `8.3 of 16.0 GB (${mem}%)`;
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

      // Storage Telemetry
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

  // --- Global Event Listeners ---
  function initEventDelegation() {
    document.addEventListener('click', (e) => {
      // 1. Navigation item clicked
      const navBtn = e.target.closest('[data-go]');
      if (navBtn) {
        switchView(parseInt(navBtn.dataset.go, 10));
        return;
      }

      // 2. Thumbnail clicked in Live Stage side or Dashboard Preview
      const thumb = e.target.closest('.thumb');
      if (thumb) {
        selectedCamIdx = parseInt(thumb.dataset.i, 10);
        renderLiveView();
        if (thumb.closest('#prev')) {
          switchView(0);
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        return;
      }

      // 3. Focus button in Wall mode
      const focusBtn = e.target.closest('[data-focus]');
      if (focusBtn) {
        selectedCamIdx = parseInt(focusBtn.dataset.focus, 10);
        setLayout('focus');
        return;
      }

      // 4. Record action button
      const recActBtn = e.target.closest('[data-act="record"]');
      if (recActBtn) {
        const cid = recActBtn.dataset.cid || cameras[selectedCamIdx].id;
        toggleRecording(cid);
        return;
      }

      // 5. Reload stream button
      const reloadBtn = e.target.closest('[data-act="reload"]');
      if (reloadBtn) {
        const cid = reloadBtn.dataset.cid || cameras[selectedCamIdx].id;
        const img = $(`#stream-img-${cid}`);
        if (img) img.src = `${img.src.split('?')[0]}?t=${Date.now()}`;
        showToast('Stream reloaded');
        return;
      }

      // 6. Configure camera button
      const cfgBtn = e.target.closest('[data-act="config"]');
      if (cfgBtn) {
        const cid = cfgBtn.dataset.cid || cameras[selectedCamIdx].id;
        const cam = cameras.find((c) => c.id === cid);
        if (cam) {
          if ($('#config-cam-name')) $('#config-cam-name').textContent = cam.name;
          if ($('#cfg-name')) $('#cfg-name').value = cam.name;
          if ($('#cfg-url')) $('#cfg-url').value = cam.streamUrl;
          if ($('#cfg-location')) $('#cfg-location').value = cam.ip;
          const dlg = $('#config-dialog');
          if (dlg) dlg.showModal();
        }
        return;
      }

      // 7. Zoom controls
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

      // 8. Fullscreen toggle
      if (e.target.closest('[data-fs]')) {
        const feed = $('#mc .feed');
        if (feed && feed.requestFullscreen) feed.requestFullscreen();
        return;
      }

      // 9. Open Live view button from Dashboard
      if (e.target.closest('#openlive')) {
        switchView(0);
        return;
      }

      // 10. Toolbar action buttons
      if (e.target.closest('#refresh')) {
        pollBackendHealth();
        showToast('Feeds & telemetry refreshed');
        return;
      }

      if (e.target.closest('#restart')) {
        const dlg = $('#dlg');
        if (dlg) dlg.showModal();
        return;
      }

      if (e.target.closest('#no')) {
        const dlg = $('#dlg');
        if (dlg) dlg.close();
        return;
      }

      if (e.target.closest('#yes')) {
        const dlg = $('#dlg');
        if (dlg) dlg.close();
        restartAllCameras();
        return;
      }

      // 11. Sidebar toggle button
      if (e.target.closest('#sbt')) {
        const shell = $('#shell');
        if (shell) {
          const isHidden = shell.classList.toggle('hide');
          $('#sbt').setAttribute('aria-expanded', !isHidden);
        }
        return;
      }

      // 12. Playback play/del buttons
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

      // 13. Events snapshot lightbox & delete
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
        const dlg = $('#event-dialog');
        if (dlg) dlg.close();
        return;
      }

      // 14. Diagnostics actions
      if (e.target.closest('#btn-generate-bundle')) {
        generateDiagnosticBundle();
        return;
      }

      // 15. Notifications actions
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

      // 16. Config dialog actions
      if (e.target.closest('#cfg-cancel')) {
        const dlg = $('#config-dialog');
        if (dlg) dlg.close();
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
    renderLiveView();
    switchView(0);

    // Initial telemetry pull and polling interval
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
