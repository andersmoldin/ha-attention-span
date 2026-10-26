// AttentionSpan-kortet: visar AttentionSpan-entiteterna efter nivå.
// All räknelogik och kortets texter finns i card-model.js.

// Samma version som kortet laddades med, så att en uppdatering inte blandar
// nytt kort med en gammal cachad card-model.js.
const versionQuery = new URL(import.meta.url).search;
const { NEEDS_ATTENTION, cardModel, strings } = await import(`./card-model.js${versionQuery}`);

// Färger och typsnitt kommer från HA:s tema; storlekar och layout är fasta,
// så att ett tema ändrar utseendet men inte var saker hamnar.
const STYLE = `
  .stack { display: flex; flex-direction: column; gap: 8px; }
  ha-card { padding: 12px 16px; color: var(--primary-text-color); }
  .calm { display: flex; align-items: center; gap: 10px; padding: 6px 0;
    font-size: 13.5px; color: var(--secondary-text-color); }
  .calm i { flex: none; width: 9px; height: 9px; border-radius: 50%; background: var(--success-color); }
  .notice { position: relative; overflow: hidden; display: flex; align-items: center; gap: 12px;
    padding: 14px 16px; }
  .notice::before { content: ""; position: absolute; top: 0; right: 0; bottom: 0; left: 0;
    opacity: 0.1; pointer-events: none; }
  .notice ha-icon { position: relative; flex: none; display: flex; align-items: center;
    justify-content: center; width: 42px; height: 42px; --mdc-icon-size: 24px; }
  .notice span { position: relative; display: flex; flex-direction: column; min-width: 0; }
  .notice b { font-size: 16px; font-weight: 500; }
  .notice small { font-size: 13px; color: var(--secondary-text-color); }
  .alarm { padding: 18px 16px; border-width: 2px; border-style: solid;
    border-color: var(--error-color); }
  .alarm::before { background: var(--error-color); opacity: 0.12; }
  .alarm ha-icon { width: 54px; height: 54px; border-radius: 18px; --mdc-icon-size: 32px;
    color: var(--text-primary-color); background: var(--error-color); }
  .alarm b { font-size: 20px; color: var(--error-color); }
  .alarm small { color: var(--primary-text-color); }
  .problem { border-width: 1px; border-style: solid; border-color: var(--warning-color); }
  .problem::before { background: var(--warning-color); }
  .problem ha-icon { color: var(--warning-color); }
  .ongoing ha-icon { color: var(--info-color); }
  .glance, .quiet { display: flex; align-items: center; min-width: 0; }
  .glance { gap: 12px; min-height: 44px; font-size: 16px; }
  .glance ha-icon { --mdc-icon-size: 24px; color: var(--state-icon-color); }
  .glance b { font-weight: 500; white-space: nowrap; }
  .glance small { font-size: 13px; color: var(--secondary-text-color); }
  .quiet { gap: 10px; padding: 5px 0; font-size: 13px; color: var(--secondary-text-color); }
  .quiet ha-icon { --mdc-icon-size: 18px; }
  .quiet b { font-weight: 500; color: var(--primary-text-color); white-space: nowrap; }
  .quiet small { font-size: inherit; }
  small { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
`;

// Hur ofta kortet ritas om för att «hur länge» ska stämma.
const TICK_MS = 60_000;

function calmElement(text) {
  const el = document.createElement("div");
  el.className = "calm";
  el.append(document.createElement("i"), text);
  return el;
}

function iconElement(row) {
  const icon = document.createElement("ha-icon");
  if (row.icon) icon.setAttribute("icon", row.icon);
  return icon;
}

function textElement(tag, text) {
  const el = document.createElement(tag);
  el.textContent = text;
  return el;
}

// Larm, Problem och Pågår: ett eget kort per notis, med namnet över det Typen visar.
function noticeElement(row, level) {
  const el = document.createElement("ha-card");
  el.className = `notice ${level}`;
  const body = document.createElement("span");
  body.append(textElement("b", row.name), " ", textElement("small", row.text));
  el.append(iconElement(row), body);
  return el;
}

// Blick och Tyst: en rad. Ett Värde står före namnet, annars står namnet först.
function rowElement(row, level) {
  const el = document.createElement("div");
  el.className = level;
  const [first, second] = row.type === "value" ? [row.text, row.name] : [row.name, row.text];
  el.append(iconElement(row), textElement("b", first), " ", textElement("small", second));
  return el;
}

class AttentionSpanCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = config;
    this._drawn = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    this._tick = setInterval(() => this._render(), TICK_MS);
    this._render();
  }

  disconnectedCallback() {
    clearInterval(this._tick);
  }

  _render() {
    if (!this._config || !this._hass) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><div class="stack"></div>`;
    }
    const model = cardModel(this._hass, Date.now());
    const calmText = strings(this._hass).calm;
    // HA skickar hass vid varje tillståndsändring i hela systemet. Rita bara om när det
    // kortet visar har ändrats, så att korten och ikonerna inte byggs om i onödan.
    const drawn = JSON.stringify([model, calmText]);
    if (drawn === this._drawn) return;
    this._drawn = drawn;
    const rows = [
      ...(model.calm ? [calmElement(calmText)] : []),
      ...model.glance.map((row) => rowElement(row, "glance")),
      ...model.quiet.map((row) => rowElement(row, "quiet")),
    ];
    const rowsCard = document.createElement("ha-card");
    rowsCard.append(...rows);
    this.shadowRoot
      .querySelector(".stack")
      .replaceChildren(
        ...NEEDS_ATTENTION.flatMap((level) =>
          model[level].map((row) => noticeElement(row, level)),
        ),
        ...(rows.length ? [rowsCard] : []),
      );
  }
}

if (!customElements.get("attention-span-card")) {
  customElements.define("attention-span-card", AttentionSpanCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "attention-span-card",
    name: "AttentionSpan",
    description: "Shows only what matters now.",
  });
}
