"""Conseil d'agents M9.4 : douze responsabilités, sélection déterministe des spécialistes utiles, chaîne gouvernée.

Module pur : aucun appel de modèle, aucune horloge, aucun import d'``opsys``. Il définit QUI peut être consulté, QUAND
un
spécialiste est utile, ce qu'une sortie de modèle doit contenir pour être recevable et ce que la gouvernance en fait.
L'appel
de modèle lui-même est un port de l'adaptateur (``conseil_executeur``) qui passe par l'admission native de budget.

Chaîne : superviseur (code) → spécialistes sélectionnés (modèle sous budget) → auditeur de données (code, puis modèle si
le
budget le permet) → critique de décisions (modèle, décisions majeures seulement) → gouvernance (code) → recommandation
finale.
Aucun agent ne décide seul et aucune sortie de modèle n'est une autorité d'effet : c'est une PROPOSITION structurée,
dont
chaque affirmation est une observation citée, une hypothèse déclarée ou une inférence qui nomme ses prémisses.

* une citation exacte valide la CORRESPONDANCE textuelle à la source, jamais une inférence : une inférence n'est admise
  qu'avec des prémisses présentes (observations ou hypothèses admises) et reste ``INFERENCE_NON_VALIDEE`` ;
* le texte d'une source est une donnée, jamais une instruction : le contenu envoyé au modèle sépare consigne et données,
et
  toute demande d'outil, d'effet ou d'autorité dans une sortie est écartée et comptée (``demandes_ecartees``) ;
* pas d'appel systématique de tous les rôles : seuls les spécialistes dont le domaine est concerné sont consultés,
jusqu'à
  épuisement du budget ; les autres sont nommés ``NON_APPELE`` avec la raison.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

VERSION = "2026-10-28.1"
DOMAINES = frozenset(
    {
        "strategie",
        "arbitrage",
        "capacite",
        "chantiers",
        "meteo",
        "equipes",
        "cash",
        "marge",
        "couts",
        "dettes",
        "creances",
        "leads",
        "marketing",
        "campagnes",
        "pipeline",
        "relances",
        "conversion",
        "marge_estimee",
        "ecarts",
        "prix",
        "stock",
        "materiaux",
        "fournisseurs",
        "satisfaction",
        "plaintes",
        "delais_client",
        "risque",
        "plan",
        "taches",
        "execution",
        "donnees",
    }
)
IMPORTANCES = ("courante", "majeure")
NATURES = frozenset({"observation_source", "hypothese", "inference"})
MAX_AFFIRMATIONS = 24
MAX_TEXTE = 1500
CODE_CHIFFRE_LIBRE = "REJ-CONSEIL-CHIFFRE-LIBRE"
# Montant, pourcentage ou décimal à deux chiffres : une quantité que le code calcule et qu'un modèle ne produit pas.
_MONTANT = re.compile(
    r"(?<![\w.,])(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d{1,2})?\s?(?:\$|CAD|%|dollars?|k\$)"
    r"|(?<![\w.,])\d+[.,]\d{2}(?![\w])"
)
_DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMERIQUE = re.compile(r"\s*\d[\d \u00a0\u202f]*(?:[.,]\d+)?\s*(?:\$|CAD|%)?\s*")


@dataclasses.dataclass(frozen=True)
class Role:
    id: str
    nom: str
    responsabilite: str
    domaines: frozenset[str]
    lectures: tuple[str, ...]  # lectures du catalogue qui nourrissent ce rôle
    enveloppe_tokens: int  # enveloppe de réservation par tour, déclarée (jamais un prix)
    etape: str = "specialiste"  # "specialiste" | "audit" | "critique"
    palier: str = "standard"


ROLES: tuple[Role, ...] = (
    Role(
        "conseiller_pdg",
        "Conseiller du PDG",
        "Cadrer l'arbitrage global et la décision pour le propriétaire.",
        frozenset({"strategie", "arbitrage"}),
        (),
        6000,
        palier="fort",
    ),
    Role(
        "operations",
        "Opérations",
        "Lire capacité, chantiers, équipes et météo sans promettre de date.",
        frozenset({"capacite", "chantiers", "meteo", "equipes"}),
        ("m4.interventions", "m4.cedule_semaine", "m4.retards_incidents", "m4.meteo_intervention"),
        5000,
    ),
    Role(
        "liaison_finance",
        "Liaison finance",
        "Relayer les faits financiers de M5 sans les recalculer.",
        frozenset({"cash", "marge", "couts", "dettes", "creances"}),
        ("m5.prevision_tresorerie", "m5.rentabilite_chantier", "m5.comptes_a_recevoir", "m5.comptes_a_payer"),
        5000,
    ),
    Role(
        "croissance_marketing",
        "Croissance marketing",
        "Lire la performance des campagnes et les leads M7.",
        frozenset({"leads", "marketing", "campagnes"}),
        ("m7.performance_campagnes", "m2.leads"),
        4500,
    ),
    Role(
        "strategie_ventes",
        "Stratégie de vente",
        "Lire le pipeline, les relances et la conversion de M2.",
        frozenset({"pipeline", "relances", "conversion"}),
        ("m2.leads", "m2.relances"),
        4500,
    ),
    Role(
        "rentabilite_estimation",
        "Rentabilité d'estimation",
        "Lire les écarts estimé/réel de M3 sans recalculer de marge.",
        frozenset({"marge_estimee", "ecarts", "prix"}),
        ("m3.ecarts", "m8.mesures_chantier"),
        4500,
    ),
    Role(
        "contraintes_inventaire",
        "Contraintes d'inventaire",
        "Lire disponibilité et fournisseurs de M6, sans acheter.",
        frozenset({"stock", "materiaux", "fournisseurs", "prix"}),
        ("m6.disponibilite",),
        4500,
    ),
    Role(
        "experience_client",
        "Expérience client",
        "Lire délais, satisfaction et plaintes connus, sans les inventer.",
        frozenset({"satisfaction", "plaintes", "delais_client"}),
        ("m1.digest", "m4.retards_incidents"),
        4000,
    ),
    Role(
        "responsable_risques",
        "Responsable des risques",
        "Nommer les risques sourcés et ce qui contredit chaque risque.",
        frozenset({"risque"}),
        ("m5.comptes_a_payer", "m6.disponibilite", "m4.retards_incidents"),
        5000,
    ),
    Role(
        "auditeur_donnees",
        "Auditeur de données",
        "Vérifier citations, couverture, fraîcheur et contradictions.",
        frozenset({"donnees"}),
        (),
        3500,
        etape="audit",
    ),
    Role(
        "planificateur_execution",
        "Planificateur d'exécution",
        "Découper une décision approuvée en tâches proposées.",
        frozenset({"plan", "taches", "execution"}),
        (),
        4500,
    ),
    Role(
        "critique_decisions",
        "Critique de décisions",
        "Chercher la faille de la recommandation et ses contre-exemples.",
        frozenset({"arbitrage"}),
        (),
        5000,
        etape="critique",
        palier="fort",
    ),
)
PAR_ID: Mapping[str, Role] = {role.id: role for role in ROLES}
if len(PAR_ID) != 12 or len(ROLES) != 12:  # pragma: no cover - garde de construction
    raise ValueError("les douze responsabilités sont requises")


def selectionner(domaines: Sequence[str], *, importance: str, budget_tokens: int) -> dict:
    """Spécialistes utiles, sans les appeler tous. Déterministe : pertinence décroissante, puis ordre du catalogue.

    L'auditeur de données est toujours inscrit (son contrôle de code n'a pas besoin de budget de modèle) ; le critique
    n'est
    consulté que pour une décision ``majeure``. Un rôle dont l'enveloppe dépasse le reste du budget est
    ``NON_APPELE``."""
    if importance not in IMPORTANCES:
        raise ValueError("REJ-CONSEIL-IMPORTANCE : courante ou majeure requise")
    if type(budget_tokens) is not int or budget_tokens < 0:
        raise ValueError("REJ-CONSEIL-BUDGET : entier positif ou nul requis")
    if not isinstance(domaines, Sequence) or isinstance(domaines, str) or not 1 <= len(domaines) <= 16:
        raise ValueError("REJ-CONSEIL-DOMAINES : 1 à 16 domaines requis")
    if len(set(domaines)) != len(domaines) or not set(domaines) <= DOMAINES:
        raise ValueError("REJ-CONSEIL-DOMAINES : domaines distincts du vocabulaire fermé requis")
    demandes = set(domaines)
    candidats = []
    for position, role in enumerate(ROLES):
        if role.etape != "specialiste":
            continue
        pertinence = len(role.domaines & demandes)
        if pertinence:
            candidats.append((-pertinence, position, role))
    candidats.sort(key=lambda element: (element[0], element[1]))
    reste = budget_tokens
    appeles, ecartes = [], []
    for _, _, role in candidats:
        if role.enveloppe_tokens <= reste:
            appeles.append({"role": role.id, "reservation_tokens": role.enveloppe_tokens, "palier": role.palier})
            reste -= role.enveloppe_tokens
        else:
            ecartes.append({"role": role.id, "statut": "NON_APPELE", "raison": "budget insuffisant"})
    critique = PAR_ID["critique_decisions"]
    if importance == "majeure":
        if critique.enveloppe_tokens <= reste and appeles:
            appeles.append(
                {"role": critique.id, "reservation_tokens": critique.enveloppe_tokens, "palier": critique.palier}
            )
            reste -= critique.enveloppe_tokens
        else:
            ecartes.append(
                {
                    "role": critique.id,
                    "statut": "NON_APPELE",
                    "raison": "budget insuffisant ou aucun spécialiste appelé",
                }
            )
    else:
        ecartes.append({"role": critique.id, "statut": "NON_APPELE", "raison": "décision non majeure"})
    consultes = {element["role"] for element in (*appeles, *ecartes)}
    ecartes.extend(
        {"role": role.id, "statut": "NON_APPELE", "raison": "domaine non concerné"}
        for role in ROLES
        if role.etape == "specialiste" and role.id not in consultes
    )
    return {
        "type": "SELECTION_CONSEIL",
        "version": VERSION,
        "domaines": sorted(demandes),
        "importance": importance,
        "budget_tokens": budget_tokens,
        "appeles": appeles,
        "non_appeles": sorted(ecartes, key=lambda element: element["role"]),
        "auditeur_donnees": "controle de code toujours execute",
        "tokens_reserves": sum(element["reservation_tokens"] for element in appeles),
        "tokens_restants": reste,
    }


def profil_agent(role_id: str, *, outils: Sequence[str], budget_jour: int, budget_mois: int) -> dict:
    """Spécification d'un profil d'agent natif (``opsys.agents``) pour un rôle ; déclenchement manuel seulement.

    Les profils sont des DÉCLARATIONS : leur création relève d'un administrateur (``agents.creer``) et n'active aucun
    grant."""
    role = PAR_ID[role_id]
    return {
        "id": f"m9-{role.id.replace('_', '-')}",
        "departement": "m09-strategic-intelligence",
        "responsabilite": role.responsabilite,
        "palier_modele": role.palier,
        "outils": sorted(outils),
        "budget_jour": budget_jour,
        "budget_mois": budget_mois,
        "limite_tours": 3,
        "limite_reessais": 1,
        "limite_concurrence": 1,
        "declencheurs": [{"type": "manuel"}],
    }


def _texte(valeur: object, maximum: int = MAX_TEXTE) -> bool:
    return type(valeur) is str and bool(valeur.strip()) and len(valeur) <= maximum


def _nombre(texte: str) -> Decimal | None:
    try:
        return Decimal(re.sub(r"[^\d.,]", "", texte).replace(",", "."))
    except InvalidOperation:
        return None


def chiffres_libres(texte: str, valeurs_citees: Sequence[str]) -> list[str]:
    """Montants, pourcentages, décimaux et dates ISO d'un texte libre absents de toute valeur CITÉE par la même sortie.

    « Le code calcule, le modèle explique » : un modèle peut reprendre une valeur qu'il cite, jamais en produire une
    (somme, projection, zéro pour une absence). Entiers nus et identifiants ne sont pas visés : leur sens ne se
    détermine pas sans sémantique (limite connue, voir le corpus métier M9.23)."""
    nombres: set[Decimal] = set()
    dates: set[str] = set()
    for valeur in valeurs_citees:
        if _NUMERIQUE.fullmatch(valeur) and (n := _nombre(valeur)) is not None:
            nombres.add(n)
        nombres.update(n for m in _MONTANT.finditer(valeur) if (n := _nombre(m.group(0))) is not None)
        dates.update(_DATE_ISO.findall(valeur))
    libres = [m.group(0).strip() for m in _MONTANT.finditer(texte) if _nombre(m.group(0)) not in nombres]
    libres += [d for d in _DATE_ISO.findall(texte) if d not in dates]
    return list(dict.fromkeys(libres))


def exiger_chiffres_sources(textes: Sequence[str], valeurs_citees: Sequence[str]) -> None:
    for texte in textes:
        libres = chiffres_libres(texte, valeurs_citees)
        if libres:
            raise ValueError(
                f"{CODE_CHIFFRE_LIBRE} : {libres[:3]} absent de toute citation de la même sortie ; "
                "citer la valeur du propriétaire plutôt que la produire"
            )


def admettre_proposition(sortie: object, *, sources: Mapping[str, str]) -> dict:
    """Admet ou refuse la sortie structurée d'un spécialiste. ``sources`` : ``reference → valeur textuelle`` exacte des
    sources autorisées de la capture. Tout est admis ou rien : une citation qui ne correspond pas mot pour mot, une
    inférence sans prémisse présente, un champ inconnu ou une demande d'outil refusent la sortie entière — sauf les
    ``demandes`` d'outil/d'effet, qui sont écartées et comptées sans jamais être exécutées.

    Entrée : ``{"affirmations": [{id, nature, …}], "demandes": [...]}`` avec ``nature`` ∈ observation_source
    (``reference``, ``valeur``), hypothese (``enonce``) ou inference (``enonce``, ``premisses`` = identifiants
    admis)."""
    if not isinstance(sortie, dict) or not set(sortie) <= {"affirmations", "demandes"} or "affirmations" not in sortie:
        raise ValueError("REJ-CONSEIL-SORTIE : objet {affirmations[, demandes]} requis")
    brutes = sortie["affirmations"]
    if type(brutes) is not list or not 1 <= len(brutes) <= MAX_AFFIRMATIONS:
        raise ValueError(f"REJ-CONSEIL-SORTIE : 1 à {MAX_AFFIRMATIONS} affirmations requises")
    demandes = sortie.get("demandes", [])
    if type(demandes) is not list or len(demandes) > 64:
        raise ValueError("REJ-CONSEIL-SORTIE : demandes = liste bornée")
    admises: dict[str, dict] = {}
    for brute in brutes:
        if not isinstance(brute, dict) or not _texte(brute.get("id"), 64) or brute["id"] in admises:
            raise ValueError("REJ-CONSEIL-AFFIRMATION : identifiant distinct requis")
        nature = brute.get("nature")
        if nature == "observation_source":
            if set(brute) != {"id", "nature", "reference", "valeur"} or not _texte(brute["reference"], 256):
                raise ValueError("REJ-CONSEIL-AFFIRMATION : citation {reference, valeur} exacte requise")
            if brute["reference"] not in sources or sources[brute["reference"]] != brute["valeur"]:
                raise ValueError(
                    "REJ-CONSEIL-CITATION : la citation ne correspond pas mot pour mot à la source autorisée"
                )
            statut = "SOURCE_CONCORDANTE"
        elif nature == "hypothese":
            if set(brute) != {"id", "nature", "enonce"} or not _texte(brute["enonce"]):
                raise ValueError("REJ-CONSEIL-AFFIRMATION : hypothèse {enonce} requise")
            statut = "HYPOTHESE_DECLAREE"
        elif nature == "inference":
            premisses = brute.get("premisses")
            if set(brute) != {"id", "nature", "enonce", "premisses"} or not _texte(brute["enonce"]):
                raise ValueError("REJ-CONSEIL-AFFIRMATION : inférence {enonce, premisses} requise")
            if type(premisses) is not list or not 1 <= len(premisses) <= 16 or len(set(premisses)) != len(premisses):
                raise ValueError("REJ-CONSEIL-INFERENCE : 1 à 16 prémisses distinctes requises")
            if any(type(p) is not str or p not in admises or admises[p]["nature"] == "inference" for p in premisses):
                raise ValueError(
                    "REJ-CONSEIL-INFERENCE : prémisses = observations ou hypothèses déjà admises, en amont"
                )
            statut = "INFERENCE_NON_VALIDEE"
        else:
            raise ValueError("REJ-CONSEIL-AFFIRMATION : nature inconnue")
        admises[brute["id"]] = {**brute, "statut": statut}
    exiger_chiffres_sources(
        [a["enonce"] for a in admises.values() if a["nature"] in ("hypothese", "inference")],
        [a["valeur"] for a in admises.values() if a["nature"] == "observation_source"],
    )
    return {
        "type": "PROPOSITION_ADMISE",
        "affirmations": list(admises.values()),
        "demandes_ecartees": len(demandes),
        "validation_semantique": "NON_PROUVEE",
        "limites": [
            "Une citation exacte prouve la correspondance au texte de la source, pas la vérité ni la validité d'une "
            "inférence.",
            "Les demandes d'outil, d'effet ou d'autorité d'une sortie de modèle sont écartées, jamais exécutées.",
        ],
    }


# Actions qui exigent une validation humaine applicable (DEFINITION-PRODUIT §M9 « Règles dures », M9.19).
ACTIONS_SENSIBLES = {
    "depense_reelle": "Nathan",
    "budget_marketing": "Nathan",
    "embauche": "Nathan",
    "achat_majeur": "Nathan",
    "dette": "Nathan",
    "prix_global": "Nathan",
    "decision_fiscale_ou_legale": "Nathan et professionnel",
    "contrat": "Nathan",
    "suppression_donnees": "Nathan",
}


def gouverner(recommandation: Mapping) -> dict:
    """Étape gouvernance (code) : classe chaque action proposée ; une action sensible n'est jamais autorisée ici.

    ``recommandation`` : ``{"decision": str, "actions": [{"id", "type", "description"}]}``. Un type inconnu ou
    ``sensible`` sans classe connue est refusé (fail-closed) ; une classe sensible exige l'approbation exacte du
    mandataire
    nommé ; seule une action interne non sensible (``suivi_interne``, ``information``) reste « proposable »."""
    if not isinstance(recommandation, Mapping) or not _texte(recommandation.get("decision")):
        raise ValueError("REJ-GOUVERNANCE-ENTREE : décision textuelle requise")
    actions = recommandation.get("actions", [])
    if type(actions) is not list or len(actions) > 32:
        raise ValueError("REJ-GOUVERNANCE-ENTREE : actions = liste bornée")
    verdicts, vus = [], set()
    for action in actions:
        if not isinstance(action, Mapping) or not _texte(action.get("id"), 64) or action["id"] in vus:
            raise ValueError("REJ-GOUVERNANCE-ENTREE : action {id, type, description} distincte requise")
        vus.add(action["id"])
        genre = action.get("type")
        if genre in ACTIONS_SENSIBLES:
            verdicts.append(
                {
                    "action": action["id"],
                    "type": genre,
                    "verdict": "VALIDATION_HUMAINE_REQUISE",
                    "mandataire": ACTIONS_SENSIBLES[genre],
                    "effet_autorise": False,
                }
            )
        elif genre in ("suivi_interne", "information"):
            verdicts.append(
                {
                    "action": action["id"],
                    "type": genre,
                    "verdict": "PROPOSABLE",
                    "mandataire": None,
                    "effet_autorise": False,
                }
            )
        else:
            verdicts.append(
                {
                    "action": action["id"],
                    "type": genre,
                    "verdict": "REFUSEE_TYPE_INCONNU",
                    "mandataire": None,
                    "effet_autorise": False,
                }
            )
    resultat = {
        "type": "VERDICT_GOUVERNANCE",
        "decision": recommandation["decision"],
        "actions": verdicts,
        "decision_majeure": any(v["verdict"] == "VALIDATION_HUMAINE_REQUISE" for v in verdicts),
        "autorite_d_effet": False,
    }
    resultat["verdict_id"] = hashlib.sha256(
        json.dumps(resultat, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return resultat
