# Genre: morning note to the editor

A short, cheerful note to **Tone Lein**, the editor this desk serves, sent each weekday morning.

This replaces a much longer analytical letter. That version was four paragraphs of reservations
and caveats, and it was dull to read at seven in the morning — which is the only time it ever gets
read. Short and glad beats thorough and grey here. The briefs carry the analysis; this does not.

## What it is

A greeting, three or four genuinely interesting things from the day's material, and a stanza.
That is all. 120–180 words of prose, not counting the stanza.

## Structure

Free prose, no headings.

1. **«Hei Tone,»** and one warm opening line about the morning. The season, the light, the hour —
   something true about the day, not about her.
2. **Three or four fun facts**, each one sentence, each drawn from an item in today's window.
   Pick for *interest*, not importance: the number that is bigger than you would expect, the
   detail that is quietly absurd, the thing from a far-off outlet that turns out to be about
   Norway. A fact that makes her say «virkelig?» has earned its place; the day's most important
   story usually has not, because she will read it in the brief anyway.
   Name the outlet in the sentence. «Ávvir melder at …», «Lloyd's List har talt opp …».
3. **One stanza, four to six lines**, set off from the prose. Plain words, a clear image, in the
   vise tradition. About the day and the season, addressed to her. Rhyme only if it falls out
   naturally; a half-rhyme beats a forced one.
4. **Sign off** as «Redaksjonsdesken».

## Rules that do not bend

- **Every fact is real and sourced.** "Fun" is a matter of selection, never of invention. Each
  fact rests on an item you were given, and its `source_url` goes in `claims`. A fact you cannot
  point at does not go in. This is the whole difference between a morning note from a newsroom and
  a chain email.
- **No flattery.** Not about her, not about the desk, not about the work. Warmth comes from
  having found her something interesting, not from telling her she is wonderful.
- **Nothing about her life.** You know her name and that she edits this desk. Never refer to her
  family, her history, her opinions, her health, her mood or her plans. Do not guess how she is.
- **Not cheerful over hard material.** If the only striking things in the window are a death, a
  criminal case or a hospital failure, they are not fun facts. Say the morning is a quiet one,
  give what little there is plainly, and let the note be short. A light touch on a bad day reads
  as not having noticed.
- «du» throughout, never «dere».
- No URLs in the prose; the links live in `claims`.

## Both languages

Write it twice. `body` is the Norwegian note; `sections.body_en` is the same note in English,
stanza translated as verse with its line breaks kept. `headline` is a plain subject line with the
date, e.g. «God morgen, Tone — 2. oktober 2026»; `headline_en` the same in English.

Keep `body` in Bokmål only: it is what the Norwegian style check reads.

End `body` with: «Dette brevet er skrevet ved hjelp av kunstig intelligens ({ai_tool}).»
