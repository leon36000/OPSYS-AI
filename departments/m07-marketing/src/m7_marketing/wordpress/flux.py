"""Le flux « brouillon -> revue -> approbation N3 -> publication » d'un article WordPress, sur un journal append-only.

    brouillon   l'article existe chez OPSYS (texte contrôlé), pas encore sur le site
    en_revue    le BROUILLON est sur le site (le plugin a rendu son empreinte) : la direction le lit dans WordPress
    approuve    la direction a approuvé CETTE empreinte (N3), pour `publish` ou `schedule` à une heure précise
    publie      le plugin a publié avec le jeton d'approbation (état `publish` ou `future` rendu par le site)
    echec       le plugin a refusé ou le transport a échoué
    annule      retiré du flux

L'approbation lie : le site, l'article (`post_id`), l'EMPREINTE du contenu tel que le site le stocke, l'action,
l'heure de
planification, l'approbateur et une expiration. Une révision après l'approbation, ou un brouillon qui change côté site,
la rend inutilisable. Le jeton lui-même n'est jamais écrit au journal : seul l'identifiant d'approbation l'est, et
le plugin
le consomme une fois.

Aucune fonction ici n'appelle le site : le client (`client.py`) transmet, l'exécuteur appelle ces fonctions pour
consigner.

Module pur : aucune entrée-sortie, l'horloge est un argument.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import secrets
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from opsys import garde_fou_texte as socle

from .. import journal_chaine
from ..sas_social.modele import en_instant, instant
from . import contenu, empreinte, sites

BROUILLON = "brouillon"
EN_REVUE = "en_revue"
APPROUVE = "approuve"
PUBLIE = "publie"
ECHEC = "echec"
ANNULE = "annule"
ETATS = (BROUILLON, EN_REVUE, APPROUVE, PUBLIE, ECHEC, ANNULE)

M_PREPARE = "brouillon_prepare"
M_REVISE = "brouillon_revise"
M_TRANSMIS = "brouillon_transmis"
M_APPROUVE = "approbation_publication"
M_JETON = "jeton_emis"
M_PUBLIE = "publie"
M_ECHEC = "echec"
M_TRANSMISSION_ECHEC = "transmission_echec"
M_ANNULE = "annule"

ROLE_DECIDEUR = "nathan_owner"
VALIDITE_APPROBATION_S = 3600
DELAI_MIN_PLANIFICATION_S = 300
_CLE = re.compile(r"[A-Za-z0-9_-]{16,64}")

REJ_JOURNAL = "REJ-WP-JOURNAL-ALTERE"
REJ_INCOHERENT = "REJ-WP-JOURNAL-INCOHERENT"
REJ_INCONNUE = "REJ-WP-PUBLICATION-INCONNUE"
REJ_ETAT = "REJ-WP-ETAT"
REJ_SITE_INACTIF = "REJ-WP-SITE-INACTIF"
REJ_TYPE = "REJ-WP-TYPE-NON-PERMIS"
REJ_STATUT = "REJ-WP-STATUT-INTERDIT"
REJ_CLE = "REJ-WP-CLE-INVALIDE"
REJ_CLE_CONFLIT = "REJ-WP-CLE-CONFLIT"
REJ_IA = "REJ-WP-IA-NON-DECLAREE"
REJ_HUMAIN = "REJ-WP-HUMAIN-REQUIS"
REJ_EMPREINTE = "REJ-WP-EMPREINTE-DIFFERENTE"
REJ_ACTION = "REJ-WP-ACTION-INVALIDE"
REJ_PLANIFICATION = "REJ-WP-PLANIFICATION-INVALIDE"
REJ_APPROBATION_ABSENTE = "REJ-WP-APPROBATION-ABSENTE"
REJ_APPROBATION_EXPIREE = "REJ-WP-APPROBATION-EXPIREE"
REJ_APPROBATION_UTILISEE = "REJ-WP-APPROBATION-DEJA-UTILISEE"
REJ_DIVERGENCE = "REJ-WP-CONTENU-DIVERGENT"


class JournalIncoherent(ValueError):
    pass


@dataclasses.dataclass
class EtatArticle:
    publication_id: str
    etat: str
    site_id: str
    type_contenu: str
    cle_idempotence: str
    article: dict[str, Any]
    statut_cible: str
    ia_generee: bool
    empreinte_locale: str
    revision: int = 1
    post_id: int | None = None
    empreinte_serveur: str | None = None
    divergence: bool = False
    approbation: dict[str, Any] | None = None
    jeton_emis: bool = False
    statut_site: str | None = None
    lien_public: str | None = None
    derniere_erreur: dict[str, Any] | None = None
    rangs: list[int] = dataclasses.field(default_factory=list)

    def resume(self) -> dict[str, Any]:
        return {
            "publication_id": self.publication_id,
            "etat": self.etat,
            "site_id": self.site_id,
            "type": self.type_contenu,
            "post_id": self.post_id,
            "empreinte_locale": self.empreinte_locale,
            "empreinte_serveur": self.empreinte_serveur,
            "divergence": self.divergence,
            "revision": self.revision,
            "ia_generee": self.ia_generee,
            "statut_site": self.statut_site,
            "approbation": None
            if self.approbation is None
            else {
                "approval_id": self.approbation["approval_id"],
                "action": self.approbation["action"],
                "publish_at": self.approbation["publish_at"],
                "expire_le": self.approbation["expire_le"],
                "par": self.approbation["par"],
            },
            "jeton_emis": self.jeton_emis,
            "derniere_erreur": self.derniere_erreur,
        }


@dataclasses.dataclass(frozen=True)
class ApprobationVerifiee:
    """Ce que l'exécuteur a le droit de transformer en jeton : une approbation humaine consignée, encore valable,
    pour le
    contenu actuel. Elle ne se construit que par `approbation_verifiee`."""

    publication_id: str
    approval_id: str
    site_id: str
    post_id: int
    empreinte: str
    action: str
    publish_at: str | None
    approuve_par: str
    emis_le: int
    expire_le: int


def _appliquer(etats: dict[str, EtatArticle], m: Mapping[str, Any]) -> None:
    identifiant = m.get("publication_id")
    type_maillon = m["type"]
    if type_maillon == M_PREPARE:
        if identifiant in etats:
            raise JournalIncoherent(f"rang {m['rang']} : {identifiant} déjà préparée")
        a = m["article"]
        etats[identifiant] = EtatArticle(
            publication_id=identifiant,
            etat=BROUILLON,
            site_id=m["site_id"],
            type_contenu=a["type"],
            cle_idempotence=m["cle_idempotence"],
            article=a,
            statut_cible=m["statut_cible"],
            ia_generee=m["ia_generee"],
            empreinte_locale=m["empreinte_locale"],
            rangs=[m["rang"]],
        )
        return
    courant = etats.get(identifiant)
    if courant is None:
        raise JournalIncoherent(f"rang {m['rang']} : publication {identifiant!r} inconnue")
    courant.rangs.append(m["rang"])
    if type_maillon == M_REVISE:
        if courant.etat not in (BROUILLON, EN_REVUE):
            raise JournalIncoherent(f"rang {m['rang']} : révision depuis {courant.etat}")
        courant.article, courant.statut_cible = m["article"], m["statut_cible"]
        courant.ia_generee, courant.empreinte_locale = m["ia_generee"], m["empreinte_locale"]
        courant.revision += 1
        courant.approbation, courant.empreinte_serveur, courant.divergence = None, None, False
        # Un brouillon déjà sur le site doit y être retransmis (mise à jour) : l'empreinte à approuver sera celle du
        # site.
        courant.etat = BROUILLON
        return
    if type_maillon == M_TRANSMIS:
        if courant.etat not in (BROUILLON, EN_REVUE, ECHEC) and not (
            courant.etat == APPROUVE and not courant.jeton_emis
        ):
            raise JournalIncoherent(f"rang {m['rang']} : transmission depuis {courant.etat}")
        courant.post_id, courant.empreinte_serveur = m["post_id"], m["empreinte_serveur"]
        courant.divergence = m["empreinte_serveur"] != courant.empreinte_locale
        # Une nouvelle synchronisation du site efface toute approbation antérieure : elle portait une autre empreinte.
        courant.approbation, courant.jeton_emis, courant.derniere_erreur = None, False, None
        courant.etat = EN_REVUE
        return
    if type_maillon == M_TRANSMISSION_ECHEC:
        if courant.etat not in (BROUILLON, EN_REVUE, ECHEC):
            raise JournalIncoherent(f"rang {m['rang']} : échec de transmission depuis {courant.etat}")
        courant.derniere_erreur = {"code": m["code"], "detail": m["detail"]}
        return
    if type_maillon == M_APPROUVE:
        if courant.etat != EN_REVUE:
            raise JournalIncoherent(f"rang {m['rang']} : approbation depuis {courant.etat}")
        courant.approbation = {
            k: m[k]
            for k in (
                "approval_id",
                "action",
                "publish_at",
                "par",
                "role",
                "source",
                "empreinte",
                "post_id",
                "emis_le",
                "expire_le",
            )
        }
        courant.etat = APPROUVE
        return
    if type_maillon == M_JETON:
        if (
            courant.etat != APPROUVE
            or courant.approbation is None
            or courant.approbation["approval_id"] != m["approval_id"]
        ):
            raise JournalIncoherent(f"rang {m['rang']} : jeton émis hors approbation")
        courant.jeton_emis = True
        return
    if type_maillon == M_PUBLIE and courant.etat == ANNULE and courant.jeton_emis:
        # Une annulation a été posée APRÈS l'émission du jeton, pendant l'appel au site : le site a publié quand même.
        # Le registre dit la vérité sans devenir incohérent (il serait mort pour toujours, tous articles confondus).
        courant.etat, courant.statut_site, courant.lien_public = PUBLIE, m["statut_site"], m.get("lien_public")
        courant.derniere_erreur = None
        return
    if type_maillon == M_PUBLIE:
        if courant.etat != APPROUVE or not courant.jeton_emis:
            raise JournalIncoherent(f"rang {m['rang']} : publication sans jeton émis")
        courant.etat, courant.statut_site, courant.lien_public = PUBLIE, m["statut_site"], m.get("lien_public")
        courant.derniere_erreur = None
        return
    if type_maillon == M_ECHEC:
        if courant.etat != APPROUVE:
            raise JournalIncoherent(f"rang {m['rang']} : échec de publication depuis {courant.etat}")
        courant.etat = ECHEC
        courant.derniere_erreur = {"code": m["code"], "detail": m["detail"]}
        return
    if type_maillon == M_ANNULE:
        if courant.etat in (PUBLIE, ANNULE):
            raise JournalIncoherent(f"rang {m['rang']} : annulation depuis {courant.etat}")
        courant.etat = ANNULE
        return
    raise JournalIncoherent(f"rang {m['rang']} : type de maillon inconnu {type_maillon!r}")


def plier(journal: Any) -> dict[str, EtatArticle]:
    etats: dict[str, EtatArticle] = {}
    for maillon in journal:
        _appliquer(etats, maillon)
    return etats


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def charger(journal: Any) -> tuple[dict[str, EtatArticle], dict[str, Any] | None]:
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return {}, _refus(REJ_JOURNAL, "$", "; ".join(problemes[:3]))
    try:
        return plier(journal), None
    except JournalIncoherent as exc:
        return {}, _refus(REJ_INCOHERENT, "$", str(exc))


def identifiant_publication(site_id: str, cle: str) -> str:
    return "wp-" + hashlib.sha256(f"{site_id}\n{cle}".encode()).hexdigest()[:20]


def empreinte_locale(article: Mapping[str, Any]) -> str:
    """L'empreinte de l'article tel qu'OPSYS l'envoie, sans image à la une : celle que le plugin rendra (sur ce qu'il
    stocke) peut en différer si l'assainissement a changé quelque chose : c'est alors une `divergence`, dite et
    visible."""
    return empreinte.empreinte_contenu(
        {
            "type": article["type"],
            "titre": article["titre"],
            "contenu": article["contenu"],
            "extrait": article["extrait"],
            "slug": article["slug"],
            "image_a_la_une_sha256": "",
        }
    )


CHAMPS_ARTICLE = ("type", "titre", "contenu", "extrait", "slug")


def preparer(
    journal: Any,
    sites_actifs: Mapping[str, sites.SiteWordPress],
    site_id: str,
    article: Any,
    statut_cible: Any,
    cle_idempotence: Any,
    texte_genere_par_ia: Any,
    par: str,
    horodatage: str,
    *,
    publication_id: str | None = None,
    contexte_texte: socle.Contexte | None = None,
) -> dict[str, Any]:
    """Crée (ou révise, avec `publication_id`) un brouillon d'article : contenu contrôlé, statut `draft` ou
    `pending` seulement.
    Même clé et même contenu : la même publication, rien d'écrit."""
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    site = sites_actifs.get(site_id)
    if site is None:
        return _refus(REJ_SITE_INACTIF, "$.site_id", f"site {site_id!r} inconnu ou désactivé")
    if type(texte_genere_par_ia) is not bool:
        return _refus(
            REJ_IA, "$.texte_genere_par_ia", "booléen exigé : un contenu produit par un modèle est marqué comme tel"
        )
    if statut_cible not in contenu.STATUTS_BROUILLON:
        return _refus(
            REJ_STATUT,
            "$.statut_cible",
            f"{statut_cible!r} refusé : un article n'est jamais créé publié ({list(contenu.STATUTS_BROUILLON)} "
            f"seulement) ; "
            "la publication passe par l'approbation de la direction",
        )
    if not isinstance(cle_idempotence, str) or not _CLE.fullmatch(cle_idempotence):
        return _refus(REJ_CLE, "$.cle_idempotence", "16 à 64 caractères [A-Za-z0-9_-]")
    if not isinstance(article, Mapping) or set(article) != set(CHAMPS_ARTICLE):
        return _refus(contenu.REJ_CHAMP, "$.article", f"champs exacts {list(CHAMPS_ARTICLE)} attendus")
    if article["type"] not in site.types_autorises:
        return _refus(REJ_TYPE, "$.article.type", f"types permis pour ce site : {list(site.types_autorises)}")
    problemes = contenu.controler(dict(article), contexte_texte)
    if problemes:
        return {"accepte": False, "refus": problemes}
    copie = {nom: article[nom] for nom in CHAMPS_ARTICLE}
    locale = empreinte_locale(copie)
    if publication_id is not None:
        courant = tous.get(publication_id)
        if courant is None:
            return _refus(REJ_INCONNUE, "$.publication_id", f"publication inconnue : {publication_id!r}")
        if courant.site_id != site_id:
            return _refus(REJ_SITE_INACTIF, "$.site_id", "le site d'une publication ne change pas")
        if courant.etat not in (BROUILLON, EN_REVUE, APPROUVE):
            return _refus(REJ_ETAT, "$.publication_id", f"publication {courant.etat} : plus de révision possible")
        if courant.etat == APPROUVE and courant.jeton_emis:
            return _refus(REJ_ETAT, "$.publication_id", "un jeton d'approbation a été émis : annuler et recréer")
        if (
            courant.empreinte_locale == locale
            and courant.statut_cible == statut_cible
            and courant.ia_generee == texte_genere_par_ia
        ):
            return {
                "accepte": True,
                "publication_id": publication_id,
                "etat": courant.etat,
                "empreinte_locale": locale,
                "deja_prepare": True,
            }
        if courant.etat == APPROUVE:
            return _refus(
                REJ_ETAT, "$.publication_id", "approuvée : une révision annule l'approbation, annuler d'abord"
            )
        journal_chaine.ajouter(
            journal,
            M_REVISE,
            {
                "publication_id": publication_id,
                "article": copie,
                "statut_cible": statut_cible,
                "ia_generee": texte_genere_par_ia,
                "empreinte_locale": locale,
                "par": par,
            },
            horodatage,
        )
        return {
            "accepte": True,
            "publication_id": publication_id,
            "etat": BROUILLON,
            "empreinte_locale": locale,
            "deja_prepare": False,
            "revision": courant.revision + 1,
        }
    identifiant = identifiant_publication(site_id, cle_idempotence)
    existant = tous.get(identifiant)
    if existant is not None:
        if existant.empreinte_locale != locale:
            return _refus(
                REJ_CLE_CONFLIT, "$.cle_idempotence", f"cette clé désigne déjà {identifiant} avec un autre contenu"
            )
        return {
            "accepte": True,
            "publication_id": identifiant,
            "etat": existant.etat,
            "empreinte_locale": locale,
            "deja_prepare": True,
        }
    journal_chaine.ajouter(
        journal,
        M_PREPARE,
        {
            "publication_id": identifiant,
            "site_id": site_id,
            "article": copie,
            "statut_cible": statut_cible,
            "cle_idempotence": cle_idempotence,
            "ia_generee": texte_genere_par_ia,
            "empreinte_locale": locale,
            "par": par,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "publication_id": identifiant,
        "etat": BROUILLON,
        "empreinte_locale": locale,
        "deja_prepare": False,
    }


def consigner_transmission(
    journal: Any,
    publication_id: str,
    post_id: int,
    empreinte_serveur: str,
    horodatage: str,
) -> dict[str, Any]:
    """Appelé par l'exécuteur après que le plugin a créé ou mis à jour le brouillon : l'empreinte du SITE devient
    celle que
    la direction approuvera. Une différence avec l'empreinte locale (assainissement du plugin) est consignée comme
    divergence.

    Le plugin a été appelé (réseau) AVANT cette écriture : le rang du journal est lu avant l'état et l'écriture exige
    qu'il n'ait pas bougé (une annulation ou une publication écrite entre-temps rendrait le journal incohérent)."""
    rang = len(journal)
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    courant = tous.get(publication_id)
    if courant is None:
        return _refus(REJ_INCONNUE, "$.publication_id", publication_id)
    if courant.etat not in (BROUILLON, EN_REVUE, ECHEC) and not (courant.etat == APPROUVE and not courant.jeton_emis):
        return _refus(REJ_ETAT, "$.publication_id", f"publication {courant.etat} : transmission impossible")
    if type(post_id) is not int or post_id <= 0 or not re.fullmatch(r"[0-9a-f]{64}", empreinte_serveur or ""):
        return _refus(REJ_EMPREINTE, "$", "réponse du site invalide (post_id, empreinte)")
    try:
        journal_chaine.ajouter(
            journal,
            M_TRANSMIS,
            {
                "publication_id": publication_id,
                "post_id": post_id,
                "empreinte_serveur": empreinte_serveur,
            },
            horodatage,
            rang_attendu=rang,
        )
    except journal_chaine.ConcurrenceJournal:
        return _refus(REJ_ETAT, "$.publication_id", "la publication a changé pendant la transmission : relire")
    return {
        "accepte": True,
        "publication_id": publication_id,
        "etat": EN_REVUE,
        "divergence": empreinte_serveur != courant.empreinte_locale,
    }


def approuver(
    journal: Any,
    publication_id: str,
    empreinte_approuvee: str,
    action: Any,
    publish_at: Any,
    approbateur: Mapping[str, str] | None,
    maintenant: datetime,
    horodatage: str,
) -> dict[str, Any]:
    """en_revue -> approuve : la direction approuve l'EMPREINTE DU SITE, pour `publish` ou `schedule` (heure UTC
    future).
    N'émet aucun jeton et n'appelle pas le site : elle consigne la décision que l'exécuteur transformera, une fois."""
    if (
        approbateur is None
        or approbateur.get("role") != ROLE_DECIDEUR
        or not approbateur.get("par")
        or not approbateur.get("source")
    ):
        return _refus(REJ_HUMAIN, "$", "publier un article est une décision humaine de la direction (N3)")
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    courant = tous.get(publication_id)
    if courant is None:
        return _refus(REJ_INCONNUE, "$.publication_id", publication_id)
    if courant.etat != EN_REVUE or courant.post_id is None or courant.empreinte_serveur is None:
        return _refus(
            REJ_ETAT, "$.publication_id", f"publication {courant.etat} : seul un brouillon revu sur le site s'approuve"
        )
    if empreinte_approuvee != courant.empreinte_serveur:
        return _refus(
            REJ_EMPREINTE,
            "$.empreinte",
            f"l'empreinte approuvée n'est pas celle du brouillon sur le site ({courant.empreinte_serveur})",
        )
    if action not in ("publish", "schedule"):
        return _refus(REJ_ACTION, "$.action", "publish ou schedule")
    if action == "schedule":
        try:
            prevu = instant(publish_at)
        except ValueError:
            return _refus(REJ_PLANIFICATION, "$.publier_le", "instant UTC AAAA-MM-JJTHH:MM:SSZ exigé pour schedule")
        if prevu < maintenant + timedelta(seconds=DELAI_MIN_PLANIFICATION_S):
            return _refus(REJ_PLANIFICATION, "$.publier_le", f"au moins {DELAI_MIN_PLANIFICATION_S} s dans le futur")
    elif publish_at is not None:
        return _refus(REJ_PLANIFICATION, "$.publier_le", "publier_le est réservé à schedule")
    emis = int(maintenant.timestamp())
    approval_id = secrets.token_urlsafe(18)
    journal_chaine.ajouter(
        journal,
        M_APPROUVE,
        {
            "publication_id": publication_id,
            "approval_id": approval_id,
            "action": action,
            "publish_at": publish_at if action == "schedule" else None,
            "empreinte": courant.empreinte_serveur,
            "post_id": courant.post_id,
            "par": approbateur["par"],
            "role": approbateur["role"],
            "source": approbateur["source"],
            "emis_le": emis,
            "expire_le": emis + VALIDITE_APPROBATION_S,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "publication_id": publication_id,
        "etat": APPROUVE,
        "approval_id": approval_id,
        "action": action,
        "expire_le": en_instant(datetime.fromtimestamp(emis + VALIDITE_APPROBATION_S, tz=maintenant.tzinfo)),
        "execute": False,
        "execution": (
            "Aucune : l'exécuteur hors transaction émet le jeton d'approbation depuis le coffre et appelle le "
            "plugin. Aucun outil d'agent ne publie."
        ),
    }


def approbation_verifiee(
    journal: Any, publication_id: str, maintenant: datetime
) -> ApprobationVerifiee | dict[str, Any]:
    """L'approbation à transformer en jeton, SI elle existe, n'est pas expirée, n'a pas déjà servi et porte l'empreinte
    actuelle du brouillon ; sinon le refus typé."""
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    courant = tous.get(publication_id)
    if courant is None:
        return _refus(REJ_INCONNUE, "$.publication_id", publication_id)
    approbation = courant.approbation
    if courant.etat != APPROUVE or approbation is None:
        return _refus(REJ_APPROBATION_ABSENTE, "$", f"publication {courant.etat} : aucune approbation en cours")
    if courant.jeton_emis:
        return _refus(
            REJ_APPROBATION_UTILISEE,
            "$",
            "le jeton de cette approbation a déjà été émis : une approbation sert une fois",
        )
    if (
        approbation["role"] != ROLE_DECIDEUR
        or approbation["empreinte"] != courant.empreinte_serveur
        or approbation["post_id"] != courant.post_id
    ):
        return _refus(REJ_EMPREINTE, "$", "l'approbation ne correspond plus au brouillon")
    if int(maintenant.timestamp()) >= approbation["expire_le"]:
        return _refus(REJ_APPROBATION_EXPIREE, "$", "approbation expirée : en demander une nouvelle")
    return ApprobationVerifiee(
        publication_id=publication_id,
        approval_id=approbation["approval_id"],
        site_id=courant.site_id,
        post_id=courant.post_id,
        empreinte=approbation["empreinte"],
        action=approbation["action"],
        publish_at=approbation["publish_at"],
        approuve_par=approbation["par"],
        emis_le=approbation["emis_le"],
        expire_le=approbation["expire_le"],
    )


def consigner_jeton_emis(journal: Any, approbation: ApprobationVerifiee, horodatage: str) -> dict[str, Any] | None:
    """À écrire AVANT l'envoi du jeton au site : si l'envoi échoue ou que la réponse se perd, l'approbation est brûlée
    (jamais deux jetons pour une approbation) et la direction en donne une nouvelle.

    C'est la CONSOMMATION de l'approbation, donc une comparaison-échange : `None` si CE appel a consigné le jeton,
    sinon le refus typé (`REJ_APPROBATION_UTILISEE`) et RIEN n'est écrit. Entre `approbation_verifiee` et ici
    l'exécuteur a relu le site (appel réseau) : un autre exécuteur (bail expiré, second processus) a pu consigner le
    jeton et publier. Le rang du journal est donc lu AVANT de relire l'état, et l'écriture exige que le journal soit
    encore à ce rang : au moindre maillon écrit entre-temps, elle est refusée. L'appelant n'envoie AUCUN jeton sur un
    refus."""
    rang = len(journal)
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    courant = tous.get(approbation.publication_id)
    if (
        courant is None
        or courant.etat != APPROUVE
        or courant.jeton_emis
        or courant.approbation is None
        or courant.approbation["approval_id"] != approbation.approval_id
    ):
        return _refus(REJ_APPROBATION_UTILISEE, "$", "cette approbation a déjà servi ou n'est plus en cours")
    try:
        journal_chaine.ajouter(
            journal,
            M_JETON,
            {
                "publication_id": approbation.publication_id,
                "approval_id": approbation.approval_id,
                "expire_le": approbation.expire_le,
            },
            horodatage,
            rang_attendu=rang,
        )
    except journal_chaine.ConcurrenceJournal:
        return _refus(REJ_APPROBATION_UTILISEE, "$", "le journal a changé pendant la vérification : rien n'est émis")
    return None


def consigner_publication(
    journal: Any, publication_id: str, statut_site: str, lien_public: str | None, horodatage: str
) -> bool:
    """Le site a publié (réponse du plugin, ou relecture du site après une réponse perdue).

    Rend True si CE appel a consigné la publication. Elle ne l'est qu'une fois et seulement si le jeton est parti
    (`jeton_emis`) et que la publication n'est pas déjà `publie` : deux exécuteurs peuvent constater la même sortie
    (l'un publie, l'autre réconcilie après un bail repris), et une seconde écriture de `publie` rendrait le journal
    incohérent pour toujours. Comparaison-échange sur le rang lu AVANT l'état : au moindre maillon écrit entre-temps
    le geste est refusé, et le prochain tour (réconciliation, relecture du site) consigne la vérité."""
    rang = len(journal)
    tous, refus = charger(journal)
    courant = None if refus is not None else tous.get(publication_id)
    if courant is None or not courant.jeton_emis or courant.etat not in (APPROUVE, ANNULE):
        return False
    try:
        journal_chaine.ajouter(
            journal,
            M_PUBLIE,
            {
                "publication_id": publication_id,
                "statut_site": statut_site,
                "lien_public": lien_public,
            },
            horodatage,
            rang_attendu=rang,
        )
    except journal_chaine.ConcurrenceJournal:
        return False
    return True


def consigner_echec_transmission(
    journal: Any, publication_id: str, code: str, detail: str, horodatage: str
) -> bool:
    """Le brouillon n'a pas pu être créé ou mis à jour : l'état ne change pas (on retransmet), la cause est consignée.

    Rend True si la cause est consignée. Elle ne l'est que pour une publication encore à transmettre (brouillon, en
    revue, en échec) à l'instant de l'écriture : l'appel au site (réseau) précède cette écriture, et une annulation
    posée pendant ce temps rendrait le journal incohérent (plus aucune lecture possible, tous articles confondus)."""
    rang = len(journal)
    tous, refus = charger(journal)
    courant = None if refus is not None else tous.get(publication_id)
    if courant is None or courant.etat not in (BROUILLON, EN_REVUE, ECHEC):
        return False
    try:
        journal_chaine.ajouter(
            journal,
            M_TRANSMISSION_ECHEC,
            {
                "publication_id": publication_id,
                "code": code[:80],
                "detail": detail[:300],
            },
            horodatage,
            rang_attendu=rang,
        )
    except journal_chaine.ConcurrenceJournal:
        return False
    return True


def consigner_echec(journal: Any, publication_id: str, code: str, detail: str, horodatage: str) -> bool:
    """La publication a échoué après l'émission du jeton (ou son approbation est tombée) : l'approbation est brûlée ;
    `consigner_transmission` (après une relecture de l'état du site) rouvre la revue.

    Rend True si l'échec est consigné. Il ne l'est QUE pour une publication encore `approuve` à l'instant de
    l'écriture (comparaison-échange sur le rang du journal, lu avant l'état) : l'exécuteur travaille sur un instantané
    de début de tour, et une publication annulée, publiée ou retransmise entre-temps rendrait le journal incohérent
    (plus aucune lecture possible, tous articles confondus) si on y écrivait un échec."""
    rang = len(journal)
    tous, refus = charger(journal)
    courant = None if refus is not None else tous.get(publication_id)
    if courant is None or courant.etat != APPROUVE:
        return False
    try:
        journal_chaine.ajouter(
            journal,
            M_ECHEC,
            {
                "publication_id": publication_id,
                "code": code[:80],
                "detail": detail[:300],
            },
            horodatage,
            rang_attendu=rang,
        )
    except journal_chaine.ConcurrenceJournal:
        return False
    return True


def annuler(journal: Any, publication_id: str, par: str, motif: str, horodatage: str) -> dict[str, Any]:
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    courant = tous.get(publication_id)
    if courant is None:
        return _refus(REJ_INCONNUE, "$.publication_id", publication_id)
    if courant.etat in (PUBLIE, ANNULE):
        return _refus(REJ_ETAT, "$.publication_id", f"publication {courant.etat} : rien à annuler")
    journal_chaine.ajouter(
        journal,
        M_ANNULE,
        {
            "publication_id": publication_id,
            "par": par,
            "motif": motif[:300],
            "etat_avant": courant.etat,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "publication_id": publication_id,
        "etat": ANNULE,
        "attention": "le brouillon reste sur le site WordPress : le supprimer à la main" if courant.post_id else None,
    }


def lire(journal: Any, publication_id: str | None = None, limite: int = 20) -> dict[str, Any]:
    tous, refus = charger(journal)
    if refus is not None:
        return refus
    if publication_id is not None:
        courant = tous.get(publication_id)
        if courant is None:
            return _refus(REJ_INCONNUE, "$.publication_id", publication_id)
        return {
            "accepte": True,
            "publication": {**courant.resume(), "article": courant.article, "rangs": courant.rangs},
        }
    recentes = sorted(tous.values(), key=lambda e: e.rangs[-1], reverse=True)
    return {
        "accepte": True,
        "total": len(recentes),
        "publications": [e.resume() for e in recentes[: max(1, min(limite, 50))]],
    }
