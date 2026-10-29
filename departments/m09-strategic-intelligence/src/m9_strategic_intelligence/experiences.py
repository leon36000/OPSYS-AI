"""Expériences et ROI M9.18 : mesurer une action avec les chiffres des propriétaires, sans fabriquer ni confondre.

Module pur. Une expérience (événement chaîné ``EXPERIENCE``, versionné) déclare une hypothèse, son DESIGN
(``ALEATOIRE`` | ``GROUPE_TEMOIN`` | ``AVANT_APRES`` | ``SANS_REFERENCE``), ses groupes et des MESURES : chacune cite un
fait
du dossier (adresse ``<lecture>#<rang>:p<page>.<chemin>``), son rôle (résultat de référence, résultat exposé, coût,
effectif) et
son unité. L'évaluation relit les valeurs dans les dernières captures complètes ; ``RESULTAT`` en garde l'empreinte des
entrées,
donc une source corrigée produit un nouveau résultat sans effacer l'ancien.

* GAIN MESURÉ = résultat exposé − résultat de référence (Decimal, même unité) ; aucune extrapolation ;
* ROI = (gain − coût) / coût, seulement si gain ET coût sont mesurés, en CAD, et coût > 0 ; sinon ``ROI_NON_CALCULABLE``
avec
  la liste de ce qui manque (jamais zéro, jamais un défaut) ;
* ATTRIBUTION et CAUSALITÉ sont distinguées : seul un design ``ALEATOIRE`` déclaré rend la causalité plausible ; tout
autre
  design reste une association. L'effectif absent est dit ; aucune incertitude chiffrée n'est produite ;
* les contre-exemples déclarés par la personne sont comptés et rendus ; un gain négatif en est un de plus ;
* chaque expérience porte son CADRE de gouvernance, obligatoire : plafond de budget (CAD), durée en jours, limite de
  risque, porteur et plan de retour. Le coût mesuré est comparé au plafond (RESPECTE, DEPASSE ou INCONNU) ; un plafond
  dépassé est une lacune nommée. Une ancienne définition sans cadre reste lisible : ``CADRE_NON_DECLARE``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from . import capture_strategique as cs
from . import chainage, criteres, plans

SCHEMA = "m9.experiences.v1"
TYPES = frozenset({"EXPERIENCE", "RESULTAT"})
DESIGNS = frozenset({"ALEATOIRE", "GROUPE_TEMOIN", "AVANT_APRES", "SANS_REFERENCE"})
ROLES = frozenset({"reference", "expose", "cout", "effectif"})
DEVISE = "CAD"
MAX_MESURES = 16
_ID = re.compile(r"[a-z0-9][a-z0-9_.\-]{0,63}")
_CADRE = ("plafond_budget_cad", "duree_jours", "limite_risque", "porteur", "plan_retour")
_CHAMPS = frozenset(
    {"experience_id", "hypothese", "design", "exposition", "reference", "mesures", "contre_exemples", *_CADRE}
)
_OBLIGATOIRES = frozenset({"experience_id", "hypothese", "design", "mesures", *_CADRE})
_PLAFOND = re.compile(r"\d{1,12}(\.\d{1,2})?")
_LIMITES = (
    "Valeurs lues chez leurs propriétaires ; M9 ne mesure rien lui-même et ne chiffre aucune incertitude.",
    "Un ROI est une association mesurée, pas une preuve de cause, sauf design aléatoire déclaré (non vérifié par M9).",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def valider_chaine(chaine: Sequence[Mapping]) -> tuple[bool, str]:
    return chainage.valider(SCHEMA, TYPES, chaine)


def _mesure(brute: object, faits: Mapping[str, str]) -> dict:
    if not isinstance(brute, Mapping) or set(brute) != {"id", "role", "ref", "unite"}:
        raise _refus("REJ-EXPERIENCE-MESURE", "mesure {id, role, ref, unite} requise")
    if type(brute["id"]) is not str or not _ID.fullmatch(brute["id"]) or brute["role"] not in ROLES:
        raise _refus("REJ-EXPERIENCE-MESURE", f"identifiant sobre et rôle parmi {sorted(ROLES)} requis")
    if type(brute["unite"]) is not str or not 0 < len(brute["unite"]) <= 20:
        raise _refus("REJ-EXPERIENCE-MESURE", "unité déclarée requise (non vérifiée par M9)")
    ref = brute["ref"]
    if type(ref) is not str or not plans.ADRESSE.fullmatch(ref) or ref not in faits:
        raise _refus("REJ-EXPERIENCE-SOURCE", "ref : adresse absente des faits citables du dossier")
    return {"id": brute["id"], "role": brute["role"], "ref": ref, "unite": brute["unite"], "valeur_deposee": faits[ref]}


def _cadre(experience: Mapping) -> dict:
    """Cadre de gouvernance obligatoire : plafond (CAD, 0 = aucune dépense), durée, risque, porteur, retour."""
    plafond = experience["plafond_budget_cad"]
    if type(plafond) is not str or not _PLAFOND.fullmatch(plafond):
        raise _refus(
            "REJ-EXPERIENCE-CADRE", 'plafond_budget_cad : montant décimal textuel en CAD requis (ex. "0", "250.00")'
        )
    duree = experience["duree_jours"]
    if type(duree) is not int or not 1 <= duree <= 365:
        raise _refus("REJ-EXPERIENCE-CADRE", "duree_jours : entier de 1 à 365 requis")
    for nom in ("limite_risque", "plan_retour"):
        texte = experience[nom]
        if type(texte) is not str or not texte.strip() or len(texte) > 300:
            raise _refus("REJ-EXPERIENCE-CADRE", f"{nom} : texte non vide de 300 caractères au plus requis")
    porteur = experience["porteur"]
    if type(porteur) is not str or not _ID.fullmatch(porteur):
        raise _refus("REJ-EXPERIENCE-CADRE", "porteur : identifiant sobre requis")
    return {nom: experience[nom] for nom in _CADRE}


def definir(
    chaine: Sequence[Mapping],
    experience: Mapping,
    faits: Mapping[str, str],
    *,
    recu_a: str,
    par: str,
    motif_revision: str | None = None,
) -> dict:
    if not isinstance(experience, Mapping) or not _OBLIGATOIRES <= set(experience) <= _CHAMPS:
        raise _refus(
            "REJ-EXPERIENCE-CHAMP", f"expérience {sorted(_CHAMPS)} requise dont le cadre {sorted(_CADRE)} obligatoire"
        )
    exp_id = experience["experience_id"]
    if type(exp_id) is not str or not _ID.fullmatch(exp_id):
        raise _refus("REJ-EXPERIENCE-CHAMP", "identifiant minuscule sobre requis")
    if (
        type(experience["hypothese"]) is not str
        or not experience["hypothese"].strip()
        or len(experience["hypothese"]) > 400
    ):
        raise _refus("REJ-EXPERIENCE-CHAMP", "hypothèse bornée requise")
    if experience["design"] not in DESIGNS:
        raise _refus("REJ-EXPERIENCE-CHAMP", f"design parmi {sorted(DESIGNS)}")
    cadre = _cadre(experience)
    mesures_brutes = experience["mesures"]
    if type(mesures_brutes) is not list or not 1 <= len(mesures_brutes) <= MAX_MESURES:
        raise _refus("REJ-EXPERIENCE-MESURE", f"1 à {MAX_MESURES} mesures requises")
    mesures = [_mesure(m, faits) for m in mesures_brutes]
    if len({m["id"] for m in mesures}) != len(mesures):
        raise _refus("REJ-EXPERIENCE-MESURE", "identifiants de mesures distincts requis")
    for nom in ("exposition", "reference"):
        texte = experience.get(nom)
        if texte is not None and (type(texte) is not str or len(texte) > 300):
            raise _refus("REJ-EXPERIENCE-CHAMP", f"{nom} : texte borné ou absent")
    contre = experience.get("contre_exemples", [])
    if (
        type(contre) is not list
        or len(contre) > 12
        or any(type(x) is not str or not x.strip() or len(x) > 300 for x in contre)
    ):
        raise _refus("REJ-EXPERIENCE-CHAMP", "contre_exemples : liste bornée de textes")
    if cs.instant(recu_a) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")
    precedentes = [e for e in chaine if e["type"] == "EXPERIENCE" and e["experience_id"] == exp_id]
    version = len(precedentes) + 1
    if version > 1 and (type(motif_revision) is not str or not motif_revision.strip() or len(motif_revision) > 300):
        raise _refus("REJ-EXPERIENCE-REVISION", "motif de révision borné requis")
    if version == 1 and motif_revision is not None:
        raise _refus("REJ-EXPERIENCE-REVISION", "un premier dépôt n'a pas de motif de révision")
    corps = {
        "hypothese": experience["hypothese"],
        "design": experience["design"],
        "exposition": experience.get("exposition"),
        "reference": experience.get("reference"),
        "mesures": mesures,
        "contre_exemples": list(contre),
        **cadre,
    }
    if precedentes and precedentes[-1]["definition"] == corps:
        raise _refus("REJ-EXPERIENCE-REVISION", "aucun changement : une révision identique n'ajoute rien")
    return chainage.suivant(
        SCHEMA,
        chaine,
        {
            "type": "EXPERIENCE",
            "experience_id": exp_id,
            "version": version,
            "definition": corps,
            "motif_revision": motif_revision,
            "recu_a": recu_a,
            "par": par,
        },
    )


def _lire(mesure: Mapping, captures: Sequence[Mapping], en_conflit: set) -> dict:
    """Valeur COURANTE d'une mesure, relue dans la dernière capture complète de sa lecture."""
    parties = plans.ADRESSE.fullmatch(mesure["ref"])
    if parties is None:
        return {"id": mesure["id"], "statut": "ADRESSE_INVALIDE", "valeur": None}
    utilisables = [
        c
        for c in captures
        if c["lecture_id"] == parties["lecture"]
        and c["verdict"] == "ACCEPTEE"
        and c["complete"]
        and (c["lecture_id"], c["arguments_sha256"]) not in en_conflit
    ]
    if not utilisables:
        return {"id": mesure["id"], "statut": "LECTURE_INDISPONIBLE", "valeur": None}
    capture = utilisables[-1]
    page = int(parties["page"])
    brute = plans.valeur_a(capture["pages"][page], parties["chemin"]) if page < len(capture["pages"]) else None
    if brute is None:
        return {"id": mesure["id"], "statut": "VALEUR_ABSENTE", "valeur": None, "capture": capture["index"]}
    return {
        "id": mesure["id"],
        "statut": "LUE",
        "valeur": criteres.texte(brute),
        "capture": capture["index"],
        "hash": capture["hash_maillon"],
        "change_depuis_le_depot": criteres.texte(brute) != mesure["valeur_deposee"],
    }


def _decimal(texte: str | None) -> Decimal | None:
    try:
        return Decimal(texte) if texte is not None else None
    except InvalidOperation:
        return None


def evaluer(definition: Mapping, captures: Sequence[Mapping], *, connaissance: str) -> dict:
    """Résultat courant d'une définition : valeurs lues, gain mesuré, ROI ou ce qui manque, causalité, lacunes."""
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    lues = {m["id"]: _lire(m, connues, en_conflit) for m in definition["mesures"]}
    par_role: dict[str, list[dict]] = {}
    for m in definition["mesures"]:
        par_role.setdefault(m["role"], []).append(m)
    manques: list[str] = []

    def valeur_unique(role: str) -> tuple[Decimal | None, str | None]:
        mesures = par_role.get(role, [])
        if len(mesures) != 1:
            manques.append(f"{role} : exactement une mesure requise ({len(mesures)} déclarée(s))")
            return None, None
        m = mesures[0]
        lue = lues[m["id"]]
        nombre = _decimal(lue["valeur"])
        if lue["statut"] != "LUE" or nombre is None:
            manques.append(
                f"{role} ({m['id']}) : {lue['statut'] if lue['statut'] != 'LUE' else 'valeur non numérique'}"
            )
            return None, None
        return nombre, m["unite"]

    gain = roi = None
    couts = par_role.get("cout", [])
    if definition["design"] == "SANS_REFERENCE":
        manques.append("design SANS_REFERENCE : aucune référence, aucun gain mesurable")
    else:
        expose, u_expose = valeur_unique("expose")
        reference, u_reference = valeur_unique("reference")
        if expose is not None and reference is not None:
            if u_expose != u_reference:
                manques.append(f"UNITE_DIVERGENTE : exposé {u_expose} contre référence {u_reference}")
            else:
                gain = expose - reference
    total_cout = Decimal(0)
    couts_ok = bool(couts)
    if not couts:
        manques.append("cout : aucune mesure de coût déclarée")
    for m in couts:
        lue = lues[m["id"]]
        nombre = _decimal(lue["valeur"])
        if lue["statut"] != "LUE" or nombre is None:
            manques.append(f"cout ({m['id']}) : {lue['statut'] if lue['statut'] != 'LUE' else 'valeur non numérique'}")
            couts_ok = False
        elif m["unite"] != DEVISE:
            manques.append(f"cout ({m['id']}) : unité {m['unite']} ≠ {DEVISE}")
            couts_ok = False
        else:
            total_cout += nombre
    if gain is not None and par_role.get("expose") and par_role["expose"][0]["unite"] != DEVISE:
        manques.append(f"gain : unité {par_role['expose'][0]['unite']} ≠ {DEVISE}, pas de ROI monétaire")
        gain_monetaire = False
    else:
        gain_monetaire = gain is not None
    if gain_monetaire and couts_ok and total_cout > 0 and gain is not None:
        roi = (gain - total_cout) / total_cout
    elif gain_monetaire and couts_ok and total_cout <= 0:
        manques.append("cout : total nul ou négatif, ROI indéfini")
    effectif = par_role.get("effectif", [])
    lacunes = []
    if not effectif or lues[effectif[0]["id"]]["statut"] != "LUE":
        lacunes.append("EFFECTIF_INCONNU")
    if definition["design"] != "ALEATOIRE":
        lacunes.append("DESIGN_NON_ALEATOIRE")
    if any(v.get("change_depuis_le_depot") for v in lues.values()):
        lacunes.append("SOURCE_CORRIGEE_DEPUIS_LE_DEPOT")
    contre = len(definition["contre_exemples"]) + (1 if gain is not None and gain < 0 else 0)
    plafond = _decimal(definition.get("plafond_budget_cad"))
    if plafond is None:
        budget = {"statut": "CADRE_NON_DECLARE", "plafond_budget_cad": None}
    elif couts_ok and couts:
        budget = {
            "statut": "RESPECTE" if total_cout <= plafond else "DEPASSE",
            "plafond_budget_cad": str(plafond),
            "cout_mesure_cad": str(total_cout),
        }
    else:
        budget = {"statut": "INCONNU", "plafond_budget_cad": str(plafond), "cout_mesure_cad": None}
    if budget["statut"] == "DEPASSE":
        lacunes.append("PLAFOND_BUDGET_DEPASSE")
    resultat = {
        "cadre": {nom: definition.get(nom) for nom in _CADRE},
        "budget": budget,
        "valeurs": lues,
        "gain_mesure": None if gain is None else str(gain),
        "roi": None if roi is None else str(roi.quantize(Decimal("0.0001"))),
        "statut_roi": "CALCULE" if roi is not None else "ROI_NON_CALCULABLE",
        "manques": manques,
        "inference": "CAUSALITE_PLAUSIBLE_SI_ALEATOIRE_DECLARE"
        if definition["design"] == "ALEATOIRE"
        else "ASSOCIATION_SEULEMENT",
        "lacunes": lacunes,
        "contre_exemples": {"declares": list(definition["contre_exemples"]), "total": contre},
        "incertitude": "NON_CHIFFREE",
    }
    resultat["entrees_hash"] = hashlib.sha256(
        json.dumps({k: (v.get("hash"), v.get("valeur")) for k, v in sorted(lues.items())}, sort_keys=True).encode()
    ).hexdigest()
    return resultat


def enregistrer_resultat(
    chaine: Sequence[Mapping], experience_id: str, resultat: Mapping, *, recu_a: str, par: str
) -> dict | None:
    """Maillon RESULTAT, ou ``None`` si les entrées sont identiques au dernier résultat connu (idempotent)."""
    versions = [e for e in chaine if e["type"] == "EXPERIENCE" and e["experience_id"] == experience_id]
    if not versions:
        raise _refus("REJ-EXPERIENCE-INCONNUE", "expérience jamais définie")
    if cs.instant(recu_a) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")
    precedents = [e for e in chaine if e["type"] == "RESULTAT" and e["experience_id"] == experience_id]
    if (
        precedents
        and precedents[-1]["entrees_hash"] == resultat["entrees_hash"]
        and precedents[-1]["version"] == versions[-1]["version"]
    ):
        return None
    return chainage.suivant(
        SCHEMA,
        chaine,
        {
            "type": "RESULTAT",
            "experience_id": experience_id,
            "version": versions[-1]["version"],
            "entrees_hash": resultat["entrees_hash"],
            "gain_mesure": resultat["gain_mesure"],
            "roi": resultat["roi"],
            "statut_roi": resultat["statut_roi"],
            "recu_a": recu_a,
            "par": par,
        },
    )


def vue(chaine: Sequence[Mapping], captures: Sequence[Mapping], *, connaissance: str) -> dict:
    limite = cs.instant(connaissance)
    if limite is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant de connaissance avec fuseau explicite requis")
    connus = [e for e in chaine if (cs.instant(e["recu_a"]) or limite) <= limite]
    sortie = []
    for exp_id in sorted({e["experience_id"] for e in connus if e["type"] == "EXPERIENCE"}):
        versions = [e for e in connus if e["type"] == "EXPERIENCE" and e["experience_id"] == exp_id]
        courante = versions[-1]
        resultats = [e for e in connus if e["type"] == "RESULTAT" and e["experience_id"] == exp_id]
        sortie.append(
            {
                "experience_id": exp_id,
                "version": courante["version"],
                "versions_total": len(versions),
                "hypothese": courante["definition"]["hypothese"],
                "design": courante["definition"]["design"],
                "evaluation": evaluer(courante["definition"], captures, connaissance=connaissance),
                "historique_resultats": [
                    {k: r[k] for k in ("version", "gain_mesure", "roi", "statut_roi", "entrees_hash", "recu_a")}
                    for r in resultats
                ],
            }
        )
    return {"type": "EXPERIENCES_M9", "connaissance": connaissance, "experiences": sortie, "limites": list(_LIMITES)}
