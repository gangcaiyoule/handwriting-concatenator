const $ = (id) => document.getElementById(id);

const state = {
  file: null,
  objectUrl: null,
  result: null,
  visible: 48,
  busy: false,
  composing: false,
  composition: null,
  fontName: null,
  loadToken: 0,
  detailSample: null,
  managingSample: false,
};

const statusLabels = {
  empty: "未检测到笔迹",
  touches_border: "笔迹贴近边框",
  low_contrast: "笔迹对比度低",
  suspected_mismatch: "字符可能写错",
};
const markLabels = { "\uE000": "横删除线", "\uE001": "斜删除线" };

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
  updateUploadAvailability();
  $("error-message").hidden = true;
}

function clearFile() {
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = null;
  state.file = null;
  $("file-input").value = "";
  $("selected-file").hidden = true;
  updateUploadAvailability();
}

function selectedTargetName() {
  const target = $("upload-font").value;
  return target === "__new__" ? $("new-font-name").value.trim() : target;
}

function updateUploadAvailability() {
  const target = $("upload-font").value;
  $("new-font-row").hidden = target !== "__new__";
  $("upload-button").disabled = state.busy || !state.file || !selectedTargetName();
}

function setBusy(busy) {
  state.busy = busy;
  updateUploadAvailability();
  $("choose-file").disabled = busy;
  $("remove-file").disabled = busy;
  $("upload-font").disabled = busy;
  UI.syncPopSelect("upload-font");
  $("new-font-name").disabled = busy;
  $("upload-button").textContent = busy ? "正在提取字形…" : "上传并提取字形";
  $("upload-status").hidden = !busy;
  if (busy) $("status-text").textContent = "正在校正页面并逐格提取，照片可能需要十几秒。";
}

function showError(message) {
  $("error-message").textContent = message;
  $("error-message").hidden = false;
}

async function upload() {
  const fontName = selectedTargetName();
  if (!state.file || state.busy || !fontName) return;
  setBusy(true);
  $("error-message").hidden = true;
  const body = new FormData();
  body.append("font_name", fontName);
  body.append("file", state.file);
  try {
    const response = await fetch("/api/imports", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "上传失败，请重试。");
    const switchedFont = state.fontName !== payload.id;
    await refreshFontList();
    state.fontName = payload.id;
    $("library-select").value = payload.id;
    $("mobile-library-select").value = payload.id;
    UI.syncPopSelect("library-select");
    UI.syncPopSelect("mobile-library-select");
    window.localStorage.setItem("lastFontName", payload.id);
    if (switchedFont) {
      hideCompositionPreview();
      $("compose-text").value = window.localStorage.getItem(`composeText:${payload.id}`) || "";
    }
    window.history.replaceState(null, "", `/?font=${encodeURIComponent(payload.id)}`);
    renderResult(payload);
    $("upload-font").value = "";
    UI.syncPopSelect("upload-font");
    $("new-font-name").value = "";
    clearFile();
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
  if (sample.accepted === false) return "disabled";
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
      (query.length === 1 ? sample.character === query : sample.codepoint.toUpperCase().includes(query.toUpperCase())) ||
      (markLabels[sample.character] || "").includes(query);
    const status = sampleState(sample);
    const matchesStatus = filter === "all" ||
      (filter === "ready" && status === "ready") ||
      (filter === "review" && status === "review") ||
      (filter === "disabled" && status === "disabled") ||
      (filter === "empty" && status === "empty");
    return matchesCharacter && matchesStatus;
  });
}

function makeGlyphCard(sample) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "glyph-card";
  card.setAttribute("aria-label", `查看字符 ${labelCharacter(sample.character)} 的第 ${sample.occurrence} 个样本`);
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
  character.textContent = markLabels[sample.character] || sample.character;
  const number = document.createElement("small");
  number.textContent = `样本 ${sample.occurrence}`;
  info.append(character, number);

  const status = document.createElement("span");
  const kind = sampleState(sample);
  status.className = `glyph-status ${kind === "ready" ? "" : `is-${kind}`}`;
  status.textContent = kind === "ready" ? "已提取" : kind === "empty" ? "空白待补" : kind === "disabled" ? "已停用" : "建议复核";
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
  const hasSamples = result.summary.sample_count > 0;
  $("empty-overview").hidden = hasSamples;
  $("result-overview").hidden = !hasSamples;
  $("library").hidden = !hasSamples;
  $("run-caption").textContent = hasSamples ? `已合并 ${result.upload_count} 份采集页` : "还没有上传";
  $("sample-count").textContent = result.summary.sample_count;
  $("glyph-count").textContent = result.summary.glyph_count;
  $("review-count").textContent = result.summary.review_count;
  if (result.registered_url) {
    $("registered-image").src = result.registered_url;
    $("registered-link").href = result.registered_url;
  }
  if (result.original_url) $("original-link").href = result.original_url;
  $("manifest-link").href = `/api/imports/${encodeURIComponent(result.id)}/manifest`;
  $("save-location").textContent = `data/fonts/english/${result.id}`;
  if (hasSamples) renderGallery();
  const wordVersions = Object.values(result.word_counts || {}).reduce((sum, count) => sum + count, 0);
  $("composer-font").textContent = `当前字体库 · ${result.id} · ${wordVersions} 个整词版本`;
  if (state.composition && state.composition.font_id !== result.id) hideCompositionPreview();
  updateComposeAvailability();
  renderLegacy(result.legacy_imports || []);
}

function renderLegacy(ids) {
  const list = $("legacy-list");
  list.replaceChildren();
  $("legacy-banner").hidden = ids.length === 0;
  for (const id of ids) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `导入旧字形库 ${id.slice(0, 8)}`;
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "正在导入…";
      try {
        const response = await fetch(`/api/fonts/${encodeURIComponent(state.fontName)}/claim/${id}`, { method: "POST" });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "导入旧字形库失败");
        renderResult(result);
        await refreshFontList();
      } catch (error) {
        button.disabled = false;
        button.textContent = `重试导入 ${id.slice(0, 8)}`;
        showError(error.message);
      }
    });
    list.append(button);
  }
}

function labelCharacter(character) {
  if (markLabels[character]) return markLabels[character];
  if (character === "\t") return "Tab（制表符）";
  if (character === "\u00a0") return "不换行空格";
  return character;
}

function visibleComposeText(source) {
  const lines = [];
  for (const line of source.replace(/\r\n?/g, "\n").split("\n")) {
    let visible = "", cursor = 0;
    for (const match of line.matchAll(/~~([A-Za-z]+)~~/g)) {
      if ((match.index > 0 && /[A-Za-z]/.test(line[match.index - 1])) ||
          (match.index + match[0].length < line.length && /[A-Za-z]/.test(line[match.index + match[0].length]))) {
        return { error: "删除线标记须包住完整的英文词。" };
      }
      const prefix = line.slice(cursor, match.index);
      if (prefix.includes("~~")) return { error: "删除线请写成 ~~word~~，一次只标记一个英文词。" };
      visible += prefix + match[1];
      cursor = match.index + match[0].length;
    }
    const rest = line.slice(cursor);
    if (rest.includes("~~")) return { error: "删除线请写成 ~~word~~，一次只标记一个英文词。" };
    lines.push(visible + rest);
  }
  return { text: lines.join("\n") };
}

function updateComposeAvailability() {
  const parsed = visibleComposeText($("compose-text").value);
  const text = parsed.text || "";
  const strikeCount = [...$("compose-text").value.matchAll(/~~[A-Za-z]+~~/g)].length;
  const characters = [...text].filter((char) => char !== " " && char !== "\n");
  const fallbackCharacters = [];
  let wholeWords = 0;
  for (const line of text.split("\n")) {
    let cursor = 0;
    for (const match of line.matchAll(/[A-Za-z]+/g)) {
      if ((state.result?.word_counts?.[match[0]] || 0) > 0) {
        fallbackCharacters.push(...[...line.slice(cursor, match.index)].filter((char) => char !== " "));
        wholeWords++;
        cursor = match.index + match[0].length;
      }
    }
    fallbackCharacters.push(...[...line.slice(cursor)].filter((char) => char !== " "));
  }
  const lineCount = text ? text.split("\n").length : 0;
  $("compose-count").textContent = `${lineCount} 行 · ${characters.length} 个需拼接字符`;
  const availability = $("compose-availability");
  availability.replaceChildren();
  availability.className = "compose-availability";

  let canCompose = false;
  if (parsed.error) {
    availability.textContent = parsed.error;
    availability.classList.add("is-error");
  } else if (!state.result) {
    availability.textContent = "先选择字体库，或上传到新字体库。";
  } else if (!state.result.summary.glyph_count &&
             !Object.values(state.result.word_counts || {}).some((count) => count > 0)) {
    availability.textContent = "先上传采集页，或导入旧字形库。";
  } else if (!characters.length) {
    availability.textContent = "粘贴要拼接的文字后，系统会检查是否有缺失的字形。";
  } else if (strikeCount && !state.result.samples.some((sample) =>
    markLabels[sample.character] && sample.glyph_url && sample.accepted !== false)) {
    availability.textContent = "当前字体库缺少手写删除线，请打印新版模板，在末行宽格写横线或斜线后上传。";
    availability.classList.add("is-error");
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
    for (const character of fallbackCharacters) {
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
        availability.textContent = `可以生成。将按输入的 ${lineCount} 行排版；${wholeWords} 个词使用已保存的整词图片。`;
      }
      canCompose = true;
    }
  }
  $("compose-button").disabled = !canCompose || state.composing;
  return canCompose;
}

function hideCompositionPreview() {
  state.composition = null;
  $("compose-empty").hidden = false;
  $("compose-rendered").hidden = true;
  $("compose-error").hidden = true;
}

function clearCompositionPreview() {
  hideCompositionPreview();
  if (state.fontName) window.localStorage.removeItem(`lastCompositionId:${state.fontName}`);
  if (state.result) window.history.replaceState(null, "", `/?font=${encodeURIComponent(state.result.id)}`);
}

function renderComposition(result) {
  state.composition = result;
  for (const [id, value, output, format] of [
    ["compose-size", result.cell_height_px, "size-value", (v) => `${v} px`],
    ["compose-jitter", result.spacing_jitter == null ? null : Math.round(result.spacing_jitter * 100), "jitter-value", (v) => `${v}%`],
    ["compose-line-height", result.line_height, "line-height-value", (v) => Number(v).toFixed(2)],
  ]) {
    if (value != null) {
      $(id).value = String(value);
      $(output).textContent = format(value);
    }
  }
  if (result.background) {
    $("compose-background").value = result.background;
    UI.syncPopSelect("compose-background");
  }
  $("compose-empty").hidden = true;
  $("compose-rendered").hidden = false;
  $("compose-image").src = result.image_url;
  $("compose-image-link").href = result.image_url;
  $("compose-image-link").classList.toggle("is-transparent", result.background === "transparent");
  $("compose-download").href = result.download_url;
  $("compose-edit").href = `/editor?composition=${result.id}`;
  $("compose-render-meta").textContent = `${result.line_count} 行 · ${result.width} × ${result.height} px · 随机编号 ${result.seed}`;
  window.localStorage.setItem(`lastCompositionId:${result.font_id}`, result.id);
  window.history.replaceState(null, "", `/?font=${encodeURIComponent(result.font_id)}&composition=${result.id}`);
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
  state.detailSample = sample;
  $("dialog-action-error").hidden = true;
  $("dialog-toggle-sample").hidden = !sample.sample_file;
  $("dialog-delete-sample").hidden = !sample.sample_file;
  $("dialog-toggle-sample").textContent = sample.accepted === false ? "重新启用此版本" : "停用此版本";
  $("dialog-title").textContent = `${labelCharacter(sample.character)} · 样本 ${sample.occurrence}`;
  $("dialog-crop").src = sample.original_crop_url;
  const glyph = $("dialog-glyph");
  glyph.hidden = !sample.glyph_url;
  $("dialog-glyph-empty").hidden = Boolean(sample.glyph_url);
  if (sample.glyph_url) glyph.src = sample.glyph_url;
  $("dialog-meta").textContent = `${sample.codepoint} · 第 ${sample.row + 1} 行，第 ${sample.column + 1} 格`;
  $("dialog-flags").textContent = sample.flags.length
    ? sample.flags.map((flag) => statusLabels[flag] || flag).join(" · ")
    : "自动检查通过，仍建议对照原格确认。";
  if (!$("glyph-dialog").open) $("glyph-dialog").showModal();
}

async function manageDetailSample(action) {
  const sample = state.detailSample;
  if (!sample || (action !== "delete-character" && !sample.sample_file) ||
      state.managingSample || !state.result) return;
  if (action === "delete" && !await UI.confirm({ title: "删除这个字形版本？", message: `确定从 ${state.result.id} 字库删除 ${labelCharacter(sample.character)} 的样本 ${sample.occurrence}？旧拼接图会保留，之后生成不再使用它。`, confirmText: "删除版本", danger: true })) return;
  if (action === "delete-character") {
    const count = state.result.samples.filter((item) => item.character === sample.character).length;
    if (!await UI.confirm({ title: "删除这个字符的全部版本？", message: `确定从 ${state.result.id} 字库删除 ${labelCharacter(sample.character)} 的全部 ${count} 个样本？旧拼接图会保留，之后生成不再使用它们。`, confirmText: "删除全部版本", danger: true })) return;
  }
  state.managingSample = true;
  $("dialog-action-error").hidden = true;
  $("dialog-toggle-sample").disabled = true;
  $("dialog-delete-sample").disabled = true;
  $("dialog-delete-character").disabled = true;
  try {
    const url = `/api/imports/${encodeURIComponent(state.result.id)}/sample`;
    const target = action === "delete-character"
      ? `/api/imports/${encodeURIComponent(state.result.id)}/character?character=${encodeURIComponent(sample.character)}`
      : action === "delete" ? `${url}?sample_file=${encodeURIComponent(sample.sample_file)}` : url;
    const response = await fetch(target, {
      method: action === "toggle" ? "PATCH" : "DELETE",
      ...(action !== "toggle" ? {} : {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample_file: sample.sample_file, accepted: sample.accepted === false }),
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "管理字形失败，请重试。");
    renderResult(result);
    await refreshFontList();
    if (action !== "toggle") {
      state.detailSample = null;
      $("glyph-dialog").close();
    } else {
      openDetail(result.samples.find((item) => item.sample_file === sample.sample_file));
    }
  } catch (error) {
    $("dialog-action-error").textContent = error.message;
    $("dialog-action-error").hidden = false;
  } finally {
    state.managingSample = false;
    $("dialog-toggle-sample").disabled = false;
    $("dialog-delete-sample").disabled = false;
    $("dialog-delete-character").disabled = false;
  }
}

async function refreshFontList() {
  const response = await fetch("/api/fonts");
  const fonts = await response.json();
  if (!response.ok) throw new Error("读取字体库列表失败");
  const currentTarget = $("upload-font").value;
  const browsing = $("library-select");
  browsing.replaceChildren();
  const mobileBrowsing = $("mobile-library-select");
  mobileBrowsing.replaceChildren();
  const target = $("upload-font");
  target.replaceChildren(new Option("请选择字体库", ""));
  for (const font of fonts) {
    browsing.add(new Option(`${font.name} · ${font.glyph_count} 字形`, font.name));
    mobileBrowsing.add(new Option(`${font.name} · ${font.glyph_count} 字形`, font.name));
    target.add(new Option(`${font.name} · ${font.glyph_count} 字形`, font.name));
  }
  if (!fonts.length) {
    browsing.add(new Option("暂无字体库", ""));
    mobileBrowsing.add(new Option("暂无字体库", ""));
  }
  target.add(new Option("＋ 新建字体库", "__new__"));
  target.value = currentTarget && [...target.options].some((option) => option.value === currentTarget)
    ? currentTarget : "";
  if (state.fontName && fonts.some((font) => font.name === state.fontName)) {
    browsing.value = state.fontName;
    mobileBrowsing.value = state.fontName;
  }
  UI.syncPopSelect("library-select");
  UI.syncPopSelect("mobile-library-select");
  UI.syncPopSelect("upload-font");
  updateUploadAvailability();
  return fonts;
}

async function selectFont(fontName) {
  const token = ++state.loadToken;
  const params = new URLSearchParams(window.location.search);
  const requestedComposition = params.get("font") === fontName ? params.get("composition") : null;
  try {
    const response = await fetch(`/api/imports/${encodeURIComponent(fontName)}`);
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "无法打开字体库");
    if (token !== state.loadToken) return;
    hideCompositionPreview();
    state.fontName = result.id;
    $("library-select").value = result.id;
    $("mobile-library-select").value = result.id;
    UI.syncPopSelect("library-select");
    UI.syncPopSelect("mobile-library-select");
    window.localStorage.setItem("lastFontName", result.id);
    $("compose-text").value = window.localStorage.getItem(`composeText:${result.id}`) || "";
    renderResult(result);
    window.history.replaceState(null, "", `/?font=${encodeURIComponent(result.id)}`);

    const previousComposition = requestedComposition ||
      window.localStorage.getItem(`lastCompositionId:${result.id}`);
    if (previousComposition) {
      const saved = await fetch(`/api/compositions/${previousComposition}`);
      if (token !== state.loadToken) return;
      if (saved.ok) {
        const composition = await saved.json();
        if (composition.font_id === result.id) {
          $("compose-text").value = composition.text;
          window.localStorage.setItem(`composeText:${result.id}`, composition.text);
          updateComposeAvailability();
          renderComposition(composition);
        }
      }
    }
  } catch (error) {
    if (token === state.loadToken) showError(error.message || "打开字体库失败");
  }
}

$("choose-file").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (event) => setFile(event.target.files[0]));
$("remove-file").addEventListener("click", clearFile);
$("upload-button").addEventListener("click", upload);
$("upload-font").addEventListener("change", updateUploadAvailability);
$("new-font-name").addEventListener("input", updateUploadAvailability);
$("library-select").addEventListener("change", (event) => {
  if (event.target.value) selectFont(event.target.value);
});
$("mobile-library-select").addEventListener("change", (event) => {
  if (event.target.value) selectFont(event.target.value);
});
$("character-search").addEventListener("input", () => { state.visible = 48; renderGallery(); });
$("status-filter").addEventListener("change", () => { state.visible = 48; renderGallery(); });
$("load-more").addEventListener("click", () => { state.visible += 48; renderGallery(); });
$("dialog-close").addEventListener("click", () => $("glyph-dialog").close());
$("dialog-toggle-sample").addEventListener("click", () => manageDetailSample("toggle"));
$("dialog-delete-sample").addEventListener("click", () => manageDetailSample("delete"));
$("dialog-delete-character").addEventListener("click", () => manageDetailSample("delete-character"));
$("compose-button").addEventListener("click", compose);
$("compose-reroll").addEventListener("click", compose);
$("compose-text").value = "";
$("compose-text").addEventListener("input", () => {
  if (state.fontName) window.localStorage.setItem(`composeText:${state.fontName}`, $("compose-text").value);
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

refreshFontList().then((fonts) => {
  const requested = new URLSearchParams(window.location.search).get("font") ||
    window.localStorage.getItem("lastFontName");
  const first = fonts.find((font) => font.name === requested) || fonts[0];
  if (first) selectFont(first.name);
}).catch((error) => showError(error.message || "读取字体库失败"));
