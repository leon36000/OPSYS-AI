"""La boucle « décision → résultat mesuré → leçon » d'Athéna : une mémoire stratégique qui ne conclut jamais seule.

Module pur, sans horloge ni import d'``opsys``. Un registre chaîné et append-only (``opsys.m9.boucle_decisions/v1``)
tient quatre sortes d'entrées :

* ``DECISION`` — la décision de la DIRECTION (son énoncé, signé par l'approbation humaine qui l'enregistre) et ce
  qu'elle attend, en SENS seulement (hausse, baisse, stable) sur des mesures du catalogue de M8. La base de comparaison
  est la dernière lecture ÉTABLIE connue à l'instant de la décision ; si elle n'existe pas, la base est dite inconnue —
  jamais reconstituée ;
* ``RESULTAT`` — la comparaison, FAITE PAR LE CODE, entre la base et la dernière lecture établie postérieure : le sens
  observé de chaque mesure (deux textes décimaux comparés, aucune différence calculée) et sa concordance avec l'attendu.
  Une mesure périmée, non calculable, de fraîcheur inconnue, de définition changée ou sans lecture postérieure est
  NON_MESURABLE, avec la raison : jamais une conclusion tirée d'une valeur qui n'en est pas une ;
* ``LECON`` — une PROPOSITION de leçon (statut ``PROPOSEE_NON_VALIDEE``) dont le texte est un gabarit rempli de faits :
  elle n'établit aucune cause. Elle ne devient une leçon que par ``VALIDATION_LECON``, geste humain ;
* ``VALIDATION_LECON`` — la validation ou le rejet motivé de la leçon par la direction.

Rien n'est appliqué : une leçon validée est PRÉPARÉE pour la mémoire de M10 (arguments exacts d'une source de
connaissance interne), jamais écrite ici. Les entrées deviennent des événements ``m9.fait_strategique`` (une entrée =
un événement, identifiant lié à son empreinte) pour la mémoire des faits de M10.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from . import capture_strategique as cs
from . import certitude as ct
from . import chainage

VERSION = "2026-11-01.1"
SCHEMA = "opsys.m9.boucle_decisions/v1"
TYPES = frozenset({"DECISION", "RESULTAT", "LECON", "VALIDATION_LECON"})
LECTURE_MESURES = "m8.synthese_direction"
SENS = ("hausse", "baisse", "stable")
CONCORDANCES = ("CONCORDE", "NE_CONCORDE_PAS", "NON_MESURABLE")
GLOBALES = ("CONCORDE", "NE_CONCORDE_PAS", "MIXTE", "NON_MESURABLE")
STATUT_LECON = "PROPOSEE_NON_VALIDEE"
MAX_ENONCE = 600
MAX_ATTENDUS = 8
MENTION = (
    "Les leçons ne sont ni des causes ni des avis comptables ; "
    "À valider auprès d'un comptable (CPA) / professionnel qualifié."
)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}")
_METRIQUE = re.compile(r"m8_[a-z0-9_]{1,76}")
_FRAIS = ("a_jour", "non_applicable")


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"REJ-BOUCLE-{code} : {detail}")


def valider_chaine(chaine: Sequence[Mapping]) -> tuple[bool, str]:
    return chainage.valider(SCHEMA, TYPES, chaine)


def _texte(valeur: object, maximum: int) -> bool:
    return type(valeur) is str and bool(valeur.strip()) and len(valeur) <= maximum


def _decimal(valeur: object) -> Decimal | None:
    if type(valeur) is not str:
        return None
    try:
        nombre = Decimal(valeur)
    except InvalidOperation:
        return None
    return nombre if nombre.is_finite() else None


# ------------------------------------------------------------------------------------------ lecture des captures
def _lecture_etablie(captures: Sequence[Mapping], connaissance: str) -> Mapping | None:
    """La dernière capture de la lecture des mesures, ÉTABLIE (acceptée, complète, sans contradiction) à
    ``connaissance``."""
    connues = cs.connues_a(captures, connaissance)
    etat = ct.etat_lecture(connues, LECTURE_MESURES)
    return etat["capture"] if etat["certitude"] == ct.ETABLI else None


def _mesures(capture: Mapping) -> dict[str, dict]:
    page = capture["pages"][0]["resultat"]
    return {m["metric_id"]: m for m in page["mesures"]}


def _reference(capture: Mapping, metric_id: str) -> dict:
    """Ce que M9 retient d'une mesure à un instant : valeur, fraîcheur, statut, définition, adresse du fait."""
    mesure = _mesures(capture).get(metric_id)
    if mesure is None:
        return {"presente": False}
    rang = [m["metric_id"] for m in capture["pages"][0]["resultat"]["mesures"]].index(metric_id)
    return {
        "presente": True,
        "valeur": mesure["valeur"],
        "fraicheur": mesure["fraicheur"],
        "statut": mesure["statut"],
        "version_definition": mesure["version_definition"],
        "adresse": f"{capture['lecture_id']}#{capture['index']}:p0.resultat.mesures[{rang}].valeur",
    }


# ------------------------------------------------------------------------------------------ déclaration
def declarer(
    chaine: Sequence[Mapping],
    *,
    decision_id: str,
    enonce: str,
    attendus: object,
    captures: Sequence[Mapping],
    decide_par: str,
    decide_role: str,
    decide_le: str,
    suivi_id: str | None = None,
    suivis_connus: Sequence[str] | None = None,
) -> dict:
    """Le maillon ``DECISION`` à ajouter. Refuse un doublon, un énoncé vide, un attendu hors forme ou une référence de
    suivi
    inconnue. La base de comparaison vient des captures connues à ``decide_le`` (jamais d'un argument)."""
    if type(decision_id) is not str or not _ID.fullmatch(decision_id):
        raise _refus("IDENTIFIANT", "identifiant de décision sobre requis")
    if any(e["type"] == "DECISION" and e["decision_id"] == decision_id for e in chaine):
        raise _refus("DOUBLON", "cette décision est déjà consignée")
    if not _texte(enonce, MAX_ENONCE):
        raise _refus("ENONCE", f"énoncé non vide de {MAX_ENONCE} caractères au plus requis")
    if cs.instant(decide_le) is None:
        raise _refus("TEMPS", "instant de décision avec fuseau explicite requis")
    if not _texte(decide_par, 128) or decide_role not in ("admin", "nathan_owner"):
        raise _refus("SIGNATAIRE", "décision signée par un admin ou le propriétaire")
    if suivi_id is not None and (suivis_connus is None or suivi_id not in suivis_connus):
        raise _refus("SUIVI-INCONNU", "le suivi référencé n'existe pas au registre des suivis")
    if type(attendus) is not list or not 1 <= len(attendus) <= MAX_ATTENDUS:
        raise _refus("ATTENDUS", f"1 à {MAX_ATTENDUS} attendus {{metric_id, sens, hypothese}} requis")
    base = _lecture_etablie(captures, decide_le)
    vus: set[str] = set()
    corps_attendus = []
    for brut in attendus:
        if not isinstance(brut, Mapping) or set(brut) != {"metric_id", "sens", "hypothese"}:
            raise _refus("ATTENDUS", "chaque attendu = {metric_id, sens, hypothese}")
        if type(brut["metric_id"]) is not str or not _METRIQUE.fullmatch(brut["metric_id"]) or brut["metric_id"] in vus:
            raise _refus("ATTENDUS", "mesure M8 distincte requise (m8_…)")
        if brut["sens"] not in SENS or not _texte(brut["hypothese"], 300):
            raise _refus("ATTENDUS", f"sens parmi {list(SENS)} et hypothèse déclarée (300 caractères au plus)")
        vus.add(brut["metric_id"])
        reference = _reference(base, brut["metric_id"]) if base is not None else {"presente": False}
        corps_attendus.append(
            {"metric_id": brut["metric_id"], "sens": brut["sens"], "hypothese": brut["hypothese"], "base": reference}
        )
    corps = {
        "type": "DECISION",
        "decision_id": decision_id,
        "enonce": enonce,
        "attendus": corps_attendus,
        "suivi_id": suivi_id,
        "decide_par": decide_par,
        "decide_role": decide_role,
        "decide_le": decide_le,
        "capture_de_base": None
        if base is None
        else {"index": base["index"], "hash_maillon": base["hash_maillon"], "recu_a": base["recu_a"]},
    }
    return chainage.suivant(SCHEMA, chaine, corps)


# ------------------------------------------------------------------------------------------ projection
def _decision(chaine: Sequence[Mapping], decision_id: str) -> Mapping:
    trouvees = [e for e in chaine if e["type"] == "DECISION" and e["decision_id"] == decision_id]
    if len(trouvees) != 1:
        raise _refus("INCONNUE", "décision absente de la boucle")
    return trouvees[0]


def etat(chaine: Sequence[Mapping], decision_id: str) -> dict:
    """État d'une décision : ``declaree`` → ``mesuree`` → ``lecon_proposee`` → ``lecon_validee`` ou
    ``lecon_rejetee``."""
    decision = _decision(chaine, decision_id)
    resultats = [e for e in chaine if e["type"] == "RESULTAT" and e["decision_id"] == decision_id]
    lecons = [e for e in chaine if e["type"] == "LECON" and e["decision_id"] == decision_id]
    derniere = lecons[-1] if lecons else None
    validation = None
    if derniere is not None:
        validations = [e for e in chaine if e["type"] == "VALIDATION_LECON" and e["lecon_id"] == derniere["lecon_id"]]
        validation = validations[-1] if validations else None
    if validation is not None:
        statut = "lecon_validee" if validation["statut"] == "validee" else "lecon_rejetee"
    elif derniere is not None:
        statut = "lecon_proposee"
    elif resultats:
        statut = "mesuree"
    else:
        statut = "declaree"
    return {
        "decision_id": decision_id,
        "etat": statut,
        "enonce": decision["enonce"],
        "decide_le": decision["decide_le"],
        "attendus": [{k: a[k] for k in ("metric_id", "sens")} for a in decision["attendus"]],
        "resultat": resultats[-1] if resultats else None,
        "lecon": None
        if derniere is None
        else {
            "lecon_id": derniere["lecon_id"],
            "statut": STATUT_LECON
            if validation is None
            else ("VALIDEE" if validation["statut"] == "validee" else "REJETEE"),
            "texte": derniere["texte"],
            "concordance": derniere["concordance"],
        },
    }


def decisions(chaine: Sequence[Mapping]) -> list[str]:
    return [e["decision_id"] for e in chaine if e["type"] == "DECISION"]


# ------------------------------------------------------------------------------------------ mesure du résultat
def _observer(attendu: Mapping, apres: Mapping | None, base_capture_hash: str | None, apres_hash: str | None) -> dict:
    base = attendu["base"]
    obs = {
        "metric_id": attendu["metric_id"],
        "sens_attendu": attendu["sens"],
        "sens_observe": None,
        "valeur_avant": base.get("valeur") if base.get("presente") else None,
        "valeur_apres": None,
        "fraicheur_avant": base.get("fraicheur") if base.get("presente") else None,
        "fraicheur_apres": None,
        "adresse_avant": base.get("adresse") if base.get("presente") else None,
        "adresse_apres": None,
        "concordance": "NON_MESURABLE",
        "raison": None,
    }
    if apres is None or apres_hash is None or apres_hash == base_capture_hash:
        obs["raison"] = "aucune_lecture_posterieure"
        return obs
    if not apres.get("presente"):
        obs["raison"] = "mesure_absente_de_la_lecture"
        return obs
    obs.update(valeur_apres=apres["valeur"], fraicheur_apres=apres["fraicheur"], adresse_apres=apres["adresse"])
    if not base.get("presente"):
        obs["raison"] = "base_inconnue"
    elif base["statut"] != "calculee" or apres["statut"] != "calculee":
        obs["raison"] = "mesure_non_calculable"
    elif base["fraicheur"] not in _FRAIS or apres["fraicheur"] not in _FRAIS:
        obs["raison"] = "mesure_perimee_ou_inconnue"
    elif base["version_definition"] != apres["version_definition"]:
        obs["raison"] = "definition_changee"
    else:
        avant, apres_val = _decimal(base["valeur"]), _decimal(apres["valeur"])
        if avant is None or apres_val is None:
            obs["raison"] = "valeur_illisible"
        else:
            sens = "hausse" if apres_val > avant else "baisse" if apres_val < avant else "stable"
            obs["sens_observe"] = sens
            obs["concordance"] = "CONCORDE" if sens == attendu["sens"] else "NE_CONCORDE_PAS"
    return obs


def concordance_globale(observations: Sequence[Mapping]) -> str:
    mesurables = [o["concordance"] for o in observations if o["concordance"] != "NON_MESURABLE"]
    if not mesurables:
        return "NON_MESURABLE"
    if len(mesurables) < len(observations):
        return "MIXTE"
    if all(c == "CONCORDE" for c in mesurables):
        return "CONCORDE"
    return "NE_CONCORDE_PAS" if all(c == "NE_CONCORDE_PAS" for c in mesurables) else "MIXTE"


def texte_lecon(enonce: str, observations: Sequence[Mapping], concordance: str) -> str:
    """Gabarit rempli de FAITS : aucune cause, aucune recommandation, aucun chiffre calculé."""
    morceaux = [f"Décision « {enonce[:140]} » : concordance {concordance}."]
    for o in observations:
        if o["concordance"] == "NON_MESURABLE":
            morceaux.append(f"{o['metric_id']} : non mesurable ({o['raison']}).")
        else:
            morceaux.append(
                f"{o['metric_id']} : attendu {o['sens_attendu']}, observé {o['sens_observe']} "
                f"({o['valeur_avant']} → {o['valeur_apres']})."
            )
    morceaux.append("Aucune cause n'est établie par cette comparaison ; à valider par la direction.")
    return " ".join(morceaux)


def mesurer(chaine: Sequence[Mapping], decision_id: str, *, captures: Sequence[Mapping], maintenant: str) -> list[dict]:
    """Les maillons (``RESULTAT`` puis éventuellement ``LECON``) à ajouter ; ``[]`` si ce résultat existe déjà (rejeu).

    La comparaison utilise la dernière lecture ÉTABLIE connue à ``maintenant``. Une leçon n'est proposée que si au moins
    une mesure est mesurable : « non mesurable » n'est pas une leçon."""
    if cs.instant(maintenant) is None:
        raise _refus("TEMPS", "instant de mesure avec fuseau explicite requis")
    decision = _decision(chaine, decision_id)
    if cs.instant(maintenant) < cs.instant(decision["decide_le"]):  # type: ignore[operator]
        raise _refus("TEMPS", "la mesure ne peut pas précéder la décision")
    apres = _lecture_etablie(captures, maintenant)
    base_hash = (decision["capture_de_base"] or {}).get("hash_maillon")
    observations = [
        _observer(
            a,
            _reference(apres, a["metric_id"]) if apres is not None else None,
            base_hash,
            None if apres is None else apres["hash_maillon"],
        )
        for a in decision["attendus"]
    ]
    concordance = concordance_globale(observations)
    resultat = {
        "type": "RESULTAT",
        "decision_id": decision_id,
        "mesure_le": maintenant,
        "capture_apres": None
        if apres is None
        else {"index": apres["index"], "hash_maillon": apres["hash_maillon"], "recu_a": apres["recu_a"]},
        "observations": observations,
        "concordance": concordance,
    }
    deja = [e for e in chaine if e["type"] == "RESULTAT" and e["decision_id"] == decision_id]
    if deja and all(deja[-1][k] == resultat[k] for k in ("capture_apres", "observations", "concordance")):
        return []
    maillon_resultat = chainage.suivant(SCHEMA, chaine, resultat)
    ajoutes = [maillon_resultat]
    if concordance != "NON_MESURABLE":
        texte = texte_lecon(decision["enonce"], observations, concordance)
        lecon_id = "lecon-" + cs.empreinte({"decision": decision_id, "resultat": maillon_resultat["hash_maillon"]})[:24]
        ajoutes.append(
            chainage.suivant(
                SCHEMA,
                [*chaine, maillon_resultat],
                {
                    "type": "LECON",
                    "decision_id": decision_id,
                    "lecon_id": lecon_id,
                    "statut": STATUT_LECON,
                    "concordance": concordance,
                    "texte": texte,
                    "resultat_hash": maillon_resultat["hash_maillon"],
                    "mention": MENTION,
                },
            )
        )
    return ajoutes


def valider_lecon(
    chaine: Sequence[Mapping], lecon_id: str, statut: str, *, decide_par: str, decide_role: str, decide_le: str,
    motif: str | None = None,
) -> dict:  # fmt: skip
    """Le maillon ``VALIDATION_LECON`` : la direction valide ou rejette (motif obligatoire) une leçon encore
    proposée."""
    lecons = [e for e in chaine if e["type"] == "LECON" and e["lecon_id"] == lecon_id]
    if len(lecons) != 1:
        raise _refus("LECON-INCONNUE", "leçon absente de la boucle")
    if statut not in ("validee", "rejetee"):
        raise _refus("STATUT", "validee ou rejetee")
    if any(e["type"] == "VALIDATION_LECON" and e["lecon_id"] == lecon_id for e in chaine):
        raise _refus("DEJA-DECIDEE", "cette leçon a déjà été décidée par la direction")
    if cs.instant(decide_le) is None or not _texte(decide_par, 128) or decide_role not in ("admin", "nathan_owner"):
        raise _refus("SIGNATAIRE", "décision signée par un admin ou le propriétaire, à un instant avec fuseau")
    if statut == "rejetee" and not _texte(motif, 300):
        raise _refus("MOTIF", "un rejet est motivé (300 caractères au plus)")
    if motif is not None and not _texte(motif, 300):
        raise _refus("MOTIF", "motif de 300 caractères au plus")
    return chainage.suivant(
        SCHEMA,
        chaine,
        {
            "type": "VALIDATION_LECON",
            "decision_id": lecons[0]["decision_id"],
            "lecon_id": lecon_id,
            "statut": statut,
            "motif": motif,
            "decide_par": decide_par,
            "decide_role": decide_role,
            "decide_le": decide_le,
        },
    )


# ------------------------------------------------------------------------------------------ vers M10
def source_connaissance(chaine: Sequence[Mapping], lecon_id: str) -> dict:
    """Arguments EXACTS de ``m10_ingerer_source_connaissance`` pour une leçon VALIDÉE par la direction (rien d'autre
    n'est
    préparé). Rien n'est écrit : l'ingestion (brouillon, N2) et la publication appartiennent à M10 et à son cycle de
    revue."""
    lecons = [e for e in chaine if e["type"] == "LECON" and e["lecon_id"] == lecon_id]
    validations = [e for e in chaine if e["type"] == "VALIDATION_LECON" and e["lecon_id"] == lecon_id]
    if len(lecons) != 1 or not validations or validations[-1]["statut"] != "validee":
        raise _refus("LECON-NON-VALIDEE", "seule une leçon validée par la direction est préparée pour la mémoire")
    lecon = lecons[0]
    return {
        "departement": "m09-strategic-intelligence",
        "cle": lecon_id,
        "titre": f"Leçon de la décision {lecon['decision_id']}"[:200],
        "domaine": "general",
        "type_source": "texte",
        "editeur": "Direction (M9, leçon validée par la direction)",
        "type_autorite": "interne",
        "reference": f"m9://boucle_decisions/{lecon['decision_id']}/{lecon_id}",
        "licence_reutilisation": "interne",
        "contenu": f"{lecon['texte']}\n\n{MENTION}",
    }


def evenement_fait(entree: Mapping, chaine: Sequence[Mapping]) -> dict:
    """La charge ``m9.fait_strategique`` d'UNE entrée de la boucle : identifiant lié à l'empreinte du maillon (republier
    la même entrée rejoue la première enveloppe). Toutes les clés sont requises, nulles quand elles ne s'appliquent pas.
    Aucun nom de personne : seulement le rôle du signataire."""
    type_ = entree["type"]
    charge: dict = {
        "evenement_id": "m9-strat-" + entree["hash_maillon"],
        "genre": {
            "DECISION": "decision",
            "RESULTAT": "resultat_observe",
            "LECON": "lecon",
            "VALIDATION_LECON": "lecon",
        }[type_],
        "decision_id": entree["decision_id"],
        "lecon_id": entree.get("lecon_id"),
        "statut": None,
        "texte": None,
        "attendus": [],
        "observations": [],
        "concordance": None,
        "decide_role": entree.get("decide_role"),
        "enregistre_le": entree.get("decide_le") or entree.get("mesure_le"),
        "source_empreinte": entree["hash_maillon"],
        "mention": MENTION,
    }
    if type_ == "DECISION":
        charge.update(
            statut="declaree_par_la_direction",
            texte=entree["enonce"],
            attendus=[{"metric_id": a["metric_id"], "sens": a["sens"]} for a in entree["attendus"]],
        )
    elif type_ == "RESULTAT":
        charge.update(
            statut="observe_par_mesure",
            concordance=entree["concordance"],
            observations=[
                {
                    k: o[k]
                    for k in (
                        "metric_id",
                        "sens_attendu",
                        "sens_observe",
                        "valeur_avant",
                        "valeur_apres",
                        "concordance",
                    )
                }
                for o in entree["observations"]
            ],
        )
    elif type_ == "LECON":
        resultat = next(e for e in chaine if e["hash_maillon"] == entree["resultat_hash"])
        charge.update(
            statut="proposee_non_validee", texte=entree["texte"], concordance=entree["concordance"],
            enregistre_le=resultat["mesure_le"],
        )  # fmt: skip
    else:
        lecon = next(e for e in chaine if e["type"] == "LECON" and e["lecon_id"] == entree["lecon_id"])
        charge.update(
            statut="validee_par_la_direction" if entree["statut"] == "validee" else "rejetee_par_la_direction",
            texte=lecon["texte"],
            concordance=lecon["concordance"],
        )
    return charge
