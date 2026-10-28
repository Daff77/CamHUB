const DEFAULT_CAMERAS = [
  {
    id: "v380-1",
    name: "V380 Pro · Kamera 1",
    location: "Area Utama (192.168.100.24 · ID: 124095217)",
    brand: "V380 Pro / V380Decoder-Latest",
    url: "http://192.168.100.11:8080/stream.mjpg",
    snapshotUrl: "http://192.168.100.11:8080/snapshot",
    hint: "HTTP :8080 · MJPEG (LAN)"
  },
  {
    id: "v380-2",
    name: "V380 Pro · Garasi",
    location: "Garasi (Cloud Adapter · ID: 97357757)",
    brand: "V380 Pro / V380Decoder-Fork",
    url: "http://192.168.100.11:8081/stream.mjpg",
    snapshotUrl: "http://192.168.100.11:8081/snapshot",
    hint: "HTTP :8081 · MJPEG (Cloud)"
  },
  {
    id: "okam-3",
    name: "O Kam Pro · Kamera 3",
    location: "Menunggu Pengaturan Protokol",
    brand: "O Kam Pro (Adapter Pending)",
    url: "",
    snapshotUrl: "",
    hint: "Adapter belum dikonfigurasi"
  }
];

const STORAGE_KEY = "camhub.mvp.cameras.v3";
const PREV_STORAGE_KEY = "camhub.mvp.cameras.v2";
const LEGACY_STORAGE_KEY = "camhub.mvp.cameras.v1";

let cameras = loadCameras();
const connectionStates = new Map();
const watchdogs = new Map();

const grid = document.querySelector("#camera-grid");
const dialog = document.querySelector("#config-dialog");
const configForm = document.querySelector("#config-form");
const closeDialogBtn = document.querySelector("#close-dialog-btn");
const cancelDialogBtn = document.querySelector("#cancel-dialog-btn");

function loadCameras() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY) || localStorage.getItem(PREV_STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      if (Array.isArray(saved)) {
        return DEFAULT_CAMERAS.map((def, idx) => {
          const legacyId = ["v380-a", "v380-b", "okam-c"][idx];
          const matched = saved.find(item => item.id === def.id || item.id === legacyId);
          if (matched) {
            const isGenericDefault = !matched.location || matched.location.includes("Point") || matched.location.includes("Local network") || matched.location.includes("Area Utama / Indoor");
            return {
              ...def,
              ...matched,
              id: def.id,
              name: matched.name || def.name,
              location: isGenericDefault ? def.location : matched.location,
              brand: isGenericDefault ? def.brand : (matched.brand || def.brand),
              url: matched.url !== undefined && matched.url !== "" ? matched.url : def.url,
              snapshotUrl: matched.snapshotUrl !== undefined && matched.snapshotUrl !== "" ? matched.snapshotUrl : def.snapshotUrl,
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

  const statusBadge = card.querySelector(`[data-status="${CSS.escape(id)}"]`);
  const livePill = card.querySelector(`[data-live-pill="${CSS.escape(id)}"]`);
  const placeholder = card.querySelector(`[data-placeholder="${CSS.escape(id)}"]`);
  const placeholderIcon = card.querySelector(`[data-placeholder-icon="${CSS.escape(id)}"]`);
  const placeholderTitle = card.querySelector(`[data-placeholder-title="${CSS.escape(id)}"]`);
  const placeholderDetail = card.querySelector(`[data-placeholder-detail="${CSS.escape(id)}"]`);
  const retryBtn = card.querySelector(`[data-retry-btn="${CSS.escape(id)}"]`);
  const configureBtnInPlaceholder = card.querySelector(`[data-placeholder-config="${CSS.escape(id)}"]`);

  if (statusBadge) {
    statusBadge.className = "status";
    if (status === "online") {
      statusBadge.classList.add("online");
      statusBadge.textContent = "Live · Connected";
    } else if (status === "connecting") {
      statusBadge.classList.add("connecting");
      statusBadge.textContent = "Connecting…";
    } else if (status === "offline") {
      statusBadge.classList.add("offline");
      statusBadge.textContent = "No Signal / Offline";
    } else {
      statusBadge.textContent = "Not Configured";
    }
  }

  if (livePill) {
    livePill.classList.toggle("hidden", status !== "online");
  }

  if (placeholder) {
    placeholder.classList.toggle("hidden", status === "online");

    if (status === "connecting") {
      if (placeholderIcon) placeholderIcon.innerHTML = '<div class="spinner"></div>';
      if (placeholderTitle) placeholderTitle.textContent = "Connecting to camera stream…";
      if (placeholderDetail) placeholderDetail.textContent = "Establishing local connection with V380Decoder…";
      if (retryBtn) retryBtn.style.display = "none";
      if (configureBtnInPlaceholder) configureBtnInPlaceholder.style.display = "none";
    } else if (status === "offline") {
      if (placeholderIcon) placeholderIcon.innerHTML = '<span class="placeholder-icon">⚠</span>';
      if (placeholderTitle) placeholderTitle.textContent = "Video Stream Unavailable";
      if (placeholderDetail) placeholderDetail.textContent = message || "Cannot reach local decoder. Ensure the V380Decoder process is running.";
      if (retryBtn) retryBtn.style.display = "inline-flex";
      if (configureBtnInPlaceholder) configureBtnInPlaceholder.style.display = "none";
    } else if (status === "unconfigured") {
      if (placeholderIcon) placeholderIcon.innerHTML = '<span class="placeholder-icon">⚙</span>';
      if (placeholderTitle) placeholderTitle.textContent = "Camera Adapter Not Configured";
      if (placeholderDetail) placeholderDetail.textContent = "Streaming protocol pending compatibility verification. Click Configure once URL is known.";
      if (retryBtn) retryBtn.style.display = "none";
      if (configureBtnInPlaceholder) configureBtnInPlaceholder.style.display = "inline-flex";
    }
  }

  updateSummary();
}

function updateSummary() {
  const onlineCount = cameras.filter((camera) => connectionStates.get(camera.id)?.status === "online").length;
  const onlineEl = document.querySelector("#online-count");
  const summaryTotalEl = document.querySelector("#summary-total");
  const totalEl = document.querySelector("#total-count");
  const navCountEl = document.querySelector("#nav-camera-count");
  const brandsEl = document.querySelector("#brands-count");
  const lastUpdatedEl = document.querySelector("#last-updated");

  if (onlineEl) onlineEl.textContent = String(onlineCount);
  if (summaryTotalEl) summaryTotalEl.textContent = ` / ${cameras.length}`;
  if (totalEl) totalEl.textContent = String(cameras.length).padStart(2, "0");
  if (navCountEl) navCountEl.textContent = String(cameras.length);

  const uniqueBrands = new Set(cameras.map(c => (c.brand || "").split("/")[0].trim()).filter(Boolean));
  if (brandsEl) brandsEl.textContent = String(Math.max(uniqueBrands.size, 1)).padStart(2, "0");

  if (lastUpdatedEl) {
    lastUpdatedEl.textContent = `Last status check · ${new Date().toLocaleTimeString()}`;
  }
}

function startStream(id) {
  const camera = cameras.find((item) => item.id === id);
  if (!camera) return;

  clearWatchdog(id);

  if (!camera.url) {
    setConnection(id, "unconfigured", "Adapter belum dikonfigurasi.");
    return;
  }

  setConnection(id, "connecting");

  const img = document.querySelector(`[data-feed="${CSS.escape(id)}"]`);
  if (!img) return;

  // Reset existing listeners to avoid duplicate calls
  img.onload = null;
  img.onerror = null;

  // Set timeout watchdog (8 seconds)
  const timer = setTimeout(() => {
    if (connectionStates.get(id)?.status === "connecting") {
      setConnection(id, "offline", "Connection timed out (8s). Local decoder did not return any frames.");
    }
  }, 8000);
  watchdogs.set(id, timer);

  img.onload = () => {
    clearWatchdog(id);
    setConnection(id, "online");
  };

  img.onerror = () => {
    clearWatchdog(id);
    const portMatch = camera.url.match(/:(\d+)/);
    const portNote = portMatch ? `port :${portMatch[1]}` : "stream URL";
    setConnection(id, "offline", `Connection failed on ${portNote}. Verify decoder is active on that port.`);
  };

  // Add cache buster query parameter to prevent browser caching stale or broken streams
  const cacheBuster = `camhub_t=${Date.now()}`;
  const sep = camera.url.includes("?") ? "&" : "?";
  img.src = `${camera.url}${sep}${cacheBuster}`;
}

function render() {
  grid.innerHTML = cameras.map((camera, index) => {
    const stateObj = connectionStates.get(camera.id);
    const status = stateObj?.status || (camera.url ? "connecting" : "unconfigured");
    const statusClass = status === "online" ? "online" : status === "connecting" ? "connecting" : status === "offline" ? "offline" : "";
    const statusLabel = status === "online" ? "Live · Connected" : status === "connecting" ? "Connecting…" : status === "offline" ? "No Signal / Offline" : "Not Configured";

    return `
      <article class="camera-card" data-camera="${escapeHtml(camera.id)}">
        <div class="camera-head">
          <div class="camera-title">
            <div class="camera-symbol">▣</div>
            <div>
              <h3>${escapeHtml(camera.name)}</h3>
              <div class="camera-location">${escapeHtml(camera.location)}</div>
            </div>
          </div>
          <span class="status ${statusClass}" data-status="${escapeHtml(camera.id)}">${statusLabel}</span>
        </div>

        <div class="feed-wrap">
          <div class="live-pill ${status === 'online' ? '' : 'hidden'}" data-live-pill="${escapeHtml(camera.id)}">
            <span class="pulse-live"></span>LIVE
          </div>

          <img
            class="camera-feed"
            data-feed="${escapeHtml(camera.id)}"
            alt="Live feed: ${escapeHtml(camera.name)}"
          />

          <div class="feed-placeholder" data-placeholder="${escapeHtml(camera.id)}">
            <div data-placeholder-icon="${escapeHtml(camera.id)}">
              ${status === "connecting" ? '<div class="spinner"></div>' : status === "offline" ? '<span class="placeholder-icon">⚠</span>' : '<span class="placeholder-icon">⚙</span>'}
            </div>
            <strong data-placeholder-title="${escapeHtml(camera.id)}">
              ${status === "connecting" ? "Connecting to camera stream…" : status === "offline" ? "Video Stream Unavailable" : "Camera Adapter Not Configured"}
            </strong>
            <small data-placeholder-detail="${escapeHtml(camera.id)}">
              ${status === "connecting" ? "Establishing local connection with V380Decoder…" : status === "offline" ? "Cannot reach local decoder. Ensure the V380Decoder process is running." : "Streaming protocol pending compatibility verification. Click Configure once URL is known."}
            </small>
            <button class="retry-btn" data-retry-btn="${escapeHtml(camera.id)}" style="${status === 'offline' ? 'display:inline-flex;' : 'display:none;'}">
              ↻ Retry Connection
            </button>
            <button class="retry-btn" data-placeholder-config="${escapeHtml(camera.id)}" style="${status === 'unconfigured' ? 'display:inline-flex;' : 'display:none;'}">
              ⚙ Configure Stream
            </button>
          </div>

          <span class="feed-corner">CAM ${String(index + 1).padStart(2, "0")}</span>
          <span class="feed-bottom">${escapeHtml(camera.hint)}</span>
        </div>

        <div class="camera-meta">
          <span title="${escapeHtml(camera.brand)}">${escapeHtml(camera.brand)}</span>
          <div class="camera-actions">
            <button class="small-button" data-refresh="${escapeHtml(camera.id)}" title="Reload stream">↻ Reload</button>
            <button class="small-button" data-configure="${escapeHtml(camera.id)}" title="Edit camera configuration">⚙ Configure</button>
          </div>
        </div>
      </article>`;
  }).join("");

  updateSummary();
  attachEvents();

  // Initiate streams
  cameras.forEach((camera) => {
    startStream(camera.id);
  });
}

function attachEvents() {
  document.querySelectorAll("[data-configure]").forEach((button) => {
    button.onclick = () => openConfig(button.dataset.configure);
  });

  document.querySelectorAll("[data-placeholder-config]").forEach((button) => {
    button.onclick = () => openConfig(button.dataset.placeholderConfig);
  });

  document.querySelectorAll("[data-refresh]").forEach((button) => {
    button.onclick = () => startStream(button.dataset.refresh);
  });

  document.querySelectorAll("[data-retry-btn]").forEach((button) => {
    button.onclick = () => startStream(button.dataset.retryBtn);
  });
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

  if (urlInput) {
    try {
      const parsed = new URL(urlInput);
      camera.hint = `Port :${parsed.port || (parsed.protocol === "https:" ? 443 : 80)} · MJPEG`;
    } catch {
      camera.hint = "MJPEG";
    }
  } else {
    camera.hint = "Adapter belum dikonfigurasi";
  }

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

// Periodic liveness check: when tab regains focus, refresh active streams
window.addEventListener("focus", () => {
  cameras.forEach((camera) => {
    if (camera.url && connectionStates.get(camera.id)?.status === "offline") {
      startStream(camera.id);
    }
  });
});

// Setup Guide script tabs & copy functionality
const SETUP_SCRIPTS = {
  cam1: `cd "$HOME\\V380Decoder-Latest"

$user1 = Read-Host "Username kamera 1"
$secure1 = Read-Host "Password kamera 1" -AsSecureString
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
  --quality sd \`
  --enable-api \`
  --http-port 8080 \`
  --rtsp-port 8554 \`
  --debug

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr1)
Remove-Variable pass1, secure1, user1 -ErrorAction SilentlyContinue`,

  cam2: `cd "$HOME\\V380Decoder-Fork"

dotnet build

$user2 = Read-Host "Username kamera 2"
$secure2 = Read-Host "Password kamera 2" -AsSecureString
$ptr2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure2)
$pass2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr2)

dotnet run --no-build -- \`
  --id 97357757 \`
  --username $user2 \`
  --password $pass2 \`
  --source cloud \`
  --output rtsp \`
  --quality sd \`
  --enable-api \`
  --http-port 8081 \`
  --rtsp-port 8555 \`
  --debug

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr2)
Remove-Variable pass2, secure2, user2 -ErrorAction SilentlyContinue`,

  all: `# ==========================================
# 1. KAMERA 1 — V380Decoder-Latest (Port 8080)
# ==========================================
cd "$HOME\\V380Decoder-Latest"

$user1 = Read-Host "Username kamera 1"
$secure1 = Read-Host "Password kamera 1" -AsSecureString
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
  --quality sd \`
  --enable-api \`
  --http-port 8080 \`
  --rtsp-port 8554 \`
  --debug

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr1)
Remove-Variable pass1, secure1, user1 -ErrorAction SilentlyContinue

# ==========================================
# 2. KAMERA 2 — Garasi V380Decoder-Fork (Port 8081)
# ==========================================
cd "$HOME\\V380Decoder-Fork"

dotnet build

$user2 = Read-Host "Username kamera 2"
$secure2 = Read-Host "Password kamera 2" -AsSecureString
$ptr2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure2)
$pass2 = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr2)

dotnet run --no-build -- \`
  --id 97357757 \`
  --username $user2 \`
  --password $pass2 \`
  --source cloud \`
  --output rtsp \`
  --quality sd \`
  --enable-api \`
  --http-port 8081 \`
  --rtsp-port 8555 \`
  --debug

[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr2)
Remove-Variable pass2, secure2, user2 -ErrorAction SilentlyContinue`
};

function initSetupGuide() {
  const codeEl = document.querySelector("#setup-script-code");
  const copyBtn = document.querySelector("#copy-script-btn");
  const tabButtons = document.querySelectorAll("[data-script-tab]");

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
        copyBtn.textContent = "✓ Tersalin!";
        setTimeout(() => {
          copyBtn.textContent = originalText;
        }, 2000);
      } catch (err) {
        console.warn("Clipboard copy fallback", err);
        const range = document.createRange();
        range.selectNodeContents(codeEl);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
    });
  }
}

initSetupGuide();

// Initial boot
render();
