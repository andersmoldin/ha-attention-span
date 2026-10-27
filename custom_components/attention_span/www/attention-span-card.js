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
  .notice { position: relative; overflow: hidden; display: flex; flex-wrap: wrap;
    align-items: center; gap: 12px; padding: 14px 16px; }
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
  /* Tryckytan: ikonen och texterna. Knapparna ligger bredvid, inte i den. */
  .head { display: flex; flex: 1; align-items: center; gap: inherit; min-width: 0; }
  .notice.custom .head { flex: none; }
  .glance.custom, .quiet.custom { display: block; }
  [role="button"] { cursor: pointer; }
  .actions { position: relative; display: flex; flex-wrap: wrap; gap: 8px; }
  .actions:empty, .head small:empty { display: none; }
  .notice .actions { flex-basis: 100%; }
  .glance .actions, .quiet .actions { flex: none; margin-left: auto; }
  .actions button { height: 36px; padding: 0 14px; border-style: none; border-radius: 12px;
    font-family: inherit; font-size: 13.5px; font-weight: 500; cursor: pointer;
    color: var(--primary-text-color); background: var(--secondary-background-color); }
  .quiet .actions button { height: 28px; padding: 0 10px; font-size: 12.5px; }
  /* Det inbäddade kortet ligger i notisen: utan egen ram, skugga och bakgrund. */
  .custom { --ha-card-border-width: 0; --ha-card-box-shadow: none;
    --ha-card-background: transparent; }
`;

// Hur ofta kortet ritas om för att «hur länge» ska stämma.
const TICK_MS = 60_000;

// Kortet bygger varje del en gång och uppdaterar den sedan på plats. HA skickar hass vid varje
// tillståndsändring i hela systemet, och ett nytt ha-icon laddar sin ikon igen; med en
// ikonuppsättning som hämtar en svg per ikon blir det en hämtning och en tom ikon varje gång.

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

function setIcon(icon, name) {
  if (icon.getAttribute("icon") === name) return;
  if (name) icon.setAttribute("icon", name);
  else icon.removeAttribute("icon");
}

// Lägger children i parent i den ordningen och flyttar bara det som inte redan står rätt.
// Det som inte ska visas tas bort först, så att det som står kvar inte flyttas förbi det;
// en flytt kopplar bort och in elementet igen, och ett inbäddat kort kan då laddas om.
function placeChildren(parent, children) {
  const shown = new Set(children);
  for (const child of [...parent.children]) if (!shown.has(child)) child.remove();
  children.forEach((child, i) => {
    if (parent.children[i] !== child) parent.insertBefore(child, parent.children[i] ?? null);
  });
}

function calmElement() {
  const el = document.createElement("div");
  el.className = "calm";
  const text = document.createTextNode("");
  el.append(document.createElement("i"), text);
  return { el, update: (calmText) => setText(text, calmText) };
}

// Stapeln för Förlopp, sist i parent, eller ingen när notisen inte har någon.
function barPart(parent) {
  const el = document.createElement("div");
  el.className = "bar";
  const fill = document.createElement("i");
  el.append(fill);
  return (fraction) => {
    if (fraction === null) {
      el.remove();
      return;
    }
    const width = `${fraction * 100}%`;
    if (fill.style.width !== width) fill.style.width = width;
    if (el.parentNode !== parent) parent.append(el);
  };
}

// el visar mer i HA:s detaljdialog: öppnas med tryck, Enter eller mellanslag.
// Returnerar en funktion som sätter entiteten att visa.
function moreInfoPart(el) {
  let entityId = null;
  el.setAttribute("role", "button");
  el.tabIndex = 0;
  const open = () => {
    el.dispatchEvent(
      new CustomEvent("hass-more-info", {
        detail: { entityId },
        bubbles: true,
        composed: true,
      }),
    );
  };
  el.addEventListener("click", open);
  el.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    open();
  });
  return (moreInfo) => {
    entityId = moreInfo;
  };
}

// Åtgärderna som knappar. Ett tryck ber HA anropa tjänsten som en knapp i Lovelace gör
// (hass-action), så att HA:s egen dialog frågar med bekräftelsetexten först när den finns.
// Knapparna byggs bara om när åtgärderna ändras. Utan åtgärder är raden tom och dold.
function actionsPart() {
  const el = document.createElement("div");
  el.className = "actions";
  let drawn = null;
  const update = (entityId, actions) => {
    const key = JSON.stringify([entityId, actions]);
    if (key === drawn) return;
    drawn = key;
    el.replaceChildren(...actions.map((action) => actionButton(entityId, action)));
  };
  return { el, update };
}

function actionButton(entityId, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = action.name;
  const tapAction = {
    action: "perform-action",
    perform_action: action.action,
    target: action.target,
    data: action.data,
  };
  if (action.confirmation) tapAction.confirmation = { text: action.confirmation };
  button.addEventListener("click", () => {
    button.dispatchEvent(
      new CustomEvent("hass-action", {
        detail: { config: { entity: entityId, tap_action: tapAction }, action: "tap" },
        bubbles: true,
        composed: true,
      }),
    );
  });
  return button;
}

// Namnet och det Typen visar eller orsaken, med en stapel för Förlopp. first och second är
// texterna i ordning.
function textParts(parent) {
  const first = document.createElement("b");
  const second = document.createElement("small");
  parent.append(first, " ", second);
  const bar = barPart(parent);
  return (firstText, secondText, fraction) => {
    setText(first, firstText);
    setText(second, secondText);
    bar(fraction);
  };
}

// Tryckytan som öppnar detaljdialogen, med ikonen först.
function headElement() {
  const head = document.createElement("div");
  head.className = "head";
  const icon = document.createElement("ha-icon");
  head.append(icon);
  return { head, icon, moreInfo: moreInfoPart(head) };
}

// Larm, Problem och Pågår: ett eget kort per notis, med namnet över det Typen visar eller
// orsaken, och åtgärderna under.
function noticeElement(level) {
  const el = document.createElement("ha-card");
  el.className = `notice ${level}`;
  const { head, icon, moreInfo } = headElement();
  const body = document.createElement("span");
  head.append(body);
  const actions = actionsPart();
  el.append(head, actions.el);
  const texts = textParts(body);
  return {
    el,
    update: (row) => {
      setIcon(icon, row.icon);
      texts(row.name, row.text, row.fraction);
      moreInfo(row.moreInfo);
      actions.update(row.id, row.actions);
    },
  };
}

// Blick och Tyst: en rad med åtgärderna sist. Ett Värde utan orsak står före namnet, annars
// står namnet först.
function rowElement(level) {
  const el = document.createElement("div");
  el.className = level;
  const { head, icon, moreInfo } = headElement();
  const actions = actionsPart();
  el.append(head, actions.el);
  const texts = textParts(head);
  return {
    el,
    update: (row) => {
      setIcon(icon, row.icon);
      const [first, second] = row.valueFirst ? [row.text, row.name] : [row.name, row.text];
      texts(first, second, row.fraction);
      moreInfo(row.moreInfo);
      actions.update(row.id, row.actions);
    },
  };
}

// Det inbäddade kortet i parent före next, utbytt bara när det är ett annat kortelement.
function embeddedPart(parent, next) {
  let current = null;
  return (embedded) => {
    const [card = null] = embedded;
    if (card === current) return;
    current?.remove();
    if (card) parent.insertBefore(card, next);
    current = card;
  };
}

// Eget kort på Larm, Problem och Pågår: ikonen, namnet och orsaken över det inbäddade kortet,
// och åtgärderna under. Ett tryck på huvudet öppnar detaljdialogen; det inbäddade kortet
// hanterar sina egna tryck. embeddedFor ger det inbäddade kortet för en notis.
function customNoticeElement(level, embeddedFor) {
  const el = document.createElement("ha-card");
  el.className = `notice ${level} custom`;
  const { head, icon, moreInfo } = headElement();
  const name = document.createElement("b");
  const reason = document.createElement("small");
  head.append(name, reason);
  const actions = actionsPart();
  el.append(head, actions.el);
  const embedded = embeddedPart(el, actions.el);
  return {
    el,
    update: (row) => {
      setIcon(icon, row.icon);
      setText(name, row.name);
      setText(reason, row.text);
      embedded(embeddedFor(row));
      moreInfo(row.moreInfo);
      actions.update(row.id, row.actions);
    },
  };
}

// Eget kort på Blick och Tyst: det inbäddade kortet som en rad, med åtgärderna under.
function customRowElement(level, embeddedFor) {
  const el = document.createElement("div");
  el.className = `${level} custom`;
  const actions = actionsPart();
  el.append(actions.el);
  const embedded = embeddedPart(el, actions.el);
  return {
    el,
    update: (row) => {
      embedded(embeddedFor(row));
      actions.update(row.id, row.actions);
    },
  };
}

// Hur en notis byggs: som eget kort (notice) eller som rad (row), med ett inbäddat kort för
// Eget kort och annars med text.
const ELEMENTS = {
  notice: { custom: customNoticeElement, text: noticeElement },
  row: { custom: customRowElement, text: rowElement },
};

class AttentionSpanCard extends HTMLElement {
  // De inbäddade korten för Eget kort, per notis: konfigurationen och kortelementet.
  _cards = new Map();
  // De ritade notiserna, per nivå, Typ och entitet, som uppdateras på plats.
  _drawnNotices = new Map();

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
      this._calm = calmElement();
      this._rowsCard = document.createElement("ha-card");
    }
    const model = cardModel(this._hass, Date.now());
    const calmText = strings(this._hass).calm;
    // De inbäddade korten visar egna entiteter och behöver varje ny hass.
    for (const { el } of this._cards.values()) el.hass = this._hass;
    // Inget att göra när det kortet visar är detsamma som förra gången.
    const drawn = JSON.stringify([model, calmText]);
    if (drawn === this._drawn) return;
    this._drawn = drawn;
    const levels = [...NEEDS_ATTENTION, "glance", "quiet"];
    this._keepCards(levels.flatMap((level) => model[level]));
    const drawnNotices = new Map();
    const draw = (shape, row, level) => {
      const key = `${level} ${row.type} ${row.id}`;
      const notice =
        this._drawnNotices.get(key) ??
        ELEMENTS[shape][row.type === "custom" ? "custom" : "text"](level, (r) => this._embedded(r));
      notice.update(row);
      drawnNotices.set(key, notice);
      return notice.el;
    };
    this._calm.update(calmText);
    const rows = [
      ...(model.calm ? [this._calm.el] : []),
      ...["glance", "quiet"].flatMap((level) => model[level].map((row) => draw("row", row, level))),
    ];
    const notices = NEEDS_ATTENTION.flatMap((level) =>
      model[level].map((row) => draw("notice", row, level)),
    );
    this._drawnNotices = drawnNotices;
    placeChildren(this._rowsCard, rows);
    placeChildren(this.shadowRoot.querySelector(".stack"), [
      ...notices,
      ...(rows.length ? [this._rowsCard] : []),
    ]);
  }

  // Glöm de inbäddade korten för notiser som inte visas längre, och ladda HA:s verktyg för
  // att skapa kort första gången ett Eget kort ska visas.
  _keepCards(rows) {
    const ids = new Set(rows.filter((row) => row.type === "custom").map((row) => row.id));
    for (const id of this._cards.keys()) if (!ids.has(id)) this._cards.delete(id);
    if (ids.size && !this._helpers && !this._loadingHelpers && window.loadCardHelpers) {
      this._loadingHelpers = window.loadCardHelpers().then((helpers) => {
        this._helpers = helpers;
        this._drawn = null;
        this._render();
      });
    }
  }

  // Det inbäddade kortet för ett Eget kort, återanvänt så länge konfigurationen är densamma.
  // Inget förrän HA:s verktyg för att skapa kort har laddats.
  _embedded(row) {
    if (!this._helpers) return [];
    const config = JSON.stringify(row.card);
    let card = this._cards.get(row.id);
    if (card?.config !== config) {
      card = { config, el: this._helpers.createCardElement(row.card) };
      this._cards.set(row.id, card);
    }
    card.el.hass = this._hass;
    return [card.el];
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
