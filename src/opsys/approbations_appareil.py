"""Le propriétaire liste et décide, depuis son téléphone, les demandes d'approbation du socle
(PLAN T1.4-f, étape 6 ; DEFINITION-PRODUIT §9.2 et §9.5 : « le propriétaire approuve tout depuis le
téléphone »).

Ce module est la LOGIQUE, en fonctions pures de `(cnx, départements, identité)`. Les deux outils MCP qui
l'exposent à `/tools/invoke` sont déclarés par M9 (`m9_lister_demandes_approbation`,
`m9_decider_demande_approbation`) : c'est le seul département qui lit déjà la file du propriétaire
(`m9_produire_briefing_matin`) et dont le mobile est réservé à l'admin (§7 M9). `openclaw.roles_outils` et
`opsys verifier` ne voient que des outils de département : les déclarer ailleurs les laisserait hors de
`roles.json`, donc injoignables (et présents sur les dix serveurs à la fois).

Ce n'est pas un second chemin de décision. La décision passe par `tableau_de_bord.decider_approbation`,
donc par `approbations.decider` : mêmes vérifications (personne active, rôle autorisé pour le niveau dans
le département de la demande), même réservation atomique, même exécution avec les arguments exacts
enregistrés, même journal d'audit. Ce module ajoute des GARDES en amont, jamais un contournement :

1. **Identité.** La personne vient de `contexte.identite_appelante()` (le `_meta` que OPSYS-CORE n'émet
   que pour un jeton d'appareil vérifié), relue en base : personne active portant encore le rôle du
   jeton (`approbations.signataire_valide`). Jamais un argument d'outil : les paramètres des outils M9 ne
   contiennent ni personne ni rôle, et un paramètre inconnu est refusé. Sans identité, refus.
2. **Rôle d'appareil `admin`** (`ROLE_APPAREIL`), en défense en profondeur : le core refuse déjà l'outil hors
   de la portée du rôle, mais le socle ne s'y fie pas seul.
3. **Plafond : le propriétaire.** Un appareil ne décide N3 et N4 que si la PERSONNE authentifiée porte
   `nathan_owner` (`identite.Role`), jamais sur la foi du seul rôle `admin` du jeton (un gestionnaire peut
   porter `admin`). La décision est signée sous `nathan_owner`. Un `admin` qui n'est pas le propriétaire
   voit la file sans les arguments, en lecture seule. La politique du département de la demande
   s'applique en plus, inchangée (`Departement.roles_autorises`).
4. **N5 jamais.** Une demande N5 (ou sans niveau, ancienne, lue comme N5 : fail-closed) et tout outil T3
   (`Outil.frontiere_humaine`) sont montrés en lecture seule, « à décider à la console » : l'attestation
   du professionnel (ADR-0009 §5) n'a pas d'écran dans l'app.
5. **Ce qu'on décide, on l'a vu.** Les arguments sont affichés en entier (`fix_gps` masqué comme dans la
   trace) ou la demande est en lecture seule : on n'approuve pas depuis un téléphone ce qu'il ne peut pas
   afficher.
6. **Un appareil identifié.** La décision exige le contexte d'un appel d'appareil idempotent (l'appareil
   et sa clé, `contexte.horodatage_reception`) : sans lui, refus. L'appareil entre au journal d'audit.
7. **Contexte d'exécution.** L'outil approuvé s'exécute SANS l'identité ni les horloges de l'appareil du
   propriétaire, comme depuis la console : sinon `m4_pointer`, qui lit l'heure de réception de l'appareil
   courant, daterait le pointage d'un tiers à l'heure de l'approbation.

Idempotence : elle est celle du transport (`Capacites._appeler_idempotent`). Rejouer la même clé rend la
réponse enregistrée sans rien ré-exécuter ; une AUTRE clé pour une demande déjà décidée reçoit le verdict
`deja_decidee`.

Réponses : le patron `(résultat, verdict)` de `opsys.outils.depuis_couple`. Un refus est un verdict
`{code, detail}` que l'app montre tel quel, pas une erreur technique. Les refus d'une personne
authentifiée (hors demande inconnue ou déjà décidée) laissent une entrée d'audit
`approbation.refus_appareil` : une tentative de décider hors de ses droits se voit.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection

from . import approbations, contexte, identite, tableau_de_bord
from .capacites import outils_executables
from .contexte import IdentiteAppelante
from .departements import DEFAUT_ROLES_NIVEAU, Departement
from .etat import journaliser
from .outils import Niveau, Outil

ROLE_APPAREIL = "admin"
ROLE_SIGNATAIRE = identite.Role.NATHAN_OWNER.value
NIVEAUX_DECIDABLES = frozenset({Niveau.N3, Niveau.N4})
DECISIONS = tableau_de_bord.DECISIONS  # ("approuver", "refuser") : celles de la console
ACTION_REFUS_APPAREIL = "approbation.refus_appareil"

LIMITE_LISTE_DEFAUT = 20
LIMITE_LISTE_MAX = 50
LIMITE_MOTIF = 500
LIMITE_IDENTIFIANT = 32  # `approbations.id` est un String(32)
# Un outil de département voit sa sortie tronquée au-delà de `jetons.LIMITE_SORTIE_DEFAUT` (6000
# caractères) : le téléphone ne saurait pas lire la suite. La liste s'arrête donc avant, et dit combien
# de demandes elle n'a pas montrées.
BUDGET_LISTE = 4600
LIMITE_ARGUMENTS = 1500
LIMITE_DESCRIPTION = 200
LIMITE_MOTIF_DEMANDE = 300
LIMITE_DETAIL_ISSUE = 300

# Codes de verdict (l'app les affiche tels quels, avec leur détail).
IDENTITE_ABSENTE = "identite_absente"
IDENTITE_INVALIDE = "identite_invalide"
ROLE_APPAREIL_INSUFFISANT = "role_appareil_insuffisant"
APPAREIL_INCONNU = "appareil_inconnu"
RESERVE_AU_PROPRIETAIRE = "reserve_au_proprietaire"
DEMANDE_INCONNUE = "demande_inconnue"
DEJA_DECIDEE = "deja_decidee"
N5_A_LA_CONSOLE = "n5_a_la_console"
NIVEAU_NON_DECIDABLE = "niveau_non_decidable"
OUTIL_FRONTIERE_HUMAINE = "outil_frontiere_humaine"
OUTIL_INCONNU = "outil_inconnu"
POLITIQUE_DU_DEPARTEMENT = "politique_du_departement"
ARGUMENTS_TROP_VOLUMINEUX = "arguments_trop_volumineux"
DECISION_INVALIDE = "decision_invalide"
MOTIF_INVALIDE = "motif_invalide"
LIMITE_INVALIDE = "limite_invalide"
DECISION_REFUSEE = "decision_refusee"

# Refus qui ne disent rien de plus qu'une erreur de saisie ou d'état : pas d'entrée d'audit.
_SANS_AUDIT = frozenset({DEMANDE_INCONNUE, DEJA_DECIDEE, DECISION_INVALIDE, MOTIF_INVALIDE})

Reponse = tuple[dict[str, Any] | None, dict[str, Any] | None]


def _verdict(code: str, detail: str, **plus: Any) -> dict[str, Any]:
    return {"code": code, "detail": detail, **plus}


def _court(texte: Any, limite: int) -> str | None:
    """Texte réduit à `limite` caractères (`…` s'il a été coupé) ; None s'il est vide ou n'est pas un texte."""
    if not isinstance(texte, str) or not texte.strip():
        return None
    texte = texte.strip()
    return texte if len(texte) <= limite else texte[: limite - 1].rstrip() + "…"


@dataclasses.dataclass(frozen=True)
class Signataire:
    """La personne authentifiée qui parle, relue en base, et ce qu'elle peut faire ici."""

    personne: identite.Personne
    role_appareil: str
    proprietaire: bool


def _signataire(
    cnx: Connection, appelante: IdentiteAppelante | None
) -> tuple[Signataire | None, dict[str, Any] | None]:
    if appelante is None:
        return None, _verdict(
            IDENTITE_ABSENTE,
            "Aucune identité d'appareil authentifiée : cette action ne se fait que depuis l'app appairée "
            "du propriétaire. Rien n'a été décidé.",
        )
    valide = approbations.signataire_valide(cnx, appelante)
    if valide is None:
        return None, _verdict(
            IDENTITE_INVALIDE,
            "La personne de cet appareil est inconnue, inactive, ou ne porte plus le rôle de son appairage. "
            "Rien n'a été décidé.",
        )
    if valide.role != ROLE_APPAREIL:
        return None, _verdict(
            ROLE_APPAREIL_INSUFFISANT,
            f"Le rôle {valide.role!r} de cet appareil ne couvre pas les approbations ; il faut {ROLE_APPAREIL!r}.",
        )
    personne = identite.personne_active(cnx, valide.personne)
    if personne is None:
        return None, _verdict(IDENTITE_INVALIDE, "La personne de cet appareil est inconnue ou inactive.")
    return Signataire(personne, valide.role, ROLE_SIGNATAIRE in personne.roles), None


def _niveau_de(demande: Mapping[str, Any]) -> Niveau:
    """Niveau figé de la demande ; une demande sans niveau (héritée d'avant ADR-0009) ou au niveau
    illisible est lue N5, comme le fait `approbations.decider` (fail-closed)."""
    brut = demande.get("niveau")
    try:
        return Niveau(brut) if brut else Niveau.N5
    except ValueError:
        return Niveau.N5


def _outils_par_nom(departements: Mapping[str, Departement], cnx: Connection) -> dict[str, Outil]:
    """Les outils qu'une approbation peut exécuter (départements et outils communs), comme la console.

    Un département dont le code ne charge pas donne un index vide : chaque demande devient alors
    `outil_inconnu`, donc en lecture seule (la console garde ce cas pour elle)."""
    try:
        return outils_executables(departements, lambda: contextlib.nullcontext(cnx))
    except (ImportError, ValueError, TypeError):
        return {}


def _arguments_affichables(demande: Mapping[str, Any], signataire: Signataire) -> dict[str, Any] | None:
    """Les arguments à montrer (donnée personnelle masquée), ou None : pas le propriétaire, ou trop gros
    pour être relus en entier sur un téléphone."""
    if not signataire.proprietaire:
        return None
    arguments = approbations.arguments_masques(demande["arguments"])
    if len(json.dumps(arguments, ensure_ascii=False)) > LIMITE_ARGUMENTS:
        return None
    return arguments


def _lecture_seule(
    demande: Mapping[str, Any], signataire: Signataire, departements: Mapping[str, Departement],
    outils: Mapping[str, Outil],
) -> dict[str, Any] | None:
    """Verdict qui dit pourquoi une demande EN ATTENTE ne peut pas être décidée depuis l'app, ou None si
    elle le peut. Liste et décision passent toutes deux ici : ce que l'écran offre, le serveur le permet, et
    rien d'autre."""
    niveau = _niveau_de(demande)
    if niveau is Niveau.N5:
        return _verdict(
            N5_A_LA_CONSOLE,
            "Niveau N5 (argent réel, fiscal, légal, paie ou RH) : à décider à la console, avec l'attestation "
            "du professionnel. Jamais depuis l'app.",
        )
    if niveau not in NIVEAUX_DECIDABLES:
        return _verdict(NIVEAU_NON_DECIDABLE, f"Niveau {niveau.value} : seuls N3 et N4 se décident depuis l'app.")
    outil = outils.get(demande["outil"])
    if outil is None:
        return _verdict(OUTIL_INCONNU, f"L'outil {demande['outil']} n'est pas connu du serveur : à voir à la console.")
    if outil.frontiere_humaine:
        return _verdict(
            OUTIL_FRONTIERE_HUMAINE,
            f"{outil.nom} est une frontière humaine (T3/N5) : à décider à la console.",
        )
    if not signataire.proprietaire:
        return _verdict(
            RESERVE_AU_PROPRIETAIRE,
            "Décider une demande depuis l'app est réservé au propriétaire ; cette personne n'a pas ce rôle.",
        )
    departement = departements.get(demande["departement"])
    roles_autorises = departement.roles_autorises(niveau) if departement is not None else DEFAUT_ROLES_NIVEAU
    if ROLE_SIGNATAIRE not in roles_autorises:
        return _verdict(
            POLITIQUE_DU_DEPARTEMENT,
            f"La politique du département {demande['departement']} n'autorise pas le propriétaire à décider "
            f"une demande {niveau.value} ; à voir à la console.",
        )
    if _arguments_affichables(demande, signataire) is None:
        return _verdict(
            ARGUMENTS_TROP_VOLUMINEUX,
            "Les arguments de cette demande sont trop volumineux pour être relus en entier sur le téléphone : "
            "à décider à la console.",
        )
    return None


def _item(
    demande: Mapping[str, Any], signataire: Signataire, departements: Mapping[str, Departement],
    outils: Mapping[str, Outil],
) -> dict[str, Any]:
    departement = departements.get(demande["departement"])
    outil = outils.get(demande["outil"])
    verdict = _lecture_seule(demande, signataire, departements, outils)
    return {
        "id": demande["id"],
        "departement": demande["departement"],
        "departement_nom": departement.nom if departement is not None else None,
        "outil": demande["outil"],
        "description_outil": _court(outil.description, LIMITE_DESCRIPTION) if outil is not None else None,
        "niveau": demande["niveau"],  # None pour une ancienne demande : jamais deviné
        "depuis": demande["cree_le"],
        "motif_demande": _court(demande["motif_demande"], LIMITE_MOTIF_DEMANDE),
        "arguments": _arguments_affichables(demande, signataire),
        "decidable": verdict is None,
        "lecture_seule": verdict,
    }


def lister_demandes(
    cnx: Connection, departements: Mapping[str, Departement], appelante: IdentiteAppelante | None,
    *, limite: Any = LIMITE_LISTE_DEFAUT,
) -> Reponse:
    """Les demandes EN ATTENTE, la plus ancienne d'abord (comme la file du propriétaire), chacune avec ce
    que l'app doit afficher et si elle peut la décider. Lecture seule.

    Rend `(résultat, None)` ou `(None, verdict)`. Le résultat dit combien de demandes existent
    (`total_en_attente`), combien sont montrées (`affichees`) et combien restent (`reste`) : la liste
    est bornée par `limite` et par `BUDGET_LISTE`, et une demande non montrée est comptée, jamais omise
    en silence. `proprietaire` dit si la personne peut décider quoi que ce soit ici.
    """
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= LIMITE_LISTE_MAX:
        return None, _verdict(LIMITE_INVALIDE, f"limite : un entier de 1 à {LIMITE_LISTE_MAX} est attendu.")
    signataire, verdict = _signataire(cnx, appelante)
    if signataire is None:
        return None, verdict
    outils = _outils_par_nom(departements, cnx)
    total = approbations.compter(cnx, "en_attente")
    items: list[dict[str, Any]] = []
    taille = 0
    for demande in approbations.lister(cnx, "en_attente", limite, plus_anciennes_d_abord=True):
        item = _item(demande, signataire, departements, outils)
        poids = len(json.dumps(item, ensure_ascii=False))
        if items and taille + poids > BUDGET_LISTE:
            break
        items.append(item)
        taille += poids
    return {
        "demandes": items,
        "total_en_attente": total,
        "affichees": len(items),
        "reste": total - len(items),
        "proprietaire": signataire.proprietaire,
    }, None


def _refuser(
    cnx: Connection, signataire: Signataire, demande_id: str, verdict: dict[str, Any], *, decision: str,
    appareil: str | None,
) -> Reponse:
    """Refus d'une décision : le verdict, plus l'entrée d'audit d'une personne authentifiée qui a tenté
    quelque chose qu'elle ne pouvait pas (sauf erreur de saisie ou d'état, `_SANS_AUDIT`)."""
    if verdict["code"] not in _SANS_AUDIT:
        journaliser(cnx, signataire.personne.identifiant, ACTION_REFUS_APPAREIL, demande_id, {
            "code": verdict["code"], "decision": decision, "appareil": appareil,
            "role_appareil": signataire.role_appareil,
        })
    return None, verdict


def _issue(reponse: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que l'outil approuvé a rendu, en petit : l'app dit si l'exécution a réussi et, quand l'outil
    rend un verdict métier (`opsys.outils.depuis_couple`), ce verdict. Les données produites vivent dans
    les registres du département."""
    issue: dict[str, Any] = {"ok": bool(reponse.get("ok"))}
    metier = reponse.get("resultat")
    if isinstance(metier, Mapping) and "accepte" in metier:
        issue["accepte"] = bool(metier["accepte"])
        verdict = metier.get("verdict")
        if isinstance(verdict, Mapping):
            issue["verdict"] = {
                "code": _court(verdict.get("code"), 80) or "inconnu",
                "detail": _court(verdict.get("detail"), LIMITE_DETAIL_ISSUE) or "",
            }
    if not reponse.get("ok"):
        issue["erreur"] = _court(reponse.get("erreur"), 80) or "inconnue"
        details = reponse.get("details")
        if details is not None:
            issue["details"] = _court(
                details if isinstance(details, str) else json.dumps(details, ensure_ascii=False, default=str),
                LIMITE_DETAIL_ISSUE,
            )
    return issue


def decider_demande(
    cnx: Connection, departements: Mapping[str, Departement], appelante: IdentiteAppelante | None,
    demande_id: Any, decision: Any, motif: Any = "", *, appareil: str | None,
) -> Reponse:
    """Approuve ou refuse la demande `demande_id`, au nom de la personne authentifiée, par le chemin de la
    console (`tableau_de_bord.decider_approbation`). Rend `(résultat, None)` ou `(None, verdict)`.

    Ordre des gardes : saisie, identité, appareil, propriétaire, existence, statut, puis
    `_lecture_seule` (N5, outil, politique, arguments). Le propriétaire est vérifié AVANT de lire la
    demande : quelqu'un d'autre n'apprend rien de son état. Si tout passe, la décision est celle de
    `approbations.decider`, qui revérifie la personne, le rôle et le statut, et signe sous
    `nathan_owner` avec l'appareil au journal. `appareil` vient de `contexte.horodatage_reception()`
    (l'appel d'appareil idempotent), jamais des arguments.
    """
    if decision not in DECISIONS:
        return None, _verdict(DECISION_INVALIDE, f"décision : {' ou '.join(DECISIONS)} attendu.")
    if not isinstance(motif, str) or len(motif.strip()) > LIMITE_MOTIF:
        return None, _verdict(MOTIF_INVALIDE, f"motif : un texte d'au plus {LIMITE_MOTIF} caractères est attendu.")
    if not isinstance(demande_id, str) or not demande_id.strip() or len(demande_id.strip()) > LIMITE_IDENTIFIANT:
        return None, _verdict(DEMANDE_INCONNUE, "demande_id : un identifiant de demande est attendu.")
    demande_id = demande_id.strip()
    signataire, verdict = _signataire(cnx, appelante)
    if signataire is None:
        return None, verdict
    if not isinstance(appareil, str) or not appareil.strip():
        return _refuser(cnx, signataire, demande_id, _verdict(
            APPAREIL_INCONNU,
            "La décision doit venir d'un appel d'appareil identifié (appareil et clé d'idempotence). "
            "Rien n'a été décidé.",
        ), decision=decision, appareil=None)
    appareil = appareil.strip()
    if not signataire.proprietaire:
        return _refuser(cnx, signataire, demande_id, _verdict(
            RESERVE_AU_PROPRIETAIRE,
            "Décider une demande depuis l'app est réservé au propriétaire ; cette personne n'a pas ce rôle.",
        ), decision=decision, appareil=appareil)
    demande = approbations.lire(cnx, demande_id)
    if demande is None:
        return None, _verdict(DEMANDE_INCONNUE, f"Aucune demande {demande_id}.")
    if demande["statut"] != "en_attente":
        return None, _verdict(
            DEJA_DECIDEE, f"La demande {demande_id} est déjà traitée ({demande['statut']}) : rien n'a été refait.",
            statut=demande["statut"], decide_par=demande["decide_par"], decide_le=demande["decide_le"],
        )
    refus = _lecture_seule(demande, signataire, departements, _outils_par_nom(departements, cnx))
    if refus is not None:
        return _refuser(cnx, signataire, demande_id, refus, decision=decision, appareil=appareil)
    try:
        # Comme depuis la console : l'outil approuvé ne voit ni l'identité ni les horloges de l'appareil.
        with contexte.receptionne_de(None), contexte.appele_par_appareil(None):
            resultat = tableau_de_bord.decider_approbation(
                cnx, departements, demande_id, decision, signataire.personne.identifiant, motif.strip(), None,
                role=ROLE_SIGNATAIRE, appareil=appareil,
            )
    except (ValueError, KeyError) as exc:
        # Levé par `approbations.decider` avant toute écriture (course avec une autre décision, rôle ou
        # politique changés entre-temps) : rien n'a changé, le message du socle est montré tel quel.
        message = str(exc.args[0]) if exc.args else str(exc)
        return _refuser(cnx, signataire, demande_id, _verdict(DECISION_REFUSEE, message),
                        decision=decision, appareil=appareil)
    decidee = approbations.lire(cnx, demande_id)
    reponse = resultat.get("reponse")
    sortie: dict[str, Any] = {
        "demande_id": demande_id,
        "decision": decision,
        "statut": resultat["statut"],
        "outil": demande["outil"],
        "departement": demande["departement"],
        "niveau": demande["niveau"],
        "decide_par": signataire.personne.identifiant,
        "role": ROLE_SIGNATAIRE,
        "decide_le": decidee["decide_le"] if decidee is not None else None,
    }
    if isinstance(reponse, Mapping):
        sortie["issue"] = _issue(reponse)
    return sortie, None
