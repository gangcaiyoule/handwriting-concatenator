const $ = (id) => document.getElementById(id);

const state = {
  draft: null,
  placements: [],
  variants: new Map(),
  selected: null,
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
    sample_file: item.sample_file,
    x: item.x,
    y: item.y,
    scale: item.scale,
  }));
}

function snapshot() { return JSON.stringify(editPayload()); }
function variantFor(file) { return state.variants.get(file); }
function isDirty() { return Boolean(state.draft && snapshot() !== state.saved); }

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
  $("editor-save-state").textContent = state.saving ? "保存中…" : isDirty() ? "尚未保存" : "已保存";
  $("editor-save").disabled = state.saving || !isDirty();
  $("editor-export").disabled = state.saving;
  $("editor-undo").disabled = state.saving || !state.undo.length;
  $("editor-redo").disabled = state.saving || !state.redo.length;
}

function commit(previous) {
  if (snapshot() === previous) return;
  state.undo.push(previous);
  if (state.undo.length > 100) state.undo.shift();
  state.redo.length = 0;
  renderAll();
}

function restore(serialized) {
  const edits = JSON.parse(serialized);
  for (const [index, edit] of edits.entries()) {
    const item = state.placements[index];
    const variant = variantFor(edit.sample_file);
    Object.assign(item, edit, {
      width: Math.max(1, Math.round(variant.width * edit.scale)),
      height: Math.max(1, Math.round(variant.height * edit.scale)),
    });
  }
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
    glyph.className = `edit-glyph${state.selected === index ? " is-selected" : ""}`;
    glyph.dataset.index = String(index);
    glyph.setAttribute("aria-label", `第 ${item.line + 1} 行，第 ${item.column + 1} 个字符 ${item.character}`);
    glyph.style.left = `${item.x}px`;
    glyph.style.top = `${item.y}px`;
    glyph.style.width = `${item.width}px`;
    glyph.style.height = `${item.height}px`;
    const image = document.createElement("img");
    image.src = variant.image_url;
    image.alt = "";
    image.draggable = false;
    glyph.append(image);
    glyph.addEventListener("pointerdown", (event) => startDrag(event, "glyph", index));
    glyph.addEventListener("click", (event) => event.stopPropagation());
    stage.append(glyph);
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

function renderPanel() {
  const selected = state.selected;
  $("editor-no-selection").hidden = selected !== null;
  $("editor-selection").hidden = selected === null;
  if (selected === null) return;
  const item = state.placements[selected];
  $("editor-character").textContent = item.character;
  $("editor-character-meta").textContent = `第 ${item.line + 1} 行 · 第 ${item.column + 1} 格`;
  $("editor-line").value = String(item.line);
  const variants = [...state.variants.values()].filter((variant) => variant.character === item.character);
  const list = $("editor-variants");
  list.replaceChildren();
  for (const variant of variants) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `editor-variant${variant.sample_file === item.sample_file ? " is-selected" : ""}`;
    button.disabled = !variant.accepted;
    button.setAttribute("aria-label", `使用 ${item.character} 的版本 ${variant.occurrence}${variant.accepted ? "" : "，已停用"}`);
    const image = document.createElement("img");
    image.src = variant.image_url;
    image.alt = "";
    const label = document.createElement("span");
    label.textContent = variant.accepted ? `版本 ${variant.occurrence}` : "已停用";
    button.append(image, label);
    button.addEventListener("click", () => replaceVariant(variant));
    list.append(button);
  }
  const current = variantFor(item.sample_file);
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

function refreshPositions() {
  for (const glyph of $("editor-stage").querySelectorAll(".edit-glyph")) {
    const item = state.placements[Number(glyph.dataset.index)];
    glyph.style.left = `${item.x}px`;
    glyph.style.top = `${item.y}px`;
  }
  const handle = $("editor-stage").querySelector(".edit-gap-handle");
  if (handle && state.selected !== null) {
    handle.style.left = `${state.placements[state.selected].x - 7}px`;
    handle.style.top = `${Math.max(0, state.placements[state.selected].y - 4)}px`;
  }
  applyZoom();
  renderSelectionFields();
}

function startDrag(event, mode, index) {
  if (event.button !== 0 || state.saving) return;
  event.preventDefault();
  event.stopPropagation();
  if (state.selected !== index) {
    state.selected = index;
    renderAll();
  }
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
      state.placements[index].x = Math.max(0, positions[index].x + dx);
      state.placements[index].y = Math.max(0, positions[index].y + dy);
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
  const variant = variantFor(state.placements[state.selected].sample_file);
  state.toggling = true;
  $("editor-toggle-sample").disabled = true;
  clearError();
  try {
    await requestJSON(`/api/imports/${state.draft.font_id}/sample`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_file: variant.sample_file, accepted: !variant.accepted }),
    });
    variant.accepted = !variant.accepted;
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
    $("editor-back").href = `/?import=${draft.font_id}&composition=${draft.id}`;
    for (let line = 0; line < draft.line_count; line++) {
      const option = document.createElement("option");
      option.value = String(line);
      option.textContent = `第 ${line + 1} 行`;
      $("editor-line").append(option);
    }
    $("editor-loading").hidden = true;
    $("editor-workspace").hidden = false;
    renderAll();
  } catch (error) {
    $("editor-loading").hidden = true;
    showError(error.message);
  }
}

$("editor-stage").addEventListener("pointerdown", (event) => {
  if (event.target !== $("editor-stage")) return;
  state.selected = null;
  renderAll();
});
$("editor-deselect").addEventListener("click", () => { state.selected = null; renderAll(); });
$("editor-undo").addEventListener("click", undo);
$("editor-redo").addEventListener("click", redo);
$("editor-align").addEventListener("click", alignBaselines);
$("editor-save").addEventListener("click", save);
$("editor-export").addEventListener("click", exportPNG);
$("editor-toggle-sample").addEventListener("click", toggleSample);
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
$("editor-scale").addEventListener("change", () => changeScale(Number($("editor-scale").value)));
$("editor-gap").addEventListener("change", () => changeGap(Number($("editor-gap").value)));
$("editor-line-up").addEventListener("click", () => shiftLine(-4));
$("editor-line-down").addEventListener("click", () => shiftLine(4));
window.addEventListener("keydown", (event) => {
  if (event.target.closest("input, select, textarea")) return;
  if (event.ctrlKey && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) redo(); else undo();
    return;
  }
  if (event.ctrlKey && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); return; }
  if (state.selected === null || state.saving) return;
  const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  if (!moves[event.key]) return;
  event.preventDefault();
  const before = snapshot();
  const [dx, dy] = moves[event.key];
  const step = event.shiftKey ? 10 : 1;
  const item = state.placements[state.selected];
  item.x = Math.max(0, item.x + dx * step);
  item.y = Math.max(0, item.y + dy * step);
  commit(before);
});
window.addEventListener("beforeunload", (event) => {
  if (!isDirty()) return;
  event.preventDefault();
  event.returnValue = "";
});
load();
