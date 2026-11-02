"""Configuration des rôles de modèles et de la passerelle : lecture, validation et UNE fonction d'écriture.

**Toute écriture de la configuration des modèles passe par `appliquer`** (une seule porte : le registre de « réglages de
direction » d'une autre branche s'y branchera plus tard sans toucher au reste). Elle :
- exige une personne active `nathan_owner`/`admin` relue en base ;
- exige le niveau d'approbation de l'opération (`NIVEAU_REQUIS`) : changer le fournisseur d'un rôle, ses replis, la
  passerelle, activer ou rétablir = **N3** (confirmation explicite) ; plafonds et coûts = N2 ; désactiver le
  raisonnement = N2 ;
- valide TOUT avant d'écrire (fournisseur actif et conforme à la politique de licence du registre, capacité compatible,
  replis, isolation du raisonnement, plafonds, URL, noms de secrets du coffre) ;
- écrit l'état et son historique append-only dans la même transaction (retour arrière), sans jamais une valeur de
  secret : seulement des NOMS du coffre. Un historique qui contiendrait une valeur active ou une forme de clé est
  refusé (`REJ-MODELES-SECRET-DETECTE`).

Un rôle sans ligne est INERTE : aucun appel, aucune valeur par défaut (fail-closed).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import ipaddress
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Connection, delete, insert, select, update

from .. import etat
from ..fournisseurs import registre
from ..fournisseurs.modele import Fournisseur
from ..fournisseurs.politique import evaluer
from ..passerelle import _CLE_ENV_FOURNISSEUR
from ..secrets_coffre import masquage
from ..stockage.schema import (
    COFFRE_SECRETS,
    FOURNISSEURS_CONFIGURATIONS,
    MODELES_HISTORIQUE,
    MODELES_REGLAGES,
    MODELES_ROLES,
    MODELES_USAGE,
)
from . import codes, economie
from . import roles as lex
from .codes import ModelesErreur

# -- niveaux d'approbation ---------------------------------------------------------------------------------------
OP_PASSERELLE_CONFIGURER = "passerelle.configurer"
OP_PASSERELLE_RETIRER = "passerelle.retirer"
OP_ROLE_AFFECTER = "role.affecter"
OP_ROLE_RETIRER = "role.retirer"
OP_ROLE_REPLIS = "role.replis"
OP_ROLE_PLAFONDS = "role.plafonds"
OP_ROLE_COUTS = "role.couts"
OP_RAISONNEMENT_ACTIVER = "raisonnement.activer"
OP_RAISONNEMENT_DESACTIVER = "raisonnement.desactiver"
OP_REVENIR = "revenir"

NIVEAU_REQUIS: dict[str, str] = {
    OP_PASSERELLE_CONFIGURER: "N3",
    OP_PASSERELLE_RETIRER: "N3",
    OP_ROLE_AFFECTER: "N3",
    OP_ROLE_RETIRER: "N3",
    OP_ROLE_REPLIS: "N3",
    OP_ROLE_PLAFONDS: "N2",
    OP_ROLE_COUTS: "N2",
    OP_RAISONNEMENT_ACTIVER: "N3",
    OP_RAISONNEMENT_DESACTIVER: "N2",
    OP_REVENIR: "N3",
}
_RANG = {"N0": 0, "N1": 1, "N2": 2, "N3": 3, "N4": 4, "N5": 5}

MODES_PASSERELLE = ("integree", "existante")
REPLIS_MAX = 4
_MODELE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$")
_NOM_SECRET = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_AMONT_FOURNISSEUR = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MOTIF = re.compile(r"^[^\x00-\x1f\x7f]{10,300}$")
_JOUR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def instant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def aujourd_hui() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def _json(valeur: Any) -> str:
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def exiger_admin(cnx: Connection, acteur: Any) -> None:
    try:
        registre._admin(cnx, acteur)  # noqa: SLF001 — même règle que le registre et le coffre : relue en base
    except registre.RegistreErreur as exc:
        raise ModelesErreur(codes.ADMIN_REQUIS, exc.detail, exc.statut_http) from None


def _exiger_niveau(operation: str, confirme: Any) -> None:
    requis = NIVEAU_REQUIS[operation]
    if _RANG[requis] > _RANG.get(confirme, -1) and _RANG[requis] >= _RANG["N3"]:
        raise ModelesErreur(
            codes.CONFIRMATION_REQUISE,
            f"{operation} est un geste {requis} : confirmation explicite du propriétaire requise",
            403,
        )


# -- réglages ----------------------------------------------------------------------------------------------------
def lire_reglage(cnx: Connection, cle: str) -> tuple[dict[str, Any] | None, int]:
    ligne = cnx.execute(select(MODELES_REGLAGES).where(MODELES_REGLAGES.c.cle == cle)).mappings().first()
    if ligne is None:
        return None, 0
    return json.loads(ligne["valeur"]), ligne["revision"]


def _ecrire_reglage(cnx: Connection, cle: str, valeur: Mapping[str, Any] | None, acteur: str) -> int:
    ligne = cnx.execute(select(MODELES_REGLAGES.c.revision).where(MODELES_REGLAGES.c.cle == cle)).first()
    if valeur is None:
        if ligne is not None:
            cnx.execute(delete(MODELES_REGLAGES).where(MODELES_REGLAGES.c.cle == cle))
        return 0
    if ligne is None:
        cnx.execute(
            insert(MODELES_REGLAGES).values(
                cle=cle, valeur=_json(valeur), revision=1, modifie_le=instant(), modifie_par=acteur
            )
        )
        return 1
    cnx.execute(
        update(MODELES_REGLAGES)
        .where(MODELES_REGLAGES.c.cle == cle)
        .values(valeur=_json(valeur), revision=ligne[0] + 1, modifie_le=instant(), modifie_par=acteur)
    )
    return ligne[0] + 1


def passerelle(cnx: Connection) -> dict[str, Any] | None:
    return lire_reglage(cnx, "passerelle")[0]


def raisonnement_actif(cnx: Connection) -> bool:
    valeur, _ = lire_reglage(cnx, "raisonnement")
    return bool(valeur and valeur.get("actif") is True)


# -- rôles : lecture ---------------------------------------------------------------------------------------------
def _ligne_role(cnx: Connection, role: str) -> dict[str, Any] | None:
    ligne = cnx.execute(select(MODELES_ROLES).where(MODELES_ROLES.c.role == role)).mappings().first()
    if ligne is None:
        return None
    donnees = dict(ligne)
    donnees["replis"] = json.loads(donnees["replis"])
    donnees["amont"] = json.loads(donnees["amont"]) if donnees["amont"] else None
    donnees["mesures"] = json.loads(donnees["mesures"]) if donnees["mesures"] else None
    return donnees


def ligne_role(cnx: Connection, role: str) -> dict[str, Any] | None:
    return _ligne_role(cnx, lex.verifier_role(role))


def toutes_les_lignes(cnx: Connection) -> dict[str, dict[str, Any]]:
    return {r: ligne for r in lex.ROLES if (ligne := _ligne_role(cnx, r)) is not None}


_CHAMPS_INSTANTANE = (
    "fournisseur_id",
    "modele_appel",
    "replis",
    "amont",
    "plafond_jetons_jour",
    "budget_usd_mois",
    "cout_entree_par_million",
    "cout_sortie_par_million",
    "cout_source",
)


def _instantane_role(ligne: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if ligne is None else {c: ligne.get(c) for c in _CHAMPS_INSTANTANE}


# -- validations ---------------------------------------------------------------------------------------------------
def _decimal_positif(valeur: Any, champ: str, *, maximum: Decimal, strict: bool) -> str | None:
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, bool) or not isinstance(valeur, (str, int)):
        raise ModelesErreur(codes.DECLARATION_INVALIDE, f"{champ} : nombre décimal en chaîne attendu", 422)
    try:
        montant = Decimal(str(valeur))
    except InvalidOperation:
        raise ModelesErreur(codes.DECLARATION_INVALIDE, f"{champ} : nombre décimal invalide", 422) from None
    if (
        not montant.is_finite()
        or montant > maximum
        or montant < 0
        or (strict and montant == 0)
        or len(str(valeur)) > 24
    ):
        raise ModelesErreur(codes.DECLARATION_INVALIDE, f"{champ} hors limites", 422)
    return format(montant.normalize(), "f")


def _plafond_jetons(valeur: Any) -> int | None:
    if valeur is None or valeur == "":
        return None
    if type(valeur) is not int or not 1 <= valeur <= 10**12:
        raise ModelesErreur(codes.DECLARATION_INVALIDE, "plafond_jetons_jour : entier de 1 à 10^12", 422)
    return valeur


def _modele(valeur: Any, champ: str = "modele_appel") -> str:
    if not isinstance(valeur, str) or not _MODELE.fullmatch(valeur):
        raise ModelesErreur(
            codes.DECLARATION_INVALIDE,
            f"{champ} : nom de modèle ou d'alias invalide (lettres, chiffres, . _ : / @ + -)",
            422,
        )
    return valeur


def _cible_fournisseur(cnx: Connection, role: str, identifiant: Any, *, repli: bool = False) -> Fournisseur:
    """Le fournisseur doit être configuré, ACTIF, de la bonne capacité et conforme à la politique de licence."""
    if not isinstance(identifiant, str) or not identifiant:
        raise ModelesErreur(codes.FOURNISSEUR_INVALIDE, "identifiant de fournisseur requis", 422)
    ligne = (
        cnx.execute(select(FOURNISSEURS_CONFIGURATIONS).where(FOURNISSEURS_CONFIGURATIONS.c.identifiant == identifiant))
        .mappings()
        .first()
    )
    if ligne is None:
        raise ModelesErreur(
            codes.FOURNISSEUR_INVALIDE, f"{identifiant} : fournisseur non configuré dans le registre", 409
        )
    fournisseur = Fournisseur.depuis_json(json.loads(ligne["definition"]))
    attendue = lex.CAPACITE_DU_ROLE[role]
    if fournisseur.capacite != attendue:
        raise ModelesErreur(
            codes.FOURNISSEUR_INVALIDE,
            f"{identifiant} sert la capacité {fournisseur.capacite} ; le rôle {role} demande {attendue}",
            422,
        )
    if not ligne["actif"]:
        raise ModelesErreur(
            codes.FOURNISSEUR_INVALIDE, f"{identifiant} est inactif : l'activer d'abord (politique)", 409
        )
    decision = evaluer(fournisseur, registre.lire_profil(cnx))
    if not decision.conforme:
        raise ModelesErreur(
            codes.FOURNISSEUR_REFUSE, f"{identifiant} non conforme au profil du client", 409, decision.codes
        )
    return fournisseur


def _valider_amont(amont: Any, fournisseur: Fournisseur) -> dict[str, str] | None:
    if amont is None:
        return None
    if (
        not isinstance(amont, Mapping)
        or set(amont) != {"fournisseur", "modele"}
        or not isinstance(amont["fournisseur"], str)
        or not _AMONT_FOURNISSEUR.fullmatch(amont["fournisseur"])
    ):
        raise ModelesErreur(codes.DECLARATION_INVALIDE, "amont : {fournisseur, modele} attendu", 422)
    _modele(amont["modele"], "amont.modele")
    if not (fournisseur.point_acces or "").startswith("passerelle:"):
        raise ModelesErreur(
            codes.DECLARATION_INVALIDE, "amont : réservé aux fournisseurs servis par la passerelle intégrée", 422
        )
    return {"fournisseur": amont["fournisseur"], "modele": amont["modele"]}


def _valider_replis(cnx: Connection, role: str, replis: Any, principal: tuple[str, str]) -> list[dict[str, str]]:
    if replis is None:
        replis = []
    if not isinstance(replis, list) or len(replis) > REPLIS_MAX:
        raise ModelesErreur(codes.REPLI_INVALIDE, f"replis : liste de {REPLIS_MAX} éléments au plus", 422)
    if replis and role == lex.ROLE_RAISONNEMENT:
        raise ModelesErreur(
            codes.RAISONNEMENT_ISOLE,
            "le raisonnement n'a aucun repli : il ne se dégrade pas en silence vers un autre modèle",
            422,
        )
    if replis and role == "embeddings":
        raise ModelesErreur(
            codes.REPLI_INVALIDE,
            "les embeddings n'ont aucun repli : un autre modèle produirait un autre "
            "espace vectoriel (les vecteurs seraient incomparables)",
            422,
        )
    vus = {principal}
    propres: list[dict[str, str]] = []
    for element in replis:
        if not isinstance(element, Mapping) or set(element) != {"fournisseur", "modele"}:
            raise ModelesErreur(codes.REPLI_INVALIDE, "repli : {fournisseur, modele} attendu", 422)
        _cible_fournisseur(cnx, role, element["fournisseur"], repli=True)
        modele = _modele(element["modele"], "repli.modele")
        cle = (element["fournisseur"], modele)
        if cle in vus:
            raise ModelesErreur(codes.REPLI_INVALIDE, "repli en double ou identique au fournisseur principal", 422)
        vus.add(cle)
        propres.append({"fournisseur": element["fournisseur"], "modele": modele})
    return propres


def _exiger_passerelle_si_besoin(cnx: Connection, fournisseurs: list[Fournisseur]) -> None:
    if any((f.point_acces or "").startswith("passerelle:") for f in fournisseurs) and passerelle(cnx) is None:
        raise ModelesErreur(
            codes.PASSERELLE_ABSENTE,
            "un fournisseur sert via la passerelle, qui n'est pas configurée : la connecter d'abord",
            409,
        )


def _verifier_isolation(lignes: Mapping[str, Mapping[str, Any]]) -> None:
    """Le modèle de raisonnement n'est ni principal ni repli d'un autre rôle (ni son modèle d'amont réutilisé) :
    aucune voie détournée ne mène à Opus."""
    raison = lignes.get(lex.ROLE_RAISONNEMENT)
    if raison is None:
        return
    cible = (raison["fournisseur_id"], raison["modele_appel"])
    amont = raison.get("amont")
    for role, ligne in lignes.items():
        if role == lex.ROLE_RAISONNEMENT:
            continue
        autres = [(ligne["fournisseur_id"], ligne["modele_appel"])] + [
            (r["fournisseur"], r["modele"]) for r in ligne["replis"]
        ]
        if cible in autres or (amont and ligne.get("amont") == amont):
            raise ModelesErreur(
                codes.RAISONNEMENT_ISOLE,
                f"la cible du raisonnement est aussi une cible de {role} : refusé (escalade explicite seulement)",
                409,
            )


def _construire_ligne(
    cnx: Connection, role: str, p: Mapping[str, Any], existante: Mapping[str, Any] | None
) -> dict[str, Any]:
    fournisseur = _cible_fournisseur(cnx, role, p.get("fournisseur_id"))
    modele = _modele(p.get("modele_appel"))
    replis = _valider_replis(cnx, role, p.get("replis"), (fournisseur.identifiant, modele))
    fournisseurs = [fournisseur, *(registre.definition(cnx, r["fournisseur"]) for r in replis)]
    _exiger_passerelle_si_besoin(cnx, [f for f in fournisseurs if f is not None])
    base = existante or {}

    def garder(cle: str, valide: Any) -> Any:
        return valide(p[cle]) if cle in p else base.get(cle)

    ligne = {
        "fournisseur_id": fournisseur.identifiant,
        "modele_appel": modele,
        "replis": replis,
        "amont": _valider_amont(p.get("amont"), fournisseur),
        "plafond_jetons_jour": garder("plafond_jetons_jour", _plafond_jetons),
        "budget_usd_mois": garder(
            "budget_usd_mois", lambda v: _decimal_positif(v, "budget_usd_mois", maximum=Decimal(10**7), strict=True)
        ),
        # Les coûts appartiennent au MODÈLE : un autre modèle les remet à « non déclaré » tant qu'on ne les donne pas.
        "cout_entree_par_million": _decimal_positif(
            p.get("cout_entree_par_million"), "cout_entree_par_million", maximum=Decimal(10**5), strict=False
        ),
        "cout_sortie_par_million": _decimal_positif(
            p.get("cout_sortie_par_million"), "cout_sortie_par_million", maximum=Decimal(10**5), strict=False
        ),
        "cout_source": (str(p["cout_source"])[:200] if p.get("cout_source") else None),
    }
    if ligne["cout_entree_par_million"] is None and ligne["cout_sortie_par_million"] is None:
        _couts_du_catalogue(cnx, ligne)
    return ligne


def _couts_du_catalogue(cnx: Connection, ligne: dict[str, Any]) -> None:
    """Coût DÉCLARÉ lu du catalogue de la passerelle (dernière découverte), s'il existe : jamais estimé.
    Un coût absent ou rapporté à 0 reste « non déclaré »."""
    fournisseur = registre.definition(cnx, ligne["fournisseur_id"])
    if fournisseur is None or fournisseur.point_acces != "passerelle:litellm":
        return
    decouverte, _ = lire_reglage(cnx, "catalogue")
    for entree in (decouverte or {}).get("entrees", []):
        if (
            entree["nom"] == ligne["modele_appel"]
            and entree["cout_entree_par_million"]
            and entree["cout_sortie_par_million"]
        ):
            ligne["cout_entree_par_million"] = entree["cout_entree_par_million"]
            ligne["cout_sortie_par_million"] = entree["cout_sortie_par_million"]
            ligne["cout_source"] = f"catalogue de la passerelle (découvert le {decouverte['decouvert_le'][:10]})"
            return


# -- écriture de l'historique ------------------------------------------------------------------------------------
def _historiser(cnx: Connection, cible: str, action: str, acteur: str, niveau: str, avant: Any, apres: Any) -> None:
    texte_avant = None if avant is None else _json(avant)
    texte_apres = None if apres is None else _json(apres)
    if masquage.contient_secret((texte_avant or "") + (texte_apres or "")):
        raise ModelesErreur(codes.SECRET_DETECTE, "valeur de secret détectée dans la configuration : refus", 422)
    cnx.execute(
        insert(MODELES_HISTORIQUE).values(
            quand=instant(),
            cible=cible,
            action=action,
            acteur=acteur,
            niveau=niveau,
            avant=texte_avant,
            apres=texte_apres,
        )
    )
    etat.journaliser(cnx, acteur, f"modeles.{action}", cible, {"niveau": niveau})


def _poser_ligne_role(cnx: Connection, role: str, ligne: Mapping[str, Any] | None, acteur: str) -> int:
    existante = cnx.execute(select(MODELES_ROLES.c.revision).where(MODELES_ROLES.c.role == role)).first()
    if ligne is None:
        if existante is not None:
            cnx.execute(delete(MODELES_ROLES).where(MODELES_ROLES.c.role == role))
        return 0
    valeurs = {
        **{k: ligne.get(k) for k in _CHAMPS_INSTANTANE},
        "replis": _json(ligne.get("replis") or []),
        "amont": None if not ligne.get("amont") else _json(ligne["amont"]),
        "mesures": None,
        "modifie_le": instant(),
        "modifie_par": acteur,
    }
    if existante is None:
        cnx.execute(insert(MODELES_ROLES).values(role=role, revision=1, **valeurs))
        return 1
    cnx.execute(update(MODELES_ROLES).where(MODELES_ROLES.c.role == role).values(revision=existante[0] + 1, **valeurs))
    return existante[0] + 1


def _synchroniser_selection(
    cnx: Connection, role: str, avant: Mapping[str, Any] | None, apres: Mapping[str, Any] | None, acteur: str
) -> None:
    """Pour les rôles à fournisseur unique par capacité, la sélection globale du registre reflète le rôle : les
    consommateurs existants (M10, STT, OCR…) lisent la même vérité, sans seconde configuration."""
    if role not in lex.ROLES_AVEC_SELECTION:
        return
    capacite = lex.CAPACITE_DU_ROLE[role]
    if apres is not None:
        registre.selectionner(cnx, acteur=acteur, capacite=capacite, identifiant=apres["fournisseur_id"])
        return
    if avant is not None:
        courante = [s for s in registre.selections(cnx) if s["capacite"] == capacite and s["portee"] == registre.GLOBAL]
        if courante and courante[0]["identifiant"] == avant["fournisseur_id"]:
            registre.retirer_selection(cnx, acteur=acteur, capacite=capacite)


def _verifier_revision(cnx: Connection, role: str, attendue: Any) -> None:
    if attendue is None:
        return
    ligne = cnx.execute(select(MODELES_ROLES.c.revision).where(MODELES_ROLES.c.role == role)).first()
    if attendue != (0 if ligne is None else ligne[0]):
        raise ModelesErreur(codes.CONFLIT_REVISION, f"rôle {role} modifié entre-temps", 409)


# -- URL de passerelle ---------------------------------------------------------------------------------------------
def valider_url_passerelle(url: Any, reseau_prive_confirme: bool) -> str:
    """https partout ; http seulement vers la boucle locale, ou vers un réseau PRIVÉ que le propriétaire a confirmé.
    Jamais d'identifiants dans l'URL, de paramètres, d'adresse link-local (métadonnées infonuagiques) ni non
    spécifiée."""
    refus = ModelesErreur(codes.URL_REFUSEE, "URL de passerelle refusée", 422)
    if not isinstance(url, str) or not url.isprintable() or len(url) > 300:
        raise refus
    try:
        parties = urlsplit(url)
        hote = parties.hostname
        parties.port  # noqa: B018 — lève ValueError si le port est invalide
    except ValueError:
        raise refus from None
    if (
        parties.scheme not in {"http", "https"}
        or not hote
        or parties.username
        or parties.password
        or parties.query
        or parties.fragment
        or parties.path not in {"", "/", "/v1", "/v1/"}
    ):
        raise ModelesErreur(
            codes.URL_REFUSEE,
            "URL de passerelle : http(s)://hôte[:port] sans identifiants, paramètres ni chemin autre que /v1",
            422,
        )
    adresse = None
    with contextlib.suppress(ValueError):
        adresse = ipaddress.ip_address(hote)
    if adresse is not None and (adresse.is_link_local or adresse.is_unspecified or adresse.is_multicast):
        raise ModelesErreur(codes.URL_REFUSEE, "adresse link-local, non spécifiée ou multicast refusée", 422)
    if parties.scheme == "http":
        boucle = hote == "localhost" or (adresse is not None and adresse.is_loopback)
        prive = (adresse is not None and adresse.is_private) or (adresse is None and "." not in hote)
        if not boucle and not (reseau_prive_confirme is True and prive):
            raise ModelesErreur(
                codes.URL_REFUSEE,
                "http:// en clair seulement vers la boucle locale ou un réseau "
                "privé confirmé par le propriétaire (sinon https://)",
                422,
            )
    return url.rstrip("/")


def _secret_actif(cnx: Connection, nom: Any, champ: str) -> str:
    if not isinstance(nom, str) or not _NOM_SECRET.fullmatch(nom):
        raise ModelesErreur(codes.DECLARATION_INVALIDE, f"{champ} : nom de secret du coffre attendu", 422)
    etat_secret = cnx.execute(select(COFFRE_SECRETS.c.etat).where(COFFRE_SECRETS.c.nom == nom)).scalar_one_or_none()
    if etat_secret != "actif":
        raise ModelesErreur(codes.SECRET_INDISPONIBLE, f"{champ} : secret absent ou révoqué dans le coffre", 422)
    return nom


def _construire_passerelle(cnx: Connection, p: Mapping[str, Any]) -> dict[str, Any]:
    mode = p.get("mode")
    if mode not in MODES_PASSERELLE:
        raise ModelesErreur(codes.DECLARATION_INVALIDE, f"mode parmi {', '.join(MODES_PASSERELLE)}", 422)
    prive = p.get("reseau_prive_confirme", False)
    if type(prive) is not bool:
        raise ModelesErreur(codes.DECLARATION_INVALIDE, "reseau_prive_confirme : booléen", 422)
    amont = p.get("secrets_amont") or {}
    if not isinstance(amont, Mapping) or len(amont) > 12 or any(k not in _CLE_ENV_FOURNISSEUR for k in amont):
        raise ModelesErreur(
            codes.DECLARATION_INVALIDE,
            f"secrets_amont : fournisseurs parmi {', '.join(sorted(_CLE_ENV_FOURNISSEUR))}",
            422,
        )
    return {
        "mode": mode,
        "url_base": valider_url_passerelle(p.get("url_base"), prive),
        "reseau_prive_confirme": prive,
        "secret_cle": _secret_actif(cnx, p.get("secret_cle"), "secret_cle"),
        "secrets_amont": {k: _secret_actif(cnx, v, f"secrets_amont.{k}") for k, v in sorted(amont.items())},
    }


# -- LA fonction d'écriture ----------------------------------------------------------------------------------------
def appliquer(
    cnx: Connection,
    *,
    acteur: str,
    operation: str,
    parametres: Mapping[str, Any],
    niveau_confirme: str | None = None,
    motif: str | None = None,
) -> dict[str, Any]:
    """Unique porte d'écriture de la configuration des modèles. Rend la vue du rôle ou du réglage modifié."""
    exiger_admin(cnx, acteur)
    if operation not in NIVEAU_REQUIS:
        raise ModelesErreur(codes.DECLARATION_INVALIDE, f"opération inconnue : {operation}", 422)
    if not isinstance(parametres, Mapping):
        raise ModelesErreur(codes.DECLARATION_INVALIDE, "paramètres : objet attendu", 422)
    _exiger_niveau(operation, niveau_confirme)
    niveau = niveau_confirme if niveau_confirme in _RANG else NIVEAU_REQUIS[operation]
    if operation in (OP_PASSERELLE_CONFIGURER, OP_PASSERELLE_RETIRER):
        return _op_passerelle(cnx, acteur, operation, parametres, niveau)
    if operation in (OP_RAISONNEMENT_ACTIVER, OP_RAISONNEMENT_DESACTIVER):
        return _op_raisonnement(cnx, acteur, operation, parametres, niveau, motif)
    if operation == OP_REVENIR:
        return _op_revenir(cnx, acteur, parametres, niveau)
    return _op_role(cnx, acteur, operation, parametres, niveau)


def _op_passerelle(cnx: Connection, acteur: str, operation: str, p: Mapping[str, Any], niveau: str) -> dict[str, Any]:
    avant, _ = lire_reglage(cnx, "passerelle")
    if operation == OP_PASSERELLE_RETIRER:
        utilisee = [r for r, ligne in toutes_les_lignes(cnx).items() if _utilise_passerelle(cnx, ligne)]
        if utilisee:
            raise ModelesErreur(
                codes.PASSERELLE_ABSENTE,
                f"rôles encore servis par la passerelle : {', '.join(utilisee)} (les retirer d'abord)",
                409,
            )
        apres = None
    else:
        apres = _construire_passerelle(cnx, p)
    _historiser(cnx, "passerelle", operation, acteur, niveau, avant, apres)
    _ecrire_reglage(cnx, "passerelle", apres, acteur)
    return {"passerelle": apres}


def _utilise_passerelle(cnx: Connection, ligne: Mapping[str, Any]) -> bool:
    identifiants = [ligne["fournisseur_id"], *(r["fournisseur"] for r in ligne["replis"])]
    for identifiant in identifiants:
        f = registre.definition(cnx, identifiant)
        if f is not None and (f.point_acces or "").startswith("passerelle:"):
            return True
    return False


def _op_raisonnement(
    cnx: Connection, acteur: str, operation: str, p: Mapping[str, Any], niveau: str, motif: str | None
) -> dict[str, Any]:
    avant, _ = lire_reglage(cnx, "raisonnement")
    if operation == OP_RAISONNEMENT_ACTIVER:
        texte = motif if motif is not None else p.get("motif")
        if not isinstance(texte, str) or not _MOTIF.fullmatch(texte):
            raise ModelesErreur(
                codes.CONFIRMATION_REQUISE, "motif de l'activation du raisonnement requis (10 à 300 caractères)", 422
            )
        ligne = _ligne_role(cnx, lex.ROLE_RAISONNEMENT)
        if ligne is None:
            raise ModelesErreur(
                codes.ROLE_NON_CONFIGURE, "affecter d'abord un fournisseur au rôle llm_raisonnement", 409
            )
        # Revalidation : le fournisseur doit être encore actif et conforme au moment de l'activation.
        _cible_fournisseur(cnx, lex.ROLE_RAISONNEMENT, ligne["fournisseur_id"])
        apres = {"actif": True, "par": acteur, "motif": texte, "le": instant()}
    else:
        apres = {"actif": False, "par": acteur, "le": instant()}
    _historiser(cnx, "raisonnement", operation, acteur, niveau, avant, apres)
    _ecrire_reglage(cnx, "raisonnement", apres, acteur)
    return {"raisonnement": apres}


def _op_role(cnx: Connection, acteur: str, operation: str, p: Mapping[str, Any], niveau: str) -> dict[str, Any]:
    role = lex.verifier_role(p.get("role")) if p.get("role") in lex.ROLES else None
    if role is None:
        raise ModelesErreur(codes.ROLE_INCONNU, f"rôle parmi {', '.join(lex.ROLES)}", 422)
    existante = _ligne_role(cnx, role)
    _verifier_revision(cnx, role, p.get("revision_attendue"))
    avant = _instantane_role(existante)
    if operation == OP_ROLE_AFFECTER:
        nouvelle = _construire_ligne(cnx, role, p, existante)
    elif existante is None:
        raise ModelesErreur(codes.ROLE_NON_CONFIGURE, f"le rôle {role} n'a pas d'affectation", 409)
    elif operation == OP_ROLE_RETIRER:
        nouvelle = None
    elif operation == OP_ROLE_REPLIS:
        nouvelle = {
            **existante,
            "replis": _valider_replis(
                cnx, role, p.get("replis"), (existante["fournisseur_id"], existante["modele_appel"])
            ),
        }
        _exiger_passerelle_si_besoin(
            cnx, [f for f in (registre.definition(cnx, r["fournisseur"]) for r in nouvelle["replis"]) if f is not None]
        )
    elif operation == OP_ROLE_PLAFONDS:
        nouvelle = {
            **existante,
            "plafond_jetons_jour": _plafond_jetons(p.get("plafond_jetons_jour")),
            "budget_usd_mois": _decimal_positif(
                p.get("budget_usd_mois"), "budget_usd_mois", maximum=Decimal(10**7), strict=True
            ),
        }
    else:  # OP_ROLE_COUTS
        nouvelle = {
            **existante,
            "cout_entree_par_million": _decimal_positif(
                p.get("cout_entree_par_million"), "cout_entree_par_million", maximum=Decimal(10**5), strict=False
            ),
            "cout_sortie_par_million": _decimal_positif(
                p.get("cout_sortie_par_million"), "cout_sortie_par_million", maximum=Decimal(10**5), strict=False
            ),
            "cout_source": str(p["cout_source"])[:200] if p.get("cout_source") else "déclaré par le propriétaire",
        }
    return _ecrire_role(cnx, acteur, operation, role, avant, nouvelle, niveau)


def _ecrire_role(
    cnx: Connection,
    acteur: str,
    action: str,
    role: str,
    avant: Mapping[str, Any] | None,
    nouvelle: Mapping[str, Any] | None,
    niveau: str,
) -> dict[str, Any]:
    lignes = {r: ligne for r, ligne in toutes_les_lignes(cnx).items() if r != role}
    if nouvelle is not None:
        lignes[role] = dict(nouvelle)
    _verifier_isolation(lignes)
    apres = _instantane_role(nouvelle)
    _historiser(cnx, f"role:{role}", action, acteur, niveau, avant, apres)
    _poser_ligne_role(cnx, role, nouvelle, acteur)
    _synchroniser_selection(cnx, role, avant, apres, acteur)
    return {"role": role, "configure": nouvelle is not None, **(apres or {})}


def _op_revenir(cnx: Connection, acteur: str, p: Mapping[str, Any], niveau: str) -> dict[str, Any]:
    cible = p.get("cible")
    if not isinstance(cible, str) or not re.fullmatch(r"(role:[a-z_]{3,24}|passerelle|raisonnement)", cible):
        raise ModelesErreur(codes.DECLARATION_INVALIDE, "cible : role:<rôle>, passerelle ou raisonnement", 422)
    derniere = (
        cnx.execute(
            select(MODELES_HISTORIQUE)
            .where(MODELES_HISTORIQUE.c.cible == cible)
            .order_by(MODELES_HISTORIQUE.c.id.desc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    if derniere is None:
        raise ModelesErreur(codes.RIEN_A_ANNULER, f"aucun changement à annuler pour {cible}", 409)
    ancien = json.loads(derniere["avant"]) if derniere["avant"] else None
    if cible == "passerelle":
        courant, _ = lire_reglage(cnx, "passerelle")
        if ancien is not None:
            ancien = _construire_passerelle(cnx, ancien)  # revalidé : URL, secrets encore actifs
        _historiser(cnx, cible, OP_REVENIR, acteur, niveau, courant, ancien)
        _ecrire_reglage(cnx, "passerelle", ancien, acteur)
        return {"passerelle": ancien}
    if cible == "raisonnement":
        courant, _ = lire_reglage(cnx, "raisonnement")
        if ancien is not None and ancien.get("actif") is True:
            ligne = _ligne_role(cnx, lex.ROLE_RAISONNEMENT)
            if ligne is None:
                raise ModelesErreur(codes.ROLE_NON_CONFIGURE, "rôle llm_raisonnement sans affectation", 409)
            _cible_fournisseur(cnx, lex.ROLE_RAISONNEMENT, ligne["fournisseur_id"])
        _historiser(cnx, cible, OP_REVENIR, acteur, niveau, courant, ancien)
        _ecrire_reglage(cnx, "raisonnement", ancien, acteur)
        return {"raisonnement": ancien}
    role = cible.removeprefix("role:")
    if role not in lex.ROLES:
        raise ModelesErreur(codes.ROLE_INCONNU, f"rôle parmi {', '.join(lex.ROLES)}", 422)
    existante = _ligne_role(cnx, role)
    avant = _instantane_role(existante)
    nouvelle = None
    if ancien is not None:
        # Revalidation complète : l'ancien fournisseur peut être devenu inactif ou non conforme depuis.
        nouvelle = _construire_ligne(cnx, role, {k: v for k, v in ancien.items() if k != "cout_source" or v}, None)
        for cle in (
            "plafond_jetons_jour",
            "budget_usd_mois",
            "cout_entree_par_million",
            "cout_sortie_par_million",
            "cout_source",
        ):
            nouvelle[cle] = ancien.get(cle)
    return _ecrire_role(cnx, acteur, OP_REVENIR, role, avant, nouvelle, niveau)


# -- mesures et usage (observations, pas des changements de configuration) ------------------------------------------
def enregistrer_mesure(cnx: Connection, role: str, mesure: Mapping[str, Any]) -> None:
    """Dernière mesure d'un test de connexion (statut, latence, dimension…) ; sans révision, sans secret."""
    texte = _json(mesure)
    if masquage.contient_secret(texte):
        raise ModelesErreur(codes.SECRET_DETECTE, "valeur de secret détectée dans la mesure : refus", 422)
    cnx.execute(update(MODELES_ROLES).where(MODELES_ROLES.c.role == lex.verifier_role(role)).values(mesures=texte))


def ecrire_catalogue(cnx: Connection, entrees: list[dict[str, Any]], acteur: str) -> None:
    texte = _json(entrees)
    if masquage.contient_secret(texte):
        raise ModelesErreur(codes.SECRET_DETECTE, "valeur de secret détectée dans le catalogue : refus", 422)
    _ecrire_reglage(cnx, "catalogue", {"decouvert_le": instant(), "entrees": entrees}, acteur)


def usage(cnx: Connection, role: str, jour: str | None = None) -> dict[str, int]:
    jour = jour or aujourd_hui()
    ligne = (
        cnx.execute(select(MODELES_USAGE).where((MODELES_USAGE.c.role == role) & (MODELES_USAGE.c.jour == jour)))
        .mappings()
        .first()
    )
    if ligne is None:
        return {"appels": 0, "jetons_entree": 0, "jetons_sortie": 0, "cout_micro_usd": 0, "appels_repli": 0}
    return {k: int(ligne[k]) for k in ("appels", "jetons_entree", "jetons_sortie", "cout_micro_usd", "appels_repli")}


def usage_mois(cnx: Connection, role: str, jour: str | None = None) -> dict[str, int]:
    jour = jour or aujourd_hui()
    debut = jour[:8] + "01"
    total = {"appels": 0, "jetons_entree": 0, "jetons_sortie": 0, "cout_micro_usd": 0}
    for ligne in cnx.execute(
        select(MODELES_USAGE).where(
            (MODELES_USAGE.c.role == role) & (MODELES_USAGE.c.jour >= debut) & (MODELES_USAGE.c.jour <= jour)
        )
    ).mappings():
        for cle in total:
            total[cle] += int(ligne[cle])
    return total


def ajouter_usage(cnx: Connection, role: str, *, entree: int, sortie: int, cout_micro_usd: int, repli: bool) -> None:
    jour = aujourd_hui()
    existe = cnx.execute(
        select(MODELES_USAGE.c.role).where((MODELES_USAGE.c.role == role) & (MODELES_USAGE.c.jour == jour))
    ).first()
    if existe is None:
        cnx.execute(
            insert(MODELES_USAGE).values(
                role=role,
                jour=jour,
                appels=0 if repli else 1,
                jetons_entree=0 if repli else entree,
                jetons_sortie=0 if repli else sortie,
                cout_micro_usd=0 if repli else cout_micro_usd,
                appels_repli=1 if repli else 0,
            )
        )
        return
    if repli:
        cnx.execute(
            update(MODELES_USAGE)
            .where((MODELES_USAGE.c.role == role) & (MODELES_USAGE.c.jour == jour))
            .values(appels_repli=MODELES_USAGE.c.appels_repli + 1)
        )
    else:
        cnx.execute(
            update(MODELES_USAGE)
            .where((MODELES_USAGE.c.role == role) & (MODELES_USAGE.c.jour == jour))
            .values(
                appels=MODELES_USAGE.c.appels + 1,
                jetons_entree=MODELES_USAGE.c.jetons_entree + entree,
                jetons_sortie=MODELES_USAGE.c.jetons_sortie + sortie,
                cout_micro_usd=MODELES_USAGE.c.cout_micro_usd + cout_micro_usd,
            )
        )


# -- vue pour la console, la CLI et les outils ---------------------------------------------------------------------
def historique(cnx: Connection, cible: str | None = None, limite: int = 30) -> list[dict[str, Any]]:
    requete = select(MODELES_HISTORIQUE).order_by(MODELES_HISTORIQUE.c.id.desc()).limit(min(max(limite, 1), 200))
    if cible:
        requete = requete.where(MODELES_HISTORIQUE.c.cible == cible)
    return [
        {
            **dict(r),
            "avant": json.loads(r["avant"]) if r["avant"] else None,
            "apres": json.loads(r["apres"]) if r["apres"] else None,
        }
        for r in cnx.execute(requete).mappings()
    ]


def _vue_fournisseur(cnx: Connection, identifiant: str) -> dict[str, Any] | None:
    try:
        v = registre.vue(cnx, identifiant)
    except registre.RegistreErreur:
        return None
    licence = v["licence"]
    return {
        "identifiant": identifiant,
        "mode": v["mode"],
        "modele": v["modele"],
        "point_acces": v["point_acces"],
        "actif": v["actif"],
        "conforme": v["politique"]["conforme"],
        "refus": [r["code"] for r in v["politique"]["refus"]],
        "qualification": v["qualification"],
        "statut_catalogue": v["statut_catalogue"],
        "residence_donnees": v["residence_donnees"],
        "efvp_ref": v["efvp_ref"],
        "contrat_ref": v["contrat_ref"],
        "licence": {
            "code": licence["code"],
            "poids": licence["poids"],
            "usage_commercial": licence["usage_commercial"],
            "service_tiers": licence["service_tiers"],
            "verification": licence["verification"],
            "seuil_revenu_usd": licence["seuil_revenu_usd"],
        },
        "cout_declare": v["cout_unitaire"],
        "dernier_test": v["dernier_test"],
    }


def etat_mesure(fournisseur: Mapping[str, Any] | None, mesure: Mapping[str, Any] | None) -> dict[str, Any]:
    """« Mesuré » = qualité qualifiée par une mesure locale (jamais ici) ; la connexion testée est dite à part."""
    qualifie = bool(fournisseur and fournisseur.get("qualification") == "qualifie")
    return {
        "mesure": qualifie,
        "libelle": "mesuré" if qualifie else "non mesuré",
        "connexion_testee": bool(mesure and mesure.get("statut") == "succes"),
        "dernier_test": mesure,
    }


def vue_role(cnx: Connection, role: str, *, jour: str | None = None) -> dict[str, Any]:
    ligne = _ligne_role(cnx, role)
    reco = lex.RECOMMANDATIONS.get(role)
    base: dict[str, Any] = {
        "role": role,
        "libelle": lex.LIBELLES[role],
        "capacite": lex.CAPACITE_DU_ROLE[role],
        "alias": lex.ALIAS_ROLE[role],
        "recommandation": reco,
        "configure": ligne is not None,
        "classes": sorted(c for c, r in economie.CLASSES.items() if r["role"] == role),
    }
    if ligne is None:
        return {**base, "etat": "inerte"}
    fournisseur = _vue_fournisseur(cnx, ligne["fournisseur_id"])
    jour = jour or aujourd_hui()
    jetons = usage(cnx, role, jour)
    mois = usage_mois(cnx, role, jour)
    return {
        **base,
        "etat": "actif",
        "fournisseur": fournisseur,
        "modele_appel": ligne["modele_appel"],
        "replis": [{**r, "fournisseur_vue": _vue_fournisseur(cnx, r["fournisseur"])} for r in ligne["replis"]],
        "amont": ligne["amont"],
        "revision": ligne["revision"],
        "plafonds": {"jetons_jour": ligne["plafond_jetons_jour"], "budget_usd_mois": ligne["budget_usd_mois"]},
        "usage_jour": jetons,
        "usage_mois": mois,
        "cout": {
            "entree_par_million": ligne["cout_entree_par_million"],
            "sortie_par_million": ligne["cout_sortie_par_million"],
            "source": ligne["cout_source"],
            "devise": "USD",
        },
        "mesure": etat_mesure(fournisseur, ligne["mesures"]),
        "plafond_atteint": bool(
            ligne["plafond_jetons_jour"]
            and jetons["jetons_entree"] + jetons["jetons_sortie"] >= ligne["plafond_jetons_jour"]
        ),
        "modifie_le": ligne["modifie_le"],
        "modifie_par": ligne["modifie_par"],
        "actif_raisonnement": raisonnement_actif(cnx) if role == lex.ROLE_RAISONNEMENT else None,
    }


def vue_passerelle(cnx: Connection) -> dict[str, Any]:
    p, revision = lire_reglage(cnx, "passerelle")
    if p is None:
        return {"configuree": False}
    noms = [p["secret_cle"], *p["secrets_amont"].values()]
    etats = {
        n: cnx.execute(select(COFFRE_SECRETS.c.etat).where(COFFRE_SECRETS.c.nom == n)).scalar_one_or_none()
        for n in noms
    }
    return {"configuree": True, "revision": revision, **p, "etat_secrets": etats}


def vue_complete(cnx: Connection) -> dict[str, Any]:
    catalogue_decouvert, _ = lire_reglage(cnx, "catalogue")
    raisonnement, _ = lire_reglage(cnx, "raisonnement")
    return {
        "passerelle": vue_passerelle(cnx),
        "raisonnement": {"actif": raisonnement_actif(cnx), "detail": raisonnement},
        "roles": [vue_role(cnx, r) for r in lex.ROLES],
        "politique_economie": economie.vue(),
        "catalogue_passerelle": catalogue_decouvert,
        "profil_licence_declare": registre.lire_profil(cnx) is not None,
        "historique": historique(cnx, limite=20),
    }


__all__ = ["NIVEAU_REQUIS", "ModelesErreur", "appliquer", "vue_complete", "vue_role"]
