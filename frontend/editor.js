const $ = (id) => document.getElementById(id);

const state = {
  draft: null,
  placements: [],
  variants: new Map(),
  selected: null,
  selectedIndices: new Set(),
  anchor: null,
  zoom: 1,
  undo: [],
  redo: [],
  saved: "",
  saving: false,
  toggling: false,
};

function editPayload() {
  return state.placements.map((item, index) => ({
    index,
    kind: item.kind || "glyph",
    character: item.character,
    line: item.line,
    column: item.column,
    sample_file: item.sample_file,
    x: item.x,
    y: item.y,
    scale: item.scale,
  }));
}

function snapshot() { return JSON.stringify(state.placements); }
function variantFor(file) { return state.variants.get(file); }
function isDirty() { return Boolean(state.draft && snapshot() !== state.saved); }

function setSelection(indices, anchor = null) {
  state.selectedIndices = new Set(indices);
  state.selected = state.selectedIndices.size === 1 ? [...state.selectedIndices][0] : null;
  state.anchor = anchor;
  renderAll();
}

function clearSelection() { setSelection([], null); }

function selectRange(index) {
  if (state.anchor === null) { setSelection([index], index); return; }
  const start = Math.min(state.anchor, index);
  const end = Math.max(state.anchor, index);
  setSelection(Array.from({ length: end - start + 1 }, (_, offset) => start + offset), state.anchor);
}

function toggleSelection(index) {
  const next = new Set(state.selectedIndices);
  if (next.has(index)) next.delete(index); else next.add(index);
  setSelection(next, index);
}

function selectionBounds() {
  if (!state.selectedIndices.size) return null;
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  for (const index of state.selectedIndices) {
    const item = state.placements[index];
    left = Math.min(left, item.x);
    top = Math.min(top, item.y);
    right = Math.max(right, item.x + item.width);
    bottom = Math.max(bottom, item.y + item.height);
  }
  return { left, top, right, bottom };
}

function boundedMove(indices, dx, dy, positions = null) {
  const current = positions || state.placements;
  const first = [...indices];
  if (!first.length) return;
  const minX = Math.min(...first.map((index) => current[index].x));
  const minY = Math.min(...first.map((index) => current[index].y));
  const maxRight = Math.max(...first.map((index) => current[index].x + state.placements[index].width));
  const maxBottom = Math.max(...first.map((index) => current[index].y + state.placements[index].height));
  const moveX = Math.max(-minX, Math.min(12000 - maxRight, dx));
  const moveY = Math.max(-minY, Math.min(12000 - maxBottom, dy));
  for (const index of first) {
    state.placements[index].x = current[index].x + moveX;
    state.placements[index].y = current[index].y + moveY;
  }
}

function showError(message) {
  $("editor-error").textContent = message;
  $("editor-error").hidden = false;
}

function clearError() { $("editor-error").hidden = true; }

async function requestJSON(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : "操作失败，请重试。");
  }
  return body;
}

function markState() {
  if (!state.draft) return;
  const saveState = $("editor-save-state");
  saveState.textContent = state.saving ? "保存中…" : isDirty() ? "尚未保存" : "已保存";
  saveState.classList.toggle("is-busy", state.saving);
  saveState.classList.toggle("is-dirty", !state.saving && isDirty());
  saveState.classList.toggle("is-saved", !state.saving && !isDirty());
  $("editor-save").disabled = state.saving || !isDirty();
  $("editor-export").disabled = state.saving;
  $("editor-save-words").disabled = state.saving;
  $("editor-undo").disabled = state.saving || !state.undo.length;
  $("editor-redo").disabled = state.saving || !state.redo.length;
}

function commit(previous) {
  if (snapshot() === previous) return;
  $("editor-word-status").hidden = true;
  state.undo.push(previous);
  if (state.undo.length > 100) state.undo.shift();
  state.redo.length = 0;
  renderAll();
}

function restore(serialized) {
  state.placements = JSON.parse(serialized);
  state.selectedIndices = new Set();
  state.selected = null;
  state.anchor = null;
  renderAll();
}

function undo() {
  if (!state.undo.length || state.saving) return;
  state.redo.push(snapshot());
  restore(state.undo.pop());
}

function redo() {
  if (!state.redo.length || state.saving) return;
  state.undo.push(snapshot());
  restore(state.redo.pop());
}

function stageSize() {
  const right = Math.max(0, ...state.placements.map((item) => item.x + item.width));
  const bottom = Math.max(0, ...state.placements.map((item) => item.y + item.height));
  return [Math.max(state.draft.width, right + 20), Math.max(state.draft.height, bottom + 20)];
}

function applyZoom() {
  const [width, height] = stageSize();
  $("editor-stage").style.width = `${width}px`;
  $("editor-stage").style.height = `${height}px`;
  $("editor-stage").style.transform = `scale(${state.zoom})`;
  $("editor-stage-wrap").style.width = `${Math.ceil(width * state.zoom)}px`;
  $("editor-stage-wrap").style.height = `${Math.ceil(height * state.zoom)}px`;
}

function median(numbers) {
  const values = [...numbers].sort((a, b) => a - b);
  const middle = Math.floor(values.length / 2);
  return values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
}

function baselineFor(line) {
  const positions = state.placements
    .filter((item) => item.line === line && /^[A-Za-z]$/.test(item.character) && !/[gjpqy]/.test(item.character))
    .map((item) => item.y + item.height);
  return positions.length ? median(positions) : null;
}

function priorInLine(index) {
  const line = state.placements[index].line;
  for (let prior = index - 1; prior >= 0; prior--) {
    if (state.placements[prior].line === line) return prior;
    if (state.placements[prior].line < line) break;
  }
  return null;
}

function currentGap(index) {
  const prior = priorInLine(index);
  if (prior === null) return null;
  const before = state.placements[prior];
  return state.placements[index].x - before.x - before.width;
}

function renderStage() {
  const stage = $("editor-stage");
  stage.replaceChildren();
  stage.classList.toggle("is-transparent", state.draft.background === "transparent");
  applyZoom();
  if ($("editor-guides").checked) {
    for (let line = 0; line < state.draft.line_count; line++) {
      const baseline = baselineFor(line);
      if (baseline === null) continue;
      const guide = document.createElement("div");
      guide.className = "edit-baseline";
      guide.style.top = `${baseline}px`;
      const label = document.createElement("span");
      label.textContent = `第 ${line + 1} 行`;
      guide.append(label);
      stage.append(guide);
    }
  }
  for (const [index, item] of state.placements.entries()) {
    const variant = variantFor(item.sample_file);
    const glyph = document.createElement("button");
    glyph.type = "button";
    glyph.className = `edit-glyph${state.selectedIndices.has(index) ?
      (state.selectedIndices.size > 1 ? " is-group-selected" : " is-selected") : ""}`;
    glyph.dataset.index = String(index);
    glyph.setAttribute("aria-pressed", state.selectedIndices.has(index) ? "true" : "false");
    glyph.setAttribute("aria-label", `第 ${item.line + 1} 行，第 ${item.column + 1} 位${item.kind === "word" ? "整词" : "字符"} ${item.character}`);
    glyph.classList.toggle("is-word", item.kind === "word");
    glyph.style.left = `${item.x}px`;
    glyph.style.top = `${item.y}px`;
    glyph.style.width = `${item.width}px`;
    glyph.style.height = `${item.height}px`;
    const image = document.createElement("img");
    image.src = variant.image_url;
    image.alt = "";
    image.draggable = false;
    glyph.append(image);
    glyph.addEventListener("pointerdown", (event) => glyphPointerDown(event, index));
    glyph.addEventListener("click", (event) => event.stopPropagation());
    stage.append(glyph);
  }
  renderStrikes();
  if (state.selectedIndices.size > 1) {
    const bounds = selectionBounds();
    const outline = document.createElement("div");
    outline.className = "edit-group-bounds";
    outline.style.left = `${bounds.left - 4}px`;
    outline.style.top = `${Math.max(0, bounds.top - 4)}px`;
    outline.style.width = `${bounds.right - bounds.left + 8}px`;
    outline.style.height = `${bounds.bottom - bounds.top + 8}px`;
    const label = document.createElement("span");
    label.textContent = `已选 ${state.selectedIndices.size} 项`;
    outline.append(label);
    stage.append(outline);
  }
  if (state.selected !== null && priorInLine(state.selected) !== null) {
    const item = state.placements[state.selected];
    const handle = document.createElement("button");
    handle.type = "button";
    handle.className = "edit-gap-handle";
    handle.setAttribute("aria-label", `调整字符 ${item.character} 前的间距`);
    handle.style.left = `${item.x - 7}px`;
    handle.style.top = `${Math.max(0, item.y - 4)}px`;
    handle.style.height = `${Math.max(42, item.height + 8)}px`;
    handle.addEventListener("pointerdown", (event) => startDrag(event, "gap", state.selected));
    handle.addEventListener("click", (event) => event.stopPropagation());
    stage.append(handle);
  }
}

function renderStrikes() {
  const stage = $("editor-stage");
  stage.querySelectorAll(".edit-strike").forEach((line) => line.remove());
  for (const span of state.draft.strikes || []) {
    const covered = state.placements.filter((item) => item.line === span.line &&
      item.column < span.end_column && item.column + item.character.length > span.column);
    if (!covered.length) continue;
    const left = Math.min(...covered.map((item) => item.x));
    const right = Math.max(...covered.map((item) => item.x + item.width));
    const y = Math.round(median(covered.map((item) => item.y + item.height * 0.52)));
    const variant = span.sample_file ? variantFor(span.sample_file) : null;
    const line = document.createElement(variant ? "img" : "div");
    line.className = "edit-strike";
    if (variant) { line.src = variant.image_url; line.alt = ""; }
    line.style.left = `${left}px`;
    const height = variant ? Math.min(variant.height, Math.max(3, Math.round(state.draft.cell_height_px * 0.7)))
      : Math.max(2, Math.round(state.draft.cell_height_px * 0.055));
    line.style.top = `${variant ? Math.max(0, y - Math.floor(height / 2)) : y}px`;
    line.style.width = `${right - left}px`;
    line.style.height = `${height}px`;
    stage.append(line);
  }
}

function renderSelectionFields() {
  if (state.selected === null) return;
  const item = state.placements[state.selected];
  $("editor-x").value = String(item.x);
  $("editor-y").value = String(item.y);
  $("editor-scale").value = String(Math.round(item.scale * 100));
  const gap = currentGap(state.selected);
  $("editor-gap").disabled = gap === null;
  $("editor-gap").value = gap === null ? "" : String(gap);
}

function renderGroupFields() {
  if (state.selectedIndices.size < 2) return;
  const bounds = selectionBounds();
  $("editor-group-x").value = String(bounds.left);
  $("editor-group-y").value = String(bounds.top);
}

function renderPanel() {
  const selected = state.selected;
  $("editor-no-selection").hidden = state.selectedIndices.size > 0;
  $("editor-selection").hidden = selected === null;
  $("editor-group-selection").hidden = state.selectedIndices.size < 2;
  if (state.selectedIndices.size > 1) {
    $("editor-group-count").textContent = String(state.selectedIndices.size);
    renderGroupFields();
    return;
  }
  if (selected === null) return;
  const item = state.placements[selected];
  $("editor-character").textContent = item.character;
  const isWord = item.kind === "word";
  $("editor-character-meta").textContent = `第 ${item.line + 1} 行 · 第 ${item.column + 1} 位 · ${isWord ? "整词" : "字母"}`;
  $("editor-line").value = String(item.line);
  UI.syncPopSelect("editor-line");
  const variants = [...state.variants.values()].filter((variant) =>
    variant.character === item.character && variant.kind === (isWord ? "word" : "glyph"));
  const list = $("editor-variants");
  list.replaceChildren();
  for (const variant of variants) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `editor-variant${variant.sample_file === item.sample_file ? " is-selected" : ""}`;
    button.disabled = !variant.accepted;
    button.setAttribute("aria-label", `使用 ${item.character} 的版本 ${variant.occurrence}${variant.accepted ? "" : variant.deleted ? "，已删除" : "，已停用"}`);
    const image = document.createElement("img");
    image.src = variant.image_url;
    image.alt = "";
    const label = document.createElement("span");
    label.textContent = variant.accepted ? `版本 ${variant.occurrence}` : variant.deleted ? "已删除" : "已停用";
    button.append(image, label);
    button.addEventListener("click", () => replaceVariant(variant));
    list.append(button);
  }
  const current = variantFor(item.sample_file);
  $("editor-toggle-sample").hidden = isWord || current.deleted;
  $("editor-break-word").hidden = !isWord;
  $("editor-sample-note").textContent = isWord
    ? "整词会作为一张图片使用。拆成字母后可重新调整并保存为新词版本。"
    : "停用后，当前草稿中使用该版本的字母会自动换成可用版本；没有其他版本时会提示。";
  $("editor-toggle-sample").textContent = current.accepted ? "以后不再使用这个版本" : "重新启用这个版本";
  $("editor-toggle-sample").disabled = state.toggling;
  renderSelectionFields();
}

function renderAll() {
  renderStage();
  renderPanel();
  markState();
}

function shiftFollowing(index, difference) {
  const line = state.placements[index].line;
  for (let next = index + 1; next < state.placements.length; next++) {
    if (state.placements[next].line !== line) break;
    state.placements[next].x = Math.max(0, state.placements[next].x + difference);
  }
}

async function repairUnavailableGlyphs() {
  const before = snapshot();
  const unavailable = state.placements.filter((item) => item.kind !== "word" &&
    !variantFor(item.sample_file)?.accepted);
  if (!unavailable.length) return { repaired: 0, unresolved: 0 };
  const transformed = await requestJSON(`/api/compositions/${state.draft.id}/transform`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      revision: state.draft.revision, placements: editPayload(),
      operations: [{ type: "replace_unavailable" }],
    }),
  });
  state.placements = transformed.placements;
  const unresolved = state.placements.filter((item) => item.kind !== "word" &&
    !variantFor(item.sample_file)?.accepted).length;
  const repaired = unavailable.length - unresolved;
  if (repaired) commit(before);
  return { repaired, unresolved };
}

function replaceVariant(variant) {
  if (state.selected === null || !variant.accepted) return;
  const item = state.placements[state.selected];
  if (item.sample_file === variant.sample_file) return;
  const before = snapshot();
  const oldWidth = item.width;
  const oldHeight = item.height;
  item.sample_file = variant.sample_file;
  item.width = Math.max(1, Math.round(variant.width * item.scale));
  item.height = Math.max(1, Math.round(variant.height * item.scale));
  item.y = Math.max(0, item.y + Math.round((oldHeight - item.height) / 2));
  shiftFollowing(state.selected, item.width - oldWidth);
  commit(before);
}

async function breakWord() {
  if (state.selected === null || state.saving) return;
  const index = state.selected;
  const item = state.placements[index];
  if (item.kind !== "word") return;
  const before = snapshot();
  const count = item.character.length;
  state.saving = true;
  clearError();
  markState();
  try {
    const transformed = await requestJSON(`/api/compositions/${state.draft.id}/transform`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        revision: state.draft.revision,
        placements: editPayload(),
        operations: [{ type: "split_word", line: item.line, column: item.column }],
      }),
    });
    state.placements = transformed.placements;
    state.selectedIndices = new Set(Array.from({ length: count }, (_, offset) => index + offset));
    state.selected = count === 1 ? index : null;
    state.anchor = index;
    commit(before);
  } catch (error) {
    showError(error.message);
  } finally {
    state.saving = false;
    markState();
  }
}

function changeScale(percent) {
  if (state.selected === null || !Number.isFinite(percent) || percent < 50 || percent > 150) return;
  const item = state.placements[state.selected];
  const before = snapshot();
  const oldWidth = item.width;
  const oldHeight = item.height;
  const variant = variantFor(item.sample_file);
  item.scale = percent / 100;
  item.width = Math.max(1, Math.round(variant.width * item.scale));
  item.height = Math.max(1, Math.round(variant.height * item.scale));
  item.y = Math.max(0, item.y + Math.round((oldHeight - item.height) / 2));
  shiftFollowing(state.selected, item.width - oldWidth);
  commit(before);
}

function changeGap(gap) {
  if (state.selected === null || !Number.isFinite(gap) || gap < -100 || gap > 300) return;
  const old = currentGap(state.selected);
  if (old === null) return;
  const before = snapshot();
  const difference = gap - old;
  const line = state.placements[state.selected].line;
  for (let index = state.selected; index < state.placements.length; index++) {
    if (state.placements[index].line !== line) break;
    state.placements[index].x = Math.max(0, state.placements[index].x + difference);
  }
  commit(before);
}

function moveSelection(dx, dy) {
  if (!state.selectedIndices.size || state.saving) return;
  const before = snapshot();
  boundedMove(state.selectedIndices, dx, dy);
  commit(before);
}

function refreshPositions() {
  for (const glyph of $("editor-stage").querySelectorAll(".edit-glyph")) {
    const item = state.placements[Number(glyph.dataset.index)];
    glyph.style.left = `${item.x}px`;
    glyph.style.top = `${item.y}px`;
  }
  renderStrikes();
  const handle = $("editor-stage").querySelector(".edit-gap-handle");
  if (handle && state.selected !== null) {
    handle.style.left = `${state.placements[state.selected].x - 7}px`;
    handle.style.top = `${Math.max(0, state.placements[state.selected].y - 4)}px`;
  }
  const outline = $("editor-stage").querySelector(".edit-group-bounds");
  if (outline) {
    const bounds = selectionBounds();
    outline.style.left = `${bounds.left - 4}px`;
    outline.style.top = `${Math.max(0, bounds.top - 4)}px`;
  }
  applyZoom();
  renderSelectionFields();
  renderGroupFields();
}

function glyphPointerDown(event, index) {
  if (event.button !== 0 || state.saving) return;
  if (event.shiftKey) {
    event.preventDefault();
    event.stopPropagation();
    selectRange(index);
    return;
  }
  if (event.ctrlKey || event.metaKey) {
    event.preventDefault();
    event.stopPropagation();
    toggleSelection(index);
    return;
  }
  startDrag(event, "glyph", index);
}

function startDrag(event, mode, index) {
  if (event.button !== 0 || state.saving) return;
  event.preventDefault();
  event.stopPropagation();
  if (mode === "glyph" && !state.selectedIndices.has(index)) {
    setSelection([index], index);
  }
  const moving = mode === "glyph" ? [...state.selectedIndices] : [];
  const start = { x: event.clientX, y: event.clientY };
  const before = snapshot();
  const positions = state.placements.map((item) => ({ x: item.x, y: item.y }));
  const line = state.placements[index].line;
  const pointerId = event.pointerId;
  const move = (pointer) => {
    if (pointer.pointerId !== pointerId) return;
    const dx = Math.round((pointer.clientX - start.x) / state.zoom);
    const dy = Math.round((pointer.clientY - start.y) / state.zoom);
    if (mode === "glyph") {
      boundedMove(moving, dx, dy, positions);
    } else {
      const bounded = Math.max(-positions[index].x, dx);
      for (let next = index; next < state.placements.length; next++) {
        if (state.placements[next].line !== line) break;
        state.placements[next].x = positions[next].x + bounded;
      }
    }
    refreshPositions();
    markState();
  };
  const stop = (pointer) => {
    if (pointer.pointerId !== pointerId) return;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
    window.removeEventListener("pointercancel", stop);
    commit(before);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop);
  window.addEventListener("pointercancel", stop);
}

function alignBaselines() {
  const before = snapshot();
  for (let line = 0; line < state.draft.line_count; line++) {
    const baseline = baselineFor(line);
    if (baseline === null) continue;
    for (const item of state.placements) {
      if (item.line !== line || !/^[A-Za-z]$/.test(item.character) || /[gjpqy]/.test(item.character)) continue;
      const offset = Math.round(Math.max(-8, Math.min(8, (baseline - item.y - item.height) * 0.6)));
      item.y = Math.max(0, item.y + offset);
    }
  }
  commit(before);
}

function shiftLine(amount) {
  const line = Number($("editor-line").value);
  const before = snapshot();
  for (const item of state.placements) {
    if (item.line === line) item.y = Math.max(0, item.y + amount);
  }
  commit(before);
}

async function toggleSample() {
  if (state.selected === null || state.toggling) return;
  if (state.placements[state.selected].kind === "word") return;
  const variant = variantFor(state.placements[state.selected].sample_file);
  state.toggling = true;
  $("editor-toggle-sample").disabled = true;
  clearError();
  try {
    await requestJSON(`/api/imports/${encodeURIComponent(state.draft.font_id)}/sample`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_file: variant.sample_file, accepted: !variant.accepted }),
    });
    variant.accepted = !variant.accepted;
    if (!variant.accepted) {
      const result = await repairUnavailableGlyphs();
      if (result.repaired && await save()) {
        state.undo.length = 0;
        state.redo.length = 0;
      }
      if (result.unresolved) showError(`已停用这个版本，但 ${result.unresolved} 处没有其他可用的 ${variant.character} 字形。`);
    }
    renderPanel();
  } catch (error) {
    showError(error.message);
  } finally {
    state.toggling = false;
    renderPanel();
  }
}

async function save() {
  if (!state.draft || state.saving || !isDirty()) return true;
  state.saving = true;
  $("editor-workspace").style.pointerEvents = "none";
  clearError();
  markState();
  try {
    const updated = await requestJSON(`/api/compositions/${state.draft.id}/draft`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revision: state.draft.revision, placements: editPayload() }),
    });
    state.draft = updated;
    state.placements = updated.placements.map((item) => ({ ...item }));
    state.variants = new Map(updated.variants.map((variant) => [variant.sample_file, variant]));
    state.saved = snapshot();
    renderAll();
    return true;
  } catch (error) {
    showError(error.message);
    return false;
  } finally {
    state.saving = false;
    $("editor-workspace").style.pointerEvents = "";
    markState();
  }
}

async function exportPNG() {
  if (!(await save())) return;
  const link = document.createElement("a");
  link.href = `/api/compositions/${state.draft.id}/download?revision=${state.draft.revision}`;
  link.download = `handwriting-${state.draft.id}.png`;
  document.body.append(link);
  link.click();
  link.remove();
  await chooseWords();
}

async function chooseWords() {
  if (!(await save())) return;
  clearError();
  try {
    const candidates = await requestJSON(`/api/compositions/${state.draft.id}/word-candidates`);
    const list = $("editor-words-list");
    list.replaceChildren();
    if (!candidates.length) {
      const empty = document.createElement("p");
      empty.textContent = "当前没有由单个字母拼出的词。整词图片拆成字母并调整后，可再次保存为新版本。";
      list.append(empty);
    }
    for (const candidate of candidates) {
      const row = document.createElement("label");
      row.className = "editor-word-choice";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = candidate.key;
      checkbox.disabled = candidate.saved;
      checkbox.checked = !candidate.saved;
      checkbox.addEventListener("change", updateWordSelection);
      const title = document.createElement("span");
      const word = document.createElement("strong");
      word.textContent = candidate.word;
      const location = document.createElement("small");
      location.textContent = candidate.saved ? "本次已保存" :
        `第 ${candidate.line + 1} 行 · 第 ${candidate.column + 1} 位`;
      title.append(word, location);
      const preview = document.createElement("img");
      preview.src = `${candidate.preview_url}?revision=${state.draft.revision}`;
      preview.loading = "lazy";
      preview.alt = `${candidate.word} 的编辑结果`;
      row.append(checkbox, title, preview);
      list.append(row);
    }
    updateWordSelection();
    $("editor-words-error").hidden = true;
    $("editor-words-dialog").showModal();
  } catch (error) {
    showError(error.message);
  }
}

function updateWordSelection() {
  const available = [...$("editor-words-list").querySelectorAll("input:not(:disabled)")];
  const checked = available.filter((input) => input.checked).length;
  $("editor-words-confirm").disabled = checked === 0;
  $("editor-words-toggle-all").disabled = available.length === 0;
  $("editor-words-toggle-all").textContent = available.length && checked === available.length ? "取消全选" : "全选";
  $("editor-words-selected-count").textContent = `已选 ${checked} / ${available.length} 个可保存的词`;
}

function toggleAllWords() {
  const available = [...$("editor-words-list").querySelectorAll("input:not(:disabled)")];
  const select = available.some((input) => !input.checked);
  for (const input of available) input.checked = select;
  updateWordSelection();
}

async function saveSelectedWords() {
  const keys = [...$("editor-words-list").querySelectorAll("input:checked")]
    .map((input) => input.value);
  if (!keys.length) return;
  $("editor-words-confirm").disabled = true;
  try {
    const saved = await requestJSON(`/api/compositions/${state.draft.id}/words`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revision: state.draft.revision, keys }),
    });
    $("editor-words-dialog").close();
    $("editor-word-status").textContent = `已将 ${saved.length} 个词图片保存到 ${state.draft.font_id} 的词库。`;
    $("editor-word-status").hidden = false;
  } catch (error) {
    $("editor-words-error").textContent = error.message;
    $("editor-words-error").hidden = false;
    $("editor-words-confirm").disabled = false;
  }
}

async function load() {
  const id = new URLSearchParams(location.search).get("composition");
  if (!/^[0-9a-f]{32}$/.test(id || "")) {
    $("editor-loading").hidden = true;
    showError("缺少有效的拼接编号。请从拼接结果点击“编辑字形与排版”。");
    return;
  }
  try {
    const draft = await requestJSON(`/api/compositions/${id}/draft`);
    state.draft = draft;
    state.placements = draft.placements.map((item) => ({ ...item }));
    state.variants = new Map(draft.variants.map((variant) => [variant.sample_file, variant]));
    state.saved = snapshot();
    const repair = await repairUnavailableGlyphs();
    if (repair.repaired && await save()) {
      state.undo.length = 0;
      state.redo.length = 0;
    }
    if (repair.unresolved) showError(`${repair.unresolved} 处使用了已停用或已删除的字形，当前字库没有可替换版本。`);
    const returnUrl = `/?font=${encodeURIComponent(draft.font_id)}&composition=${draft.id}`;
    $("editor-back").href = returnUrl;
    $("editor-return").href = returnUrl;
    $("editor-document-meta").textContent = `${draft.font_id} · ${draft.line_count} 行`;
    for (let line = 0; line < draft.line_count; line++) {
      const option = document.createElement("option");
      option.value = String(line);
      option.textContent = `第 ${line + 1} 行`;
      $("editor-line").append(option);
    }
    UI.syncPopSelect("editor-line");
    $("editor-loading").hidden = true;
    $("editor-workspace").hidden = false;
    state.zoom = Math.max(0.1, Math.min(2, ($("editor-viewport").clientWidth - 64) / stageSize()[0]));
    $("editor-zoom").value = "fit";
    UI.syncPopSelect("editor-zoom");
    renderAll();
    if (location.hash === "#save-words") {
      history.replaceState(null, "", location.pathname + location.search);
      await chooseWords();
    }
  } catch (error) {
    $("editor-loading").hidden = true;
    showError(error.message);
  }
}

function canvasPoint(clientX, clientY) {
  const rect = $("editor-stage").getBoundingClientRect();
  const [width, height] = stageSize();
  return {
    x: Math.max(0, Math.min(width, (clientX - rect.left) / state.zoom)),
    y: Math.max(0, Math.min(height, (clientY - rect.top) / state.zoom)),
  };
}

function startMarquee(event) {
  if (event.target !== $("editor-stage") || event.button !== 0 || state.saving) return;
  if (event.pointerType === "touch") return;
  event.preventDefault();
  const start = canvasPoint(event.clientX, event.clientY);
  const origin = { x: event.clientX, y: event.clientY };
  const pointerId = event.pointerId;
  const additive = event.ctrlKey || event.metaKey;
  const existing = new Set(state.selectedIndices);
  const overlay = document.createElement("div");
  overlay.className = "edit-marquee";
  let moved = false;
  let latest = origin;
  let end = start;
  const update = () => {
    if (!moved) return;
    const viewport = $("editor-viewport");
    const bounds = viewport.getBoundingClientRect();
    if (latest.x >= bounds.left && latest.x <= bounds.right &&
        latest.y >= bounds.top && latest.y <= bounds.bottom) {
      if (latest.x < bounds.left + 24) viewport.scrollLeft -= 16;
      if (latest.x > bounds.right - 24) viewport.scrollLeft += 16;
      if (latest.y < bounds.top + 24) viewport.scrollTop -= 16;
      if (latest.y > bounds.bottom - 24) viewport.scrollTop += 16;
    }
    end = canvasPoint(latest.x, latest.y);
    overlay.style.left = `${Math.min(start.x, end.x)}px`;
    overlay.style.top = `${Math.min(start.y, end.y)}px`;
    overlay.style.width = `${Math.abs(end.x - start.x)}px`;
    overlay.style.height = `${Math.abs(end.y - start.y)}px`;
  };
  const timer = window.setInterval(update, 40);
  const move = (pointer) => {
    if (pointer.pointerId !== pointerId) return;
    latest = { x: pointer.clientX, y: pointer.clientY };
    if (!moved && Math.hypot(latest.x - origin.x, latest.y - origin.y) >= 4) {
      moved = true;
      $("editor-stage").append(overlay);
    }
    update();
  };
  const finish = (pointer) => {
    if (pointer.pointerId !== pointerId) return;
    window.clearInterval(timer);
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", finish);
    window.removeEventListener("pointercancel", cancel);
    latest = { x: pointer.clientX, y: pointer.clientY };
    if (!moved) { clearSelection(); return; }
    update();
    overlay.remove();
    const left = Math.min(start.x, end.x), right = Math.max(start.x, end.x);
    const top = Math.min(start.y, end.y), bottom = Math.max(start.y, end.y);
    const selected = additive ? existing : new Set();
    for (const [index, item] of state.placements.entries()) {
      const overlapWidth = Math.max(0, Math.min(right, item.x + item.width) - Math.max(left, item.x));
      const overlapHeight = Math.max(0, Math.min(bottom, item.y + item.height) - Math.max(top, item.y));
      if (overlapWidth * overlapHeight >= item.width * item.height * 0.25) selected.add(index);
    }
    const indices = [...selected].sort((a, b) => a - b);
    setSelection(indices, indices.length ? indices[0] : null);
  };
  const cancel = (pointer) => {
    if (pointer.pointerId !== pointerId) return;
    window.clearInterval(timer);
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", finish);
    window.removeEventListener("pointercancel", cancel);
    overlay.remove();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", finish);
  window.addEventListener("pointercancel", cancel);
}

$("editor-stage").addEventListener("pointerdown", startMarquee);
$("editor-deselect").addEventListener("click", clearSelection);
$("editor-clear-group").addEventListener("click", clearSelection);
$("editor-undo").addEventListener("click", undo);
$("editor-redo").addEventListener("click", redo);
$("editor-align").addEventListener("click", alignBaselines);
$("editor-save").addEventListener("click", save);
$("editor-save-words").addEventListener("click", chooseWords);
$("editor-export").addEventListener("click", exportPNG);
$("editor-toggle-sample").addEventListener("click", toggleSample);
$("editor-break-word").addEventListener("click", breakWord);
$("editor-words-close").addEventListener("click", () => $("editor-words-dialog").close());
$("editor-words-skip").addEventListener("click", () => $("editor-words-dialog").close());
$("editor-words-confirm").addEventListener("click", saveSelectedWords);
$("editor-words-toggle-all").addEventListener("click", toggleAllWords);
$("editor-guides").addEventListener("change", renderStage);
$("editor-zoom").addEventListener("change", () => {
  state.zoom = $("editor-zoom").value === "fit"
    ? Math.max(0.1, Math.min(2, ($("editor-viewport").clientWidth - 64) / stageSize()[0]))
    : Number($("editor-zoom").value);
  applyZoom();
});
$("editor-fit").addEventListener("click", () => {
  const width = stageSize()[0];
  state.zoom = Math.max(0.1, Math.min(2, ($("editor-viewport").clientWidth - 64) / width));
  $("editor-zoom").value = "fit";
  UI.syncPopSelect("editor-zoom");
  applyZoom();
});
for (const field of ["x", "y"]) {
  $(`editor-${field}`).addEventListener("change", () => {
    if (state.selected === null) return;
    const value = Number($(`editor-${field}`).value);
    if (!Number.isInteger(value) || value < 0 || value > 12000) { renderSelectionFields(); return; }
    const before = snapshot();
    state.placements[state.selected][field] = value;
    commit(before);
  });
}
for (const field of ["x", "y"]) {
  $(`editor-group-${field}`).addEventListener("change", () => {
    if (state.selectedIndices.size < 2) return;
    const value = Number($(`editor-group-${field}`).value);
    if (!Number.isInteger(value) || value < 0 || value > 12000) { renderGroupFields(); return; }
    const bounds = selectionBounds();
    moveSelection(field === "x" ? value - bounds.left : 0,
                  field === "y" ? value - bounds.top : 0);
    renderGroupFields();
  });
}
$("editor-scale").addEventListener("change", () => changeScale(Number($("editor-scale").value)));
$("editor-gap").addEventListener("change", () => changeGap(Number($("editor-gap").value)));
$("editor-line-up").addEventListener("click", () => shiftLine(-4));
$("editor-line-down").addEventListener("click", () => shiftLine(4));
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.selectedIndices.size) {
    event.preventDefault();
    clearSelection();
    return;
  }
  if (event.target.closest("input, select, textarea")) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) redo(); else undo();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); return; }
  if (!state.selectedIndices.size || state.saving) return;
  const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  if (!moves[event.key]) return;
  event.preventDefault();
  const [dx, dy] = moves[event.key];
  const step = event.shiftKey ? 10 : 1;
  moveSelection(dx * step, dy * step);
});
window.addEventListener("beforeunload", (event) => {
  if (!isDirty()) return;
  event.preventDefault();
  event.returnValue = "";
});
load();
