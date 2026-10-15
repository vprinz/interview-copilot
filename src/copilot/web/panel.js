// Панель копайлота: раз в полсекунды берёт /state (поля — panel-state.schema.json) и раскладывает его
// по разметке panel.html. Раскладку по ширине окна делает panel.css, здесь — только данные.
"use strict";

const $ = id => document.getElementById(id);
const esc = text => String(text ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const mmss = s => String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
const post = path => fetch(path, { method: "POST" });
const ICON_FLAG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20z"></path><path d="M12 10v4"></path><path d="M12 17h.01"></path></svg>';
const SLOT_NAMES = { результат: "Результат", критерии: "Критерии", контекст: "Контекст", триггер: "Триггер",
                     выше: "Задача выше", эмоции: "Эмоции", частота: "Частота", важность: "Важность" };
const STATUS_DOT = { "слушаю": "", "думаю": "think", "ошибка": "error", "ответ не по формату": "error", "готовлюсь": "idle" };

const shown = {};
let G = null;  // статичное за звонок: GET /guide — название, часть, стоп-лист, названия блоков
const foldTouched = { "guide-fold": false, "stop-fold": false };  // интервьюер сам открыл или закрыл

// Меняет содержимое, только если оно другое; flash — подсветить изменение (кроме первого показа).
function put(id, html, flash = false) {
  if (shown[id] === html) return;
  const first = shown[id] === undefined;
  shown[id] = html;
  const node = $(id);
  node.innerHTML = html;
  if (flash && !first) {
    node.classList.remove("flash");
    void node.offsetWidth;
    node.classList.add("flash");
  }
}
const show = (id, on) => $(id).classList.toggle("hidden", !on);
const name = id => (G.names || {})[id] || "";

function renderHead(s) {
  const g = G;
  put("guide-title", esc(g.kind === "canon" ? "Блоки по канону" : g.title || "Копайлот"));
  const part = g.kind === "canon" ? "гайд под респондента не задан" : /^часть/i.test(g.part) ? g.part : "";
  put("guide-part", esc([part, `звонок на ${s.minutes} мин`].filter(Boolean).join(" · ")));
  put("clock", `${mmss(s.elapsed)} <small>/ ${s.minutes}</small>`);
  $("clock").classList.toggle("late", s.elapsed > s.minutes * 60);
}

function renderTimeline(s) {
  const t = s.timeline;
  put("timeline", t.items.map(item => {
    const cls = ["tl-item", item.sub ? "tl-sub" : "", `is-${item.state}`, item.plan ? "is-plan" : ""].join(" ");
    const mark = item.state === "cut" ? "резать" : item.must && item.state !== "done" ? "не резать" : "";
    const grow = item.sub ? "" : ` style="flex-grow: ${Math.max(2, item.minutes)}"`;
    return `<li class="${cls}"${grow} title="${esc(item.number + " " + item.title)}"><span class="tl-bar"></span>`
      + `<span class="tl-num">${esc(item.number || "·")}</span>`
      + `<span class="tl-name">${esc(item.title)}${item.star ? " ⭐" : ""}`
      + (mark ? `<span class="tl-mark">${mark}</span>` : "")
      + (item.plan ? `<span class="tl-plan-tag">по часам</span>` : "") + `</span>`
      + `<span class="tl-time">${esc(item.state === "current" && item.sub ? "сейчас" : item.time)}</span></li>`;
  }).join(""));
  const pace = t.behind > 0 ? `<span class="behind">отстаёшь на ${t.behind} мин</span>`
             : t.behind < 0 ? `<span class="ahead-of">опережаешь на ${-t.behind} мин</span>` : "";
  const parts = [];
  if (t.current) parts.push(`<span><strong>${esc(t.current)} ${esc(name(t.current))}</strong>${t.plan && t.plan !== t.current ? ` · по часам уже ${esc(t.plan)}` : ""}</span>`);
  else if (t.plan) parts.push(`<span>по часам: <strong>${esc(t.plan)} ${esc(name(t.plan))}</strong></span>`);
  if (pace) parts.push(pace);
  if (t.ahead.length) parts.push(`<span>не резать: ${esc(t.ahead.join(", "))}</span>`);
  if (t.cut.length) parts.push(`<span>резать: ${esc(t.cut.join(", "))}</span>`);
  if (!t.current && s.block) parts.push(`<span>${esc(s.block)}</span>`);
  put("tl-summary", parts.join(""));
  show("tl-behind", t.behind !== 0);
  put("tl-behind", t.behind > 0 ? `Отстаёшь на ${t.behind} мин: по часам уже блок ${esc(t.plan)}`
                 : t.behind < 0 ? `Опережаешь план на ${-t.behind} мин` : "");
}

function renderAsk(s) {
  const skipped = !!s.question && s.question === s.skipped;
  const label = s.topic_id ? `${s.topic_id} · ${name(s.topic_id)}` : s.topic;
  show("topic", !!label);
  put("topic", esc(label));
  put("fills", s.fills ? `добираем: <b>${esc(s.fills)}</b>` : "");
  put("ask-state", skipped ? "пропущен" : "");
  $("question").classList.toggle("none", !s.question);
  $("question").classList.toggle("is-skipped", skipped);
  $("ask").classList.toggle("is-skipped", skipped);
  put("question", esc(s.question || "Подсказка появится после первых реплик."), true);
  $("skip").disabled = !s.question || skipped;
  show("skipped", !!s.skipped && !skipped);
  put("skipped", `Пропущен: <s>${esc(s.skipped)}</s>`);
  put("canon", s.canon ? "Канон: " + esc(s.canon) : "");
}

function renderSide(s) {
  put("flags", s.flags.map(flag => `<p class="flag">${ICON_FLAG}${esc(flag)}</p>`).join(""), true);
  const [focus] = (s.focus || "").split(" | ");
  show("focus", !!focus);
  put("focus", `Фокус: <b>${esc(focus)}</b>`);
  $("focus").title = s.focus || "";
  put("tasks", s.tasks.length
    ? s.tasks.map((task, i) => i === s.dig
        ? `<li class="task is-dig"><span class="task-n">${i + 1}</span><span class="task-text">${esc(task)}</span><span class="task-why">копать: ${esc(s.why)}</span></li>`
        : `<li class="task"><span class="task-n">${i + 1}</span><span class="task-text">${esc(task)}</span></li>`).join("")
      + (s.dig === null ? `<li class="empty-note">задача для прокопки ещё не выбрана</li>` : "")
    : `<li class="empty-note">пока не названы</li>`, true);
  const above = s.slots.find(slot => slot.name === "выше");
  show("above", !!above && above.mark !== "✗" && !!above.text);
  put("above", `Задача выше: <b>${esc(above ? above.text : "")}</b>`);
  const chosen = s.dig !== null && s.dig < s.tasks.length;
  show("slots", chosen);
  show("slots-empty", !chosen);
  put("slots-title", chosen ? `Собрано по задаче ${s.dig + 1}` : "Собрано по задаче");
  put("slots", s.slots.map(slot => {
    const kind = slot.mark === "✓" ? "is-ok" : slot.mark === "≈" ? "is-vague" : "is-empty";
    const text = slot.mark === "✗" ? "" : `<span class="slot-text">${esc(slot.text || "есть")}</span>`;
    return `<div class="slot ${kind}"><span class="slot-name">${SLOT_NAMES[slot.name] || esc(slot.name)}${slot.mark === "≈" ? " ≈" : ""}</span>${text}</div>`;
  }).join(""));
}

function renderGuide(s) {
  const card = s.guide_block;
  show("guide-fold", !!card);
  if (card) {
    put("guide-fold-title", `Из гайда · ${esc(card.id)} ${esc(card.title)}`);
    put("guide-fold-body",
      card.questions.map(q => `<p class="gq">${q.label ? `<b>${esc(q.label)}</b> ` : ""}${esc(q.text)}`
        + q.alts.map(alt => `<small>иначе: ${esc(alt)}</small>`).join("") + `</p>`).join("")
      + card.checks.map(text => `<p>${esc(text)}</p>`).join("")
      + card.traps.map(text => `<p class="trap">${esc(text)}</p>`).join(""));
  }
  const stop = G.stop_list || [];
  show("stop-fold", stop.length > 0);
  put("stop-body", stop.map(row => `<div>${esc(row.pattern)}<span>${esc(row.why)}</span></div>`).join(""));
  // По ширине окна: справка по блоку открыта с 600 px, стоп-лист — с 1100. Если интервьюер сам
  // открыл или закрыл раздел, дальше решает он.
  const width = $("panel").clientWidth;
  if (!foldTouched["guide-fold"]) $("guide-fold").open = width >= 600;
  if (!foldTouched["stop-fold"]) $("stop-fold").open = width >= 1100;
}

function renderStatus(s) {
  const dot = STATUS_DOT[s.status] ?? "idle";
  for (const id of ["dot", "dot-head"]) $(id).className = "dot " + dot;
  let text = s.status + (s.note ? " — " + s.note : "");
  if (s.updated) text += ` · обновлено ${Math.max(0, Math.round(s.now - s.updated))} с назад`;
  if (s.status === "слушаю" && s.waiting) text += ` · следующее через ${s.next} с`;
  put("status", esc(text) + (s.errors.length ? ` · <span class="errors" title="${esc(s.errors.join("\n"))}">формат: ${s.errors.length}</span>` : ""));
  put("status-head", esc(text));
  put("heard", esc(s.heard));
  $("heard").title = s.heard;
  put("context", s.context ? `контекст сессии ${Math.round(s.context / 2000)}%` : "");
}

function render(s) {
  renderHead(s);
  renderTimeline(s);
  renderAsk(s);
  renderSide(s);
  renderGuide(s);
  renderStatus(s);
}

async function tick() {
  try {
    if (!G) G = await (await fetch("/guide")).json();
    render(await (await fetch("/state")).json());
  } catch (error) {
    put("status", "нет связи с копайлотом");
    for (const id of ["dot", "dot-head"]) $(id).className = "dot error";
  }
}

function skip() {
  if ($("skip").disabled) return;
  $("skip").disabled = true;
  $("question").classList.add("is-skipped");
  post("/skip");
}

// --- тема: как в системе ---
const dark = window.matchMedia("(prefers-color-scheme: dark)");
const applyTheme = () => $("panel").classList.toggle("theme-dark", dark.matches);
dark.addEventListener("change", applyTheme);
applyTheme();

// --- «поверх окон»: кнопка есть только в окне panel-window, в браузере её нет ---
const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.copilot;
window.copilotWindowChanged = pinned => $("pin").setAttribute("aria-pressed", String(pinned));
if (bridge) {
  show("pin", true);
  window.copilotWindowChanged(window.copilotWindow ? window.copilotWindow.pinned : true);
  $("pin").onclick = () => bridge.postMessage({ pinned: $("pin").getAttribute("aria-pressed") !== "true" });
}

for (const id of Object.keys(foldTouched)) {
  $(id).querySelector("summary").addEventListener("click", () => { foldTouched[id] = true; });
}
$("skip").onclick = skip;
$("refresh").onclick = () => post("/refresh");
$("clock").onclick = () => confirm("Начать отсчёт интервью заново с этого момента?") && post("/restart-clock");
document.addEventListener("keydown", event => {
  if (event.target.closest("input, textarea")) return;
  if (event.code === "Space") { event.preventDefault(); post("/refresh"); }
  if (event.code === "KeyS" && !event.metaKey && !event.ctrlKey) skip();
});
setInterval(tick, 500);
tick();
