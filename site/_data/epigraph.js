/**
 * The epigraph above the masthead: a line from the Daodejing, in older literary Norwegian.
 *
 * WHY THESE ARE RENDERED HERE AND NOT QUOTED
 * The Daodejing is roughly twenty-six centuries old and long out of copyright. Its TRANSLATIONS
 * are not: every published Norwegian Daodejing is someone's copyrighted work, and pasting one onto
 * a public site would be lifting it. So these are renderings written for this site, from the sense
 * of the chapter rather than from any one translator's wording, in the register the rest of the
 * masthead is in -- the plain, slightly archaic Norwegian of the older literary prose. They are
 * credited as «etter Daodejing, kap. N» ("after"), not as a translation, because that is what they
 * are.
 *
 * One line a day, chosen by day-of-year so the site is not reshuffling under a reader who reloads,
 * and so the sequence is the same for everyone looking on the same day.
 */

// nb: the Norwegian rendering. en: a plain English gloss for the other half of the bilingual site.
const LINES = [
  { ch: 1,  nb: "Den veg som lar seg nemne, er ikkje den evige veg.",
            en: "The way that can be named is not the eternal way." },
  { ch: 2,  nb: "Difor verkar den vise utan å gjera vesen av det, og lærer utan ord.",
            en: "So the wise act without fuss, and teach without words." },
  { ch: 8,  nb: "Det høgste gode er som vatnet: det gagnar alt og strider med inkje.",
            en: "The highest good is like water: it benefits all things and contends with none." },
  { ch: 9,  nb: "Fyll kjeraldet til randa, og du kjem til å søle.",
            en: "Fill the vessel to the brim, and you will spill it." },
  { ch: 11, nb: "Tretti eiker møtest i navet; det er tomrommet som gjer hjulet nyttig.",
            en: "Thirty spokes meet at the hub; it is the emptiness that makes the wheel useful." },
  { ch: 15, nb: "Kven kan la det grumsete vatnet stå til det klårnar av seg sjølv?",
            en: "Who can let muddy water stand until it clears of itself?" },
  { ch: 17, nb: "Den beste styraren veit folket knapt at er der.",
            en: "The best ruler is one the people barely know is there." },
  { ch: 22, nb: "Det bøygde vert heilt att; det kroka vert rett.",
            en: "What is bent becomes whole; what is crooked becomes straight." },
  { ch: 23, nb: "Kvervelvinden varer ikkje morgonen ut, og styrtregnet ikkje dagen.",
            en: "A whirlwind does not outlast the morning, nor a downpour the day." },
  { ch: 24, nb: "Den som står på tå, står ikkje stødig.",
            en: "One who stands on tiptoe is not steady." },
  { ch: 33, nb: "Å kjenna andre er klokskap; å kjenna seg sjølv er ljos.",
            en: "To know others is wisdom; to know oneself is clarity." },
  { ch: 41, nb: "Den store tonen har knapt nokon klang; den store skapnaden har ingen form.",
            en: "The great note is almost without sound; the great shape has no form." },
  { ch: 44, nb: "Veit du når det er nok, lid du ingen skade.",
            en: "Know when it is enough, and you come to no harm." },
  { ch: 56, nb: "Den som veit, talar ikkje; den som talar, veit ikkje.",
            en: "Those who know do not speak; those who speak do not know." },
  { ch: 63, nb: "Tak fatt på det vande medan det endå er lett.",
            en: "Take hold of the difficult while it is still easy." },
  { ch: 64, nb: "Ei ferd på tusen mil tek til med eit einaste steg.",
            en: "A journey of a thousand miles begins with a single step." },
  { ch: 71, nb: "Å vita at ein ikkje veit, er det høgste.",
            en: "To know that one does not know is highest." },
  { ch: 76, nb: "Det myke og veike høyrer livet til; det harde og stive høyrer dauden til.",
            en: "The soft and yielding belong to life; the hard and rigid belong to death." },
  { ch: 78, nb: "Inkje i verda er mjukare enn vatnet, og like vel slit det ned det harde.",
            en: "Nothing in the world is softer than water, yet it wears down the hard." },
  { ch: 81, nb: "Sanne ord er ikkje fagre, og fagre ord er ikkje sanne.",
            en: "True words are not pretty, and pretty words are not true." },
];

module.exports = function () {
  // Day of year, so it turns over at midnight and is stable through the day.
  const now = new Date();
  const start = Date.UTC(now.getUTCFullYear(), 0, 0);
  const day = Math.floor((Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
                          - start) / 86400000);
  return { ...LINES[day % LINES.length], total: LINES.length };
};
