// Testseam 2: kortet ritas i en DOM från happy-dom och matas med ett fejkat hass-objekt
// byggt av de delade fixturerna (tests/fixtures/contract-v1.json), samma exempel som
// backend-testerna förväntar sig som utdata.
import { readFileSync } from "node:fs";
import { after } from "node:test";

import { Window } from "happy-dom";

const window = new Window();
for (const name of ["window", "document", "customElements", "HTMLElement", "CustomEvent"]) {
  globalThis[name] = name === "window" ? window : window[name];
}

await import("../../custom_components/attention_span/www/attention-span-card.js");

// Ett kort i dokumentet ritar om sig varje minut. Ta bort det sista, så att testerna kan avslutas.
after(() => document.body.replaceChildren());

const examples = JSON.parse(
  readFileSync(new URL("../fixtures/contract-v1.json", import.meta.url), "utf8"),
);

// Ett exempel i dataformat version 1, med valfria ändringar av tillstånd och attribut.
export function notice(name, { state, attributes = {} } = {}) {
  const example = structuredClone(examples[name]);
  return {
    ...example,
    state: state ?? example.state,
    attributes: { ...example.attributes, ...attributes },
  };
}

// Entiteten som en Rule av typen Värde visar.
export function value(entityId, state, unit) {
  return { entity_id: entityId, state, attributes: unit ? { unit_of_measurement: unit } : {} };
}

// Tiden för minutes minuter sedan, som HA skriver tider i attribut.
export function ago(minutes) {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

// En notis av typen Status vars visade tillstånd har gällt i minutes minuter enligt regeln.
export function held(name, minutes, { state, attributes = {} } = {}) {
  return notice(name, { state, attributes: { state_since: ago(minutes), ...attributes } });
}

// Entiteten som en Rule av typen Status visar: ett tillstånd som HA redan har formaterat
// och som har gällt i minutes minuter.
export function status(entityId, state, minutes) {
  const changed = new Date(Date.now() - minutes * 60_000).toISOString();
  return { entity_id: entityId, state, attributes: {}, last_changed: changed };
}

// Som HA: tillstånden, entitetsregistret, formatEntityState och callService, som sparar
// tjänsteanropen i calls som { domain, service, data, target }. AttentionSpans
// entiteter hör till plattformen attention_span, groups till grupphjälparna (plattformen
// group) och övriga till en annan integration.
export function fakeHass({ notices = [], values = [], groups = [], language = "sv" } = {}) {
  const states = {};
  const entities = {};
  const calls = [];
  for (const stateObj of notices) {
    states[stateObj.entity_id] = stateObj;
    entities[stateObj.entity_id] = { entity_id: stateObj.entity_id, platform: "attention_span" };
  }
  for (const stateObj of values) {
    states[stateObj.entity_id] = stateObj;
    entities[stateObj.entity_id] = { entity_id: stateObj.entity_id, platform: "template" };
  }
  for (const stateObj of groups) {
    states[stateObj.entity_id] = stateObj;
    entities[stateObj.entity_id] = { entity_id: stateObj.entity_id, platform: "group" };
  }
  return {
    states,
    entities,
    language,
    // Tider visas i serverns tidszon, som i HA:s profilinställning «Serverns tidszon».
    locale: { language, time_zone: "server" },
    config: { time_zone: "Europe/Stockholm" },
    formatEntityState: (stateObj) => {
      const unit = stateObj.attributes.unit_of_measurement;
      return unit ? `${stateObj.state} ${unit}` : stateObj.state;
    },
    calls,
    callService: async (domain, service, data, target) => {
      calls.push({ domain, service, data, target });
    },
  };
}

// Ritar kortet med hass och returnerar dess shadow root.
export function renderCard(hass, config = {}) {
  const card = document.createElement("attention-span-card");
  document.body.replaceChildren(card);
  card.setConfig({ type: "custom:attention-span-card", ...config });
  card.hass = hass;
  return card.shadowRoot;
}

// Den synliga texten i ett element, med blanktecken hopslagna.
export function text(el) {
  return el.textContent.replace(/\s+/g, " ").trim();
}

// En entitet med attribut vars tillstånd har gällt i minutes minuter.
export function entity(entityId, state, attributes = {}, minutes = 0) {
  const changed = new Date(Date.now() - minutes * 60_000).toISOString();
  return { entity_id: entityId, state, attributes, last_changed: changed };
}

// Som HA:s loadCardHelpers: createCardElement ger ett kortelement med konfigurationen.
// created räknar de kort som har skapats och connected gångerna ett kort kopplades in i
// dokumentet; ett iframe- eller kamerakort laddas om varje gång det kopplas in igen.
export const cardHelpers = { created: 0, connected: 0 };
customElements.define(
  "hui-test-card",
  class extends HTMLElement {
    connectedCallback() {
      cardHelpers.connected += 1;
    }
  },
);
window.loadCardHelpers = async () => ({
  createCardElement: (config) => {
    cardHelpers.created += 1;
    const el = document.createElement("hui-test-card");
    el.config = config;
    return el;
  },
});

// Som HA:s ha-icon: ett nytt element eller en ny ikon laddar ikonen, och en ikonuppsättning
// som hämtar en svg per ikon gör då en ny hämtning. loaded räknar laddningarna.
export const icons = { loaded: 0 };
customElements.define(
  "ha-icon",
  class extends HTMLElement {
    static observedAttributes = ["icon"];

    attributeChangedCallback(_name, old, icon) {
      if (icon !== old) icons.loaded += 1;
    }
  },
);

// Väntar tills kortet har laddat det som laddas i bakgrunden, till exempel loadCardHelpers.
export function settled() {
  return new Promise((resolve) => setImmediate(resolve));
}
