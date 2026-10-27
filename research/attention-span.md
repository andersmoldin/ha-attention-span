# AttentionSpan – teknisk lösning

En relevansstyrd dashboard för Home Assistant: hemskärmen visar bara det som är viktigt nu, och allt annat är dolt tills det blir relevant.
Bygger på designskisserna i `~/Developer/home-assistant/research/UI/`, främst «Det som är viktigt nu» (runda 2).
Begreppen definieras i `GLOSSARY.md`, och de beslut som är svåra att ändra finns i `docs/adr/`.
Ett klickbart utkast av regeldialogen, inställningssidan och kortet finns i `.lavish/rule-draft.html`.

## Sammanfattning

En HACS-integration i Python där varje regel ställs in i gränssnittet med högst ett villkor per nivå, och där den allvarligaste uppfyllda nivån gäller.
Varje regel exponeras som en egen sensor med nivå, typ, ordning, orsak, kvittering och «åt sidan»-status som attribut.
En separat sida för tillgänglighet gör integrationer som inte laddas och utvalda enheter som inte svarar till Problem eller Larm, utan att någon regel behöver skrivas.
Samma repo levererar ett kort till sections-vyn som rangordnar notiserna och ritar dem med fem typer, medan andra kort och teman kan byggas mot samma dataformat.

## Principer

- **Bedömning och presentation är skilda åt.** Backend avgör vad som är relevant; frontend ritar bara. Samma bedömning kan då användas av automationer, notiser, röstassistent och andra kort.
- **Inga hårdkodade entiteter eller apparater.** Allt som rör ett specifikt hem är konfiguration, eftersom lösningen distribueras via HACS.
- **Inget eget regelspråk.** Villkor uttrycks med Home Assistants inbyggda villkor och templates.
- **Engelska nycklar, svenska via översättningar.** Tillstånd, attribut och tjänster har engelska namn; svenska kommer från `translations/` (ADR 0001).

## Nivåmodellen

| Nivå (nyckel) | Betydelse | Exempel | Beteende |
|---|---|---|---|
| Larm (`alarm`) | Något är fel och kräver åtgärd nu. | Läcka, brandvarnare | Överst, stort, rött. Kan kvitteras, aldrig läggas åt sidan. |
| Problem (`problem`) | Något är fel och kräver åtgärd, men inte nu. | Integration nere, frysen 7 °C, ytterdörren olåst kl. 23 | Under larm. Kan läggas åt sidan. |
| Pågår (`ongoing`) | Något händer eller väntar på hushållet och tar slut av sig självt eller genom en åtgärd. Inget är fel. | Tvätten kör eller är klar men inte urplockad, ställ ut soptunnan i kväll | Ett kort per sak. Kan läggas åt sidan. |
| Blick (`glance`) | Värt att se i förbigående. | Bilens laddning, inomhustemperatur | Alltid där, större. |
| Tyst (`quiet`) | Finns där om du letar efter det. | Nästa bussar, elpris, sophämtning | Alltid där, mindre, längst ner. |

Nivåerna är fasta. Dold (`hidden`) är ingen nivå utan tillståndet när ingen nivå gäller.

## Regler

En regel konfigureras i gränssnittet (en config subentry per regel). Dialogen har fälten i den här ordningen:

1. **Typ**, först, eftersom den styr vilka entitetsfält och orsaksmallar som följer (se Typer).
2. **Namn och ikon.**
3. **Entiteter** som typen visar.
4. **Nivåvillkor:** en rad per nivå med högst ett villkor, som anges med Home Assistants villkorsväljare. Behövs flera villkor för samma nivå kombineras de med HA:s *Eller*. «Alltid» är ett eget val, eftersom HA saknar ett villkor som alltid är sant.
5. **Dölj när:** ett valfritt villkor som gör regeln dold oavsett nivåvillkor.
6. **Ordning:** en lista med de regler som kan hamna på samma nivå, där regeln flyttas upp eller ner med pilar. Ett prioritetstal sparas i bakgrunden.
7. **Orsak:** en färdig mall för typen (t.ex. «Öppen i {tid}», «{tid} kvar») eller en egen template, med förhandsvisning. Orsak gäller hela regeln; det som skiljer mellan nivåer löses i mallen.
8. **Åtgärder** (valfritt): tjänsteanrop som kortet visar som knappar, t.ex. «Starta om». Gäller hela regeln och alla typer.
9. **Larma igen efter kvittering:** visas bara om regeln kan bli Larm. Standard 24 h; tomt betyder aldrig.
10. **Fladdergräns:** hur länge ett villkor måste ha varit falskt innan det räknas som släppt. Standard 5 min.

### Utvärdering

- Alla nivåvillkor utvärderas, och den **allvarligaste** uppfyllda nivån gäller. Ordningen mellan raderna spelar ingen roll (ADR 0002).
- Om **Dölj när** är uppfyllt blir regeln dold.
- Om en enhet som regeln handlar om är otillgänglig enligt Tillgänglighet, blir regeln dold och Tillgänglighets notis tar över (ADR 0003). Regeldialogen visar den ärvda bevakningen under respektive nivå, med en länk till Tillgänglighet.
- Integrationen lyssnar på entiteterna i varje regels villkor och räknar om när de ändras. Tidsbaserade villkor räknas om på en timer.
- Villkor med tid («offline i 2 h») räknar från när villkoret började gälla, inte som i HA från källentitetens `last_changed`, som sätts om när källans integration laddas efter en omstart. När villkoren började gälla sparas i Home Assistants lagring (`Store`). En regel som var Larm före en omstart är därför Larm direkt efter den, med samma `since`, och ett villkor som slutade gälla under omstarten räknas som släppt. Medan en källentitet väntar på att dess integration ska laddas behålls den sparade tiden.

### Exempel

- *Vatten i tvättstugan* (Status): Larm när läckagegivaren är «fukt»; Pågår när fukten är över 70 %. Efter kvittering och när läckan har slutat visas «Torkar – 78 % fukt».
- *Findus* (Status): Problem när den har fastnat; Pågår när den städar. Offline hanteras av Tillgänglighet.
- *Ytterdörren* (Status): Problem när den har varit öppen i 5 min; Pågår när den är öppen; dölj när vädring är på.
- *Tvätten* (Förlopp): Pågår när maskinen kör *eller* är klar och inte urplockad.
- *Sophämtning* (Kommande): Pågår när hämtningen är inom 24 h och klockan är efter 18; annars alltid Tyst.
- *Buss 3* (Kommande): alltid Tyst, de tre närmaste avgångarna.

## Typer

En typ beskriver innehållets form; nivån beskriver betoningen. Alla typer kan visas på alla nivåer och ha åtgärder. Kvittera-knappen följer av nivån Larm, inte av typen.

| Typ (nyckel) | Visar | Entiteter | Exempel |
|---|---|---|---|
| Status (`status`) | Ett tillstånd och hur länge det har gällt, för en entitet eller en grupp | En entitet eller grupp, valfri domän | «Ytterdörren · öppen i 10 min», «Fönster · 3 öppna» (namnen bakom ett tryck) |
| Förlopp (`progress`) | Tid kvar eller procent, med stapel | En sensor med tid kvar eller procent, valfritt sluttid | «Tvätten · 40 min kvar» |
| Värde (`value`) | Ett tal med enhet | En numerisk sensor | «Bilen 52 %», «Inne 21,4°» |
| Kommande (`upcoming`) | Nästa tillfälle eller de närmaste N | En kalender eller en sensor med tidpunkter | «Buss 3 · 7 · 19 · 31 min», «Sopor · mån 06:30» |
| Eget kort (`custom`) | Valfri Lovelace-kortkonfiguration | Det kortet behöver | Kamerakort, graf |

## Tillgänglighet

En egen inställningssida, inte en del av varje regel (ADR 0003).

- **Integrationer** som inte laddas blir Problem direkt. Bevakningen är på som standard, har en lista med undantag (t.ex. Google Cast som strular när tv:n är av) och kan stängas av helt. Alla trasiga integrationer samlas i en enda notis och entitet: «2 integrationer laddas inte: Nibe, Tibber» (ADR 0004).
- **Enheter** bevakas bara om man lägger till dem. Varje enhet har «Problem efter X» och valfritt «Larm efter Y». Bevakningen gäller enheter, inte entiteter, eftersom en enhet har många entiteter som går ner samtidigt.
- Tillgänglighetens notiser visas **först inom sin nivå**, med den som gick ner senast överst. Ordningen kan ändras i en inställning.

## Lägg åt sidan och kvittera

- Gäller hela hushållet; samma läge på väggplatta och telefoner.
- Sparas i Home Assistants lagring (`Store`) och överlever omstart.

### Kvittera (Larm)

- Ett kvitterat larm ligger kvar i kompakt form tills villkoret släpper eller tiden för «larma igen» har gått (standard 24 h).
- Kvitteringen nollställs först när villkoret har varit falskt längre än fladdergränsen.

### Lägg åt sidan (Problem och Pågår)

- Valen är **1 timme · Ikväll 21:00 · I morgon bitti · Tills det är lagat**. De är standard och kan ändras i kortets konfiguration. «Tills det är lagat» har ingen sluttid.
- En notis som lagts åt sidan visas igen när något av följande inträffar:
  1. **Tiden har gått ut.**
  2. **Ny händelse:** regeln har varit under nivån den lades åt sidan på (lägre nivå eller dold) längre än fladdergränsen och når den nivån igen. För den samlade integrationsnotisen räknas en ny trasig integration som en ny händelse.
  3. **Högre nivå:** regeln har gått till en allvarligare nivå än när notisen lades åt sidan.
- Blick och Tyst kan inte läggas åt sidan; för dem är Dölj när rätt verktyg.

## Kortet

Ett eget Lovelace-kort som läggs i en vanlig sections-vy. Det läser alla AttentionSpan-entiteter, rangordnar dem och ritar dem.

**Rangordning:** först nivå, sedan Tillgänglighet före regler, sedan regelns ordning.

**Per nivå:**

- **Larm:** okvitterade före kvitterade. Det första larmet visas i full storlek. Finns det fler visas en röd stapel i full bredd med namnen: «＋1 larm till: Brandvarnare hallen». Ett tryck visar alla. Kvitteras det första tar nästa okvitterade dess plats.
- **Problem:** det första visas i full storlek, resten bakom «+N problem till».
- **Pågår:** ett kort per notis.
- **Blick:** större rader eller chip.
- **Tyst:** mindre rader längst ner.

Typen bestämmer innehållet i varje kort (se Typer).

**Åt sidan:** ett gemensamt gult chip, «⚠ N åt sidan», uppe till höger. Ett tryck öppnar listan «Lagt åt sidan». Varje post visar «Åt sidan till 21:00 · sedan 19:40» och knappen «Ta fram igen». Är listan tom står det «Inget ligger åt sidan.»

Om inget är relevant visas ett lugnt tomt läge. Detaljvyer bakom ett tryck använder Home Assistants vanliga dialogrutor.

Utseende (Natt/Dag) hanteras med Home Assistant-teman och CSS-variabler; teman ändrar färg och typsnitt, inte layout.

## Dataformat (kontraktet mot frontend), version 1

Attributnamnen är ett versionerat, dokumenterat kontrakt så att tredjepartskort och teman kan byggas mot det.

**Entiteter**

- En per regel: `sensor.attention_span_<regel>`
- En per bevakad enhet: `sensor.attention_span_availability_<enhet>`
- En samlad för integrationer: `sensor.attention_span_integrations`

**Tillstånd:** `alarm`, `problem`, `ongoing`, `glance`, `quiet` eller `hidden`.

**Attribut**

| Attribut | Innehåll |
|---|---|
| `contract` | Kontraktets version, `1` |
| `source` | `rule`, `device` eller `integrations` |
| `type` | `status`, `progress`, `value`, `upcoming` eller `custom` |
| `priority` | Regelns ordningstal; tomt för Tillgänglighet |
| `reason` | Orsakstexten, färdigrenderad på hemmets språk; `null` när regeln saknar orsak eller texten är tom |
| `entities` | De entiteter typen visar |
| `actions` | Åtgärder som kortet visar som knappar. Varje åtgärd har `name` (knappens text), `action` («domän.tjänst»), `target`, `data` och `confirmation` (texten kortet frågar med innan tjänsten anropas, eller `null`) |
| `since` | När nuvarande nivå började gälla |
| `acknowledged` | Om larmet är kvitterat |
| `realarm_at` | När ett kvitterat larm larmar igen |
| `snoozed` | Om notisen ligger åt sidan |
| `snoozed_until` | Till när; `null` med `snoozed: true` betyder «tills det är lagat» |
| `occurrences` | De närmaste tillfällena, först det tidigaste, bara för typen `upcoming`. Varje tillfälle har `start`, `end` och `summary`; heldag anges som datum, och för en sensor med tidpunkter är `end` och `summary` `null` |
| `state_since` | När den visade entiteten fick sitt tillstånd, också över en omstart av Home Assistant, bara för typen `status`; `null` innan Home Assistant har startat, när entiteten saknas och medan den väntar på att dess integration ska laddas med ett annat tillstånd än före omstarten |
| `card` | Kortkonfigurationen, bara för typen `custom` |
| `integrations` | Trasiga integrationer, bara på `sensor.attention_span_integrations` |

**Tjänster**

- `attention_span.snooze`: `until` är valfri; saknas den gäller «tills det är lagat».
- `attention_span.unsnooze`
- `attention_span.acknowledge`

## Paketering

- Ett HACS-repo av typen integration.
- Integrationen levererar kortets JavaScript och registrerar det som frontend-resurs automatiskt, så att kort och integration alltid har matchande versioner.
- Andra kort och teman kan byggas i separata repon mot dataformatet.

## Senare

- **Mätvärde** som fjärde sätt att återkomma från «åt sidan»: regeln pekar på ett tal, och notisen återkommer om talet blir sämre med en viss marginal (t.ex. frysen 4 °C → 7 °C). Kräver ingen ändring i datamodellen.
- **Inbyggd upptäckt av fladder:** en egen inställningssida, som Tillgänglighet, som upptäcker givare som slår av och på och hanterar dem utan att varje regel behöver en egen fladdergräns.
- **Bedömningsvy per regel** som visar vilka nivåvillkor som är uppfyllda och vilken nivå som vann (se «Bedömning per Rule» i `.lavish/rule-draft.html`). Tas med som förslag i en framtida skiss över GUI:ts delar.
- **En dashboard-strategi** som genererar hela vyn, inklusive ikonraden.
- **Fler typer** om de generella formerna inte räcker, t.ex. en riktig lista utan tider om Status för en grupp inte räcker.
