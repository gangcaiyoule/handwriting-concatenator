/* Shared, progressively enhanced controls for both static pages. */
(function () {
  const icon = (name) => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ui-icon ui-icon--sm");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `/static/icons.svg#${name}`);
    svg.append(use);
    return svg;
  };

  const popupSelects = new Map();
  function enhanceSelect(select) {
    if (popupSelects.has(select.id)) return;
    const wrapper = document.createElement("div");
    wrapper.className = "ui-pop-select";
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "ui-btn ui-pop-select__trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    const parentLabel = select.closest("label");
    trigger.setAttribute("aria-label", select.getAttribute("aria-label") ||
      document.querySelector(`label[for="${select.id}"]`)?.textContent.trim() ||
      parentLabel?.querySelector("span")?.textContent.trim() ||
      parentLabel?.firstChild?.textContent.trim() || "选择选项");
    const label = document.createElement("span");
    label.className = "ui-pop-select__value";
    trigger.append(label, icon("chevron-down"));
    const menu = document.createElement("div");
    menu.className = "ui-pop-select__menu";
    menu.id = `${select.id}-menu`;
    menu.setAttribute("popover", "auto");
    menu.setAttribute("role", "listbox");
    menu.setAttribute("aria-label", trigger.getAttribute("aria-label"));
    trigger.setAttribute("aria-controls", menu.id);
    select.after(wrapper);
    wrapper.append(trigger, menu);
    select.classList.add("ui-native-select");
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;

    const render = () => {
      const active = select.selectedOptions[0];
      label.textContent = active?.textContent || "请选择";
      trigger.disabled = select.disabled;
      menu.replaceChildren();
      for (const option of select.options) {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "ui-pop-select__option";
        row.setAttribute("role", "option");
        row.setAttribute("aria-selected", String(option.selected));
        row.disabled = option.disabled;
        const text = document.createElement("span");
        text.textContent = option.textContent;
        row.append(text);
        if (option.selected) row.append(icon("tick-02"));
        row.addEventListener("click", () => {
          select.value = option.value;
          select.dispatchEvent(new Event("change", { bubbles: true }));
          render();
          menu.hidePopover();
          trigger.focus();
        });
        menu.append(row);
      }
    };
    const place = () => {
      const rect = trigger.getBoundingClientRect();
      const roomBelow = window.innerHeight - rect.bottom;
      const height = Math.min(menu.scrollHeight, 320, window.innerHeight * .5);
      const top = roomBelow >= height + 8 || rect.top < height + 8
        ? rect.bottom + 5 : rect.top - height - 5;
      menu.style.top = `${Math.max(8, top)}px`;
      const width = Math.min(Math.max(rect.width, 220), window.innerWidth - 16);
      menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`;
      menu.style.width = `${width}px`;
    };
    trigger.addEventListener("click", () => {
      render();
      if (menu.matches(":popover-open")) menu.hidePopover();
      else { menu.showPopover(); place(); }
    });
    trigger.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      render();
      menu.showPopover();
      place();
      const options = [...menu.querySelectorAll(".ui-pop-select__option:not(:disabled)")];
      (event.key === "ArrowDown" ? options[0] : options.at(-1))?.focus();
    });
    menu.addEventListener("keydown", (event) => {
      const options = [...menu.querySelectorAll(".ui-pop-select__option:not(:disabled)")];
      const index = options.indexOf(document.activeElement);
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        options[(index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length]?.focus();
      } else if (event.key === "Escape") {
        menu.hidePopover(); trigger.focus();
      }
    });
    menu.addEventListener("toggle", () => trigger.setAttribute("aria-expanded", String(menu.matches(":popover-open"))));
    select.addEventListener("change", render);
    const observer = new MutationObserver(render);
    observer.observe(select, { childList: true, subtree: true, attributes: true,
      attributeFilter: ["disabled", "label", "selected"] });
    popupSelects.set(select.id, render);
    render();
  }

  function confirm({ title, message, confirmText = "确认", danger = false }) {
    return new Promise((resolve) => {
      const dialog = document.createElement("dialog");
      dialog.className = "ui-modal ui-modal--confirm";
      dialog.setAttribute("aria-label", title);
      const heading = document.createElement("div");
      heading.className = "ui-modal__header";
      const h2 = document.createElement("h2");
      h2.textContent = title;
      heading.append(h2);
      const body = document.createElement("div");
      body.className = "ui-modal__body";
      body.textContent = message;
      const actions = document.createElement("div");
      actions.className = "ui-modal__actions";
      const cancel = document.createElement("button");
      cancel.type = "button"; cancel.className = "ui-btn"; cancel.textContent = "取消";
      const accept = document.createElement("button");
      accept.type = "button"; accept.className = `ui-btn ${danger ? "ui-btn--danger" : "ui-btn--primary"}`;
      accept.textContent = confirmText;
      actions.append(cancel, accept);
      dialog.append(heading, body, actions);
      document.body.append(dialog);
      let accepted = false;
      cancel.addEventListener("click", () => dialog.close());
      accept.addEventListener("click", () => { accepted = true; dialog.close(); });
      dialog.addEventListener("close", () => { dialog.remove(); resolve(accepted); }, { once: true });
      dialog.showModal();
      cancel.focus();
    });
  }

  document.querySelectorAll("select[data-popup]").forEach(enhanceSelect);
  document.querySelectorAll("dialog.ui-modal").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });
  window.UI = {
    icon,
    confirm,
    syncPopSelect(id) { popupSelects.get(id)?.(); },
    syncAllPopSelects() { for (const render of popupSelects.values()) render(); },
  };
})();
