"""Les réseaux sociaux du sas : limites déclarées par la CLASSE d'adaptateur, et le port que tout adaptateur respecte.

Décision d'architecte (feuille de route r2, « Réseaux/pub ») : connecteurs natifs OPSYS (GBP, Facebook, Instagram,
LinkedIn, YouTube, TikTok) derrière un sas d'approbation. Cette tranche livre le PORT et les LIMITES, jamais un appel
réseau : aucun adaptateur réel n'existe, aucune clé n'est lue, aucun module réseau n'est importé (un test le vérifie sur
la source). Les adaptateurs de test (`doubles.py`) héritent de ces limites.

Les limites sont DÉCLARÉES PAR LA CLASSE (`LIMITES`), et le sas les lit là, jamais dans une copie à lui : changer la
limite d'un adaptateur change ce que le sas accepte (un test le prouve en remplaçant la classe).

AVERTISSEMENT sur les chiffres : ils proviennent de la recherche R4 (§5.2, niveaux de preuve V/S/H) ou sont un plafond
INTERNE prudent là où aucune valeur officielle n'a été retenue. AUCUN n'a été revérifié contre la documentation
officielle
de la plateforme au moment d'écrire ce module : `a_verifier=True` partout, et `docs/architecture/M7-WORDPRESS-SOCIAL.md`
liste, par réseau, ce qu'il faut revérifier (niveau d'accès de l'application, quotas, formats, champs de divulgation)
avant d'écrire le premier adaptateur réel. Les conditions d'accès des API changent (R4 le note pour YouTube et
LinkedIn).

Module pur : aucune entrée-sortie, aucun import d'`opsys`.
"""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Callable, Mapping
from typing import Any, ClassVar, Protocol

GBP = "gbp"
FACEBOOK = "facebook"
INSTAGRAM = "instagram"
LINKEDIN = "linkedin"
YOUTUBE = "youtube"
TIKTOK = "tiktok"
RESEAUX = (GBP, FACEBOOK, INSTAGRAM, LINKEDIN, YOUTUBE, TIKTOK)

IMAGE = "image"
VIDEO = "video"


@dataclasses.dataclass(frozen=True)
class LimitesReseau:
    """Ce qu'un service accepte, tel que la classe d'adaptateur le déclare au sas.

    `texte_max` : caractères Unicode du corps (légende, description). `titre_max` : `None` si le réseau n'a pas de
    titre.
    `medias_min`/`medias_max` : nombre de médias. `melange_medias` : images et vidéo dans une même publication.
    `quota_24h` : publications par API par période mobile de 24 h et par compte. `etiquette_ia` : le service offre un
    champ de divulgation de contenu synthétique réaliste. `annonce_payante` : le réseau a une API publicitaire que ce
    sas sait encadrer. `options_requises` : choix explicites de l'approbateur, sans valeur par défaut (TikTok).
    """

    reseau: str
    texte_max: int
    titre_max: int | None
    titre_requis: bool
    hashtags_max: int | None
    medias_min: int
    medias_max: int
    melange_medias: bool
    formats_images: frozenset[str]
    formats_videos: frozenset[str]
    octets_max: int
    video_duree_max_s: int | None
    quota_24h: int
    etiquette_ia: bool
    annonce_payante: bool
    options_requises: tuple[str, ...]
    source: str
    a_verifier: bool = True


@dataclasses.dataclass(frozen=True)
class RequetePublication:
    """Ce que l'adaptateur reçoit : le contenu approuvé, jamais un jeton d'accès (l'adaptateur le demande au coffre)."""

    reseau: str
    compte: str
    texte: str
    titre: str | None
    medias: tuple[Mapping[str, Any], ...]
    cle_idempotence: str
    empreinte: str
    divulgation: Mapping[str, bool]
    type_publication: str
    budget: Mapping[str, int] | None
    options: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class ResultatPublication:
    id_externe: str
    url: str | None
    publie_le: str


class ErreurReseau(Exception):
    """Un échec du service. `transitoire` : un nouvel essai a un sens ; `incertain` : la requête est peut-être passée
    (délai dépassé après envoi) — avant tout nouvel essai, le sas demande `retrouver`, il ne republie jamais à
    l'aveugle."""

    def __init__(self, code: str, detail: str, *, transitoire: bool = False, incertain: bool = False) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail
        self.transitoire = transitoire
        self.incertain = incertain


FournisseurSecret = Callable[[], contextlib.AbstractContextManager[str]]


class DeclarationReseau:
    """Ce que le sas sait d'un réseau SANS le joindre : ses limites et la validation de ses options. Base commune des
    adaptateurs (réels, un jour) et des doubles de test : une classe d'adaptateur déclare ses `LIMITES` ici et
    hérite de la
    validation ; le sas ne lit les limites que sur CETTE classe."""

    LIMITES: ClassVar[LimitesReseau]
    CLIENT_AUDITE: ClassVar[bool] = False

    def valider_options(self, options: Mapping[str, Any]) -> list[str]:
        """Les problèmes des options propres au réseau (vide si elles conviennent)."""
        if self.LIMITES.reseau == TIKTOK:
            return valider_options_tiktok(options, client_audite=self.CLIENT_AUDITE)
        return valider_options_requises(self.LIMITES, options)


class AdaptateurReseau(Protocol):
    """Le port complet. Une classe qui le respecte déclare ses `LIMITES`, valide ses options, sait publier et retrouver
    une publication déjà passée. Le jeton d'accès lui est PASSÉ à chaque appel par l'exécuteur, qui l'a obtenu du coffre
    le temps de l'appel : l'adaptateur ne le garde pas, ne le journalise pas et ne le met dans aucun message
    d'erreur."""

    LIMITES: ClassVar[LimitesReseau]

    def valider_options(self, options: Mapping[str, Any]) -> list[str]:
        """Les problèmes des options propres au réseau (vide si elles conviennent)."""

    def publier(self, requete: RequetePublication, jeton_acces: str) -> ResultatPublication:
        """Publie ; lève `ErreurReseau` en cas d'échec."""

    def retrouver(self, requete: RequetePublication, depuis: str, jeton_acces: str) -> ResultatPublication | None:
        """Cherche, parmi les publications récentes du compte depuis `depuis` (AAAA-MM-JJTHH:MM:SSZ), celle qui porte
        EXACTEMENT ce contenu ; `None` si elle n'existe pas."""


_JPEG = frozenset({"jpeg"})
_IMAGES_COURANTES = frozenset({"jpeg", "png"})
_VIDEOS_COURANTES = frozenset({"mp4", "mov"})
_SOURCE_INTERNE = "plafond interne prudent (aucune valeur officielle retenue)"

LIMITES_GBP = LimitesReseau(
    reseau=GBP,
    texte_max=1500,
    titre_max=None,
    titre_requis=False,
    hashtags_max=None,
    medias_min=0,
    medias_max=1,
    melange_medias=False,
    formats_images=_IMAGES_COURANTES,
    formats_videos=frozenset(),
    octets_max=5 * 1024 * 1024,
    video_duree_max_s=None,
    quota_24h=3,
    etiquette_ia=False,
    annonce_payante=False,
    options_requises=(),
    source="R4 §3.4 / §5.2 (texte de mise à jour de la fiche) ; quota : " + _SOURCE_INTERNE,
)
LIMITES_FACEBOOK = LimitesReseau(
    reseau=FACEBOOK,
    texte_max=63206,
    titre_max=None,
    titre_requis=False,
    hashtags_max=None,
    medias_min=0,
    medias_max=10,
    melange_medias=False,
    formats_images=frozenset({"jpeg", "png", "gif", "webp"}),
    formats_videos=_VIDEOS_COURANTES,
    octets_max=10 * 1024 * 1024,
    video_duree_max_s=240 * 60,
    quota_24h=25,
    etiquette_ia=True,
    annonce_payante=True,
    options_requises=(),
    source="R4 §5.2 (Pages Facebook, étiquette « AI info ») ; quota : " + _SOURCE_INTERNE,
)
LIMITES_INSTAGRAM = LimitesReseau(
    reseau=INSTAGRAM,
    texte_max=2200,
    titre_max=None,
    titre_requis=False,
    hashtags_max=30,
    medias_min=1,
    medias_max=10,
    melange_medias=True,
    formats_images=_JPEG,
    formats_videos=_VIDEOS_COURANTES,
    octets_max=8 * 1024 * 1024,
    video_duree_max_s=15 * 60,
    quota_24h=100,
    etiquette_ia=True,
    annonce_payante=True,
    options_requises=(),
    source="R4 §5.2 (V : 100 publications par API par 24 h glissantes ; un carrousel compte pour 1)",
)
LIMITES_LINKEDIN = LimitesReseau(
    reseau=LINKEDIN,
    texte_max=3000,
    titre_max=None,
    titre_requis=False,
    hashtags_max=None,
    medias_min=0,
    medias_max=9,
    melange_medias=False,
    formats_images=frozenset({"jpeg", "png", "gif"}),
    formats_videos=frozenset({"mp4"}),
    octets_max=10 * 1024 * 1024,
    video_duree_max_s=10 * 60,
    quota_24h=25,
    etiquette_ia=False,
    annonce_payante=True,
    options_requises=(),
    source="R4 §5.2 (Community Management API, S) ; quota : " + _SOURCE_INTERNE,
)
LIMITES_YOUTUBE = LimitesReseau(
    reseau=YOUTUBE,
    texte_max=5000,
    titre_max=100,
    titre_requis=True,
    hashtags_max=15,
    medias_min=1,
    medias_max=1,
    melange_medias=False,
    formats_images=frozenset(),
    formats_videos=_VIDEOS_COURANTES,
    octets_max=256 * 1024 * 1024,
    video_duree_max_s=15 * 60,
    quota_24h=100,
    etiquette_ia=True,
    annonce_payante=False,
    options_requises=(),
    source="R4 §5.2 (V : videos.insert, 100 appels par jour ; champ containsSyntheticMedia)",
)
LIMITES_TIKTOK = LimitesReseau(
    reseau=TIKTOK,
    texte_max=2200,
    titre_max=None,
    titre_requis=False,
    hashtags_max=None,
    medias_min=1,
    medias_max=1,
    melange_medias=False,
    formats_images=frozenset(),
    formats_videos=frozenset({"mp4"}),
    octets_max=256 * 1024 * 1024,
    video_duree_max_s=10 * 60,
    quota_24h=15,
    etiquette_ia=True,
    annonce_payante=True,
    options_requises=("confidentialite", "commentaires", "duo", "stitch"),
    source="R4 §5.2 (V : environ 15 publications par jour par compte ; interface sans valeur par défaut)",
)

LIMITES_PAR_RESEAU: Mapping[str, LimitesReseau] = {
    limites.reseau: limites
    for limites in (
        LIMITES_GBP,
        LIMITES_FACEBOOK,
        LIMITES_INSTAGRAM,
        LIMITES_LINKEDIN,
        LIMITES_YOUTUBE,
        LIMITES_TIKTOK,
    )
}

CONFIDENTIALITES_TIKTOK = frozenset({"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"})


def valider_options_requises(limites: LimitesReseau, options: Mapping[str, Any]) -> list[str]:
    """Contrôle commun : chaque option requise est présente (jamais de valeur par défaut) et aucune autre n'est admise.
    """
    problemes = [
        f"option requise absente : {nom} (aucune valeur par défaut)"
        for nom in limites.options_requises
        if nom not in options
    ]
    problemes += [f"option inconnue : {nom}" for nom in sorted(set(options) - set(limites.options_requises))]
    return problemes


def valider_options_tiktok(options: Mapping[str, Any], *, client_audite: bool) -> list[str]:
    """TikTok (R4 §5.2, V) : la confidentialité est choisie à la main parmi les valeurs du service ; un client non
    audité
    ne publie qu'en privé (`SELF_ONLY`) ; les trois interactions sont des booléens explicites."""
    problemes = valider_options_requises(LIMITES_TIKTOK, options)
    confidentialite = options.get("confidentialite")
    if "confidentialite" in options and confidentialite not in CONFIDENTIALITES_TIKTOK:
        problemes.append(f"confidentialite : une de {sorted(CONFIDENTIALITES_TIKTOK)} attendue")
    elif confidentialite is not None and not client_audite and confidentialite != "SELF_ONLY":
        problemes.append("application non auditée : seule la confidentialité SELF_ONLY est permise")
    problemes += [
        f"{nom} : booléen explicite attendu"
        for nom in ("commentaires", "duo", "stitch")
        if nom in options and type(options[nom]) is not bool
    ]
    return problemes


class DeclarationGBP(DeclarationReseau):
    LIMITES = LIMITES_GBP


class DeclarationFacebook(DeclarationReseau):
    LIMITES = LIMITES_FACEBOOK


class DeclarationInstagram(DeclarationReseau):
    LIMITES = LIMITES_INSTAGRAM


class DeclarationLinkedIn(DeclarationReseau):
    LIMITES = LIMITES_LINKEDIN


class DeclarationYouTube(DeclarationReseau):
    LIMITES = LIMITES_YOUTUBE


class DeclarationTikTok(DeclarationReseau):
    LIMITES = LIMITES_TIKTOK


DECLARATIONS: Mapping[str, type[DeclarationReseau]] = {
    classe.LIMITES.reseau: classe
    for classe in (
        DeclarationGBP,
        DeclarationFacebook,
        DeclarationInstagram,
        DeclarationLinkedIn,
        DeclarationYouTube,
        DeclarationTikTok,
    )
}


def declarations_par_defaut() -> dict[str, DeclarationReseau]:
    """Une instance de déclaration par réseau : ce qui valide un contenu quand aucun adaptateur n'est branché."""
    return {reseau: classe() for reseau, classe in DECLARATIONS.items()}
