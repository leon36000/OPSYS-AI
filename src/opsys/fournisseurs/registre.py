"""Registre durable des fournisseurs : configuration, activation sous politique, sélection et résolution.

- `configurer` fige une définition (catalogue ou déclaration personnalisée) en base, sans valeur de secret.
  Le bloc licence d'une entrée du catalogue est immuable ; seule la lecture du texte intégral peut être
  consignée (`licence_lue`). Une déclaration personnalisée porte son bloc licence complet.
- `activer` évalue la politique contre le profil du client : un refus est journalisé et RENDU avec ses codes ;
  rien d'autre n'est activé à la place (aucun repli silencieux).
- `selectionner` associe une capacité à un fournisseur actif et conforme, par département ou par défaut global.
- `resoudre` rend le fournisseur d'une capacité pour un département : la sélection du département prime, sinon
  le défaut global ; si la sélection retenue est inactive ou devenue non conforme (ex. revenu déclaré au-delà
  du seuil), c'est un REFUS explicite, jamais le défaut global ni un autre fournisseur.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from .. import etat, identite
from ..secrets_coffre import coffre, masquage
from ..secrets_coffre.erreurs import CoffreErreur
from ..stockage.schema import COFFRE_SECRETS, FOURNISSEURS_CONFIGURATIONS, FOURNISSEURS_PROFIL, FOURNISSEURS_SELECTIONS
from . import catalogue, sondes
from .modele import CAPACITES, RESIDENCES, Cout, DeclarationInvalide, Fournisseur, Licence, Quotas
from .politique import Decision, ProfilClient, evaluer, profil_depuis_ligne

GLOBAL = "*"
_DEPARTEMENT = re.compile(r"^m(0[1-9]|10)-[a-z0-9-]{2,40}$")
_MODIFIABLES = frozenset({
    "point_acces", "modele", "reference_secret", "efvp_ref", "contrat_ref", "mention_confirmee", "licence_lue",
    "quotas", "cout_unitaire", "residence_donnees",
})
FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]


class RegistreErreur(ValueError):
    def __init__(self, code: str, detail: str, statut_http: int = 409, codes: tuple[str, ...] = ()) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail, self.statut_http, self.codes = code, detail, statut_http, codes

    def publique(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "refus": list(self.codes)}


@dataclasses.dataclass(frozen=True)
class Resolution:
    fournisseur: Fournisseur
    portee: str  # département ou "*" : dit toujours d'où vient le choix

    def vers_json(self) -> dict[str, Any]:
        return {"identifiant": self.fournisseur.identifiant, "portee": self.portee}


def _admin(cnx: Connection, acteur: str) -> None:
    personne = identite.personne_active(cnx, acteur) if isinstance(acteur, str) else None
    if personne is None:
        raise RegistreErreur("ADMIN_REQUIS", "authentification requise", 401)
    if not personne.roles.intersection(coffre.ROLES_ADMIN):
        raise RegistreErreur("ADMIN_REQUIS", "administration réservée au propriétaire ou à un administrateur", 403)


def _instant() -> str:
    return coffre._instant()


# -- profil du client ---------------------------------------------------------------------------------
def profil_brut(cnx: Connection) -> dict[str, Any] | None:
    ligne = cnx.execute(select(FOURNISSEURS_PROFIL).where(FOURNISSEURS_PROFIL.c.id == 1)).mappings().first()
    if ligne is None:
        return None
    profil = profil_depuis_ligne(ligne)
    assert profil is not None
    return {**profil.vers_json(), "revision": ligne["revision"], "modifie_le": ligne["modifie_le"],
            "modifie_par": ligne["modifie_par"]}


def lire_profil(cnx: Connection) -> ProfilClient | None:
    return profil_depuis_ligne(
        cnx.execute(select(FOURNISSEURS_PROFIL).where(FOURNISSEURS_PROFIL.c.id == 1)).mappings().first())


def declarer_profil(cnx: Connection, *, acteur: str, usage_commercial: bool, revenu_annuel_usd: int | None,
                    territoires: list[str] | tuple[str, ...], heberge_pour_tiers: bool,
                    revision_attendue: int) -> dict[str, Any]:
    _admin(cnx, acteur)
    try:
        profil = ProfilClient(usage_commercial, revenu_annuel_usd, frozenset(territoires), heberge_pour_tiers)
    except DeclarationInvalide as exc:
        raise RegistreErreur("PROFIL_INVALIDE", str(exc), 422) from None
    courant = profil_brut(cnx)
    revision = 0 if courant is None else courant["revision"]
    if revision_attendue != revision:
        raise RegistreErreur("CONFLIT_REVISION", f"profil modifié entre-temps (révision {revision})")
    valeurs = {"usage_commercial": profil.usage_commercial, "revenu_annuel_usd": profil.revenu_annuel_usd,
               "territoires": json.dumps(sorted(profil.territoires)), "heberge_pour_tiers": profil.heberge_pour_tiers,
               "revision": revision + 1, "modifie_le": _instant(), "modifie_par": acteur}
    if courant is None:
        cnx.execute(insert(FOURNISSEURS_PROFIL).values(id=1, **valeurs))
    else:
        cnx.execute(update(FOURNISSEURS_PROFIL).where(FOURNISSEURS_PROFIL.c.id == 1).values(**valeurs))
    etat.journaliser(cnx, acteur, "fournisseurs.profil.declarer", "profil", profil.vers_json())
    resultat = profil_brut(cnx)
    assert resultat is not None
    return resultat


# -- configurations -----------------------------------------------------------------------------------
def _ligne(cnx: Connection, identifiant: str) -> Mapping[str, Any] | None:
    return cnx.execute(select(FOURNISSEURS_CONFIGURATIONS).where(
        FOURNISSEURS_CONFIGURATIONS.c.identifiant == identifiant)).mappings().first()


def definition(cnx: Connection, identifiant: str) -> Fournisseur | None:
    ligne = _ligne(cnx, identifiant)
    if ligne is not None:
        return Fournisseur.depuis_json(json.loads(ligne["definition"]))
    return catalogue.par_identifiant().get(identifiant)


def _appliquer(base: Fournisseur, modifications: Mapping[str, Any], acteur: str) -> Fournisseur:
    if set(modifications) - _MODIFIABLES:
        raise RegistreErreur("CHAMP_NON_MODIFIABLE",
                             f"champs modifiables : {', '.join(sorted(_MODIFIABLES))} (licence du catalogue immuable)",
                             422)
    valeurs = {k: v for k, v in modifications.items() if k != "licence_lue"}
    for champ in ("point_acces", "reference_secret", "efvp_ref", "contrat_ref"):
        if valeurs.get(champ) == "":
            valeurs[champ] = None
    try:
        if "quotas" in valeurs and isinstance(valeurs["quotas"], Mapping):
            valeurs["quotas"] = Quotas(**valeurs["quotas"])
        if "cout_unitaire" in valeurs and isinstance(valeurs["cout_unitaire"], Mapping):
            valeurs["cout_unitaire"] = Cout(**valeurs["cout_unitaire"])
    except (DeclarationInvalide, TypeError) as exc:
        raise RegistreErreur("DECLARATION_INVALIDE", str(exc), 422) from None
    if valeurs.get("residence_donnees") not in (None, *RESIDENCES):
        raise RegistreErreur("RESIDENCE_INVALIDE", f"résidence parmi {', '.join(RESIDENCES)}", 422)
    if modifications.get("licence_lue") is True:
        valeurs["licence_lue_par"] = f"{acteur} le {_instant()[:10]}"
    elif modifications.get("licence_lue") not in (None, False):
        raise RegistreErreur("CHAMP_INVALIDE", "licence_lue est un booléen", 422)
    try:
        return dataclasses.replace(base, **valeurs)
    except (DeclarationInvalide, TypeError) as exc:
        raise RegistreErreur("DECLARATION_INVALIDE", str(exc), 422) from None


def configurer(cnx: Connection, *, acteur: str, identifiant: str, modifications: Mapping[str, Any] | None = None,
               revision_attendue: int = 0, declaration: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Crée ou modifie la configuration d'un fournisseur (révision optimiste). Une déclaration personnalisée
    (absente du catalogue) passe par `declaration` : fournisseur complet, bloc licence compris."""
    _admin(cnx, acteur)
    ligne = _ligne(cnx, identifiant)
    revision = 0 if ligne is None else ligne["revision"]
    if revision_attendue != revision:
        raise RegistreErreur("CONFLIT_REVISION", f"configuration modifiée entre-temps (révision {revision})")
    if declaration is not None:
        if ligne is not None or identifiant in catalogue.par_identifiant():
            raise RegistreErreur("DECLARATION_EXISTANTE", "identifiant déjà connu : modifier sa configuration", 409)
        try:
            base = Fournisseur.depuis_json({**declaration, "identifiant": identifiant, "statut_catalogue": "declare",
                                            "qualification": "a_mesurer", "licence_lue_par": None})
        except DeclarationInvalide as exc:
            raise RegistreErreur("DECLARATION_INVALIDE", str(exc), 422) from None
    else:
        base = definition(cnx, identifiant)
        if base is None:
            raise RegistreErreur("FOURNISSEUR_INCONNU", "fournisseur absent du catalogue et non déclaré", 404)
    fournisseur = _appliquer(base, modifications or {}, acteur)
    if fournisseur.nom_secret is not None:
        etat_secret = cnx.execute(select(COFFRE_SECRETS.c.etat).where(
            COFFRE_SECRETS.c.nom == fournisseur.nom_secret)).scalar_one_or_none()
        if etat_secret != "actif":
            raise RegistreErreur("SECRET_INDISPONIBLE", "référence de secret inconnue ou révoquée dans le coffre", 422)
    actif = bool(ligne["actif"]) if ligne is not None else False
    if actif:
        decision = evaluer(fournisseur, lire_profil(cnx))
        if not decision.conforme:
            raise RegistreErreur("REFUS_POLITIQUE", "fournisseur actif : la modification le rendrait non conforme",
                                 409, decision.codes)
    valeurs = {"capacite": fournisseur.capacite, "definition": fournisseur.canonique(), "actif": actif,
               "revision": revision + 1, "modifie_le": _instant(), "modifie_par": acteur}
    if ligne is None:
        cnx.execute(insert(FOURNISSEURS_CONFIGURATIONS).values(identifiant=identifiant, **valeurs))
    else:
        cnx.execute(update(FOURNISSEURS_CONFIGURATIONS).where(
            FOURNISSEURS_CONFIGURATIONS.c.identifiant == identifiant).values(**valeurs))
    etat.journaliser(cnx, acteur, "fournisseurs.configurer", identifiant,
                     {"revision": revision + 1, "champs": sorted((modifications or {}).keys()),
                      "declaration": declaration is not None})
    return vue(cnx, identifiant)


def activer(cnx: Connection, *, acteur: str, identifiant: str) -> Decision:
    """Active si et seulement si la politique est conforme ; sinon journalise le refus et le rend tel quel."""
    _admin(cnx, acteur)
    ligne = _ligne(cnx, identifiant)
    if ligne is None:
        raise RegistreErreur("NON_CONFIGURE", "configurer le fournisseur avant de l'activer", 409)
    fournisseur = Fournisseur.depuis_json(json.loads(ligne["definition"]))
    decision = evaluer(fournisseur, lire_profil(cnx))
    if not decision.conforme:
        etat.journaliser(cnx, acteur, "fournisseurs.activation.refusee", identifiant, {"refus": list(decision.codes)})
        return decision
    cnx.execute(update(FOURNISSEURS_CONFIGURATIONS).where(
        FOURNISSEURS_CONFIGURATIONS.c.identifiant == identifiant).values(
        actif=True, revision=ligne["revision"] + 1, modifie_le=_instant(), modifie_par=acteur))
    etat.journaliser(cnx, acteur, "fournisseurs.activer", identifiant, {})
    return decision


def desactiver(cnx: Connection, *, acteur: str, identifiant: str) -> dict[str, Any]:
    _admin(cnx, acteur)
    ligne = _ligne(cnx, identifiant)
    if ligne is None:
        raise RegistreErreur("NON_CONFIGURE", "fournisseur non configuré", 404)
    cnx.execute(update(FOURNISSEURS_CONFIGURATIONS).where(
        FOURNISSEURS_CONFIGURATIONS.c.identifiant == identifiant).values(
        actif=False, revision=ligne["revision"] + 1, modifie_le=_instant(), modifie_par=acteur))
    etat.journaliser(cnx, acteur, "fournisseurs.desactiver", identifiant, {})
    return vue(cnx, identifiant)


# -- sélection et résolution --------------------------------------------------------------------------
def _portee(departement: str | None) -> str:
    if departement is None or departement == GLOBAL:
        return GLOBAL
    if not isinstance(departement, str) or not _DEPARTEMENT.fullmatch(departement):
        raise RegistreErreur("DEPARTEMENT_INVALIDE", "code de département attendu (ex. m07-marketing)", 422)
    return departement


def selectionner(cnx: Connection, *, acteur: str, capacite: str, identifiant: str,
                 departement: str | None = None) -> dict[str, Any]:
    _admin(cnx, acteur)
    if capacite not in CAPACITES:
        raise RegistreErreur("CAPACITE_INVALIDE", f"capacité parmi {', '.join(CAPACITES)}", 422)
    portee = _portee(departement)
    ligne = _ligne(cnx, identifiant)
    if ligne is None:
        raise RegistreErreur("NON_CONFIGURE", "fournisseur non configuré", 409)
    if ligne["capacite"] != capacite:
        raise RegistreErreur("CAPACITE_INCOMPATIBLE", f"{identifiant} sert la capacité {ligne['capacite']}", 422)
    if not ligne["actif"]:
        raise RegistreErreur("FOURNISSEUR_INACTIF", "activer le fournisseur avant de le sélectionner", 409)
    decision = evaluer(Fournisseur.depuis_json(json.loads(ligne["definition"])), lire_profil(cnx))
    if not decision.conforme:
        raise RegistreErreur("REFUS_POLITIQUE", "fournisseur non conforme au profil du client", 409, decision.codes)
    cnx.execute(delete(FOURNISSEURS_SELECTIONS).where(
        (FOURNISSEURS_SELECTIONS.c.capacite == capacite) & (FOURNISSEURS_SELECTIONS.c.portee == portee)))
    cnx.execute(insert(FOURNISSEURS_SELECTIONS).values(capacite=capacite, portee=portee, identifiant=identifiant,
                                                       modifie_le=_instant(), modifie_par=acteur))
    etat.journaliser(cnx, acteur, "fournisseurs.selectionner", f"{capacite}@{portee}", {"identifiant": identifiant})
    return {"capacite": capacite, "portee": portee, "identifiant": identifiant}


def retirer_selection(cnx: Connection, *, acteur: str, capacite: str, departement: str | None = None) -> bool:
    _admin(cnx, acteur)
    portee = _portee(departement)
    resultat = cnx.execute(delete(FOURNISSEURS_SELECTIONS).where(
        (FOURNISSEURS_SELECTIONS.c.capacite == capacite) & (FOURNISSEURS_SELECTIONS.c.portee == portee)))
    etat.journaliser(cnx, acteur, "fournisseurs.selection.retirer", f"{capacite}@{portee}", {})
    return resultat.rowcount > 0


def selections(cnx: Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in cnx.execute(select(FOURNISSEURS_SELECTIONS).order_by(
        FOURNISSEURS_SELECTIONS.c.capacite, FOURNISSEURS_SELECTIONS.c.portee)).mappings()]


def resoudre(cnx: Connection, capacite: str, departement: str | None = None) -> Resolution:
    if capacite not in CAPACITES:
        raise RegistreErreur("CAPACITE_INVALIDE", f"capacité parmi {', '.join(CAPACITES)}", 422)
    portees = [GLOBAL] if departement is None else [_portee(departement), GLOBAL]
    for portee in portees:
        ligne = cnx.execute(select(FOURNISSEURS_SELECTIONS).where(
            (FOURNISSEURS_SELECTIONS.c.capacite == capacite) & (FOURNISSEURS_SELECTIONS.c.portee == portee)
        )).mappings().first()
        if ligne is None:
            continue
        # La première sélection trouvée est LA décision : un problème ici ne retombe jamais sur le défaut global.
        config = _ligne(cnx, ligne["identifiant"])
        assert config is not None  # clé étrangère
        if not config["actif"]:
            raise RegistreErreur("FOURNISSEUR_INACTIF", f"{ligne['identifiant']} sélectionné pour {capacite}@{portee} "
                                 "est inactif ; aucun repli", 409)
        fournisseur = Fournisseur.depuis_json(json.loads(config["definition"]))
        decision = evaluer(fournisseur, lire_profil(cnx))
        if not decision.conforme:
            raise RegistreErreur("REFUS_POLITIQUE", f"{fournisseur.identifiant} n'est plus conforme ; aucun repli",
                                 409, decision.codes)
        return Resolution(fournisseur, portee)
    raise RegistreErreur("AUCUN_FOURNISSEUR", f"aucun fournisseur sélectionné pour {capacite} "
                         f"({departement or 'global'}) ni par défaut", 404)


# -- lecture ------------------------------------------------------------------------------------------
def vue(cnx: Connection, identifiant: str, profil: ProfilClient | None = None, *,
        profil_lu: bool = False) -> dict[str, Any]:
    fournisseur = definition(cnx, identifiant)
    if fournisseur is None:
        raise RegistreErreur("FOURNISSEUR_INCONNU", "fournisseur inconnu", 404)
    ligne = _ligne(cnx, identifiant)
    decision = evaluer(fournisseur, profil if profil_lu else lire_profil(cnx))
    return {
        **fournisseur.vers_json(),
        "configure": ligne is not None, "actif": bool(ligne["actif"]) if ligne else False,
        "revision": ligne["revision"] if ligne else 0,
        "dernier_test": json.loads(ligne["dernier_test"]) if ligne and ligne["dernier_test"] else None,
        "politique": decision.vers_json(),
    }


def lister(cnx: Connection, capacite: str | None = None) -> list[dict[str, Any]]:
    profil = lire_profil(cnx)
    configures = cnx.execute(select(FOURNISSEURS_CONFIGURATIONS.c.identifiant)).scalars().all()
    identifiants = list(dict.fromkeys([*(f.identifiant for f in catalogue.CATALOGUE), *sorted(configures)]))
    vues = [vue(cnx, i, profil, profil_lu=True) for i in identifiants]
    return [v for v in vues if capacite is None or v["capacite"] == capacite]


# -- test de connexion --------------------------------------------------------------------------------
def tester(fabrique: FabriqueConnexion, *, acteur: str, identifiant: str, sonde: sondes.Sonde | None = None,
           delai_s: float = 5.0) -> dict[str, Any]:
    """Test de connexion : politique d'abord (aucun appel pour un fournisseur non conforme), secret résolu côté
    serveur au dernier moment, sonde hors transaction, résultat consigné."""
    with fabrique() as cnx:
        _admin(cnx, acteur)
        ligne = _ligne(cnx, identifiant)
        if ligne is None:
            raise RegistreErreur("NON_CONFIGURE", "configurer le fournisseur avant de le tester", 409)
        fournisseur = Fournisseur.depuis_json(json.loads(ligne["definition"]))
        decision = evaluer(fournisseur, lire_profil(cnx))
    resultat: dict[str, Any]
    if not decision.conforme:
        resultat = {"statut": "refuse_politique", "detail": "aucun appel : fournisseur non conforme",
                    "refus": list(decision.codes), "latence_ms": None}
    elif not fournisseur.point_acces:
        resultat = {"statut": "echec", "detail": "point d'accès non configuré", "latence_ms": None}
    else:
        try:
            if fournisseur.nom_secret is not None:
                with coffre.utiliser(nom=fournisseur.nom_secret, usage=f"fournisseur:{identifiant}",
                                     acteur=f"console:{acteur}", fabrique=fabrique) as secret:
                    brut = sondes.sonder(fournisseur, secret, delai_s, http=sonde)
            else:
                brut = sondes.sonder(fournisseur, None, delai_s, http=sonde)
            resultat = brut.vers_json()
        except CoffreErreur as exc:
            resultat = {"statut": "echec", "detail": f"secret indisponible ({exc.code})", "latence_ms": None}
    resultat = masquage.masquer({**resultat, "date": _instant()})
    with fabrique() as cnx:
        _admin(cnx, acteur)
        cnx.execute(update(FOURNISSEURS_CONFIGURATIONS).where(
            FOURNISSEURS_CONFIGURATIONS.c.identifiant == identifiant).values(
            dernier_test=json.dumps(resultat, ensure_ascii=False, sort_keys=True)))
        etat.journaliser(cnx, acteur, "fournisseurs.tester", identifiant,
                         {"statut": resultat["statut"], "refus": resultat.get("refus", [])})
    return resultat


__all__ = ["GLOBAL", "Licence", "RegistreErreur", "Resolution", "activer", "configurer", "declarer_profil",
           "definition", "desactiver", "lire_profil", "lister", "profil_brut", "resoudre", "retirer_selection",
           "selectionner", "selections", "tester", "vue"]
