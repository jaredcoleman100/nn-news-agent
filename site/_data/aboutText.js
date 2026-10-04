/**
 * Copy for the explainer page, in both languages.
 *
 * Its own module rather than more entries in site.js: site.t is chrome -- button labels, column
 * headings, words that appear on every page -- and this is several screens of prose that belongs
 * to exactly one template.
 *
 * Every NUMBER the page shows comes from _data/pipeline.js instead, measured at build time. The
 * rule for editing this file: if a sentence here states a fact about how the system behaves, and
 * the system stops behaving that way, this file is the bug.
 */
module.exports = {
  lede: [
    "This site is a monitoring desk, not a newspaper. It watches what other newsrooms publish about Norway and the Arctic, in several languages, and summarises it each morning. Nobody here attended an event, phoned a source or witnessed anything. Every figure on this page is measured when the site is built rather than written by hand.",
    "Dette er en overvåkingsdesk, ikke en avis. Den følger hva andre redaksjoner publiserer om Norge og Arktis, på flere språk, og sammenfatter det hver morgen. Ingen her har vært til stede, ringt en kilde eller sett noe selv. Hvert tall på denne siden måles når siden bygges, ikke skrevet for hånd.",
  ],

  sections: [
    {
      h: ["What is collected", "Hva som hentes inn"],
      p: [
        "Feeds are polled hourly. Most are ordinary newsroom RSS feeds; some are research databases; and several are topic-filtered search feeds in languages where no Arctic publication exists — a query for «Norway OR Arctic OR Svalbard» in Chinese, Japanese, Hindi, Arabic or Indonesian returns that country's coverage of this region at a volume worth reading. Only the headline and summary are taken. The article itself stays with its publisher, and every card here links back to it.",
        "Kildene hentes hver time. De fleste er vanlige RSS-strømmer fra redaksjoner, noen er forskningsdatabaser, og flere er emnefiltrerte søk på språk der det ikke finnes noen arktisk publikasjon — et søk på «Norge ELLER Arktis ELLER Svalbard» på kinesisk, japansk, hindi, arabisk eller indonesisk gir det landets dekning av regionen. Bare tittel og ingress hentes. Selve artikkelen blir hos utgiveren, og hvert kort her lenker tilbake til den.",
      ],
    },
    {
      h: ["How stories are chosen", "Hvordan saker velges"],
      p: [
        "Each desk defines beats — Arctic security, fisheries, Helse Nord, Sámi rights — written as descriptions rather than keyword lists. Every incoming item and every beat is turned into a numeric vector by a multilingual model running on the newsroom's own machine, and an item joins a beat when the two are close enough. Because that model is multilingual, a Mandarin article about Arctic shipping scores against a beat written in Norwegian without being translated first. No language model makes a selection decision, and the ranking is not editorial judgement: it is a distance measure, and at the margins it is often wrong.",
        "Hver desk definerer felt — arktisk sikkerhet, fiskeri, Helse Nord, samiske rettigheter — skrevet som beskrivelser, ikke stikkordlister. Hver innkommende sak og hvert felt gjøres om til en tallvektor av en flerspråklig modell som kjører på redaksjonens egen maskin, og en sak treffer et felt når de to ligger nært nok. Fordi modellen er flerspråklig, treffer en kinesisk artikkel om arktisk skipsfart et felt skrevet på norsk uten å bli oversatt først. Ingen språkmodell velger saker, og rangeringen er ikke redaksjonelt skjønn: den er et avstandsmål, og i ytterkantene bommer den ofte.",
      ],
    },
    {
      h: ["Why NRK is listed separately", "Hvorfor NRK står for seg"],
      p: [
        "This desk was built for an NRK newsroom, so NRK's own reporting is not the product — the editor has already seen it. What earns a place is what other outlets are carrying that bears on Norway. NRK's stories still appear, grouped under «NRK already has», as a check against commissioning the same story twice. A brief's lead may never be an NRK story while a usable outside story exists.",
        "Desken er laget for en NRK-redaksjon, og NRKs egne saker er derfor ikke produktet — redaktøren har allerede sett dem. Det som teller, er hva andre redaksjoner har som angår Norge. NRK-sakene vises likevel, samlet under «NRK har allerede», som en kontroll mot å bestille samme sak to ganger. Hovedsaken i en brief kan aldri være en NRK-sak så lenge det finnes en brukbar sak utenfra.",
      ],
    },
    {
      h: ["Translation", "Oversettelse"],
      p: [
        "Every headline is rendered into both English and Norwegian by machine, and the original is shown underneath with its language named and a link to the publisher. No person checks these translations. Where one has not been produced yet the column says so, rather than quietly showing the original — an untranslated headline under a heading reading «English» is not a translation.",
        "Hver overskrift gjengis maskinelt på både engelsk og norsk, og originalen vises under, med språket navngitt og lenke til utgiveren. Ingen person kontrollerer oversettelsene. Der en oversettelse ennå ikke finnes, sier kolonnen det, framfor å vise originalen i stillhet — en uoversatt overskrift under en tittel som sier «Engelsk», er ingen oversettelse.",
      ],
    },
    {
      h: ["How a brief is written", "Hvordan en brief blir til"],
      p: [
        "The items selected for a window go to a language model with a template that fixes the structure: a lead, the material from outside NRK, what NRK already has, and what is being watched. Every claim it makes must name the source URL it rests on, and those links are what appears under each story card. The model does not browse and sees nothing beyond the items it was handed. It can still mischaracterise them — that is what the source links are for.",
        "Sakene som er valgt ut for et vindu, sendes til en språkmodell sammen med en mal som fastsetter strukturen: en hovedsak, stoffet utenfor NRK, hva NRK allerede har, og hva som følges videre. Hver påstand må oppgi kilde-URL-en den bygger på, og det er disse lenkene som står under hvert saksfelt. Modellen surfer ikke og ser ingenting utover sakene den fikk. Den kan likevel gjengi dem feil — det er nettopp derfor kildelenkene er der.",
      ],
    },
    {
      h: ["The ethics flags", "De presseetiske merknadene"],
      p: [
        "Before publication each brief is checked against the Vær Varsom-plakaten by fixed pattern rules. No model is involved: the same text always produces the same flags. The rules over-match, and badly — one has flagged a brief about minorities as involving a child, another treats the ordinary word «criticises» as an accusation carrying a right of reply. Flagged briefs are published with the flags stated on the page rather than withheld, because a warning that hides the story teaches nobody anything, and a label that appears on nearly everything is one people stop reading.",
        "Før publisering kontrolleres hver brief mot Vær Varsom-plakaten av faste mønsterregler. Ingen modell er inne i bildet: samme tekst gir alltid samme merknader. Reglene treffer altfor bredt — én har merket en brief om minoriteter som om den omtalte et barn, en annen behandler det helt vanlige ordet «kritiserer» som en beskyldning med rett til samtidig imøtegåelse. Merkede briefer publiseres med merknadene synlig framfor å holdes tilbake, for en advarsel som skjuler saken lærer ingen noe, og en merkelapp som står på nesten alt, slutter folk å lese.",
      ],
    },
  ],

  limitsH: ["What this is not", "Hva dette ikke er"],
  limits: [
    ["No original reporting. Nothing here was witnessed and no one was interviewed.",
     "Ingen egen journalistikk. Ingenting her er sett, og ingen er intervjuet."],
    ["Summaries and translations are machine-made and unverified. Follow the link before relying on anything.",
     "Sammendrag og oversettelser er maskinlagde og ukontrollerte. Følg lenken før du stoler på noe."],
    ["Coverage follows the feeds. A story no monitored outlet published does not exist here, and the beats reflect one desk's priorities.",
     "Dekningen følger kildene. En sak ingen overvåket kilde har publisert, finnes ikke her, og feltene speiler én desks prioriteringer."],
    ["The satire section is satire, and is published only after an editor approves it.",
     "Satiredelen er satire, og publiseres bare etter at en redaktør har godkjent den."],
  ],

  outletsH: ["Who is monitored", "Hvem som overvåkes"],
  sourcesWord: ["sources", "kilder"],
  languagesWord: ["languages", "språk"],
  itemsWord: ["items held", "saker lagret"],
  hitRate: ["of everything collected clears the threshold and becomes a candidate for a brief.",
            "av alt som hentes inn, passerer terskelen og blir en kandidat til en brief."],
};
