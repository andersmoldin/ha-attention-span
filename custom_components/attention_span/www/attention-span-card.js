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
  .bar { position: relative; height: 6px; border-radius: 3px; overflow: hidden;
    background: var(--divider-color); }
  .bar i { position: absolute; top: 0; bottom: 0; left: 0; border-radius: 3px;
    background: var(--info-color); }
  .alarm .bar i { background: var(--error-color); }
  .problem .bar i { background: var(--warning-color); }
  .notice .bar { margin-top: 8px; }
  .glance .bar, .quiet .bar { flex: 1 1 48px; min-width: 32px; }
  .notice span { flex: 1; }
  .notice.custom { flex-direction: column; align-items: stretch; }
  .custom .head { display: flex; align-items: center; gap: 12px; }
  .glance.custom, .quiet.custom { display: block; }
  [role="button"] { cursor: pointer; }
  /* Det inbäddade kortet ligger i notisen: utan egen ram, skugga och bakgrund. */
  .custom { --ha-card-border-width: 0; --ha-card-box-shadow: none;
    --ha-card-background: transparent; }
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

// Stapeln för Förlopp, eller inget när notisen inte har någon.
function barElements(row) {
  if (row.done === null) return [];
  const el = document.createElement("div");
  el.className = "bar";
  const fill = document.createElement("i");
  fill.style.width = `${row.done * 100}%`;
  el.append(fill);
  return [el];
}

// En notis som visar mer i HA:s detaljdialog: öppnas med tryck, Enter eller mellanslag.
function moreInfo(el, row) {
  if (!row.moreInfo) return el;
  el.setAttribute("role", "button");
  el.tabIndex = 0;
  const open = () =>
    el.dispatchEvent(
      new CustomEvent("hass-more-info", {
        detail: { entityId: row.moreInfo },
        bubbles: true,
        composed: true,
      }),
    );
  el.addEventListener("click", open);
  el.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    open();
  });
  return el;
}

// Larm, Problem och Pågår: ett eget kort per notis, med namnet över det Typen visar.
function noticeElement(row, level) {
  const el = document.createElement("ha-card");
  el.className = `notice ${level}`;
  const body = document.createElement("span");
  body.append(textElement("b", row.name), " ", textElement("small", row.text), ...barElements(row));
  el.append(iconElement(row), body);
  return moreInfo(el, row);
}

// Eget kort på Larm, Problem och Pågår: ikonen och namnet över det inbäddade kortet.
function customNoticeElement(row, level, embedded) {
  const el = document.createElement("ha-card");
  el.className = `notice ${level} custom`;
  const head = document.createElement("div");
  head.className = "head";
  head.append(iconElement(row), textElement("b", row.name));
  el.append(head, ...embedded);
  return el;
}

// Eget kort på Blick och Tyst: det inbäddade kortet som en rad.
function customRowElement(level, embedded) {
  const el = document.createElement("div");
  el.className = `${level} custom`;
  el.append(...embedded);
  return el;
}

// Blick och Tyst: en rad. Ett Värde står före namnet, annars står namnet först.
function rowElement(row, level) {
  const el = document.createElement("div");
  el.className = level;
  const [first, second] = row.type === "value" ? [row.text, row.name] : [row.name, row.text];
  el.append(
    iconElement(row),
    textElement("b", first),
    " ",
    textElement("small", second),
    ...barElements(row),
  );
  return moreInfo(el, row);
}

class AttentionSpanCard extends HTMLElement {
  // De inbäddade korten för Eget kort, per notis: konfigurationen och kortelementet.
  _cards = new Map();

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
    // De inbäddade korten visar egna entiteter och behöver varje ny hass ändå.
    for (const { el } of this._cards.values()) el.hass = this._hass;
    const drawn = JSON.stringify([model, calmText]);
    if (drawn === this._drawn) return;
    this._drawn = drawn;
    const shown = Object.values(model).flatMap((rows) => (Array.isArray(rows) ? rows : []));
    this._keepCards(shown);
    const row = (row, level) =>
      row.type === "custom" ? customRowElement(level, this._embedded(row)) : rowElement(row, level);
    const notice = (row, level) =>
      row.type === "custom"
        ? customNoticeElement(row, level, this._embedded(row))
        : noticeElement(row, level);
    const rows = [
      ...(model.calm ? [calmElement(calmText)] : []),
      ...model.glance.map((r) => row(r, "glance")),
      ...model.quiet.map((r) => row(r, "quiet")),
    ];
    const rowsCard = document.createElement("ha-card");
    rowsCard.append(...rows);
    this.shadowRoot
      .querySelector(".stack")
      .replaceChildren(
        ...NEEDS_ATTENTION.flatMap((level) => model[level].map((r) => notice(r, level))),
        ...(rows.length ? [rowsCard] : []),
      );
  }
}

// Glöm de inbäddade korten för notiser som inte visas längre, och ladda HA:s verktyg för
// att skapa kort första gången ett Eget kort ska visas.
AttentionSpanCard.prototype._keepCards = function keepCards(shown) {
  const ids = new Set(shown.filter((row) => row.type === "custom").map((row) => row.id));
  for (const id of this._cards.keys()) if (!ids.has(id)) this._cards.delete(id);
  if (ids.size && !this._helpers && !this._loadingHelpers && window.loadCardHelpers) {
    this._loadingHelpers = window.loadCardHelpers().then((helpers) => {
      this._helpers = helpers;
      this._drawn = null;
      this._render();
    });
  }
};

// Det inbäddade kortet för ett Eget kort, återanvänt så länge konfigurationen är densamma.
// Inget förrän HA:s verktyg för att skapa kort har laddats.
AttentionSpanCard.prototype._embedded = function embedded(row) {
  if (!this._helpers) return [];
  const config = JSON.stringify(row.card);
  let card = this._cards.get(row.id);
  if (card?.config !== config) {
    card = { config, el: this._helpers.createCardElement(row.card) };
    this._cards.set(row.id, card);
  }
  card.el.hass = this._hass;
  return [card.el];
};

if (!customElements.get("attention-span-card")) {
  customElements.define("attention-span-card", AttentionSpanCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "attention-span-card",
    name: "AttentionSpan",
    description: "Shows only what matters now.",
  });
}
