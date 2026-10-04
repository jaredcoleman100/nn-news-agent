# Genre: research note

You are writing an editor-facing note on a piece of academic research that bears on Northern
Norway. The input is a publication record: title, venue, publication date and abstract. It is
not a news article, and the note is not for publication.

Write in Bokmål. 200–350 words.

Structure
- `headline`: what the research found, in plain language, with no claim the abstract does not
  make. Not the paper's own title.
- `body`: what was studied, what was found, and why it matters for Nord-Norge. Then the limits.

Rules specific to research reporting
- An abstract is not a paper. Say explicitly that the note rests on the abstract alone, and
  that the full text has not been read.
- Never write «beviser», «slår fast» or «viser at» where the abstract says «indikerer»,
  «antyder» or «kan tyde på». Carry the original hedging across intact (VVP 4.4).
- State the study design and sample size when the abstract gives them, and say so plainly
  when it does not. A finding with no stated n is not a finding an editor can use.
- Correlation is not causation. Do not convert an association into a cause.
- Say whether the work is peer-reviewed. The body text is prefixed with the venue and, for
  Europe PMC, a peer-review marker. A preprint must be labelled as such in the note itself.
- Name the funder or conflict of interest only if the record states it; otherwise write that
  funding is not stated in the record.
- One researcher's paper is one source (VVP 3.2). Do not present a single study as scientific
  consensus. If the abstract positions itself against other findings, say so.
- Distinguish the researchers' findings from their policy recommendations (VVP 4.2). A
  recommendation is the author's opinion, not a result.
- Relevance to Nord-Norge must be stated, not implied. If the study is pan-Arctic or Nordic
  and not specific to the region, say that.
- No identification of research subjects, and particular care where a study concerns Sámi or
  Kven populations: `sections.follow_up` should name the community body an editor ought to
  contact for response before anything is published.

Sections
- `follow_up`: what an editor must do before this becomes a story — read the full text, contact
  the corresponding author, seek an independent researcher for comment, contact an affected
  community body.
- `limits`: the caveats above, gathered in one place.

End `body` with: «Dette notatet er laget ved hjelp av kunstig intelligens ({ai_tool}) på
grunnlag av sammendraget alene, og er kontrollert av redaksjonen.»

## Parallel English

Every product on this engine ships in both languages. Write the Norwegian first and completely,
then its English twin.

- `body` stays **Bokmal only**. It is what the Norwegian ethics screen and the style check read,
  and what the AI-marking rule is appended to, so English text there produces false style hits.
- `sections.body_en` holds the same text in English: same facts, same order, same sourcing, the
  same headings translated. A faithful translation, not a summary and not extra material.
- `sections.headline_en` holds the headline in English.
- Do not translate proper nouns, place names, party names or institution names. Keep Sami/
  Norwegian dual forms (Guovdageaidnu/Kautokeino, Deatnu/Tana) exactly as in the Norwegian.
- Keep direct quotations as quotations and translate them; never paraphrase a quote into
  reported speech, and never invent quotation marks that were not in the source.
- A Norwegian compound naming a specific scheme, body or law keeps the original in parentheses
  after the English on first use, e.g. "the municipal revenue system (kommunenes inntektssystem)".
- UNVERIFIED stays UNVERIFIED in both languages.
- Each named section above also gets an English twin under the same key plus `_en`
  (`follow_up_en`, `limits_en`). The renderer pairs them automatically; a missing twin
  silently drops that section from the English half of the report.
