"""Registre des indicateurs exécutifs M9.3 : chacun renvoie à UNE définition officielle, ou dit qu'il n'en a pas.

Module pur. Le cahier de direction nomme dix-sept indicateurs (revenu, marge, cash libre réel, pipeline, conversion,
rentabilité d'un chantier, ROI marketing, coût par lead, capacité, préparation des stocks, satisfaction, score de
risque…). Aucun n'est « inventé » ici : la définition officielle d'un indicateur appartient à son DÉPARTEMENT
PROPRIÉTAIRE. Ce registre ne fait que RELIER chaque indicateur à ce qui existe vraiment :

* ``DEFINIE_M8`` — M8 tient une définition versionnée (``departments/m08-analytics/metrics/*.yaml``) ; le registre
  durable de M8 dit si elle y est enregistrée ;
* ``DEFINIE_CHEZ_LE_PROPRIETAIRE`` — le département propriétaire définit et publie la valeur lui-même (M5, M7), sans
  définition dans le dictionnaire M8 ;
* ``SIGNAL_M9`` — signal propre à M9 (grade du radar de risques) : il n'est PAS un score numérique et sa grille est
  proposée, non validée ;
* ``A_DEFINIR_PAR_LE_PROPRIETAIRE`` — aucune définition officielle n'existe : M9 ne la fabrique pas et ne calcule pas
  l'indicateur ; la sortie dit qui doit le définir et ce qui manque.

Le LIGNAGE ne fait jamais de calcul : pour un indicateur défini, il cite les adresses de faits des captures complètes
(``<lecture>#<rang>:p<page>.<chemin>``) dont la clé terminale ou l'identifiant de métrique est celui de
l'indicateur, avec leur valeur textuelle exacte (ou « null »). Une capture partielle, refusée ou contradictoire ne
produit aucun lignage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs

VERSION = "2026-10-29.1"
STATUTS = frozenset({"DEFINIE_M8", "DEFINIE_CHEZ_LE_PROPRIETAIRE", "SIGNAL_M9", "A_DEFINIR_PAR_LE_PROPRIETAIRE"})
LECTURE_REGISTRE_M8 = "m8.definitions_metriques"
_MAX_FAITS_PAR_INDICATEUR = 6


def _ind(
    id_: str,
    libelle: str,
    unite: str,
    proprietaire: str,
    statut: str,
    *,
    m8: Sequence[str] = (),
    lectures: Sequence[str] = (),
    cles: Sequence[str] = (),
    note: str,
) -> dict:
    return {
        "id": id_,
        "libelle": libelle,
        "unite": unite,
        "proprietaire": proprietaire,
        "statut_definition": statut,
        "metriques_m8": list(m8),
        "lectures_sources": list(lectures),
        "cles_de_fait": list(cles),
        "note": note,
    }


REGISTRE: tuple[dict, ...] = (
    _ind(
        "revenue", "Revenu", "CAD", "m05-financecore", "A_DEFINIR_PAR_LE_PROPRIETAIRE",
        note="Aucun revenu d'entreprise agrégé n'est exposé. Le carnet signé de M8 (devis acceptés) n'en est pas un.",
    ),
    _ind(
        "gross_margin", "Marge brute", "CAD", "m05-financecore", "DEFINIE_M8",
        m8=("m8_marge_reelle_cad", "m8_marge_prevue_cad"), lectures=("m8.mesures_chantier",),
        note="Marge réelle d'un CHANTIER (M5) : aucune marge brute d'entreprise n'est définie ni agrégée par M9.",
    ),
    _ind(
        "net_margin", "Marge nette", "CAD", "m05-financecore", "A_DEFINIR_PAR_LE_PROPRIETAIRE",
        note="Aucune marge nette d'entreprise n'est définie ; taxes, paies et frais fixes restent chez M5.",
    ),
    _ind(
        "cash_free_real", "Cash libre réel", "CAD", "m05-financecore", "DEFINIE_CHEZ_LE_PROPRIETAIRE",
        note="M5 constate le cash libre réel du jour (m5_constater_cash_libre : événement du bus). Aucune lecture T0 "
        "n'est autorisée dans le catalogue de M9 : tant que M5 n'en expose pas, M9 ne cite aucune valeur.",
    ),
    _ind(
        "pipeline_value", "Valeur du pipeline", "CAD", "m02-revenue-crm", "A_DEFINIR_PAR_LE_PROPRIETAIRE",
        note="M2 ne valorise pas les leads. Le carnet signé de M8 ne couvre que les devis acceptés, pas le pipeline.",
    ),
    _ind(
        "qualified_lead", "Lead qualifié", "leads", "m02-revenue-crm", "DEFINIE_M8",
        m8=("m8_leads_qualifies",), lectures=("m8.vue_executive", "m8.mesures_chantier"),
        note="Leads distincts que M2 a fait passer de nouveau à qualifié (définition M8).",
    ),
    _ind(
        "conversion_rate", "Taux de conversion lead → vente", "pourcentage", "m02-revenue-crm",
        "A_DEFINIR_PAR_LE_PROPRIETAIRE",
        note="M8 publie des comptes (leads reçus, devis acceptés), aucun rapport lead → vente : M9 ne le calcule pas.",
    ),
    _ind(
        "estimate_to_quote_rate", "Taux estimation → devis", "pourcentage", "m03-estimation",
        "A_DEFINIR_PAR_LE_PROPRIETAIRE",
        note="Aucune définition du passage de l'estimation au devis envoyé n'existe.",
    ),
    _ind(
        "quote_to_win_rate", "Taux devis → vente", "pourcentage", "m03-estimation", "DEFINIE_M8",
        m8=("m8_taux_acceptation_pct",), lectures=("m8.vue_executive", "m8.mesures_chantier"),
        note="Part des devis envoyés qui ont été acceptés (définition M8).",
    ),
    _ind(
        "job_profitability", "Rentabilité d'un chantier", "CAD", "m05-financecore", "DEFINIE_M8",
        m8=("m8_marge_reelle_cad", "m8_ecart_marge_cad", "m8_ecart_marge_pct"),
        lectures=("m8.mesures_chantier", "m5.rentabilite_chantier"),
        note="Marge réelle qualifiée par M5 et écart face à la marge prévue de M3 (définitions M8), par chantier.",
    ),
    _ind(
        "marketing_roi", "ROI marketing", "ratio", "m07-marketing", "DEFINIE_CHEZ_LE_PROPRIETAIRE",
        lectures=("m7.performance_campagnes",), cles=("roi",),
        note="M7 publie le ROI d'une campagne seulement avec attribution ; sinon la clé est absente ou nulle. "
        "Le calcul de démonstration de M7 sur fixtures n'est pas un fait d'entreprise.",
    ),
    _ind(
        "cost_per_lead", "Coût par lead", "CAD", "m07-marketing", "DEFINIE_CHEZ_LE_PROPRIETAIRE",
        lectures=("m7.performance_campagnes",), cles=("cout_par_lead_cad",),
        note="Valeur de M7 par campagne ; nulle tant que l'attribution ou le coût publicitaire manque.",
    ),
    _ind(
        "cost_per_sale", "Coût par vente", "CAD", "m07-marketing", "A_DEFINIR_PAR_LE_PROPRIETAIRE",
        note="M7 n'expose aucun coût par vente.",
    ),
    _ind(
        "team_capacity", "Capacité d'équipe", "jours-personnes", "m04-field-ops", "A_DEFINIR_PAR_LE_PROPRIETAIRE",
        note="M4 expose la cédule et les interventions, pas une capacité en jours-personnes : M9 ne la fabrique pas.",
    ),
    _ind(
        "inventory_readiness", "Préparation des stocks", "indice", "m06-material-control",
        "A_DEFINIR_PAR_LE_PROPRIETAIRE",
        note="M6 expose la disponibilité par article, pas un indice de préparation.",
    ),
    _ind(
        "customer_satisfaction", "Satisfaction client", "indice", "m04-field-ops", "A_DEFINIR_PAR_LE_PROPRIETAIRE",
        note="Un signal de satisfaction existe chez M4 mais n'est pas gardé par M2 ni défini comme indicateur.",
    ),
    _ind(
        "risk_score", "Grade de risque", "grade", "m09-strategic-intelligence", "SIGNAL_M9",
        note="Grade FAIBLE/MOYEN/ELEVE/INCONNU du radar de risques, selon une grille PROPOSÉE non validée par Nathan : "
        "ce n'est pas un score numérique.",
    ),
)  # fmt: skip
PAR_ID = {i["id"]: i for i in REGISTRE}


def definitions() -> list[dict]:
    """Copie du registre (sans lignage)."""
    return [dict(i, metriques_m8=list(i["metriques_m8"])) for i in REGISTRE]


def _utilisables(captures: Sequence[Mapping], connaissance: str) -> list[Mapping]:
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    derniere: dict[tuple[str, str], Mapping] = {}
    for capture in connues:
        derniere[(capture["lecture_id"], capture["arguments_sha256"])] = capture
    return [
        c
        for cle, c in sorted(derniere.items(), key=lambda kv: kv[1]["index"])
        if c["verdict"] == "ACCEPTEE" and c["complete"] and cle not in en_conflit
    ]


def _registre_m8(utilisables: Sequence[Mapping]) -> set[str] | None:
    """Identifiants du registre M8 d'après la dernière capture complète, ou ``None`` si jamais capturé."""
    capture = next((c for c in reversed(utilisables) if c["lecture_id"] == LECTURE_REGISTRE_M8), None)
    if capture is None:
        return None
    return {
        ligne["metric_id"]
        for page in capture["pages"]
        for ligne in cs.extraire(page, "resultat.definitions[*]")
        if isinstance(ligne, Mapping) and type(ligne.get("metric_id")) is str
    }


def _texte(valeur: object) -> str:
    return "null" if valeur is None else (valeur if isinstance(valeur, str) else json.dumps(valeur, sort_keys=True))


_MAX_PROFONDEUR = 12
_MAX_FEUILLES = 4000


def _feuilles(
    document: object, chemin: str = "", profondeur: int = 0, sortie: list | None = None
) -> list[tuple[str, str]]:
    """Feuilles scalaires d'un document, ``chemin → texte`` (bornées en profondeur et en nombre)."""
    sortie = [] if sortie is None else sortie
    if profondeur > _MAX_PROFONDEUR or len(sortie) >= _MAX_FEUILLES:
        return sortie
    if isinstance(document, Mapping):
        for cle in sorted(document):
            _feuilles(document[cle], f"{chemin}.{cle}" if chemin else str(cle), profondeur + 1, sortie)
    elif isinstance(document, list):
        for rang, element in enumerate(document):
            _feuilles(element, f"{chemin}[{rang}]", profondeur + 1, sortie)
    elif document is None or isinstance(document, (bool, int, float, str)):
        sortie.append((chemin, "true" if document is True else "false" if document is False else _texte(document)))
    return sortie


def _faits(indicateur: Mapping, utilisables: Sequence[Mapping]) -> list[dict]:
    """Faits cités de l'indicateur : mesures M8 par identifiant, clés terminales publiées par le propriétaire."""
    trouves: list[dict] = []
    for capture in reversed(utilisables):
        if capture["lecture_id"] not in indicateur["lectures_sources"]:
            continue
        for numero_page, page in enumerate(capture["pages"]):
            base = f"{capture['lecture_id']}#{capture['index']}:p{numero_page}"
            for chemin in ("resultat.mesures[*]", "resultat.resultat.mesures[*]"):
                for rang, ligne in enumerate(cs.extraire(page, chemin)):
                    if isinstance(ligne, Mapping) and ligne.get("metric_id") in indicateur["metriques_m8"]:
                        trouves.append(
                            {
                                "adresse": f"{base}.{chemin[:-3]}[{rang}].valeur",
                                "metric_id": ligne["metric_id"],
                                "valeur": _texte(ligne.get("valeur")),
                            }
                        )
            if indicateur["cles_de_fait"]:
                for chemin_feuille, valeur in _feuilles(page):
                    if chemin_feuille.rsplit(".", 1)[-1] in indicateur["cles_de_fait"]:
                        trouves.append({"adresse": f"{base}.{chemin_feuille}", "valeur": valeur})
        if len(trouves) >= _MAX_FAITS_PAR_INDICATEUR:
            break
    return trouves[:_MAX_FAITS_PAR_INDICATEUR]


def lignage(captures: Sequence[Mapping], *, connaissance: str) -> dict:
    """Les dix-sept indicateurs avec leur statut de définition, leur présence au registre M8 et leurs faits cités."""
    utilisables = _utilisables(captures, connaissance)
    registre = _registre_m8(utilisables)
    lignes: list[dict] = []
    for indicateur in REGISTRE:
        ligne = {
            "id": indicateur["id"],
            "libelle": indicateur["libelle"],
            "unite": indicateur["unite"],
            "proprietaire": indicateur["proprietaire"],
            "statut_definition": indicateur["statut_definition"],
            "note": indicateur["note"],
            "calcule_par_m9": False,
        }
        if indicateur["statut_definition"] == "DEFINIE_M8":
            ligne["metriques_m8"] = {
                m: (
                    "REGISTRE_NON_CAPTURE"
                    if registre is None
                    else ("AU_REGISTRE" if m in registre else "ABSENTE_DU_REGISTRE")
                )
                for m in indicateur["metriques_m8"]
            }
        if (
            indicateur["statut_definition"] in ("DEFINIE_M8", "DEFINIE_CHEZ_LE_PROPRIETAIRE")
            and (indicateur["lectures_sources"])
        ):
            faits = _faits(indicateur, utilisables)
            ligne["faits"] = faits
            ligne["lignage"] = "FAITS_CITES" if faits else "AUCUN_FAIT_CAPTURE"
        lignes.append(ligne)
    par_statut: dict[str, int] = {}
    for ligne in lignes:
        par_statut[ligne["statut_definition"]] = par_statut.get(ligne["statut_definition"], 0) + 1
    resultat = {
        "type": "INDICATEURS_EXECUTIFS",
        "version": VERSION,
        "connaissance": connaissance,
        "registre_m8_capture": registre is not None,
        "par_statut": par_statut,
        "indicateurs": lignes,
        "limites": [
            "La définition d'un indicateur appartient à son propriétaire : M9 relie et cite, il ne calcule jamais.",
            "Un indicateur A_DEFINIR_PAR_LE_PROPRIETAIRE n'a pas de valeur citable : l'absence n'est jamais un zéro.",
        ],
    }
    resultat["lignage_id"] = hashlib.sha256(
        json.dumps(resultat, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return resultat
