"""Copilote analytique en langage naturel (M8.12) : des questions en français vers un CATALOGUE FERMÉ de mesures.

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge, aucun réseau, aucun modèle de langage. Le copilote ne
GÉNÈRE aucune requête : il reconnaît, dans la question, des mesures du catalogue (``catalogue_mesures``) par leurs
formulations déclarées, et répond avec les valeurs que le moteur (``moteur_mesures``) a lues. Il n'y a ni SQL libre, ni
colonne choisie par l'appelant, ni calcul de tête : chaque chiffre du texte est un texte déjà produit par le moteur.

Ce qu'il fait, dans l'ordre :

1. VALIDE la question (texte, 2 à 400 caractères, aucun caractère de contrôle) ;
2. REFUSE ce qui sort du cadre, avec un code typé et sans jamais exécuter : consigne glissée
(``REJ-COPILOTE-INJECTION``),
   SQL ou code (``REJ-COPILOTE-SQL-REFUSE``), action d'écriture (``REJ-COPILOTE-ACTION-REFUSEE`` : lecture seule),
   donnée personnelle ou classement de personnes (``REJ-COPILOTE-DONNEE-PERSONNELLE``), secret
   (``REJ-COPILOTE-SECRET-REFUSE``) ;
3. RECONNAÎT l'intention parmi un ensemble fermé (valeur, fraîcheur, tendance, santé de l'entreprise, liste des
mesures) ;
4. RÉSOUT la ou les mesures du catalogue. Ce qui n'est pas au catalogue est refusé (``REJ-COPILOTE-HORS-CATALOGUE``) ;
une
   question qui touche plusieurs mesures sans les nommer demande une précision (``precision_requise``) au lieu de
   deviner ;
5. RÉPOND avec la valeur exacte, l'unité, la source, la version de la définition, la fraîcheur et, si la mesure est
périmée,
   inconnue ou non calculable, LE DIT (jamais une valeur périmée présentée comme à jour, jamais un zéro) ;
6. REND UN REÇU : empreinte de la question normalisée (jamais le texte de la question), du catalogue, des valeurs
lues, de
   leur fraîcheur et de l'instant de l'appelant. ``verifier_recu`` le recalcule ; ``recu_correspond`` dit s'il décrit
   encore les mesures actuelles.

Le texte de la question n'est JAMAIS recopié dans la réponse. Le texte d'un fait (détail d'un manque venu d'un autre
département) n'y est pas non plus : seuls les NOMS de ce qui manque, qui appartiennent au code, sont cités.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import catalogue_mesures, encodage, entonnoir, fraicheur_mesures, qualite_mesures, tendances, wallboards

SCHEMA_RECU = "opsys.m8.copilote.recu/v1"
QUESTION_MIN, QUESTION_MAX = 2, 400
MESURES_MAX = 5
PRECISIONS_MAX = 5

STATUT_REPONDU = "repondu"
STATUT_REFUSE = "refuse"
STATUT_PRECISION = "precision_requise"

REJ_QUESTION_INVALIDE = "REJ-COPILOTE-QUESTION-INVALIDE"
REJ_INJECTION = "REJ-COPILOTE-INJECTION"
REJ_SQL = "REJ-COPILOTE-SQL-REFUSE"
REJ_ACTION = "REJ-COPILOTE-ACTION-REFUSEE"
REJ_PERSONNEL = "REJ-COPILOTE-DONNEE-PERSONNELLE"
REJ_SECRET = "REJ-COPILOTE-SECRET-REFUSE"
REJ_HORS_CATALOGUE = "REJ-COPILOTE-HORS-CATALOGUE"
REJ_QUALITE_ECHEC = "REJ-COPILOTE-QUALITE-ECHEC"

INTENTION_VALEUR = "valeur"
INTENTION_FRAICHEUR = "fraicheur"
INTENTION_TENDANCE = "tendance"
INTENTION_SANTE = "sante"
INTENTION_LISTE = "liste"
INTENTION_REFUS = "refus"

MENTION_PROFESSIONNEL = "À valider auprès d'un comptable (CPA) / professionnel qualifié"

_CATEGORIES_CONTROLE = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})

# -- Consignes glissées dans la question (sur la forme NORMALISÉE : sans accents, en minuscules)
# --------------------------
_INJECTION = re.compile(
    r"\b(ignore|ignores|ignorez|oublie|oublies|oubliez|contourne|desactive|neglige)\b.{0,40}\b(instruction|instructions|"
    r"regle|regles|consigne|consignes|restriction|restrictions|garde fou|garde fous|limite|limites|catalogue)\b"
    r"|\b(prompt|system prompt|message systeme|consignes systeme|instructions systeme)\b"
    r"|\b(tu es maintenant|you are now|agis comme|fais semblant|joue le role|mode developpeur|developer mode|jailbreak|"
    r"dan mode)\b"
    r"|\b(ignore|disregard|forget)\b.{0,30}\b(previous|above|all|prior|instructions|rules)\b"
    r"|\b(nouvelle|nouvelles) (instruction|instructions|consigne|consignes|regle|regles)\b"
    r"|\b(reponds|repondez) (uniquement|seulement|toujours|exactement)\b"
    r"|\b(revele|reveler|affiche|montre|dis moi|donne moi)\b.{0,30}\b(tes|ses) "
    r"(instructions|regles|consignes|secrets)\b"
)
_INJECTION_BRUT = re.compile(
    r"<\|[^>]*\|>|\[/?INST\]|```|<\s*/?\s*(system|assistant|script)\b|###\s*(system|instruction)", re.I
)
# -- SQL et code ------------------------------------------------------------------------------------------------------
_SQL = re.compile(
    r"\b(select|insert|update|delete|drop|alter|truncate|union|pragma|attach|exec|execute|create table|from m8_|"
    r"where \w+ ?=|group by|order by|having|join)\b"
)
_SQL_BRUT = re.compile(r";|--|/\*|\*/|\bor\s+1\s*=\s*1\b|\bm8_ent_|\bpont_bi_", re.I)
# -- Actions d'écriture (le copilote est en lecture seule) -------------------------------------------------------------
_ACTION = re.compile(
    r"\b(supprime|supprimer|efface|effacer|modifie|modifier|change|changer|ajoute|ajouter|cree|creer|envoie|envoyer|"
    r"publie|publier|paye|payer|vire|virer|approuve|approuver|enregistre|enregistrer|configure|configurer|fixe|fixer|"
    r"definis|definir|declenche|declencher|lance|lancer|reconstruis|reconstruire|emets|emettre|revoque|revoquer|"
    r"corrige|corriger|remplace|remplacer|mets a jour|mettre a jour|ecris|ecrire|annule|annuler|reinitialise|"
    r"reinitialiser|reecris|ouvre un|ferme le|bloque|debloque|desactive|active|installe|deploie|deployer)\b"
)
# -- Personnes (jamais de détail nominatif ni de classement de personnes) ---------------------------------------------
_PERSONNEL = re.compile(
    r"\b(technicien|techniciens|employe|employes|employee|equipier|equipiers|vendeur|vendeurs|salarie|salaries|"
    r"personne|personnes|nom|noms|prenom|courriel|courriels|email|emails|telephone|telephones|adresse|adresses|nas|"
    r"salaire|salaires|contact|contacts|coordonnees|palmares|classement|classer|ranking|punition|pointage)\b"
    r"|\bqui (est|a|sont|ont)\b|\bclients? (de|du|qui|nomme)\b|\bnom du client\b"
)
# -- Secrets ----------------------------------------------------------------------------------------------------------
# « Comptes à payer » est le NOM d'une mesure (M5), pas l'ordre de payer : seul ce groupe nominal est retiré avant de
# chercher un verbe d'action. « Paye les comptes à payer » reste refusé (le verbe « paye » est resté).
_GROUPE_NOMINAL_A_PAYER = re.compile(r"\b(compte|comptes|facture|factures)\s+a\s+payer\b")
_SECRET = re.compile(
    r"\b(jeton|jetons|token|tokens|mot de passe|mots de passe|password|cle api|cles api|api key|secret|secrets|"
    r"identifiants? de connexion|coffre)\b"
)

_INTENTION_SANTE = re.compile(r"\b(sante|score|indice|bien portante|va bien|se porte)\b")
_INTENTION_LISTE = re.compile(
    r"\b(quelles? (sont )?(les )?(mesures?|metriques?|indicateurs?)|que peux tu|que sais tu|"
    r"qu est ce que tu (peux|sais)|"
    r"liste (des |de tes )?(mesures?|metriques?|indicateurs?)|aide|menu|catalogue)\b"
)
_INTENTION_TENDANCE = re.compile(r"\b(evolution|evolue|evoluer|tendance|historique|progression|progresse|variation)\b")
_INTENTION_FRAICHEUR = re.compile(
    r"\b(a jour|perime|perimee|perimes|perimees|fraiche|fraiches|fraicheur|obsolete|recent|recente|date de|"
    r"depuis quand)\b"
)
_MOTS_VIDES = frozenset(
    {
        "a", "actuel", "actuelle", "actuels", "au", "aux", "avec", "avoir", "c", "ca", "ce", "ces", "cet", "cette",
        "chiffre", "chiffres", "combien", "comme", "d", "dans", "de", "des", "dis", "donne", "du", "en",
        "entreprise", "est", "et", "etre", "faire", "fait", "il", "j", "je", "l", "la", "le", "les", "m", "ma",
        "merci", "mes", "moi", "moins", "mon", "n", "ne", "nombre", "nos", "notre", "nous", "on", "ont", "ou",
        "par", "pas", "peux", "plait", "plus", "pour", "que", "quel", "quelle", "quelles", "quels", "qui", "quoi",
        "s", "sans", "sont", "sur", "svp", "t", "ta", "te", "tes", "ton", "total", "tu", "un", "une", "va",
        "valeur", "vont", "y"
    }
)


def _racine(mot: str) -> str:
    """Racine légère d'un mot normalisé (pluriel et féminin) : ``acceptes``, ``acceptees`` et ``accepte`` se
    rejoignent."""
    for suffixe in ("ees", "es", "ee", "s", "x", "e"):
        if mot.endswith(suffixe) and len(mot) - len(suffixe) >= 3:
            return mot[: -len(suffixe)]
    return mot


# Mots de liaison sans valeur de désignation : « combien de leads » et « leads » désignent la même mesure.
_LIAISONS = frozenset(["combien", "nombre", "de", "du", "des", "d", "le", "la", "les", "l", "un", "une"])


def _racines(texte_normalise: str) -> frozenset[str]:
    return frozenset(_racine(mot) for mot in texte_normalise.split() if mot not in _LIAISONS)


def _assainir_question(question: Any) -> str:
    if not isinstance(question, str):
        raise ValueError(f"{REJ_QUESTION_INVALIDE} : la question est un texte")
    texte = unicodedata.normalize("NFKC", question).strip()
    if any(unicodedata.category(c) in _CATEGORIES_CONTROLE for c in texte if c not in "\n\t"):
        raise ValueError(f"{REJ_QUESTION_INVALIDE} : caractères de contrôle ou invisibles refusés")
    texte = " ".join(texte.split())
    if not QUESTION_MIN <= len(texte) <= QUESTION_MAX:
        raise ValueError(f"{REJ_QUESTION_INVALIDE} : {QUESTION_MIN} à {QUESTION_MAX} caractères attendus")
    if not any(c.isalpha() for c in texte):
        raise ValueError(f"{REJ_QUESTION_INVALIDE} : la question ne contient aucune lettre")
    return texte


def classer_securite(question: str) -> tuple[str, str] | None:
    """Le code et la raison du refus si la question sort du cadre, sinon ``None``. L'ordre compte : une consigne glissée
    l'emporte sur tout, puis le SQL, les secrets, les personnes, les actions."""
    normalisee = catalogue_mesures.normaliser(question)
    brut = unicodedata.normalize("NFKC", question)
    if _INJECTION.search(normalisee) or _INJECTION_BRUT.search(brut):
        return REJ_INJECTION, "La question contient une consigne adressée à l'assistant : elle n'est pas exécutée."
    if _SQL.search(normalisee) or _SQL_BRUT.search(brut):
        return REJ_SQL, "Le copilote ne génère ni n'exécute de SQL : il répond seulement avec les mesures du catalogue."
    if _SECRET.search(normalisee):
        return REJ_SECRET, "Les secrets, jetons et identifiants ne sont jamais lus ni montrés par le copilote."
    if _PERSONNEL.search(normalisee):
        return REJ_PERSONNEL, (
            "Aucune donnée personnelle ni classement de personnes : les mesures du catalogue sont des mesures "
            "d'entreprise, sans technicien, client ni contact."
        )
    if _ACTION.search(_GROUPE_NOMINAL_A_PAYER.sub(" ", normalisee)):
        return REJ_ACTION, "Le copilote est en lecture seule : il ne modifie, n'envoie ni ne déclenche rien."
    return None


# ---------------------------------------------------------------------------
# Résolution des mesures
# ---------------------------------------------------------------------------
def _correspondances(question_normalisee: str, catalogue: dict[str, Any]) -> list[tuple[str, frozenset[str]]]:
    """Les mesures dont une formulation déclarée (ou le nom gouverné) est contenue dans la question : toutes ses racines
    s'y trouvent. Une correspondance qui n'est qu'une partie d'une plus précise (autre mesure) est écartée."""
    racines_question = _racines(question_normalisee)
    trouvees: dict[str, frozenset[str]] = {}
    for entree in catalogue["mesures"]:
        formes = [*entree["synonymes_normalises"], catalogue_mesures.normaliser(entree["nom"])]
        for forme in formes:
            racines = _racines(forme)
            if racines and racines <= racines_question and len(racines) >= len(trouvees.get(entree["metric_id"], ())):
                trouvees[entree["metric_id"]] = racines
    retenues = []
    for metric_id, racines in trouvees.items():
        if not any(racines < autres for autre_id, autres in trouvees.items() if autre_id != metric_id):
            retenues.append((metric_id, racines))
    return retenues


def _propositions(question_normalisee: str, catalogue: dict[str, Any]) -> list[dict[str, str]]:
    """Mesures qui partagent au moins un mot significatif avec la question : de quoi PRÉCISER, jamais de quoi
    deviner."""
    utiles = {_racine(m) for m in question_normalisee.split() if m not in _MOTS_VIDES and len(m) >= 4}
    scores = []
    for entree in catalogue["mesures"]:
        formes = " ".join([*entree["synonymes_normalises"], catalogue_mesures.normaliser(entree["nom"])])
        communs = utiles & _racines(formes)
        if communs:
            scores.append((-len(communs), entree["metric_id"], entree["nom"]))
    return [{"metric_id": m, "nom": nom} for _, m, nom in sorted(scores)[:PRECISIONS_MAX]]


# ---------------------------------------------------------------------------
# Réponse
# ---------------------------------------------------------------------------
def _chiffres_de(valeurs: list[str]) -> list[str]:
    return sorted({v for v in valeurs if v})


def _ligne_mesure(mesure: dict[str, Any]) -> dict[str, Any]:
    fraicheur = mesure["fraicheur"]
    return {
        "metric_id": mesure["metric_id"],
        "nom": mesure["nom"],
        "valeur": mesure["valeur"],
        "valeur_affichee": wallboards.formater_valeur(mesure["valeur"], mesure["unite"]),
        "unite": mesure["unite"],
        "statut": mesure["statut"],
        "source": mesure["source"],
        "proprietaire": mesure["proprietaire"],
        "version_definition": mesure["version_definition"],
        "dernier_fait_le": mesure["dernier_fait_le"],
        "sensibilite": mesure["sensibilite"],
        "fraicheur": {
            "statut": fraicheur["statut"],
            "age_s": fraicheur["age_s"],
            "fenetre_s": fraicheur["fenetre_s"],
            "motif": fraicheur["motif"],
        },
        "a_jour": fraicheur["peut_etre_montree_comme_a_jour"] and mesure["statut"] == entonnoir.STATUT_CALCULEE,
        "manque": [m["champ"] for m in mesure["manque"]],
        "couverture": mesure.get("couverture") or {"etat": "complete"},
        "qualite_en_echec": qualite_mesures.en_echec(mesure),
        "pastille": (mesure.get("pastille") or {}).get("code"),
    }


# La phrase d'une mesure BLOQUÉE par le contrôle de qualité : elle ne cite jamais la valeur douteuse (il n'y en a
# aucune, le moteur l'a retenue) et ne contient aucun chiffre.
_PHRASE_QUALITE_ECHEC = (
    "BLOQUÉE par le contrôle de qualité des données : la donnée reçue à la source est aberrante ou incohérente. Aucune "
    "valeur n'est donnée plutôt qu'un chiffre douteux ; le rapport de qualité nomme la règle en échec et le geste de "
    "correction."
)


def _couverture_partielle(ligne: dict[str, Any]) -> bool:
    return ligne["statut"] == entonnoir.STATUT_CALCULEE and ligne["couverture"].get("etat") == "partielle"


def _nombres_de_couverture(ligne: dict[str, Any]) -> list[str]:
    """Les nombres que la phrase de couverture cite (n sur N, jours sans relevé) : ceux du moteur, comme la valeur."""
    if not _couverture_partielle(ligne):
        return []
    return [str(v) for v in ligne["couverture"].values() if isinstance(v, int) and not isinstance(v, bool)]


def _mention_couverture(ligne: dict[str, Any]) -> str:
    """La phrase qui dit qu'une valeur ne couvre qu'une partie de ce qu'elle devrait couvrir : jamais présentée comme
    complète, même quand elle est à jour."""
    if not _couverture_partielle(ligne):
        return ""
    return f" Couverture PARTIELLE : {ligne['couverture']['raison']}."


def _phrase_valeur(ligne: dict[str, Any]) -> str:
    return _phrase_valeur_brute(ligne) + _mention_couverture(ligne)


def _phrase_valeur_brute(ligne: dict[str, Any]) -> str:
    fraicheur = ligne["fraicheur"]
    nom = ligne["nom"]
    if ligne["qualite_en_echec"]:
        return f"{nom} : {_PHRASE_QUALITE_ECHEC}"
    age = "" if fraicheur["age_s"] is None else fraicheur_mesures.formater_duree(fraicheur["age_s"])
    if ligne["statut"] != entonnoir.STATUT_CALCULEE:
        manque = ", ".join(ligne["manque"]) or "une donnée"
        return f"{nom} : non calculable pour l'instant (il manque : {manque}). Aucune valeur n'est donnée."
    if ligne["a_jour"]:
        if fraicheur["statut"] == fraicheur_mesures.STATUT_NON_APPLICABLE:
            return f"{nom} : {ligne['valeur_affichee']} (cumul de chantiers terminés)."
        return f"{nom} : {ligne['valeur_affichee']} (à jour, dernier fait il y a {age})."
    if fraicheur["statut"] == fraicheur_mesures.STATUT_PERIME:
        return (
            f"{nom} : la dernière valeur connue est {ligne['valeur_affichee']}, mais elle est PÉRIMÉE "
            f"(dernier fait il y a {age}) : ne vous y fiez pas."
        )
    return (
        f"{nom} : la dernière valeur connue est {ligne['valeur_affichee']}, mais sa fraîcheur est INCONNUE "
        "(aucun instant de fait fiable) : ne vous y fiez pas."
    )


def _phrase_fraicheur(ligne: dict[str, Any]) -> str:
    fraicheur = ligne["fraicheur"]
    if ligne["qualite_en_echec"]:
        return f"{ligne['nom']} : bloquée par le contrôle de qualité, donc sans valeur à dater."
    if ligne["statut"] != entonnoir.STATUT_CALCULEE:
        return f"{ligne['nom']} : non calculable, donc sans valeur à dater."
    if fraicheur["statut"] == fraicheur_mesures.STATUT_A_JOUR:
        return (
            f"{ligne['nom']} est à jour : dernier fait il y a {fraicheur_mesures.formater_duree(fraicheur['age_s'])} "
            f"(fenêtre attendue {fraicheur_mesures.formater_duree(fraicheur['fenetre_s'])})."
        )
    if fraicheur["statut"] == fraicheur_mesures.STATUT_NON_APPLICABLE:
        return f"{ligne['nom']} : cumul de chantiers terminés, la fraîcheur ne s'y applique pas."
    if fraicheur["statut"] == fraicheur_mesures.STATUT_PERIME:
        return (
            f"{ligne['nom']} est PÉRIMÉE : dernier fait il y a {fraicheur_mesures.formater_duree(fraicheur['age_s'])}, "
            f"fenêtre attendue {fraicheur_mesures.formater_duree(fraicheur['fenetre_s'])}."
        )
    return f"{ligne['nom']} : fraîcheur inconnue (aucun instant de fait fiable)."


def _phrase_tendance(
    ligne: dict[str, Any], historique: list[dict[str, Any]] | None, maintenant_cle: str
) -> tuple[str, list[str]]:
    if ligne["qualite_en_echec"]:
        return f"{ligne['nom']} : bloquée par le contrôle de qualité, aucune tendance n'est donnée.", []
    if not historique:
        return f"{ligne['nom']} : aucun historique enregistré dans l'entrepôt (il n'a pas encore été construit).", []
    entree = {"metric_id": ligne["metric_id"], "version_definition": ligne["version_definition"]}
    comptes, _, valeurs, futurs = tendances._preparer(historique, entree, maintenant_cle)
    exclus = sum(comptes.values()) + len(futurs)
    reserve = (
        f" {exclus} observation(s) futures ou non comparables sont exclues."
        if exclus else ""
    )
    if len(valeurs) < 2:
        return (
            f"{ligne['nom']} : un seul point d'historique ({valeurs[0]['valeur']}), pas assez pour une tendance."
            if valeurs
            else f"{ligne['nom']} : l'historique ne contient aucune valeur calculée à couverture complète."
        ) + reserve, ([str(valeurs[0]["valeur"])] if valeurs else []) + ([str(exclus)] if exclus else [])
    ancien, recent = valeurs[0], valeurs[-1]
    a, b = ancien["valeur"], recent["valeur"]
    sens = "en hausse" if b > a else "en baisse" if b < a else "stable"
    phrase = (
        f"{ligne['nom']} : {sens} entre la construction du {ancien['cle_utc']} ({ancien['valeur']}) "
        f"et celle du {recent['cle_utc']} ({recent['valeur']}), sur {len(valeurs)} points enregistrés."
    )
    chiffres = [str(ancien["valeur"]), str(recent["valeur"]), str(len(valeurs))]
    if exclus:
        chiffres.append(str(exclus))
    if not ligne["a_jour"]:
        phrase += " La mesure actuelle n'est pas à jour : cette tendance vaut jusqu'à la dernière construction."
    phrase += reserve
    return phrase, chiffres


def _phrase_sante(sante_resultat: dict[str, Any] | None) -> tuple[str, list[str]]:
    if sante_resultat is None:
        return "Le score de santé n'a pas été fourni pour cette question.", []
    if sante_resultat["statut"] != "determine":
        raisons = sorted({f"{m['composante']} ({m['raison']})" for m in sante_resultat["manques"]})
        return (
            "Le score de santé est INDÉTERMINÉ : " + "; ".join(raisons) + ". Aucun score n'est donné plutôt qu'un "
            "faux score."
        ), []
    composantes = ", ".join(f"{c['libelle']} {c['score']}" for c in sante_resultat["composantes"])
    chiffres = [sante_resultat["score"], *[c["score"] for c in sante_resultat["composantes"]]]
    texte = f"Score de santé : {sante_resultat['score']} sur 100 ({composantes}). {sante_resultat['mention']}"
    return texte, chiffres


def _recu(
    *,
    intention: str,
    question_normalisee: str,
    catalogue: dict[str, Any],
    lignes: list[dict[str, Any]],
    maintenant: str,
    empreinte_registres: str | None,
    code: str | None,
) -> dict[str, Any]:
    corps = {
        "schema": SCHEMA_RECU,
        "intention": intention,
        "code_refus": code,
        "question_empreinte": encodage.empreinte(question_normalisee),
        "version_catalogue": catalogue["version_catalogue"],
        "maintenant": maintenant,
        "empreinte_registres": empreinte_registres,
        "mesures": [
            {
                "metric_id": ligne["metric_id"],
                "valeur": ligne["valeur"],
                "statut": ligne["statut"],
                "version_definition": ligne["version_definition"],
                "dernier_fait_le": ligne["dernier_fait_le"],
                "fraicheur": ligne["fraicheur"]["statut"],
                "couverture": ligne["couverture"]["etat"],
            }
            for ligne in lignes
        ],
    }
    return {**corps, "empreinte": encodage.empreinte(corps)}


def verifier_recu(recu: Any) -> bool:
    """Vrai si l'empreinte correspond au contenu : ce hachage non signé ne prouve pas son authenticité."""
    if not isinstance(recu, dict) or recu.get("schema") != SCHEMA_RECU or not isinstance(recu.get("empreinte"), str):
        return False
    corps = {cle: valeur for cle, valeur in recu.items() if cle != "empreinte"}
    try:
        return encodage.empreinte(corps) == recu["empreinte"]
    except TypeError:
        return False


def recu_correspond(recu: dict[str, Any], mesures: list[dict[str, Any]]) -> bool:
    """Vrai si le condensat est cohérent et les mesures citées ont la même valeur, le même statut et la même
    version de définition dans ``mesures`` (la lecture actuelle du moteur)."""
    if not verifier_recu(recu):
        return False
    actuelles = {m["metric_id"]: m for m in mesures}
    return all(
        (a := actuelles.get(cite["metric_id"])) is not None
        and (a["valeur"], a["statut"], a["version_definition"])
        == (cite["valeur"], cite["statut"], cite["version_definition"])
        for cite in recu["mesures"]
    )


def _refus(
    code: str,
    raison: str,
    *,
    question_normalisee: str,
    catalogue: dict[str, Any],
    maintenant: str,
    empreinte_registres: str | None,
    propositions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "statut": STATUT_REFUSE,
        "intention": INTENTION_REFUS,
        "texte": raison,
        "mesures": [],
        "refus": {"code": code, "raison": raison},
        "propositions": propositions or [],
        "sources": [],
        "mention": None,
        "chiffres": [],
        "recu": _recu(
            intention=INTENTION_REFUS,
            question_normalisee=question_normalisee,
            catalogue=catalogue,
            lignes=[],
            maintenant=maintenant,
            empreinte_registres=empreinte_registres,
            code=code,
        ),
    }


_LIBELLE_DOMAINE = {
    "ventes": "Ventes",
    "marketing": "Marketing",
    "operations": "Opérations",
    "qualite": "Qualité",
    "finance": "Finance",
    "clientele": "Clientèle",
}


def _liste_des_mesures(catalogue: dict[str, Any]) -> str:
    par_domaine: dict[str, list[str]] = {}
    for entree in catalogue["mesures"]:
        par_domaine.setdefault(entree["domaine"], []).append(entree["nom"])
    return " ".join(
        f"{_LIBELLE_DOMAINE.get(domaine, domaine)} : {', '.join(noms)}."
        for domaine, noms in sorted(par_domaine.items())
    )


def repondre(
    question: Any,
    mesures: list[dict[str, Any]],
    catalogue: dict[str, Any],
    *,
    maintenant: str,
    empreinte_registres: str | None = None,
    sante_resultat: dict[str, Any] | None = None,
    historiques: dict[str, list[dict[str, Any]]] | None = None,
    historique_lire: Any | None = None,
) -> dict[str, Any]:
    """La réponse à une question. ``mesures`` est la sortie de ``fraicheur_mesures.lire_mesures_avec_fraicheur``
    (valeur,
    provenance ET fraîcheur de chaque mesure du catalogue). Rend toujours un dictionnaire de même forme : ``statut``
    (``repondu``, ``refuse`` ou ``precision_requise``), ``texte``, ``mesures`` (une ligne par mesure citée), ``refus``,
    ``propositions``, ``sources``, ``mention``, ``chiffres`` (les seuls nombres que le texte contient, tels que le
    moteur
    les a produits) et ``recu``. Une question invalide lève ``ValueError`` (``REJ-COPILOTE-QUESTION-INVALIDE``)."""
    texte_question = _assainir_question(question)
    fraicheur_mesures.lire_maintenant(maintenant)
    normalisee = catalogue_mesures.normaliser(texte_question)
    contexte = {
        "question_normalisee": normalisee,
        "catalogue": catalogue,
        "maintenant": maintenant,
        "empreinte_registres": empreinte_registres,
    }
    refus = classer_securite(texte_question)
    if refus is not None:
        return _refus(refus[0], refus[1], **contexte)
    par_id = {m["metric_id"]: m for m in mesures}

    def repondu(
        intention: str, texte: str, lignes: list[dict[str, Any]], chiffres: list[str], mention: bool = False
    ) -> dict[str, Any]:
        return {
            "statut": STATUT_REPONDU,
            "intention": intention,
            "texte": texte,
            "mesures": lignes,
            "refus": None,
            "propositions": [],
            "sources": sorted({ligne["source"] for ligne in lignes if ligne["source"]}),
            "mention": MENTION_PROFESSIONNEL if mention else None,
            "chiffres": _chiffres_de(chiffres),
            "recu": _recu(
                intention=intention,
                question_normalisee=normalisee,
                catalogue=catalogue,
                lignes=lignes,
                maintenant=maintenant,
                empreinte_registres=empreinte_registres,
                code=None,
            ),
        }

    if _INTENTION_LISTE.search(normalisee):
        return repondu(
            INTENTION_LISTE,
            "Je réponds seulement avec les mesures du catalogue de M8. " + _liste_des_mesures(catalogue),
            [],
            [],
        )
    correspondances = _correspondances(normalisee, catalogue)
    if _INTENTION_SANTE.search(normalisee) and not correspondances:
        texte, chiffres = _phrase_sante(sante_resultat)
        return repondu(INTENTION_SANTE, texte, [], chiffres, mention=True)
    if not correspondances:
        propositions = _propositions(normalisee, catalogue)
        if propositions:
            noms = "; ".join(p["nom"] for p in propositions)
            reponse = _refus(
                REJ_HORS_CATALOGUE,
                f"Je ne reconnais pas une mesure précise. Voulez-vous parler de : {noms} ?",
                propositions=propositions,
                **contexte,
            )
            reponse["statut"] = STATUT_PRECISION
            return reponse
        return _refus(
            REJ_HORS_CATALOGUE,
            "Cette question sort du catalogue de mesures de M8 : je ne réponds pas de mémoire. "
            + _liste_des_mesures(catalogue),
            **contexte,
        )
    identifiants = sorted(m for m, _ in correspondances)
    plusieurs = len(identifiants) > 1
    conjonction = bool(re.search(r"\bet\b|\bainsi que\b|,|\bavec\b", normalisee)) or "," in texte_question
    if plusieurs and not conjonction:
        propositions = [{"metric_id": m, "nom": par_id[m]["nom"]} for m in identifiants][:PRECISIONS_MAX]
        noms = "; ".join(p["nom"] for p in propositions)
        reponse = _refus(
            REJ_HORS_CATALOGUE,
            f"Votre question touche plusieurs mesures. Laquelle voulez-vous : {noms} ?",
            propositions=propositions,
            **contexte,
        )
        reponse["statut"] = STATUT_PRECISION
        return reponse
    if len(identifiants) > MESURES_MAX:
        return _refus(REJ_HORS_CATALOGUE, f"Au plus {MESURES_MAX} mesures par question.", **contexte)
    lignes = [_ligne_mesure(par_id[m]) for m in identifiants]
    if all(ligne["qualite_en_echec"] for ligne in lignes):
        # Toute la question porte sur des mesures que le contrôle de qualité a bloquées : refus expliqué, jamais un
        # chiffre douteux (ni une valeur « de la dernière fois »).
        noms = "; ".join(ligne["nom"] for ligne in lignes)
        reponse = _refus(
            REJ_QUALITE_ECHEC,
            f"Je ne donne pas ce chiffre : {noms}. " + _PHRASE_QUALITE_ECHEC,
            **contexte,
        )
        reponse["mesures"] = lignes
        reponse["sources"] = sorted({ligne["source"] for ligne in lignes if ligne["source"]})
        reponse["recu"] = _recu(
            intention=INTENTION_REFUS,
            question_normalisee=normalisee,
            catalogue=catalogue,
            lignes=lignes,
            maintenant=maintenant,
            empreinte_registres=empreinte_registres,
            code=REJ_QUALITE_ECHEC,
        )
        return reponse
    mention = any(ligne["sensibilite"] == "financier" for ligne in lignes)
    if _INTENTION_TENDANCE.search(normalisee):
        phrases, chiffres = [], []
        maintenant_cle = entonnoir.instant_utc(maintenant)
        if maintenant_cle is None:
            raise ValueError("REJ-COPILOTE-MAINTENANT-INVALIDE : instant normalisé requis pour l'historique")
        for ligne in lignes:
            historique = (
                historique_lire(ligne["metric_id"])
                if historique_lire is not None
                else (historiques or {}).get(ligne["metric_id"])
            )
            phrase, valeurs = _phrase_tendance(ligne, historique, maintenant_cle)
            phrases.append(phrase)
            chiffres += valeurs
        return repondu(INTENTION_TENDANCE, " ".join(phrases), lignes, chiffres, mention)
    if _INTENTION_FRAICHEUR.search(normalisee):
        chiffres = [
            fraicheur_mesures.formater_duree(ligne_lue["fraicheur"]["age_s"])
            for ligne_lue in lignes
            if ligne_lue["fraicheur"]["age_s"] is not None
        ]
        texte = " ".join(_phrase_fraicheur(ligne_lue) for ligne_lue in lignes)
        return repondu(INTENTION_FRAICHEUR, texte, lignes, chiffres, mention)
    chiffres = [ligne_lue["valeur"] for ligne_lue in lignes]
    for ligne_lue in lignes:
        chiffres += _nombres_de_couverture(ligne_lue)
    texte = " ".join(_phrase_valeur(ligne_lue) for ligne_lue in lignes)
    return repondu(INTENTION_VALEUR, texte, lignes, chiffres, mention)


__all__ = [
    "INTENTION_FRAICHEUR",
    "INTENTION_LISTE",
    "INTENTION_REFUS",
    "INTENTION_SANTE",
    "INTENTION_TENDANCE",
    "INTENTION_VALEUR",
    "MENTION_PROFESSIONNEL",
    "REJ_ACTION",
    "REJ_HORS_CATALOGUE",
    "REJ_INJECTION",
    "REJ_PERSONNEL",
    "REJ_QUALITE_ECHEC",
    "REJ_QUESTION_INVALIDE",
    "REJ_SECRET",
    "REJ_SQL",
    "SCHEMA_RECU",
    "STATUT_PRECISION",
    "STATUT_REFUSE",
    "STATUT_REPONDU",
    "classer_securite",
    "recu_correspond",
    "repondre",
    "verifier_recu",
]
