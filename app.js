const DEFAULT_CAMERAS = [
  {
    id: "v380-1",
    name: "Camera 1 · Indoor",
    location: "192.168.100.24 · ID 124095217 · Port 8080",
    brand: "V380 Pro / V380Decoder-Latest",
    url: "http://192.168.100.11:8080/stream.mjpg",
    snapshotUrl: "http://192.168.100.11:8080/snapshot",
    hint: "LAN"
  },
  {
    id: "v380-2",
    name: "Camera 2 · Garage",
    location: "192.168.100.4 · ID 97357757 · Port 8081",
    brand: "V380 Pro / V380Decoder-Fork",
    url: "http://192.168.100.11:8081/stream.mjpg",
    snapshotUrl: "http://192.168.100.11:8081/snapshot",
    hint: "LAN"
  },
  {
    id: "okam-3",
    name: "Camera 3 · O Kam Pro",
    location: "Pending protocol setup",
    brand: "O Kam Pro (Adapter pending)",
    url: "",
    snapshotUrl: "",
    hint: "Not configured"
  }
];

const STORAGE_KEY = "camhub.control.cameras.v1";
const PREV_KEYS = ["camhub.mvp.cameras.v3", "camhub.mvp.cameras.v2", "camhub.mvp.cameras.v1"];

let cameras = loadCameras();
const connectionStates = new Map();
const watchdogs = new Map();

const grid = document.querySelector("#camera-grid");
const dialog = document.querySelector("#config-dialog");
const configForm = document.querySelector("#config-form");
const closeDialogBtn = document.querySelector("#close-dialog-btn");
const cancelDialogBtn = document.querySelector("#cancel-dialog-btn");

function getFormattedTime() {
  return new Intl.DateTimeFormat([], {
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date());
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

  // Timeout watchdog (8s)
  const timer = setTimeout(() => {
    if (connectionStates.get(id)?.status === "connecting") {
      setConnection(id, "offline", "Connection timed out (8s). No frames received from decoder.");
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
              <div class="tile-micro" data-micro="${escapeHtml(camera.id)}">${timeStr}</div>
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
          <div class="tile-details">
            <span class="details-text" title="${escapeHtml(camera.location)}">${escapeHtml(camera.location)}</span>
          </div>
          <div class="tile-actions">
            <button class="button button-small" data-refresh="${escapeHtml(camera.id)}" type="button" title="Reload feed">Reload</button>
            <button class="button button-small" data-configure="${escapeHtml(camera.id)}" type="button" title="Configure camera">Configure</button>
            <button class="button button-small button-focus" data-focus="${escapeHtml(camera.id)}" type="button" title="Expand to full row">Focus</button>
          </div>
        </div>
      </article>`;
  }).join("");

  updateSummary();
  attachEvents();

  cameras.forEach((camera) => {
    startStream(camera.id);
  });
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

  // Focus mode toggle (Section 5: "Clicking a tile expands it to full row (focus mode); click again to restore.")
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

  // Also allow clicking video area to toggle focus mode
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
Remove-Variable pass2, secure2, user2 -ErrorAction SilentlyContinue`
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

initSetupGuide();
render();
