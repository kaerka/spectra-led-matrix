"""Controls for procedural effects, shared by the wall UI and the orchestrator.

Plain strings (not f-strings) so the JS braces need no escaping; both pages
interpolate them into their HTML. Relies on the pages' existing
``flame-swatch`` / ``flame-intensity`` / ``flame-stop`` styles.
"""

EFFECT_CSS = """
    .effect-option { margin-top: 0.55rem; }
    .effect-option .flame-intensity { margin-top: 0.25rem; }
    .effect-label { font-size: 0.78rem; color: #9aa0a6; }
"""

EFFECT_JS = r"""
    function effectHex(rgb) {
      return "#" + rgb.map(v => v.toString(16).padStart(2, "0")).join("");
    }

    function effectRgb(hex) {
      return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
    }

    function effectSwatchBackground(stops) {
      if (stops.length === 1) return effectHex(stops[0]);
      return `linear-gradient(135deg, ${stops.map(effectHex).join(", ")})`;
    }

    // Builds palette swatches, custom colour pickers and option buttons from the
    // /effect config. save(patch, label) persists one change. Skips the rebuild
    // when nothing changed so periodic refreshes don't close an open picker.
    function renderEffectPanel(el, cfg, save) {
      const key = JSON.stringify(cfg);
      if (el.dataset.cfg === key) return;
      el.dataset.cfg = key;
      const options = cfg.options.map(o => `
        <div class="effect-option">
          <span class="effect-label">${o.label}</span>
          <div class="flame-intensity">${o.choices.map((choice, i) =>
            `<button type="button" class="${i === o.value ? "active" : ""}"
                     data-key="${o.key}" data-value="${i}">${choice}</button>`).join("")}</div>
        </div>`).join("");
      const swatches = Object.entries(cfg.palettes).map(([name, stops]) =>
        `<button type="button" class="flame-swatch${name === cfg.palette ? " active" : ""}"
                 data-palette="${name}" title="${name}"
                 style="background:${effectSwatchBackground(stops)}"></button>`).join("");
      const pickers = cfg.color_labels.map((label, i) => `
        <label class="flame-stop"><span>${label}${cfg.palette ? "" : " (custom)"}</span>
          <input type="color" data-slot="${i}" value="${effectHex(cfg.colors[i])}"></label>`).join("");
      el.innerHTML = `
        <div class="effect-option"><span class="effect-label">Palette</span>
          <div class="flame-swatches" style="margin-top:0.25rem">${swatches}</div></div>
        <div class="flame-stops">${pickers}</div>
        ${options}`;
      el.querySelectorAll("button[data-key]").forEach(btn => btn.addEventListener("click", () =>
        save({ [btn.dataset.key]: Number(btn.dataset.value) }, btn.textContent.trim())));
      el.querySelectorAll("button[data-palette]").forEach(btn => btn.addEventListener("click", () =>
        save({ palette: btn.dataset.palette }, btn.dataset.palette)));
      el.querySelectorAll("input[data-slot]").forEach(input => input.addEventListener("change", () => {
        const colors = cfg.colors.map(c => c.slice());
        colors[Number(input.dataset.slot)] = effectRgb(input.value);
        save({ colors }, input.value);
      }));
    }
"""
