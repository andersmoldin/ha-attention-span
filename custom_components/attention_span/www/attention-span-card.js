// AttentionSpan-kortet: visar AttentionSpan-entiteterna efter nivå.
// All räknelogik finns i card-model.js.

// Samma version som kortet laddades med, så att en uppdatering inte blandar
// nytt kort med en gammal cachad card-model.js.
const version = new URL(import.meta.url).search;
const { cardModel } = await import(`./card-model.js${version}`);

const STRINGS = {
  en: { calm: "All is calm at home." },
  sv: { calm: "Allt är lugnt hemma." },
};

function strings(hass) {
  return STRINGS[hass.locale?.language ?? hass.language] ?? STRINGS.en;
}

// Färger och typsnitt kommer från HA:s tema; storlekar och layout är fasta,
// så att ett tema ändrar utseendet men inte var saker hamnar.
const STYLE = `
  ha-card { padding: 12px 16px; color: var(--primary-text-color); }
  .calm { display: flex; align-items: center; gap: 10px; padding: 6px 0;
    font-size: 13.5px; color: var(--secondary-text-color); }
  .calm i { flex: none; width: 9px; height: 9px; border-radius: 50%; background: var(--success-color); }
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

function calmElement(text) {
  const el = document.createElement("div");
  el.className = "calm";
  el.append(document.createElement("i"), text);
  return el;
}

function rowElement(row, level) {
  const el = document.createElement("div");
  el.className = level;
  const icon = document.createElement("ha-icon");
  if (row.icon) icon.setAttribute("icon", row.icon);
  const value = document.createElement("b");
  value.textContent = row.value;
  const name = document.createElement("small");
  name.textContent = row.name;
  el.append(icon, value, " ", name);
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

  _render() {
    if (!this._config || !this._hass) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card></ha-card>`;
    }
    const model = cardModel(this._hass);
    const calmText = strings(this._hass).calm;
    // HA skickar hass vid varje tillståndsändring i hela systemet. Rita bara om när det
    // kortet visar har ändrats, så att raderna och ikonerna inte byggs om i onödan.
    const drawn = JSON.stringify([model, calmText]);
    if (drawn === this._drawn) return;
    this._drawn = drawn;
    this.shadowRoot
      .querySelector("ha-card")
      .replaceChildren(
        ...(model.calm ? [calmElement(calmText)] : []),
        ...model.glance.map((row) => rowElement(row, "glance")),
        ...model.quiet.map((row) => rowElement(row, "quiet")),
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
