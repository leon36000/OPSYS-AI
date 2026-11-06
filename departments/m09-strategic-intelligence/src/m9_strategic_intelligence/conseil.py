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
import unicodedata
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
_SIGNES_NUMERIQUES = r"[+\-\u2212\uff0d\ufe63]"
_BORDURE_NUMERIQUE = r"[\w.,\uff0c\uff0e\u066b\u066c\u2027\u2009+\-\u2212$]"
_CONTEXTE_TIRET_COMPAT = r"(?:(?<=\d[\uff0d\ufe63])|(?<![\uff0d\ufe63]))"
_BASE_NOMBRE_MONTANT = r"(?:\d{1,3}(?:,\d{3})+|\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)"
_BASE_NOMBRE_NUMERIQUE = r"(?:\d{1,3}(?:,\d{3})+|\d[\d \u00a0\u202f]*)"
# Montant, pourcentage ou décimal à deux chiffres : une quantité que le code calcule et qu'un modèle ne produit pas.
_MONTANT = re.compile(
    rf"{_CONTEXTE_TIRET_COMPAT}(?<!{_BORDURE_NUMERIQUE}){_SIGNES_NUMERIQUES}?{_BASE_NOMBRE_MONTANT}"
    r"(?:[.,]\d{1,2})?\s?(?:\$|CAD|%|dollars?|k\$)(?!\d|[.,]\d)"
    rf"|{_CONTEXTE_TIRET_COMPAT}(?<!{_BORDURE_NUMERIQUE})(?:{_SIGNES_NUMERIQUES}\$|\$\s*{_SIGNES_NUMERIQUES}?){_BASE_NOMBRE_MONTANT}"
    r"(?:[.,]\d{1,2})?(?:\s?(?:CAD|%|dollars?|k\$|\$))?(?!\d|[.,]\d)"
    rf"|{_CONTEXTE_TIRET_COMPAT}(?<!{_BORDURE_NUMERIQUE}){_SIGNES_NUMERIQUES}?\d+[.,]\d{{2}}(?![\w]|[.,]\d)"
)
_SEQUENCE_NUMERIQUE_MONTANT = r"\d[\d.,\uff0c\uff0e\u066b\u066c\u2027\u2009]*"
_UNITE_MONTANT = r"(?:CAD|%|dollars?|k\$|\$)"
# Candidats monétaires plus larges que _MONTANT : ils servent seulement à repérer et refuser les
# tokens avec devise/unité dont la ponctuation ne forme pas un montant reconnu. Les dates ISO et
# identifiants sans devise ne correspondent pas à cette règle.
_MONTANT_CANDIDAT = re.compile(
    rf"(?<!{_BORDURE_NUMERIQUE})(?:{_SIGNES_NUMERIQUES}\$|\$\s*{_SIGNES_NUMERIQUES}?)"
    rf"{_SEQUENCE_NUMERIQUE_MONTANT}(?:\s?{_UNITE_MONTANT})?(?![\w])"
    rf"|(?<!{_BORDURE_NUMERIQUE}){_SIGNES_NUMERIQUES}?{_SEQUENCE_NUMERIQUE_MONTANT}"
    rf"\s?{_UNITE_MONTANT}(?![\w])"
)
_DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DATE_COMPAT = re.compile(r"\b\d{4}[-\uff0d\ufe63]\d{2}[-\uff0d\ufe63]\d{2}\b")
_DATE_SEQUENCES_NUMERIQUES = re.compile(
    r"\b\d{4}[-/\uff0d\ufe63\u2212\u2010\u2011\u2012\u2013\u2014\uff0f]"
    r"\d{2}[-/\uff0d\ufe63\u2212\u2010\u2011\u2012\u2013\u2014\uff0f]\d{2}\b"
)
_SEQUENCE_NUMERIQUE_MALFORMEE = re.compile(
    rf"(?<!{_BORDURE_NUMERIQUE}){_SIGNES_NUMERIQUES}?\d+(?:[.,\uff0c\uff0e\u066b\u066c\u2027\u2009]\d+)+(?![\w])"
)
_IDENTIFIANT_ETIQUETTE = re.compile(
    r"(?i)(?<![\w])(?:version|lot|id|identifiant|référence|reference|ref|code)\s*(?:[:#]\s*)?$"
)
_NUMERIQUE = re.compile(
    rf"\s*{_CONTEXTE_TIRET_COMPAT}(?:(?:{_SIGNES_NUMERIQUES}\$|\$\s*{_SIGNES_NUMERIQUES}?)\s*|{_SIGNES_NUMERIQUES}?)"
    rf"{_BASE_NOMBRE_NUMERIQUE}(?:[.,]\d+)?\s*(?:\$|CAD|%)?\s*"
)
_EMOJI_CLE = re.compile(r"(?<!\d)[0-9#*]\ufe0f?\u20e3(?!\d)")
_SEPARATEURS_NUMERIQUES = frozenset(".,:/+-−\uff0d\ufe63$%#*\uff0c\uff0e\u066b\u066c\u2027\u2009")
_SIGNES_ET_DEVISES = frozenset("+-−\uff0d\ufe63$")


def _groupe_chiffres_autour_espace(texte: str, position: int, direction: int) -> tuple[int, int]:
    index = position + direction
    while 0 <= index < len(texte) and unicodedata.category(texte[index]) in {"Cf", "Mn", "Mc", "Me"}:
        index += direction
    debut = fin = index
    while 0 <= index < len(texte) and (
        texte[index].isdecimal() or unicodedata.category(texte[index]) in {"Cf", "Mn", "Mc", "Me"}
    ):
        if texte[index].isdecimal():
            debut = min(debut, index)
            fin = max(fin, index + 1)
        index += direction
    return debut, fin


def _espace_est_groupement_numerique(texte: str, position: int) -> bool:
    debut_gauche, fin_gauche = _groupe_chiffres_autour_espace(texte, position, -1)
    debut_droite, fin_droite = _groupe_chiffres_autour_espace(texte, position, 1)
    gauche = fin_gauche - debut_gauche
    droite = fin_droite - debut_droite
    # Les espaces autour d'une devise font partie du même token, sans relier deux valeurs distinctes.
    index_droite = position + 1
    while index_droite < len(texte) and (
        texte[index_droite].isspace() or unicodedata.category(texte[index_droite]) in {"Cf", "Mn", "Mc", "Me"}
    ):
        index_droite += 1
    index_gauche = position - 1
    while index_gauche >= 0 and (
        texte[index_gauche].isspace() or unicodedata.category(texte[index_gauche]) in {"Cf", "Mn", "Mc", "Me"}
    ):
        index_gauche -= 1
    if gauche and index_droite < len(texte) and unicodedata.category(texte[index_droite]) == "Sc":
        return True
    if droite and index_gauche >= 0 and unicodedata.category(texte[index_gauche]) == "Sc":
        return True
    if not 1 <= gauche <= 3 or droite != 3:
        return False
    # Une date ou une heure suivie d'une autre valeur ne forme pas un groupe de milliers.
    prefixe = "".join(
        caractere
        for caractere in texte[:debut_gauche]
        if unicodedata.category(caractere) not in {"Cf", "Mn", "Mc", "Me"}
    )
    separateur_date = r"[-/\uff0d\ufe63\u2212\u2010\u2011\u2012\u2013\u2014\uff0f]"
    if re.search(rf"\d{{4}}{separateur_date}\d{{2}}{separateur_date}$", prefixe):
        return False
    return not re.search(r"\d{1,2}:\d{2}$", prefixe)


def _caractere_atome_numerique(texte: str, position: int) -> bool:
    caractere = texte[position]
    categorie = unicodedata.category(caractere)
    if caractere.isdecimal() or categorie in {"Cf", "Mn", "Mc", "Me"}:
        return True
    if categorie in {"Zs", "Zl", "Zp"} and caractere not in {" ", "\u00a0", "\u202f"}:
        return True
    if categorie == "Sc":
        return any(
            0 <= voisin < len(texte)
            and (
                texte[voisin].isdecimal()
                or unicodedata.category(texte[voisin]) in {"Cf", "Mn", "Mc", "Me"}
                or texte[voisin] in _SIGNES_ET_DEVISES
                or (texte[voisin].isspace() and _espace_est_groupement_numerique(texte, voisin))
            )
            for voisin in (position - 1, position + 1)
        )
    if caractere.isspace():
        return _espace_est_groupement_numerique(texte, position)
    if caractere not in _SEPARATEURS_NUMERIQUES:
        return False
    gauche = position > 0 and (
        texte[position - 1].isdecimal()
        or unicodedata.category(texte[position - 1]) in {"Cf", "Mn", "Mc", "Me"}
    )
    droite = position + 1 < len(texte) and (
        texte[position + 1].isdecimal()
        or unicodedata.category(texte[position + 1]) in {"Cf", "Mn", "Mc", "Me"}
    )
    if caractere in {"-", "+", "\u2212", "\uff0d", "\ufe63"}:
        return gauche and droite or (not gauche and droite)
    return gauche and droite


def _marque_adjacent_signe_ou_devise(texte: str, position: int) -> bool:
    marques = {"Cf", "Mn", "Mc", "Me"}
    for direction in (-1, 1):
        voisin = position + direction
        while 0 <= voisin < len(texte) and unicodedata.category(texte[voisin]) in marques:
            voisin += direction
        while 0 <= voisin < len(texte) and texte[voisin].isspace():
            voisin += direction
        if voisin < 0 or voisin >= len(texte):
            continue
        if texte[voisin] in _SIGNES_ET_DEVISES or unicodedata.category(texte[voisin]) == "Sc":
            return True
        if texte[voisin].isdecimal():
            while 0 <= voisin < len(texte):
                caractere = texte[voisin]
                if (
                    caractere.isdecimal()
                    or unicodedata.category(caractere) in marques
                    or caractere.isspace()
                    or caractere in ".,"
                ):
                    voisin += direction
                    continue
                return caractere in _SIGNES_ET_DEVISES or unicodedata.category(caractere) == "Sc"
    return False


def _sequences_numeriques_marquees(texte: str) -> list[tuple[str, int, int, bool]]:
    """Repère les chiffres adjacents à des formats invisibles ou marques combinantes.

    Les dates/plages ne sont jamais normalisées : une forme marquée est tolérée seulement si cette
    séquence complète est citée textuellement. Les keycaps isolées et les marques sans chiffre sont
    laissées intactes.
    """
    keycap_positions = {
        position
        for match in _EMOJI_CLE.finditer(texte)
        for position in range(*match.span())
    }
    prefixes_chiffres = [0]
    for caractere in texte:
        prefixes_chiffres.append(prefixes_chiffres[-1] + caractere.isdecimal())
    resultats = []
    position = 0
    while position < len(texte):
        if not _caractere_atome_numerique(texte, position):
            position += 1
            continue
        debut = position
        while position < len(texte) and _caractere_atome_numerique(texte, position):
            position += 1
        fin = position
        while debut < fin and texte[debut].isspace():
            debut += 1
        while fin > debut and texte[fin - 1].isspace():
            fin -= 1
        if debut == fin:
            continue
        total_chiffres = prefixes_chiffres[fin] - prefixes_chiffres[debut]
        douteux = False
        for marque in range(debut, fin):
            categorie = unicodedata.category(texte[marque])
            if categorie not in {"Cf", "Mn", "Mc", "Me", "Zs", "Zl", "Zp"}:
                continue
            if texte[marque] in {" ", "\u00a0", "\u202f"} or marque in keycap_positions:
                continue
            avant = prefixes_chiffres[marque] - prefixes_chiffres[debut]
            apres = prefixes_chiffres[fin] - prefixes_chiffres[marque + 1]
            if categorie == "Cf":
                # Un marqueur de format peut aussi suffixer/préfixer un chiffre seul; sinon un chiffre
                # cité comme ``1<U+200B> $`` autoriserait sa forme nette dans une autre affirmation.
                douteux = avant > 0 and apres > 0 or (
                    total_chiffres > 0 and _marque_adjacent_signe_ou_devise(texte, marque)
                )
            elif categorie.startswith("Z"):
                douteux = avant > 0 and apres > 0
            elif total_chiffres > 0:
                gauche = marque - 1
                while gauche >= debut and unicodedata.category(texte[gauche]) in {"Cf", "Mn", "Mc", "Me"}:
                    gauche -= 1
                douteux = gauche >= debut and texte[gauche].isdecimal()
                if not douteux:
                    douteux = _marque_adjacent_signe_ou_devise(texte, marque)
            if douteux:
                break
        if douteux:
            tronquee = fin - debut > MAX_TEXTE
            resultats.append((texte[debut : min(fin, debut + MAX_TEXTE)], debut, fin, tronquee))
    return resultats


def _masquer_sequences_numeriques_marquees(texte: str) -> str:
    caracteres = list(texte)
    for _token, debut, fin, _tronquee in _sequences_numeriques_marquees(texte):
        caracteres[debut:fin] = [" "] * (fin - debut)
    return "".join(caracteres)


def _sequence_marquee_exactement_citee(
    texte: str, token: str, debut: int, valeurs_citees: Sequence[str], *, tronquee: bool = False
) -> bool:
    if tronquee:
        return False
    if texte in valeurs_citees:
        return True
    for valeur in valeurs_citees:
        position = valeur.find(token)
        while position >= 0:
            fin = position + len(token)
            avant = valeur[position - 1] if position else ""
            apres = valeur[fin] if fin < len(valeur) else ""
            if not (avant.isalnum() or avant == "_") and not (apres.isalnum() or apres == "_"):
                match = re.compile(re.escape(token)).search(texte, debut)
                etiquette = _IDENTIFIANT_ETIQUETTE.search(texte[:debut])
                if etiquette is None or (
                    match and _identifiant_numerique_exactement_cite(texte, match, valeurs_citees)
                ):
                    return True
            position = valeur.find(token, position + 1)
    return False


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
        ("m8.synthese_direction", "m10.faits_analytiques"),
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
        (
            "m5.prevision_tresorerie", "m5.rentabilite_chantier", "m5.comptes_a_recevoir", "m5.comptes_a_payer",
            "m5.calendrier_obligations", "m5.statut_revue_fiscale",
        ),  # fmt: skip
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
        ("m2.leads", "m2.relances", "m2.analyse_pipeline", "m2.prevision_pipeline"),
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
    chiffres = re.sub(r"[^\d.,]", "", texte)
    if "," in chiffres and "." in chiffres:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d+", chiffres):
            chiffres = chiffres.replace(",", "")
        else:
            return None
    elif re.fullmatch(r"\d{1,3}(?:,\d{3}){2,}", chiffres):
        # Plusieurs groupes complets de trois ne peuvent pas être une décimale seule.
        chiffres = chiffres.replace(",", "")
    elif re.fullmatch(r"\d{1,3},\d{3}", chiffres):
        # Un seul groupe de trois après la virgule est ambigu sans convention de locale :
        # il peut s'agir de milliers ou d'une décimale. Ne l'interprète pas comme 8.400.
        return None
    else:
        chiffres = chiffres.replace(",", ".")
    try:
        nombre = Decimal(chiffres)
    except InvalidOperation:
        return None
    debut = texte.lstrip()
    moins = ("-", "\u2212", "\uff0d", "\ufe63")
    if debut.startswith(moins) or (
        debut.startswith("$") and debut[1:].lstrip().startswith(moins)
    ):
        return nombre.copy_negate()
    return nombre


def _montants_malformes(texte: str):
    """Candidats monétaires ambigus ou non valides, sans fragment numérique autorisable."""
    return [
        m for m in _MONTANT_CANDIDAT.finditer(texte)
        if _MONTANT.fullmatch(m.group(0)) is None or _nombre(m.group(0)) is None
    ]

def _masquer_montants_malformes(texte: str) -> str:
    """Retire les candidats malformés avant toute extraction pour interdire les captures partielles."""
    caracteres = list(texte)
    for match in _montants_malformes(texte):
        caracteres[match.start() : match.end()] = [" "] * (match.end() - match.start())
    return "".join(caracteres)

def _identifiant_numerique_exactement_cite(texte: str, match, valeurs_citees: Sequence[str]) -> bool:
    etiquette = _IDENTIFIANT_ETIQUETTE.search(texte[: match.start()])
    if etiquette is None:
        return False
    identifiant = texte[etiquette.start() : match.end()]
    for valeur in valeurs_citees:
        position = valeur.find(identifiant)
        while position >= 0:
            fin = position + len(identifiant)
            avant = valeur[position - 1] if position else ""
            apres = valeur[fin] if fin < len(valeur) else ""
            if not (avant.isalnum() or avant == "_") and not (apres.isalnum() or apres == "_"):
                return True
            position = valeur.find(identifiant, position + 1)
    return False

def _sequences_numeriques_malformees(texte: str, valeurs_citees: Sequence[str]) -> list[str]:
    """Tokens numériques composites non pris en charge, hors dates, citations exactes et IDs étiquetés."""
    texte_sans_montants = _masquer_montants_malformes(texte)
    texte_a_scanner = _DATE_SEQUENCES_NUMERIQUES.sub(" ", texte_sans_montants)
    libres = []
    for match in _SEQUENCE_NUMERIQUE_MALFORMEE.finditer(texte_a_scanner):
        token = match.group(0)
        if _NUMERIQUE.fullmatch(token) is not None or token in valeurs_citees:
            continue
        if not _identifiant_numerique_exactement_cite(texte_a_scanner, match, valeurs_citees):
            libres.append(token)
    return libres

def chiffres_libres(texte: str, valeurs_citees: Sequence[str]) -> list[str]:
    """Montants, pourcentages, décimaux et dates ISO d'un texte libre absents de toute valeur CITÉE par la même sortie.

    « Le code calcule, le modèle explique » : un modèle peut reprendre une valeur qu'il cite, jamais en produire une
    (somme, projection, zéro pour une absence). Les entiers nus et identifiants attachés restent hors de ce garde. Les
    séquences ponctuées non parseables sont refusées, sauf token exactement cité ou identifiant étiqueté et cité ; ce
    contrôle lexical ne classe pas le sens d'autres formats (voir aussi la limite du corpus métier M9.23)."""
    nombres: set[Decimal] = set()
    dates: set[str] = set()
    valeurs_citees_sans_marques = [_masquer_sequences_numeriques_marquees(valeur) for valeur in valeurs_citees]
    for valeur in valeurs_citees_sans_marques:
        valeur_sans_malformes = _masquer_montants_malformes(valeur)
        if _NUMERIQUE.fullmatch(valeur_sans_malformes) and (n := _nombre(valeur_sans_malformes)) is not None:
            nombres.add(n)
        nombres.update(
            n for m in _MONTANT.finditer(valeur_sans_malformes) if (n := _nombre(m.group(0))) is not None
        )
        # Toutes les formes écartées du scan composite sont des dates candidates et ne sont autorisées
        # qu'avec la même orthographe complète dans une citation.
        dates.update(_DATE_SEQUENCES_NUMERIQUES.findall(valeur_sans_malformes))
    texte_sans_marques = _masquer_sequences_numeriques_marquees(texte)
    texte_sans_malformes = _masquer_montants_malformes(texte_sans_marques)
    libres = [
        m.group(0).strip()
        for m in _MONTANT.finditer(texte_sans_malformes)
        if _nombre(m.group(0)) not in nombres
    ]
    libres += [m.group(0).strip() for m in _montants_malformes(texte_sans_marques)]
    libres += _sequences_numeriques_malformees(texte_sans_marques, valeurs_citees_sans_marques)
    libres += [d for d in _DATE_SEQUENCES_NUMERIQUES.findall(texte_sans_marques) if d not in dates]
    libres += [
        token
        for token, debut, _fin, tronquee in _sequences_numeriques_marquees(texte)
        if not _sequence_marquee_exactement_citee(texte, token, debut, valeurs_citees, tronquee=tronquee)
    ]
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

STATUTS_CLASSEMENT_INCERTAIN = frozenset(
    {"CLASSEMENT_NON_VERIFIE", "CLASSEMENT_HISTORIQUE_NON_VERIFIE", "PROPOSABLE"}
)


def classement_incertain(verdict: object) -> bool:
    """Reconnaît le statut actuel et l'ancien statut PROPOSABLE, sans réécrire le registre historique."""
    return type(verdict) is str and verdict in STATUTS_CLASSEMENT_INCERTAIN


def compter_actions_classement_incertain(gouvernance: object) -> int:
    """Compte les catégories déclarées par le modèle mais non garanties par la gouvernance."""
    if not isinstance(gouvernance, Mapping) or type(gouvernance.get("actions")) is not list:
        return 0
    return sum(
        1
        for action in gouvernance["actions"]
        if isinstance(action, Mapping) and classement_incertain(action.get("verdict"))
    )


def verdict_pour_synthese(verdict: object) -> object:
    """Dans une synthèse actuelle, ne pas présenter l'ancien PROPOSABLE comme une classification fiable."""
    return "CLASSEMENT_HISTORIQUE_NON_VERIFIE" if verdict == "PROPOSABLE" else verdict


def empreinte_verdict(gouvernance: Mapping) -> str:
    """Empreinte du contenu d'un verdict, hors son propre identifiant."""
    contenu = {k: v for k, v in gouvernance.items() if k != "verdict_id"}
    return hashlib.sha256(json.dumps(contenu, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def gouverner(recommandation: Mapping) -> dict:
    """Étape gouvernance (code) : classe chaque action proposée ; une action sensible n'est jamais autorisée ici.

    ``recommandation`` : ``{"decision": str, "actions": [{"id", "type", "description"}]}``. Un type inconnu ou
    ``sensible`` sans classe connue est refusé (fail-closed) ; une classe sensible exige l'approbation exacte du
    mandataire nommé ; une déclaration ``suivi_interne`` ou ``information`` est ``CLASSEMENT_NON_VERIFIE`` et ne
    vaut pas approbation. ``decision_majeure`` vaut vrai si au moins un type déclaré est reconnu comme sensible ; faux
    signifie seulement qu'aucun type déclaré n'a reçu ce classement. Faux ne garantit pas l'absence d'une action
    sensible dans la réalité, et ce booléen ne vaut ni validation humaine ni autorisation d'effet. La limite de
    classification est signalée séparément."""
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
                    "verdict": "CLASSEMENT_NON_VERIFIE",
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
        "actions_a_classement_non_verifie": compter_actions_classement_incertain({"actions": verdicts}),
        "autorite_d_effet": False,
    }
    resultat["verdict_id"] = empreinte_verdict(resultat)
    return resultat
