"""Les cinq variantes d'un chantier terminé (PLAN T4.17, DEFINITION-PRODUIT §7 M7.3 « variantes par plateforme »).

Un chantier donne un contenu par plateforme : Facebook, Instagram, fiche Google, script de vidéo courte, et
une demande de témoignage au client. Chaque variante dit :
  - où elle va (`public` : les quatre premières sont publiques, la demande de témoignage est un message privé) ;
  - son lien de suivi (`source_utm`, `medium_utm`, valeurs du contrat gelé `utm-convention.v1.yaml` : la vidéo
    courte prend `tiktok`, seule source vidéo de l'énuméré ; la demande de témoignage n'a pas de lien) ;
  - son plafond de longueur : un plafond INTERNE, prudent, sous les limites connues des plateformes (qui
    changent, à revalider) — jamais présenté comme une règle de la plateforme ;
  - ses instructions de publication MANUELLE (M7.2 « paquet manuel ») : M7 ne publie jamais, l'API officielle
    de chaque plateforme est une porte fermée (PLAN §10), le paquet manuel est le chemin principal.

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

import dataclasses

MEDIA_REQUIS = "requis"
MEDIA_CONSEILLE = "conseille"
MEDIA_AUCUN = "aucun"

# Étape commune à toute publication manuelle : ce que M7 ne peut pas garantir (docstring de
# `moderation.floutage`) — l'absence de détection n'est pas une preuve d'absence de visage.
VERIFICATION_AVANT_PUBLICATION = (
    "Avant de publier : vérifier à l'œil qu'aucun visage, plaque d'immatriculation, numéro civique ni nom de "
    "client n'est visible sur les médias ou dans le texte."
)


@dataclasses.dataclass(frozen=True)
class Plateforme:
    code: str
    libelle: str
    public: bool
    source_utm: str | None
    medium_utm: str | None
    longueur_max: int
    media: str
    lien_dans_le_texte: bool
    instructions: tuple[str, ...]


PLATEFORMES: tuple[Plateforme, ...] = (
    Plateforme(
        code="facebook", libelle="Publication Facebook", public=True,
        source_utm="facebook", medium_utm="social", longueur_max=1500, media=MEDIA_CONSEILLE,
        lien_dans_le_texte=True,
        instructions=(
            "Ouvrir la page Facebook de l'entreprise et créer une publication.",
            "Coller le texte, puis ajouter les photos une fois vérifiées.",
            "Publier à l'heure suggérée, ou à l'heure de ton choix.",
        ),
    ),
    Plateforme(
        code="instagram", libelle="Publication Instagram", public=True,
        source_utm="instagram", medium_utm="social", longueur_max=2000, media=MEDIA_REQUIS,
        lien_dans_le_texte=False,
        instructions=(
            "Ouvrir le compte Instagram de l'entreprise et créer une publication : une photo est obligatoire.",
            "Coller le texte et les mots-clics dans la légende.",
            "Le lien de suivi n'est pas cliquable dans une légende : le mettre dans la bio ou dans une story.",
        ),
    ),
    Plateforme(
        code="fiche_google", libelle="Mise à jour de la fiche Google", public=True,
        source_utm="gbp", medium_utm="social", longueur_max=1400, media=MEDIA_CONSEILLE,
        lien_dans_le_texte=False,
        instructions=(
            "Ouvrir le profil d'entreprise Google de l'entreprise et ajouter une mise à jour.",
            "Coller le texte, ajouter une photo vérifiée.",
            "Choisir le bouton « En savoir plus » et y mettre le lien de suivi.",
        ),
    ),
    Plateforme(
        code="video_courte", libelle="Script de vidéo courte", public=True,
        source_utm="tiktok", medium_utm="social", longueur_max=1200, media=MEDIA_CONSEILLE,
        lien_dans_le_texte=False,
        instructions=(
            "Filmer ou monter la vidéo en suivant le script, avec les photos vérifiées comme plans.",
            "Publier la vidéo sur la plateforme de ton choix ; mettre le lien de suivi dans la description "
            "ou dans la bio.",
        ),
    ),
    Plateforme(
        code="demande_temoignage", libelle="Demande de témoignage au client", public=False,
        source_utm=None, medium_utm=None, longueur_max=900, media=MEDIA_AUCUN,
        lien_dans_le_texte=False,
        instructions=(
            "Envoyer ce message toi-même au client, par le canal qu'il a choisi, seulement s'il a consenti à "
            "être contacté (voir « contact_client » dans ce paquet).",
            "Ne rien publier du témoignage reçu sans l'accord écrit du client.",
        ),
    ),
)

CODES_PLATEFORMES: tuple[str, ...] = tuple(p.code for p in PLATEFORMES)
_PAR_CODE: dict[str, Plateforme] = {p.code: p for p in PLATEFORMES}


def plateforme(code: str) -> Plateforme:
    """La plateforme de ce code ; `KeyError` (refus métier pour l'outil) si le code n'existe pas."""
    try:
        return _PAR_CODE[code]
    except KeyError:
        raise KeyError(f"plateforme inconnue : {code!r} (attendu : {', '.join(CODES_PLATEFORMES)})") from None
