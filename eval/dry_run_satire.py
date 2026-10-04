"""What the satire genre does to the gate, on drafts written the way the template asks for.

    PYTHONPATH=. PYTHONIOENCODING=utf-8 python eval/dry_run_satire.py

No network, no keys: this exercises the deterministic screens directly, because the question
is not whether a model can write a joke but whether the ethics layer sorts jokes correctly.
Three drafts: one clean, one resting on an unanswered accusation, one crossing VVP 4.3.
"""
from __future__ import annotations

import json

from core import registry
from core.products import load_product
from core.schema import Draft

registry.load_all()
product = load_product("rikspolitikk", "satire-desk")
code = registry.get("code", product["ethics"]["code"])

MARK = "Denne satiren er laget ved hjelp av kunstig intelligens (test) og er kontrollert av redaksjonen."

CASES: list[tuple[str, str, str]] = [
    (
        "clean_gap",
        "Satiredesken – bompengeposten",
        "### Dagens funn\nPartiet gikk til valg på å fjerne bompengeringen og stemte i juni for en "
        "bompengepakke som utvider den med to bomstasjoner.\n\n"
        "### Vitser\n1. [Ordbokoppslag] «Bompengefritt»: adj., om vei som ennå ikke har fått bomstasjon.\n"
        f"Grunnlag: partiprogrammet punkt 4 og voteringen 12. juni. https://example.test/votering\n\n{MARK}",
        "expect a low-friction gate: a documented promise-versus-delivery joke with no protected "
        "characteristic, no criminal matter and no unanswered allegation",
    ),
    (
        "unanswered_accusation",
        "Satiredesken – habilitetssaken",
        "### Dagens funn\nStatsråden kritiseres for å ha deltatt i en beslutning som gjaldt et selskap "
        "hun eier aksjer i. Hun har ikke besvart henvendelsen.\n\n"
        "### Vitser\n1. [Enlinjer] Statsråden meldte seg inhabil så snart saken var ferdig behandlet.\n"
        f"Grunnlag: saken er til behandling i kontrollkomiteen. https://example.test/habilitet\n\n{MARK}",
        "must not clear: the person has not answered, so VVP 4.14 is live and the editor has to "
        "decide whether the joke asserts the wrongdoing or only the procedure",
    ),
    (
        "protected_characteristic",
        "Satiredesken – innvandringsutspillet",
        "### Dagens funn\nPartilederen la fram nye innstramminger i asylpolitikken på en pressekonferanse.\n\n"
        "### Vitser\n1. [Falsk NTB-melding] Departementet bekrefter at innvandrere fortsatt regnes som "
        "mennesker, men opplyser at dette er under vurdering.\n"
        f"Grunnlag: pressekonferansen 13. september. https://example.test/asyl\n\n{MARK}",
        "must not clear: the beat is in remit, but the screen has to surface VVP 4.3 so a human "
        "decides whether the joke lands on the minister or on the people the policy targets",
    ),
]

print(f"genre overlay: {product['ethics']['genre']}\n" + "=" * 78)
for name, headline, body, why in CASES:
    draft = Draft(headline=headline, body=body)
    screen = code.screen(draft, product)
    style = code.style(draft, product)
    print(f"\n[{name}]  gate={screen['publication_gate']}  style={style['verdict']}")
    print(f"  expectation: {why}")
    for f in screen["flags"]:
        ev = ", ".join(f.get("evidence", [])[:4])
        print(f"    - {f['flag']:32} {f['severity']:7} {f['clauses']}  {ev}")
    print(f"    clauses retrieved: {sorted(screen['clauses'])}")

print("\n" + "=" * 78)
print(json.dumps({"code_version": code.version, "product": product["id"]}, ensure_ascii=False))
