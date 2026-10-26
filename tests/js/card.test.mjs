import { test } from "node:test";
import assert from "node:assert/strict";

import { fakeHass, notice, renderCard, text, value } from "./fake-hass.mjs";

const BILEN = value("sensor.bilen_batteri", "52", "%");
const ELPRIS = value("sensor.elpris", "42", "öre/kWh");

test("en Blick-notis av typen Värde ritas som en större rad med ikon, värde och namn", () => {
  const root = renderCard(fakeHass({ notices: [notice("value_glance")], values: [BILEN] }));

  const [row] = root.querySelectorAll(".glance");
  assert.equal(text(row), "52 % Bilen");
  assert.equal(row.querySelector("ha-icon").getAttribute("icon"), "mdi:car");
});

test("Tyst-notiser ritas som mindre rader längst ner, under Blick", () => {
  const root = renderCard(
    fakeHass({ notices: [notice("value_quiet"), notice("value_glance")], values: [BILEN, ELPRIS] }),
  );

  const rows = [...root.querySelectorAll(".glance, .quiet")];
  assert.deepEqual(
    rows.map((row) => [row.className, text(row)]),
    [
      ["glance", "52 % Bilen"],
      ["quiet", "42 öre/kWh Elpris"],
    ],
  );
  assert.equal(rows.at(-1).querySelector("ha-icon").getAttribute("icon"), "mdi:flash");
});

test("en dold notis ritas inte", () => {
  const root = renderCard(
    fakeHass({
      notices: [notice("value_glance", { state: "hidden" }), notice("value_quiet")],
      values: [BILEN, ELPRIS],
    }),
  );

  assert.deepEqual([...root.querySelectorAll(".glance, .quiet")].map(text), ["42 öre/kWh Elpris"]);
});

test("entiteter från andra integrationer ritas inte, även med samma attribut", () => {
  const lookalike = { ...notice("value_glance"), entity_id: "sensor.annan" };
  const root = renderCard(fakeHass({ values: [lookalike, BILEN] }));

  assert.equal(root.querySelectorAll(".glance, .quiet").length, 0);
});

test("utan notiser visas ett lugnt tomt läge", () => {
  const root = renderCard(fakeHass({ values: [BILEN] }));

  assert.equal(text(root.querySelector(".calm")), "Allt är lugnt hemma.");
  assert.equal(root.querySelectorAll(".glance, .quiet").length, 0);
});

test("det lugna läget står över Blick och Tyst när inget behöver hushållet", () => {
  const root = renderCard(
    fakeHass({ notices: [notice("value_glance"), notice("value_quiet")], values: [BILEN, ELPRIS] }),
  );

  const parts = [...root.querySelectorAll(".calm, .glance, .quiet")].map((el) => el.className);
  assert.deepEqual(parts, ["calm", "glance", "quiet"]);
});

test("kortet säger inte att allt är lugnt när en notis behöver hushållet", () => {
  for (const level of ["alarm", "problem", "ongoing"]) {
    const root = renderCard(
      fakeHass({ notices: [notice("value_glance", { state: level })], values: [BILEN] }),
    );

    assert.equal(root.querySelector(".calm"), null, level);
  }
});

test("det lugna läget följer användarens språk", () => {
  const root = renderCard(fakeHass({ language: "en" }));

  assert.equal(text(root.querySelector(".calm")), "All is calm at home.");
});

test("inom en nivå kommer notiserna i regelns ordning", () => {
  const inne = notice("value_glance", {
    attributes: { friendly_name: "Inne", priority: 3, entities: ["sensor.inne"] },
  });
  inne.entity_id = "sensor.attention_span_inne";
  const root = renderCard(
    fakeHass({
      notices: [inne, notice("value_glance")],
      values: [BILEN, value("sensor.inne", "21.4", "°C")],
    }),
  );

  assert.deepEqual([...root.querySelectorAll(".glance")].map(text), ["52 % Bilen", "21.4 °C Inne"]);
});

test("en notis vars entitet saknas visar ett streck i stället för värdet", () => {
  const root = renderCard(fakeHass({ notices: [notice("value_glance")] }));

  assert.equal(text(root.querySelector(".glance")), "– Bilen");
});

test("en notis i ett annat dataformat än version 1 ritas inte", () => {
  const root = renderCard(
    fakeHass({ notices: [notice("value_glance", { attributes: { contract: 2 } })], values: [BILEN] }),
  );

  assert.equal(root.querySelectorAll(".glance, .quiet").length, 0);
});

test("kortet ritas i ha-card och tar färger och typsnitt bara från temat", () => {
  const root = renderCard(fakeHass({ notices: [notice("value_glance")], values: [BILEN] }));

  assert.ok(root.querySelector("ha-card .glance"));
  // Reservvärdet i var(--x, reserv) gäller bara när temat saknar variabeln.
  const style = root.querySelector("style").textContent.replace(/var\(--[\w-]+,[^()]*\)/g, "var()");
  assert.doesNotMatch(style, /#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(|(?<![\w-])(white|black)(?![\w-])/i);
  assert.doesNotMatch(style, /font-family\s*:(?!\s*var\()/);
  assert.match(style, /var\(--primary-text-color/);
  assert.match(style, /var\(--secondary-text-color/);
});

test("kortet finns i kortväljaren och kan läggas till utan inställningar", () => {
  const entry = window.customCards.find((card) => card.type === "attention-span-card");
  assert.equal(entry.name, "AttentionSpan");

  const Card = customElements.get("attention-span-card");
  const root = renderCard(fakeHass(), Card.getStubConfig());

  assert.ok(root.querySelector(".calm"));
});

test("kortet ritas om när det som visas ändras, inte när andra entiteter ändras", () => {
  const hass = fakeHass({ notices: [notice("value_glance")], values: [BILEN] });
  const root = renderCard(hass);
  const card = root.host;
  const row = root.querySelector(".glance");

  card.hass = { ...hass, states: { ...hass.states, "light.kok": { state: "on", attributes: {} } } };
  assert.ok(root.querySelector(".glance") === row, "raden byggdes om");

  const states = { ...hass.states, "sensor.bilen_batteri": value("sensor.bilen_batteri", "53", "%") };
  card.hass = { ...hass, states };
  assert.equal(text(root.querySelector(".glance")), "53 % Bilen");
});

test("notiser av en Typ som kortet ännu inte kan rita ritas inte som Värde", () => {
  const root = renderCard(
    fakeHass({ notices: [notice("value_glance", { attributes: { type: "status" } })], values: [BILEN] }),
  );

  assert.equal(root.querySelectorAll(".glance, .quiet").length, 0);
});
