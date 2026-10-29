const defaultHost = (typeof window !== "undefined" && window.location && window.location.hostname) ? window.location.hostname : "127.0.0.1";

const DEFAULT_CAMERAS = [
  {
    id: "v380-1",
    name: "Camera 1 · Indoor",
    location: "192.168.100.24 · ID 124095217 · Port 8080",
    brand: "V380 Pro / V380Decoder-Latest",
    url: `http://${defaultHost}:8080/stream.mjpg`,
    snapshotUrl: `http://${defaultHost}:8080/snapshot`,
    metricsUrl: `http://${defaultHost}:8080/api/metrics`,
    hint: "LAN"
  },
  {
    id: "v380-2",
    name: "Camera 2 · Garage",
    location: "192.168.100.4 · ID 97357757 · Port 8081",
    brand: "V380 Pro / V380Decoder-Fork",
    url: `http://${defaultHost}:8081/stream.mjpg`,
    snapshotUrl: `http://${defaultHost}:8081/snapshot`,
    metricsUrl: `http://${defaultHost}:8081/api/metrics`,
    hint: "LAN"
  },
  {
    id: "okam-3",
    name: "Camera 3 · O Kam Pro",
    location: "192.168.100.6 · Port 10554 · VStarcam",
    brand: "O Kam Pro / VStarcam",
    url: `http://${defaultHost}:8082/stream.mjpg`,
    snapshotUrl: `http://${defaultHost}:8082/snapshot`,
    metricsUrl: `http://${defaultHost}:8082/api/metrics`,
    hint: "LAN RTSP"
  }
];

const STORAGE_KEY = "camhub.control.cameras.v3";
const PREV_KEYS = ["camhub.control.cameras.v2", "camhub.control.cameras.v1", "camhub.mvp.cameras.v3", "camhub.mvp.cameras.v2", "camhub.mvp.cameras.v1"];
const SELECTED_CAMERAS_KEY = "camhub.selected_cameras.v1";

let cameras = loadCameras();

function getSelectedCameraIds() {
  try {
    const raw = localStorage.getItem(SELECTED_CAMERAS_KEY);
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr) && arr.length > 0) {
        return new Set(arr);
      }
    }
  } catch {}
  return new Set(cameras.map((c) => c.id));
}

let selectedCameraIds = getSelectedCameraIds();

function saveSelectedCameraIds() {
  try {
    localStorage.setItem(SELECTED_CAMERAS_KEY, JSON.stringify(Array.from(selectedCameraIds)));
  } catch {}
}

function isCameraSelected(id) {
  return selectedCameraIds.has(id);
}

function stopStream(id) {
  clearWatchdog(id);
  const img = document.querySelector(`[data-feed="${CSS.escape(id)}"]`);
  if (img) {
    img.onload = null;
    img.onerror = null;
    img.removeAttribute("src");
  }
}

const connectionStates = new Map();
const watchdogs = new Map();
const metricsData = new Map();
const metricsHistory = new Map();

const grid = document.querySelector("#camera-grid");
const dialog = document.querySelector("#config-dialog");
const configForm = document.querySelector("#config-form");
const closeDialogBtn = document.querySelector("#close-dialog-btn");
const cancelDialogBtn = document.querySelector("#cancel-dialog-btn");
const analyticsCards = document.querySelector("#analytics-cards");

function getFormattedTime() {
  return new Intl.DateTimeFormat([], {
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date());
}

function deriveMetricsUrl(streamUrl) {
  if (!streamUrl) return "";
  try {
    const u = new URL(streamUrl);
    return `${u.protocol}//${u.host}/api/metrics`;
  } catch {
    return "";
  }
}

function loadCameras() {
  try {
    let raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      for (const k of PREV_KEYS) {
        raw = localStorage.getItem(k);
        if (raw) break;
      }
    }
    if (raw) {
      const saved = JSON.parse(raw);
      if (Array.isArray(saved)) {
        return DEFAULT_CAMERAS.map((def, idx) => {
          const legacyId = ["v380-a", "v380-b", "okam-c"][idx];
          const matched = saved.find(item => item.id === def.id || item.id === legacyId);
          if (matched) {
            const isGenericDefault = !matched.location || matched.location.includes("Point") || matched.location.includes("Local network");
            let url = matched.url !== undefined && matched.url !== "" ? matched.url : def.url;
            let snapshotUrl = matched.snapshotUrl !== undefined && matched.snapshotUrl !== "" ? matched.snapshotUrl : def.snapshotUrl;
            if (url && url.includes("192.168.100.11") && defaultHost !== "192.168.100.11") {
              url = url.replace("192.168.100.11", defaultHost);
            }
            if (snapshotUrl && snapshotUrl.includes("192.168.100.11") && defaultHost !== "192.168.100.11") {
              snapshotUrl = snapshotUrl.replace("192.168.100.11", defaultHost);
            }
            return {
              ...def,
              ...matched,
              id: def.id,
              name: matched.name || def.name,
              location: isGenericDefault ? def.location : matched.location,
              brand: isGenericDefault ? def.brand : (matched.brand || def.brand),
              url: url,
              snapshotUrl: snapshotUrl,
              metricsUrl: deriveMetricsUrl(url),
              hint: def.hint
            };
          }
          return { ...def };
        });
      }
    }
  } catch (error) {
    console.warn("CamHub config could not be loaded; using defaults.", error);
  }
  return DEFAULT_CAMERAS.map((camera) => ({ ...camera }));
}

function saveCameras() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(cameras));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[char]);
}

function clearWatchdog(id) {
  if (watchdogs.has(id)) {
    clearTimeout(watchdogs.get(id));
    watchdogs.delete(id);
  }
}

function setConnection(id, status, message = "") {
  connectionStates.set(id, { status, message, timestamp: Date.now() });

  const card = document.querySelector(`[data-camera="${CSS.escape(id)}"]`);
  if (!card) {
    updateSummary();
    return;
  }

  const dot = card.querySelector(`[data-dot="${CSS.escape(id)}"]`);
  const statusText = card.querySelector(`[data-status-text="${CSS.escape(id)}"]`);
  const micro = card.querySelector(`[data-micro="${CSS.escape(id)}"]`);
  const feed = card.querySelector(`[data-feed="${CSS.escape(id)}"]`);
  const placeholder = card.querySelector(`[data-placeholder="${CSS.escape(id)}"]`);
  const placeholderMsg = card.querySelector(`[data-placeholder-message="${CSS.escape(id)}"]`);
  const retryBtn = card.querySelector(`[data-retry-btn="${CSS.escape(id)}"]`);
  const configBtnInPlaceholder = card.querySelector(`[data-placeholder-config="${CSS.escape(id)}"]`);

  let word = "Offline";
  if (status === "online") word = "Live";
  else if (status === "connecting") word = "Connecting";
  else if (status === "unconfigured") word = "Not configured";

  if (dot) {
    dot.className = `status-dot ${status}`;
  }
  if (statusText) {
    statusText.textContent = word;
  }
  if (micro && status === "online") {
    micro.textContent = getFormattedTime();
  }

  if (feed) {
    feed.classList.toggle("is-hidden", status !== "online");
  }

  if (placeholder) {
    placeholder.classList.toggle("is-hidden", status === "online");
    if (placeholderMsg) {
      if (status === "connecting") {
        placeholderMsg.textContent = "Connecting to camera stream…";
      } else if (status === "offline") {
        placeholderMsg.textContent = message || "Stream unavailable. Verify local decoder is active.";
      } else if (status === "unconfigured") {
        placeholderMsg.textContent = "Protocol adapter not configured.";
      }
    }
    if (retryBtn) {
      retryBtn.style.display = status === "offline" ? "inline-flex" : "none";
    }
    if (configBtnInPlaceholder) {
      configBtnInPlaceholder.style.display = status === "unconfigured" ? "inline-flex" : "none";
    }
  }

  updateSummary();
}

function updateSummary() {
  const visibleCameras = cameras.filter((c) => isCameraSelected(c.id));
  const onlineCount = visibleCameras.filter((camera) => connectionStates.get(camera.id)?.status === "online").length;
  const sentenceEl = document.querySelector("#status-sentence");
  const navCountEl = document.querySelector("#nav-camera-count");
  const timeStr = getFormattedTime();

  if (sentenceEl) {
    if (visibleCameras.length < cameras.length) {
      sentenceEl.textContent = `${onlineCount} of ${visibleCameras.length} displayed cameras connected (${visibleCameras.length}/${cameras.length} visible). Checked ${timeStr}.`;
    } else {
      sentenceEl.textContent = `${onlineCount} of ${cameras.length} cameras connected. Checked ${timeStr}.`;
    }
  }
  if (navCountEl) {
    navCountEl.textContent = visibleCameras.length < cameras.length ? `${visibleCameras.length}/${cameras.length}` : String(cameras.length);
  }
}

function startStream(id) {
  const camera = cameras.find((item) => item.id === id);
  if (!camera) return;

  clearWatchdog(id);

  if (!camera.url) {
    setConnection(id, "unconfigured", "Protocol adapter not configured.");
    return;
  }

  setConnection(id, "connecting");

  const img = document.querySelector(`[data-feed="${CSS.escape(id)}"]`);
  if (!img) return;

  img.onload = null;
  img.onerror = null;

  // Watchdog timer (8s)
  const timer = setTimeout(() => {
    if (connectionStates.get(id)?.status === "connecting") {
      setConnection(id, "offline", "Connection timed out (8s). No frames received from decoder.");
    }
  }, 8000);
  watchdogs.set(id, timer);

  img.onload = () => {
    clearWatchdog(id);
    setConnection(id, "online");

    // Dynamic stream ratio adjustment
    if (img.naturalWidth && img.naturalHeight) {
      const wrap = img.closest(".video-container");
      if (wrap) {
        wrap.style.setProperty("--stream-ratio", `${img.naturalWidth} / ${img.naturalHeight}`);
      }
      const badge = document.querySelector(`[data-ratio="${CSS.escape(id)}"]`);
      if (badge) {
        badge.textContent = `${img.naturalWidth} × ${img.naturalHeight}`;
        badge.style.display = "inline-block";
      }
      const tileRes = document.querySelector(`[data-telemetry-res="${CSS.escape(id)}"]`);
      if (tileRes) {
        tileRes.textContent = `${img.naturalWidth}×${img.naturalHeight}`;
      }
    }
  };

  img.onerror = () => {
    clearWatchdog(id);
    const portMatch = camera.url.match(/:(\d+)/);
    const portNote = portMatch ? `port :${portMatch[1]}` : "stream URL";
    setConnection(id, "offline", `Connection failed on ${portNote}. Verify decoder is running.`);
  };

  const cacheBuster = `camhub_t=${Date.now()}`;
  const sep = camera.url.includes("?") ? "&" : "?";
  img.src = `${camera.url}${sep}${cacheBuster}`;
}

function render() {
  const timeStr = getFormattedTime();

  const visibleCameras = cameras.filter((camera) => isCameraSelected(camera.id));

  if (visibleCameras.length === 0) {
    grid.innerHTML = `
      <div class="no-cameras-selected">
        <div class="no-cam-icon">📹</div>
        <h3 class="no-cam-title">No cameras selected</h3>
        <p class="no-cam-desc">All camera feeds are currently hidden. Choose one or more cameras using the selection bar above to display them.</p>
        <button class="button button-accent button-small" id="empty-state-show-all" type="button">Show all cameras</button>
      </div>`;
    const emptyBtn = document.getElementById("empty-state-show-all");
    if (emptyBtn) {
      emptyBtn.onclick = () => selectAllCameras(true);
    }
  } else {
    grid.innerHTML = visibleCameras.map((camera) => {
      const isUnconfigured = !camera.url;
      const stateObj = connectionStates.get(camera.id);
      const status = stateObj?.status || (camera.url ? "connecting" : "unconfigured");
      const statusClass = status;
      const statusWord = status === "online" ? "Live" : status === "connecting" ? "Connecting" : status === "offline" ? "Offline" : "Not configured";
      const placeholderMsg = stateObj?.message || (status === "connecting" ? "Connecting to camera stream…" : status === "offline" ? "Stream unavailable. Verify local decoder is active." : "Protocol adapter not configured.");

      // Read current health status
      const h = cameraHealthData.get(camera.id);
      const healthStatus = (h?.status || "UNKNOWN").toLowerCase();
      const healthUpper = h?.status || "UNKNOWN";

      return `
        <article class="camera-card ${isUnconfigured ? 'is-unconfigured' : ''}" data-camera="${escapeHtml(camera.id)}">
          <div class="video-container" data-video-wrap="${escapeHtml(camera.id)}">
            <div class="tile-scrim">
              <div class="tile-status-bar">
                <div class="tile-title-group">
                  <span class="status-dot ${statusClass}" data-dot="${escapeHtml(camera.id)}"></span>
                  <h3 class="tile-title">${escapeHtml(camera.name)}</h3>
                  <span class="status-text" data-status-text="${escapeHtml(camera.id)}">${statusWord}</span>
                  <span class="health-tile-badge ${healthStatus}" data-tile-health="${escapeHtml(camera.id)}">${healthUpper}</span>
                </div>
                <div class="tile-micro-group">
                  <span class="ratio-badge" data-ratio="${escapeHtml(camera.id)}" style="display:none;"></span>
                  <span class="tile-micro" data-micro="${escapeHtml(camera.id)}">${timeStr}</span>
                </div>
              </div>
            </div>

            <!-- Floating CCTV Zoom Bar -->
            <div class="tile-zoom-bar" data-zoom-bar="${escapeHtml(camera.id)}">
              <button class="tile-zoom-btn" data-zoom-in="${escapeHtml(camera.id)}" type="button" title="Zoom in (+)">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
              </button>
              <button class="tile-zoom-btn zoom-level-badge" data-zoom-reset="${escapeHtml(camera.id)}" type="button" title="Click to reset zoom (1.0x)">
                <span data-zoom-val="${escapeHtml(camera.id)}">1.0x</span>
              </button>
              <button class="tile-zoom-btn" data-zoom-out="${escapeHtml(camera.id)}" type="button" title="Zoom out (-)">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"></line></svg>
              </button>
              <button class="tile-zoom-btn" data-zoom-fullscreen="${escapeHtml(camera.id)}" type="button" title="Toggle fullscreen">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>
              </button>
            </div>

            <img
              class="camera-feed ${status === 'online' ? '' : 'is-hidden'}"
              data-feed="${escapeHtml(camera.id)}"
              alt="Live feed: ${escapeHtml(camera.name)}"
            />

            <div class="feed-placeholder ${status === 'online' ? 'is-hidden' : ''}" data-placeholder="${escapeHtml(camera.id)}">
              <div class="placeholder-content">
                <p class="placeholder-message" data-placeholder-message="${escapeHtml(camera.id)}">${escapeHtml(placeholderMsg)}</p>
                ${isUnconfigured
                  ? `<button class="button button-accent button-small" data-placeholder-config="${escapeHtml(camera.id)}" type="button">Set up protocol</button>`
                  : `<button class="button button-small" data-retry-btn="${escapeHtml(camera.id)}" type="button" style="${status === 'offline' ? 'display:inline-flex;' : 'display:none;'}">Retry connection</button>`
                }
              </div>
            </div>
          </div>

          <div class="tile-footer">
            <div class="tile-footer-top">
              <div class="tile-details">
                <span class="details-text" title="${escapeHtml(camera.location)}">${escapeHtml(camera.location)}</span>
              </div>
              <div class="tile-actions">
                <button class="button button-small" data-refresh="${escapeHtml(camera.id)}" type="button" title="Reload feed">Reload</button>
                <button class="button button-small" data-configure="${escapeHtml(camera.id)}" type="button" title="Configure camera">Configure</button>
                <button class="button button-small button-focus" data-focus="${escapeHtml(camera.id)}" type="button" title="Expand to full row">Focus</button>
              </div>
            </div>
            <div class="tile-telemetry" data-tile-telemetry="${escapeHtml(camera.id)}">
              <span class="telemetry-item">FPS: <span class="telemetry-val live" data-telemetry-fps="${escapeHtml(camera.id)}">—</span></span>
              <span>·</span>
              <span class="telemetry-item">Latency: <span class="telemetry-val accent" data-telemetry-lat="${escapeHtml(camera.id)}">—</span></span>
              <span>·</span>
              <span class="telemetry-item">Ratio: <span class="telemetry-val" data-telemetry-res="${escapeHtml(camera.id)}">—</span></span>
              <span>·</span>
              <span class="telemetry-item">Clients: <span class="telemetry-val" data-telemetry-clients="${escapeHtml(camera.id)}">—</span></span>
            </div>
          </div>
        </article>`;
    }).join("");
  }

  renderAnalyticsCards();
  updateSummary();
  attachEvents();

  cameras.forEach((camera) => {
    if (isCameraSelected(camera.id)) {
      startStream(camera.id);
    } else {
      stopStream(camera.id);
    }
  });
}

const clientRenderMetrics = new Map();

function trackClientRender(id) {
  const now = performance.now();
  let m = clientRenderMetrics.get(id);
  if (!m) {
    m = { frames: [], fps: 0 };
    clientRenderMetrics.set(id, m);
  }
  m.frames.push(now);
  while (m.frames.length > 0 && m.frames[0] < now - 2000) {
    m.frames.shift();
  }
  if (m.frames.length >= 2) {
    const durSec = (m.frames[m.frames.length - 1] - m.frames[0]) / 1000;
    if (durSec > 0) {
      m.fps = Math.round(((m.frames.length - 1) / durSec) * 10) / 10;
    }
  }
}

function renderAnalyticsCards() {
  if (!analyticsCards) return;

  analyticsCards.innerHTML = cameras.map((camera) => {
    const isUnconfigured = !camera.url;
    return `
      <article class="metric-card" data-metric-card="${escapeHtml(camera.id)}">
        <div class="metric-card-head">
          <div class="metric-card-title">
            <span class="status-dot ${isUnconfigured ? 'unconfigured' : 'connecting'}" data-metric-dot="${escapeHtml(camera.id)}"></span>
            ${escapeHtml(camera.name)}
          </div>
          <div style="display:flex; align-items:center; gap:6px;">
            <span class="health-badge-pill" data-health-badge="${escapeHtml(camera.id)}">UNKNOWN</span>
            <span class="metric-card-chip">${escapeHtml(camera.hint || 'LAN')}</span>
          </div>
        </div>

        <!-- Pipeline Stage Flow -->
        <div class="pipeline-section">
          <div class="pipeline-title">Pipeline Stage Flow</div>
          <div class="pipeline-flow" data-pipeline-flow="${escapeHtml(camera.id)}">
            <div class="stage-step">
              <span class="stage-name">Target</span>
              <span class="stage-fps" data-stage-target="${escapeHtml(camera.id)}">15.0 fps</span>
            </div>
            <span class="stage-arrow">→</span>
            <div class="stage-step">
              <span class="stage-name">LAN Ingest</span>
              <span class="stage-fps live" data-stage-source="${escapeHtml(camera.id)}">— fps</span>
            </div>
            <span class="stage-arrow">→</span>
            <div class="stage-step">
              <span class="stage-name">Decoder</span>
              <span class="stage-fps live" data-stage-decoder="${escapeHtml(camera.id)}">— fps</span>
            </div>
            <span class="stage-arrow">→</span>
            <div class="stage-step">
              <span class="stage-name">MJPEG</span>
              <span class="stage-fps live" data-stage-mjpeg="${escapeHtml(camera.id)}">— fps</span>
            </div>
            <span class="stage-arrow">→</span>
            <div class="stage-step">
              <span class="stage-name">Browser</span>
              <span class="stage-fps live" data-stage-browser="${escapeHtml(camera.id)}">— fps</span>
            </div>
          </div>
        </div>

        <!-- Bottleneck Diagnosis Box -->
        <div class="diagnosis-box" data-diagnosis-box="${escapeHtml(camera.id)}">
          <div class="diagnosis-head">
            <span class="diagnosis-pill" data-diagnosis-pill="${escapeHtml(camera.id)}">Analyzing…</span>
            <span class="diagnosis-stage" data-diagnosis-stage="${escapeHtml(camera.id)}"></span>
          </div>
          <p class="diagnosis-desc" data-diagnosis-desc="${escapeHtml(camera.id)}">Gathering pipeline telemetry data…</p>
        </div>

        <!-- Detailed Metric Grid -->
        <div class="metric-grid">
          <div class="metric-item">
            <span class="metric-label">Pipeline latency</span>
            <span class="metric-value latency" data-val-latency="${escapeHtml(camera.id)}">— ms</span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Active subscribers</span>
            <span class="metric-value" data-val-clients="${escapeHtml(camera.id)}">—</span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Queue / Dropped</span>
            <span class="metric-value" data-val-drops="${escapeHtml(camera.id)}">Q: 0 · Drop: 0</span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Decode errors</span>
            <span class="metric-value" data-val-errors="${escapeHtml(camera.id)}">0</span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Total frames</span>
            <span class="metric-value" data-val-frames="${escapeHtml(camera.id)}">—</span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Stream resolution</span>
            <span class="metric-value" data-val-resolution="${escapeHtml(camera.id)}">—</span>
          </div>
        </div>

        <!-- Sparkline FPS Stability -->
        <div class="sparkline-wrap">
          <div class="sparkline-label">
            <span>FPS stability (last 30s)</span>
            <span data-val-fps-current="${escapeHtml(camera.id)}">—</span>
          </div>
          <svg class="sparkline-svg" data-sparkline="${escapeHtml(camera.id)}" viewBox="0 0 320 44" preserveAspectRatio="none">
            <line x1="0" y1="22" x2="320" y2="22" stroke="rgba(255,255,255,0.05)" stroke-width="1" stroke-dasharray="2 2" />
          </svg>
        </div>

        <!-- Smart Health Monitor Section -->
        <div class="health-monitor-section" data-health-section="${escapeHtml(camera.id)}">
          <div class="health-section-head">
            <div class="health-status-group">
              <span class="health-state-dot" data-health-dot="${escapeHtml(camera.id)}"></span>
              <span class="health-state-title" data-health-state="${escapeHtml(camera.id)}">STATUS: UNKNOWN</span>
            </div>
            <div class="health-time-group">
              <span class="health-duration" data-health-duration="${escapeHtml(camera.id)}">—</span>
              <span class="health-checked" data-health-checked="${escapeHtml(camera.id)}">Checked: —</span>
            </div>
          </div>
          <p class="health-reason" data-health-reason="${escapeHtml(camera.id)}">Evaluating camera signals…</p>
          <div class="health-signals" data-health-signals="${escapeHtml(camera.id)}">
            <span class="signal-tag" data-sig-port="${escapeHtml(camera.id)}">Port: —</span>
            <span class="signal-tag" data-sig-feed="${escapeHtml(camera.id)}">Feed: —</span>
            <span class="signal-tag" data-sig-frozen="${escapeHtml(camera.id)}">Frozen: —</span>
            <span class="signal-tag" data-sig-fps="${escapeHtml(camera.id)}">FPS: —</span>
          </div>

          <!-- Process Supervisor & Auto-Recovery Status -->
          <div class="supervisor-line" data-supervisor-line="${escapeHtml(camera.id)}">
            <span class="supervisor-pill" data-sup-pill="${escapeHtml(camera.id)}">Supervisor: STOPPED</span>
            <button class="button button-small button-reset-breaker" data-reset-breaker="${escapeHtml(camera.id)}" type="button" style="display:none;">Reset Circuit Breaker</button>
          </div>
        </div>
      </article>`;
  }).join("");
}

function updateSparkline(id, history) {
  const svg = document.querySelector(`[data-sparkline="${CSS.escape(id)}"]`);
  if (!svg || !history || history.length < 2) return;

  const width = 320;
  const height = 44;
  const pad = 4;
  const maxVal = Math.max(...history, 16);
  const minVal = 0;
  const range = maxVal - minVal || 1;

  const points = history.map((val, idx) => {
    const x = pad + (idx / (history.length - 1)) * (width - pad * 2);
    const y = height - pad - ((val - minVal) / range) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const polylinePts = points.join(" ");
  const polygonPts = `${points[0].split(",")[0]},${height - pad} ${polylinePts} ${points[points.length - 1].split(",")[0]},${height - pad}`;

  svg.innerHTML = `
    <line x1="0" y1="${height / 2}" x2="${width}" y2="${height / 2}" stroke="rgba(255,255,255,0.08)" stroke-width="1" stroke-dasharray="3 3" />
    <polygon points="${polygonPts}" fill="rgba(111, 207, 151, 0.12)" />
    <polyline points="${polylinePts}" fill="none" stroke="var(--live)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
  `;
}

let clientDisplayFps = 60.0;
let lastRafTime = performance.now();
let rafFrameCount = 0;

function monitorDisplayFps(now) {
  rafFrameCount++;
  if (now - lastRafTime >= 1000) {
    clientDisplayFps = Math.round((rafFrameCount * 1000) / (now - lastRafTime));
    rafFrameCount = 0;
    lastRafTime = now;
  }
  requestAnimationFrame(monitorDisplayFps);
}
requestAnimationFrame(monitorDisplayFps);

async function pollMetrics() {
  await Promise.allSettled(cameras.map(async (camera) => {
    if (!camera.metricsUrl) return;
    try {
      const isHidden = typeof document !== "undefined" && document.hidden;
      const cached = metricsData.get(camera.id);
      const estFps = isHidden ? 0.0 : Math.min(clientDisplayFps, (cached?.stages?.mjpegOutFps ?? cached?.mjpegFps ?? 15.0));

      const fetchUrl = new URL(camera.metricsUrl);
      fetchUrl.searchParams.set("clientFps", estFps.toFixed(1));

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2000);
      const res = await fetch(fetchUrl.toString(), { cache: "no-store", signal: controller.signal });
      clearTimeout(timer);
      if (!res.ok) return;
      const data = await res.json();
      metricsData.set(camera.id, data);

      // Record history
      let history = metricsHistory.get(camera.id);
      if (!history) {
        history = [];
        metricsHistory.set(camera.id, history);
      }
      const primaryFps = data.stages?.sourceFps ?? data.sourceFps ?? 0;
      history.push(primaryFps);
      if (history.length > 30) history.shift();

      // Update per-tile telemetry strip
      const fpsEl = document.querySelector(`[data-telemetry-fps="${CSS.escape(camera.id)}"]`);
      const latEl = document.querySelector(`[data-telemetry-lat="${CSS.escape(camera.id)}"]`);
      const clientsEl = document.querySelector(`[data-telemetry-clients="${CSS.escape(camera.id)}"]`);
      const latMs = data.latency?.decodeLatencyMs ?? data.xcodeLatencyMs ?? 0;
      if (fpsEl) fpsEl.textContent = `${primaryFps.toFixed(1)} fps`;
      if (latEl) latEl.textContent = `${Math.round(latMs)} ms`;
      if (clientsEl) clientsEl.textContent = `${data.activeRtspSessions ?? 0} RTSP · ${data.activeMjpegClients ?? 0} Web`;

      // Update Pipeline Stage Flow
      const stages = data.stages || {};
      const targetFps = stages.cameraDeclaredFps > 0 ? stages.cameraDeclaredFps : 15.0;
      const srcFpsVal = stages.sourceFps ?? data.sourceFps ?? 0;
      const xcodeFpsVal = stages.decoderOutFps ?? data.xcodeOutFps ?? 0;
      const mjpegFpsVal = stages.mjpegOutFps ?? data.mjpegFps ?? 0;
      const browserFpsVal = stages.browserRenderFps > 0 ? stages.browserRenderFps : (isHidden ? 0.0 : mjpegFpsVal);

      function setStageFps(sel, val, target) {
        const el = document.querySelector(`[${sel}="${CSS.escape(camera.id)}"]`);
        if (!el) return;
        el.textContent = `${val.toFixed(1)} fps`;
        el.className = "stage-fps";
        if (val >= target * 0.8) {
          el.classList.add("live");
        } else if (val >= target * 0.4) {
          el.classList.add("warn");
        } else {
          el.classList.add("bad");
        }
      }

      const targetEl = document.querySelector(`[data-stage-target="${CSS.escape(camera.id)}"]`);
      if (targetEl) targetEl.textContent = `${targetFps.toFixed(1)} fps`;

      setStageFps("data-stage-source", srcFpsVal, targetFps);
      setStageFps("data-stage-decoder", xcodeFpsVal, targetFps);
      setStageFps("data-stage-mjpeg", mjpegFpsVal, targetFps);
      setStageFps("data-stage-browser", browserFpsVal, targetFps);

      // Update Bottleneck Diagnosis
      const diag = data.bottleneck;
      const diagBox = document.querySelector(`[data-diagnosis-box="${CSS.escape(camera.id)}"]`);
      const diagPill = document.querySelector(`[data-diagnosis-pill="${CSS.escape(camera.id)}"]`);
      const diagStage = document.querySelector(`[data-diagnosis-stage="${CSS.escape(camera.id)}"]`);
      const diagDesc = document.querySelector(`[data-diagnosis-desc="${CSS.escape(camera.id)}"]`);

      if (diag && diagBox && diagPill && diagDesc) {
        const sev = diag.severity || "none";
        diagBox.className = `diagnosis-box ${sev !== "none" ? `severity-${sev}` : ""}`;
        diagPill.className = `diagnosis-pill ${sev !== "none" ? sev : ""}`;

        let pillText = "Pipeline Smooth";
        if (diag.dominantStage === "CameraSource") pillText = "Ingest / Sensor";
        else if (diag.dominantStage === "Transcoder") pillText = "Decode Latency";
        else if (diag.dominantStage === "MjpegEncoder") pillText = "MJPEG Backlog";
        else if (diag.dominantStage === "BrowserClient") pillText = "Browser Throttled";
        diagPill.textContent = pillText;

        if (diagStage) {
          diagStage.textContent = diag.dominantStage && diag.dominantStage !== "None" ? `Stage: ${diag.dominantStage}` : "All stages OK";
        }
        diagDesc.textContent = diag.description || "Pipeline berjalan optimal.";
      }

      // Update Metric Grid
      const latVal = document.querySelector(`[data-val-latency="${CSS.escape(camera.id)}"]`);
      const framesVal = document.querySelector(`[data-val-frames="${CSS.escape(camera.id)}"]`);
      const clientsVal = document.querySelector(`[data-val-clients="${CSS.escape(camera.id)}"]`);
      const dropsVal = document.querySelector(`[data-val-drops="${CSS.escape(camera.id)}"]`);
      const errorsVal = document.querySelector(`[data-val-errors="${CSS.escape(camera.id)}"]`);
      const curFps = document.querySelector(`[data-val-fps-current="${CSS.escape(camera.id)}"]`);
      const mDot = document.querySelector(`[data-metric-dot="${CSS.escape(camera.id)}"]`);

      if (latVal) latVal.textContent = `${Math.round(latMs)} ms`;
      if (framesVal) framesVal.textContent = Number(data.totalSourceFrames || 0).toLocaleString();
      if (clientsVal) clientsVal.textContent = `${data.activeRtspSessions ?? 0} RTSP · ${data.activeMjpegClients ?? 0} Web`;

      const health = data.health || {};
      const totalDrops = (health.droppedDecoderIn || 0) + (health.droppedMjpegIn || 0);
      if (dropsVal) dropsVal.textContent = `Q: ${health.queueDepth ?? 0} · Drop: ${totalDrops}`;
      if (errorsVal) errorsVal.textContent = `${health.decodingErrors ?? 0} err · ${health.reconnectCount ?? 0} rcn`;
      if (curFps) curFps.textContent = `${primaryFps.toFixed(1)} fps`;
      if (mDot) mDot.className = "status-dot online";

      const img = document.querySelector(`[data-feed="${CSS.escape(camera.id)}"]`);
      if (img && img.naturalWidth) {
        const resVal = document.querySelector(`[data-val-resolution="${CSS.escape(camera.id)}"]`);
        if (resVal) resVal.textContent = `${img.naturalWidth} × ${img.naturalHeight}`;
      }

      updateSparkline(camera.id, history);
    } catch {
      // Offline or network error
      const mDot = document.querySelector(`[data-metric-dot="${CSS.escape(camera.id)}"]`);
      if (mDot && connectionStates.get(camera.id)?.status === "offline") {
        mDot.className = "status-dot offline";
      }
    }
  }));
}

function attachEvents() {
  document.querySelectorAll("[data-configure]").forEach((button) => {
    button.onclick = (e) => {
      e.stopPropagation();
      openConfig(button.dataset.configure);
    };
  });

  document.querySelectorAll("[data-placeholder-config]").forEach((button) => {
    button.onclick = (e) => {
      e.stopPropagation();
      openConfig(button.dataset.placeholderConfig);
    };
  });

  document.querySelectorAll("[data-refresh]").forEach((button) => {
    button.onclick = (e) => {
      e.stopPropagation();
      startStream(button.dataset.refresh);
    };
  });

  document.querySelectorAll("[data-retry-btn]").forEach((button) => {
    button.onclick = (e) => {
      e.stopPropagation();
      startStream(button.dataset.retryBtn);
    };
  });

  // Focus mode
  document.querySelectorAll("[data-focus]").forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const card = btn.closest(".camera-card");
      if (card) {
        const isFocused = card.classList.toggle("is-focused");
        btn.textContent = isFocused ? "Restore" : "Focus";
      }
    };
  });

  document.querySelectorAll("[data-video-wrap]").forEach((wrap) => {
    wrap.onclick = (e) => {
      if (e.target.closest("button") || e.target.closest(".tile-zoom-bar")) return;
      const cid = wrap.dataset.videoWrap;
      const z = getZoomState(cid);
      if (z && z.scale > 1.05) return; // Ignore card focus when zoomed in
      const card = wrap.closest(".camera-card");
      if (card) {
        const isFocused = card.classList.toggle("is-focused");
        const focusBtn = card.querySelector("[data-focus]");
        if (focusBtn) {
          focusBtn.textContent = isFocused ? "Restore" : "Focus";
        }
      }
    };
  });

  // Layout View Switcher (2col, auto, 1col)
  document.querySelectorAll("[data-layout]").forEach((btn) => {
    btn.onclick = () => {
      document.querySelectorAll("[data-layout]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const mode = btn.dataset.layout;
      grid.classList.remove("density-2col", "density-auto", "density-1col");
      grid.classList.add(`density-${mode}`);
      localStorage.setItem("camhub.view.density", mode);
    };
  });

  attachZoomEvents();
}

function restoreLayoutPreference() {
  const saved = localStorage.getItem("camhub.view.density") || "2col";
  const btn = document.querySelector(`[data-layout="${saved}"]`);
  if (btn) {
    document.querySelectorAll("[data-layout]").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    grid.classList.remove("density-2col", "density-auto", "density-1col");
    grid.classList.add(`density-${saved}`);
  }
}

const cameraZoomState = new Map();

function getZoomState(id) {
  if (!cameraZoomState.has(id)) {
    cameraZoomState.set(id, { scale: 1.0, x: 0, y: 0 });
  }
  return cameraZoomState.get(id);
}

function applyZoom(id, smooth = false) {
  const z = getZoomState(id);
  const wrap = document.querySelector(`[data-video-wrap="${CSS.escape(id)}"]`);
  const img = document.querySelector(`[data-feed="${CSS.escape(id)}"]`);
  const valBadge = document.querySelector(`[data-zoom-val="${CSS.escape(id)}"]`);

  if (!wrap || !img) return;

  const rect = wrap.getBoundingClientRect();
  const maxX = Math.max(0, (rect.width * (z.scale - 1)) / 2);
  const maxY = Math.max(0, (rect.height * (z.scale - 1)) / 2);

  z.x = Math.max(-maxX, Math.min(maxX, z.x));
  z.y = Math.max(-maxY, Math.min(maxY, z.y));

  img.style.transition = smooth ? "transform 0.16s ease-out" : "none";
  img.style.transform = `translate(${z.x}px, ${z.y}px) scale(${z.scale})`;

  if (z.scale > 1.02) {
    wrap.classList.add("is-zoomed");
    if (valBadge) valBadge.classList.add("is-active");
  } else {
    wrap.classList.remove("is-zoomed", "is-panning");
    if (valBadge) valBadge.classList.remove("is-active");
    z.x = 0;
    z.y = 0;
  }

  if (valBadge) {
    valBadge.textContent = `${z.scale.toFixed(1)}x`;
  }
}

function zoomCamera(id, deltaScale, focalX = 0, focalY = 0) {
  const z = getZoomState(id);
  const oldScale = z.scale;
  let newScale = Math.round((oldScale + deltaScale) * 10) / 10;
  newScale = Math.max(1.0, Math.min(5.0, newScale));

  if (newScale === oldScale) return;

  if (newScale > 1.0 && oldScale > 0) {
    const factor = newScale / oldScale;
    z.x = (z.x - focalX) * factor + focalX;
    z.y = (z.y - focalY) * factor + focalY;
  } else {
    z.x = 0;
    z.y = 0;
  }

  z.scale = newScale;
  applyZoom(id, true);
}

function resetZoom(id) {
  const z = getZoomState(id);
  z.scale = 1.0;
  z.x = 0;
  z.y = 0;
  applyZoom(id, true);
}

function attachZoomEvents() {
  document.querySelectorAll("[data-video-wrap]").forEach((wrap) => {
    const id = wrap.dataset.videoWrap;
    if (!id) return;

    // Apply current zoom state on re-render
    applyZoom(id, false);

    // Zoom Buttons
    const inBtn = wrap.querySelector(`[data-zoom-in="${CSS.escape(id)}"]`);
    const outBtn = wrap.querySelector(`[data-zoom-out="${CSS.escape(id)}"]`);
    const resetBtn = wrap.querySelector(`[data-zoom-reset="${CSS.escape(id)}"]`);
    const fsBtn = wrap.querySelector(`[data-zoom-fullscreen="${CSS.escape(id)}"]`);

    if (inBtn) inBtn.onclick = (e) => { e.stopPropagation(); zoomCamera(id, 0.5); };
    if (outBtn) outBtn.onclick = (e) => { e.stopPropagation(); zoomCamera(id, -0.5); };
    if (resetBtn) resetBtn.onclick = (e) => { e.stopPropagation(); resetZoom(id); };

    if (fsBtn) {
      fsBtn.onclick = (e) => {
        e.stopPropagation();
        if (!document.fullscreenElement) {
          wrap.requestFullscreen().catch(() => {});
        } else {
          document.exitFullscreen().catch(() => {});
        }
      };
    }

    // Wheel Zoom (centered around cursor position)
    wrap.onwheel = (e) => {
      e.preventDefault();
      const rect = wrap.getBoundingClientRect();
      const focalX = e.clientX - rect.left - rect.width / 2;
      const focalY = e.clientY - rect.top - rect.height / 2;
      const delta = e.deltaY < 0 ? 0.3 : -0.3;
      zoomCamera(id, delta, focalX, focalY);
    };

    // Double-click to toggle 1.0x <-> 2.5x
    wrap.ondblclick = (e) => {
      if (e.target.closest("button") || e.target.closest(".tile-zoom-bar")) return;
      e.preventDefault();
      e.stopPropagation();
      const z = getZoomState(id);
      if (z.scale > 1.05) {
        resetZoom(id);
      } else {
        const rect = wrap.getBoundingClientRect();
        const focalX = e.clientX - rect.left - rect.width / 2;
        const focalY = e.clientY - rect.top - rect.height / 2;
        zoomCamera(id, 1.5, focalX, focalY);
      }
    };

    // Mouse Drag / Touch Pan
    let isDragging = false;
    let startX = 0, startY = 0;
    let origX = 0, origY = 0;

    wrap.onmousedown = (e) => {
      if (e.target.closest("button") || e.target.closest(".tile-zoom-bar")) return;
      const z = getZoomState(id);
      if (z.scale <= 1.0) return;

      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      origX = z.x;
      origY = z.y;
      wrap.classList.add("is-panning");
      e.preventDefault();
    };

    const onMouseMove = (e) => {
      if (!isDragging) return;
      const z = getZoomState(id);
      z.x = origX + (e.clientX - startX);
      z.y = origY + (e.clientY - startY);
      applyZoom(id, false);
    };

    const onMouseUp = () => {
      if (!isDragging) return;
      isDragging = false;
      wrap.classList.remove("is-panning");
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);

    // Touch support (1 finger pan when zoomed, 2 finger pinch-to-zoom)
    let lastTouchDist = null;
    wrap.ontouchstart = (e) => {
      if (e.touches.length === 1) {
        const z = getZoomState(id);
        if (z.scale > 1.0) {
          isDragging = true;
          startX = e.touches[0].clientX;
          startY = e.touches[0].clientY;
          origX = z.x;
          origY = z.y;
        }
      } else if (e.touches.length === 2) {
        isDragging = false;
        lastTouchDist = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
      }
    };

    wrap.ontouchmove = (e) => {
      if (e.touches.length === 1 && isDragging) {
        const z = getZoomState(id);
        z.x = origX + (e.touches[0].clientX - startX);
        z.y = origY + (e.touches[0].clientY - startY);
        applyZoom(id, false);
      } else if (e.touches.length === 2 && lastTouchDist !== null) {
        const dist = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
        const delta = (dist - lastTouchDist) * 0.01;
        lastTouchDist = dist;
        zoomCamera(id, delta);
      }
    };

    wrap.ontouchend = () => {
      isDragging = false;
      lastTouchDist = null;
    };
  });
}

function initPlaybackZoom() {
  const video = document.querySelector("#playback-video");
  const wrapper = document.querySelector(".playback-player-card .player-wrapper");
  const inBtn = document.querySelector("#playback-zoom-in");
  const outBtn = document.querySelector("#playback-zoom-out");
  const resetBtn = document.querySelector("#playback-zoom-reset");
  const valBadge = document.querySelector("#playback-zoom-val");

  if (!video || !wrapper) return;

  let pScale = 1.0;
  let pX = 0, pY = 0;

  const applyPbZoom = (smooth = false) => {
    const rect = wrapper.getBoundingClientRect();
    const maxX = Math.max(0, (rect.width * (pScale - 1)) / 2);
    const maxY = Math.max(0, (rect.height * (pScale - 1)) / 2);

    pX = Math.max(-maxX, Math.min(maxX, pX));
    pY = Math.max(-maxY, Math.min(maxY, pY));

    video.style.transition = smooth ? "transform 0.16s ease-out" : "none";
    video.style.transform = `translate(${pX}px, ${pY}px) scale(${pScale})`;

    if (valBadge) valBadge.textContent = `${pScale.toFixed(1)}x`;
    if (pScale > 1.02) {
      wrapper.classList.add("is-zoomed");
    } else {
      wrapper.classList.remove("is-zoomed", "is-panning");
      pX = 0;
      pY = 0;
    }
  };

  const zoomPb = (delta) => {
    pScale = Math.max(1.0, Math.min(5.0, Math.round((pScale + delta) * 10) / 10));
    applyPbZoom(true);
  };

  if (inBtn) inBtn.onclick = () => zoomPb(0.5);
  if (outBtn) outBtn.onclick = () => zoomPb(-0.5);
  if (resetBtn) resetBtn.onclick = () => { pScale = 1.0; pX = 0; pY = 0; applyPbZoom(true); };

  wrapper.onwheel = (e) => {
    if (e.target.closest("button") || e.target.closest("input")) return;
    e.preventDefault();
    zoomPb(e.deltaY < 0 ? 0.3 : -0.3);
  };

  let isDragging = false;
  let startX = 0, startY = 0;
  let origX = 0, origY = 0;

  wrapper.onmousedown = (e) => {
    if (e.target.closest("button") || e.target.closest(".tile-zoom-bar") || pScale <= 1.0) return;
    isDragging = true;
    startX = e.clientX;
    startY = e.clientY;
    origX = pX;
    origY = pY;
    wrapper.classList.add("is-panning");
    e.preventDefault();
  };

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    pX = origX + (e.clientX - startX);
    pY = origY + (e.clientY - startY);
    applyPbZoom(false);
  });

  window.addEventListener("mouseup", () => {
    if (!isDragging) return;
    isDragging = false;
    wrapper.classList.remove("is-panning");
  });
}

function toggleCameraSelection(id) {
  if (selectedCameraIds.has(id)) {
    selectedCameraIds.delete(id);
  } else {
    selectedCameraIds.add(id);
  }
  saveSelectedCameraIds();
  updateCameraFilterUI();
  render();
}

function selectAllCameras(selectAll = true) {
  if (selectAll) {
    selectedCameraIds = new Set(cameras.map((c) => c.id));
  } else {
    selectedCameraIds.clear();
  }
  saveSelectedCameraIds();
  updateCameraFilterUI();
  render();
}

function selectHealthyCamerasOnly() {
  selectedCameraIds.clear();
  cameras.forEach((c) => {
    const h = cameraHealthData.get(c.id);
    const status = (h?.status || "UNKNOWN").toUpperCase();
    if (status === "HEALTHY") {
      selectedCameraIds.add(c.id);
    }
  });
  if (selectedCameraIds.size === 0) {
    selectedCameraIds = new Set(cameras.map((c) => c.id));
    showToast("No healthy cameras found at the moment", "warn", 3000);
  } else {
    showToast(`Showing ${selectedCameraIds.size} healthy camera(s)`, "info", 2500);
  }
  saveSelectedCameraIds();
  updateCameraFilterUI();
  render();
}

function updateCameraFilterUI() {
  const toggleText = document.querySelector("#camera-filter-toggle-text");
  const chipsContainer = document.querySelector("#camera-filter-chips");
  const dropdownList = document.querySelector("#filter-dropdown-list");
  const countLabel = document.querySelector("#cam-sel-count");
  const resetBtn = document.querySelector("#cam-sel-reset-btn");

  const total = cameras.length;
  const selCount = selectedCameraIds.size;

  if (toggleText) {
    toggleText.textContent = `Cameras (${selCount}/${total})`;
  }

  if (countLabel) {
    countLabel.textContent = `${selCount} of ${total} visible`;
  }

  if (resetBtn) {
    resetBtn.style.display = selCount < total ? "inline-block" : "none";
  }

  // Render quick chips
  if (chipsContainer) {
    chipsContainer.innerHTML = cameras.map((c) => {
      const isSel = isCameraSelected(c.id);
      const h = cameraHealthData.get(c.id);
      const st = (h?.status || "UNKNOWN").toLowerCase();
      const stUpper = h?.status || "UNKNOWN";
      const reason = h?.reason || "Checking camera status…";
      const fps = h?.metrics?.fps !== undefined ? `${h.metrics.fps} fps` : "";

      return `
        <button
          type="button"
          class="camera-filter-chip ${isSel ? 'active' : 'inactive'}"
          data-cam-chip="${escapeHtml(c.id)}"
          title="${escapeHtml(reason)}"
        >
          <span class="chip-check-icon">${isSel ? '✓' : '＋'}</span>
          <span class="chip-status-dot ${st}"></span>
          <span class="chip-name">${escapeHtml(c.name)}</span>
          ${fps ? `<span class="chip-fps">${fps}</span>` : ''}
          <span class="chip-status-badge ${st}">${stUpper}</span>
        </button>
      `;
    }).join("");

    chipsContainer.querySelectorAll("[data-cam-chip]").forEach((btn) => {
      btn.onclick = () => {
        toggleCameraSelection(btn.dataset.camChip);
      };
    });
  }

  // Render dropdown list
  if (dropdownList) {
    dropdownList.innerHTML = cameras.map((c) => {
      const isSel = isCameraSelected(c.id);
      const h = cameraHealthData.get(c.id);
      const st = (h?.status || "UNKNOWN").toLowerCase();
      const stUpper = h?.status || "UNKNOWN";
      const reason = h?.reason || "Checking camera status…";
      const fps = h?.metrics?.fps !== undefined ? `${h.metrics.fps} fps` : "";

      return `
        <label class="filter-item-row" title="${escapeHtml(reason)}">
          <input
            type="checkbox"
            class="filter-item-check"
            data-cam-check="${escapeHtml(c.id)}"
            ${isSel ? 'checked' : ''}
          />
          <span class="chip-status-dot ${st}"></span>
          <div class="filter-item-info">
            <span class="filter-item-name">${escapeHtml(c.name)}</span>
            <span class="filter-item-sub">${escapeHtml(c.location || c.id)}${fps ? ` · ${fps}` : ''}</span>
          </div>
          <span class="chip-status-badge ${st}">${stUpper}</span>
        </label>
      `;
    }).join("");

    dropdownList.querySelectorAll("[data-cam-check]").forEach((chk) => {
      chk.onchange = () => {
        toggleCameraSelection(chk.dataset.camCheck);
      };
    });
  }
}

function initCameraFilter() {
  const toggleBtn = document.querySelector("#camera-filter-toggle-btn");
  const dropdown = document.querySelector("#camera-filter-dropdown");
  const allBtn = document.querySelector("#filter-all-btn");
  const healthyBtn = document.querySelector("#filter-healthy-btn");
  const noneBtn = document.querySelector("#filter-none-btn");
  const resetBtn = document.querySelector("#cam-sel-reset-btn");

  if (toggleBtn && dropdown) {
    toggleBtn.onclick = (e) => {
      e.stopPropagation();
      const isVisible = dropdown.style.display !== "none";
      dropdown.style.display = isVisible ? "none" : "flex";
      toggleBtn.setAttribute("aria-expanded", String(!isVisible));
    };

    document.addEventListener("click", (e) => {
      if (!dropdown.contains(e.target) && !toggleBtn.contains(e.target)) {
        dropdown.style.display = "none";
        toggleBtn.setAttribute("aria-expanded", "false");
      }
    });
  }

  if (allBtn) allBtn.onclick = () => selectAllCameras(true);
  if (healthyBtn) healthyBtn.onclick = () => selectHealthyCamerasOnly();
  if (noneBtn) noneBtn.onclick = () => selectAllCameras(false);
  if (resetBtn) resetBtn.onclick = () => selectAllCameras(true);

  updateCameraFilterUI();
}

function openConfig(id) {
  const camera = cameras.find((item) => item.id === id);
  if (!camera) return;

  document.querySelector("#camera-id").value = camera.id;
  document.querySelector("#dialog-title").textContent = `Configure ${camera.name}`;
  document.querySelector("#camera-name").value = camera.name || "";
  document.querySelector("#camera-location").value = camera.location || "";
  document.querySelector("#camera-brand").value = camera.brand || "";
  document.querySelector("#camera-url").value = camera.url || "";
  document.querySelector("#camera-snapshot").value = camera.snapshotUrl || "";

  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "true");
  }
}

function closeDialog() {
  if (typeof dialog.close === "function") {
    dialog.close();
  } else {
    dialog.removeAttribute("open");
  }
}

if (closeDialogBtn) closeDialogBtn.onclick = closeDialog;
if (cancelDialogBtn) cancelDialogBtn.onclick = closeDialog;

configForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const id = document.querySelector("#camera-id").value;
  const camera = cameras.find((item) => item.id === id);
  if (!camera) return;

  const urlInput = document.querySelector("#camera-url").value.trim();
  const snapshotInput = document.querySelector("#camera-snapshot").value.trim();

  if (urlInput) {
    try {
      const parsed = new URL(urlInput);
      if (!["http:", "https:"].includes(parsed.protocol)) {
        throw new Error("Only HTTP(S) stream URLs are supported.");
      }
      if (parsed.username || parsed.password) {
        throw new Error("Do not embed camera usernames or passwords inside the stream URL.");
      }
    } catch (error) {
      alert(error.message || "Please enter a valid HTTP or HTTPS stream URL.");
      return;
    }
  }

  if (snapshotInput) {
    try {
      const parsed = new URL(snapshotInput);
      if (!["http:", "https:"].includes(parsed.protocol)) {
        throw new Error("Only HTTP(S) snapshot URLs are supported.");
      }
      if (parsed.username || parsed.password) {
        throw new Error("Do not embed camera usernames or passwords inside snapshot URLs.");
      }
    } catch (error) {
      alert(error.message || "Please enter a valid HTTP or HTTPS snapshot URL.");
      return;
    }
  }

  camera.name = document.querySelector("#camera-name").value.trim();
  camera.location = document.querySelector("#camera-location").value.trim();
  camera.brand = document.querySelector("#camera-brand").value.trim();
  camera.url = urlInput;
  camera.snapshotUrl = snapshotInput;
  camera.metricsUrl = deriveMetricsUrl(urlInput);

  saveCameras();
  closeDialog();
  render();
});

document.querySelector("#refresh-all").addEventListener("click", () => {
  cameras.forEach((camera) => {
    if (camera.url && isCameraSelected(camera.id)) {
      startStream(camera.id);
    }
  });
});

window.addEventListener("focus", () => {
  cameras.forEach((camera) => {
    if (camera.url && isCameraSelected(camera.id) && connectionStates.get(camera.id)?.status === "offline") {
      startStream(camera.id);
    }
  });
});

// Setup guide scripts
const SETUP_SCRIPTS = {
  cam1: `cd "$HOME\\V380Decoder-Latest"

$user1 = Read-Host "Username camera 1"
$secure1 = Read-Host "Password camera 1" -AsSecureString
$ptr1 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure1)
$pass1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr1)

dotnet run --no-build -- \`
  --id 124095217 \`
  --username $user1 \`
  --password $pass1 \`
  --ip 192.168.100.24 \`
  --port 8800 \`
  --source lan \`
  --output rtsp \`
  --quality hd \`
  --enable-api \`
  --http-port 8080 \`
  --rtsp-port 8554 \`
  --debug

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr1)
Remove-Variable pass1, secure1, user1 -ErrorAction SilentlyContinue`,

  cam2: `cd "$HOME\\V380Decoder-Fork"

$user2 = Read-Host "Username camera 2"
$secure2 = Read-Host "Password camera 2" -AsSecureString
$ptr2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure2)
$pass2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr2)

dotnet run --no-build -- \`
  --id 97357757 \`
  --username $user2 \`
  --password $pass2 \`
  --ip 192.168.100.4 \`
  --port 8800 \`
  --source lan \`
  --output rtsp \`
  --quality hd \`
  --enable-api \`
  --http-port 8081 \`
  --rtsp-port 8555 \`
  --debug

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr2)
Remove-Variable pass2, secure2, user2 -ErrorAction SilentlyContinue`,

  all: `# ==========================================
# 1. CAMERA 1 — Indoor (Port 8080)
# ==========================================
cd "$HOME\\V380Decoder-Latest"

$user1 = Read-Host "Username camera 1"
$secure1 = Read-Host "Password camera 1" -AsSecureString
$ptr1 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure1)
$pass1 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr1)

dotnet run --no-build -- \`
  --id 124095217 \`
  --username $user1 \`
  --password $pass1 \`
  --ip 192.168.100.24 \`
  --port 8800 \`
  --source lan \`
  --output rtsp \`
  --quality hd \`
  --enable-api \`
  --http-port 8080 \`
  --rtsp-port 8554 \`
  --debug

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr1)
Remove-Variable pass1, secure1, user1 -ErrorAction SilentlyContinue

# ==========================================
# 2. CAMERA 2 — Garage (Port 8081)
# ==========================================
cd "$HOME\\V380Decoder-Fork"

$user2 = Read-Host "Username camera 2"
$secure2 = Read-Host "Password camera 2" -AsSecureString
$ptr2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure2)
$pass2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr2)

dotnet run --no-build -- \`
  --id 97357757 \`
  --username $user2 \`
  --password $pass2 \`
  --ip 192.168.100.4 \`
  --port 8800 \`
  --source lan \`
  --output rtsp \`
  --quality hd \`
  --enable-api \`
  --http-port 8081 \`
  --rtsp-port 8555 \`
  --debug

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr2)
Remove-Variable pass2, secure2, user2 -ErrorAction SilentlyContinue

# ==========================================
# 3. CAMERA 3 — O-Kam Pro / VStarcam (Port 8082)
# ==========================================
cd "C:\\DaffaP\\Project df\\CamHUB"
python okam_adapter.py --port 8082 --rtsp "rtsp://admin:Danendra07.@192.168.100.6:10554/tcp/av0_0"`,

  okam: `# ==========================================
# 3. CAMERA 3 — O-Kam Pro / VStarcam (Port 8082)
# ==========================================
cd "C:\\DaffaP\\Project df\\CamHUB"

# Runs O-Kam RTSP-to-MJPEG adapter on port 8082
python okam_adapter.py --port 8082 --rtsp "rtsp://admin:Danendra07.@192.168.100.6:10554/tcp/av0_0"`
};

function initSetupGuide() {
  const codeEl = document.querySelector("#setup-script-code");
  const copyBtn = document.querySelector("#copy-script-btn");
  const tabButtons = document.querySelectorAll("[data-script-tab]");

  if (codeEl && SETUP_SCRIPTS.cam1) {
    codeEl.textContent = SETUP_SCRIPTS.cam1;
  }

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const key = btn.dataset.scriptTab;
      if (codeEl && SETUP_SCRIPTS[key]) {
        codeEl.textContent = SETUP_SCRIPTS[key];
      }
    });
  });

  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const textToCopy = codeEl ? codeEl.textContent : "";
      if (!textToCopy) return;
      try {
        await navigator.clipboard.writeText(textToCopy);
        const originalText = copyBtn.textContent;
        copyBtn.textContent = "Copied";
        setTimeout(() => {
          copyBtn.textContent = originalText;
        }, 2000);
      } catch (err) {
        const range = document.createRange();
        range.selectNodeContents(codeEl);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
    });
  }
}

function initNav() {
  const navLinks = document.querySelectorAll(".nav-link");
  navLinks.forEach((link) => {
    link.addEventListener("click", () => {
      navLinks.forEach((l) => l.classList.remove("active"));
      link.classList.add("active");
    });
  });

  const sections = [
    { id: "overview", link: document.querySelector('.nav-link[href="#overview"]') },
    { id: "analytics", link: document.querySelector('.nav-link[href="#analytics"]') },
    { id: "playback", link: document.querySelector('.nav-link[href="#playback"]') },
    { id: "events", link: document.querySelector('.nav-link[href="#events"]') },
    { id: "setup", link: document.querySelector('.nav-link[href="#setup"]') }
  ];

  window.addEventListener("scroll", () => {
    const scrollPos = window.scrollY + 140;
    for (let i = sections.length - 1; i >= 0; i--) {
      const el = document.getElementById(sections[i].id);
      if (el && scrollPos >= el.offsetTop) {
        navLinks.forEach((l) => l.classList.remove("active"));
        if (sections[i].link) sections[i].link.classList.add("active");
        break;
      }
    }
  }, { passive: true });
}

function showToast(message, type = "info", duration = 3500) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 250);
  }, duration);
}

function initServiceControls() {
  const runBtn = document.getElementById("run-all-cameras");
  const runText = document.getElementById("run-all-text");
  if (!runBtn) return;

  let allRunning = false;
  let isProcessing = false;

  const updateBtnState = (running) => {
    allRunning = running;
    if (running) {
      runBtn.classList.add("is-running");
      runBtn.title = "Restart all camera processes";
      if (runText) runText.textContent = "Restart all cameras";
      const icon = runBtn.querySelector(".btn-icon");
      if (icon) {
        icon.innerHTML = `<polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>`;
        icon.setAttribute("fill", "none");
        icon.setAttribute("stroke", "currentColor");
        icon.setAttribute("stroke-width", "2");
      }
    } else {
      runBtn.classList.remove("is-running");
      runBtn.title = "Start all decoder and adapter services directly";
      if (runText) runText.textContent = "Run all cameras";
      const icon = runBtn.querySelector(".btn-icon");
      if (icon) {
        icon.innerHTML = `<polygon points="5 3 19 12 5 21 5 3"></polygon>`;
        icon.setAttribute("fill", "currentColor");
        icon.removeAttribute("stroke");
      }
    }
  };

  const checkStatus = async () => {
    if (isProcessing) return;
    try {
      const res = await fetch("/api/services/status", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        updateBtnState(Boolean(data.allRunning));
      }
    } catch {
      // Host server might be plain http-server
    }
  };

  runBtn.addEventListener("click", async () => {
    if (isProcessing) return;
    isProcessing = true;
    runBtn.classList.add("is-loading");
    runBtn.disabled = true;

    const action = allRunning ? "restart-all" : "start-all";
    const actionText = allRunning ? "Restarting all cameras…" : "Starting all cameras…";
    if (runText) runText.textContent = actionText;

    const icon = runBtn.querySelector(".btn-icon");
    if (icon) {
      icon.classList.add("btn-spinner");
      icon.innerHTML = `<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2.5" stroke-opacity="0.25" fill="none"></circle><path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" fill="none"></path>`;
    }

    showToast(allRunning ? "Restarting camera services..." : "Launching camera decoders and adapters...", "info", 2500);

    try {
      const res = await fetch(`/api/services/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });

      if (res.ok) {
        const data = await res.json();
        showToast("All camera services active (8080, 8081, 8082). Connecting feeds...", "success", 4000);
        updateBtnState(Boolean(data.status?.allRunning ?? true));

        // Allow 1.2s for sockets to bind, then restart client feeds
        setTimeout(() => {
          cameras.forEach((cam) => startStream(cam.id));
          pollMetrics();
        }, 1200);
      } else {
        showToast("Failed to communicate with CamHub service manager", "error", 4000);
      }
    } catch (err) {
      showToast("Could not reach service manager. Run server.py on port 3000.", "error", 4500);
    } finally {
      isProcessing = false;
      runBtn.classList.remove("is-loading");
      runBtn.disabled = false;
      if (icon) icon.classList.remove("btn-spinner");
      await checkStatus();
    }
  });

  // Initial check & periodic sync
  checkStatus();
  setInterval(checkStatus, 8000);
}

function formatDuration(sec) {
  if (!sec || sec < 0) return "0s";
  sec = Math.round(sec);
  if (sec < 60) return `${sec}s`;
  const mins = Math.floor(sec / 60);
  const remSec = sec % 60;
  if (mins < 60) return `${mins}m ${remSec}s`;
  const hrs = Math.floor(mins / 60);
  const remMin = mins % 60;
  return `${hrs}h ${remMin}m`;
}

const cameraHealthData = new Map();

async function pollHealth() {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2500);
    const res = await fetch("/api/health", { cache: "no-store", signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) return;
    const data = await res.json();

    // 1. Update Fleet Health pill in header
    const fleetPill = document.querySelector("#fleet-health-pill");
    const fleetText = document.querySelector("#fleet-health-text");
    if (fleetPill && fleetText && data.summary) {
      const fleetStatus = (data.status || "UNKNOWN").toLowerCase();
      fleetPill.className = `fleet-health-pill ${fleetStatus}`;
      fleetText.textContent = `Fleet: ${data.status} (${data.summary.healthy}/${data.summary.total} healthy)`;
    }

    // 2. Update each camera
    if (data.cameras) {
      for (const [cid, h] of Object.entries(data.cameras)) {
        cameraHealthData.set(cid, h);
        const status = (h.status || "UNKNOWN").toLowerCase();
        const statusUpper = h.status || "UNKNOWN";

        // Tile header badge
        const tileBadge = document.querySelector(`[data-tile-health="${CSS.escape(cid)}"]`);
        if (tileBadge) {
          tileBadge.className = `health-tile-badge ${status}`;
          tileBadge.textContent = statusUpper;
        }

        // Analytics card badge
        const cardBadge = document.querySelector(`[data-health-badge="${CSS.escape(cid)}"]`);
        if (cardBadge) {
          cardBadge.className = `health-badge-pill ${status}`;
          cardBadge.textContent = statusUpper;
        }

        // Analytics card health section
        const sec = document.querySelector(`[data-health-section="${CSS.escape(cid)}"]`);
        const stTitle = document.querySelector(`[data-health-state="${CSS.escape(cid)}"]`);
        const stDur = document.querySelector(`[data-health-duration="${CSS.escape(cid)}"]`);
        const stChk = document.querySelector(`[data-health-checked="${CSS.escape(cid)}"]`);
        const stReason = document.querySelector(`[data-health-reason="${CSS.escape(cid)}"]`);

        if (sec) sec.className = `health-monitor-section ${status}`;
        if (stTitle) stTitle.textContent = `STATUS: ${statusUpper}`;
        if (stDur) {
          const isIncident = statusUpper === "DEGRADED" || statusUpper === "OFFLINE";
          const durSec = isIncident ? h.incidentDurationSeconds : h.stateDurationSeconds;
          const label = isIncident ? "Incident" : "Stable";
          stDur.textContent = `${label}: ${formatDuration(durSec)}`;
        }
        if (stChk) {
          const dt = h.lastChecked ? new Intl.DateTimeFormat([], { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date(h.lastChecked)) : "—";
          stChk.textContent = `Checked: ${dt}`;
        }
        if (stReason) {
          stReason.textContent = h.reason || "Operating normally.";
        }

        // Signals tags
        const chk = h.checks || {};
        const pTag = document.querySelector(`[data-sig-port="${CSS.escape(cid)}"]`);
        const fTag = document.querySelector(`[data-sig-feed="${CSS.escape(cid)}"]`);
        const zTag = document.querySelector(`[data-sig-frozen="${CSS.escape(cid)}"]`);
        const fpsTag = document.querySelector(`[data-sig-fps="${CSS.escape(cid)}"]`);

        if (pTag) {
          pTag.textContent = chk.portListening ? "Port: Open" : "Port: Closed";
          pTag.className = `signal-tag ${chk.portListening ? "pass" : "fail"}`;
        }
        if (fTag) {
          pTag.textContent = chk.feedAlive ? "Feed: Flowing" : "Feed: Stalled";
          pTag.className = `signal-tag ${chk.feedAlive ? "pass" : "warn"}`;
        }
        if (zTag) {
          zTag.textContent = chk.streamFrozen ? "Frozen: YES" : "Frozen: No";
          zTag.className = `signal-tag ${chk.streamFrozen ? "fail" : "pass"}`;
        }
        if (fpsTag) {
          fpsTag.textContent = `FPS: ${h.metrics?.fps ?? 0} fps`;
          fpsTag.className = `signal-tag ${chk.fpsAdequate ? "pass" : "warn"}`;
        }
      }
      updateCameraFilterUI();
    }

    // 3. Update Supervisor & Auto-Recovery state
    try {
      const sRes = await fetch("/api/services/status", { cache: "no-store" });
      if (sRes.ok) {
        const sData = await sRes.json();
        for (const [cid, sInfo] of Object.entries(sData.services || {})) {
          const supPill = document.querySelector(`[data-sup-pill="${CSS.escape(cid)}"]`);
          const resetBtn = document.querySelector(`[data-reset-breaker="${CSS.escape(cid)}"]`);

          if (supPill) {
            const st = sInfo.state || (sInfo.running ? "RUNNING" : "STOPPED");
            const pidStr = sInfo.pid ? ` (PID ${sInfo.pid})` : "";
            const backoffStr = sInfo.nextAllowedRestartIn > 0 ? ` · Cooldown ${sInfo.nextAllowedRestartIn}s` : "";
            supPill.textContent = `Process: ${st}${pidStr}${backoffStr}`;
            supPill.className = `supervisor-pill state-${st.toLowerCase()}`;
          }

          if (resetBtn) {
            const isTripped = Boolean(sInfo.circuitBreakerTripped);
            resetBtn.style.display = isTripped ? "inline-flex" : "none";
            resetBtn.onclick = async (e) => {
              e.stopPropagation();
              resetBtn.disabled = true;
              resetBtn.textContent = "Resetting…";
              try {
                await fetch(`/api/recovery/reset?id=${encodeURIComponent(cid)}`, { method: "POST" });
                await fetch(`/api/services/start?id=${encodeURIComponent(cid)}`, { method: "POST" });
                showToast(`Circuit breaker reset for ${cid}. Process restarted.`, "success", 3000);
                setTimeout(pollHealth, 600);
              } catch {
                showToast(`Failed to reset circuit breaker for ${cid}`, "error", 3000);
              } finally {
                resetBtn.disabled = false;
                resetBtn.textContent = "Reset Circuit Breaker";
              }
            };
          }
        }
      }
    } catch {}
  } catch {
    // Non-blocking error recovery
  }
}

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function initPlayback() {
  const camSelect = document.querySelector("#playback-cam-select");
  const dateSelect = document.querySelector("#playback-date-select");
  const refreshBtn = document.querySelector("#playback-refresh-btn");
  const video = document.querySelector("#playback-video");
  const placeholder = document.querySelector("#playback-empty-placeholder");
  const currentTitle = document.querySelector("#current-rec-title");
  const downloadBtn = document.querySelector("#current-rec-download");
  const deleteBtn = document.querySelector("#current-rec-delete");
  const segmentsList = document.querySelector("#segments-list");
  const timelineCount = document.querySelector("#timeline-count");
  const manualBtns = document.querySelector("#manual-record-buttons");
  const storagePill = document.querySelector("#storage-indicator-pill");
  const storageText = document.querySelector("#storage-text");

  let activeRecordings = new Set();
  let currentSelectedId = null;

  // Set today's date
  if (dateSelect) {
    const today = new Date().toISOString().split("T")[0];
    dateSelect.value = today;
  }

  // Populate camera select
  if (camSelect) {
    camSelect.innerHTML = `<option value="">All cameras</option>` +
      cameras.map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join("");
  }

  // Render manual recording buttons
  const renderManualButtons = () => {
    if (!manualBtns) return;
    manualBtns.innerHTML = cameras.map(c => {
      const isRec = activeRecordings.has(c.id);
      return `<button class="button button-small rec-toggle-btn ${isRec ? 'is-recording' : ''}" data-rec-cam="${escapeHtml(c.id)}" type="button">
        ${isRec ? 'Stop' : 'Rec'} ${escapeHtml(c.name.split('·')[0].trim())}
      </button>`;
    }).join("");

    manualBtns.querySelectorAll("[data-rec-cam]").forEach(btn => {
      btn.onclick = async () => {
        const cid = btn.dataset.recCam;
        const isRec = activeRecordings.has(cid);
        const action = isRec ? "stop" : "start";
        btn.disabled = true;
        try {
          const res = await fetch(`/api/recordings/${action}?cameraId=${encodeURIComponent(cid)}`, { method: "POST" });
          const data = await res.json();
          if (data.success) {
            if (isRec) activeRecordings.delete(cid);
            else activeRecordings.add(cid);
            showToast(`${isRec ? 'Stopped' : 'Started'} recording for ${cid}`, "success", 2500);
          } else {
            showToast(data.message || "Failed to toggle recording", "error", 3500);
          }
        } catch {
          showToast("Could not communicate with recording server", "error", 3500);
        } finally {
          btn.disabled = false;
          renderManualButtons();
          loadRecordings();
        }
      };
    });
  };

  const loadStorageStatus = async () => {
    try {
      const res = await fetch("/api/recordings/storage", { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      if (data.activeRecordingCameras) {
        activeRecordings = new Set(data.activeRecordingCameras);
        renderManualButtons();
      }
      if (storagePill && storageText && data.disk) {
        if (data.diskWarning) {
          storagePill.className = "storage-indicator-pill warn";
          storageText.textContent = `Disk Warning: ${data.disk.freeGb} GB free (Min ${data.minDiskFreeGb} GB)`;
        } else {
          storagePill.className = "storage-indicator-pill";
          storageText.textContent = `Storage: ${data.recordingsStorageGb} GB / ${data.maxStorageGb} GB max · Free: ${data.disk.freeGb} GB`;
        }
      }
    } catch {}
  };

  const loadRecordings = async () => {
    if (!segmentsList) return;
    const cid = camSelect ? camSelect.value : "";
    const dateVal = dateSelect ? dateSelect.value : "";
    const params = new URLSearchParams();
    if (cid) params.set("cameraId", cid);
    if (dateVal) params.set("date", dateVal);

    try {
      segmentsList.innerHTML = `<div class="segments-loading">Loading segments…</div>`;
      const res = await fetch(`/api/recordings?${params.toString()}`, { cache: "no-store" });
      if (!res.ok) {
        segmentsList.innerHTML = `<div class="segments-empty">Failed to load recordings</div>`;
        return;
      }
      const data = await res.json();
      const recs = data.recordings || [];

      if (timelineCount) {
        timelineCount.textContent = `${recs.length} clips`;
      }

      if (recs.length === 0) {
        segmentsList.innerHTML = `<div class="segments-empty">No recordings found for the selected filter.</div>`;
        return;
      }

      segmentsList.innerHTML = recs.map(r => {
        const isActive = r.id === currentSelectedId;
        const dur = r.durationSeconds ? `${Math.round(r.durationSeconds)}s` : "—";
        const size = formatBytes(r.fileSizeBytes);
        const dateStr = r.startTime ? new Intl.DateTimeFormat([], { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date(r.startTime)) : "";
        const badgeClass = r.mode === "motion" ? "motion" : "continuous";
        const badgeText = r.mode === "motion" ? "Motion" : "Segment";

        return `<div class="segment-item ${isActive ? 'active' : ''}" data-segment-id="${escapeHtml(r.id)}">
          <div class="segment-meta">
            <span class="segment-name">${escapeHtml(r.fileName)}</span>
            <div class="segment-sub">
              <span>${escapeHtml(r.cameraId)}</span>
              <span>·</span>
              <span>${dateStr}</span>
              <span>·</span>
              <span>${dur} (${size})</span>
            </div>
          </div>
          <span class="segment-badge ${badgeClass}">${badgeText}</span>
        </div>`;
      }).join("");

      segmentsList.querySelectorAll("[data-segment-id]").forEach(item => {
        item.onclick = () => {
          const segId = item.dataset.segmentId;
          const rec = recs.find(x => x.id === segId);
          if (rec) playSegment(rec);
        };
      });
    } catch {
      segmentsList.innerHTML = `<div class="segments-empty">Could not connect to recording server</div>`;
    }
  };

  const playSegment = (rec) => {
    currentSelectedId = rec.id;
    document.querySelectorAll(".segment-item").forEach(el => {
      el.classList.toggle("active", el.dataset.segmentId === rec.id);
    });

    if (currentTitle) {
      currentTitle.textContent = `${rec.fileName} (${formatBytes(rec.fileSizeBytes)})`;
    }

    if (downloadBtn) {
      downloadBtn.href = `/api/recordings/download?id=${encodeURIComponent(rec.id)}`;
      downloadBtn.style.display = "inline-flex";
    }

    if (deleteBtn) {
      deleteBtn.style.display = "inline-flex";
      deleteBtn.onclick = async () => {
        if (!confirm(`Delete recording '${rec.fileName}'?`)) return;
        deleteBtn.disabled = true;
        try {
          const res = await fetch(`/api/recordings?id=${encodeURIComponent(rec.id)}`, { method: "DELETE" });
          const d = await res.json();
          if (d.success) {
            showToast("Recording deleted", "success", 2500);
            if (video) {
              video.pause();
              video.removeAttribute("src");
              video.load();
            }
            if (placeholder) placeholder.classList.remove("hidden");
            if (currentTitle) currentTitle.textContent = "No segment selected";
            downloadBtn.style.display = "none";
            deleteBtn.style.display = "none";
            currentSelectedId = null;
            loadRecordings();
            loadStorageStatus();
          } else {
            showToast(d.message || "Failed to delete recording", "error", 3500);
          }
        } catch {
          showToast("Error deleting recording", "error", 3500);
        } finally {
          deleteBtn.disabled = false;
        }
      };
    }

    if (video) {
      video.src = `/api/recordings/stream?id=${encodeURIComponent(rec.id)}`;
      if (placeholder) placeholder.classList.add("hidden");
      video.play().catch(() => {});
    }
  };

  if (camSelect) camSelect.onchange = loadRecordings;
  if (dateSelect) dateSelect.onchange = loadRecordings;
  if (refreshBtn) {
    refreshBtn.onclick = () => {
      loadRecordings();
      loadStorageStatus();
    };
  }

  renderManualButtons();
  loadStorageStatus();
  loadRecordings();
  setInterval(loadStorageStatus, 10000);
}

function initEventsTimeline() {
  const camSelect = document.querySelector("#events-cam-select");
  const dateSelect = document.querySelector("#events-date-select");
  const scoreSelect = document.querySelector("#events-score-select");
  const refreshBtn = document.querySelector("#events-refresh-btn");
  const cardsGrid = document.querySelector("#events-cards-grid");
  const countLabel = document.querySelector("#events-list-count");
  const navCount = document.querySelector("#nav-events-count");
  const fpsStat = document.querySelector("#events-fps-stat");
  const storageStat = document.querySelector("#events-storage-stat");
  const statusPill = document.querySelector("#events-status-pill");

  // Modal elements
  const modal = document.querySelector("#event-dialog");
  const modalImg = document.querySelector("#event-modal-img");
  const modalBbox = document.querySelector("#event-modal-bbox");
  const modalMeta = document.querySelector("#event-modal-meta");
  const modalTitle = document.querySelector("#event-modal-title");
  const modalJumpBtn = document.querySelector("#event-modal-jump-playback");
  const modalDelBtn = document.querySelector("#event-modal-delete-btn");
  const closeBtn = document.querySelector("#close-event-dialog-btn");
  const closeAction = document.querySelector("#close-event-dialog-action");

  let currentSelectedEvent = null;

  // Populate camera select
  if (camSelect) {
    camSelect.innerHTML = `<option value="">All cameras</option>` +
      cameras.map(c => `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)}</option>`).join("");
  }

  // Close modal handlers
  if (closeBtn) closeBtn.onclick = () => modal.close();
  if (closeAction) closeAction.onclick = () => modal.close();

  const loadStats = async () => {
    try {
      const res = await fetch("/api/events/stats", { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      if (fpsStat) fpsStat.textContent = `FPS: ${data.analyticsFps?.toFixed(1) || "0.0"}`;
      if (storageStat) storageStat.textContent = `Storage: ${data.storageMb || 0} MB / ${data.maxStorageMb || 1000} MB`;
      if (navCount) navCount.textContent = data.eventsToday || 0;
      if (statusPill) {
        statusPill.title = `Total events: ${data.totalEvents}, today: ${data.eventsToday}`;
      }
    } catch {}
  };

  const loadEvents = async () => {
    if (!cardsGrid) return;
    const cid = camSelect ? camSelect.value : "";
    const dt = dateSelect ? dateSelect.value : "";
    const minScore = scoreSelect ? scoreSelect.value : "";

    const params = new URLSearchParams();
    if (cid) params.set("cameraId", cid);
    if (dt) params.set("date", dt);
    if (minScore) params.set("minScore", minScore);
    params.set("limit", "60");

    try {
      const res = await fetch(`/api/events?${params.toString()}`, { cache: "no-store" });
      if (!res.ok) throw new Error("Failed to load events");
      const data = await res.json();
      const events = data.events || [];

      if (countLabel) countLabel.textContent = `${events.length} event${events.length === 1 ? '' : 's'}`;

      if (events.length === 0) {
        cardsGrid.innerHTML = `
          <div class="segments-empty" style="grid-column: 1 / -1; padding: 40px 10px;">
            No motion events detected matching current filters.
          </div>`;
        return;
      }

      cardsGrid.innerHTML = events.map(evt => {
        const bbox = evt.boundingBox || { x: 0, y: 0, width: 0, height: 0 };
        const leftPct = (bbox.x * 100).toFixed(1);
        const topPct = (bbox.y * 100).toFixed(1);
        const widthPct = (bbox.width * 100).toFixed(1);
        const heightPct = (bbox.height * 100).toFixed(1);

        return `
        <div class="event-card" data-event-id="${escapeHtml(evt.id)}">
          <div class="event-thumb-wrap" data-open-event="${escapeHtml(evt.id)}">
            <img class="event-thumb-img" src="/api/events/snapshot?id=${encodeURIComponent(evt.id)}" alt="Snapshot" loading="lazy" />
            <div class="event-bbox-overlay" style="left: ${leftPct}%; top: ${topPct}%; width: ${widthPct}%; height: ${heightPct}%;"></div>
            <span class="event-score-pill">Score: ${evt.score}%</span>
          </div>
          <div class="event-card-body">
            <div class="event-card-top">
              <span class="event-cam-badge">${escapeHtml(evt.cameraName || evt.cameraId)}</span>
              <span class="event-duration">${evt.durationSeconds || 0}s motion</span>
            </div>
            <div class="event-timestamp">${escapeHtml(evt.isoTime || '')}</div>
            <div class="event-card-actions">
              <a href="#playback" class="event-btn-link" data-jump-playback="${escapeHtml(evt.cameraId)}" data-timestamp="${evt.timestamp}">Jump to Playback</a>
              <button type="button" class="event-del-btn" data-del-event="${escapeHtml(evt.id)}">Delete</button>
            </div>
          </div>
        </div>`;
      }).join("");

      // Open lightbox
      cardsGrid.querySelectorAll("[data-open-event]").forEach(wrap => {
        wrap.onclick = () => {
          const eid = wrap.dataset.openEvent;
          const evt = events.find(x => x.id === eid);
          if (evt) openEventModal(evt);
        };
      });

      // Jump to playback
      cardsGrid.querySelectorAll("[data-jump-playback]").forEach(link => {
        link.onclick = (e) => {
          e.preventDefault();
          const cid = link.dataset.jumpPlayback;
          const ts = parseInt(link.dataset.timestamp, 10);
          jumpToPlayback(cid, ts);
        };
      });

      // Delete event
      cardsGrid.querySelectorAll("[data-del-event]").forEach(btn => {
        btn.onclick = async (e) => {
          e.stopPropagation();
          const eid = btn.dataset.delEvent;
          if (!confirm("Delete this event and snapshot image?")) return;
          try {
            const dRes = await fetch(`/api/events?id=${encodeURIComponent(eid)}`, { method: "DELETE" });
            const dData = await dRes.json();
            if (dData.success) {
              showToast("Event deleted", "success", 2000);
              loadEvents();
              loadStats();
            } else {
              showToast(dData.message || "Failed to delete event", "error", 3000);
            }
          } catch {
            showToast("Error deleting event", "error", 3000);
          }
        };
      });

    } catch (e) {
      cardsGrid.innerHTML = `
        <div class="segments-empty" style="grid-column: 1 / -1;">
          Could not connect to event timeline service
        </div>`;
    }
  };

  const openEventModal = (evt) => {
    currentSelectedEvent = evt;
    if (modalTitle) modalTitle.textContent = `${evt.cameraName || evt.cameraId} · ${evt.isoTime}`;
    if (modalImg) modalImg.src = `/api/events/snapshot?id=${encodeURIComponent(evt.id)}`;

    if (modalBbox) {
      const b = evt.boundingBox;
      if (b && b.width > 0 && b.height > 0) {
        modalBbox.style.display = "block";
        modalBbox.style.left = `${(b.x * 100).toFixed(1)}%`;
        modalBbox.style.top = `${(b.y * 100).toFixed(1)}%`;
        modalBbox.style.width = `${(b.width * 100).toFixed(1)}%`;
        modalBbox.style.height = `${(b.height * 100).toFixed(1)}%`;
      } else {
        modalBbox.style.display = "none";
      }
    }

    if (modalMeta) {
      modalMeta.innerHTML = `
        <div class="event-meta-cell">
          <span class="event-meta-cell-label">Camera</span>
          <span class="event-meta-cell-value">${escapeHtml(evt.cameraName || evt.cameraId)}</span>
        </div>
        <div class="event-meta-cell">
          <span class="event-meta-cell-label">Motion Score</span>
          <span class="event-meta-cell-value">${evt.score}%</span>
        </div>
        <div class="event-meta-cell">
          <span class="event-meta-cell-label">Duration</span>
          <span class="event-meta-cell-value">${evt.durationSeconds || 0}s</span>
        </div>
        <div class="event-meta-cell">
          <span class="event-meta-cell-label">Timestamp</span>
          <span class="event-meta-cell-value">${escapeHtml(evt.isoTime)}</span>
        </div>
        <div class="event-meta-cell">
          <span class="event-meta-cell-label">Snapshot Size</span>
          <span class="event-meta-cell-value">${formatBytes(evt.fileSizeBytes)}</span>
        </div>
      `;
    }

    if (modalJumpBtn) {
      modalJumpBtn.onclick = (e) => {
        e.preventDefault();
        modal.close();
        jumpToPlayback(evt.cameraId, evt.timestamp);
      };
    }

    if (modalDelBtn) {
      modalDelBtn.onclick = async () => {
        if (!confirm("Delete this event and snapshot?")) return;
        try {
          const dRes = await fetch(`/api/events?id=${encodeURIComponent(evt.id)}`, { method: "DELETE" });
          const dData = await dRes.json();
          if (dData.success) {
            modal.close();
            showToast("Event deleted", "success", 2000);
            loadEvents();
            loadStats();
          }
        } catch {}
      };
    }

    modal.showModal();
  };

  const jumpToPlayback = (cid, timestampMs) => {
    // Navigate to #playback
    const pbLink = document.querySelector('.nav-link[href="#playback"]');
    if (pbLink) pbLink.click();
    const pbSec = document.getElementById("playback");
    if (pbSec) pbSec.scrollIntoView({ behavior: "smooth" });

    // Set filter in playback
    const pbCam = document.querySelector("#playback-cam-select");
    const pbDate = document.querySelector("#playback-date-select");
    if (pbCam) {
      pbCam.value = cid;
      pbCam.dispatchEvent(new Event("change"));
    }
    if (pbDate && timestampMs) {
      const dt = new Date(timestampMs).toISOString().split("T")[0];
      pbDate.value = dt;
      pbDate.dispatchEvent(new Event("change"));
    }
    showToast(`Jumped to playback for ${cid}`, "info", 3000);
  };

  if (camSelect) camSelect.onchange = loadEvents;
  if (dateSelect) dateSelect.onchange = loadEvents;
  if (scoreSelect) scoreSelect.onchange = loadEvents;
  if (refreshBtn) {
    refreshBtn.onclick = () => {
      loadEvents();
      loadStats();
    };
  }

  loadStats();
  loadEvents();
  setInterval(loadStats, 5000);
  setInterval(loadEvents, 10000);
}

// Initial boot
initNav();
initSetupGuide();
initServiceControls();
initPlayback();
initPlaybackZoom();
initEventsTimeline();
initCameraFilter();
render();
restoreLayoutPreference();

// Start periodic telemetry poller (every 2s)
setInterval(pollMetrics, 2000);
pollMetrics();

// Start Smart Health Monitor poller (every 3s)
setInterval(pollHealth, 3000);
pollHealth();
