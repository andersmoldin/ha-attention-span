// Testseam 2: kortet ritas i en DOM från happy-dom och matas med ett fejkat hass-objekt
// byggt av de delade fixturerna (tests/fixtures/contract-v1.json), samma exempel som
// backend-testerna förväntar sig som utdata.
import { readFileSync } from "node:fs";

import { Window } from "happy-dom";

const window = new Window();
for (const name of ["window", "document", "customElements", "HTMLElement"]) {
  globalThis[name] = name === "window" ? window : window[name];
}

await import("../../custom_components/attention_span/www/attention-span-card.js");

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

// Som HA: tillstånden, entitetsregistret och formatEntityState. AttentionSpans
// entiteter hör till plattformen attention_span, övriga till platform.
export function fakeHass({ notices = [], values = [], language = "sv", platform = "template" } = {}) {
  const states = {};
  const entities = {};
  for (const stateObj of notices) {
    states[stateObj.entity_id] = stateObj;
    entities[stateObj.entity_id] = { entity_id: stateObj.entity_id, platform: "attention_span" };
  }
  for (const stateObj of values) {
    states[stateObj.entity_id] = stateObj;
    entities[stateObj.entity_id] = { entity_id: stateObj.entity_id, platform };
  }
  return {
    states,
    entities,
    language,
    locale: { language },
    formatEntityState: (stateObj) => {
      const unit = stateObj.attributes.unit_of_measurement;
      return unit ? `${stateObj.state} ${unit}` : stateObj.state;
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
