import { test } from "node:test";
import assert from "node:assert/strict";

import { fakeHass, notice, renderCard, status, text, value } from "./fake-hass.mjs";

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

// Egenskaper som bär färg eller typsnitt. Kortskrivna egenskaper som border och font
// delas upp av CSSOM, så deras färg och typsnitt hamnar här.
const THEMED = new Set([
  "background",
  "background-image",
  "box-shadow",
  "text-shadow",
  "fill",
  "stroke",
  "font-family",
]);

test("kortet ritas i ha-card och tar färger och typsnitt bara från temat", () => {
  const root = renderCard(fakeHass({ notices: [notice("value_glance")], values: [BILEN] }));

  assert.ok(root.querySelector("ha-card .glance"));
  const style = root.querySelector("style");
  // happy-dom slänger tyst deklarationer vars värde den inte förstår, till exempel
  // oklch(). Varje deklaration måste överleva tolkningen för att kontrollen nedan ska se den.
  const written = style.textContent
    .split("}")
    .flatMap((rule) => rule.split("{")[1]?.split(";") ?? [])
    .map((declaration) => declaration.trim())
    .filter(Boolean);
  const dropped = written.filter((declaration) => {
    const probe = document.createElement("div");
    probe.style.cssText = declaration;
    return probe.style.length === 0;
  });
  assert.deepEqual(dropped, []);
  const declarations = [...style.sheet.cssRules].flatMap((rule) =>
    Array.from(rule.style, (property) => [property, rule.style.getPropertyValue(property)]),
  );
  const themed = declarations.filter(([property]) => property.endsWith("color") || THEMED.has(property));
  const fixed = themed.filter(([, val]) => val !== "inherit" && !/^var\(--[\w-]+\)$/.test(val));
  assert.deepEqual(fixed, []);
  const values = themed.map(([, val]) => val);
  assert.ok(values.includes("var(--primary-text-color)"));
  assert.ok(values.includes("var(--secondary-text-color)"));
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
    fakeHass({ notices: [notice("value_glance", { attributes: { type: "progress" } })], values: [BILEN] }),
  );

  assert.equal(root.querySelectorAll(".glance, .quiet").length, 0);
});

const FINDUS = status("vacuum.findus", "Ej tillgänglig", 3 * 60);
const DORREN = status("binary_sensor.ytterdorr", "Öppen", 10);
const TVATTEN = status("sensor.tvattmaskin", "Kör", 25);

test("Larm, Problem och Pågår ritas som egna kort i den ordningen, över Blick", () => {
  const root = renderCard(
    fakeHass({
      notices: [
        notice("value_glance"),
        notice("status_ongoing"),
        notice("status_problem"),
        notice("status_alarm"),
      ],
      values: [BILEN, FINDUS, DORREN, TVATTEN],
    }),
  );

  const parts = [...root.querySelectorAll(".notice, .glance")];
  assert.deepEqual(
    parts.map((el) => [el.className, text(el)]),
    [
      ["notice alarm", "Findus Ej tillgänglig i 3 tim"],
      ["notice problem", "Ytterdörren Öppen i 10 min"],
      ["notice ongoing", "Tvätten Kör i 25 min"],
      ["glance", "52 % Bilen"],
    ],
  );
  assert.ok(parts.slice(0, 3).every((el) => el.tagName === "HA-CARD"));
  assert.equal(parts[0].querySelector("ha-icon").getAttribute("icon"), "mdi:robot-vacuum");
});

test("varje notis på Pågår får ett eget kort", () => {
  const dorren = notice("status_problem", { state: "ongoing" });
  const root = renderCard(
    fakeHass({ notices: [notice("status_ongoing"), dorren], values: [DORREN, TVATTEN] }),
  );

  assert.deepEqual([...root.querySelectorAll(".notice.ongoing")].map(text), [
    "Ytterdörren Öppen i 10 min",
    "Tvätten Kör i 25 min",
  ]);
});

test("Larm ritas stort och rött ur temat", () => {
  const root = renderCard(fakeHass({ notices: [notice("status_alarm")], values: [FINDUS] }));

  const rules = [...root.querySelector("style").sheet.cssRules];
  const alarmName = rules.find((rule) => rule.selectorText === ".alarm b");
  assert.equal(alarmName.style.getPropertyValue("color"), "var(--error-color)");
  assert.ok(parseFloat(alarmName.style.getPropertyValue("font-size")) > 16);
});

test("en Status-notis på Blick visar namnet först, sedan tillståndet och hur länge", () => {
  const root = renderCard(
    fakeHass({ notices: [notice("status_problem", { state: "glance" })], values: [DORREN] }),
  );

  assert.equal(text(root.querySelector(".glance")), "Ytterdörren Öppen i 10 min");
});

test("hur länge räknas i minuter, timmar eller dagar", () => {
  for (const [minutes, shown] of [
    [0, "0 min"],
    [59, "59 min"],
    [60, "1 tim"],
    [47 * 60, "47 tim"],
    [48 * 60, "2 d"],
  ]) {
    const root = renderCard(
      fakeHass({
        notices: [notice("status_problem")],
        values: [status("binary_sensor.ytterdorr", "Öppen", minutes)],
      }),
    );

    assert.equal(text(root.querySelector(".notice")), `Ytterdörren Öppen i ${shown}`);
  }
});

test("Status följer användarens språk", () => {
  const root = renderCard(
    fakeHass({
      notices: [notice("status_problem")],
      values: [status("binary_sensor.ytterdorr", "Open", 10)],
      language: "en",
    }),
  );

  assert.equal(text(root.querySelector(".notice")), "Ytterdörren Open for 10 min");
});

test("en notis av typen Värde på Problem visar namnet och värdet", () => {
  const root = renderCard(
    fakeHass({ notices: [notice("value_glance", { state: "problem" })], values: [BILEN] }),
  );

  assert.equal(text(root.querySelector(".notice.problem")), "Bilen 52 %");
});

test("hur länge räknas upp medan kortet visas, utan att något annat ändras", (t) => {
  // Ta bort förra testets kort med den riktiga klockan; en låtsad clearInterval stoppar inte
  // dess timer, och då avslutas inte testerna.
  document.body.replaceChildren();
  t.mock.timers.enable({ apis: ["Date", "setInterval"], now: Date.parse("2026-10-26T08:00:00Z") });
  const root = renderCard(fakeHass({ notices: [notice("status_problem")], values: [status("binary_sensor.ytterdorr", "Öppen", 10)] }));
  assert.equal(text(root.querySelector(".notice")), "Ytterdörren Öppen i 10 min");

  t.mock.timers.tick(60_000);

  assert.equal(text(root.querySelector(".notice")), "Ytterdörren Öppen i 11 min");
});
