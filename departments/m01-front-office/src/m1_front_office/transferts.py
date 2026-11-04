"""Transfert à un humain avec résumé (PLAN T4.5, DEFINITION-PRODUIT §7 M1.12 : « transférer sans résumé » est interdit).

Un transfert est une main tendue à une personne : une plainte, une urgence de sécurité, ou toute demande que M1 ne doit
pas traiter seul (ventes, estimation, admin, finance, technique, propriétaire). Ce module, pur, dit comment il s'écrit
au registre anti-perte et comment il se relit.

**Le registre est la seule mémoire.** Un transfert est une suite de lignes `transfert` (jamais modifiées) :

- `ouvert` : le type (ensemble fermé, `taxonomie.TYPES_TRANSFERT`), les catégories reconnues, le résumé (obligatoire),
  le destinataire (un RÔLE, lu du profil ; absent, `verdict_destinataire` dit « destinataire à configurer »), le contact
  et les messages couverts ;
- `clos` : une PERSONNE l'a traité (qui, son rôle, par quelle voie, pourquoi).

Un transfert est OUVERT tant qu'aucune ligne `clos` ne lui répond : c'est la file « À voir » du propriétaire
(`attente`), qui ne se viderait jamais sans l'outil de clôture. Les messages du client qui arrivent ensuite sont
inscrits et RATTACHÉS au transfert (`rattache_au_transfert` sur leur ligne) : ils ne se qualifient jamais en lead, la
plainte prime, et la personne les relit (`vue`).

**Le résumé est obligatoire.** Composé par le code (les faits de la conversation : type, termes reconnus, canal, nombre
et heures des messages, lead ou non, contact) ou fourni par l'agent puis CONTRÔLÉ : non vide, borné, sans donnée de
contact brute, passé par le garde-fou des interdits. Le résumé n'emprunte aucun texte du client (les messages sont lus à
côté) : il tient dans la file « À voir » sans donnée personnelle. Aucune heure ici ne vient d'une horloge : c'est
l'heure de réception que la plateforme a livrée avec le message.

**Niveaux d'attente** (`niveau_attente` ; l'ordre de la file est le niveau, puis l'ancienneté :
`approbations.ordre_attente`) : N5 pour une urgence de sécurité ou une menace juridique (le sujet est légal,
DEFINITION-PRODUIT §5), N4 pour une plainte ou un transfert au propriétaire (la réponse engage l'entreprise), N3 pour
les autres (une tâche à prendre).

Module pur : aucune horloge, aucun accès à la base ni au réseau.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opsys import taxonomie

from . import conversation, garde_fou, plaintes, provenance, qualification, verdicts
from . import horodatage as controle_horodatage

TYPE_ENTREE = "transfert"
EVT_OUVERT = "ouvert"
EVT_CLOS = "clos"
EVT_PRISE_EN_CHARGE = "prise_en_charge"
EVT_TENTATIVE_SANS_CONTACT = "tentative_sans_contact"
MARQUE = "rattache_au_transfert"
TYPE_EVENEMENT_TRANSFERT = "m1.transfert_ouvert"
TYPE_EVENEMENT_PLAINTE = "m1.plainte_ouverte"

TYPES = taxonomie.TYPES_TRANSFERT
TYPE_PROPRIETAIRE = "proprietaire"

DECLENCHE_PAR_REGLES = "regles"
DECLENCHE_PAR_AGENT = "agent"
ORIGINE_CODE = "code"
ORIGINE_AGENT = "agent"

NIVEAU_URGENCE_OU_JURIDIQUE = "N5"
NIVEAU_ENGAGEMENT = "N4"
NIVEAU_TACHE = "N3"

RESUME_MAX = 1200
MESSAGES_MAX = 6  # messages couverts par un transfert (les plus récents)
MESSAGES_AFFICHES_MAX = 4  # par lecture : `Capacites` tronque au-delà de 6 000 caractères
EXTRAIT_MAX = 350
MOTIF_MIN = 10
MOTIF_MAX = 500

_LIBELLES = {
    "ventes": "Transfert aux ventes",
    "estimation": "Transfert à l'estimation",
    "admin": "Transfert à l'administration",
    "finance": "Transfert aux finances",
    "plainte": "Plainte",
    "urgence": "Urgence de sécurité",
    "technique": "Transfert technique",
    TYPE_PROPRIETAIRE: "Transfert au propriétaire",
}
_TYPE_D_ATTENTE = {plaintes.TYPE_PLAINTE: "plainte_escaladee", plaintes.TYPE_URGENCE: "urgence_escaladee"}
TYPE_D_ATTENTE_GENERAL = "transfert_humain"

ACTION_PROPOSEE = "lire (m1_lire_transfert), agir auprès du client, puis clore (m1_clore_transfert)"

# M1-E : les deux champs CALCULÉS qui enrichissent un transfert. Ce sont des CODES d'ensembles fermés, jamais un
# texte du client ni une valeur choisie par un modèle. `service`, `ville`, `contact` sont les seuls champs que la
# qualification de M1 peut établir ; `non_evalues` dit ce que le profil n'a pas permis de lire (aucun manque supposé).
CHAMPS_DU_DOSSIER = ("service", "ville", "contact")
INFORMATIONS_EVALUEES = "evaluee"
INFORMATIONS_PARTIELLES = "partielle"
MOTIF_DIAGNOSTIC_INDISPONIBLE = "diagnostic_indisponible"

ACTION_DEMANDER_INFORMATIONS = "demander_informations"
ACTION_TRAITER_LA_PLAINTE = "traiter_la_plainte"
ACTION_TRAITER_L_URGENCE = "traiter_l_urgence"
ACTION_PRENDRE_EN_CHARGE = "prendre_en_charge"
ACTION_VERIFIER_LE_DOSSIER = "verifier_le_dossier"
ACTION_DECISION_APRES_RETRAIT = "decision_humaine_apres_retrait"
ACTIONS_RECOMMANDEES = (
    ACTION_DEMANDER_INFORMATIONS,
    ACTION_TRAITER_LA_PLAINTE,
    ACTION_TRAITER_L_URGENCE,
    ACTION_PRENDRE_EN_CHARGE,
    ACTION_VERIFIER_LE_DOSSIER,
    ACTION_DECISION_APRES_RETRAIT,
)

# Un courriel dans un résumé (PLAN T4.17-g3) : un « @ », un domaine derrière et, juste devant, un caractère qui peut
# faire partie d'une adresse ou d'un mot : lettre, chiffre, `_`, signe permis par la RFC 5322, et aussi un accent
# combinant, un caractère de format, l'apostrophe typographique, un trait d'union Unicode ou le point médian
# (`qualification.dans_un_mot`). L'ancien `[\w.%+'-]@…` ne voyait pas « rene\u0301@x.ca », un accent tapé en deux
# caractères juste devant le « @ ». Ce garde-fou ne peut que refuser plus que lui : jamais moins.
# Temps linéaire (T4.17-g) : un seul départ par « @ », et un domaine ne contient pas de « @ ». La partie locale n'a pas
# à être lue : le verdict est « oui » ou « non ». `tests/test_motifs_lineaires.py` compare ce verdict à une référence
# écrite lettre à lettre et à l'ancien motif (recopié), et mesure des textes de 20 000 et de 100 000 caractères.
_ARROBASE_ET_DOMAINE = re.compile(r"@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")
_SIGNES_D_UNE_ADRESSE = ".%+'-!#$&*/=?^`{|}~"
_DATE_ISO = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?")
_ECHEANCE_RAPPEL = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
_SUITE_DE_CHIFFRES = re.compile(r"\+?\d[\d\s().\-]{5,}\d")
_CHIFFRES_D_UN_TELEPHONE = 7


def _verdict(code: str, detail: str) -> dict[str, str]:
    return verdicts.construire_verdict(code, detail=detail)


def libelle(type_transfert: str) -> str:
    return _LIBELLES[type_transfert]


def niveau_attente(type_transfert: str, categories: Sequence[str]) -> str:
    """Le niveau N de l'attente : N5 pour une urgence de sécurité ou une menace juridique, N4 pour une plainte ou un
    transfert au propriétaire, N3 pour le reste. Détermine l'ordre de la file (le plus élevé d'abord)."""
    if type_transfert == plaintes.TYPE_URGENCE or plaintes.CATEGORIE_JURIDIQUE in categories:
        return NIVEAU_URGENCE_OU_JURIDIQUE
    if type_transfert in (plaintes.TYPE_PLAINTE, TYPE_PROPRIETAIRE):
        return NIVEAU_ENGAGEMENT
    return NIVEAU_TACHE


# ---------------------------------------------------------------------------------------------------------------
# Lire l'état du registre
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EtatTransfert:
    """Un transfert tel que le registre le dit : sa ligne d'ouverture, la ligne qui le clôt (s'il l'est), et les
    messages du client arrivés depuis (rattachés, jamais qualifiés en lead)."""

    ouverture: Mapping[str, Any]
    cloture: Mapping[str, Any] | None
    suivis: tuple[Mapping[str, Any], ...]

    @property
    def ouvert(self) -> bool:
        return self.cloture is None

    @property
    def identifiant(self) -> str:
        return self.ouverture["transfert_id"]


def lire(lignes: Iterable[Mapping[str, Any]]) -> list[EtatTransfert]:
    """Les transferts du registre, dans l'ordre d'ouverture. Une ligne `clos` sans ouverture, ou une seconde ligne
    `clos`, est ignorée : la première fait foi."""
    ouvertures: dict[str, Mapping[str, Any]] = {}
    clotures: dict[str, Mapping[str, Any]] = {}
    rattaches: list[Mapping[str, Any]] = []
    for ligne in lignes:
        type_entree = ligne.get("type_entree")
        if type_entree == TYPE_ENTREE:
            identifiant = ligne.get("transfert_id")
            if ligne.get("evenement") == EVT_OUVERT and identifiant not in ouvertures:
                ouvertures[identifiant] = ligne
            elif ligne.get("evenement") == EVT_CLOS and identifiant in ouvertures and identifiant not in clotures:
                clotures[identifiant] = ligne
        elif type_entree == "signal" and ligne.get(MARQUE):
            rattaches.append(ligne)
    etats = []
    for identifiant, ouverture in ouvertures.items():
        couverts = set(ouverture.get("signaux", ()))
        suivis = tuple(
            s for s in rattaches if s[MARQUE] == identifiant and s.get("signal_id") not in couverts
        )
        etats.append(EtatTransfert(ouverture, clotures.get(identifiant), suivis))
    return etats


def ouverts_de(
    etats: Iterable[EtatTransfert], conversation_id: str, type_transfert: str | None = None
) -> list[EtatTransfert]:
    """Les transferts OUVERTS d'une conversation, éventuellement d'un seul type."""
    return [
        e for e in etats
        if e.ouvert and e.ouverture["conversation_id"] == conversation_id
        and (type_transfert is None or e.ouverture["type_transfert"] == type_transfert)
    ]


def signaux_exclus(lignes: Iterable[Mapping[str, Any]]) -> set[str]:
    """Les signaux que la qualification ne relit plus : ceux qu'un transfert couvre et ceux qui lui sont rattachés. Sans
    cela, les mots d'une plainte rassemblés dans la fenêtre d'une conversation pourraient ouvrir un lead plus tard : la
    plainte prime, même une fois le transfert clos."""
    lignes = list(lignes)
    exclus: set[str] = set()
    for ligne in lignes:
        if ligne.get("type_entree") == TYPE_ENTREE and ligne.get("evenement") == EVT_OUVERT:
            exclus.update(ligne.get("signaux", ()))
        elif ligne.get("type_entree") == "signal" and ligne.get(MARQUE):
            exclus.add(ligne["signal_id"])
    return exclus


def retire(lignes: Iterable[Mapping[str, Any]], conversation_id: str) -> bool:
    """Vrai si le correspondant a écrit un mot de retrait (STOP) : aucun brouillon ne lui est proposé."""
    return any(
        ligne.get("type_entree") == "alerte" and ligne.get("marqueur") == "retrait_consentement"
        and ligne.get("conversation_id") == conversation_id
        for ligne in lignes
    )


# ---------------------------------------------------------------------------------------------------------------
# Le résumé : obligatoire, composé par le code ou fourni par l'agent puis contrôlé
# ---------------------------------------------------------------------------------------------------------------


def _courriel_present(texte: str) -> bool:
    """Vrai si un « @ » suivi d'un domaine a devant lui un caractère qui peut faire partie d'une adresse ou d'un mot."""
    for trouve in _ARROBASE_ET_DOMAINE.finditer(texte):
        debut = trouve.start()
        if debut and (qualification.dans_un_mot(texte[debut - 1]) or texte[debut - 1] in _SIGNES_D_UNE_ADRESSE):
            return True
    return False


def contient_coordonnees(texte: str) -> bool:
    """Vrai si le texte porte un courriel ou un numéro de téléphone (une suite d'au moins sept chiffres, séparateurs
    admis ; une date ou une heure ISO n'en est pas une). Une adresse postale n'est pas reconnue : limite documentée."""
    if _courriel_present(texte):
        return True
    sans_date = _DATE_ISO.sub(" ", texte)
    return any(
        sum(c.isdigit() for c in suite.group()) >= _CHIFFRES_D_UN_TELEPHONE
        for suite in _SUITE_DE_CHIFFRES.finditer(sans_date)
    )


def controler_resume(resume: Any) -> tuple[str | None, bool, dict[str, str] | None]:
    """Contrôle un résumé que l'AGENT fournit : `(texte, sain, None)` s'il est recevable, sinon `(None, True, verdict)`.

    Dans l'ordre : non vide (un résumé vide est refusé, jamais remplacé en silence), d'au plus `RESUME_MAX` caractères,
    neutralisé par le filtre de provenance (le texte du client qu'il recopierait n'est jamais une consigne ; `sain` dit
    si quelque chose l'a été), sans donnée de contact brute (téléphone, courriel : elle est portée à part, jamais
    dans le texte), et passé par `garde_fou.verifier_sortie` (aucun prix, aucune date, aucun engagement, aucun aveu).
    """
    if not isinstance(resume, str) or not resume.strip():
        return None, True, _verdict(
            "REJ-TRANSFERT-RESUME-VIDE",
            "un transfert exige un résumé de la conversation : donne-le, ou omets `resume` pour que le code le compose",
        )
    texte = resume.strip()
    if len(texte) > RESUME_MAX:
        return None, True, _verdict(
            "REJ-TRANSFERT-RESUME-TROP-LONG",
            f"résumé de {len(texte)} caractères : {RESUME_MAX} au plus (l'essentiel ; les messages sont lus à côté)",
        )
    filtre, sain = provenance.filtrer(texte)
    if contient_coordonnees(filtre):
        return None, sain, _verdict(
            "REJ-TRANSFERT-RESUME-CONTACT",
            "le résumé contient un numéro de téléphone ou un courriel : retire-le, le contact est porté à part par le "
            "code (le canal l'a vérifié)",
        )
    verdict = garde_fou.verifier_sortie(filtre)
    if verdict["code"] != "OK":
        return None, sain, verdict
    return filtre, sain, None


def _termes_lisibles(termes: Mapping[str, Sequence[str]]) -> str:
    return " ; ".join(
        f"{plaintes.LIBELLES.get(categorie, categorie)} ({', '.join(f'« {t} »' for t in liste)})"
        for categorie, liste in termes.items()
    )


def _categories_lisibles(categories: Sequence[str]) -> str:
    return ", ".join(plaintes.LIBELLES.get(c, c) for c in categories)


def composer_faits(
    *, type_transfert: str, categories: Sequence[str], termes: Mapping[str, Sequence[str]], canal: str,
    horodatages: Sequence[str], lead: Mapping[str, Any] | None, lead_evalue: bool, contact_source: str | None,
    declenche_par: str, lead_a_verifier: bool = False,
) -> str:
    """Le résumé composé par le code : les faits de la conversation, sans aucun texte du client ni contact. Rien n'est
    inventé : chaque phrase dit ce que le registre établit. `lead_evalue` : une fenêtre de conversation permet de dire
    si la conversation a déjà son lead ; sans fenêtre, chaque message est qualifié seul et le résumé n'en dit rien."""
    origine = "les règles" if declenche_par == DECLENCHE_PAR_REGLES else "l'agent"
    phrases = [f"{libelle(type_transfert)}. Ouvert par : {origine}."]
    if termes:
        phrases.append(f"Termes reconnus : {_termes_lisibles(termes)}.")
    elif categories:
        phrases.append(f"Catégories : {_categories_lisibles(categories)}.")
    if len(horodatages) == 1:
        phrases.append(f"Canal : {canal}. Un message du client, reçu le {horodatages[0]}.")
    else:
        phrases.append(
            f"Canal : {canal}. Messages du client rassemblés : {len(horodatages)}, du {horodatages[0]} au "
            f"{horodatages[-1]}."
        )
    if lead is not None:
        phrases.append(
            f"Lead déjà transmis à M2 avant ce transfert : service {lead.get('service')}, ville {lead.get('ville')}."
        )
        if lead_a_verifier:
            phrases.append("Ces informations sont historiques : vérifier le service et la ville dans le dossier.")
    elif type_transfert in (plaintes.TYPE_PLAINTE, plaintes.TYPE_URGENCE):
        phrases.append("Aucun lead n'a été ouvert par ce message : la plainte prime, rien n'est transmis à M2.")
    elif lead_evalue:
        phrases.append("Aucun lead n'est ouvert pour cette conversation.")
    contacts = {
        "canal": "Contact : celui du correspondant, vérifié par le canal (porté à part).",
        "texte": "Contact : écrit par le client dans son message (porté à part).",
        "numéro transmis par l'hôte": "Contact : numéro transmis par l'hôte (porté à part).",
    }
    phrases.append(contacts.get(contact_source or "", "Contact : aucun connu."))
    phrases.append("Les messages du client se lisent avec `m1_lire_transfert`.")
    return " ".join(phrases)


# ---------------------------------------------------------------------------------------------------------------
# M1-E : informations manquantes et prochaine action, calculées par les règles de qualification
# ---------------------------------------------------------------------------------------------------------------


def informations_manquantes(
    diagnostic: Mapping[str, Any] | None, *, contact_present: bool
) -> dict[str, Any]:
    """Ce que le dossier n'établit pas encore, en CODES fermés.

    `diagnostic` : la lecture de `qualification.diagnostiquer` sur les messages couverts, ou `None` quand la zone
    desservie ou les services ne sont pas déclarés. Dans ce dernier cas, `service` et `ville` ne sont pas dits
    « manquants » (on ne le sait pas) mais `non_evalues` : aucun manque n'est supposé. Le contact, lui, est toujours
    observable : son absence est un vrai manque. Aucun texte du client n'entre ici.
    """
    champs: list[str] = []
    non_evalues: list[str] = []
    if diagnostic is None:
        non_evalues = ["service", "ville"]
        if not contact_present:
            champs.append("contact")
        statut = INFORMATIONS_PARTIELLES
        motif: str | None = MOTIF_DIAGNOSTIC_INDISPONIBLE
    else:
        manque = set(qualification.champs_manquants(diagnostic))
        champs = [champ for champ in CHAMPS_DU_DOSSIER if champ in manque]
        statut = INFORMATIONS_EVALUEES
        motif = None
    return {"statut": statut, "champs": champs, "non_evalues": non_evalues, "motif": motif}


def prochaine_action_recommandee(
    type_transfert: str, informations: Mapping[str, Any], *, retire: bool
) -> dict[str, Any]:
    """La suite recommandée à une PERSONNE, en choix fermé (`ACTIONS_RECOMMANDEES`), jamais un texte du client.

    Un champ non évalué commande `verifier_le_dossier` : le code ne comble pas un profil absent. Un client retiré
    (STOP) commande une décision humaine, jamais une relance. Une urgence passe avant une plainte.
    """
    champs = list(informations["champs"])
    if retire:
        code = ACTION_DECISION_APRES_RETRAIT
        detail = "le client s'est retiré des messages : une personne décide de la suite, rien ne lui est proposé"
    elif champs:
        code = ACTION_DEMANDER_INFORMATIONS
        detail = f"demander au client : {', '.join(champs)}"
    elif informations["non_evalues"]:
        code = ACTION_VERIFIER_LE_DOSSIER
        detail = (
            "vérifier le dossier avec l'équipe : "
            f"{', '.join(informations['non_evalues'])} n'ont pas pu être évalués avec les données disponibles"
        )
    elif type_transfert == plaintes.TYPE_URGENCE:
        code = ACTION_TRAITER_L_URGENCE
        detail = "l'urgence de sécurité est reconnue, une personne doit la prendre en charge maintenant"
    elif type_transfert == plaintes.TYPE_PLAINTE:
        code = ACTION_TRAITER_LA_PLAINTE
        detail = "la plainte est reconnue, une personne doit la lire et agir"
    else:
        code = ACTION_PRENDRE_EN_CHARGE
        detail = "une personne doit prendre en charge ce transfert"
    return {"code": code, "detail": detail, "champs": champs}


def _diagnostic_des_messages(
    messages: Sequence[Mapping[str, Any]], zone_desservie: Sequence[str] | None,
    services: Sequence[Any] | None, contact: Mapping[str, str] | None,
) -> dict[str, Any] | None:
    """La lecture de qualification des messages couverts, ou `None` si la zone ou les services manquent.

    Le contact vérifié par le canal est passé à la qualification : il est établi même quand le texte ne l'écrit pas.
    Une erreur de profil (zone ou services chargés mais invalides) est un `None`, comme une absence : le champ
    `informations_manquantes` le dit (`diagnostic_indisponible`), jamais une valeur par défaut.
    """
    if not zone_desservie or not services:
        return None
    contenu = "\n".join(str(m.get("contenu_filtre", "")) for m in messages)
    if not contenu.strip():
        return None
    try:
        return qualification.diagnostiquer(
            contenu, list(zone_desservie), services, dict(contact) if contact else None
        )
    except (ValueError, KeyError, TypeError):
        return None


def _valeur_du_lead(lead: Mapping[str, Any] | None, champ: str) -> str | None:
    """Un champ texte NON VIDE d'un lead déjà validé, ou `None`. Aucune conversion, aucune valeur de repli."""
    if not isinstance(lead, Mapping):
        return None
    valeur = lead.get(champ)
    return valeur if isinstance(valeur, str) and valeur.strip() else None


def _diagnostic_avec_le_lead(
    diagnostic: dict[str, Any] | None, lead: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """Complète le diagnostic des messages avec le `service` et la `ville` d'un lead DÉJÀ VALIDÉ.

    Le texte rassemblé d'une conversation peut encore évoquer les deux services que le client a départagés : le
    relire seul annoncerait un `service` manquant alors que le lead, lui, l'établit. Le lead est la lecture que M1 a
    acceptée (`qualification.qualifier`, contrat gelé) : ses deux champs sont réutilisés tels quels, jamais relus dans
    le texte ni devinés. Un lead absent ou incomplet ne remplace rien ; un profil indisponible garde son diagnostic
    partiel (`diagnostic_indisponible`), même si un lead existe : le contrat ne comble pas un profil absent.
    """
    if lead is None:
        return diagnostic
    service, ville = _valeur_du_lead(lead, "service"), _valeur_du_lead(lead, "ville")
    if diagnostic is None:
        return None
    resultat = dict(diagnostic)
    if service:
        resultat["service"] = service
    if ville:
        resultat["ville"] = ville
    return resultat


# ---------------------------------------------------------------------------------------------------------------
# Écrire : les lignes du registre
# ---------------------------------------------------------------------------------------------------------------


def identifiant_de_transfert(conversation_id: str, type_transfert: str, signal_id: str, rang: int) -> str:
    """Stable et sans renseignement personnel : `rang` (le nombre de transferts déjà ouverts pour cette conversation)
    distingue deux transferts du même type sur le même message, l'un après la clôture de l'autre."""
    materiau = "|".join(f"{len(x)}:{x}" for x in (conversation_id, type_transfert, signal_id, str(rang)))
    return f"tr-{hashlib.sha256(materiau.encode('utf-8')).hexdigest()[:20]}"


def rang_suivant(lignes: Iterable[Mapping[str, Any]], conversation_id: str) -> int:
    return sum(
        1 for ligne in lignes
        if ligne.get("type_entree") == TYPE_ENTREE and ligne.get("evenement") == EVT_OUVERT
        and ligne.get("conversation_id") == conversation_id
    )


def messages_de(lignes: Iterable[Mapping[str, Any]], conversation_id: str) -> list[Mapping[str, Any]]:
    """Les lignes `signal` d'une conversation, dans l'ordre d'arrivée."""
    return [
        ligne for ligne in lignes
        if ligne.get("type_entree") == "signal" and ligne.get("conversation_id") == conversation_id
    ]


def _est_un_signal_de(ligne: Mapping[str, Any], identifiants: set[str]) -> bool:
    return ligne.get("type_entree") == "signal" and ligne.get("signal_id") in identifiants


def preparer_ouverture(
    lignes: Sequence[Mapping[str, Any]],
    *,
    type_transfert: str,
    categories: Sequence[str],
    termes: Mapping[str, Sequence[str]],
    declenche_par: str,
    canal: str,
    source: str | None,
    conversation_id: str,
    message_courant: Mapping[str, Any] | None,
    contact: Mapping[str, str] | None,
    contact_source: str | None,
    destinataire: str | None,
    verdict_destinataire: Mapping[str, str] | None,
    fenetre_minutes: int | None = None,
    resume_agent: Any = None,
    resume_fourni: bool = False,
    zone_desservie: Sequence[str] | None = None,
    services: Sequence[Any] | None = None,
    retire: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """La ligne d'ouverture d'un transfert, ou le verdict qui le refuse : `(ligne, None)` ou `(None, verdict)`.

    `lignes` : le registre AVANT ce message. `message_courant` : le message qui déclenche le transfert (`signal_id`,
    `horodatage`, `contenu_filtre`, pas encore au registre) ; absent quand l'agent ouvre le transfert, le dernier
    message de la conversation est alors le déclencheur (et la ligne est datée de son heure de réception : jamais une
    horloge).
    `fenetre_minutes` : la fenêtre de conversation du profil, ou `None`. Avec elle, le transfert couvre les messages de
    la conversation OUVERTE (`conversation.lire`, au plus `MESSAGES_MAX`) et dit si elle avait déjà son lead ; sans
    elle, chaque message est qualifié seul : le transfert ne couvre que le message déclencheur et ne dit rien d'un
    lead.
    `resume_fourni` : l'agent a fourni un résumé (`resume_agent`), qui est alors CONTRÔLÉ, jamais composé à sa place ;
    absent, le code le compose.

    Refus : type inconnu ; conversation sans aucun message (rien à transférer) ; résumé fourni vide, trop long, avec
    une donnée de contact ou qui viole le garde-fou.
    """
    if type_transfert not in TYPES:
        return None, _verdict("REJ-ENUM-INVALIDE", f"type de transfert {type_transfert!r} : attendu {', '.join(TYPES)}")
    exclus = signaux_exclus(lignes)
    tous = messages_de(lignes, conversation_id)
    if message_courant is not None:
        declencheur: Mapping[str, Any] = message_courant
        a_lire = [ligne for ligne in lignes if not _est_un_signal_de(ligne, exclus)]
    elif tous:
        declencheur = tous[-1]  # le dernier message du client, même s'il est déjà couvert par un autre transfert
        a_lire = [ligne for ligne in lignes if not _est_un_signal_de(ligne, exclus | {declencheur["signal_id"]})]
    else:
        return None, _verdict(
            "REJ-TRANSFERT-CONVERSATION-INCONNUE",
            "aucun message de ce correspondant au registre : rien à transférer (recopie le canal et l'expéditeur "
            "tels que la plateforme les donne)",
        )
    lead = None
    signaux_du_lead: set[str] = set()
    couverts = [declencheur]
    if fenetre_minutes is not None:
        ouverte = conversation.lire(a_lire, conversation_id, declencheur["horodatage"], fenetre_minutes)
        couverts = [*ouverte.messages[-(MESSAGES_MAX - 1):], declencheur]
        lead = None if ouverte.lead is None else ouverte.lead["lead"]
        if ouverte.lead is not None:
            signaux = ouverte.lead.get("signaux_rassembles")
            if isinstance(signaux, list) and all(isinstance(signal, str) for signal in signaux):
                signaux_du_lead = set(signaux)
    horodatages = [m["horodatage"] for m in couverts]
    diagnostic = _diagnostic_des_messages(couverts, zone_desservie, services, contact)
    # Le lead ne tranche que les messages qui ont servi à le qualifier. Le diagnostic assemblé ne sait pas
    # arbitrer sûrement deux villes ou une correction ultérieure : après un nouveau signal, il reste non évalué.
    if signaux_du_lead and all(message.get("signal_id") in signaux_du_lead for message in couverts):
        service, ville = _valeur_du_lead(lead, "service"), _valeur_du_lead(lead, "ville")
        if diagnostic is not None and (
            (service and taxonomie.valider_service(service, services)[1] is not None)
            or (ville and not any(ville.casefold() == v.casefold() for v in zone_desservie or ()))
        ):
            diagnostic = None
        else:
            diagnostic = _diagnostic_avec_le_lead(diagnostic, lead)
    elif lead is not None:
        diagnostic = None
    informations = informations_manquantes(diagnostic, contact_present=contact is not None)
    action = prochaine_action_recommandee(type_transfert, informations, retire=retire)
    if lead is not None and diagnostic is None:
        action["detail"] += ". Le lead est historique : vérifier son service et sa ville."
    faits = composer_faits(
        type_transfert=type_transfert, categories=categories, termes=termes, canal=source or canal,
        horodatages=horodatages, lead=lead, lead_evalue=fenetre_minutes is not None, contact_source=contact_source,
        declenche_par=declenche_par, lead_a_verifier=lead is not None and diagnostic is None,
    )
    resume, origine, sain = faits, ORIGINE_CODE, True
    if resume_fourni:
        resume, sain, refus = controler_resume(resume_agent)
        if refus is not None:
            return None, refus
        origine = ORIGINE_AGENT
    ligne: dict[str, Any] = {
        "type_entree": TYPE_ENTREE,
        "evenement": EVT_OUVERT,
        "transfert_id": identifiant_de_transfert(
            conversation_id, type_transfert, declencheur["signal_id"], rang_suivant(lignes, conversation_id)),
        "type_transfert": type_transfert,
        "niveau": niveau_attente(type_transfert, categories),
        "categories": list(categories),
        "termes": {c: list(t) for c, t in termes.items()},
        "declenche_par": declenche_par,
        "canal": canal,
        "conversation_id": conversation_id,
        "signal_id": declencheur["signal_id"],
        "signaux": [m["signal_id"] for m in couverts],
        "horodatage": declencheur["horodatage"],
        "resume": resume,
        "resume_origine": origine,
        "faits": faits,
        "informations_manquantes": informations,
        "prochaine_action": action,
        "destinataire": destinataire,
        "verdict_destinataire": None if verdict_destinataire is None else dict(verdict_destinataire),
        "contact": None if contact is None else dict(contact),
        "lead_id": None if lead is None else lead.get("lead_id"),
    }
    if source is not None:
        ligne["source"] = source
    if origine == ORIGINE_AGENT:
        ligne["resume_provenance_saine"] = sain
    return ligne, None


def verifier_cloture(motif: Any, horodatage: Any) -> dict[str, str] | None:
    """`None` si la clôture est recevable, sinon le verdict du premier défaut : le motif dit pourquoi (de `MOTIF_MIN` à
    `MOTIF_MAX` caractères) et l'heure est un ISO-8601 avec fuseau."""
    if not isinstance(motif, str) or not MOTIF_MIN <= len(motif.strip()) <= MOTIF_MAX:
        return _verdict(
            "REJ-HUMAIN-MOTIF-INVALIDE",
            f"le motif est obligatoire : {MOTIF_MIN} à {MOTIF_MAX} caractères, dit ce qui a été fait",
        )
    try:
        controle_horodatage.valider_horodatage(horodatage)
    except ValueError:
        return _verdict("REJ-HUMAIN-HORODATAGE-INVALIDE", "horodatage ISO 8601 avec fuseau requis")
    return None


def charge_evenement_ouverture(ligne: Mapping[str, Any], type_evenement: str) -> dict[str, Any]:
    """La charge MINIMALE d'un transfert ouvert pour le bus (M1-E) : identifiants, type, catégories et niveau.

    Jamais le contact, le résumé, un terme du vocabulaire ni le texte du client. `conversation_id` est déjà un
    pseudonyme (empreinte du correspondant) ; `lead_id` est absent quand aucune affaire n'existe. L'identifiant est
    déterministe : un rejeu du même transfert est un no-op du bus.
    """
    prefixe = "m1-transfert-ouvert" if type_evenement == TYPE_EVENEMENT_TRANSFERT else "m1-plainte-ouverte"
    return {
        "evenement_id": f"{prefixe}-{ligne['transfert_id']}",
        "transfert_id": ligne["transfert_id"],
        "conversation_id": ligne["conversation_id"],
        "lead_id": ligne.get("lead_id"),
        "type_transfert": ligne["type_transfert"],
        "categories": list(ligne.get("categories", ())),
        "niveau": ligne["niveau"],
        "canal": ligne["canal"],
        "declenche_par": ligne["declenche_par"],
        "horodatage": ligne["horodatage"],
    }


def ligne_de_cloture(
    etat: EtatTransfert, *, par: str, role: str, voie: str, motif: str, horodatage: str
) -> dict[str, Any]:
    """La ligne qui clôt un transfert : une PERSONNE (identifiée, avec son rôle et la voie par laquelle elle agit) et
    son motif. Elle ne modifie aucune ligne : le registre reste append-only."""
    ouverture = etat.ouverture
    return {
        "type_entree": TYPE_ENTREE,
        "evenement": EVT_CLOS,
        "transfert_id": etat.identifiant,
        "type_transfert": ouverture["type_transfert"],
        "conversation_id": ouverture["conversation_id"],
        "canal": ouverture["canal"],
        "horodatage": horodatage,
        "clos_par": par,
        "role": role,
        "voie": voie,
        "motif": motif.strip(),
    }


# ---------------------------------------------------------------------------------------------------------------
# Lire : la file « À voir » et la vue d'une personne
# ---------------------------------------------------------------------------------------------------------------


def attente(etat: EtatTransfert) -> dict[str, Any]:
    """L'attente du propriétaire pour un transfert ouvert (forme `approbations.CHAMPS_ATTENTE`) : un résumé d'une ligne,
    SANS donnée personnelle (ni contact ni texte du client : ce sont des résumés, `ROLES.md`), le niveau qui règle
    l'ordre de la file, l'heure de réception du message déclencheur, et le geste."""
    ouverture = etat.ouverture
    type_transfert = ouverture["type_transfert"]
    nombre = len(ouverture["signaux"]) + len(etat.suivis)
    morceaux = [libelle(type_transfert)]
    if ouverture["categories"]:
        morceaux.append(f"({_categories_lisibles(ouverture['categories'])})")
    canal = ouverture.get("source") or ouverture["canal"]
    depuis = f", dont {len(etat.suivis)} depuis l'ouverture" if etat.suivis else ""
    morceaux.append(f"par {canal}, {nombre} message{'s' if nombre > 1 else ''}{depuis}")
    destinataire = ouverture["destinataire"] or "destinataire à configurer"
    return {
        "type": _TYPE_D_ATTENTE.get(type_transfert, TYPE_D_ATTENTE_GENERAL),
        "id": etat.identifiant,
        "resume": f"{' '.join(morceaux)} ; pour : {destinataire}.",
        "niveau": ouverture["niveau"],
        "depuis": ouverture["horodatage"],
        "action_proposee": ACTION_PROPOSEE,
    }


def _extrait(ligne: Mapping[str, Any]) -> dict[str, str]:
    texte = ligne["contenu_filtre"]
    if len(texte) > EXTRAIT_MAX:
        texte = texte[: EXTRAIT_MAX - 1].rstrip() + "…"
    return {"signal_id": ligne["signal_id"], "recu_le": ligne["horodatage"], "texte": texte}


def _extraits(lignes_par_id: Mapping[str, Mapping[str, Any]], identifiants: Sequence[str]) -> dict[str, Any]:
    presents = [lignes_par_id[i] for i in identifiants if i in lignes_par_id]
    gardes = presents[-MESSAGES_AFFICHES_MAX:]
    return {"messages": [_extrait(m) for m in gardes], "omis": len(presents) - len(gardes)}


def vue(etat: EtatTransfert, lignes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Ce qu'une personne lit d'un transfert : le résumé, le destinataire (ou pourquoi il manque), le contact, les
    messages couverts et ceux qui sont arrivés depuis (les plus récents, bornés), et la clôture s'il y en a une.
    Lecture seule."""
    ouverture = etat.ouverture
    par_id = {m["signal_id"]: m for m in lignes if m.get("type_entree") == "signal"}
    couverts = _extraits(par_id, ouverture["signaux"])
    suivants = _extraits(par_id, [s["signal_id"] for s in etat.suivis])
    verdict = ouverture["verdict_destinataire"]
    if verdict is not None:
        # Projection utilisateur bornée ; le diagnostic complet reste dans le maillon original.
        verdict = {
            "code": verdict["code"],
            "detail": {
                taxonomie.VERDICT_DESTINATAIRE_NON_CONFIGURE: "Destinataire à configurer pour ce type de transfert.",
                taxonomie.VERDICT_PROFIL_INVALIDE:
                    "Profil d'entreprise invalide : corriger la configuration des destinataires de transfert.",
            }.get(verdict["code"], "Vérifier la configuration du destinataire du transfert."),
        }
    resultat: dict[str, Any] = {
        "transfert_id": etat.identifiant,
        "statut": "ouvert" if etat.ouvert else "clos",
        "type_transfert": ouverture["type_transfert"],
        "niveau": ouverture["niveau"],
        "categories": list(ouverture["categories"]),
        "termes": dict(ouverture["termes"]),
        "declenche_par": ouverture["declenche_par"],
        "canal": ouverture["canal"],
        "conversation_id": ouverture["conversation_id"],
        "ouvert_le": ouverture["horodatage"],
        "destinataire": ouverture["destinataire"],
        "verdict_destinataire": verdict,
        "contact": ouverture["contact"],
        "lead_id": ouverture["lead_id"],
        "resume": ouverture["resume"],
        "resume_origine": ouverture["resume_origine"],
        "informations_manquantes": ouverture["informations_manquantes"],
        "prochaine_action": ouverture["prochaine_action"],
        "messages_couverts": couverts["messages"],
        "messages_couverts_omis": couverts["omis"],
        "messages_suivants": suivants["messages"],
        "messages_suivants_omis": suivants["omis"],
    }
    if etat.cloture is not None:
        cloture = etat.cloture
        resultat["cloture"] = {
            "par": cloture["clos_par"], "role": cloture["role"], "voie": cloture["voie"], "motif": cloture["motif"],
            "clos_le": cloture["horodatage"],
        }
    return resultat


def source_appel_revendiquee(lignes: Iterable[Mapping[str, Any]], transfert_id: str) -> bool:
    """Vrai si une ligne d'appel revendique le lien, même si son contenu doit ensuite échouer à la validation."""
    for ligne in lignes:
        reponse = ligne.get("reponse")
        tache = reponse.get("tache_rappel") if isinstance(reponse, Mapping) else None
        if (
            ligne.get("type_entree") == "appel_importe"
            and isinstance(tache, Mapping)
            and tache.get("transfert_id") == transfert_id
        ):
            return True
    return False


def sources_appel_rappel(lignes: Iterable[Mapping[str, Any]], transfert_id: str) -> tuple[Mapping[str, Any], ...]:
    """Sources canoniques d'appel dont la réponse M1 rattache une tâche de rappel à ce transfert."""
    sources = []
    for ligne in lignes:
        if ligne.get("type_entree") != "appel_importe":
            continue
        reponse = ligne.get("reponse")
        if not isinstance(reponse, Mapping) or reponse.get("accepte") is not True:
            continue
        tache = reponse.get("tache_rappel")
        if not isinstance(tache, Mapping) or tache.get("transfert_id") != transfert_id:
            continue
        if (
            ligne.get("appel_id") != reponse.get("appel_id")
            or ligne.get("source") != reponse.get("source")
            or ligne.get("statut") != reponse.get("statut")
            or ligne.get("statut") not in {"manque", "voicemail"}
        ):
            continue
        sources.append(ligne)
    return tuple(sources)


def projection_suivi_rappel(
    lignes: Iterable[Mapping[str, Any]], transfert_id: str
) -> dict[str, Any] | None:
    """Projection privée et révision CAS du rappel lié à une vraie source d'appel M1."""
    lignes = tuple(lignes)
    etat = next((element for element in lire(lignes) if element.identifiant == transfert_id), None)
    sources = sources_appel_rappel(lignes, transfert_id)
    if etat is None or not sources:
        return None

    lignes_transfert = tuple(
        ligne for ligne in lignes
        if ligne.get("type_entree") == TYPE_ENTREE and ligne.get("transfert_id") == transfert_id
    )
    pertinentes = tuple(
        ligne for ligne in lignes
        if (
            ligne.get("type_entree") == TYPE_ENTREE and ligne.get("transfert_id") == transfert_id
        ) or (
            ligne.get("type_entree") == "signal" and ligne.get(MARQUE) == transfert_id
        ) or (
            ligne.get("type_entree") == "appel_importe"
            and sources_appel_rappel((ligne,), transfert_id)
        )
    )
    identifiants = [ligne.get("ligne_id") for ligne in pertinentes]
    if any(not isinstance(identifiant, str) or re.fullmatch(r"[0-9a-f]{64}", identifiant) is None
           for identifiant in identifiants):
        raise ValueError("REJ-SUIVI-RAPPEL-HISTORIQUE-INCOHERENT")
    snapshot = hashlib.sha256(json.dumps(identifiants, separators=(",", ":")).encode("ascii")).hexdigest()

    suivi = [
        (index, ligne) for index, ligne in enumerate(lignes_transfert)
        if ligne.get("evenement") in {EVT_PRISE_EN_CHARGE, EVT_TENTATIVE_SANS_CONTACT}
    ]
    prise = None
    tentatives = []
    cloture_index = next(
        (index for index, ligne in enumerate(lignes_transfert) if ligne.get("evenement") == EVT_CLOS), None,
    )
    for index, ligne in suivi:
        if cloture_index is not None and index > cloture_index:
            raise ValueError("REJ-SUIVI-RAPPEL-HISTORIQUE-INCOHERENT")
        if ligne.get("evenement") == EVT_PRISE_EN_CHARGE:
            if prise is not None or tentatives:
                raise ValueError("REJ-SUIVI-RAPPEL-HISTORIQUE-INCOHERENT")
            prise = ligne
        else:
            if prise is None or ligne.get("par") != prise.get("par"):
                raise ValueError("REJ-SUIVI-RAPPEL-HISTORIQUE-INCOHERENT")
            tentatives.append(ligne)

    derniere = tentatives[-1] if tentatives else None
    return {
        "snapshot_suivi": snapshot,
        "responsable": prise.get("par") if prise is not None else None,
        "role": prise.get("role") if prise is not None else None,
        "pris_en_charge_le": prise.get("horodatage") if prise is not None else None,
        "tentatives_sans_contact": len(tentatives),
        "derniere_tentative_le": derniere.get("horodatage") if derniere is not None else None,
        "prochaine_tentative_le": derniere.get("prochaine_tentative_le") if derniere is not None else None,
    }


def normaliser_echeance_rappel(echeance: str, maintenant: str) -> str:
    """Valide une échéance ASCII explicitement zonée et strictement future; rend l'instant en UTC."""
    if not isinstance(echeance, str) or len(echeance) > 40 or _ECHEANCE_RAPPEL.fullmatch(echeance) is None:
        raise ValueError("REJ-SUIVI-RAPPEL-ECHEANCE-INVALIDE")
    try:
        date_echeance = datetime.fromisoformat(echeance.replace("Z", "+00:00"))
        date_serveur = datetime.fromisoformat(maintenant.replace("Z", "+00:00"))
        date_echeance_utc = date_echeance.astimezone(UTC)
        date_serveur_utc = date_serveur.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("REJ-SUIVI-RAPPEL-ECHEANCE-INVALIDE") from None
    if date_echeance.tzinfo is None or date_serveur.tzinfo is None:
        raise ValueError("REJ-SUIVI-RAPPEL-ECHEANCE-INVALIDE")
    if date_echeance_utc <= date_serveur_utc:
        raise ValueError("REJ-SUIVI-RAPPEL-ECHEANCE-PAS-FUTURE")
    return date_echeance_utc.isoformat(timespec="microseconds")
