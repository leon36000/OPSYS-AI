"""Les contrôles du sas, du plus proche du contenu au plus proche de l'horloge. Chaque refus est typé
`{code, chemin, detail}` et NOMME la règle ; aucun contrôle ne corrige ni ne complète en silence.

Les limites d'un réseau sont lues sur la CLASSE d'adaptateur (`adaptateur.LIMITES`, `adaptateur.valider_options`) :
le sas
n'a aucune copie des chiffres. Le texte passe par le garde-fou du socle (`opsys.garde_fou_texte`, profil de M7 :
adresse,
coordonnées, nom de client, identifiant interne, prix, chiffre non sourcé, garantie, promesse de date, exagération,
lien),
les médias par les règles de la décision r2 n°3 (aucun texte, logo ou mention produits par un modèle d'image sans
composition déterministe et contrôle OCR) et par la modération (visages, plaques : la revue humaine reste requise sur un
doute de détection), la divulgation d'IA par le calcul des médias, l'annonce payante par des plafonds de budget
codés ici.

Module pur : aucune entrée-sortie, aucune horloge (le moment est un argument).
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from ..moderation.floutage import RapportPhoto
from ..usine import controle_texte
from . import modele
from .politique import NIVEAU_ANNONCE_PAYANTE, NIVEAU_ORGANIQUE, PolitiqueSas
from .reseaux import IMAGE, VIDEO, DeclarationReseau, LimitesReseau

REJ_RESEAU_INCONNU = "REJ-SOCIAL-RESEAU-INCONNU"
REJ_TITRE = "REJ-SOCIAL-TITRE"
REJ_TITRE_LONG = "REJ-SOCIAL-TITRE-LONG"
REJ_HASHTAGS = "REJ-SOCIAL-HASHTAGS"
REJ_MEDIAS_NOMBRE = "REJ-SOCIAL-MEDIAS-NOMBRE"
REJ_MEDIA_FORMAT = "REJ-SOCIAL-MEDIA-FORMAT"
REJ_MEDIA_TAILLE = "REJ-SOCIAL-MEDIA-TAILLE"
REJ_MEDIA_DUREE = "REJ-SOCIAL-MEDIA-DUREE"
REJ_MEDIAS_MELANGE = "REJ-SOCIAL-MEDIAS-MELANGE"
REJ_MEDIA_GENERE_NON_COMPOSE = "REJ-SOCIAL-MEDIA-GENERE-NON-COMPOSE"
REJ_MEDIA_OCR = "REJ-SOCIAL-MEDIA-OCR-NON-CONFORME"
REJ_MEDIA_MODERATION = "REJ-SOCIAL-MEDIA-MODERATION"
REJ_MEDIA_IA_INCOHERENTE = "REJ-SOCIAL-MEDIA-IA-INCOHERENTE"
REJ_DIVULGATION_INCOHERENTE = "REJ-SOCIAL-DIVULGATION-INCOHERENTE"
REJ_DIVULGATION_IMPOSSIBLE = "REJ-SOCIAL-DIVULGATION-IMPOSSIBLE"
REJ_OPTIONS = "REJ-SOCIAL-OPTIONS-RESEAU"
REJ_TYPE_INCOHERENT = "REJ-SOCIAL-TYPE-INCOHERENT"
REJ_ANNONCE_NON_SUPPORTEE = "REJ-SOCIAL-ANNONCE-NON-SUPPORTEE"
REJ_BUDGET = "REJ-SOCIAL-BUDGET-PLAFOND"
REJ_PASSE = "REJ-SOCIAL-PLANIFICATION-TROP-PROCHE"
REJ_HORIZON = "REJ-SOCIAL-PLANIFICATION-TROP-LOINTAINE"
REJ_HORS_FENETRE = "REJ-SOCIAL-HORS-FENETRE"
REJ_QUOTA = "REJ-SOCIAL-QUOTA-24H"
REJ_NIVEAU = "REJ-SOCIAL-NIVEAU-INSUFFISANT"

_HASHTAG = re.compile(r"(?<![\w#])#\w+", re.UNICODE)


def _refus(code: str, chemin: str, detail: str) -> dict[str, str]:
    return {"code": code, "chemin": chemin, "detail": detail}


def niveau_requis(publication: modele.Publication) -> int:
    """N3 pour toute publication publique, N4 pour une annonce payante (engagement de dépense)."""
    return NIVEAU_ANNONCE_PAYANTE if publication.type_publication == modele.ANNONCE_PAYANTE else NIVEAU_ORGANIQUE


def moderation_depuis_rapport(rapport: RapportPhoto, *, revue_humaine_faite: bool) -> str:
    """Le statut de modération d'un média à partir du rapport de floutage de `moderation/` : un doute de détection exige
    une revue humaine ; tant qu'elle n'est pas faite le média est `revue_requise`, jamais `verifiee`."""
    if rapport.revue_humaine_requise and not revue_humaine_faite:
        return "revue_requise"
    return "verifiee"


def controler_texte(
    publication: modele.Publication, limites: LimitesReseau, politique: PolitiqueSas
) -> list[dict[str, str]]:
    refus: list[dict[str, str]] = []
    contexte = dataclasses.replace(politique.contexte_texte, longueur_max=limites.texte_max)
    for violation in controle_texte.controler_texte(publication.texte, contexte):
        refus.append(_refus(violation.regle, "$.texte", violation.detail))
    if publication.titre is None:
        if limites.titre_requis:
            refus.append(_refus(REJ_TITRE, "$.titre", f"un titre est exigé sur {limites.reseau}"))
    elif limites.titre_max is None:
        refus.append(_refus(REJ_TITRE, "$.titre", f"{limites.reseau} n'a pas de titre"))
    else:
        if len(publication.titre) > limites.titre_max:
            refus.append(
                _refus(REJ_TITRE_LONG, "$.titre", f"{len(publication.titre)} caractères, {limites.titre_max} au plus")
            )
        for violation in controle_texte.controler_texte(
            publication.titre, dataclasses.replace(contexte, longueur_max=None)
        ):
            refus.append(_refus(violation.regle, "$.titre", violation.detail))
    if limites.hashtags_max is not None:
        nombre = len(_HASHTAG.findall(publication.texte))
        if nombre > limites.hashtags_max:
            refus.append(_refus(REJ_HASHTAGS, "$.texte", f"{nombre} mots-clics, {limites.hashtags_max} au plus"))
    return refus


def controler_medias(publication: modele.Publication, limites: LimitesReseau) -> list[dict[str, str]]:
    refus: list[dict[str, str]] = []
    medias = publication.medias
    if not limites.medias_min <= len(medias) <= limites.medias_max:
        refus.append(
            _refus(
                REJ_MEDIAS_NOMBRE,
                "$.medias",
                f"{len(medias)} média(s) ; {limites.reseau} en exige de {limites.medias_min} à {limites.medias_max}",
            )
        )
    types = {m.type_media for m in medias}
    if types == {IMAGE, VIDEO} and not limites.melange_medias:
        refus.append(_refus(REJ_MEDIAS_MELANGE, "$.medias", f"{limites.reseau} n'accepte pas images et vidéo ensemble"))
    for rang, media in enumerate(medias):
        chemin = f"$.medias[{rang}]"
        permis = limites.formats_images if media.type_media == IMAGE else limites.formats_videos
        if media.format not in permis:
            refus.append(
                _refus(
                    REJ_MEDIA_FORMAT,
                    f"{chemin}.format",
                    f"{media.format} non accepté pour {media.type_media} sur {limites.reseau} "
                    f"(permis : {sorted(permis)})",
                )
            )
        if media.octets > limites.octets_max:
            refus.append(
                _refus(REJ_MEDIA_TAILLE, f"{chemin}.octets", f"{media.octets} octets, {limites.octets_max} au plus")
            )
        if (
            media.type_media == VIDEO
            and limites.video_duree_max_s is not None
            and media.duree_s is not None
            and media.duree_s > limites.video_duree_max_s
        ):
            refus.append(
                _refus(
                    REJ_MEDIA_DUREE, f"{chemin}.duree_s", f"{media.duree_s} s, {limites.video_duree_max_s} s au plus"
                )
            )
        if media.origine == modele.ORIGINE_GENERE_NON_COMPOSE:
            refus.append(
                _refus(
                    REJ_MEDIA_GENERE_NON_COMPOSE,
                    f"{chemin}.origine",
                    "un média produit par un modèle d'image sans composition déterministe ne se publie jamais "
                    "(décision r2 n°3 : texte, logo et mentions viennent d'un gabarit, contrôlés par OCR)",
                )
            )
        if media.origine == modele.ORIGINE_COMPOSEE and media.controle_ocr != "conforme":
            refus.append(
                _refus(
                    REJ_MEDIA_OCR,
                    f"{chemin}.controle_ocr",
                    "une composition déterministe exige un contrôle OCR conforme "
                    "(zéro erreur sur les informations critiques)",
                )
            )
        if media.origine == modele.ORIGINE_PHOTO and media.ia_generee:
            refus.append(
                _refus(
                    REJ_MEDIA_IA_INCOHERENTE, f"{chemin}.ia_generee", "une photo de chantier n'est pas générée par IA"
                )
            )
        if media.origine == modele.ORIGINE_GENERE_NON_COMPOSE and not media.ia_generee:
            refus.append(
                _refus(REJ_MEDIA_IA_INCOHERENTE, f"{chemin}.ia_generee", "un média généré porte ia_generee=true")
            )
        if media.moderation != "verifiee":
            refus.append(
                _refus(
                    REJ_MEDIA_MODERATION,
                    f"{chemin}.moderation",
                    f"modération {media.moderation} : visages et plaques floutés ou absents, et revue humaine faite, "
                    "sont exigés avant toute publication",
                )
            )
    return refus


def controler_divulgation(publication: modele.Publication, limites: LimitesReseau) -> list[dict[str, str]]:
    """La divulgation déclarée DOIT être celle que les médias imposent (calculée, jamais crue sur parole), et le réseau
    doit savoir la porter ; sinon on ne publie pas."""
    refus: list[dict[str, str]] = []
    exigee = modele.media_synthetique_realiste(publication)
    if publication.divulgation.media_synthetique_realiste != exigee:
        refus.append(
            _refus(
                REJ_DIVULGATION_INCOHERENTE,
                "$.divulgation.media_synthetique_realiste",
                f"les médias imposent {exigee} (média généré par IA et réaliste), la publication déclare "
                f"{publication.divulgation.media_synthetique_realiste}",
            )
        )
    if exigee and not limites.etiquette_ia:
        refus.append(
            _refus(
                REJ_DIVULGATION_IMPOSSIBLE,
                "$.divulgation",
                f"{limites.reseau} n'offre pas de champ de divulgation de contenu synthétique réaliste : publication "
                f"refusée",
            )
        )
    return refus


def controler_type(
    publication: modele.Publication, limites: LimitesReseau, politique: PolitiqueSas
) -> list[dict[str, str]]:
    refus: list[dict[str, str]] = []
    if publication.type_publication == modele.ORGANIQUE:
        if publication.budget is not None:
            refus.append(_refus(REJ_TYPE_INCOHERENT, "$.budget", "une publication organique n'a pas de budget"))
        return refus
    if not limites.annonce_payante:
        refus.append(
            _refus(
                REJ_ANNONCE_NON_SUPPORTEE,
                "$.type_publication",
                f"{limites.reseau} : annonce payante non prise en charge",
            )
        )
    budget = publication.budget
    if budget is None:
        refus.append(_refus(REJ_TYPE_INCOHERENT, "$.budget", "une annonce payante exige un budget"))
        return refus
    if budget.plafond_quotidien_cents > politique.plafond_budget_quotidien_cents:
        refus.append(
            _refus(
                REJ_BUDGET,
                "$.budget.plafond_quotidien_cents",
                f"{budget.plafond_quotidien_cents} cents par jour, "
                f"plafond dur de {politique.plafond_budget_quotidien_cents}",
            )
        )
    if budget.montant_cents > politique.plafond_budget_total_cents:
        refus.append(
            _refus(
                REJ_BUDGET,
                "$.budget.montant_cents",
                f"{budget.montant_cents} cents au total, plafond dur de {politique.plafond_budget_total_cents}",
            )
        )
    if budget.montant_cents > budget.plafond_quotidien_cents * budget.duree_jours:
        refus.append(
            _refus(
                REJ_BUDGET,
                "$.budget.montant_cents",
                "le montant dépasse le plafond quotidien multiplié par la durée : le budget ne tient pas dans ses "
                "propres bornes",
            )
        )
    return refus


def controler_options(publication: modele.Publication, adaptateur: DeclarationReseau) -> list[dict[str, str]]:
    return [_refus(REJ_OPTIONS, "$.options", probleme) for probleme in adaptateur.valider_options(publication.options)]


def quota_applicable(limites: LimitesReseau, politique: PolitiqueSas) -> int:
    plafonds = dict(politique.quota_24h)
    return min(limites.quota_24h, plafonds.get(limites.reseau, limites.quota_24h))


def quota_respecte(horaires: Iterable[datetime], candidat: datetime, quota: int) -> bool:
    """Vrai si, une fois `candidat` ajouté aux `horaires` déjà réservés ou publiés du compte, AUCUNE période de 24 h
    glissantes ne compte plus de `quota` publications. Le maximum d'une fenêtre glissante est atteint pour une
    fenêtre qui
    COMMENCE à une publication : on les essaie toutes."""
    tous = sorted([*horaires, candidat])
    for debut in tous:
        fin = debut + timedelta(hours=24)
        if sum(1 for t in tous if debut <= t < fin) > quota:
            return False
    return True


def controler_planification(
    publication: modele.Publication,
    limites: LimitesReseau,
    politique: PolitiqueSas,
    maintenant: datetime,
    horaires_du_compte: Sequence[datetime],
) -> list[dict[str, str]]:
    refus: list[dict[str, str]] = []
    prevu = modele.instant(publication.planifie_le)
    if prevu < maintenant + timedelta(seconds=politique.delai_minimal_s):
        refus.append(
            _refus(
                REJ_PASSE,
                "$.planifie_le",
                f"au moins {politique.delai_minimal_s} s après le moment présent "
                "(le temps d'une dernière vérification)",
            )
        )
    if prevu > maintenant + timedelta(days=politique.horizon_max_jours):
        refus.append(_refus(REJ_HORIZON, "$.planifie_le", f"{politique.horizon_max_jours} jours au plus"))
    if not politique.fenetre.contient(prevu):
        refus.append(
            _refus(
                REJ_HORS_FENETRE,
                "$.planifie_le",
                f"hors de la fenêtre de publication ({politique.fenetre.debut:%H:%M}–{politique.fenetre.fin:%H:%M}, "
                f"{politique.fenetre.fuseau})",
            )
        )
    quota = quota_applicable(limites, politique)
    if not quota_respecte(horaires_du_compte, prevu, quota):
        refus.append(
            _refus(
                REJ_QUOTA,
                "$.planifie_le",
                f"plus de {quota} publications sur 24 h glissantes pour ce compte {limites.reseau} : choisir une "
                f"autre heure",
            )
        )
    return refus


def controler_contenu(
    publication: modele.Publication,
    adaptateur: DeclarationReseau,
    politique: PolitiqueSas,
) -> list[dict[str, str]]:
    """Tout ce qui ne dépend pas de l'horloge : texte, médias, divulgation, type, options. L'ordre est fixe."""
    limites = adaptateur.LIMITES
    return [
        *controler_texte(publication, limites, politique),
        *controler_medias(publication, limites),
        *controler_divulgation(publication, limites),
        *controler_type(publication, limites, politique),
        *controler_options(publication, adaptateur),
    ]


def controler_tout(
    publication: modele.Publication,
    adaptateur: DeclarationReseau,
    politique: PolitiqueSas,
    maintenant: datetime,
    horaires_du_compte: Sequence[datetime],
) -> list[dict[str, str]]:
    return [
        *controler_contenu(publication, adaptateur, politique),
        *controler_planification(publication, adaptateur.LIMITES, politique, maintenant, horaires_du_compte),
    ]


def verifier_niveau(publication: modele.Publication, niveau_outil: int) -> list[dict[str, str]]:
    requis = niveau_requis(publication)
    if niveau_outil < requis:
        outil = (
            "m7_demander_annonce_payante (N4)"
            if requis == NIVEAU_ANNONCE_PAYANTE
            else "m7_demander_publication_sociale (N3)"
        )
        return [
            _refus(
                REJ_NIVEAU,
                "$.type_publication",
                f"cette publication exige N{requis}, l'outil appelé est N{niveau_outil} : utiliser {outil}",
            )
        ]
    if niveau_outil != requis:
        return [
            _refus(
                REJ_NIVEAU,
                "$.type_publication",
                f"cette publication relève de N{requis} : utiliser l'outil de ce niveau",
            )
        ]
    return []


def resume_adaptateur(adaptateur: DeclarationReseau) -> Mapping[str, Any]:
    limites = adaptateur.LIMITES
    return {
        "reseau": limites.reseau,
        "texte_max": limites.texte_max,
        "medias": [limites.medias_min, limites.medias_max],
        "quota_24h": limites.quota_24h,
        "a_verifier": limites.a_verifier,
        "source": limites.source,
    }
