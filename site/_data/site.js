/**
 * Build-time site constants.
 *
 * Internal links are NOT here: they are relative, computed per page by _data/eleventyComputed.js,
 * so one build serves both the hosted site and an offline copy opened straight off the drive.
 */

// TWO BUILDS OUT OF ONE SOURCE TREE.
//
// internal (default) -- the whole archive: every ingested item, its machine translation, browsable
//   by category, outlet, day and source. For the newsroom. Behind a password or opened off the
//   drive, never on an open URL.
//
// public (SITE_PUBLIC=1) -- the digests and nothing else. Our own summary sentences, the source's
//   headline, the outlet's name and a link to the original. No article bodies, no translations of
//   article bodies. That is the difference that makes one hostable and the other not: 1,902 of
//   7,589 archived items carry over 1,500 characters of someone else's reporting, and English
//   translations of those are derivative works. eleventy.config.js drops the archive templates
//   entirely in this mode rather than hiding their links, so there is no route to reach them.
const INTERNAL = process.env.SITE_PUBLIC !== "1";

module.exports = {
  internal: INTERNAL,
  // Indexed only in the public build, and SITE_NOINDEX=1 forces it off again from the outside.
  noindex: INTERNAL || process.env.SITE_NOINDEX === "1",
  // The public origin, for canonical URLs and the sitemap. Only meaningful in the public build;
  // the internal one is opened off the drive or served on localhost and is never indexed.
  origin: (process.env.SITE_ORIGIN || "https://norway-royal-news.pages.dev").replace(/\/+$/, ""),

  // Every chrome string exists in both languages. The archive is read by Norwegian-speaking and
  // English-speaking editors together, so nothing on the page is single-language.
  t: {
    // Retitled 2026-09-17: the archive was always titled Nord-Norge while carrying both desks'
    // items, which browsing by category makes impossible to ignore.
    // Retitled again 2026-09-26: the front page is now the daily brief, not the archive index.
    // Named by the owner, 2026-09-27. A masthead is a proper noun, so it is NOT translated -- the
    // second slot carries the Norwegian standfirst instead, and base.njk drops that line when the
    // two are equal so an untranslated name never prints twice.
    title: INTERNAL
      ? ["Royal News of Norway", "Redaksjonsarkiv"]
      : ["Royal News of Norway", "Nyheter og satire fra Norge"],
    // The motto, set under the nameplate. English on both builds: it is the masthead's own line,
    // not chrome, and translating a motto makes it a caption.
    motto: ["News fit for a queen", "News fit for a queen"],
    // Alt text for the crest. It describes the drawing, and says plainly that it is the
    // historic arms rather than the official ones -- a screen reader should not be told
    // this site carries the state symbol when it does not.
    crestAlt: ["Historic Norwegian arms: a gold lion with an axe on a red shield",
               "Historisk norsk riksvåpen: gull løve med øks på rød skjold"],
    front: ["Today", "I dag"],
    notFound: ["That page does not exist.", "Den siden finnes ikke."],
    briefs: ["Briefs", "Brief"],
    allDigests: ["All briefs", "Alle brief"],
    earlier: ["Earlier briefs", "Tidligere brief"],
    noDigest: ["No brief drafted yet — run `python run.py --run daily-digest`.",
               "Ingen brief er skrevet ennå."],
    approved: ["Approved", "Godkjent"],
    flagsWord: ["flags", "merknader"],
    about: ["How this works", "Slik fungerer det"],
    // The literature desk is called Norlit, by name, on Jared's instruction.
    norlitNav: ["Norlit", "Norlit"],
    magasin: ["Literature", "Litteratur"],
    allMagasin: ["All posts", "Alle innlegg"],
    contents: ["Contents", "Innhold"],
    chapters: ["Chapters", "Kapitler"],
    wholeEssay: ["The whole series as one essay", "Hele serien som ett essay"],
    noSeries: ["No chapters published yet.", "Ingen kapitler publisert ennå."],
    seriesLede: [
      "A weekly literary history of the idea of the king in Norway, read through the texts themselves — saga, law, hymn, ballad, drama and the newspapers of 1905. Chapters appear as they are written.",
      "En ukentlig litteraturhistorie om kongetanken i Norge, lest gjennom tekstene selv — saga, lov, salme, ballade, drama og avisene fra 1905. Kapitlene kommer etter hvert som de skrives."],
    withReservation: ["with reservation", "med forbehold"],
    quotationsChecked: ["quotations checked against their sources", "sitater kontrollert mot kildene"],
    quotationsFailing: ["could not be found", "ble ikke funnet"],
    litReservation: ["This piece was flagged by its own checks",
                     "Dette stykket ble merket av sine egne kontroller"],
    litReservationFoot: [
      "Published with the flag shown rather than withheld. The checks are pattern rules run before publication, and they over-match: one has held an essay on Ibsen's Ghosts because it uses the word «barn».",
      "Publisert med merknaden synlig framfor å holdes tilbake. Kontrollene er mønsterregler som kjøres før publisering, og de treffer for bredt: én har holdt tilbake et essay om Ibsens Gengangere fordi det bruker ordet «barn»."],
    heldForReview: ["Held for review", "Holdt for gjennomsyn"],
    heldNote: ["These did not pass their own checks and are not published. A reason is shown for each.",
               "Disse besto ikke sine egne kontroller og er ikke publisert. En grunn vises for hver."],
    latestLit: ["From the literature desk", "Fra litteraturdesken"],
    works: ["Works quoted", "Verk sitert"],
    // Deliberately "Picture of X", never "X, pictured" or a bare caption: the reader must
    // not take an evergreen Commons image for a photograph of the event reported.
    pictureOf: ["Picture of", "Bilde av"],
    writtenAgainst: ["Written against", "Skrevet mot"],
    noMagasin: ["Nothing published yet — posts stay drafts until an editor releases them.",
                "Ingenting publisert ennå — innlegg er utkast til en redaktør slipper dem."],
    // Rewritten 2026-10-01: the old text said pieces appear "only once a person has released
    // them", which stopped being true the moment review pieces started publishing. A standfirst
    // that describes a gate the site no longer has is worse than none.
    magasinLede: [
      "Norwegian literature read against the news, from a desk with its own verified corpus. Every quotation is checked word for word against its source before publication; where a check flagged something, the piece says so.",
      "Norsk litteratur lest mot nyhetene, fra en desk med sitt eget verifiserte korpus. Hvert sitat kontrolleres ord for ord mot kilden før publisering; der en kontroll har merket noe, sier stykket fra."],
    via: ["found via", "funnet via"],
    regions: ["By region", "Etter region"],
    allRegions: ["All regions", "Alle regioner"],
    regionFrom: ["from outlets based here.", "fra redaksjoner som holder til her."],
    regionsLede: [
      "Where the reporting came from, rather than what it is about. An article on Svalbard written in Murmansk and one written in Tromsø are the same subject and not the same story.",
      "Hvor journalistikken kommer fra, ikke hva den handler om. En artikkel om Svalbard skrevet i Murmansk og en skrevet i Tromsø er samme tema, men ikke samme sak."],
    // For the original-language line under a translated story card. Both columns above are
    // translations now, so the reader is told which language the source actually was.
    langNames: {
      nb: ["Norwegian", "Norsk"], nn: ["Norwegian (Nynorsk)", "Nynorsk"],
      en: ["English", "Engelsk"], sv: ["Swedish", "Svensk"], da: ["Danish", "Dansk"],
      fi: ["Finnish", "Finsk"], se: ["Northern Sami", "Nordsamisk"],
      ru: ["Russian", "Russisk"], de: ["German", "Tysk"], fr: ["French", "Fransk"],
      es: ["Spanish", "Spansk"], it: ["Italian", "Italiensk"], nl: ["Dutch", "Nederlandsk"],
      zh: ["Chinese", "Kinesisk"], ja: ["Japanese", "Japansk"], ko: ["Korean", "Koreansk"],
      hi: ["Hindi", "Hindi"], ar: ["Arabic", "Arabisk"], fa: ["Persian", "Persisk"],
      ur: ["Urdu", "Urdu"], id: ["Indonesian", "Indonesisk"], tr: ["Turkish", "Tyrkisk"],
      pt: ["Portuguese", "Portugisisk"], pl: ["Polish", "Polsk"],
    },

    // The ethics warning that replaced withholding on 2026-09-28. Wording matters here: the
    // screens are regex run over the draft before any model sees it, and they over-match, so the
    // banner says what was flagged and who should judge it -- it does not assert a breach.
    ethicsWarning: ["Ethics flags on this brief",
                    "Presseetiske merknader til denne briefen"],
    ethicsFoot: [
      "Flagged automatically against the Vær Varsom-plakaten before publication. A flag marks something a reader should weigh, not a finding that the code was breached.",
      "Automatisk merket mot Vær Varsom-plakaten før publisering. En merknad peker på noe leseren bør vurdere, ikke en konstatering av brudd."],
    flagNames: {
      accusation_requires_reply: ["Contains an accusation — the right of reply may apply",
                                  "Inneholder en beskyldning — retten til samtidig imøtegåelse kan gjelde"],
      minor_involved: ["May involve a minor", "Kan omtale mindreårige"],
      ethnicity_or_identity: ["Mentions ethnicity, nationality or identity",
                              "Omtaler etnisitet, nasjonalitet eller identitet"],
      accident_or_death: ["Concerns an accident or a death", "Gjelder ulykke eller dødsfall"],
      criminal_matter_identification: [
        "Concerns a criminal matter — identification rules apply",
        "Gjelder en straffesak — identifiseringsreglene gjelder"],
      ai_generated_content: ["Drafted with AI assistance", "Skrevet med hjelp av kunstig intelligens"],
    },
    fullText: ["Full text", "Hele teksten"],
    // The digest template's two halves. Outside NRK leads; NRK's own coverage is listed as overlap.
    ownCoverage: ["NRK already has", "NRK har allerede"],

    topics: ["Categories", "Kategorier"],
    briefTopics: ["Brief categories", "Kategorier i brief"],
    storiesWord: ["stories", "saker"],
    citedIn: ["In briefs", "I brief"],
    noTopics: ["No categorised stories yet.", "Ingen kategoriserte saker ennå."],
    satire: ["Satire", "Satire"],
    satireNote: [
      "Jokes anchored to something a named politician on the Norwegian right actually said, quoted with a link. Only briefs an editor has approved appear here.",
      "Vitser forankret i noe en navngitt politiker på høyresiden faktisk har sagt, sitert med lenke. Bare brief en redaktør har godkjent vises her."],
    noSatire: ["Nothing approved for publication yet.",
               "Ingenting er godkjent for publisering ennå."],
    satireWaiting: ["drafted and waiting for an editor's decision.",
                    "skrevet og venter på redaktørens avgjørelse."],
    categories: ["Categories", "Kategorier"],
    hits: ["hits", "treff"],
    score: ["score", "skår"],
    everything: ["Everything", "Alt"],
    everythingNote: ["Every item ingested, whether or not it matched a beat:",
                     "Alt som er hentet inn, uansett om det traff et felt:"],
    rankedNote: ["Ranked by match score, strongest first.",
                 "Rangert etter treffskår, sterkest først."],
    allCategories: ["All categories", "Alle kategorier"],
    noHits: ["No hits yet — run `python run.py --publish` to export them.",
             "Ingen treff enda."],
    latest: ["Latest", "Siste"],
    browse: ["Browse", "Bla gjennom"],
    sources: ["Sources", "Kilder"],
    days: ["Days", "Dager"],
    outlets: ["Outlets", "Redaksjoner"],
    own: ["NRK", "NRK"],
    external: ["Outside NRK", "Utenfor NRK"],
    // Shown instead of a card's headline when the item has left the archive and no title
    // survives. The fallback used to be the raw source URL, which printed four-hundred-character
    // Google News redirects as <h3> headlines on the public site. The URL is still one line below,
    // on "Read the original", so nothing is lost by not shouting it.
    untitled: ["Title unavailable", "Tittel mangler"],
    readOriginal: ["Read the original", "Les originalen"],
    noSummary: ["No summary in the source — title only.", "Ingen sammendrag i kilden — bare tittel."],
    pending: ["English not yet available.", "Engelsk er ikke klar ennå."],
    english: ["English", "Engelsk"],
    norwegian: ["Source", "Kilde"],
    items: ["items", "saker"],
    prev: ["Newer", "Nyere"],
    next: ["Older", "Eldre"],
    page: ["Page", "Side"],
    // THE PUBLIC FOOTER. Added 2026-10-02, when the access gate came off and the site stopped
    // being a review surface for one editor. Until then every reader had arrived through a link
    // that came with an explanation attached; now anyone can land on any of the seventy pages
    // cold, including a satire page about a named living politician, so each page has to say for
    // itself what it is. The AI-marking line already sat inside the brief bodies -- that covered
    // 25 pages of 70 and left Norlit, satire, the region and category indexes saying nothing.
    // Build stamp and the staleness line. See site/_data/built.js for why this is on the page.
    builtAt: ["Page built", "Siden er bygget"],
    newestBrief: ["Newest brief", "Nyeste brief"],
    staleWarn: [
      "No brief has been published for today yet. This page is showing the most recent one.",
      "Ingen brief er publisert for i dag ennå. Denne siden viser den siste som finnes."],
    osloTime: ["Oslo time", "norsk tid"],
    noticeWhat: [
      "This is a newsroom monitoring tool, not a news publication. It reads what other outlets publish, groups it by beat and summarises it for an editor. The reporting is theirs; the summaries are ours.",
      "Dette er et redaksjonelt overvåkingsverktøy, ikke en nyhetspublikasjon. Det leser hva andre redaksjoner publiserer, grupperer det etter felt og sammenfatter det for en redaktør. Journalistikken er deres; sammendragene er våre."],
    noticeAi: [
      "Every brief, letter and literary piece here is drafted with AI assistance and marked as such. Summaries can be wrong, and a machine translation is not a quotation. Follow the link and read the original before relying on anything.",
      "Hver brief, hvert brev og hvert litterært bidrag her er skrevet med hjelp av kunstig intelligens og merket som det. Sammendrag kan være feil, og en maskinoversettelse er ikke et sitat. Følg lenken og les originalen før du bygger på noe."],
    noticeRights: [
      "Headlines, links and outlet names belong to the outlets that published them. Nothing here reproduces an article; every item links to its source.",
      "Titler, lenker og redaksjonsnavn tilhører redaksjonene som har publisert dem. Ingenting her gjengir en artikkel; hver sak lenker til kilden."],
    noticeSatire: [
      "The satire section is satire: invented jokes anchored to a real, linked quotation from a named politician. The jokes are not statements of fact and were never said by the person quoted.",
      "Satiredelen er satire: oppdiktede vitser forankret i et ekte, lenket sitat fra en navngitt politiker. Vitsene er ikke faktapåstander, og de er aldri sagt av den som siteres."],
    noticeCrest: [
      "The crest is the historic medieval arms, drawn for this page. It is not the official arms of Norway, not the King's cypher, and implies no connection to the Royal House.",
      "Våpenet er det historiske middelalderske riksvåpenet, tegnet for denne siden. Det er ikke Norges offisielle riksvåpen, ikke kongens monogram, og antyder ingen tilknytning til Kongehuset."],
    backToIndex: ["All items", "Alle saker"],
  },
};
