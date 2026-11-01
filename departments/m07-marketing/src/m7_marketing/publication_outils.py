"""Les outils de M7 pour les sites WordPress du client et le sas de publication sociale.

Chaque fonction ici est une enveloppe mince : elle établit QUI appelle (la plateforme, jamais un argument), lit le
registre
durable de M7 et appelle la fonction pure de `wordpress/` ou `sas_social/`. Les registres sont des journaux
append-only à
chaîne de hachage de `opsys.stockage` (`sites_wordpress`, `publications_wordpress`, `comptes_sociaux`,
`publications_sociales`).

Niveaux (ADR-0009) :
  - lectures : T0 ; brouillon, révision, soumission, annulation : N2 (rien ne sort d'OPSYS) ;
  - enregistrer un site ou un compte (une connexion permanente à un système externe) : N3 ;
  - approuver une publication publique (article WordPress, publication sociale organique) : N3 ;
  - approuver une annonce PAYANTE (engagement de dépense) : N4.
Un N3 ou un N4 appelé par un agent attend la file d'approbation du propriétaire ; approuvé, il CONSIGNE la décision et
rend `PUBLICATION_APPROUVEE_NON_EXECUTEE` : aucun outil ne transmet un brouillon, n'émet un jeton ni ne publie. Ces
gestes
appartiennent à des exécuteurs hors transaction (`wordpress.executeur`, `sas_social.executeur`) que le planificateur des
connecteurs appelle (désactivé par défaut, activé par un admin) et qui n'ont été exercés qu'avec des doubles de test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from opsys import approbations, stockage
from opsys import contexte as contexte_appel
from opsys.outils import Autonomie, Niveau, Outil

from . import journal_chaine
from .sas_social import comptes, etats, modele, politique, reseaux
from .sas_social import service as sas
from .studio import actifs as actifs_studio
from .usine import service as usine_service
from .wordpress import flux, sites

STATUT_APPROUVEE = "PUBLICATION_APPROUVEE_NON_EXECUTEE"
REGISTRE_SITES = (usine_service.DEPARTEMENT, "sites_wordpress")
REGISTRE_PUBLICATIONS_WP = (usine_service.DEPARTEMENT, "publications_wordpress")
REGISTRE_COMPTES = (usine_service.DEPARTEMENT, "comptes_sociaux")
REGISTRE_PUBLICATIONS_SOCIALES = (usine_service.DEPARTEMENT, "publications_sociales")
POLITIQUE = politique.PolitiqueSas()

NOM_ENREGISTRER_SITE = "m7_enregistrer_site_wordpress"
NOM_DEMANDER_WP = "m7_demander_publication_wordpress"
NOM_ENREGISTRER_COMPTE = "m7_enregistrer_compte_social"
NOM_DEMANDER_SOCIAL = "m7_demander_publication_sociale"
NOM_DEMANDER_ANNONCE = "m7_demander_annonce_payante"

REJ_HORODATAGE = "REJ-PUBLICATION-HORODATAGE"


def _journal(registre: tuple[str, str]):
    return stockage.maillons(*registre)


def _actifs_studio():
    """Le résolveur du registre des actifs du studio créatif : un média « composition déterministe » doit être un visuel
    approuvé par une personne, et un actif du studio ne se présente jamais sous une autre origine (`studio.portes`).
    Fourni à CHAQUE contrôle du sas par les outils : un retrait de cet argument est une régression (test de bout
    en bout)."""
    return actifs_studio.resolveur_du_registre(_journal(actifs_studio.REGISTRE))


def _horodatage(horodatage: str) -> tuple[str, datetime] | dict[str, Any]:
    """(instant UTC en texte, datetime) de l'heure FAISANT FOI (réception serveur pendant un appel d'appareil), ou un
    refus.
    """
    brut = usine_service._horodatage_faisant_foi(horodatage)
    try:
        valeur = datetime.fromisoformat(brut)
    except (TypeError, ValueError):
        valeur = None
    if valeur is None or valeur.tzinfo is None:
        return {
            "accepte": False,
            "refus": [
                {
                    "code": REJ_HORODATAGE,
                    "chemin": "$.horodatage",
                    "detail": "ISO 8601 avec fuseau exigé",
                }
            ],
        }
    valeur = valeur.astimezone(UTC)
    if contexte_appel.horodatage_reception() is None:
        # Exécutée par la file d'approbation : l'heure faisant foi est celle de la DÉCISION (horloge du serveur,
        # écrite par `decider`), jamais l'argument qu'un agent a déposé avec la demande. Sinon l'agent choisirait la
        # validité de l'approbation (« une heure ») et le délai minimal d'une planification.
        decision = approbations.instant_de_la_decision_en_cours(stockage.connexion_courante())
        if decision is not None:
            valeur = decision.astimezone(UTC)
    return modele.en_instant(valeur), valeur


def _decideur(nom_outil: str) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    acteur, refus_humain = usine_service._proprietaire_qui_decide(nom_outil)
    if acteur is not None:
        return acteur, None
    verdict = refus_humain or {"code": "REJ-HUMAIN-REQUIS", "detail": "approbation humaine introuvable"}
    return None, {
        "accepte": False,
        "refus": [
            {
                "code": verdict["code"],
                "chemin": "$",
                "detail": f"{verdict['detail']} Cette décision est celle de la direction (N3/N4) : "
                "la demande attend dans la file "
                "d'approbation, elle n'est jamais exécutée par l'agent.",
            }
        ],
    }


# -- WordPress -------------------------------------------------------------------------------------------------------
def enregistrer_site_wordpress(
    site_id: str,
    base_url: str,
    secret_ref: dict[str, Any],
    types_autorises: list[str],
    fictif: bool,
    horodatage: str,
) -> dict[str, Any]:
    """N3 : branche un site WordPress du client (adresse HTTPS, NOM du secret dans le coffre) au registre de M7."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    acteur, refus = _decideur(NOM_ENREGISTRER_SITE)
    if acteur is None:
        return refus
    return sites.enregistrer(
        _journal(REGISTRE_SITES),
        site_id,
        base_url,
        secret_ref,
        types_autorises,
        fictif,
        acteur["par"],
        instant[0],
    )


def preparer_brouillon_wordpress(
    site_id: str,
    article: dict[str, Any],
    statut_cible: str,
    cle_idempotence: str,
    texte_genere_par_ia: bool,
    horodatage: str,
    publication_id: str | None = None,
) -> dict[str, Any]:
    """N2 : prépare (ou révise) un brouillon d'article. Contrôle le contenu, marque l'IA, consigne ; n'écrit rien sur
    le site.
    """
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    actifs = sites.actifs(_journal(REGISTRE_SITES))
    resultat = flux.preparer(
        _journal(REGISTRE_PUBLICATIONS_WP),
        actifs,
        site_id,
        article,
        statut_cible,
        cle_idempotence,
        texte_genere_par_ia,
        usine_service._qui_appelle()[0],
        instant[0],
        publication_id=publication_id,
    )
    if resultat.get("accepte"):
        resultat = {
            **resultat,
            "transmission": (
                "en attente d'un exécuteur : le brouillon n'est PAS encore sur le site WordPress (le planificateur "
                "des connecteurs le transmet seulement si un admin a activé l'exécuteur m7.wordpress.brouillons)"
            ),
        }
    return resultat


def demander_publication_wordpress(
    publication_id: str,
    empreinte: str,
    action: str,
    horodatage: str,
    publier_le: str | None = None,
) -> dict[str, Any]:
    """N3 : approbation de la direction pour publier (`publish`) ou planifier (`schedule`) CE brouillon, par son
    empreinte.
    """
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    acteur, refus = _decideur(NOM_DEMANDER_WP)
    if acteur is None:
        return refus
    resultat = flux.approuver(
        _journal(REGISTRE_PUBLICATIONS_WP),
        publication_id,
        empreinte,
        action,
        publier_le,
        acteur,
        instant[1],
        instant[0],
    )
    if resultat.get("accepte"):
        resultat = {**resultat, "statut": STATUT_APPROUVEE, "approbation": acteur}
    return resultat


def annuler_publication_wordpress(publication_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """N2 : retire une publication du flux (restriction : aucune approbation requise)."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    return flux.annuler(
        _journal(REGISTRE_PUBLICATIONS_WP),
        publication_id,
        usine_service._qui_appelle()[0],
        motif,
        instant[0],
    )


def lire_publication_wordpress(publication_id: str | None = None, limite: int = 20) -> dict[str, Any]:
    """T0 : une publication en détail, ou les sites enregistrés et les publications récentes."""
    lu = flux.lire(_journal(REGISTRE_PUBLICATIONS_WP), publication_id, limite)
    if publication_id is not None or not lu.get("accepte"):
        return lu
    registre = sites.plier(_journal(REGISTRE_SITES))
    return {
        **lu,
        "sites": [
            {
                "site_id": i,
                "base_url": e["site"].base_url,
                "fictif": e["site"].fictif,
                "actif": e["actif"],
                "types_autorises": list(e["site"].types_autorises),
            }
            for i, e in sorted(registre.items())
        ],
    }


# -- Réseaux sociaux
# ----------------------------------------------------------------------------------------------------
def enregistrer_compte_social(
    reseau: str,
    compte: str,
    secret_ref: dict[str, Any],
    fictif: bool,
    horodatage: str,
) -> dict[str, Any]:
    """N3 : déclare un compte social du client (Page, compte, chaîne) et le NOM de son jeton dans le coffre."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    acteur, refus = _decideur(NOM_ENREGISTRER_COMPTE)
    if acteur is None:
        return refus
    return comptes.enregistrer(
        _journal(REGISTRE_COMPTES), reseau, compte, secret_ref, fictif, acteur["par"], instant[0]
    )


def composer_publication_sociale(
    publication: dict[str, Any],
    cle_idempotence: str,
    horodatage: str,
    publication_id: str | None = None,
) -> dict[str, Any]:
    """N2 : crée (ou révise) un brouillon de publication. Même clé et même contenu : la même publication."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    actifs = set(comptes.actifs(_journal(REGISTRE_COMPTES)))
    return sas.composer(
        _journal(REGISTRE_PUBLICATIONS_SOCIALES),
        publication,
        cle_idempotence,
        actifs,
        usine_service._qui_appelle()[0],
        instant[0],
        publication_id=publication_id,
    )


def soumettre_publication_sociale(publication_id: str, horodatage: str) -> dict[str, Any]:
    """N2 : brouillon -> en attente d'approbation, si TOUS les contrôles passent (texte, médias, IA, quotas, fenêtre,
    budget).
    """
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    return sas.soumettre(
        _journal(REGISTRE_PUBLICATIONS_SOCIALES),
        publication_id,
        reseaux.declarations_par_defaut(),
        POLITIQUE,
        instant[1],
        instant[0],
        _actifs_studio(),
    )


def _approuver_publication(
    nom_outil: str, niveau: int, publication_id: str, empreinte: str, horodatage: str
) -> dict[str, Any]:
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    acteur, refus = _decideur(nom_outil)
    if acteur is None:
        return refus
    resultat = sas.approuver(
        _journal(REGISTRE_PUBLICATIONS_SOCIALES),
        publication_id,
        empreinte,
        niveau,
        acteur,
        reseaux.declarations_par_defaut(),
        POLITIQUE,
        instant[1],
        instant[0],
        _actifs_studio(),
    )
    if resultat.get("accepte"):
        resultat = {**resultat, "statut": STATUT_APPROUVEE}
    return resultat


def demander_publication_sociale(publication_id: str, empreinte: str, horodatage: str) -> dict[str, Any]:
    """N3 : approbation d'une publication ORGANIQUE (publique) par son empreinte exacte ; planifie, ne publie pas."""
    return _approuver_publication(
        NOM_DEMANDER_SOCIAL,
        politique.NIVEAU_ORGANIQUE,
        publication_id,
        empreinte,
        horodatage,
    )


def demander_annonce_payante(publication_id: str, empreinte: str, horodatage: str) -> dict[str, Any]:
    """N4 : approbation d'une ANNONCE PAYANTE (engagement de dépense) par son empreinte exacte, budget compris."""
    return _approuver_publication(
        NOM_DEMANDER_ANNONCE,
        politique.NIVEAU_ANNONCE_PAYANTE,
        publication_id,
        empreinte,
        horodatage,
    )


def annuler_publication_sociale(publication_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """N2 : retire de la file (brouillon, en attente, approuvée, planifiée ou en échec). Une publication déjà sortie ne
    se retire pas d'ici.
    """
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    return sas.annuler(
        _journal(REGISTRE_PUBLICATIONS_SOCIALES),
        publication_id,
        usine_service._qui_appelle()[0],
        motif,
        instant[0],
    )


def lire_file_publication_sociale(
    publication_id: str | None = None,
    etat: str | None = None,
    limite: int = 20,
) -> dict[str, Any]:
    """T0 : la file (en bref) ou une publication (en détail), avec les comptes déclarés."""
    lu = sas.lire(_journal(REGISTRE_PUBLICATIONS_SOCIALES), publication_id, etat, limite)
    if publication_id is not None or not lu.get("accepte"):
        return lu
    declares = comptes.plier(_journal(REGISTRE_COMPTES))
    return {
        **lu,
        "comptes": [
            {"reseau": r, "compte": c, "fictif": e["fictif"], "actif": e["actif"]}
            for (r, c), e in sorted(declares.items())
        ],
        "integrite": {"journal_intact": journal_chaine.integre(_journal(REGISTRE_PUBLICATIONS_SOCIALES))},
    }


# ---------------------------------------------------------------------------
# Manifeste
# ---------------------------------------------------------------------------
_HORODATAGE = {"type": "string", "description": "ISO 8601 avec fuseau (l'heure du serveur fait foi)."}
_EMPREINTE = {
    "type": "string",
    "description": "Empreinte SHA-256 exacte du contenu à approuver, rendue par la préparation.",
}
_SECRET_REF_WP = {
    "type": "object",
    "description": "{nom: NOM du secret dans le coffre, cle_id: identifiant de clé annoncé au plugin} : "
    "jamais la valeur du secret.",
}
_ARTICLE = {
    "type": "object",
    "description": "{type: post|page, titre, contenu (HTML sobre), extrait, slug} : tous les champs, texte seulement.",
}
_PUBLICATION_SOCIALE = {
    "type": "object",
    "description": (
        "{reseau, compte, texte, titre (YouTube), medias [{reference, type_media, format, sha256, octets, "
        "largeur, hauteur, "
        "duree_s, alt, origine, ia_generee, realiste, moderation, controle_ocr}], planifie_le (AAAA-MM-JJTHH:MM:SSZ, "
        "UTC), "
        "divulgation {texte_ia, media_synthetique_realiste, contenu_commercial}, type_publication (organique | "
        "annonce_payante), budget {montant_cents, plafond_quotidien_cents, duree_jours} | null, options}. Un média "
        "origine=genere_non_compose est refusé."
    ),
}
_CLE = {
    "type": "string",
    "description": "Clé d'idempotence de 16 à 64 caractères [A-Za-z0-9_-] : une clé, une publication.",
}


def _objet(proprietes: dict[str, Any], requis: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False}


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom=NOM_ENREGISTRER_SITE,
            description=(
                "DÉCISION DE LA DIRECTION (N3) : branche un site WordPress du client (adresse HTTPS, NOM du secret "
                "du coffre, types "
                "de contenu permis). Un site fictif a un domaine réservé. Le registre ne contient jamais le secret."
            ),
            parametres=_objet(
                {
                    "site_id": {"type": "string"},
                    "base_url": {"type": "string"},
                    "secret_ref": _SECRET_REF_WP,
                    "types_autorises": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(sites.TYPES_CONTENU)},
                    },
                    "fictif": {"type": "boolean"},
                    "horodatage": _HORODATAGE,
                },
                ["site_id", "base_url", "secret_ref", "types_autorises", "fictif", "horodatage"],
            ),
            fonction=enregistrer_site_wordpress,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m7_preparer_brouillon_wordpress",
            description=(
                "Prépare (ou révise, avec publication_id) un BROUILLON d'article WordPress : contrôle le contenu "
                "(contenu actif, "
                "données personnelles, prix, promesses, exagération), exige que le contenu produit par un modèle "
                "soit marqué, "
                "consigne au journal. Statut draft ou pending seulement. N'écrit rien sur le site : la transmission "
                "est faite par "
                "un exécuteur hors transaction."
            ),
            parametres=_objet(
                {
                    "site_id": {"type": "string"},
                    "article": _ARTICLE,
                    "statut_cible": {"type": "string", "enum": list(("draft", "pending"))},
                    "cle_idempotence": _CLE,
                    "texte_genere_par_ia": {"type": "boolean"},
                    "horodatage": _HORODATAGE,
                    "publication_id": {"type": "string"},
                },
                ["site_id", "article", "statut_cible", "cle_idempotence", "texte_genere_par_ia", "horodatage"],
            ),
            fonction=preparer_brouillon_wordpress,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom=NOM_DEMANDER_WP,
            description=(
                "DÉCISION DE LA DIRECTION (N3) : approuve la PUBLICATION (publish) ou la PLANIFICATION (schedule) "
                "d'un brouillon "
                "revu sur le site, par l'empreinte exacte du contenu du site. Un agent ne peut que la déposer dans "
                "la file ; "
                "approuvée, elle est consignée (PUBLICATION_APPROUVEE_NON_EXECUTEE) et rien n'est publié : l'exécuteur "
                "émet le "
                "jeton d'approbation (une fois, 1 heure) et appelle le plugin."
            ),
            parametres=_objet(
                {
                    "publication_id": {"type": "string"},
                    "empreinte": _EMPREINTE,
                    "action": {"type": "string", "enum": ["publish", "schedule"]},
                    "publier_le": {
                        "type": ["string", "null"],
                        "description": "UTC AAAA-MM-JJTHH:MM:SSZ, pour schedule seulement.",
                    },
                    "horodatage": _HORODATAGE,
                },
                ["publication_id", "empreinte", "action", "horodatage"],
            ),
            fonction=demander_publication_wordpress,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m7_annuler_publication_wordpress",
            description=(
                "Retire une publication WordPress du flux (jamais une publication déjà publiée). "
                "Le brouillon du site reste à supprimer à la main."
            ),
            parametres=_objet(
                {
                    "publication_id": {"type": "string"},
                    "motif": {"type": "string", "maxLength": 300},
                    "horodatage": _HORODATAGE,
                },
                ["publication_id", "motif", "horodatage"],
            ),
            fonction=annuler_publication_wordpress,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_lire_publication_wordpress",
            description=(
                "Lit une publication WordPress (état, empreintes, approbation, divergence d'assainissement) ou, "
                "sans identifiant, "
                "les sites enregistrés et les publications récentes. Lecture seule."
            ),
            parametres=_objet(
                {
                    "publication_id": {"type": "string"},
                    "limite": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                [],
            ),
            fonction=lire_publication_wordpress,
        ),
        Outil(
            nom=NOM_ENREGISTRER_COMPTE,
            description=(
                "DÉCISION DE LA DIRECTION (N3) : déclare un compte social du client "
                "(Google Business Profile, Facebook, "
                "Instagram, "
                "LinkedIn, YouTube, TikTok) et le NOM de son jeton dans le coffre (jamais le jeton). Ne prouve pas "
                "que le compte "
                "est autorisé chez le réseau."
            ),
            parametres=_objet(
                {
                    "reseau": {"type": "string", "enum": list(reseaux.RESEAUX)},
                    "compte": {"type": "string"},
                    "secret_ref": {"type": "object", "description": "{nom: NOM du secret dans le coffre}."},
                    "fictif": {"type": "boolean"},
                    "horodatage": _HORODATAGE,
                },
                ["reseau", "compte", "secret_ref", "fictif", "horodatage"],
            ),
            fonction=enregistrer_compte_social,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m7_composer_publication_sociale",
            description=(
                "Crée (ou révise, avec publication_id) un BROUILLON de publication sociale. Même clé et même contenu "
                ": la même "
                "publication (idempotent). Ne publie rien et ne contacte aucun réseau."
            ),
            parametres=_objet(
                {
                    "publication": _PUBLICATION_SOCIALE,
                    "cle_idempotence": _CLE,
                    "horodatage": _HORODATAGE,
                    "publication_id": {"type": "string"},
                },
                ["publication", "cle_idempotence", "horodatage"],
            ),
            fonction=composer_publication_sociale,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_soumettre_publication_sociale",
            description=(
                "Soumet un brouillon à l'approbation SI tous les contrôles passent : texte (garde-fou du socle), "
                "limites du réseau, "
                "médias (aucun média généré sans composition), divulgation d'IA, plafonds de budget, fenêtre de "
                "publication et "
                "quota sur 24 h. Un refus nomme chaque règle ; rien n'est écrit."
            ),
            parametres=_objet(
                {"publication_id": {"type": "string"}, "horodatage": _HORODATAGE}, ["publication_id", "horodatage"]
            ),
            fonction=soumettre_publication_sociale,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom=NOM_DEMANDER_SOCIAL,
            description=(
                "DÉCISION DE LA DIRECTION (N3) : approuve la publication PUBLIQUE d'une publication organique, par "
                "son empreinte "
                "exacte (texte, médias, heure, divulgation). Un agent ne peut que la déposer dans la file ; approuvée, "
                "la "
                "publication est planifiée (PUBLICATION_APPROUVEE_NON_EXECUTEE), jamais envoyée par cet outil. Refuse "
                "une annonce payante."
            ),
            parametres=_objet(
                {"publication_id": {"type": "string"}, "empreinte": _EMPREINTE, "horodatage": _HORODATAGE},
                ["publication_id", "empreinte", "horodatage"],
            ),
            fonction=demander_publication_sociale,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom=NOM_DEMANDER_ANNONCE,
            description=(
                "DÉCISION DE LA DIRECTION (N4, engagement de dépense) : approuve une ANNONCE PAYANTE, budget compris, "
                "par son "
                "empreinte exacte. Plafonds de budget codés en dur. Même approuvée, rien n'est dépensé ni publié "
                "par cet outil."
            ),
            parametres=_objet(
                {"publication_id": {"type": "string"}, "empreinte": _EMPREINTE, "horodatage": _HORODATAGE},
                ["publication_id", "empreinte", "horodatage"],
            ),
            fonction=demander_annonce_payante,
            autonomie=Autonomie.T1,
            niveau=Niveau.N4,
        ),
        Outil(
            nom="m7_annuler_publication_sociale",
            description=(
                "Retire de la file une publication sociale qui n'est pas encore sortie. "
                "Une publication déjà publiée ne se retire pas d'ici."
            ),
            parametres=_objet(
                {
                    "publication_id": {"type": "string"},
                    "motif": {"type": "string", "maxLength": 300},
                    "horodatage": _HORODATAGE,
                },
                ["publication_id", "motif", "horodatage"],
            ),
            fonction=annuler_publication_sociale,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_lire_file_publication_sociale",
            description=(
                "Lit la file de publication sociale (états, niveaux requis, tentatives, erreurs), une publication "
                "en détail, et les "
                "comptes déclarés. Lecture seule."
            ),
            parametres=_objet(
                {
                    "publication_id": {"type": "string"},
                    "etat": {"type": "string", "enum": list(etats.ETATS)},
                    "limite": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                [],
            ),
            fonction=lire_file_publication_sociale,
        ),
    )
