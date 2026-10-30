const $ = (id) => document.getElementById(id);

const state = {
  file: null,
  objectUrl: null,
  result: null,
  visible: 48,
  busy: false,
  composing: false,
  composition: null,
};

const statusLabels = {
  empty: "未检测到笔迹",
  touches_border: "笔迹贴近边框",
  low_contrast: "笔迹对比度低",
  suspected_mismatch: "字符可能写错",
};

function formatBytes(size) {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(size / 1024))} KB`;
}

function setFile(file) {
  if (!file) return;
  if (file.size > 50 * 1024 * 1024) {
    clearFile();
    showError("文件不能超过 50 MB，请选择较小的扫描图或照片。");
    return;
  }
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.file = file;
  state.objectUrl = null;
  $("selected-name").textContent = file.name;
  $("selected-size").textContent = formatBytes(file.size);
  const preview = $("selected-preview");
  preview.replaceChildren();
  if (file.type.startsWith("image/")) {
    state.objectUrl = URL.createObjectURL(file);
    const image = document.createElement("img");
    image.src = state.objectUrl;
    image.alt = "";
    preview.append(image);
  } else {
    preview.textContent = "PDF";
  }
  $("selected-file").hidden = false;
  $("upload-button").disabled = state.busy;
  $("error-message").hidden = true;
}

function clearFile() {
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = null;
  state.file = null;
  $("file-input").value = "";
  $("selected-file").hidden = true;
  $("upload-button").disabled = true;
}

function setBusy(busy) {
  state.busy = busy;
  $("upload-button").disabled = busy || !state.file;
  $("choose-file").disabled = busy;
  $("remove-file").disabled = busy;
  $("upload-button").textContent = busy ? "正在提取字形…" : "上传并提取字形";
  $("upload-status").hidden = !busy;
  if (busy) $("status-text").textContent = "正在校正页面并逐格提取，照片可能需要十几秒。";
}

function showError(message) {
  $("error-message").textContent = message;
  $("error-message").hidden = false;
}

async function upload() {
  if (!state.file || state.busy) return;
  setBusy(true);
  $("error-message").hidden = true;
  const body = new FormData();
  body.append("file", state.file);
  try {
    const response = await fetch("/api/imports", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "上传失败，请重试。");
    window.localStorage.setItem("lastImportId", payload.id);
    window.history.replaceState(null, "", `/?import=${payload.id}`);
    renderResult(payload);
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    $("library").scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  } catch (error) {
    showError(error.message || "上传失败，请检查图片后重试。");
  } finally {
    setBusy(false);
  }
}

function sampleState(sample) {
  if (sample.flags.includes("empty")) return "empty";
  if (sample.flags.length > 0) return "review";
  return "ready";
}

function sortedSamples(samples) {
  const key = (sample) => {
    const char = sample.character;
    if (/^[A-Za-z]$/.test(char)) return `0-${char.toLowerCase()}-${char === char.toUpperCase() ? 0 : 1}`;
    if (/^[0-9]$/.test(char)) return `1-${char}`;
    return `2-${sample.codepoint}`;
  };
  return [...samples].sort((a, b) =>
    key(a).localeCompare(key(b)) || a.occurrence - b.occurrence
  );
}

function filteredSamples() {
  if (!state.result) return [];
  const query = $("character-search").value.trim();
  const filter = $("status-filter").value;
  return sortedSamples(state.result.samples).filter((sample) => {
    const matchesCharacter = !query ||
      (query.length === 1 ? sample.character === query : sample.codepoint.toUpperCase().includes(query.toUpperCase()));
    const status = sampleState(sample);
    const matchesStatus = filter === "all" ||
      (filter === "ready" && status === "ready") ||
      (filter === "review" && status === "review") ||
      (filter === "empty" && status === "empty");
    return matchesCharacter && matchesStatus;
  });
}

function makeGlyphCard(sample) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "glyph-card";
  card.setAttribute("aria-label", `查看字符 ${sample.character} 的第 ${sample.occurrence} 个样本`);
  card.addEventListener("click", () => openDetail(sample));

  const imageBox = document.createElement("span");
  imageBox.className = "glyph-image";
  if (sample.glyph_url) {
    const image = document.createElement("img");
    image.src = sample.glyph_url;
    image.loading = "lazy";
    image.alt = "";
    imageBox.append(image);
  } else {
    const empty = document.createElement("span");
    empty.className = "empty-label";
    empty.textContent = "无字形";
    imageBox.append(empty);
  }
  const info = document.createElement("span");
  info.className = "glyph-info";
  const character = document.createElement("strong");
  character.textContent = sample.character;
  const number = document.createElement("small");
  number.textContent = `样本 ${sample.occurrence}`;
  info.append(character, number);

  const status = document.createElement("span");
  const kind = sampleState(sample);
  status.className = `glyph-status ${kind === "ready" ? "" : `is-${kind}`}`;
  status.textContent = kind === "ready" ? "已提取" : kind === "empty" ? "空白待补" : "建议复核";
  card.append(imageBox, info, status);
  return card;
}

function renderGallery() {
  const matches = filteredSamples();
  const visible = matches.slice(0, state.visible);
  $("glyph-grid").replaceChildren(...visible.map(makeGlyphCard));
  $("visible-count").textContent = `显示 ${visible.length} / ${matches.length} 格`;
  $("no-results").hidden = matches.length > 0;
  $("load-more").hidden = visible.length >= matches.length;
}

function renderResult(result) {
  state.result = result;
  state.visible = 48;
  $("empty-overview").hidden = true;
  $("result-overview").hidden = false;
  $("library").hidden = false;
  $("run-caption").textContent = "已完成提取";
  $("sample-count").textContent = result.summary.sample_count;
  $("glyph-count").textContent = result.summary.glyph_count;
  $("review-count").textContent = result.summary.review_count;
  $("registered-image").src = result.registered_url;
  $("registered-link").href = result.registered_url;
  $("original-link").href = result.original_url;
  $("manifest-link").href = `/api/imports/${result.id}/manifest`;
  $("save-location").textContent = `data/fonts/english/${result.id}`;
  renderGallery();
  $("composer-font").textContent = `使用当前字形库 · ${result.id.slice(0, 8)}`;
  if (state.composition && state.composition.font_id !== result.id) clearCompositionPreview();
  updateComposeAvailability();
}

function labelCharacter(character) {
  if (character === "\t") return "Tab（制表符）";
  if (character === "\u00a0") return "不换行空格";
  return character;
}

function updateComposeAvailability() {
  const text = $("compose-text").value.replace(/\r\n?|\n/g, "\n");
  const characters = [...text].filter((char) => char !== " " && char !== "\n");
  const lineCount = text ? text.split("\n").length : 0;
  $("compose-count").textContent = `${lineCount} 行 · ${characters.length} 个需拼接字符`;
  const availability = $("compose-availability");
  availability.replaceChildren();
  availability.className = "compose-availability";

  let canCompose = false;
  if (!state.result) {
    availability.textContent = "先上传采集页，或打开已有提取结果。";
  } else if (!characters.length) {
    availability.textContent = "粘贴要拼接的文字后，系统会检查是否有缺失的字形。";
  } else if (lineCount > 40) {
    availability.textContent = "最多输入 40 行，请减少换行。";
    availability.classList.add("is-error");
  } else {
    const available = new Map();
    for (const sample of state.result.samples) {
      if (sample.glyph_url && sample.accepted !== false) {
        available.set(sample.character, (available.get(sample.character) || 0) + 1);
      }
    }
    const required = new Map();
    for (const character of characters) {
      required.set(character, (required.get(character) || 0) + 1);
    }
    const missing = [...required].filter(([character]) => !available.get(character));
    if (missing.length) {
      availability.classList.add("is-error");
      const intro = document.createElement("strong");
      intro.textContent = `有 ${missing.length} 个字符没有可用字形，暂时无法生成：`;
      const list = document.createElement("ul");
      for (const [character] of missing.slice(0, 8)) {
        const item = document.createElement("li");
        item.textContent = labelCharacter(character);
        list.append(item);
      }
      availability.append(intro, list);
      if (missing.length > 8) availability.append(`另有 ${missing.length - 8} 个字符未列出。`);
    } else {
      const reused = [...required].filter(([character, count]) => count > available.get(character));
      if (reused.length) {
        availability.classList.add("is-reuse");
        const intro = document.createElement("strong");
        intro.textContent = `可以生成。${reused.length} 个字符会在用完不同字形后复用：`;
        const list = document.createElement("ul");
        for (const [character, count] of reused.slice(0, 8)) {
          const item = document.createElement("li");
          item.textContent = `${labelCharacter(character)}：出现 ${count} 次，现有 ${available.get(character)} 个版本`;
          list.append(item);
        }
        availability.append(intro, list);
        if (reused.length > 8) availability.append(`另有 ${reused.length - 8} 个字符未列出。`);
      } else {
        availability.classList.add("is-ready");
        availability.textContent = `可以生成。将按输入的 ${lineCount} 行排版，每张字形图只用一次。`;
      }
      canCompose = true;
    }
  }
  $("compose-button").disabled = !canCompose || state.composing;
  return canCompose;
}

function clearCompositionPreview() {
  state.composition = null;
  $("compose-empty").hidden = false;
  $("compose-rendered").hidden = true;
  $("compose-error").hidden = true;
  window.localStorage.removeItem("lastCompositionId");
  if (state.result) window.history.replaceState(null, "", `/?import=${state.result.id}`);
}

function renderComposition(result) {
  state.composition = result;
  $("compose-empty").hidden = true;
  $("compose-rendered").hidden = false;
  $("compose-image").src = result.image_url;
  $("compose-image-link").href = result.image_url;
  $("compose-image-link").classList.toggle("is-transparent", result.background === "transparent");
  $("compose-download").href = result.download_url;
  $("compose-render-meta").textContent = `${result.line_count} 行 · ${result.width} × ${result.height} px · 随机编号 ${result.seed}`;
  window.localStorage.setItem("lastCompositionId", result.id);
  window.history.replaceState(null, "", `/?import=${result.font_id}&composition=${result.id}`);
}

async function compose() {
  if (state.composing || !updateComposeAvailability()) return;
  state.composing = true;
  $("compose-button").disabled = true;
  $("compose-reroll").disabled = true;
  $("compose-button").textContent = "正在拼接…";
  $("compose-error").hidden = true;
  const payload = {
    font_id: state.result.id,
    text: $("compose-text").value,
    cell_height_px: Number($("compose-size").value),
    spacing_jitter: Number($("compose-jitter").value) / 100,
    line_height: Number($("compose-line-height").value),
    background: $("compose-background").value,
  };
  try {
    const response = await fetch("/api/compositions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      const detail = result.detail;
      if (detail && typeof detail === "object" && detail.missing) {
        throw new Error(detail.message);
      }
      throw new Error(typeof detail === "string" ? detail : "拼接失败，请检查文字后重试。");
    }
    renderComposition(result);
  } catch (error) {
    $("compose-error").textContent = error.message || "拼接失败，请重试。";
    $("compose-error").hidden = false;
  } finally {
    state.composing = false;
    $("compose-reroll").disabled = false;
    $("compose-button").textContent = "生成拼接预览";
    updateComposeAvailability();
  }
}

function openDetail(sample) {
  $("dialog-title").textContent = `${sample.character} · 样本 ${sample.occurrence}`;
  $("dialog-crop").src = sample.original_crop_url;
  const glyph = $("dialog-glyph");
  glyph.hidden = !sample.glyph_url;
  $("dialog-glyph-empty").hidden = Boolean(sample.glyph_url);
  if (sample.glyph_url) glyph.src = sample.glyph_url;
  $("dialog-meta").textContent = `${sample.codepoint} · 第 ${sample.row + 1} 行，第 ${sample.column + 1} 格`;
  $("dialog-flags").textContent = sample.flags.length
    ? sample.flags.map((flag) => statusLabels[flag] || flag).join(" · ")
    : "自动检查通过，仍建议对照原格确认。";
  $("glyph-dialog").showModal();
}

$("choose-file").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (event) => setFile(event.target.files[0]));
$("remove-file").addEventListener("click", clearFile);
$("upload-button").addEventListener("click", upload);
$("character-search").addEventListener("input", () => { state.visible = 48; renderGallery(); });
$("status-filter").addEventListener("change", () => { state.visible = 48; renderGallery(); });
$("load-more").addEventListener("click", () => { state.visible += 48; renderGallery(); });
$("dialog-close").addEventListener("click", () => $("glyph-dialog").close());
$("compose-button").addEventListener("click", compose);
$("compose-reroll").addEventListener("click", compose);
$("compose-text").value = window.localStorage.getItem("composeText") || "";
$("compose-text").addEventListener("input", () => {
  window.localStorage.setItem("composeText", $("compose-text").value);
  if (state.composition && state.composition.text !== $("compose-text").value) clearCompositionPreview();
  updateComposeAvailability();
});
for (const [inputId, outputId, format] of [
  ["compose-size", "size-value", (value) => `${value} px`],
  ["compose-jitter", "jitter-value", (value) => `${value}%`],
  ["compose-line-height", "line-height-value", (value) => Number(value).toFixed(2)],
]) {
  $(inputId).addEventListener("input", () => {
    $(outputId).textContent = format($(inputId).value);
    if (state.composition) clearCompositionPreview();
  });
}
$("compose-background").addEventListener("change", () => {
  if (state.composition) clearCompositionPreview();
});
updateComposeAvailability();

const dropzone = $("dropzone");
for (const eventName of ["dragenter", "dragover"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("is-dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragging");
  });
}
dropzone.addEventListener("drop", (event) => {
  if (!state.busy) setFile(event.dataTransfer.files[0]);
});

const previousImport = new URLSearchParams(window.location.search).get("import") ||
  window.localStorage.getItem("lastImportId");
if (previousImport) {
  fetch(`/api/imports/${previousImport}`)
    .then((response) => response.ok ? response.json() : null)
    .then(async (result) => {
      if (!result) return;
      renderResult(result);
      const previousComposition = new URLSearchParams(window.location.search).get("composition") ||
        window.localStorage.getItem("lastCompositionId");
      if (!previousComposition) return;
      const response = await fetch(`/api/compositions/${previousComposition}`);
      if (!response.ok) return;
      const composition = await response.json();
      if (composition.font_id !== result.id) return;
      $("compose-text").value = composition.text;
      window.localStorage.setItem("composeText", composition.text);
      updateComposeAvailability();
      renderComposition(composition);
    })
    .catch(() => {});
}
