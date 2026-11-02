"""Auto-rotate controls, shared by the wall UI and the orchestrator.

Plain strings like ``effect_ui``; relies on the pages' existing ``switch`` /
``slider`` / ``flame-intensity`` styles.
"""

ROTATION_CSS = """
    .rotation-box {
      background: #0b0d11; border: 1px solid #2a2f3a; border-radius: 10px; padding: 0.7rem 0.85rem;
    }
    .rotation-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
    .rotation-status { color: #9aa0a6; font-size: 0.82rem; display: block; margin-top: 0.15rem; }
    .rotation-modes summary { cursor: pointer; color: #9aa0a6; font-size: 0.85rem; margin-top: 0.65rem; }
    .rotation-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr));
      gap: 0.3rem 0.75rem; margin-top: 0.5rem; font-size: 0.85rem;
    }
    .rotation-grid label { display: flex; align-items: center; gap: 0.4rem; cursor: pointer; }
    .rotation-grid input { accent-color: #5f9cff; }
    .rotation-quick { display: flex; gap: 0.4rem; margin-top: 0.5rem; }
    .rotation-quick button {
      background: #1a1d24; border: 1px solid #30343c; border-radius: 8px; color: inherit;
      cursor: pointer; font-size: 0.78rem; padding: 0.3rem 0.6rem;
    }
"""

ROTATION_JS = r"""
    function rotationCountdown(el) {
      const status = el.querySelector("[data-rotation-status]");
      if (!status) return;
      const due = Number(el.dataset.due || 0);
      if (!due) { status.textContent = el.dataset.idle || "Off"; return; }
      const left = Math.max(0, Math.round(due - Date.now() / 1000));
      const m = Math.floor(left / 60), s = String(left % 60).padStart(2, "0");
      status.textContent = `Next switch in ${m}:${s}`;
    }

    // Renders the toggle, interval buttons, and mode checklist from /rotation.
    // save(patch, label) persists one change. Countdown ticks locally; the panel
    // is only rebuilt when settings change so an open checklist stays open.
    function renderRotationPanel(el, data, save, force) {
      if (force) delete el.dataset.cfg;
      // seconds_left, not next_switch_at, so browser/Pi clock skew doesn't matter.
      el.dataset.due = data.next_switch_at ? String(Date.now() / 1000 + data.seconds_left) : "";
      el.dataset.idle = data.enabled ? "Pick at least two modes" : "Off — stays on the current mode";
      const key = JSON.stringify([data.enabled, data.interval_s, data.modes]);
      if (el.dataset.cfg !== key) {
        el.dataset.cfg = key;
        const picked = new Set(data.modes);
        const open = el.querySelector("details")?.open ? "open" : "";
        el.innerHTML = `
          <div class="rotation-head">
            <div><strong>Auto-rotate</strong>
              <span class="rotation-status" data-rotation-status></span></div>
            <label class="switch" title="Randomly rotate modes on a timer">
              <input type="checkbox" data-rotation-enabled ${data.enabled ? "checked" : ""}>
              <span class="slider"></span>
            </label>
          </div>
          <div class="flame-intensity">${data.intervals.map(i =>
            `<button type="button" class="${i.seconds === data.interval_s ? "active" : ""}"
                     data-interval="${i.seconds}">Every ${i.label}</button>`).join("")}</div>
          <details class="rotation-modes" ${open}>
            <summary>Modes in rotation (${data.modes.length} of ${data.available.length})</summary>
            <div class="rotation-quick">
              <button type="button" data-rotation-preset="animations">Animations only</button>
              <button type="button" data-rotation-preset="all">Everything</button>
            </div>
            <div class="rotation-grid">${data.available.map(m =>
              `<label><input type="checkbox" data-rotation-mode="${m.id}" ${picked.has(m.id) ? "checked" : ""}>
                 ${m.label}</label>`).join("")}</div>
          </details>`;
        el.querySelector("[data-rotation-enabled]").addEventListener("change", e =>
          save({ enabled: e.target.checked }, e.target.checked ? "auto-rotate on" : "auto-rotate off"));
        el.querySelectorAll("[data-interval]").forEach(btn => btn.addEventListener("click", () =>
          save({ interval_s: Number(btn.dataset.interval) }, btn.textContent.trim().toLowerCase())));
        el.querySelectorAll("[data-rotation-preset]").forEach(btn => btn.addEventListener("click", () => {
          const modes = btn.dataset.rotationPreset === "all" ? data.available.map(m => m.id) : data.default_modes;
          save({ modes }, btn.textContent.trim().toLowerCase());
        }));
        el.querySelectorAll("[data-rotation-mode]").forEach(box => box.addEventListener("change", () => {
          const modes = [...el.querySelectorAll("[data-rotation-mode]:checked")].map(b => b.dataset.rotationMode);
          save({ modes }, `${modes.length} modes`);
        }));
      }
      rotationCountdown(el);
      if (!el.dataset.ticking) {
        el.dataset.ticking = "1";
        setInterval(() => rotationCountdown(el), 1000);
      }
    }
"""
