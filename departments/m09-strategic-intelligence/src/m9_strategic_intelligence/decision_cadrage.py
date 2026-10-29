"""Cadrage d'une décision stratégique M9.10 : classer la question, dire ce qu'il faut lire, ce qui manque et qui valide.

Module pur et déterministe. Il ne DÉCIDE jamais : il prépare le terrain du conseil (M9.4) et de la gouvernance (M9.19).
Pour une question de direction (« Dois-je acheter un camion ? », « Dois-je augmenter Google Ads ? »), il rend :

* le TYPE de décision reconnu (douze types) ou, sans correspondance claire, ``TYPE_NON_RECONNU`` / ``AMBIGU`` avec les
  candidats : jamais une devinette ;
* les départements concernés et les LECTURES de producteurs nécessaires, avec leur état de couverture réel (présente,
  absente, partielle, refusée, contradictoire…) : ``pret_pour_conseil`` est faux tant qu'une lecture requise manque ;
* la VALIDATION humaine applicable (Nathan toujours ; comptable ou juriste suggérés selon le type ; classes sensibles de
  la gouvernance) ;
* des CRITÈRES proposés par propriétaire, les scénarios et playbooks à examiner, et ce que la personne doit DÉCLARER
  (plafond, horizon, objectif) — aucune valeur par défaut ;
* un BROUILLON de demande d'approbation (jamais soumis par ce module).

Le texte de la question est une donnée : une instruction qu'il contiendrait n'est jamais suivie.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs
from . import conseil

VERSION = "2026-10-29.1"
MAX_QUESTION = 500


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _critere(id_: str, libelle: str, proprietaire: str) -> dict:
    return {"id": id_, "libelle": libelle, "proprietaire": proprietaire, "statut": "PROPOSE_NON_VALIDE"}


def _type(
    id_, libelle, motifs, departements, lectures, classes, cpa, avocat, scenarios, playbooks, criteres, a_declarer
) -> dict:
    return {
        "id": id_,
        "libelle": libelle,
        "motifs": tuple(motifs),
        "departements": tuple(departements),
        "lectures_requises": tuple(lectures),
        "classes_sensibles": tuple(classes),
        "requiert_comptable": cpa,
        "requiert_juriste": avocat,
        "scenarios": tuple(scenarios),
        "playbooks": tuple(playbooks),
        "criteres": tuple(criteres),
        "a_declarer": tuple(a_declarer),
    }


TYPES: tuple[dict, ...] = (
    _type(
        "budget_publicitaire", "Budget publicitaire",
        (r"\bgoogle ads\b", r"\bpublicite", r"\bppc\b", r"budget (marketing|publicitaire|pub)\b", r"\bfacebook ads\b"),
        ("m07", "m02", "m05", "m04"),
        ("m7.performance_campagnes", "m2.leads", "m5.prevision_tresorerie", "m4.cedule_semaine"),
        ("budget_marketing",), False, False,
        ("hausse_budget_marketing", "baisse_leads", "trop_de_demandes"), ("roi_marketing_faible", "trop_de_leads"),
        (
            _critere("cout_par_lead", "Coût par lead observé par M7", "m07"),
            _critere("capacite", "Capacité de production disponible pour absorber les leads", "m04"),
            _critere("tresorerie", "Marge de manœuvre de trésorerie", "m05"),
        ),
        ("plafond de budget", "durée du test", "objectif mesurable"),
    ),
    _type(
        "embauche", "Embauche",
        (r"\bembauch", r"\bnouvel employe\b", r"\brecruter\b", r"\bengager (un|une)\b"),
        ("m04", "m05", "m02"),
        ("m4.cedule_semaine", "m5.prevision_tresorerie", "m2.leads"),
        ("embauche",), True, False,
        ("nouvel_employe", "cashflow_serre"), ("embauche",),
        (
            _critere("charge", "Charge de travail soutenue sur plusieurs semaines", "m04"),
            _critere("cout_complet", "Coût complet annuel du poste (paie, charges)", "m05"),
            _critere("demande", "Demande prévisible (pipeline)", "m02"),
        ),
        ("poste et rémunération", "date de début", "durée d'engagement"),
    ),
    _type(
        "achat_vehicule", "Achat d'un véhicule",
        (r"\bcamion\b", r"\bvehicule\b", r"\bfourgonnette\b"),
        ("m05", "m04"),
        ("m5.prevision_tresorerie", "m5.comptes_a_payer", "m4.cedule_semaine"),
        ("achat_majeur",), True, False,
        ("achat_camion", "cashflow_serre"), ("achat_equipement",),
        (
            _critere("tresorerie", "Trésorerie après achat et financement", "m05"),
            _critere("utilisation", "Utilisation prévue du véhicule dans la cédule", "m04"),
        ),
        ("prix et financement", "date d'achat", "usage prévu"),
    ),
    _type(
        "achat_batiment", "Achat ou location d'un bâtiment",
        (r"\bbatisse\b", r"\bbatiment\b", r"\blocal commercial\b", r"\bimmeuble\b", r"\bentrepot\b"),
        ("m05", "m04", "m06"),
        ("m5.prevision_tresorerie", "m5.comptes_a_payer", "m4.cedule_semaine"),
        ("achat_majeur", "dette"), True, True,
        ("achat_batisse", "cashflow_serre"), ("achat_equipement",),
        (
            _critere("tresorerie", "Trésorerie et endettement après achat", "m05"),
            _critere("besoin", "Besoin d'espace (stock, équipes)", "m06"),
        ),
        ("prix, mise de fonds et financement", "usage prévu", "date visée"),
    ),
    _type(
        "hausse_prix", "Hausse de prix",
        (r"augmenter (les|mes|nos) prix\b", r"\bhausse (des|de) prix\b", r"\bprix plancher\b", r"\bgrille de prix\b"),
        ("m03", "m05", "m02", "m08"),
        ("m3.ecarts", "m5.rentabilite_chantier", "m2.leads", "m8.vue_executive"),
        ("prix_global",), False, False,
        ("baisse_leads", "hausse_cout_materiaux"), ("hausse_prix",),
        (
            _critere("marge", "Marge réelle des chantiers récents", "m05"),
            _critere("acceptation", "Taux d'acceptation des devis", "m08"),
            _critere("ecart_estimation", "Écart estimé / réel", "m03"),
        ),
        ("hausse visée", "services concernés", "date d'entrée en vigueur"),
    ),
    _type(
        "nouveau_service", "Lancement d'un nouveau service",
        (r"\bnouveau service\b", r"\blancer un service\b", r"\bnouvelle offre\b"),
        ("m03", "m04", "m07", "m05"),
        ("m3.ecarts", "m4.cedule_semaine", "m7.performance_campagnes", "m5.prevision_tresorerie"),
        (), False, False,
        ("nouveau_service",), ("nouveau_service",),
        (
            _critere("marge_prevue", "Marge prévue du service (M3)", "m03"),
            _critere("capacite", "Capacité à le livrer", "m04"),
        ),
        ("service visé", "investissement prévu", "date de lancement"),
    ),
    _type(
        "refus_petits_contrats", "Refus de certains petits contrats",
        (r"\bpetits (jobs|contrats|travaux|chantiers)\b", r"\brefuser (certains|des|les)\b"),
        ("m03", "m05", "m04", "m02"),
        ("m3.ecarts", "m5.rentabilite_chantier", "m4.cedule_semaine", "m2.leads"),
        (), False, False,
        ("trop_de_demandes",), ("surcharge",),
        (
            _critere("marge_petits_jobs", "Marge réelle des petits chantiers", "m05"),
            _critere("temps_deplacement", "Temps de déplacement et de préparation", "m04"),
        ),
        ("seuil de taille retenu", "durée de la politique"),
    ),
    _type(
        "priorite_ville", "Priorité à une ville ou un secteur",
        (r"\bnouvelle ville\b", r"\bnouveau secteur\b", r"\bville\b", r"\bsecteur\b"),
        ("m02", "m07", "m04", "m05"),
        ("m2.leads", "m7.performance_campagnes", "m4.interventions", "m5.rentabilite_chantier"),
        (), False, False,
        ("nouvelle_ville",), ("expansion_ville",),
        (
            _critere("demande", "Demande observée dans la ville (M2)", "m02"),
            _critere("cout_deplacement", "Coût de déplacement (M4)", "m04"),
            _critere("marge", "Marge réelle dans la zone (M5)", "m05"),
        ),
        ("ville ou secteur visé", "durée du test", "objectif mesurable"),
    ),
    _type(
        "reduction_depenses", "Réduction des dépenses",
        (r"\breduire (les|mes|nos) depenses\b", r"\bcouper (les|des) depenses\b", r"\bdepenses\b"),
        ("m05", "m06", "m07"),
        ("m5.prevision_tresorerie", "m5.comptes_a_payer", "m7.performance_campagnes"),
        (), False, False,
        ("cashflow_serre",), ("cash",),
        (
            _critere("tresorerie", "Marge de manœuvre de trésorerie", "m05"),
            _critere("echeances", "Échéances fournisseurs à payer", "m05"),
        ),
        ("postes visés", "durée de la réduction"),
    ),
    _type(
        "investissement_equipement", "Investissement en équipement",
        (r"\bequipement\b", r"\boutillage\b", r"\bmachine\b", r"\bechafaudage"),
        ("m05", "m04", "m03"),
        ("m5.prevision_tresorerie", "m4.cedule_semaine", "m3.ecarts"),
        ("achat_majeur",), True, False,
        ("achat_equipement", "cashflow_serre"), ("achat_equipement",),
        (
            _critere("tresorerie", "Trésorerie après achat", "m05"),
            _critere("gain_productivite", "Gain de productivité attendu", "m04"),
        ),
        ("équipement visé", "prix et financement", "gain attendu et horizon"),
    ),
    _type(
        "strategie_marketing", "Changement de stratégie marketing",
        (r"\bstrategie marketing\b", r"\bseo\b", r"\breseaux sociaux\b", r"\bmarketing\b"),
        ("m07", "m02", "m08"),
        ("m7.performance_campagnes", "m2.leads", "m8.vue_executive"),
        ("budget_marketing",), False, False,
        ("hausse_budget_marketing", "baisse_leads"), ("roi_marketing_faible", "relance_avis_clients"),
        (
            _critere("cout_par_lead", "Coût par lead observé par M7", "m07"),
            _critere("conversion", "Conversion lead → devis (M8)", "m08"),
        ),
        ("changement visé", "durée du test", "objectif mesurable"),
    ),
    _type(
        "ajout_equipe", "Ajout d'une équipe",
        (r"\bajouter une equipe\b", r"\bdeuxieme equipe\b", r"\bnouvelle equipe\b", r"\bequipe supplementaire\b"),
        ("m04", "m05", "m02"),
        ("m4.cedule_semaine", "m4.retards_incidents", "m5.prevision_tresorerie", "m2.leads"),
        ("embauche", "achat_majeur"), True, False,
        ("nouvel_employe", "trop_de_demandes", "cashflow_serre"), ("embauche", "trop_de_leads"),
        (
            _critere("charge", "Charge de travail soutenue sur plusieurs semaines", "m04"),
            _critere("tresorerie", "Trésorerie après embauches et équipement", "m05"),
            _critere("demande", "Demande prévisible (pipeline)", "m02"),
        ),
        ("composition de l'équipe", "date de début", "financement"),
    ),
)  # fmt: skip
PAR_ID = {t["id"]: t for t in TYPES}


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, ponctuation en espaces : forme comparable de la question."""
    decompose = unicodedata.normalize("NFKD", texte.lower())
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9% ]+", " ", sans_accents)


def classer(question: str) -> dict:
    """Type de décision de la question : un seul type, ``AMBIGU`` (candidats) ou ``TYPE_NON_RECONNU`` (types connus)."""
    if type(question) is not str or not question.strip() or len(question) > MAX_QUESTION:
        raise _refus("REJ-DECISION-QUESTION", f"question non vide de {MAX_QUESTION} caractères au plus requise")
    texte = normaliser(question)
    scores: dict[str, int] = {}
    for type_ in TYPES:
        touches = sum(1 for motif in type_["motifs"] if re.search(motif, texte))
        if touches:
            scores[type_["id"]] = touches
    if not scores:
        return {"statut": "TYPE_NON_RECONNU", "types_connus": [t["id"] for t in TYPES]}
    meilleur = max(scores.values())
    gagnants = sorted(i for i, s in scores.items() if s == meilleur)
    if len(gagnants) > 1:
        return {"statut": "AMBIGU", "candidats": gagnants, "types_connus": [t["id"] for t in TYPES]}
    return {"statut": "RECONNU", "type": gagnants[0], "score": meilleur}


def cadrer(question: str, captures: Sequence[Mapping], *, reference: str, connaissance: str) -> dict:
    """Cadre la question : type, lectures et couverture, validation humaine, critères, brouillon d'approbation."""
    classement = classer(question)
    base: dict = {
        "type": "CADRAGE_DECISION",
        "version": VERSION,
        "question": question,
        "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "reference": reference,
        "connaissance": connaissance,
        "classement": classement,
        "decision_prise_par_m9": False,
    }
    if classement["statut"] != "RECONNU":
        base |= {
            "pret_pour_conseil": False,
            "a_faire": "reformuler la question ou choisir un type de décision parmi ceux listés",
        }
        base["cadrage_id"] = _identifiant(base)
        return base
    type_ = PAR_ID[classement["type"]]
    couverture = cs.evaluer_couverture(
        captures, reference=reference, connaissance=connaissance, attendues=list(type_["lectures_requises"])
    )
    classes = {
        c: {"verdict": "VALIDATION_HUMAINE_REQUISE", "mandataire": conseil.ACTIONS_SENSIBLES[c]}
        for c in type_["classes_sensibles"]
    }
    validation = {
        "requiert_nathan": True,
        "requiert_comptable": type_["requiert_comptable"],
        "requiert_juriste": type_["requiert_juriste"],
        "classes_sensibles": classes,
        "indicatif": "suggestion de M9 : à confirmer par Nathan ; aucun effet n'est autorisé par ce cadrage",
    }
    manques = [
        {"lecture_id": e["lecture_id"], "statut": e["statut"], "manque": e.get("manque")}
        for e in couverture["lectures"]
        if e["statut"] != "PRESENTE"
    ]
    base |= {
        "decision": {"id": type_["id"], "libelle": type_["libelle"]},
        "departements": list(type_["departements"]),
        "lectures_requises": list(type_["lectures_requises"]),
        "couverture": [{"lecture_id": e["lecture_id"], "statut": e["statut"]} for e in couverture["lectures"]],
        "manques": manques,
        "contradictions": couverture["contradictions"],
        "pret_pour_conseil": couverture["complete"],
        "validation": validation,
        "criteres_proposes": [dict(c) for c in type_["criteres"]],
        "scenarios_a_examiner": list(type_["scenarios"]),
        "playbooks_a_examiner": list(type_["playbooks"]),
        "a_declarer_par_la_personne": list(type_["a_declarer"]),
        "brouillon_approbation": {
            "decision_type": type_["id"],
            "titre": type_["libelle"],
            "montant": None,
            "niveau_de_risque": "INCONNU",
            "departements_impactes": list(type_["departements"]),
            "action_recommandee": None,
            "alternatives": [],
            "requiert_nathan": True,
            "requiert_comptable": type_["requiert_comptable"],
            "requiert_juriste": type_["requiert_juriste"],
            "statut": "BROUILLON_NON_SOUMIS",
        },
        "limites": [
            "Cadrage déterministe : il ne recommande rien et ne chiffre rien ; le conseil (M9.4) délibère ensuite.",
            "Les critères sont proposés, non validés par Nathan ; montant, risque et action restent à déclarer.",
        ],
    }
    base["cadrage_id"] = _identifiant(base)
    return base


def _identifiant(corps: Mapping) -> str:
    return hashlib.sha256(json.dumps(corps, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
