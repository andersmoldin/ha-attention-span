import { test } from "node:test";
import assert from "node:assert/strict";

import {
  cardHelpers,
  entity,
  fakeHass,
  held,
  notice,
  renderCard,
  settled,
  ago,
  status,
  text,
  value,
} from "./fake-hass.mjs";

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

test("notiser av en Typ som kortet inte känner till ritas inte som Värde", () => {
  const root = renderCard(
    fakeHass({ notices: [notice("value_glance", { attributes: { type: "graph" } })], values: [BILEN] }),
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
        held("status_ongoing", 25),
        held("status_problem", 10),
        held("status_alarm", 3 * 60),
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
  const dorren = held("status_problem", 10, { state: "ongoing" });
  const root = renderCard(
    fakeHass({ notices: [held("status_ongoing", 25), dorren], values: [DORREN, TVATTEN] }),
  );

  assert.deepEqual([...root.querySelectorAll(".notice.ongoing")].map(text), [
    "Ytterdörren Öppen i 10 min",
    "Tvätten Kör i 25 min",
  ]);
});

test("Larm ritas stort och rött ur temat", () => {
  const root = renderCard(
    fakeHass({
      notices: [
        notice("status_alarm"),
        notice("status_problem"),
        notice("status_ongoing", { state: "glance" }),
      ],
      values: [FINDUS, DORREN, TVATTEN],
    }),
  );
  root.host.style.setProperty("--error-color", "rgb(219, 68, 55)");

  const [alarm, problem, glance] = [".notice.alarm b", ".notice.problem b", ".glance b"].map(
    (selector) => window.getComputedStyle(root.querySelector(selector)),
  );
  assert.equal(alarm.color, "rgb(219, 68, 55)");
  for (const other of [problem, glance]) {
    assert.ok(parseFloat(alarm.fontSize) > parseFloat(other.fontSize));
  }
});

test("en Status-notis på Blick visar namnet först, sedan tillståndet och hur länge", () => {
  const root = renderCard(
    fakeHass({ notices: [held("status_problem", 10, { state: "glance" })], values: [DORREN] }),
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
        notices: [held("status_problem", minutes)],
        values: [status("binary_sensor.ytterdorr", "Öppen", minutes)],
      }),
    );

    assert.equal(text(root.querySelector(".notice")), `Ytterdörren Öppen i ${shown}`);
  }
});

test("Status räknar hur länge från när regeln såg tillståndet börja, också efter en omstart", () => {
  // HA har startat om för 1 min sedan och gett dörren ett nytt last_changed.
  const root = renderCard(
    fakeHass({
      notices: [notice("status_problem", { attributes: { state_since: ago(3 * 60) } })],
      values: [status("binary_sensor.ytterdorr", "Öppen", 1)],
    }),
  );

  assert.equal(text(root.querySelector(".notice")), "Ytterdörren Öppen i 3 tim");
});

test("Status följer användarens språk", () => {
  const root = renderCard(
    fakeHass({
      notices: [held("status_problem", 10)],
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
  const root = renderCard(
    fakeHass({
      notices: [held("status_problem", 10)],
      values: [status("binary_sensor.ytterdorr", "Öppen", 10)],
    }),
  );
  assert.equal(text(root.querySelector(".notice")), "Ytterdörren Öppen i 10 min");

  t.mock.timers.tick(60_000);

  assert.equal(text(root.querySelector(".notice")), "Ytterdörren Öppen i 11 min");
});

const NOW = Date.parse("2026-10-26T08:00:00Z");

// Stapelns fyllnad i procent, eller null utan stapel.
function bar(el) {
  const fill = el.querySelector(".bar i");
  return fill ? parseFloat(fill.style.width) : null;
}

// Diskmaskinen fick nivån Pågår för 20 min sedan.
const DISKEN = notice("progress_ongoing", { attributes: { since: "2026-10-26T07:40:00+00:00" } });

test("Förlopp med en sluttid visar tid kvar och en stapel från när notisen fick sin nivå", (t) => {
  t.mock.timers.enable({ apis: ["Date"], now: NOW });
  // Sluttiden är om 40 min och notisen fick sin nivå för 20 min sedan: en tredjedel har gått.
  // Maskinen justerade sluttiden för 1 min sedan, vilket inte ska nollställa stapeln.
  const klar = entity(
    "sensor.diskmaskin_klar",
    "2026-10-26T08:40:00+00:00",
    { device_class: "timestamp" },
    1,
  );
  const root = renderCard(fakeHass({ notices: [DISKEN], values: [klar] }));

  const card = root.querySelector(".notice.ongoing");
  assert.equal(text(card), "Diskmaskinen 40 min kvar");
  assert.equal(Math.round(bar(card)), 33);
});

test("Förlopp i procent visar procenten och en lika lång stapel, även som Blick-rad", () => {
  const skrivaren = entity("sensor.diskmaskin_klar", "62", { unit_of_measurement: "%" });
  const root = renderCard(
    fakeHass({ notices: [notice("progress_ongoing", { state: "glance" })], values: [skrivaren] }),
  );

  const row = root.querySelector(".glance");
  assert.equal(text(row), "Diskmaskinen 62 %");
  assert.equal(bar(row), 62);
});

test("Förlopp med en timer visar tid kvar, även när timern är pausad", (t) => {
  t.mock.timers.enable({ apis: ["Date"], now: NOW });
  const active = entity("timer.agg", "active", {
    duration: "0:08:00",
    remaining: "0:08:00",
    finishes_at: "2026-10-26T08:06:00+00:00",
  });
  const paused = entity("timer.agg", "paused", { duration: "0:08:00", remaining: "0:02:00" });

  for (const [timer, shown, done] of [
    [active, "6 min kvar", 25],
    [paused, "2 min kvar", 75],
  ]) {
    const root = renderCard(
      fakeHass({
        notices: [notice("progress_ongoing", { state: "problem", attributes: { entities: ["timer.agg"] } })],
        values: [timer],
      }),
    );

    const card = root.querySelector(".notice.problem");
    assert.equal(text(card), `Diskmaskinen ${shown}`, timer.state);
    assert.equal(bar(card), done, timer.state);
  }
});

test("Förlopp utan tid kvar eller procent visar tillståndet utan stapel", () => {
  const idle = entity("timer.agg", "idle", { duration: "0:08:00", remaining: "0:08:00" });
  const root = renderCard(
    fakeHass({
      notices: [notice("progress_ongoing", { attributes: { entities: ["timer.agg"] } })],
      values: [idle],
    }),
  );

  const card = root.querySelector(".notice.ongoing");
  assert.equal(text(card), "Diskmaskinen idle");
  assert.equal(bar(card), null);
});

test("Kommande visar de närmaste tillfällena med dag och tid, även som Tyst-rad", (t) => {
  // Måndag 26 oktober 09:00 i Stockholm.
  t.mock.timers.enable({ apis: ["Date"], now: NOW });
  const root = renderCard(fakeHass({ notices: [notice("upcoming_quiet")] }));

  assert.equal(text(root.querySelector(".quiet")), "Sophämtning i morgon 06:30 Restavfall · tors Matavfall");
});

test("Kommande säger nu, om en stund, i dag eller datum beroende på hur nära det är", (t) => {
  t.mock.timers.enable({ apis: ["Date"], now: NOW });
  const at = (start, end = null) => ({ start, end, summary: null });
  const occurrences = [
    at("2026-10-26T08:30:00+01:00", "2026-10-26T09:30:00+01:00"),
    at("2026-10-26T09:07:00+01:00"),
    at("2026-10-26T14:00:00+01:00"),
    at("2026-10-26", "2026-10-27"),
    at("2026-11-03T06:30:00+01:00"),
  ];
  const root = renderCard(
    fakeHass({ notices: [notice("upcoming_quiet", { state: "ongoing", attributes: { occurrences } })] }),
  );

  assert.equal(
    text(root.querySelector(".notice.ongoing")),
    "Sophämtning nu · om 7 min · i dag 14:00 · i dag · 3 nov. 06:30",
  );
});

test("Kommande följer användarens språk", (t) => {
  t.mock.timers.enable({ apis: ["Date"], now: NOW });
  const root = renderCard(fakeHass({ notices: [notice("upcoming_quiet")], language: "en" }));

  assert.equal(text(root.querySelector(".quiet")), "Sophämtning tomorrow 6:30 AM Restavfall · Thu Matavfall");
});

test("Kommande utan tillfällen visar ett streck", () => {
  const root = renderCard(
    fakeHass({ notices: [notice("upcoming_quiet", { attributes: { occurrences: [] } })] }),
  );

  assert.equal(text(root.querySelector(".quiet")), "Sophämtning –");
});

const WEATHER_CARD = { type: "weather-forecast", entity: "weather.hemma", show_forecast: false };

test("Eget kort ritar kortkonfigurationen med HA:s kort och ger det hass, även som Blick-rad", async () => {
  const hass = fakeHass({ notices: [notice("custom_glance")] });
  const root = renderCard(hass);
  await settled();

  const embedded = root.querySelector(".glance hui-test-card");
  assert.deepEqual(embedded.config, WEATHER_CARD);
  assert.equal(embedded.hass, hass);
});

test("Eget kort på Larm visar namnet över kortet", async () => {
  const root = renderCard(fakeHass({ notices: [notice("custom_glance", { state: "alarm" })] }));
  await settled();

  const card = root.querySelector(".notice.alarm");
  assert.equal(text(card.querySelector("b")), "Vädret");
  assert.deepEqual(card.querySelector("hui-test-card").config, WEATHER_CARD);
});

test("det inbäddade kortet återanvänds och får varje ny hass, även när inget annat ändras", async () => {
  const hass = fakeHass({ notices: [notice("custom_glance")] });
  const root = renderCard(hass);
  await settled();
  const embedded = root.querySelector("hui-test-card");
  const created = cardHelpers.created;

  const next = { ...hass, states: { ...hass.states, "weather.hemma": { state: "rainy", attributes: {} } } };
  root.host.hass = next;

  assert.equal(root.querySelector("hui-test-card"), embedded);
  assert.equal(embedded.hass, next);
  assert.equal(cardHelpers.created, created);
});

// Fönstren och gruppen de ingår i, med tillstånd som HA redan har formaterat.
const WINDOWS = [
  status("binary_sensor.kok", "Öppen", 5),
  status("binary_sensor.sovrum", "Öppen", 12),
  status("binary_sensor.badrum", "Öppen", 30),
  status("binary_sensor.hall", "Stängd", 60),
  status("binary_sensor.vardagsrum", "Stängd", 60),
];
const fonster = (state = "Öppen") =>
  entity("binary_sensor.fonster", state, { entity_id: WINDOWS.map((w) => w.entity_id) }, 30);

test("Status för en grupp visar hur många av medlemmarna som har gruppens tillstånd", () => {
  const root = renderCard(
    fakeHass({ notices: [notice("status_group_ongoing")], values: WINDOWS, groups: [fonster()] }),
  );

  assert.equal(text(root.querySelector(".notice.ongoing")), "Fönster Öppen · 3 av 5");
});

test("Status för en grupp på Tyst och på engelska", () => {
  const root = renderCard(
    fakeHass({
      notices: [notice("status_group_ongoing", { state: "quiet" })],
      values: WINDOWS,
      groups: [fonster()],
      language: "en",
    }),
  );

  assert.equal(text(root.querySelector(".quiet")), "Fönster Öppen · 3 of 5");
});

test("en gammal grupp i domänen group räknas också", () => {
  const group = { ...fonster("Stängd"), entity_id: "group.fonster" };
  const root = renderCard(
    fakeHass({
      notices: [notice("status_group_ongoing", { attributes: { entities: ["group.fonster"] } })],
      values: [...WINDOWS, group],
    }),
  );

  assert.equal(text(root.querySelector(".notice")), "Fönster Stängd · 2 av 5");
});

test("en entitet med listan entity_id som inte är en grupp visar tillståndet och hur länge", () => {
  const scene = entity("scene.kvall", "Aktiverad", { entity_id: ["light.kok"] }, 10);
  const root = renderCard(
    fakeHass({
      notices: [held("status_group_ongoing", 10, { attributes: { entities: ["scene.kvall"] } })],
      values: [scene],
    }),
  );

  assert.equal(text(root.querySelector(".notice")), "Fönster Aktiverad i 10 min");
});

test("tryck eller Enter på Status för en grupp öppnar HA:s detaljdialog för gruppen", () => {
  const root = renderCard(
    fakeHass({
      notices: [notice("status_group_ongoing", { state: "glance" })],
      values: WINDOWS,
      groups: [fonster()],
    }),
  );
  const opened = [];
  root.host.addEventListener("hass-more-info", (event) => opened.push(event.detail.entityId));

  const row = root.querySelector(".glance");
  row.click();
  row.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));

  assert.deepEqual(opened, ["binary_sensor.fonster", "binary_sensor.fonster"]);
  assert.equal(row.getAttribute("role"), "button");
});

test("varje Typ kan visas på varje nivå", async () => {
  const shown = [
    ["value_glance", BILEN],
    ["status_problem", DORREN],
    ["progress_ongoing", entity("sensor.diskmaskin_klar", "62", { unit_of_measurement: "%" })],
    ["upcoming_quiet"],
    ["custom_glance"],
  ];
  for (const level of ["alarm", "problem", "ongoing", "glance", "quiet"]) {
    for (const [name, value] of shown) {
      const root = renderCard(
        fakeHass({ notices: [notice(name, { state: level })], values: value ? [value] : [] }),
      );
      await settled();

      const drawn = root.querySelector(`.${level}`);
      assert.ok(drawn, `${name} på ${level}`);
      const content = name === "custom_glance" ? drawn.querySelector("hui-test-card") : text(drawn);
      assert.ok(content, `${name} på ${level}`);
    }
  }
});

test("Förlopp med en sensor för tid kvar visar tid kvar och en stapel från när notisen fick sin nivå", (t) => {
  t.mock.timers.enable({ apis: ["Date"], now: NOW });
  // Notisen fick sin nivå för 20 min sedan.
  for (const [state, unit, left, done] of [
    ["40", "min", "40 min", 33],
    ["2400", "s", "40 min", 33],
    ["0.5", "h", "30 min", 40],
  ]) {
    const kvar = entity("sensor.diskmaskin_klar", state, { device_class: "duration", unit_of_measurement: unit });
    const root = renderCard(fakeHass({ notices: [DISKEN], values: [kvar] }));

    const card = root.querySelector(".notice.ongoing");
    assert.equal(text(card), `Diskmaskinen ${left} kvar`, unit);
    assert.equal(Math.round(bar(card)), done, unit);
  }
});

test("en entitet med gruppmedlemmar i group_entities räknas som en grupp", () => {
  const lampor = entity(
    "light.kok",
    "on",
    { group_entities: ["light.kok_1", "light.kok_2", "light.kok_3"] },
    10,
  );
  const root = renderCard(
    fakeHass({
      notices: [notice("status_group_ongoing", { attributes: { entities: ["light.kok"] } })],
      values: [lampor, entity("light.kok_1", "on"), entity("light.kok_2", "off"), entity("light.kok_3", "on")],
    }),
  );

  assert.equal(text(root.querySelector(".notice")), "Fönster on · 2 av 3");
});
