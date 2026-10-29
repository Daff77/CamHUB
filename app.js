const DEFAULT_CAMERAS = [
  {
    id: "v380-1",
    name: "Camera 1 · Indoor",
    location: "192.168.100.24 · ID 124095217 · Port 8080",
    brand: "V380 Pro / V380Decoder-Latest",
    url: "http://192.168.100.11:8080/stream.mjpg",
    snapshotUrl: "http://192.168.100.11:8080/snapshot",
    metricsUrl: "http://192.168.100.11:8080/api/metrics",
    hint: "LAN"
  },
  {
    id: "v380-2",
    name: "Camera 2 · Garage",
    location: "192.168.100.4 · ID 97357757 · Port 8081",
    brand: "V380 Pro / V380Decoder-Fork",
    url: "http://192.168.100.11:8081/stream.mjpg",
    snapshotUrl: "http://192.168.100.11:8081/snapshot",
    metricsUrl: "http://192.168.100.11:8081/api/metrics",
    hint: "LAN"
  },
  {
    id: "okam-3",
    name: "Camera 3 · O Kam Pro",
    location: "192.168.100.6 · Port 10554 · VStarcam",
    brand: "O Kam Pro / VStarcam",
    url: "http://192.168.100.11:8082/stream.mjpg",
    snapshotUrl: "http://192.168.100.11:8082/snapshot",
    metricsUrl: "http://192.168.100.11:8082/api/metrics",
    hint: "LAN RTSP"
  }
];

const STORAGE_KEY = "camhub.control.cameras.v3";
const PREV_KEYS = ["camhub.control.cameras.v2", "camhub.control.cameras.v1", "camhub.mvp.cameras.v3", "camhub.mvp.cameras.v2", "camhub.mvp.cameras.v1"];

let cameras = loadCameras();
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
            const url = matched.url !== undefined && matched.url !== "" ? matched.url : def.url;
            return {
              ...def,
              ...matched,
              id: def.id,
              name: matched.name || def.name,
              location: isGenericDefault ? def.location : matched.location,
              brand: isGenericDefault ? def.brand : (matched.brand || def.brand),
              url: url,
              snapshotUrl: matched.snapshotUrl !== undefined && matched.snapshotUrl !== "" ? matched.snapshotUrl : def.snapshotUrl,
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
  const onlineCount = cameras.filter((camera) => connectionStates.get(camera.id)?.status === "online").length;
  const sentenceEl = document.querySelector("#status-sentence");
  const navCountEl = document.querySelector("#nav-camera-count");
  const timeStr = getFormattedTime();

  if (sentenceEl) {
    sentenceEl.textContent = `${onlineCount} of ${cameras.length} cameras connected. Checked ${timeStr}.`;
  }
  if (navCountEl) {
    navCountEl.textContent = String(cameras.length);
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

  grid.innerHTML = cameras.map((camera) => {
    const isUnconfigured = !camera.url;
    const stateObj = connectionStates.get(camera.id);
    const status = stateObj?.status || (camera.url ? "connecting" : "unconfigured");
    const statusClass = status;
    const statusWord = status === "online" ? "Live" : status === "connecting" ? "Connecting" : status === "offline" ? "Offline" : "Not configured";
    const placeholderMsg = stateObj?.message || (status === "connecting" ? "Connecting to camera stream…" : status === "offline" ? "Stream unavailable. Verify local decoder is active." : "Protocol adapter not configured.");

    return `
      <article class="camera-card ${isUnconfigured ? 'is-unconfigured' : ''}" data-camera="${escapeHtml(camera.id)}">
        <div class="video-container" data-video-wrap="${escapeHtml(camera.id)}">
          <div class="tile-scrim">
            <div class="tile-status-bar">
              <div class="tile-title-group">
                <span class="status-dot ${statusClass}" data-dot="${escapeHtml(camera.id)}"></span>
                <h3 class="tile-title">${escapeHtml(camera.name)}</h3>
                <span class="status-text" data-status-text="${escapeHtml(camera.id)}">${statusWord}</span>
              </div>
              <div class="tile-micro-group">
                <span class="ratio-badge" data-ratio="${escapeHtml(camera.id)}" style="display:none;"></span>
                <span class="tile-micro" data-micro="${escapeHtml(camera.id)}">${timeStr}</span>
              </div>
            </div>
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

  renderAnalyticsCards();
  updateSummary();
  attachEvents();

  cameras.forEach((camera) => {
    startStream(camera.id);
  });
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
          <span class="metric-card-chip">${escapeHtml(camera.hint || 'LAN')}</span>
        </div>

        <div class="metric-grid">
          <div class="metric-item">
            <span class="metric-label">Source stream rate</span>
            <span class="metric-value live" data-val-source-fps="${escapeHtml(camera.id)}">— fps</span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Transcode output</span>
            <span class="metric-value live" data-val-xcode-fps="${escapeHtml(camera.id)}">— fps</span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Pipeline latency</span>
            <span class="metric-value latency" data-val-latency="${escapeHtml(camera.id)}">— ms</span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Total frames</span>
            <span class="metric-value" data-val-frames="${escapeHtml(camera.id)}">—</span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Active subscribers</span>
            <span class="metric-value" data-val-clients="${escapeHtml(camera.id)}">—</span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Stream resolution</span>
            <span class="metric-value" data-val-resolution="${escapeHtml(camera.id)}">—</span>
          </div>
        </div>

        <div class="sparkline-wrap">
          <div class="sparkline-label">
            <span>FPS stability (last 30s)</span>
            <span data-val-fps-current="${escapeHtml(camera.id)}">—</span>
          </div>
          <svg class="sparkline-svg" data-sparkline="${escapeHtml(camera.id)}" viewBox="0 0 320 44" preserveAspectRatio="none">
            <line x1="0" y1="22" x2="320" y2="22" stroke="rgba(255,255,255,0.05)" stroke-width="1" stroke-dasharray="2 2" />
          </svg>
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

async function pollMetrics() {
  for (const camera of cameras) {
    if (!camera.metricsUrl) continue;
    try {
      const res = await fetch(camera.metricsUrl, { cache: "no-store" });
      if (!res.ok) continue;
      const data = await res.json();
      metricsData.set(camera.id, data);

      // Record history
      let history = metricsHistory.get(camera.id);
      if (!history) {
        history = [];
        metricsHistory.set(camera.id, history);
      }
      history.push(data.sourceFps || 0);
      if (history.length > 20) history.shift();

      // Update per-tile telemetry strip
      const fpsEl = document.querySelector(`[data-telemetry-fps="${CSS.escape(camera.id)}"]`);
      const latEl = document.querySelector(`[data-telemetry-lat="${CSS.escape(camera.id)}"]`);
      const clientsEl = document.querySelector(`[data-telemetry-clients="${CSS.escape(camera.id)}"]`);
      if (fpsEl) fpsEl.textContent = `${data.sourceFps?.toFixed(1) ?? '—'} fps`;
      if (latEl) latEl.textContent = `${Math.round(data.xcodeLatencyMs ?? 0)} ms`;
      if (clientsEl) clientsEl.textContent = `${data.activeRtspSessions ?? 0} RTSP · ${data.activeMjpegClients ?? 0} Web`;

      // Update analytics card
      const srcFps = document.querySelector(`[data-val-source-fps="${CSS.escape(camera.id)}"]`);
      const xcodeFps = document.querySelector(`[data-val-xcode-fps="${CSS.escape(camera.id)}"]`);
      const latVal = document.querySelector(`[data-val-latency="${CSS.escape(camera.id)}"]`);
      const framesVal = document.querySelector(`[data-val-frames="${CSS.escape(camera.id)}"]`);
      const clientsVal = document.querySelector(`[data-val-clients="${CSS.escape(camera.id)}"]`);
      const curFps = document.querySelector(`[data-val-fps-current="${CSS.escape(camera.id)}"]`);
      const mDot = document.querySelector(`[data-metric-dot="${CSS.escape(camera.id)}"]`);

      if (srcFps) srcFps.textContent = `${data.sourceFps?.toFixed(1) ?? '0.0'} fps`;
      if (xcodeFps) xcodeFps.textContent = `${data.xcodeOutFps?.toFixed(1) ?? '0.0'} fps`;
      if (latVal) latVal.textContent = `${Math.round(data.xcodeLatencyMs ?? 0)} ms`;
      if (framesVal) framesVal.textContent = Number(data.totalSourceFrames || 0).toLocaleString();
      if (clientsVal) clientsVal.textContent = `${data.activeRtspSessions ?? 0} RTSP · ${data.activeMjpegClients ?? 0} Web`;
      if (curFps) curFps.textContent = `${data.sourceFps?.toFixed(1) ?? '0.0'} fps`;
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
  }
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
      if (e.target.closest("button")) return;
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
    if (camera.url) {
      startStream(camera.id);
    }
  });
});

window.addEventListener("focus", () => {
  cameras.forEach((camera) => {
    if (camera.url && connectionStates.get(camera.id)?.status === "offline") {
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

// Initial boot
initNav();
initSetupGuide();
render();
restoreLayoutPreference();

// Start periodic telemetry poller (every 2s)
setInterval(pollMetrics, 2000);
pollMetrics();
