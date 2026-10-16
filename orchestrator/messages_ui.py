"""Dashboard section for custom messages (plain strings, injected into the page)."""

MESSAGES_CSS = """
    .msg-list { display: grid; gap: 0.6rem; }
    .msg-card {
      display: grid; grid-template-columns: auto 1fr auto; gap: 0.75rem; align-items: center;
      background: #161a22; border: 1px solid #2a2f3a; border-radius: 10px; padding: 0.6rem 0.75rem;
    }
    .msg-card.disabled { opacity: 0.55; }
    .msg-card .msg-lines { font-size: 0.9rem; line-height: 1.3; }
    .msg-card .msg-meta { color: #6b7280; font-size: 0.78rem; margin-top: 0.2rem; }
    .msg-actions { display: flex; gap: 0.35rem; }
    .msg-actions button, .msg-editor .toolbar button { padding: 0.4rem 0.65rem; text-align: center; }
    .msg-status { color: #9aa0a6; font-size: 0.82rem; margin: 0.6rem 0 0; display: grid; gap: 0.2rem; }
    .msg-status .ok { color: #7dcea0; }
    .msg-status .bad { color: #e57373; }
    .msg-editor {
      margin-top: 0.85rem; padding: 0.85rem; border: 1px solid #3d4450; border-radius: 10px;
      background: #10131a; display: none;
    }
    .msg-editor.open { display: grid; gap: 0.7rem; grid-template-columns: minmax(0, 1fr) auto; }
    .msg-form { display: grid; gap: 0.6rem; }
    .msg-form label { color: #9aa0a6; font-size: 0.82rem; }
    .msg-form input[type=text], .msg-form input[type=number], .msg-form input[type=time],
    .msg-form input[type=date], .msg-form select {
      background: #1a1d24; color: inherit; border: 1px solid #30343c; border-radius: 6px;
      padding: 0.35rem 0.45rem; font: inherit; font-size: 0.88rem;
    }
    .msg-row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
    .msg-line-row { display: grid; grid-template-columns: 1fr auto auto; gap: 0.4rem; }
    .msg-line-row input[type=color] { width: 2.4rem; height: 2rem; border: none; background: none; padding: 0; }
    .msg-days label { display: inline-flex; gap: 0.2rem; align-items: center; margin-right: 0.45rem; color: #cbd5e1; }
    .msg-preview { display: grid; gap: 0.5rem; justify-items: center; align-content: start; }
    .msg-preview canvas { image-rendering: pixelated; border: 1px solid #2a2f3a; background: #000; }
    .msg-preview .hint { margin: 0; text-align: center; }
    @media (max-width: 52rem) { .msg-editor.open { grid-template-columns: 1fr; } }
"""

MESSAGES_HTML = """
    <section class="wide" id="messages-section">
      <h2>Custom messages</h2>
      <p class="hint">Text shown on a schedule, then the display returns to what it was showing.
        Live MQTT captions take priority. Times use <span id="msg-tz">the wall timezone</span>.</p>
      <div class="msg-list" id="msg-list"><em>Loading…</em></div>
      <div class="toolbar">
        <button type="button" id="msg-add">+ Add message</button>
        <button type="button" id="msg-sync" title="Re-send the list to every display">Re-sync displays</button>
      </div>
      <div class="msg-status" id="msg-status"></div>

      <div class="msg-editor" id="msg-editor">
        <div class="msg-form">
          <div class="msg-row">
            <label>Name <input type="text" id="msg-name" maxlength="60" placeholder="Goals"></label>
            <label>Lines
              <select id="msg-line-count"><option>1</option><option>2</option><option selected>3</option></select>
            </label>
            <label><input type="checkbox" id="msg-enabled" checked> Enabled</label>
          </div>
          <div id="msg-lines"></div>
          <div class="msg-row">
            <label>Every <input type="number" id="msg-every" min="1" max="1440" value="30" style="width:5rem"> minutes</label>
            <label>for <input type="number" id="msg-duration" min="3" max="300" value="15" style="width:4.5rem"> seconds</label>
          </div>
          <div class="msg-days" id="msg-days"></div>
          <div class="msg-row">
            <label><input type="checkbox" id="msg-hours-on"> Only between</label>
            <input type="time" id="msg-from" value="08:00">
            <label>and</label>
            <input type="time" id="msg-until" value="22:00">
          </div>
          <div class="msg-row">
            <label>From <input type="date" id="msg-start"></label>
            <label>to <input type="date" id="msg-end"></label>
            <span class="hint" style="margin:0">(optional, inclusive)</span>
          </div>
          <div class="msg-row" id="msg-targets"></div>
          <div class="msg-row">
            <label>Other display ids <input type="text" id="msg-other-targets" placeholder="matrixportal-s3, hat-mini" style="width:16rem"></label>
          </div>
          <div class="toolbar">
            <button type="button" id="msg-save" class="sync">Save</button>
            <button type="button" id="msg-show-now">Show now</button>
            <button type="button" id="msg-cancel">Cancel</button>
          </div>
        </div>
        <div class="msg-preview">
          <canvas id="msg-prev-big" width="192" height="192" style="width:192px;height:192px"></canvas>
          <p class="hint">192×192 wall</p>
          <div class="msg-row" style="justify-content:center">
            <div><canvas id="msg-prev-64" width="64" height="64" style="width:128px;height:128px"></canvas><p class="hint">64×64</p></div>
            <div><canvas id="msg-prev-48" width="64" height="48" style="width:128px;height:96px"></canvas><p class="hint">64×48</p></div>
          </div>
          <p class="hint">Approximate preview</p>
        </div>
      </div>
    </section>
"""

MESSAGES_JS = r"""
    (function () {
      const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
      const SIZE_PX = { small: 16, medium: 22, large: 30 };
      const DEFAULT_LINES = [
        { text: "", size: "large", color: [255, 200, 0] },
        { text: "", size: "medium", color: [255, 255, 255] },
        { text: "", size: "small", color: [120, 200, 255] },
      ];
      const $ = id => document.getElementById(id);
      let state = { messages: [], hosts: [], host_ids: [] };
      let editing = null;     // index into state.messages, or -1 for a new message
      let draftLines = [];

      const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
      const toHex = rgb => "#" + rgb.map(v => v.toString(16).padStart(2, "0")).join("");
      const fromHex = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
      const fmtTime = iso => iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";

      function summary(m) {
        const parts = [`every ${m.every_minutes} min for ${m.duration_seconds}s`];
        if (m.days.length < 7) parts.push(m.days.map(d => d[0].toUpperCase() + d.slice(1)).join(" "));
        if (m.active_from) parts.push(`${m.active_from}–${m.active_until}`);
        if (m.start_date || m.end_date) parts.push(`${m.start_date || "…"} → ${m.end_date || "…"}`);
        parts.push(m.targets.includes("all") ? "all displays" : m.targets.join(", "));
        return parts.join(" · ");
      }

      function renderList() {
        const list = $("msg-list");
        if (!state.messages.length) {
          list.innerHTML = "<em>No messages yet.</em>";
        } else {
          list.innerHTML = state.messages.map((m, i) => `
            <div class="msg-card${m.enabled ? "" : " disabled"}">
              <label class="switch" title="Enable or disable">
                <input type="checkbox" data-msg-toggle="${i}" ${m.enabled ? "checked" : ""}><span class="slider"></span>
              </label>
              <div>
                <div class="msg-lines">${m.lines.map(l => `<span style="color:${toHex(l.color)}">${esc(l.text)}</span>`).join("<br>")}</div>
                <div class="msg-meta"><strong>${esc(m.name)}</strong> · ${esc(summary(m))}</div>
              </div>
              <div class="msg-actions">
                <button type="button" data-msg-show="${i}" title="Show now">▶</button>
                <button type="button" data-msg-edit="${i}">Edit</button>
                <button type="button" data-msg-delete="${i}" title="Delete">✕</button>
              </div>
            </div>`).join("");
        }
        $("msg-tz").textContent = state.timezone || "the wall timezone";
        $("msg-status").innerHTML = (state.hosts || []).map(h => {
          let line = `<span class="${h.in_sync ? "ok" : "bad"}">${esc(h.label)}: ${h.online ? (h.in_sync ? "in sync" : "out of sync") : "offline"}</span>`;
          if (h.now_showing) line += ` · showing <strong>${esc(h.now_showing.name)}</strong> until ${fmtTime(h.now_showing.end)}`;
          else if (h.next_showing) line += ` · next <strong>${esc(h.next_showing.name)}</strong> at ${fmtTime(h.next_showing.start)}`;
          return `<div>${line}</div>`;
        }).join("") + (state.mqtt_error ? `<div class="bad">${esc(state.mqtt_error)}</div>` : "");
      }

      async function call(method, url, body) {
        const res = await fetch(url, {
          method, headers: { "Content-Type": "application/json" },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok) throw new Error((data && data.detail) || `${method} ${url} failed`);
        return data;
      }

      async function load() {
        try {
          state = await call("GET", "/api/messages");
          renderList();
        } catch (err) {
          $("msg-list").innerHTML = "<em>Unavailable</em>";
        }
      }

      async function saveAll(messages, okText) {
        try {
          state = await call("PUT", "/api/messages", { messages });
          renderList();
          const offline = state.hosts.filter(h => !h.in_sync).map(h => h.label);
          showToast(offline.length ? `${okText}; not yet on ${offline.join(", ")}` : okText);
          return true;
        } catch (err) {
          showToast(err.message);
          return false;
        }
      }

      function newId(name) {
        const base = (name || "message").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 30) || "message";
        const taken = new Set(state.messages.map(m => m.id));
        let id = base, n = 2;
        while (taken.has(id)) id = `${base}-${n++}`;
        return id;
      }

      function renderLineInputs() {
        const count = parseInt($("msg-line-count").value, 10);
        while (draftLines.length < count) draftLines.push({ ...DEFAULT_LINES[draftLines.length] });
        draftLines = draftLines.slice(0, count);
        $("msg-lines").innerHTML = draftLines.map((l, i) => `
          <div class="msg-line-row">
            <input type="text" maxlength="80" data-line-text="${i}" value="${esc(l.text)}" placeholder="Line ${i + 1}">
            <select data-line-size="${i}">${["small", "medium", "large"].map(s => `<option ${s === l.size ? "selected" : ""}>${s}</option>`).join("")}</select>
            <input type="color" data-line-color="${i}" value="${toHex(l.color)}">
          </div>`).join("");
        drawPreviews();
      }

      function renderTargets(targets) {
        const all = targets.includes("all");
        const known = state.host_ids || [];
        $("msg-targets").innerHTML = `<label><input type="checkbox" id="msg-target-all" ${all ? "checked" : ""}> All displays</label>` +
          known.map(id => `<label><input type="checkbox" data-target="${esc(id)}" ${!all && targets.includes(id) ? "checked" : ""} ${all ? "disabled" : ""}> ${esc(id)}</label>`).join("");
        $("msg-other-targets").value = targets.filter(t => t !== "all" && !known.includes(t)).join(", ");
        $("msg-other-targets").disabled = all;
        $("msg-target-all").addEventListener("change", e => renderTargets(e.target.checked ? ["all"] : []));
      }

      function openEditor(index) {
        editing = index;
        const m = index >= 0 ? state.messages[index] : {
          name: "", enabled: true, lines: DEFAULT_LINES.map(l => ({ ...l })), every_minutes: 30,
          duration_seconds: 15, days: DAYS, active_from: null, active_until: null,
          start_date: null, end_date: null, targets: ["all"],
        };
        draftLines = m.lines.map(l => ({ ...l, color: [...l.color] }));
        $("msg-name").value = m.name;
        $("msg-enabled").checked = m.enabled;
        $("msg-line-count").value = String(m.lines.length);
        $("msg-every").value = m.every_minutes;
        $("msg-duration").value = m.duration_seconds;
        $("msg-days").innerHTML = DAYS.map(d => `<label><input type="checkbox" data-day="${d}" ${m.days.includes(d) ? "checked" : ""}>${d[0].toUpperCase() + d.slice(1)}</label>`).join("");
        $("msg-hours-on").checked = !!m.active_from;
        $("msg-from").value = m.active_from || "08:00";
        $("msg-until").value = m.active_until || "22:00";
        $("msg-start").value = m.start_date || "";
        $("msg-end").value = m.end_date || "";
        renderTargets(m.targets);
        renderLineInputs();
        $("msg-editor").classList.add("open");
        $("msg-editor").scrollIntoView({ behavior: "smooth", block: "nearest" });
      }

      function closeEditor() {
        editing = null;
        $("msg-editor").classList.remove("open");
      }

      function readEditor() {
        const prev = editing >= 0 ? state.messages[editing] : null;
        const name = $("msg-name").value.trim();
        let targets = ["all"];
        if (!$("msg-target-all").checked) {
          targets = [...document.querySelectorAll("[data-target]:checked")].map(el => el.dataset.target)
            .concat($("msg-other-targets").value.split(",").map(s => s.trim()).filter(Boolean));
        }
        const hours = $("msg-hours-on").checked;
        return {
          id: prev ? prev.id : newId(name),
          name: name || (prev ? prev.id : "Message"),
          enabled: $("msg-enabled").checked,
          lines: draftLines.map(l => ({ text: l.text.trim(), size: l.size, color: l.color })),
          every_minutes: parseInt($("msg-every").value, 10),
          duration_seconds: parseInt($("msg-duration").value, 10),
          days: [...document.querySelectorAll("[data-day]:checked")].map(el => el.dataset.day),
          active_from: hours ? $("msg-from").value : null,
          active_until: hours ? $("msg-until").value : null,
          start_date: $("msg-start").value || null,
          end_date: $("msg-end").value || null,
          targets,
        };
      }

      // Rough browser version of display/messages/render.py fit_layout.
      function drawPreview(canvas) {
        const ctx = canvas.getContext("2d");
        const W = canvas.width, H = canvas.height, PAD = Math.min(W, H) >= 96 ? 2 : 1, MIN = 7;
        ctx.fillStyle = "#000";
        ctx.fillRect(0, 0, W, H);
        if (PAD === 2) { ctx.strokeStyle = "#202020"; ctx.strokeRect(0.5, 0.5, W - 1, H - 1); }
        const lines = draftLines.filter(l => l.text.trim());
        if (!lines.length) return;
        const font = px => `bold ${px}px "DejaVu Sans", Verdana, sans-serif`;
        const wrap = (text, px) => {
          ctx.font = font(px);
          const rows = []; let cur = "";
          for (const word of text.split(/\s+/).filter(Boolean)) {
            const trial = cur ? cur + " " + word : word;
            if (ctx.measureText(trial).width <= W - 2 * PAD || !cur) cur = trial;
            else { rows.push(cur); cur = word; }
          }
          rows.push(cur);
          return rows;
        };
        const smallest = MIN / Math.min(...lines.map(l => SIZE_PX[l.size]));
        let scale = Math.min(W, H) / 192, layout, total;
        for (;;) {
          layout = lines.map(l => {
            const px = Math.max(MIN, Math.round(SIZE_PX[l.size] * scale));
            return { px, rows: wrap(l.text.trim(), px), color: toHex(l.color) };
          });
          const gap = Math.max(1, Math.round(3 * scale));
          total = layout.reduce((h, b) => h + b.rows.length * Math.round(b.px * 1.15), 0) + gap * (layout.length - 1);
          layout.gap = gap;
          if (total <= H - 2 * PAD || scale <= smallest) break;
          scale = Math.max(smallest, scale * 0.9);
        }
        let y = PAD + Math.max(0, (H - 2 * PAD - total) / 2);
        ctx.textBaseline = "top";
        ctx.textAlign = "center";
        layout.forEach((b, i) => {
          ctx.font = font(b.px);
          ctx.fillStyle = b.color;
          b.rows.forEach(r => { ctx.fillText(r, W / 2, y); y += Math.round(b.px * 1.15); });
          if (i < layout.length - 1) y += layout.gap;
        });
      }

      function drawPreviews() {
        ["msg-prev-big", "msg-prev-64", "msg-prev-48"].forEach(id => drawPreview($(id)));
      }

      $("msg-lines").addEventListener("input", e => {
        const t = e.target;
        if (t.dataset.lineText) draftLines[t.dataset.lineText].text = t.value;
        else if (t.dataset.lineColor) draftLines[t.dataset.lineColor].color = fromHex(t.value);
        else if (t.dataset.lineSize) draftLines[t.dataset.lineSize].size = t.value;
        drawPreviews();
      });
      $("msg-lines").addEventListener("change", e => {
        if (e.target.dataset.lineSize) { draftLines[e.target.dataset.lineSize].size = e.target.value; drawPreviews(); }
      });
      $("msg-line-count").addEventListener("change", renderLineInputs);
      $("msg-add").addEventListener("click", () => openEditor(-1));
      $("msg-cancel").addEventListener("click", closeEditor);

      $("msg-save").addEventListener("click", async () => {
        const msg = readEditor();
        const messages = state.messages.slice();
        if (editing >= 0) messages[editing] = msg; else messages.push(msg);
        if (await saveAll(messages, `Saved "${msg.name}"`)) closeEditor();
      });

      $("msg-show-now").addEventListener("click", async () => {
        try {
          await call("POST", "/api/messages/preview", { message: readEditor() });
          showToast("Showing now");
        } catch (err) { showToast(err.message); }
      });

      $("msg-sync").addEventListener("click", async () => {
        try {
          state = await call("POST", "/api/messages/sync");
          renderList();
          showToast("Re-sent to displays");
        } catch (err) { showToast(err.message); }
      });

      $("msg-list").addEventListener("click", async e => {
        const t = e.target.closest("button");
        if (!t) return;
        if (t.dataset.msgEdit) openEditor(parseInt(t.dataset.msgEdit, 10));
        else if (t.dataset.msgShow) {
          try {
            await call("POST", "/api/messages/preview", { message: state.messages[t.dataset.msgShow] });
            showToast("Showing now");
          } catch (err) { showToast(err.message); }
        } else if (t.dataset.msgDelete) {
          const m = state.messages[t.dataset.msgDelete];
          if (!confirm(`Delete "${m.name}"?`)) return;
          await saveAll(state.messages.filter(x => x !== m), `Deleted "${m.name}"`);
          closeEditor();
        }
      });

      $("msg-list").addEventListener("change", async e => {
        const i = e.target.dataset.msgToggle;
        if (i === undefined) return;
        const messages = state.messages.map((m, j) => j == i ? { ...m, enabled: e.target.checked } : m);
        await saveAll(messages, e.target.checked ? "Enabled" : "Disabled");
      });

      load();
      setInterval(() => { if (editing === null) load(); }, 15000);
    })();
"""
