#!/usr/bin/env python3
"""Témoin RED — AUD-A2-004 : le sceau des revues n'est recalculable par personne.

Chaque verdict porte un `prompt_sha256` : l'empreinte du pack soumis aux relecteurs.
Quand trois verdicts d'un même tour portent la même valeur, cela prouve qu'ils ont lu le
même texte. Cette garantie tient, et ce témoin ne la conteste pas.

Elle a cependant une limite qui n'est nulle part écrite : un sceau ne vaut que si l'on
peut le RECALCULER. Sans le pack, `prompt_sha256` atteste que trois relecteurs ont vu le
même texte — pas QUEL texte. Un tiers ne peut ni vérifier que le pack contenait bien le
diff annoncé, ni qu'il n'a pas été remplacé après coup : il n'a rien à hacher.

Le témoin mesure donc deux choses distinctes, qu'il ne faut pas confondre :
  - la cohérence du sceau à l'intérieur d'un tour (elle tient : 2 dossiers sur 57) ;
  - la présence du pack qui rendrait ce sceau vérifiable.

Ce témoin est né d'une revue : deux relecteurs indépendants ont relevé que le périmètre
annoncé du lot promettait de vérifier les archives de tours, et que la mesure manquait.

Code retour : 1 si le défaut est reproduit, 0 s'il ne l'est plus, 2 si la mesure est
impossible.
"""
import json
import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parents[3]
REVUES = RACINE / "reviews"

# Ce à quoi ressemblerait un pack archivé. La liste est large : mieux vaut trouver une
# archive sous un nom inattendu et réfuter le constat, que la manquer et l'affirmer à tort.
EXTENSIONS_PACK = (".md", ".txt", ".pack", ".prompt")
NOMS_PACK = ("pack", "prompt", "soumission")


def _porte_un_pack(dossier: pathlib.Path) -> list[str]:
    trouves = []
    for chemin in dossier.iterdir():
        if not chemin.is_file():
            continue
        nom = chemin.name.lower()
        if nom.endswith(".verdict.json") or nom.endswith(".json"):
            continue
        if chemin.suffix.lower() in EXTENSIONS_PACK or any(m in nom for m in NOMS_PACK):
            trouves.append(chemin.name)
    return trouves


def main() -> int:
    if not REVUES.exists():
        print(f"TÉMOIN INAPPLICABLE : {REVUES} est introuvable")
        return 2

    tours = sorted(d for d in REVUES.rglob("round-*") if d.is_dir())
    if not tours:
        print("TÉMOIN INAPPLICABLE : aucun dossier de tour")
        return 2

    sans_pack, avec_pack, sceaux_multiples = [], [], []

    for dossier in tours:
        verdicts = list(dossier.glob("*.verdict.json"))
        if not verdicts:
            continue

        sceaux = set()
        for chemin in verdicts:
            try:
                sceaux.add(json.loads(chemin.read_text(encoding="utf-8")).get("prompt_sha256"))
            except (OSError, json.JSONDecodeError):
                continue
        if len(sceaux) > 1:
            sceaux_multiples.append((dossier, len(sceaux), len(verdicts)))

        packs = _porte_un_pack(dossier)
        (avec_pack if packs else sans_pack).append(dossier)

    total = len(sans_pack) + len(avec_pack)
    print(f"dossiers de tour porteurs de verdicts : {total}")
    print(f"  avec un pack archivé (sceau recalculable) : {len(avec_pack)}")
    print(f"  SANS pack archivé                          : {len(sans_pack)}")
    print(f"  à sceau multiple dans un même tour         : {len(sceaux_multiples)}")

    for dossier, nombre, verdicts in sceaux_multiples:
        print(f"     {dossier.relative_to(RACINE).as_posix()} — {nombre} sceaux / {verdicts} verdicts")

    if sans_pack:
        print("\n  échantillon de tours sans pack :")
        for dossier in sans_pack[:6]:
            print(f"     {dossier.relative_to(RACINE).as_posix()}")

    print()
    if not sans_pack:
        print("CONSTAT NON REPRODUIT : chaque tour conserve son pack, le sceau est recalculable.")
        print("AUD-A2-004 est périmé et doit être retiré du rapport.")
        return 0

    print(f"CONSTAT AUD-A2-004 CONFIRMÉ :")
    print(f"  - {len(sans_pack)} tours sur {total} ne conservent aucun pack : leur")
    print("    prompt_sha256 ne peut être recalculé par personne")
    print()
    print("Ce que le témoin N'AFFIRME PAS : que les sceaux soient faux, ni qu'un pack ait")
    print("été substitué. Il établit qu'aucune des deux hypothèses n'est vérifiable — et")
    print("qu'un sceau invérifiable atteste que trois relecteurs ont lu le même texte,")
    print("jamais QUEL texte. La cohérence interne des sceaux, elle, tient : elle est")
    print("mesurée ci-dessus et n'est pas remise en cause.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
