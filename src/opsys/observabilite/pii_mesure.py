"""Mesure du masquage sur le corpus fictif étiqueté : précision, rappel par catégorie, faux positifs, limites.

La mesure passe par le port (`MasqueurPII.masquer` et ses positions) : elle vaut donc pour n'importe quel masqueur
(motifs, Presidio, chaîne). Une détection est juste si elle a la bonne catégorie et recouvre la valeur attendue.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .corpus_pii import CORPUS, CasPII
from .pii import MasqueurPII


def _trouvees(masqueur: MasqueurPII, texte: str) -> list[tuple[str, int, int]]:
    return [(r.categorie, r.debut, r.fin) for r in masqueur.masquer(texte).remplacements]


def mesurer(masqueur: MasqueurPII, corpus: Sequence[CasPII] = CORPUS) -> dict[str, Any]:
    """Rapport de mesure. `precision` et `rappel` : None quand le dénominateur est nul (jamais inventé)."""
    par_cat: dict[str, dict[str, int]] = {}

    def cat(nom: str) -> dict[str, int]:
        return par_cat.setdefault(nom, {"vrais": 0, "faux_positifs": 0, "manques": 0})

    negatifs = negatifs_touches = 0
    limites_confirmees: list[dict[str, str]] = []
    limites_ameliorees: list[dict[str, str]] = []
    faux_positifs: list[dict[str, str]] = []
    fp_connus_confirmes: list[str] = []
    fp_connus_corriges: list[str] = []
    for cas in corpus:
        trouvees = _trouvees(masqueur, cas.texte)
        if cas.fp_connu:
            (fp_connus_confirmes if trouvees else fp_connus_corriges).append(cas.note)
            continue
        attendus = []
        for categorie, sous in cas.attendus:
            debut = cas.texte.find(sous)
            if debut < 0:
                raise ValueError(f"corpus incohérent : {sous!r} absent de {cas.texte!r}")
            attendus.append((categorie, debut, debut + len(sous)))
        utilisees: set[int] = set()
        manques = []
        for categorie, debut, fin in attendus:
            index = next((i for i, (c, d, f) in enumerate(trouvees)
                          if i not in utilisees and c == categorie and d < fin and f > debut), None)
            if index is None:
                manques.append(categorie)
            else:
                utilisees.add(index)
        if cas.limite:
            fiche = {"note": cas.note, "categorie": cas.attendus[0][0]}
            (limites_ameliorees if not manques else limites_confirmees).append(fiche)
            continue
        for categorie, _debut, _fin in attendus:
            cat(categorie)["manques" if categorie in manques else "vrais"] += 1
            if categorie in manques:
                manques.remove(categorie)
        for i, (categorie, debut, fin) in enumerate(trouvees):
            if i not in utilisees:
                cat(categorie)["faux_positifs"] += 1
                faux_positifs.append({"categorie": categorie, "extrait": cas.texte[max(0, debut - 12):fin + 12]})
        if not cas.attendus:
            negatifs += 1
            negatifs_touches += bool(trouvees)
    rapport: dict[str, Any] = {"masqueur": masqueur.identite, "categories": {}, "negatifs": negatifs,
                               "negatifs_touches": negatifs_touches,
                               "taux_faux_positifs_negatifs": (negatifs_touches / negatifs) if negatifs else None,
                               "faux_positifs": faux_positifs, "faux_positifs_connus_confirmes": fp_connus_confirmes,
                               "faux_positifs_connus_corriges": fp_connus_corriges,
                               "limites_confirmees": limites_confirmees,
                               "limites_ameliorees": limites_ameliorees}
    vrais_total = fp_total = manques_total = 0
    for nom, c in sorted(par_cat.items()):
        trouve, attendu = c["vrais"] + c["faux_positifs"], c["vrais"] + c["manques"]
        rapport["categories"][nom] = {**c, "precision": c["vrais"] / trouve if trouve else None,
                                      "rappel": c["vrais"] / attendu if attendu else None}
        vrais_total += c["vrais"]
        fp_total += c["faux_positifs"]
        manques_total += c["manques"]
    rapport["global"] = {"vrais": vrais_total, "faux_positifs": fp_total, "manques": manques_total,
                         "precision": vrais_total / (vrais_total + fp_total) if vrais_total + fp_total else None,
                         "rappel": vrais_total / (vrais_total + manques_total) if vrais_total + manques_total else None}
    return rapport
