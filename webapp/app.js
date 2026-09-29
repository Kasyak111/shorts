/**
 * Кино-Редактор Субтитров — Telegram Mini App SPA
 */

// Initialize Telegram WebApp SDK if available
const tg = window.Telegram?.WebApp;
if (tg) {
  try {
    tg.ready();
    tg.expand();
    if (tg.enableClosingConfirmation) {
      tg.enableClosingConfirmation();
    }
  } catch (e) {
    console.warn("Telegram WebApp init warning:", e);
  }
}

// App State
const state = {
  clipId: null,
  clipInfo: {},
  cues: [],
  originalCues: [],
  globalShift: 0.0,
  activeCueId: null,
  isDirty: false,
  playbackSpeed: 1.0,
};

// DOM Elements
const el = {
  clipTitle: document.getElementById("clipTitle"),
  clipMeta: document.getElementById("clipMeta"),
  btnSwitchClip: document.getElementById("btnSwitchClip"),
  btnReload: document.getElementById("btnReload"),
  videoPlayer: document.getElementById("videoPlayer"),
  videoBox: document.getElementById("videoBox"),
  subOverlay: document.getElementById("subOverlay"),
  subText: document.getElementById("subText"),
  videoTapTarget: document.getElementById("videoTapTarget"),
  btnPlayPause: document.getElementById("btnPlayPause"),
  seekSlider: document.getElementById("seekSlider"),
  timeCurrent: document.getElementById("timeCurrent"),
  timeTotal: document.getElementById("timeTotal"),
  btnSpeed: document.getElementById("btnSpeed"),
  globalShiftValue: document.getElementById("globalShiftValue"),
  btnResetShift: document.getElementById("btnResetShift"),
  cuesCount: document.getElementById("cuesCount"),
  cuesList: document.getElementById("cuesList"),
  statusIndicator: document.getElementById("statusIndicator"),
  statusText: document.getElementById("statusText"),
  btnSaveRender: document.getElementById("btnSaveRender"),
  clipsModal: document.getElementById("clipsModal"),
  clipsList: document.getElementById("clipsList"),
  btnCloseModal: document.getElementById("btnCloseModal"),
  loadingOverlay: document.getElementById("loadingOverlay"),
  loadingTitle: document.getElementById("loadingTitle"),
  loadingMsg: document.getElementById("loadingMsg"),
  inputOldWord: document.getElementById("inputOldWord"),
  inputNewWord: document.getElementById("inputNewWord"),
  btnApplyWordReplace: document.getElementById("btnApplyWordReplace"),
};

// Format seconds into MM:SS.S
function formatTime(seconds) {
  if (isNaN(seconds) || seconds < 0) return "00:00.0";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 10);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${ms}`;
}

// Format seconds into ASS format 00:00:00.00
function formatAssTime(seconds) {
  if (isNaN(seconds) || seconds < 0) return "00:00.00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const cs = Math.floor((seconds % 1) * 100);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
}

function triggerHaptic(type = "light") {
  if (tg?.HapticFeedback) {
    try {
      if (type === "success") tg.HapticFeedback.notificationOccurred("success");
      else if (type === "warning") tg.HapticFeedback.notificationOccurred("warning");
      else tg.HapticFeedback.impactOccurred(type);
    } catch (_) {}
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ---------------- API & Data Loading ----------------
function telegramFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (tg?.initData) {
    headers.set("Authorization", `tma ${tg.initData}`);
  }
  return fetch(url, { ...options, headers, credentials: "same-origin" });
}

async function initApp() {
  const urlParams = new URLSearchParams(window.location.search);
  const requestedClip = urlParams.get("clip");

  try {
    let targetClipId = requestedClip;
    if (!targetClipId) {
      // Fetch latest clips list
      const resp = await telegramFetch("/api/clips");
      const data = await resp.json();
      if (data.clips && data.clips.length > 0) {
        targetClipId = data.clips[0].id;
      }
    }

    if (targetClipId) {
      await loadClip(targetClipId);
    } else {
      el.clipTitle.textContent = "Ролики не найдены";
      el.cuesList.innerHTML = '<div class="skeleton-card">Нет доступных роликов для редактирования. Сначала нашинкуйте ролик в Telegram!</div>';
    }
  } catch (err) {
    console.error("Failed to load clips:", err);
    el.clipTitle.textContent = "Ошибка загрузки";
  }
}

async function loadClip(clipId) {
  showLoading("Загрузка данных клипа...", "Получаем распарсенные субтитры и видеопоток");
  try {
    const resp = await telegramFetch(`/api/clip/${encodeURIComponent(clipId)}`);
    if (!resp.ok) throw new Error("Clip not found");
    const data = await resp.json();

    state.clipId = data.id;
    state.clipInfo = data;
    state.cues = JSON.parse(JSON.stringify(data.cues || []));
    state.originalCues = JSON.parse(JSON.stringify(data.cues || []));
    state.globalShift = 0.0;
    state.isDirty = false;
    updateDirtyState();

    // Render Titles
    el.clipTitle.textContent = data.title || data.id;
    el.clipMeta.textContent = `🍿 Фильм: ${data.film || 'Кино'} | Код: ${data.code || '777'}`;

    // Load Video
    el.videoPlayer.src = `/media/${encodeURIComponent(data.id)}/video`;
    el.videoPlayer.load();

    // Render Cues
    renderCuesList();
    updateGlobalShiftDisplay();
  } catch (err) {
    console.error("Load clip error:", err);
    alert("Не удалось загрузить клип: " + err.message);
  } finally {
    hideLoading();
  }
}

// ---------------- Video Player Synchronization ----------------
el.videoPlayer.addEventListener("loadedmetadata", () => {
  el.seekSlider.max = el.videoPlayer.duration || 100;
  el.timeTotal.textContent = formatTime(el.videoPlayer.duration);
});

el.videoPlayer.addEventListener("timeupdate", () => {
  const cur = el.videoPlayer.currentTime;
  el.seekSlider.value = cur;
  el.timeCurrent.textContent = formatTime(cur);
  syncSubtitles(cur);
});

el.videoPlayer.addEventListener("play", () => {
  el.videoBox.classList.remove("paused");
  el.btnPlayPause.textContent = "⏸";
});

el.videoPlayer.addEventListener("pause", () => {
  el.videoBox.classList.add("paused");
  el.btnPlayPause.textContent = "▶";
});

// Tap video box to toggle play/pause
el.videoTapTarget.addEventListener("click", () => {
  togglePlayPause();
});

el.btnPlayPause.addEventListener("click", () => {
  togglePlayPause();
});

function togglePlayPause() {
  if (el.videoPlayer.paused) {
    el.videoPlayer.play();
  } else {
    el.videoPlayer.pause();
  }
  triggerHaptic("light");
}

el.seekSlider.addEventListener("input", (e) => {
  const seekTo = parseFloat(e.target.value);
  el.videoPlayer.currentTime = seekTo;
  syncSubtitles(seekTo);
});

// Speed Toggle: 1x -> 1.25x -> 0.75x -> 1x
el.btnSpeed.addEventListener("click", () => {
  if (state.playbackSpeed === 1.0) state.playbackSpeed = 1.25;
  else if (state.playbackSpeed === 1.25) state.playbackSpeed = 0.75;
  else state.playbackSpeed = 1.0;

  el.videoPlayer.playbackRate = state.playbackSpeed;
  el.btnSpeed.textContent = `${state.playbackSpeed}x`;
  triggerHaptic("light");
});

// Real-time subtitle sync over video with live golden karaoke pop
function syncSubtitles(currentTime) {
  let matchedCue = null;

  for (let i = 0; i < state.cues.length; i++) {
    const c = state.cues[i];
    const s = c.start + state.globalShift;
    const e = c.end + state.globalShift;

    if (currentTime >= s && currentTime <= e) {
      matchedCue = c;
      break;
    }
  }

  if (matchedCue) {
    const relTime = currentTime - (matchedCue.start + state.globalShift);

    if (state.activeCueId !== matchedCue.id) {
      state.activeCueId = matchedCue.id;
      el.subText.classList.remove("pop");
      void el.subText.offsetWidth; // trigger reflow for animation
      el.subText.classList.add("pop");

      highlightActiveCueCard(matchedCue.id);
    }

    // Render words with live word-by-word golden highlight
    if (matchedCue.words && matchedCue.words.length > 0) {
      const htmlWords = matchedCue.words.map((w, idx) => {
        const isLast = (idx === matchedCue.words.length - 1);
        const isActive = (relTime >= w.rel_start && (isLast ? relTime <= w.rel_end + 0.15 : relTime < w.rel_end));
        return `<span class="sub-word ${isActive ? 'active-word' : ''}">${escapeHtml(w.word)}</span>`;
      }).join(" ");
      el.subText.innerHTML = htmlWords;
    } else {
      el.subText.textContent = matchedCue.text;
    }
  } else {
    if (state.activeCueId !== null) {
      state.activeCueId = null;
      el.subText.innerHTML = "";
      highlightActiveCueCard(null);
    }
  }
}

function highlightActiveCueCard(cueId) {
  document.querySelectorAll(".cue-card").forEach(card => {
    if (cueId !== null && card.dataset.id == cueId) {
      card.classList.add("active-cue");
      // Gentle auto-scroll into view if not manually focused
      if (document.activeElement?.tagName !== "TEXTAREA" && document.activeElement?.tagName !== "INPUT") {
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    } else {
      card.classList.remove("active-cue");
    }
  });
}

// ---------------- Render Cues List ----------------
function renderCuesList() {
  el.cuesCount.textContent = state.cues.length;
  if (!state.cues.length) {
    el.cuesList.innerHTML = '<div class="skeleton-card">Субтитры отсутствуют в файле.</div>';
    return;
  }

  el.cuesList.innerHTML = "";
  state.cues.forEach((cue, index) => {
    const card = document.createElement("div");
    card.className = "cue-card";
    card.dataset.id = cue.id;
    card.dataset.index = index;

    const dur = Math.max(0, cue.end - cue.start).toFixed(2);

    card.innerHTML = `
      <div class="cue-header">
        <div class="cue-badge">
          <span class="cue-num">#${index + 1}</span>
          <span class="cue-time-text" id="timeBadge_${cue.id}">[${formatAssTime(cue.start)} - ${formatAssTime(cue.end)}] (${dur}с)</span>
        </div>
        <button class="cue-play-btn" data-action="play" data-start="${cue.start}">▶ Слушать</button>
      </div>
      <textarea class="cue-text-input" rows="2" data-id="${cue.id}">${cue.text}</textarea>
      <div class="cue-timing-controls">
        <div class="timing-group">
          <span class="timing-label">Старт:</span>
          <button class="nudge-btn" data-action="nudge" data-target="start" data-delta="-0.1">-0.1</button>
          <button class="nudge-btn" data-action="nudge" data-target="start" data-delta="+0.1">+0.1</button>
        </div>
        <div class="timing-group">
          <span class="timing-label">Конец:</span>
          <button class="nudge-btn" data-action="nudge" data-target="end" data-delta="-0.1">-0.1</button>
          <button class="nudge-btn" data-action="nudge" data-target="end" data-delta="+0.1">+0.1</button>
        </div>
      </div>
    `;

    el.cuesList.appendChild(card);
  });

  // Attach event delegation for cues
  el.cuesList.addEventListener("input", (e) => {
    if (e.target.classList.contains("cue-text-input")) {
      const cueId = parseInt(e.target.dataset.id);
      const val = e.target.value.trim().toUpperCase();
      const cue = state.cues.find(c => c.id === cueId);
      if (cue) {
        cue.text = val;
        markDirty();
        // If current cue is active on video screen, update text immediately!
        if (state.activeCueId === cueId) {
          el.subText.textContent = val;
        }
      }
    }
  });

  el.cuesList.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;

    const action = btn.dataset.action;
    if (action === "play") {
      const startTime = parseFloat(btn.dataset.start) + state.globalShift;
      el.videoPlayer.currentTime = Math.max(0, startTime);
      el.videoPlayer.play();
      triggerHaptic("light");
    } else if (action === "nudge") {
      const card = btn.closest(".cue-card");
      const cueId = parseInt(card.dataset.id);
      const target = btn.dataset.target; // 'start' or 'end'
      const delta = parseFloat(btn.dataset.delta);
      nudgeCueTiming(cueId, target, delta, card);
      triggerHaptic("medium");
    }
  });
}

function nudgeCueTiming(cueId, target, delta, card) {
  const cue = state.cues.find(c => c.id === cueId);
  if (!cue) return;

  if (target === "start") {
    cue.start = Math.max(0, parseFloat((cue.start + delta).toFixed(2)));
    if (cue.start >= cue.end) cue.end = parseFloat((cue.start + 0.2).toFixed(2));
  } else if (target === "end") {
    cue.end = Math.max(cue.start + 0.1, parseFloat((cue.end + delta).toFixed(2)));
  }

  // Update badge
  const dur = Math.max(0, cue.end - cue.start).toFixed(2);
  const badge = card.querySelector(`#timeBadge_${cue.id}`);
  if (badge) {
    badge.textContent = `[${formatAssTime(cue.start)} - ${formatAssTime(cue.end)}] (${dur}с)`;
  }
  const playBtn = card.querySelector('[data-action="play"]');
  if (playBtn) {
    playBtn.dataset.start = cue.start;
  }

  card.classList.add("modified");
  markDirty();

  // Test play current nudge
  el.videoPlayer.currentTime = Math.max(0, cue.start + state.globalShift);
}

// ---------------- Global Timing Shifts ----------------
document.querySelectorAll(".shift-btn[data-shift]").forEach(btn => {
  btn.addEventListener("click", () => {
    const delta = parseFloat(btn.dataset.shift);
    state.globalShift = parseFloat((state.globalShift + delta).toFixed(2));
    updateGlobalShiftDisplay();
    markDirty();
    triggerHaptic("medium");
  });
});

el.btnResetShift.addEventListener("click", () => {
  state.globalShift = 0.0;
  updateGlobalShiftDisplay();
  markDirty();
  triggerHaptic("light");
});

function updateGlobalShiftDisplay() {
  const sign = state.globalShift >= 0 ? "+" : "";
  el.globalShiftValue.textContent = `${sign}${state.globalShift.toFixed(2)}с`;

  document.querySelectorAll(".shift-btn[data-shift]").forEach(b => {
    b.classList.remove("active-shift");
  });
}

// ---------------- Batch Word Replacement ----------------
el.btnApplyWordReplace.addEventListener("click", () => {
  const oldW = el.inputOldWord.value.trim();
  const newW = el.inputNewWord.value.trim();

  if (!oldW || !newW) {
    alert("Укажите оба слова для автозамены!");
    return;
  }

  let count = 0;
  const regex = new RegExp(`\\b${oldW}\\b`, "gi");

  state.cues.forEach(cue => {
    if (regex.test(cue.text)) {
      cue.text = cue.text.replace(regex, newW.toUpperCase());
      count++;
    }
  });

  if (count > 0) {
    renderCuesList();
    markDirty();
    triggerHaptic("success");
    alert(`Заменено вхождений: ${count}! Изменения отображены.`);
    el.inputOldWord.value = "";
    el.inputNewWord.value = "";
  } else {
    alert(`Слово «${oldW}» не найдено в субтитрах.`);
  }
});

// ---------------- Dirty & Save Logic ----------------
function markDirty() {
  state.isDirty = true;
  updateDirtyState();
}

function updateDirtyState() {
  if (state.isDirty) {
    el.statusIndicator.classList.add("active");
    el.statusText.textContent = "Есть изменения";
    el.btnSaveRender.disabled = false;
    if (tg?.MainButton) {
      tg.MainButton.text = "💾 Сохранить и собрать видео";
      tg.MainButton.show();
    }
  } else {
    el.statusIndicator.classList.remove("active");
    el.statusText.textContent = "Без изменений";
    el.btnSaveRender.disabled = true;
    if (tg?.MainButton) {
      tg.MainButton.hide();
    }
  }
}

el.btnSaveRender.addEventListener("click", () => {
  saveAndRender();
});

if (tg?.MainButton) {
  tg.MainButton.onClick(() => {
    saveAndRender();
  });
}

async function saveAndRender() {
  if (!state.clipId) return;

  triggerHaptic("heavy");
  showLoading("Сборка ролика...", "Применяем правки субтитров и пересобираем вертикальное видео FFmpeg...");

  try {
    const payload = {
      clip_id: state.clipId,
      global_shift: state.globalShift,
      cues: state.cues.map(c => ({
        id: c.id,
        start: c.start,
        end: c.end,
        text: c.text
      }))
    };

    const resp = await telegramFetch(`/api/clip/${encodeURIComponent(state.clipId)}/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const result = await resp.json();
    if (!resp.ok || !result.success) {
      throw new Error(result.error || "Ошибка сохранения");
    }

    triggerHaptic("success");
    state.isDirty = false;
    updateDirtyState();

    hideLoading();

    const okMsg = "✅ Ролик успешно пересобран!\nОбновленное видео отправлено прямо в ваш Telegram-чат.";
    if (tg) {
      tg.showAlert(okMsg, () => {
        tg.close();
      });
    } else {
      alert(okMsg);
    }
  } catch (err) {
    hideLoading();
    triggerHaptic("warning");
    alert("Ошибка пересборки: " + err.message);
  }
}

// ---------------- Clips Drawer / Modal ----------------
el.btnSwitchClip.addEventListener("click", async () => {
  triggerHaptic("light");
  showClipsModal();
});

el.btnCloseModal.addEventListener("click", () => {
  hideClipsModal();
});

async function showClipsModal() {
  el.clipsList.innerHTML = '<div class="skeleton-card">Загрузка списка...</div>';
  el.clipsModal.classList.remove("hidden");

  try {
    const resp = await telegramFetch("/api/clips");
    const data = await resp.json();
    if (data.clips && data.clips.length) {
      el.clipsList.innerHTML = "";
      data.clips.forEach(c => {
        const item = document.createElement("div");
        item.className = "clip-item-card";
        item.innerHTML = `
          <div class="clip-item-title">${c.title || c.id}</div>
          <div class="clip-item-sub">🍿 Фильм: ${c.film || 'Кино'} • Код: ${c.code || '777'}</div>
        `;
        item.addEventListener("click", () => {
          hideClipsModal();
          loadClip(c.id);
        });
        el.clipsList.appendChild(item);
      });
    } else {
      el.clipsList.innerHTML = '<div class="skeleton-card">Список пуст</div>';
    }
  } catch (err) {
    el.clipsList.innerHTML = '<div class="skeleton-card">Ошибка загрузки списка</div>';
  }
}

function hideClipsModal() {
  el.clipsModal.classList.add("hidden");
}

// ---------------- Loading Overlays ----------------
function showLoading(title, msg) {
  el.loadingTitle.textContent = title;
  el.loadingMsg.textContent = msg;
  el.loadingOverlay.classList.remove("hidden");
}

function hideLoading() {
  el.loadingOverlay.classList.add("hidden");
}

// Start app
initApp();
