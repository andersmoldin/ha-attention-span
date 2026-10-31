// Räknar fram vad AttentionSpan-kortet ska visa ur hass. Ingen DOM här.

export const DOMAIN = "attention_span";
// Dataformatet kortet är byggt mot. Kortet laddas med integrationens version, så ett
// annat värde betyder att kort och integration inte hör ihop; sådana notiser läses inte.
const CONTRACT = 1;

// Nivåer som behöver hushållet och ritas som ett eget kort per notis. Så länge en notis
// har någon av dem är det inte lugnt, även när kortet inte kan rita notisens Typ.
export const NEEDS_ATTENTION = ["alarm", "problem", "ongoing"];

// Typer som kortet kan rita. Notiser av andra Typer ritas inte förrän kortet kan det.
const DRAWN_TYPES = ["value", "status", "progress", "upcoming", "custom"];

// Kortets egna texter, valda efter användarens språk (ADR 0001). status är Typen Status:
// tillståndet och hur länge det har gällt, och group hur många medlemmar i en grupp som har
// gruppens tillstånd. left är tid kvar för Typen Förlopp. now, soon,
// today och tomorrow säger när ett tillfälle för Typen Kommande är. moreAlarms och
// moreProblems står för Larmen och Problemen efter det första, med Larmens namn; Larmens
// stapel har ett brett plustecken (＋) som i specen, så att det syns på den röda stapeln.
// acknowledge är knappen som kvitterar ett Larm, och acknowledged och realarm texten på ett
// kvitterat Larm: utan och med hur länge det är kvar tills det larmar igen. snooze är knappen
// som visar valen för åt sidan, och choices valens standardnamn; today är namnet på ett val
// som räknas fram från nu, med timmen det ger i dag. snoozedChip är chipet för
// notiserna som ligger åt sidan, snoozedTitle rubriken på deras lista, snoozedUntil och
// snoozedUntilFixed texten på varje post i den, unsnooze knappen som tar fram en notis igen
// och nothingSnoozed texten när listan är tom. yesterday säger att en tid var i går.
const STRINGS = {
  en: {
    calm: "All is calm at home.",
    moreAlarms: (names) =>
      `＋${names.length} more ${names.length === 1 ? "alarm" : "alarms"}: ${names.join(", ")}`,
    moreProblems: (count) => `+${count} more ${count === 1 ? "problem" : "problems"}`,
    acknowledge: "Acknowledge",
    acknowledged: "Acknowledged",
    realarm: (duration) => `Acknowledged · alarms again in ${duration}`,
    snooze: "Snooze",
    choices: {
      hour: "1 hour",
      today: (hour) => `Today ${hour}:00`,
      morning: "Tomorrow morning",
      fixed: "Until fixed",
    },
    snoozedChip: (count) => `⚠ ${count} snoozed`,
    snoozedTitle: "Snoozed",
    snoozedUntil: (until, since) => `Snoozed until ${until} · since ${since}`,
    snoozedUntilFixed: (since) => `Snoozed until fixed · since ${since}`,
    unsnooze: "Bring back",
    nothingSnoozed: "Nothing is snoozed.",
    status: (state, duration) => `${state} for ${duration}`,
    group: (state, count, total) => `${state} · ${count} of ${total}`,
    left: (duration) => `${duration} left`,
    now: "now",
    soon: (duration) => `in ${duration}`,
    today: "today",
    tomorrow: "tomorrow",
    yesterday: "yesterday",
  },
  sv: {
    calm: "Allt är lugnt hemma.",
    moreAlarms: (names) => `＋${names.length} larm till: ${names.join(", ")}`,
    moreProblems: (count) => `+${count} problem till`,
    acknowledge: "Kvittera",
    acknowledged: "Kvitterad",
    realarm: (duration) => `Kvitterad · larmar igen om ${duration}`,
    snooze: "Lägg åt sidan",
    choices: {
      hour: "1 timme",
      today: (hour) => `Idag kl. ${hour}`,
      morning: "I morgon bitti",
      fixed: "Tills det är lagat",
    },
    snoozedChip: (count) => `⚠ ${count} åt sidan`,
    snoozedTitle: "Lagt åt sidan",
    snoozedUntil: (until, since) => `Åt sidan till ${until} · sedan ${since}`,
    snoozedUntilFixed: (since) => `Åt sidan tills det är lagat · sedan ${since}`,
    unsnooze: "Ta fram igen",
    nothingSnoozed: "Inget ligger åt sidan.",
    status: (state, duration) => `${state} i ${duration}`,
    group: (state, count, total) => `${state} · ${count} av ${total}`,
    left: (duration) => `${duration} kvar`,
    now: "nu",
    soon: (duration) => `om ${duration}`,
    today: "i dag",
    tomorrow: "i morgon",
    yesterday: "i går",
  },
};

function language(hass) {
  return hass.locale?.language ?? hass.language;
}

export function strings(hass) {
  return STRINGS[language(hass)] ?? STRINGS.en;
}

// Hur länge, i hela minuter under en timme, i timmar under två dygn och därefter i dygn.
// round avrundar till hela minuter: nedåt för hur länge något har gällt, uppåt för tid kvar.
function duration(ms, lang, round = Math.floor) {
  const minutes = Math.max(0, round(ms / 60_000));
  const [amount, unit] =
    minutes < 60
      ? [minutes, "minute"]
      : minutes < 48 * 60
        ? [Math.floor(minutes / 60), "hour"]
        : [Math.floor(minutes / (24 * 60)), "day"];
  return new Intl.NumberFormat(lang, { style: "unit", unit, unitDisplay: "short" }).format(amount);
}

const clamp = (fraction) => Math.min(1, Math.max(0, fraction));

// En timers längd och tid kvar, «H:MM:SS», i millisekunder.
function hms(text) {
  const [h, m, s] = (text ?? "").split(":").map(Number);
  return ((h * 60 + m) * 60 + s) * 1000;
}

// Millisekunder per enhet för en sensor med tid kvar (device_class duration).
const DURATION_UNITS = { ms: 1, s: 1000, min: 60_000, h: 3_600_000, d: 86_400_000 };

// När Förloppet började och slutar, i millisekunder, eller null när det inte går att veta.
// En timer har sin längd och sluttid. En sensor har bara sluttiden eller tiden kvar, så
// Förloppet räknas från när notisen fick sin nivå. Sensorns egen ändringstid duger inte:
// många apparater justerar sluttiden under tiden, och då skulle stapeln börja om.
function span(shown, since, now) {
  const a = shown.attributes;
  if (shown.entity_id.startsWith("timer.")) {
    const total = hms(a.duration);
    const end = shown.state === "active" ? Date.parse(a.finishes_at) : now + hms(a.remaining);
    return shown.state === "idle" ? null : { start: end - total, end };
  }
  if (a.device_class === "timestamp") return { start: since, end: Date.parse(shown.state) };
  if (a.device_class === "duration") {
    const left = Number.parseFloat(shown.state) * DURATION_UNITS[a.unit_of_measurement];
    return { start: since, end: now + left };
  }
  return null;
}

// Typen Förlopp: tid kvar eller procent, och hur långt det har kommit (0–1) för stapeln.
// since är när notisen fick sin nivå.
function progress(hass, shown, since, now) {
  const state = hass.formatEntityState(shown);
  if (shown.attributes.unit_of_measurement === "%") {
    const percent = Number.parseFloat(shown.state);
    return { text: state, fraction: Number.isFinite(percent) ? clamp(percent / 100) : null };
  }
  const { start, end } = span(shown, since, now) ?? {};
  if (!Number.isFinite(start) || !Number.isFinite(end)) return { text: state };
  const left = duration(end - now, language(hass), Math.ceil);
  const fraction = end > start ? clamp((now - start) / (end - start)) : 1;
  return { text: strings(hass).left(left), fraction };
}

// Tidszonen som användaren har valt i sin profil i HA: serverns eller enhetens.
function timeZone(hass) {
  return hass.locale?.time_zone === "server" ? hass.config?.time_zone : undefined;
}

// Datumet, «2026-10-29», för en tidpunkt i millisekunder i tidszonen zone.
function localDate(ms, zone) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: zone }).format(ms);
}

// Ett datum, «2026-10-29», som dagar sedan 1970, för att räkna hela dagar mellan datum.
function dayNumber(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86_400_000;
}

// När ett tillfälle är, med så lite text som behövs: nu, om en stund, i dag, i morgon,
// veckodagen under den närmaste veckan och annars datumet. Heldag saknar klockslag.
function when(hass, occurrence, now) {
  const lang = language(hass);
  const zone = timeZone(hass);
  const text = strings(hass);
  const allDay = !occurrence.start.includes("T");
  // Ett heldagsdatum gäller hushållets kalender; mitt på dagen i UTC är samma datum i alla tidszoner.
  const start = allDay ? Date.parse(`${occurrence.start}T12:00:00Z`) : Date.parse(occurrence.start);
  const format = (options) =>
    new Intl.DateTimeFormat(lang, { ...options, timeZone: allDay ? "UTC" : zone }).format(start);
  if (!allDay && start <= now) return text.now;
  if (!allDay && start - now < 60 * 60_000) {
    return text.soon(duration(start - now, lang, Math.ceil));
  }
  const day = allDay ? occurrence.start : localDate(start, zone);
  const days = dayNumber(day) - dayNumber(localDate(now, zone));
  const date =
    days <= 0
      ? text.today
      : days === 1
        ? text.tomorrow
        : days < 7
          ? format({ weekday: "short" })
          : format({ day: "numeric", month: "short" });
  return allDay ? date : `${date} ${format({ timeStyle: "short" })}`;
}

// Typen Kommande: de närmaste tillfällena, med vad det är när det står i kalendern.
function upcoming(hass, occurrences, now) {
  const shown = (occurrences ?? []).map((occurrence) =>
    [when(hass, occurrence, now), occurrence.summary].filter(Boolean).join(" "),
  );
  return { text: shown.join(" · ") || "–" };
}

// Medlemmarna om entiteten är en grupp, som HA:s detaljdialog ser dem: group_entities, som
// alla slags grupper kan ha, och annars entity_id i domänen group eller för en grupphjälpare
// (plattformen group). Andra entiteter kan också ha listan entity_id, till exempel scener.
function members(hass, shown) {
  const a = shown.attributes;
  if (Array.isArray(a.group_entities)) return a.group_entities;
  const group =
    shown.entity_id.startsWith("group.") || hass.entities?.[shown.entity_id]?.platform === "group";
  return group && Array.isArray(a.entity_id) ? a.entity_id : null;
}

// Det notisens Typ visar: en text och, för Förlopp, hur långt det har kommit (fraction, 0–1).
function content(hass, attributes, now) {
  if (attributes.type === "upcoming") return upcoming(hass, attributes.occurrences, now);
  // Eget kort visar sin kortkonfiguration i stället för en text.
  if (attributes.type === "custom") return { text: "" };
  const type = attributes.type;
  const shown = hass.states[attributes.entities?.[0]];
  if (!shown) return { text: "–" };
  if (type === "progress") return progress(hass, shown, Date.parse(attributes.since), now);
  const state = hass.formatEntityState(shown);
  if (type !== "status") return { text: state };
  const group = members(hass, shown);
  if (group) {
    const count = group.filter((id) => hass.states[id]?.state === shown.state).length;
    return { text: strings(hass).group(state, count, group.length) };
  }
  // Regeln vet när tillståndet började, också över en omstart av HA, som sätter om
  // entitetens last_changed. Innan HA har startat vet den det inte än.
  const since = attributes.state_since ?? shown.last_changed;
  return { text: strings(hass).status(state, duration(now - Date.parse(since), language(hass))) };
}

const isObject = (value) => typeof value === "object" && value !== null && !Array.isArray(value);

// Åtgärderna som kortet kan visa som knappar: en knapptext och ett tjänsteanrop, «domän.tjänst».
// Andra hoppas över, så att en trasig åtgärd inte tar de andra med sig.
function actions(list) {
  return (Array.isArray(list) ? list : [])
    .filter(
      (action) =>
        typeof action?.name === "string" &&
        action.name.trim() &&
        /^[a-z0-9_]+\.[a-z0-9_]+$/.test(action.action ?? ""),
    )
    .map((action) => ({
      name: action.name,
      action: action.action,
      target: isObject(action.target) ? action.target : {},
      data: isObject(action.data) ? action.data : {},
      confirmation: typeof action.confirmation === "string" ? action.confirmation : null,
    }));
}

// Nivåerna som kan läggas åt sidan.
const SNOOZABLE = ["problem", "ongoing"];

// Om notisen ligger åt sidan. Det kan bara Problem och Pågår.
const isSnoozed = (stateObj) =>
  SNOOZABLE.includes(stateObj.state) && stateObj.attributes.snoozed === true;

// Om notisen är ett kvitterat Larm.
const isAcknowledged = (stateObj) =>
  stateObj.state === "alarm" && stateObj.attributes.acknowledged === true;

// Texten på ett kvitterat Larm: när det larmar igen, om det gör det.
function acknowledgedText(hass, realarmAt, now) {
  const text = strings(hass);
  const realarm = Date.parse(realarmAt ?? "");
  if (!Number.isFinite(realarm)) return text.acknowledged;
  return text.realarm(duration(realarm - now, language(hass), Math.ceil));
}

// Ett datum, «2026-10-29», dagen efter isoDate.
function nextDate(isoDate) {
  return new Date((dayNumber(isoDate) + 1) * 86_400_000).toISOString().slice(0, 10);
}

// En tidpunkt med så lite text som behövs: klockslaget i dag, annars i morgon, i går,
// veckodagen under den närmaste veckan eller datumet före klockslaget.
function dayAndTime(hass, iso, now) {
  const at = Date.parse(iso ?? "");
  if (!Number.isFinite(at)) return "–";
  const lang = language(hass);
  const zone = timeZone(hass);
  const text = strings(hass);
  const format = (options) => new Intl.DateTimeFormat(lang, { ...options, timeZone: zone }).format(at);
  const days = dayNumber(localDate(at, zone)) - dayNumber(localDate(now, zone));
  const time = format({ timeStyle: "short" });
  const day =
    days === 0
      ? null
      : days === 1
        ? text.tomorrow
        : days === -1
          ? text.yesterday
          : Math.abs(days) < 7
            ? format({ weekday: "short" })
            : format({ day: "numeric", month: "short" });
  return day ? `${day} ${time}` : time;
}

// Valen för åt sidan när kortets konfiguration inte har några. label är standardnamnet i
// choices.
const DEFAULT_SNOOZE_OPTIONS = [
  { name: null, label: "hour", for: 60 * 60_000 },
  { name: null, ahead: 4 * 60 * 60_000, earliest: "06:00", latest: "19:00" },
  { name: null, label: "morning", at: "07:00" },
  { name: null, label: "fixed" },
];

const PERIOD_UNITS = { days: 86_400_000, hours: 3_600_000, minutes: 60_000, seconds: 1000 };

// En tidsperiod i millisekunder, som HA:s väljare för tidsperioder skriver dem:
// { days, hours, minutes, seconds }. NaN när den inte går att läsa.
function period(value) {
  if (!isObject(value)) return Number.NaN;
  let ms = 0;
  for (const [unit, amount] of Object.entries(value)) {
    if (!(unit in PERIOD_UNITS) || !Number.isFinite(amount) || amount < 0) return Number.NaN;
    ms += amount * PERIOD_UNITS[unit];
  }
  return ms;
}

// En tidsperiod längre än noll, i millisekunder, eller ett fel.
function positivePeriod(value, where) {
  const ms = period(value);
  if (!(ms > 0)) {
    throw new Error(
      `${where} must be a duration with days, hours, minutes or seconds, such as { hours: 1 }`,
    );
  }
  return ms;
}

// Ett klockslag, «HH:MM», eller ett fel.
function timeOfDay(value, where) {
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) {
    throw new Error(`${where} must be a time of day, HH:MM`);
  }
  return value;
}

// Valen för åt sidan ur kortets konfiguration snooze_options: en lista där varje val har ett
// valfritt namn (name) och antingen hur länge (for), ett klockslag nästa gång det inträffar i
// hemmets tidszon (at, «HH:MM»), hur långt fram från nu, uppåt till hel timme i dag (ahead),
// eller ingetdera, «tills det är lagat». Ett val med ahead heter «Idag kl. N» efter timmen det
// ger och visas bara från klockslaget earliest till och med latest. Tidsperioderna skrivs som HA:s väljare för
// tidsperioder, { hours: 1 }. Utan snooze_options gäller standardvalen. En ogiltig
// konfiguration ger ett fel, som HA visar i stället för kortet.
export function snoozeOptions(options) {
  if (options === undefined) return DEFAULT_SNOOZE_OPTIONS;
  if (!Array.isArray(options) || !options.length) {
    throw new Error("snooze_options must be a list with at least one choice");
  }
  return options.map((option, i) => {
    const where = `snooze_options[${i}]`;
    if (!isObject(option)) throw new Error(`${where} must be a choice with name, for, at or ahead`);
    const unknown = Object.keys(option).filter(
      (key) => !["name", "for", "at", "ahead", "earliest", "latest"].includes(key),
    );
    if (unknown.length) throw new Error(`${where} has unknown keys: ${unknown.join(", ")}`);
    const { name = null } = option;
    if (name !== null && (typeof name !== "string" || !name.trim())) {
      throw new Error(`${where}.name must be a text`);
    }
    if (["for", "at", "ahead"].filter((key) => option[key] !== undefined).length > 1) {
      throw new Error(`${where} can have only one of for, at and ahead`);
    }
    for (const key of ["earliest", "latest"]) {
      if (option[key] !== undefined && option.ahead === undefined) {
        throw new Error(`${where}.${key} needs ahead`);
      }
    }
    if (option.ahead !== undefined) {
      if (name !== null) throw new Error(`${where} with ahead is named after the hour it gives`);
      const earliest =
        option.earliest === undefined ? "00:00" : timeOfDay(option.earliest, `${where}.earliest`);
      const latest =
        option.latest === undefined ? "23:59" : timeOfDay(option.latest, `${where}.latest`);
      if (earliest > latest) throw new Error(`${where}.earliest must be before latest`);
      return { name, ahead: positivePeriod(option.ahead, `${where}.ahead`), earliest, latest };
    }
    if (option.at !== undefined) return { name, at: timeOfDay(option.at, `${where}.at`) };
    if (option.for !== undefined) return { name, for: positivePeriod(option.for, `${where}.for`) };
    return { name };
  });
}

// Datumet, «2026-10-29», och klockslaget, «HH:MM», för en tidpunkt i hemmets tidszon.
function homeClock(hass, now) {
  const zone = hass.config?.time_zone;
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(now);
  return { today: localDate(now, zone), time };
}

// Ett val med ahead som det ser ut nu: «Idag kl. N» och tiden N:00 i dag i hemmets tidszon,
// som är nu plus ahead uppåt till hel timme. Inget före klockslaget earliest, efter latest
// eller när timmen inte är i dag.
function laterToday(hass, option, now) {
  const { today, time } = homeClock(hass, now);
  if (time < option.earliest || time > option.latest) return [];
  const [h, m] = time.split(":").map(Number);
  const hour = Math.ceil((h * 60 + m + option.ahead / 60_000) / 60);
  if (hour > 23) return [];
  const until = `${today}T${String(hour).padStart(2, "0")}:00:00`;
  return [{ name: strings(hass).choices.today(hour), until }];
}

// Namnet på ett val för åt sidan: det egna, standardnamnet eller vad valet gör.
function choiceName(hass, option) {
  const text = strings(hass);
  if (option.name) return option.name;
  if (option.label) return text.choices[option.label];
  if (option.at !== undefined) return option.at;
  if (option.for !== undefined) return duration(option.for, language(hass));
  return text.choices.fixed;
}

// Valen för åt sidan som kortet visar nu, med sina namn. Ett val med ahead har sin tid räknad
// redan här, så att tiden som skickas är den i namnet.
function choices(hass, options, now) {
  return options.flatMap(({ label, ...option }) =>
    option.ahead !== undefined
      ? laterToday(hass, option, now)
      : [{ ...option, name: choiceName(hass, { label, ...option }) }],
  );
}

// Vad tjänsten snooze får för ett val ur cardModel, räknat från now: till när, eller inget för
// «tills det är lagat». Ett klockslag är nästa gång det inträffar i hemmets tidszon och skickas
// utan tidszon, som HA:s datumväljare gör, så att HA räknar det i hemmets tidszon.
export function snoozeData(hass, choice, now) {
  if (choice.for !== undefined) return { until: new Date(now + choice.for).toISOString() };
  if (choice.until !== undefined) return { until: choice.until };
  if (choice.at === undefined) return {};
  const { today, time } = homeClock(hass, now);
  return { until: `${choice.at > time ? today : nextDate(today)}T${choice.at}:00` };
}

// En notis som ligger åt sidan, som en post i listan «Lagt åt sidan»: till när och sedan när
// den har haft sin nivå. moreInfo som för en notis som kortet ritar.
function snoozedRow(hass, stateObj, now) {
  const a = stateObj.attributes;
  const text = strings(hass);
  const since = dayAndTime(hass, a.since, now);
  return {
    id: stateObj.entity_id,
    level: stateObj.state,
    type: a.type,
    name: a.friendly_name ?? stateObj.entity_id,
    icon: a.icon ?? null,
    stateObj: stateIconOf(hass, a),
    text: a.snoozed_until
      ? text.snoozedUntil(dayAndTime(hass, a.snoozed_until, now), since)
      : text.snoozedUntilFixed(since),
    moreInfo: a.entities?.[0] ?? stateObj.entity_id,
  };
}

// Entiteten vars ikon för tillståndet en Status visar när regeln inte har någon egen ikon, som
// HA:s tile- och entities-kort. För en grupp är det gruppentiteten. Annars null.
function stateIconOf(hass, attributes) {
  if (attributes.type !== "status" || attributes.icon) return null;
  return hass.states[attributes.entities?.[0]] ?? null;
}

// En notis som kortet ritar. text är orsaken när regeln har en, annars det Typen visar; ett
// kvitterat Larm säger i stället att det är kvitterat. Ett Värde utan orsak står före namnet
// på Blick och Tyst (valueFirst). moreInfo är entiteten som ett tryck visar i HA:s
// detaljdialog: den första som notisen visar, annars notisen själv. acknowledgeable är ett
// Larm som går att kvittera och snoozable ett Problem eller en Pågår-notis som kan läggas åt
// sidan.
function row(hass, stateObj, now) {
  const a = stateObj.attributes;
  const { text, fraction = null } = content(hass, a, now);
  const reason = typeof a.reason === "string" && a.reason ? a.reason : null;
  const acknowledged = isAcknowledged(stateObj);
  return {
    id: stateObj.entity_id,
    name: a.friendly_name ?? stateObj.entity_id,
    icon: a.icon ?? null,
    stateObj: stateIconOf(hass, a),
    type: a.type,
    text: acknowledged ? acknowledgedText(hass, a.realarm_at, now) : (reason ?? text),
    acknowledged,
    acknowledgeable: stateObj.state === "alarm" && !acknowledged,
    snoozable: SNOOZABLE.includes(stateObj.state),
    valueFirst: a.type === "value" && !reason,
    fraction,
    card: a.type === "custom" ? a.card : null,
    moreInfo: a.entities?.[0] ?? stateObj.entity_id,
    actions: actions(a.actions),
  };
}

// Okvitterade Larm före kvitterade, sedan regelns ordningstal, lägst först; entitets-id avgör
// mellan lika tal. Tillgänglighet saknar ordningstal och kommer före reglerna.
function byNoticeOrder(a, b) {
  if (isAcknowledged(a) !== isAcknowledged(b)) return isAcknowledged(a) ? 1 : -1;
  const pa = a.attributes.priority ?? -Infinity;
  const pb = b.attributes.priority ?? -Infinity;
  if (pa !== pb) return pa < pb ? -1 : 1;
  return a.entity_id.localeCompare(b.entity_id);
}

// now är tiden i millisekunder, så att «hur länge» kan räknas, och options valen för åt sidan
// ur snoozeOptions. Notiserna som ligger åt sidan ritas inte på sin nivå utan står i snoozed,
// och choices är valen som kortet visar nu, med namn, som snoozeData tar.
export function cardModel(hass, now, options = DEFAULT_SNOOZE_OPTIONS) {
  const notices = Object.keys(hass.entities ?? {})
    .filter((id) => hass.entities[id].platform === DOMAIN)
    .map((id) => hass.states[id])
    .filter((s) => s?.attributes.contract === CONTRACT);
  const shown = notices.filter((s) => !isSnoozed(s));
  const atLevel = (level) =>
    shown
      .filter((s) => s.state === level && DRAWN_TYPES.includes(s.attributes.type))
      .sort(byNoticeOrder)
      .map((s) => row(hass, s, now));
  return {
    calm: !shown.some((s) => NEEDS_ATTENTION.includes(s.state)),
    snoozed: SNOOZABLE.flatMap((level) =>
      notices
        .filter((s) => s.state === level && isSnoozed(s))
        .sort(byNoticeOrder)
        .map((s) => snoozedRow(hass, s, now)),
    ),
    choices: choices(hass, options, now),
    alarm: atLevel("alarm"),
    problem: atLevel("problem"),
    ongoing: atLevel("ongoing"),
    glance: atLevel("glance"),
    quiet: atLevel("quiet"),
  };
}
