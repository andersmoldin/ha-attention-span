// Lägga åt sidan i kortet: valen på Problem och Pågår, chipet «⚠ N åt sidan» och listan
// «Lagt åt sidan».
import { test } from "node:test";
import assert from "node:assert/strict";

import { fakeHass, held, icons, notice, renderCard, status, text } from "./fake-hass.mjs";

const NOW = Date.parse("2026-10-26T08:00:00Z");
const DORREN = status("binary_sensor.ytterdorr", "Öppen", 10);
const TVATTEN = status("sensor.tvattmaskin", "Kör", 25);

// Ritar kortet med låtsad klocka, now (NOW är 09:00 i hemmets tidszon, Europe/Stockholm).
function renderAt(t, hass, config, now = NOW) {
  // Ta bort förra testets kort med den riktiga klockan; en låtsad clearInterval stoppar inte
  // dess timer, och då avslutas inte testerna.
  document.body.replaceChildren();
  t.mock.timers.enable({ apis: ["Date", "setInterval"], now });
  return renderCard(hass, config);
}

// Knapparna i ett element, som text.
const buttons = (el) => [...el.querySelectorAll("button")].map(text);

// Trycker på knappen med texten i el.
function press(el, label) {
  const button = [...el.querySelectorAll("button")].find((b) => text(b) === label);
  assert.ok(button, `ingen knapp «${label}» bland ${JSON.stringify(buttons(el))}`);
  button.click();
}

test("Problem och Pågår har «Lägg åt sidan», som visar valen", (t) => {
  const root = renderAt(
    t,
    fakeHass({
      notices: [held("status_problem", 10), held("status_ongoing", 25)],
      values: [DORREN, TVATTEN],
    }),
  );

  for (const level of ["problem", "ongoing"]) {
    const el = root.querySelector(`.notice.${level}`);
    assert.deepEqual(buttons(el), ["Lägg åt sidan"]);
    press(el, "Lägg åt sidan");
    assert.deepEqual(buttons(el), [
      "Lägg åt sidan",
      "1 timme",
      "Idag kl. 13",
      "I morgon bitti",
      "Tills det är lagat",
    ]);
  }
});

test("ett val lägger notisen åt sidan för hela hushållet, till tiden i hemmets tidszon", (t) => {
  const choices = {
    "1 timme": { until: "2026-10-26T09:00:00.000Z" },
    "Idag kl. 13": { until: "2026-10-26T13:00:00" },
    "I morgon bitti": { until: "2026-10-27T07:00:00" },
    "Tills det är lagat": {},
  };
  for (const [label, data] of Object.entries(choices)) {
    const hass = fakeHass({ notices: [held("status_problem", 10)], values: [DORREN] });
    const el = renderAt(t, hass).querySelector(".notice.problem");
    press(el, "Lägg åt sidan");
    press(el, label);

    assert.deepEqual(hass.calls, [
      {
        domain: "attention_span",
        service: "snooze",
        data,
        target: { entity_id: "sensor.attention_span_ytterdorren" },
      },
    ]);
    // Valen fälls ihop igen.
    assert.deepEqual(buttons(el), ["Lägg åt sidan"]);
    t.mock.timers.reset();
  }
});

test("«Idag kl. N» är fyra timmar fram, uppåt till hel timme, och visas bara från 06:00 till 19:00", (t) => {
  // Klockslag i hemmets tidszon (UTC+1) och valen då, med vad «Idag kl. N» skickar.
  const cases = {
    "05:59": null,
    "06:00": ["Idag kl. 10", "2026-10-26T10:00:00"],
    "07:45": ["Idag kl. 12", "2026-10-26T12:00:00"],
    "08:00": ["Idag kl. 12", "2026-10-26T12:00:00"],
    "18:30": ["Idag kl. 23", "2026-10-26T23:00:00"],
    "18:59": ["Idag kl. 23", "2026-10-26T23:00:00"],
    "19:01": null,
    "23:00": null,
  };
  for (const [time, today] of Object.entries(cases)) {
    const hass = fakeHass({ notices: [held("status_problem", 10)], values: [DORREN] });
    const now = Date.parse(`2026-10-26T${time}:00+01:00`);
    const el = renderAt(t, hass, undefined, now).querySelector(".notice.problem");
    press(el, "Lägg åt sidan");

    assert.deepEqual(
      buttons(el).slice(1),
      ["1 timme", ...(today ? [today[0]] : []), "I morgon bitti", "Tills det är lagat"],
      time,
    );
    if (today) {
      press(el, today[0]);
      assert.deepEqual(hass.calls.map((call) => call.data), [{ until: today[1] }], time);
    }
    t.mock.timers.reset();
  }
});

test("«Idag kl. N» skickar timmen som står på knappen, också när klockan har gått sedan den ritades", (t) => {
  const hass = fakeHass({ notices: [held("status_problem", 10)], values: [DORREN] });
  const el = renderAt(t, hass, undefined, Date.parse("2026-10-26T08:00:50+01:00")).querySelector(
    ".notice.problem",
  );
  press(el, "Lägg åt sidan");
  // 08:01:35, när nu plus fyra timmar har gått förbi 12:00, men kortet har inte ritats om.
  t.mock.timers.tick(45_000);

  press(el, "Idag kl. 12");

  assert.deepEqual(hass.calls.map((call) => call.data), [{ until: "2026-10-26T12:00:00" }]);
});

// Dörren ligger åt sidan till 21:00 i hemmets tidszon och har varit ett Problem sedan 08:40.
const SNOOZED = notice("status_problem_snoozed", {
  attributes: {
    friendly_name: "Ytterdörren",
    entities: ["binary_sensor.ytterdorr"],
    since: "2026-10-26T07:40:00+00:00",
    snoozed_until: "2026-10-26T20:00:00+00:00",
  },
});
SNOOZED.entity_id = "sensor.attention_span_ytterdorren";

// Namnen på notiserna som ritas som egna kort.
const shownNotices = (root) => [...root.querySelectorAll(".notice b")].map(text);

test("en notis som ligger åt sidan ritas inte, och kortet är lugnt när inget annat behöver hushållet", (t) => {
  const root = renderAt(t, fakeHass({ notices: [SNOOZED, notice("value_glance")], values: [DORREN] }));

  assert.deepEqual(shownNotices(root), []);
  assert.equal(text(root.querySelector(".calm")), "Allt är lugnt hemma.");
});

test("chipet «⚠ N åt sidan» står först och öppnar listan «Lagt åt sidan»", (t) => {
  const tvatten = held("status_ongoing", 25, {
    attributes: { snoozed: true, snoozed_until: null, since: "2026-10-25T18:10:00+00:00" },
  });
  const root = renderAt(
    t,
    fakeHass({ notices: [tvatten, SNOOZED, held("status_alarm", 3 * 60)], values: [DORREN, TVATTEN] }),
  );

  const chip = root.querySelector(".stack > .chips");
  assert.equal(root.querySelector(".stack").firstElementChild, chip);
  assert.equal(text(chip), "⚠ 2 åt sidan");
  assert.equal(root.querySelector(".snoozed"), null);

  press(chip, "⚠ 2 åt sidan");

  const list = root.querySelector(".snoozed");
  assert.equal(text(list.querySelector("h2")), "Lagt åt sidan");
  assert.deepEqual([...list.querySelectorAll(".entry")].map(text), [
    "Ytterdörren Åt sidan till 21:00 · sedan 08:40Ta fram igen",
    "Tvätten Åt sidan tills det är lagat · sedan i går 19:10Ta fram igen",
  ]);
  assert.equal(list.querySelector(".entry ha-icon").getAttribute("icon"), "mdi:robot-vacuum");

  press(chip, "⚠ 2 åt sidan");
  assert.equal(root.querySelector(".snoozed"), null);
});

test("utan något åt sidan finns inget chip", (t) => {
  const root = renderAt(t, fakeHass({ notices: [held("status_problem", 10)], values: [DORREN] }));

  assert.equal(root.querySelector(".chips"), null);
});

test("«Ta fram igen» tar fram notisen för hela hushållet, och en tom lista säger att inget ligger åt sidan", (t) => {
  const hass = fakeHass({ notices: [SNOOZED], values: [DORREN] });
  const root = renderAt(t, hass);
  press(root.querySelector(".chips"), "⚠ 1 åt sidan");

  press(root.querySelector(".snoozed"), "Ta fram igen");

  assert.deepEqual(hass.calls, [
    {
      domain: "attention_span",
      service: "unsnooze",
      data: {},
      target: { entity_id: "sensor.attention_span_ytterdorren" },
    },
  ]);

  // HA skickar notisens nya tillstånd: den ligger inte åt sidan längre.
  const back = notice("status_problem_snoozed", {
    attributes: { ...SNOOZED.attributes, snoozed: false, snoozed_until: null },
  });
  back.entity_id = SNOOZED.entity_id;
  root.host.hass = fakeHass({ notices: [back], values: [DORREN] });

  assert.deepEqual(shownNotices(root), ["Ytterdörren"]);
  assert.equal(root.querySelector(".snoozed .entry"), null);
  assert.equal(text(root.querySelector(".snoozed .empty")), "Inget ligger åt sidan.");
  // Chipet står kvar medan listan är öppen, så att den går att stänga.
  press(root.querySelector(".chips"), "⚠ 0 åt sidan");
  assert.equal(root.querySelector(".chips"), null);
});

test("ett tryck på en post i listan öppnar HA:s detaljdialog för entiteten notisen visar", (t) => {
  const root = renderAt(t, fakeHass({ notices: [SNOOZED], values: [DORREN] }));
  const dialogs = [];
  root.host.addEventListener("hass-more-info", (event) => dialogs.push(event.detail.entityId));
  press(root.querySelector(".chips"), "⚠ 1 åt sidan");

  root.querySelector(".snoozed .entry .head").click();

  assert.deepEqual(dialogs, ["binary_sensor.ytterdorr"]);
});

test("valen för åt sidan ställs in i kortets konfiguration", (t) => {
  const hass = fakeHass({ notices: [held("status_problem", 10)], values: [DORREN] });
  const root = renderAt(t, hass, {
    snooze_options: [
      { name: "En kvart", for: { minutes: 15 } },
      { for: { hours: 2 } },
      { name: "Lunch", at: "12:30" },
      { at: "06:00" },
      { ahead: { hours: 1, minutes: 30 }, latest: "21:00" },
      { ahead: { hours: 2 }, latest: "08:00" },
      { ahead: { hours: 3 }, earliest: "09:30" },
      { name: "Tills vidare" },
    ],
  });
  const el = root.querySelector(".notice.problem");
  press(el, "Lägg åt sidan");

  // Klockan är 09:00, efter 08:00 och före 09:30, så de två sista valen med ahead visas inte.
  assert.deepEqual(buttons(el).slice(1), [
    "En kvart",
    "2 tim",
    "Lunch",
    "06:00",
    "Idag kl. 11",
    "Tills vidare",
  ]);
  for (const label of buttons(el).slice(1)) {
    press(el, label);
    press(el, "Lägg åt sidan");
  }
  assert.deepEqual(
    hass.calls.map((call) => call.data),
    [
      { until: "2026-10-26T08:15:00.000Z" },
      { until: "2026-10-26T10:00:00.000Z" },
      { until: "2026-10-26T12:30:00" },
      // 06:00 har redan varit i dag.
      { until: "2026-10-27T06:00:00" },
      { until: "2026-10-26T11:00:00" },
      {},
    ],
  );
});

test("en ogiltig konfiguration av valen ger ett fel som HA visar i stället för kortet", () => {
  const card = document.createElement("attention-span-card");
  for (const [options, message] of [
    [[], /at least one choice/],
    ["1 timme", /at least one choice/],
    [[{ at: "25:00" }], /snooze_options\[0\]\.at/],
    [[{ for: "en timme" }], /snooze_options\[0\]\.for must be a duration/],
    [[{ for: "1:00" }], /snooze_options\[0\]\.for must be a duration/],
    [[{ for: { hours: 0 } }], /snooze_options\[0\]\.for/],
    [[{ for: { weeks: 1 } }], /snooze_options\[0\]\.for/],
    [[{ for: { hours: 1 }, at: "21:00" }], /only one of for, at and ahead/],
    [[{ at: "07:00", ahead: { hours: 4 } }], /only one of for, at and ahead/],
    [[{ ahead: "4:00" }], /snooze_options\[0\]\.ahead must be a duration/],
    [[{ ahead: { hours: 4 }, latest: "19" }], /snooze_options\[0\]\.latest/],
    [[{ for: { hours: 1 }, latest: "19:00" }], /latest needs ahead/],
    [[{ ahead: { hours: 4 }, earliest: "6:00" }], /snooze_options\[0\]\.earliest/],
    [[{ at: "07:00", earliest: "06:00" }], /earliest needs ahead/],
    [[{ ahead: { hours: 4 }, earliest: "19:00", latest: "06:00" }], /earliest .* before latest/],
    [[{ name: "Snart", ahead: { hours: 4 } }], /named after the hour/],
    [[{ name: "Ikväll", until: "21:00" }], /unknown keys: until/],
    [[{ name: "" }], /\.name/],
  ]) {
    assert.throws(
      () => card.setConfig({ type: "custom:attention-span-card", snooze_options: options }),
      message,
      JSON.stringify(options),
    );
  }
});

test("åt sidan följer användarens språk", (t) => {
  const root = renderAt(
    t,
    fakeHass({ notices: [SNOOZED, held("status_ongoing", 25)], values: [DORREN, TVATTEN], language: "en" }),
  );
  const el = root.querySelector(".notice.ongoing");
  press(el, "Snooze");
  assert.deepEqual(buttons(el), [
    "Snooze",
    "1 hour",
    "Today 13:00",
    "Tomorrow morning",
    "Until fixed",
  ]);

  press(root.querySelector(".chips"), "⚠ 1 snoozed");

  const list = root.querySelector(".snoozed");
  assert.equal(text(list.querySelector("h2")), "Snoozed");
  assert.equal(text(list.querySelector(".entry")), "Ytterdörren Snoozed until 9:00 PM · since 8:40 AMBring back");
});

test("en notis som läggs åt sidan och tas fram igen uppdateras på plats, utan att något byggs om", (t) => {
  const tvatten = held("status_ongoing", 25);
  const problem = notice("status_problem_snoozed", {
    attributes: { ...SNOOZED.attributes, snoozed: false, snoozed_until: null },
  });
  problem.entity_id = SNOOZED.entity_id;
  const root = renderAt(t, fakeHass({ notices: [problem, tvatten], values: [DORREN, TVATTEN] }));
  const [dorren, ongoing] = root.querySelectorAll(".notice");
  let loaded = icons.loaded;

  root.host.hass = fakeHass({ notices: [SNOOZED, tvatten], values: [DORREN, TVATTEN] });
  assert.deepEqual([...root.querySelectorAll(".notice")], [ongoing]);
  assert.equal(icons.loaded, loaded, "en ikon laddades igen");
  press(root.querySelector(".chips"), "⚠ 1 åt sidan");
  const entry = root.querySelector(".snoozed .entry");
  // Posten i listan laddar sin ikon en gång, när den ritas första gången.
  loaded = icons.loaded;

  // En ny hass med samma läge, och med en ny tid till, behåller posten.
  const later = notice("status_problem_snoozed", {
    attributes: { ...SNOOZED.attributes, snoozed_until: "2026-10-27T06:00:00+00:00" },
  });
  later.entity_id = SNOOZED.entity_id;
  root.host.hass = fakeHass({ notices: [later, tvatten], values: [DORREN, TVATTEN] });
  assert.equal(root.querySelector(".snoozed .entry"), entry, "posten byggdes om");
  assert.match(text(entry), /till i morgon 07:00/);

  root.host.hass = fakeHass({ notices: [problem, tvatten], values: [DORREN, TVATTEN] });

  const [back, still] = root.querySelectorAll(".notice");
  assert.equal(back, dorren, "notisen byggdes om när den togs fram");
  assert.equal(still, ongoing, "en annan notis byggdes om");
  assert.equal(icons.loaded, loaded, "en ikon laddades igen");
});

test("valen följer en ändrad konfiguration och ett ändrat språk, också på en notis som redan visas", (t) => {
  const root = renderAt(t, fakeHass({ notices: [held("status_problem", 10)], values: [DORREN] }));
  const el = root.querySelector(".notice.problem");

  root.host.setConfig({ type: "custom:attention-span-card", snooze_options: [{ name: "Lunch", at: "12:30" }] });
  press(el, "Lägg åt sidan");
  assert.equal(root.querySelector(".notice.problem"), el);
  assert.deepEqual(buttons(el), ["Lägg åt sidan", "Lunch"]);

  root.host.setConfig({ type: "custom:attention-span-card" });
  root.host.hass = fakeHass({ notices: [held("status_problem", 10)], values: [DORREN], language: "en" });
  assert.deepEqual(buttons(el), ["Snooze", "1 hour", "Today 13:00", "Tomorrow morning", "Until fixed"]);
});
