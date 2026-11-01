"""Statut de certitude d'un fait lu chez un producteur : ce que M9 a le droit de présenter comme établi (Athéna).

Module pur, sans horloge ni import d'``opsys``. Une capture (M9.1) dit COMMENT une réponse est arrivée (acceptée,
complète, refusée…). Ce module dit CE QUE VAUT chaque fait qu'elle porte, d'après ce que le producteur lui-même déclare
dans sa réponse — jamais d'après un jugement de M9 :

* ``ETABLI`` — reçu d'un producteur, capture acceptée et complète ; ni vérité ni fraîcheur garanties au-delà de ce que
  la réponse déclare. Seul statut qu'on peut présenter comme certain ;
* ``ESSAI_NON_APPROUVE`` — le producteur dit lui-même que la valeur est une proposition ou n'est pas approuvée
  (pondérations du score de santé non validées par la direction, calendrier fiscal « à valider par le CPA »,
  couverture des taxes « partielle ») ;
* ``INDETERMINE`` — le producteur refuse de conclure (score indéterminé, mesure non calculable, échantillon
  insuffisant) : aucune valeur n'existe ;
* ``PERIME`` — le producteur dit que la valeur est plus vieille que sa fenêtre de fraîcheur ;
* ``PREVISION_PAR_INTERVALLE`` — une projection : jamais une certitude, toujours avec son intervalle ou ses réserves ;
* ``ABSENT`` / ``REFUSE`` / ``PARTIEL`` / ``CONTRADICTOIRE`` — l'état de la LECTURE elle-même.

Règle dure : seul ``ETABLI`` est « certain ». Un fait ``ESSAI_NON_APPROUVE``, ``INDETERMINE``, ``PERIME`` ou une
prévision n'est jamais rendu sans son statut, et une recommandation qui le cite comme certain est refusée
(``recommandation_gouvernee``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs
from . import dossier_strategique

ETABLI = "ETABLI"
ESSAI = "ESSAI_NON_APPROUVE"
INDETERMINE = "INDETERMINE"
PERIME = "PERIME"
PREVISION = "PREVISION_PAR_INTERVALLE"
ABSENT = "ABSENT"
REFUSE = "REFUSE"
PARTIEL = "PARTIEL"
CONTRADICTOIRE = "CONTRADICTOIRE"
STATUTS = (ETABLI, ESSAI, PREVISION, PERIME, INDETERMINE, PARTIEL, CONTRADICTOIRE, REFUSE, ABSENT)
# Du moins grave au plus grave : le statut d'un ensemble est le plus grave de ses membres.
_GRAVITE = {statut: rang for rang, statut in enumerate(STATUTS)}
MENTION_CPA = "À valider auprès d'un comptable (CPA) / professionnel qualifié"


def est_certain(statut: str) -> bool:
    """Seul ``ETABLI`` se présente comme certain."""
    return statut == ETABLI


def plus_grave(statuts: Sequence[str]) -> str:
    """Le statut le plus grave d'un ensemble ; ``ETABLI`` pour un ensemble vide est refusé (rien n'est établi sans
    fait)."""
    if not statuts:
        return ABSENT
    if any(s not in _GRAVITE for s in statuts):
        raise ValueError("REJ-CERTITUDE-STATUT : statut hors du vocabulaire fermé")
    return max(statuts, key=lambda s: _GRAVITE[s])


# ---------------------------------------------------------------------------------------------------- la lecture
def etat_lecture(captures_connues: Sequence[Mapping], lecture_id: str) -> dict:
    """État de la dernière capture connue d'une lecture : ``{certitude, capture, code, raison}``.

    ABSENT (aucune capture), REFUSE (la dernière est un refus ou une erreur du producteur — son code est conservé),
    CONTRADICTOIRE, PARTIEL, sinon ETABLI (la capture est utilisable ; la valeur de chaque fait se classe ensuite)."""
    siennes = [c for c in captures_connues if c["lecture_id"] == lecture_id]
    if not siennes:
        return {"certitude": ABSENT, "capture": None, "code": None, "raison": "aucune capture connue"}
    derniere = siennes[-1]
    if derniere["verdict"] != "ACCEPTEE":
        return {"certitude": REFUSE, "capture": derniere, "code": derniere["code"], "raison": "refus du producteur"}
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(captures_connues)}
    if (derniere["lecture_id"], derniere["arguments_sha256"]) in en_conflit:
        return {
            "certitude": CONTRADICTOIRE,
            "capture": derniere,
            "code": None,
            "raison": "deux réponses se contredisent",
        }
    if not derniere["complete"]:
        return {"certitude": PARTIEL, "capture": derniere, "code": None, "raison": derniere["raison_incomplete"]}
    return {"certitude": ETABLI, "capture": derniere, "code": None, "raison": None}


# ------------------------------------------------------------------------------------------------- chaque fait
_RANG = re.compile(r"\[(\d+)\]")


def _valeurs(page: object, chemin: str) -> list:
    return cs.extraire(page, chemin)


def _statut_mesure_m8(mesure: Mapping) -> str:
    fraicheur, statut = mesure.get("fraicheur"), mesure.get("statut")
    if statut != "calculee" or fraicheur in ("manquant", "inconnu"):
        return INDETERMINE
    if fraicheur == "perime":
        return PERIME
    return ETABLI  # a_jour, non_applicable (cumul de chantiers terminés, dit tel quel par le producteur)


def _statut_obligation_m5(obligation: Mapping) -> str:
    return {
        "DOCUMENTEE_A_VALIDER": ESSAI,
        "ECHEANCE_PASSEE_A_VERIFIER": ESSAI,
        "INCOMPLETE": INDETERMINE,
        "SOURCE_PERIMEE": PERIME,
    }.get(obligation.get("statut"), INDETERMINE)


def classer_faits(capture: Mapping) -> dict[str, str]:
    """``chemin aplati → statut`` pour les faits CITABLES d'une capture acceptée et complète, d'après les déclarations
    du
    producteur. Un chemin absent de la table est ``ETABLI`` (un fait reçu, rien de plus). Ne lève jamais pour une forme
    inattendue : un fait mal compris est rétrogradé en ``INDETERMINE``, jamais promu."""
    lecture_id = capture["lecture_id"]
    classes: dict[str, str] = {}
    for page in capture["pages"]:
        try:
            if lecture_id == "m8.synthese_direction":
                _classer_m8(page, classes)
            elif lecture_id == "m5.calendrier_obligations":
                _classer_m5_calendrier(page, classes)
            elif lecture_id in ("m2.prevision_pipeline",):
                _tout(page, "resultat.resultat", classes, PREVISION)
            elif lecture_id == "m2.analyse_pipeline":
                _classer_m2_analyse(page, classes)
            elif lecture_id == "m5.prevision_tresorerie":
                _classer_m5_tresorerie(page, classes)
        except (KeyError, TypeError, AttributeError):
            classes["*"] = INDETERMINE
    return classes


def _tout(page: object, racine: str, classes: dict, statut: str) -> None:
    classes[f"{racine}.*"] = statut


def _classer_m8(page: object, classes: dict) -> None:
    charge = page["resultat"]
    ponderations_validees = charge["sante"]["ponderations"]["validee"] is True
    classes["resultat.sante.score"] = ETABLI if ponderations_validees else ESSAI
    for rang in range(len(charge["sante"]["composantes"])):
        classes[f"resultat.sante.composantes[{rang}].score"] = ETABLI if ponderations_validees else ESSAI
    for rang, mesure in enumerate(charge["mesures"]):
        classes[f"resultat.mesures[{rang}].valeur"] = _statut_mesure_m8(mesure)


def _classer_m5_calendrier(page: object, classes: dict) -> None:
    charge = page["resultat"]["resultat"]
    racine = "resultat.resultat"
    for rang, obligation in enumerate(charge["obligations"]):
        statut = _statut_obligation_m5(obligation)
        for champ in ("montant", "montant_utilisable", "echeance"):
            classes[f"{racine}.obligations[{rang}].{champ}"] = statut
    taxes = charge["echeances_tps_tvq"]
    validation = taxes.get("validation_cpa") or {}
    for rang, echeance in enumerate(taxes.get("echeances") or []):
        annee = str(echeance.get("periode_fin", ""))[:4]
        valide = validation.get(annee) == "VALIDE"
        for champ in ("limite_paiement", "limite_production"):
            classes[f"{racine}.echeances_tps_tvq.echeances[{rang}].{champ}"] = ETABLI if valide else ESSAI
        nettes = echeance.get("taxes_nettes")
        if isinstance(nettes, Mapping):
            complete = valide and (nettes.get("couverture") or {}).get("statut") == "COMPLETE"
            classes[f"{racine}.echeances_tps_tvq.echeances[{rang}].taxes_nettes.a_remettre"] = (
                ETABLI if complete else ESSAI
            )


def _classer_m2_analyse(page: object, classes: dict) -> None:
    classes["resultat.resultat.valeur_ponderee.valeur_ponderee.*"] = PREVISION
    classes["resultat.resultat.valeur_ponderee.valeur_ponderee.intervalle.*"] = PREVISION


def _classer_m5_tresorerie(page: object, classes: dict) -> None:
    racine = "resultat.resultat"
    for champ in ("semaines", "premiere_semaine_en_deficit", "alerte", "fin_horizon"):
        classes[f"{racine}.{champ}"] = PREVISION


def statut_du_fait(classes: Mapping[str, str], chemin: str) -> str:
    """Statut d'un fait à ``chemin`` (aplati, ``a.b[2].c``) : la règle la plus précise de ``classes`` qui s'y applique ;
    ``*`` désigne tout ce qui est sous un préfixe ; sinon ``ETABLI``."""
    if chemin in classes:
        return classes[chemin]
    meilleur, longueur = None, -1
    for motif, statut in classes.items():
        if motif == "*":
            candidat = 0
        elif motif.endswith(".*") and (chemin == motif[:-2] or chemin.startswith(motif[:-1])):
            candidat = len(motif)
        else:
            continue
        if candidat > longueur:
            meilleur, longueur = statut, candidat
    return meilleur if meilleur is not None else ETABLI


def certitude_des_faits(captures: Sequence[Mapping]) -> dict[str, str]:
    """``adresse du fait → statut`` pour des captures déjà filtrées (acceptées, complètes), dans la forme exacte des
    adresses du dossier stratégique (``<lecture>#<rang>:p<page>.<chemin>``)."""
    resultat: dict[str, str] = {}
    for capture in captures:
        classes = classer_faits(capture)
        faits, _ = dossier_strategique.faits_citables([capture], max_faits=10**6)
        prefixe = f"{capture['lecture_id']}#{capture['index']}:p"
        for adresse in faits:
            reste = adresse[len(prefixe) :]
            chemin = reste.split(".", 1)[1] if "." in reste else reste
            resultat[adresse] = statut_du_fait(classes, chemin)
    return resultat
