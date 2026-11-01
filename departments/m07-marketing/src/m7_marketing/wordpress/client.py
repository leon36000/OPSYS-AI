"""Client signataire du plugin « OPSYS Connect » : prépare des requêtes signées, les remet à un PORT de transport,
valide la
réponse. Il ne fait AUCUN appel réseau : le transport (HTTP) est injecté, et dans cette tranche il n'existe que des
doubles
de test. Le plugin n'a jamais été exécuté dans un vrai WordPress.

Règles (mêmes que le plugin, appliquées d'avance côté OPSYS) :
  - une requête sans route connue, avec paramètre de requête, ou sur une autre origine que le site enregistré ne
  part pas ;
  - le secret partagé sort du coffre le temps de SIGNER (fournisseur injecté), n'est ni gardé ni journalisé ni cité
  dans une
    exception ; les en-têtes de la requête ne contiennent que la signature ;
  - un brouillon n'est jamais demandé publié (`draft` ou `pending` seulement, vérifié avant de signer) ;
  - la publication n'existe que par `publier(ApprobationVerifiee)` : le jeton est émis depuis une approbation humaine
    consignée (`flux.approbation_verifiee`), signé avec la clé d'approbation dérivée, et lié à l'empreinte approuvée ;
  - la réponse est relue strictement : forme, types, statut rendu. Un site qui répondrait « publié » à une demande
  de brouillon
    est signalé (`REJ-WP-STATUT-INATTENDU`), jamais cru.

Les refus du plugin (`opsys_…`) deviennent `REJ-WP-…` ; un code inconnu devient `REJ-WP-REPONSE-INATTENDUE`.
"""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from . import jeton, signature
from .flux import ApprobationVerifiee
from .sites import SiteWordPress

NAMESPACE = "/opsys-connect/v1"
CORPS_MAX = 1_000_000
MEDIA_MAX = 8 * 1024 * 1024
CORPS_MEDIA_MAX = 12_000_000  # 8 Mio en base64, avec la marge de l'enveloppe JSON
REPONSE_MAX = 1_000_000
DELAI_S = 20.0
STATUTS_BROUILLON = ("draft", "pending")
_SHA = re.compile(r"[0-9a-f]{64}")
_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")

REJ_ROUTE = "REJ-WP-ROUTE-INVALIDE"
REJ_STATUT_INTERDIT = "REJ-WP-STATUT-INTERDIT"
REJ_STATUT_INATTENDU = "REJ-WP-STATUT-INATTENDU"
REJ_TRANSPORT = "REJ-WP-TRANSPORT"
REJ_REPONSE = "REJ-WP-REPONSE-INATTENDUE"
REJ_EMPREINTE_REPONSE = "REJ-WP-EMPREINTE-REPONSE"
REJ_MEDIA = "REJ-WP-MEDIA-INVALIDE"
REJ_CORPS = "REJ-WP-CORPS-TROP-GRAND"
CODES_PLUGIN = frozenset(
    {
        "opsys_https_requis",
        "opsys_non_configure",
        "opsys_en_tete_manquant",
        "opsys_horodatage_invalide",
        "opsys_nonce_invalide",
        "opsys_signature_malformee",
        "opsys_horodatage_hors_fenetre",
        "opsys_signature_invalide",
        "opsys_rejeu",
        "opsys_cle_inconnue",
        "opsys_agent_dangereux",
        "opsys_agent_absent",
        "opsys_query_interdite",
        "opsys_corps_trop_grand",
        "opsys_capacite_insuffisante",
        "opsys_champ_inconnu",
        "opsys_champ_invalide",
        "opsys_type_non_permis",
        "opsys_statut_interdit",
        "opsys_publication_sans_jeton",
        "opsys_etat_non_modifiable",
        "opsys_non_gere",
        "opsys_cle_idempotence_reutilisee",
        "opsys_creation_en_cours",
        "opsys_empreinte_obsolete",
        "opsys_jeton_malforme",
        "opsys_jeton_signature_invalide",
        "opsys_jeton_champ_invalide",
        "opsys_jeton_expire",
        "opsys_jeton_duree_excessive",
        "opsys_jeton_site_different",
        "opsys_jeton_article_different",
        "opsys_jeton_empreinte_differente",
        "opsys_jeton_action_non_permise",
        "opsys_jeton_planification_invalide",
        "opsys_jeton_deja_utilise",
        "opsys_publication_desactivee",
        "opsys_media_invalide",
        "opsys_media_type_refuse",
        "opsys_media_trop_gros",
        "opsys_media_contenu_actif",
        "opsys_media_empreinte_differente",
        "opsys_erreur_interne",
    }
)


@dataclasses.dataclass(frozen=True)
class RequeteHTTP:
    methode: str
    url: str
    en_tetes: Mapping[str, str]
    corps: bytes
    delai_s: float


@dataclasses.dataclass(frozen=True)
class ReponseHTTP:
    statut: int
    corps: bytes


class Transport(Protocol):
    def envoyer(self, requete: RequeteHTTP) -> ReponseHTTP:
        """Remet la requête au site et rend sa réponse ; lève une exception en cas de panne de transport."""


FournisseurSecret = Callable[[], contextlib.AbstractContextManager[str]]


def code_refus(code_plugin: str) -> str:
    """`opsys_jeton_expire` -> `REJ-WP-JETON-EXPIRE` ; un code que le client ne connaît pas n'est jamais repris tel
    quel.
    """
    if code_plugin not in CODES_PLUGIN:
        return REJ_REPONSE
    return "REJ-WP-" + code_plugin.removeprefix("opsys_").replace("_", "-").upper()


def _refus(code: str, detail: str, http: int | None = None) -> dict[str, Any]:
    resultat: dict[str, Any] = {"accepte": False, "refus": [{"code": code, "chemin": "$", "detail": detail}]}
    if http is not None:
        resultat["http"] = http
    return resultat


def _forme(reponse: Mapping[str, Any], champs: Mapping[str, Any]) -> str | None:
    """None si `reponse` a exactement les champs de `champs` avec leurs types (ou prédicats) ; sinon le détail."""
    if set(reponse) != set(champs):
        return f"champs {sorted(reponse)} au lieu de {sorted(champs)}"
    for nom, attendu in champs.items():
        valeur = reponse[nom]
        bon = attendu(valeur) if callable(attendu) and not isinstance(attendu, type) else type(valeur) is attendu
        if not bon:
            return f"champ {nom} invalide"
    return None


def _sha(v: Any) -> bool:
    return isinstance(v, str) and _SHA.fullmatch(v) is not None


def _instant(v: Any) -> bool:
    return isinstance(v, str) and _INSTANT.fullmatch(v) is not None


def _entier_positif(v: Any) -> bool:
    return type(v) is int and v > 0


def _texte_ou_nul(v: Any) -> bool:
    return v is None or isinstance(v, str)


FORMES: Mapping[str, Mapping[str, Any]] = {
    "sante": {
        "schema": lambda v: v == "opsys-connect/v1",
        "plugin_version": str,
        "wp_version": str,
        "php_version": str,
        "site_id": _texte_ou_nul,
        "publication_activee": bool,
        "agent_sur": bool,
        "https": bool,
        "heure_serveur": _entier_positif,
    },
    "types": {"types": list},
    "brouillon_cree": {
        "post_id": _entier_positif,
        "type": str,
        "statut": lambda v: v in STATUTS_BROUILLON,
        "empreinte": _sha,
        "modifie_gmt": _instant,
        "deja_cree": bool,
        "lien_modification": str,
    },
    "brouillon_maj": {
        "post_id": _entier_positif,
        "type": str,
        "statut": lambda v: v in STATUTS_BROUILLON,
        "empreinte": _sha,
        "modifie_gmt": _instant,
    },
    "etat": {
        "post_id": _entier_positif,
        "type": str,
        "statut": str,
        "empreinte": _sha,
        "empreinte_publiee": lambda v: v is None or _sha(v),
        "modifie_gmt": _instant,
        "gere": bool,
        "lien_public": _texte_ou_nul,
    },
    "media": {
        "media_id": _entier_positif,
        "sha256": _sha,
        "mime": str,
        "largeur": _entier_positif,
        "hauteur": _entier_positif,
        "deja_cree": bool,
    },
    "publication": {
        "post_id": _entier_positif,
        "statut": lambda v: v in ("publish", "future"),
        "empreinte": _sha,
        "publie_le_gmt": _instant,
        "lien_public": _texte_ou_nul,
    },
}


class ClientWordPress:
    def __init__(
        self,
        site: SiteWordPress,
        fournisseur_secret: FournisseurSecret,
        transport: Transport,
        horloge: Callable[[], int],
        generer_nonce: Callable[[], str],
    ) -> None:
        self._site = site
        self._fournisseur = fournisseur_secret
        self._transport = transport
        self._horloge = horloge
        self._nonce = generer_nonce

    # -- bas niveau --------------------------------------------------------------------------------------------
    def _appeler(
        self,
        methode: str,
        route: str,
        forme: str,
        charge: Mapping[str, Any] | None = None,
        *,
        charge_depuis_secret: Callable[[str], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not route.startswith(NAMESPACE + "/") or "?" in route or "#" in route or ".." in route:
            return _refus(REJ_ROUTE, "route hors de l'espace opsys-connect/v1 ou avec paramètre de requête")
        try:
            with self._fournisseur() as secret:
                brut = charge_depuis_secret(secret) if charge_depuis_secret is not None else charge
                corps = (
                    b""
                    if brut is None
                    else json.dumps(
                        brut,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                )
                if len(corps) > (CORPS_MEDIA_MAX if forme == "media" else CORPS_MAX):
                    return _refus(REJ_CORPS, "corps trop grand")
                en_tetes = signature.en_tetes_signes(
                    secret,
                    self._site.cle_id,
                    methode,
                    route,
                    self._horloge(),
                    self._nonce(),
                    corps,
                )
        except signature.SecretInvalide as exc:
            return _refus(signature.REJ_SECRET_COURT, str(exc))
        except ValueError as exc:  # requête ou jeton mal formé : refusé d'avance, rien n'est envoyé
            return _refus("REJ-WP-REQUETE-INVALIDE", str(exc)[:200])
        requete = RequeteHTTP(
            methode=methode.upper(),
            url=self._site.base_url + "/wp-json" + route,
            en_tetes={**en_tetes, "Content-Type": "application/json; charset=UTF-8", "Accept": "application/json"},
            corps=corps,
            delai_s=DELAI_S,
        )
        try:
            reponse = self._transport.envoyer(requete)
        except Exception as exc:  # noqa: BLE001 — le transport est de l'extérieur : seul le NOM de l'exception est repris
            return _refus(REJ_TRANSPORT, f"échec de transport ({type(exc).__name__})")
        return self._lire(reponse, forme)

    def _lire(self, reponse: ReponseHTTP, forme: str) -> dict[str, Any]:
        if len(reponse.corps) > REPONSE_MAX:
            return _refus(REJ_REPONSE, "réponse trop grande", reponse.statut)
        try:
            donnees = json.loads(reponse.corps.decode("utf-8")) if reponse.corps else None
        except (UnicodeDecodeError, ValueError):
            return _refus(REJ_REPONSE, "réponse illisible (JSON attendu)", reponse.statut)
        if not isinstance(donnees, dict):
            return _refus(REJ_REPONSE, "objet JSON attendu", reponse.statut)
        if not 200 <= reponse.statut < 300:
            code = donnees.get("code")
            return _refus(
                code_refus(code) if isinstance(code, str) else REJ_REPONSE,
                str(donnees.get("message", "refus du plugin"))[:300],
                reponse.statut,
            )
        probleme = _forme(donnees, FORMES[forme])
        if probleme is not None:
            return _refus(REJ_REPONSE, probleme, reponse.statut)
        return {"accepte": True, "donnees": donnees, "http": reponse.statut}

    # -- opérations --------------------------------------------------------------------------------------------
    def sante(self) -> dict[str, Any]:
        return self._appeler("GET", f"{NAMESPACE}/health", "sante")

    def types(self) -> dict[str, Any]:
        return self._appeler("GET", f"{NAMESPACE}/types", "types")

    def creer_brouillon(
        self,
        type_contenu: str,
        titre: str,
        contenu: str,
        extrait: str,
        slug: str,
        statut: str,
        cle_idempotence: str,
    ) -> dict[str, Any]:
        if statut not in STATUTS_BROUILLON:
            return _refus(REJ_STATUT_INTERDIT, f"{statut!r} : un brouillon est créé draft ou pending, jamais publié")
        resultat = self._appeler(
            "POST",
            f"{NAMESPACE}/drafts",
            "brouillon_cree",
            {
                "type": type_contenu,
                "titre": titre,
                "contenu": contenu,
                "extrait": extrait,
                "slug": slug,
                "statut": statut,
                "cle_idempotence": cle_idempotence,
            },
        )
        return resultat

    def maj_brouillon(
        self,
        post_id: int,
        champs: Mapping[str, str],
        empreinte_attendue: str | None = None,
    ) -> dict[str, Any]:
        charge = dict(champs)
        if charge.get("statut", "draft") not in STATUTS_BROUILLON:
            return _refus(REJ_STATUT_INTERDIT, "un brouillon reste draft ou pending")
        if empreinte_attendue is not None:
            charge["empreinte_attendue"] = empreinte_attendue
        return self._appeler("PUT", f"{NAMESPACE}/drafts/{int(post_id)}", "brouillon_maj", charge)

    def televerser_media(self, nom_fichier: str, octets: bytes, alt: str) -> dict[str, Any]:
        if not octets or len(octets) > MEDIA_MAX:
            return _refus(REJ_MEDIA, f"1 à {MEDIA_MAX} octets exigés")
        if not alt.strip():
            return _refus(REJ_MEDIA, "texte alternatif exigé")
        return self._appeler(
            "POST",
            f"{NAMESPACE}/media",
            "media",
            {
                "nom_fichier": nom_fichier,
                "contenu_base64": base64.b64encode(octets).decode("ascii"),
                "sha256": hashlib.sha256(octets).hexdigest(),
                "alt": alt,
            },
        )

    def etat(self, post_id: int) -> dict[str, Any]:
        return self._appeler("GET", f"{NAMESPACE}/posts/{int(post_id)}/state", "etat")

    def publier(self, approbation: ApprobationVerifiee) -> dict[str, Any]:
        """Publie (ou planifie) l'article approuvé, avec un jeton émis ICI à partir de l'approbation consignée. Sans
        `ApprobationVerifiee`, il n'existe aucun moyen de demander une publication."""
        if not isinstance(approbation, ApprobationVerifiee) or approbation.site_id != self._site.site_id:
            return _refus("REJ-WP-APPROBATION-INVALIDE", "approbation absente ou d'un autre site")

        def charge(secret: str) -> Mapping[str, Any]:
            return {
                "approval_token": jeton.emettre(
                    secret,
                    {
                        "v": 1,
                        "approval_id": approbation.approval_id,
                        "site_id": approbation.site_id,
                        "action": approbation.action,
                        "post_id": approbation.post_id,
                        "content_sha256": approbation.empreinte,
                        "iat": approbation.emis_le,
                        "exp": approbation.expire_le,
                        "publish_at": approbation.publish_at,
                        "approved_by": approbation.approuve_par,
                    },
                )
            }

        resultat = self._appeler(
            "POST",
            f"{NAMESPACE}/posts/{approbation.post_id}/publish",
            "publication",
            charge_depuis_secret=charge,
        )
        if resultat["accepte"] and resultat["donnees"]["empreinte"] != approbation.empreinte:
            return _refus(
                REJ_EMPREINTE_REPONSE,
                "le site a publié un contenu d'une autre empreinte que celle qui a été approuvée : vérifier le site",
            )
        return resultat
