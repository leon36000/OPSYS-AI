"""Comparaison de deux rapports du gabarit (régressions nommées) et rendu Markdown lisible."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from .corpus import CATEGORIES, RefusEvaluation

_LIBELLES = {
    "tache_metier": "Tâche métier",
    "appel_outil": "Appel d'outil attendu",
    "refus_attendu": "Refus attendu",
    "injection_consigne": "Injection de consigne",
    "francais_quebecois": "Français québécois",
    "mention_professionnel": "Mention CPA / professionnel",
    "honnetete_inconnu": "Honnêteté (inconnu plutôt qu'estimé)",
}


def _valider_rapport(rapport: Any, nom: str) -> Mapping[str, Any]:
    if (not isinstance(rapport, Mapping) or rapport.get("type") != "EVALUATION_GABARIT"
            or not isinstance(rapport.get("departements"), Mapping)
            or not all(isinstance(b, Mapping) and isinstance(b.get("cas"), Mapping)
                       for b in rapport["departements"].values())):
        raise RefusEvaluation("REJ-EVAL-RAPPORT-FORME", "rapport du gabarit attendu (type EVALUATION_GABARIT)", nom)
    return rapport


def comparer(precedent: Any, courant: Any) -> dict[str, Any]:
    """Régressions (réussi → échoué) et améliorations NOMMÉES par cas ; corpus et répondant changés signalés."""
    avant, apres = _valider_rapport(precedent, "precedent"), _valider_rapport(courant, "courant")
    regressions, ameliorations, nouveaux, retires, departements = [], [], [], [], {}
    for dep in sorted(set(avant["departements"]) | set(apres["departements"])):
        bloc_avant, bloc_apres = avant["departements"].get(dep), apres["departements"].get(dep)
        if bloc_avant is None or bloc_apres is None:
            departements[dep] = {"statut": "nouveau" if bloc_avant is None else "retire"}
            continue
        echecs_apres = {e["id"]: e for e in bloc_apres.get("echecs", ())}
        for ident in sorted(set(bloc_avant["cas"]) | set(bloc_apres["cas"])):
            cas_avant, cas_apres = bloc_avant["cas"].get(ident), bloc_apres["cas"].get(ident)
            if cas_avant is None:
                nouveaux.append({"departement": dep, "cas": ident})
            elif cas_apres is None:
                retires.append({"departement": dep, "cas": ident})
            elif cas_avant["reussi"] and not cas_apres["reussi"]:
                regressions.append({"departement": dep, "cas": ident, "categorie": cas_apres["categorie"],
                                    "gravite": cas_apres["gravite"],
                                    "ecarts": echecs_apres.get(ident, {}).get("ecarts", [])})
            elif not cas_avant["reussi"] and cas_apres["reussi"]:
                ameliorations.append({"departement": dep, "cas": ident, "categorie": cas_apres["categorie"]})
        departements[dep] = {
            "score_avant": bloc_avant["score"], "score_apres": bloc_apres["score"],
            "delta": str(Decimal(bloc_apres["score"]) - Decimal(bloc_avant["score"])),
            "qualifie_avant": bloc_avant["qualifie"], "qualifie_apres": bloc_apres["qualifie"],
            "corpus_change": bloc_avant["corpus"]["sha256"] != bloc_apres["corpus"]["sha256"],
        }
    return {
        "type": "COMPARAISON_EVALUATION",
        "corpus_change": avant["corpus"]["empreinte"] != apres["corpus"]["empreinte"],
        "repondant_change": avant["repondant"]["empreinte"] != apres["repondant"]["empreinte"],
        "regressions": regressions, "regressions_bloquantes": [r for r in regressions if r["gravite"] == "bloquante"],
        "ameliorations": ameliorations, "cas_nouveaux": nouveaux, "cas_retires": retires,
        "departements": departements,
    }


def _oui(valeur: bool) -> str:
    return "oui" if valeur else "**non**"


def _ligne_pack(pack: Mapping[str, Any] | None) -> list[str]:
    """Le pack sectoriel de la mesure et les cas écartés (d'un autre pack) : un score sans cela est trompeur."""
    if not pack:
        return []
    if pack.get("actif") is None:
        return ["- Pack sectoriel : aucun filtre (tous les cas du corpus)"]
    return [f"- Pack sectoriel actif : `{pack['actif']}` ; cas écartés (d'un autre pack) : {pack['total_ecartes']}"]


def markdown(rapport: Mapping[str, Any], comparaison: Mapping[str, Any] | None = None) -> str:
    rep, glob = rapport["repondant"], rapport["global"]
    lignes = [
        "# Rapport d'évaluation OPSYS (gabarit commun)",
        "",
        f"- Gabarit : `{rapport['version_gabarit']}` ; seuil de qualification : {rapport['seuil_qualification']} "
        "(et aucun cas bloquant échoué)",
        f"- Répondant : `{rep['nom']}` ({rep['type']}, modèle réel : {_oui(rapport['modele_reel'])}) — empreinte "
        f"`{rep['empreinte'][:16]}`",
        f"- Corpus : {len(rapport['corpus']['fichiers'])} fichier(s), empreinte "
        f"`{rapport['corpus']['empreinte'][:16]}`",
        "- Juge par modèle : aucun (vérifications déterministes seulement)",
        *_ligne_pack(rapport.get("pack")),
        "",
        f"**Global** : {glob['reussites']}/{glob['effectif']} cas réussis, score pondéré {glob['score']} ; "
        f"qualifiés : {', '.join(glob['departements_qualifies']) or 'aucun'} ; "
        f"non qualifiés : {', '.join(glob['departements_non_qualifies']) or 'aucun'}.",
        "",
        "| Département | Cas | Réussis | Score | Qualifié | Bloquants échoués | Sondes d'autorité tenues |",
        "|---|---|---|---|---|---|---|",
    ]
    for dep, bloc in rapport["departements"].items():
        sondes = bloc["autorite_depot"]
        lignes.append(f"| {dep} | {bloc['effectif']} | {bloc['reussites']} | {bloc['score']} | {_oui(bloc['qualifie'])}"
                      f" | {', '.join(bloc['echecs_critiques']) or '—'} | {sondes['tenues']}/{sondes['sondes']} |")
    lignes += ["", "## Par catégorie", "", "| Département | " + " | ".join(_LIBELLES[c] for c in CATEGORIES) + " |",
               "|---|" + "---|" * len(CATEGORIES)]
    for dep, bloc in rapport["departements"].items():
        cellules = [f"{bloc['par_categorie'][c]['reussites']}/{bloc['par_categorie'][c]['effectif']}"
                    for c in CATEGORIES]
        lignes.append(f"| {dep} | " + " | ".join(cellules) + " |")
    echecs = [(dep, e) for dep, bloc in rapport["departements"].items() for e in bloc["echecs"]]
    lignes += ["", "## Échecs", ""]
    if not echecs:
        lignes.append("Aucun.")
    for dep, echec in echecs:
        lignes.append(f"- `{echec['id']}` ({dep}, {echec['categorie']}, {echec['gravite']}) :")
        lignes += [f"  - {e['controle']} — {e['detail']}" for e in echec["ecarts"]]
    references = [(dep, r) for dep, bloc in rapport["departements"].items() for r in bloc.get("references", ())]
    if references:
        lignes += ["", "## Corpus existants référencés (exécutés par leur propre évaluateur)", ""]
        for dep, ref in references:
            resultat = "empreinte vérifiée, non exécuté"
            if ref["execute"]:
                resultat = (f"{ref['reussites']}/{ref['effectif']} (taux {ref['taux']}), rouges connus : "
                            f"{', '.join(ref['rouges']) or 'aucun'}")
            lignes.append(f"- {dep} `{ref['chemin']}` : {resultat}")
    if comparaison is not None:
        lignes += ["", "## Comparaison au rapport précédent", "",
                   f"- Corpus changé : {'oui' if comparaison['corpus_change'] else 'non'} ; répondant changé : "
                   f"{'oui' if comparaison['repondant_change'] else 'non'}",
                   f"- Régressions : {len(comparaison['regressions'])} (dont bloquantes : "
                   f"{len(comparaison['regressions_bloquantes'])}) ; améliorations : "
                   f"{len(comparaison['ameliorations'])}"]
        lignes += [f"  - régression `{r['cas']}` ({r['departement']}, {r['gravite']})"
                   for r in comparaison["regressions"]]
    lignes += ["", "## Limites", ""] + [f"- {limite}" for limite in rapport["limites"]]
    return "\n".join(lignes) + "\n"
