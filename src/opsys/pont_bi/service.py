"""Pont BI : jetons de lecture dédiés, quotas, journal d'accès, lecture seule imposée.

LE JETON. Un jeton BI est un secret du COFFRE (`pont-bi.<jeton_id>`, service « autre ») dont la valeur n'existe en clair
qu'au moment de l'émission, rendue UNE fois à la personne qui l'émet. Le porteur présente
``opsys-bi:v1:<jeton_id>.<secret>``
dans l'en-tête ``Authorization: Bearer`` ; le serveur retrouve la ligne de `pont_bi_jetons` (métadonnées : jeux permis,
portée financière, quotas, expiration, révocation) puis compare le secret à la valeur du coffre en temps constant. La
portée
est de LECTURE et DÉDIÉE : ce jeton ne s'accepte que sur les routes du pont BI, il n'ouvre aucun outil d'agent, aucun
registre, aucune écriture. Jamais dans une URL ; jamais dans un journal (ni valeur, ni empreinte).

ÉMETTRE, RÉVOQUER : gestes d'une PERSONNE active `admin` ou `nathan_owner` (relue en base par le coffre), jamais d'un
agent :
aucun outil de département ne les expose (N3 humain). L'émission passe par la CLI (`opsys-metier pont-bi
jeton-emettre`).

QUOTAS. Par jeton : un nombre de requêtes par heure et de lignes par jour, comptés dans le journal d'accès. Un quota
dépassé est un refus 429 AVANT toute lecture de données, journalisé.

JOURNAL. `pont_bi_acces` est append-only (déclencheurs) : quand, quel jeton (identifiant, jamais le secret), quel jeu,
quel
format, combien de lignes, accepté ou refusé et pourquoi. Jamais le contenu exporté.

LECTURE SEULE. Les données se lisent dans leur propre transaction, ouverte en lecture seule (`PRAGMA query_only` sur
SQLite, `SET TRANSACTION READ ONLY` sur PostgreSQL) ; le code ne contient aucune écriture sur les tables exportées.
"""

from __future__ import annotations

import datetime as dt
import hmac
import json
import re
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from sqlalchemy import Connection, and_, func, insert, not_, select, update

from .. import etat
from ..secrets_coffre import coffre
from ..secrets_coffre.cle_maitresse import CleMaitresse
from ..secrets_coffre.erreurs import CoffreErreur
from ..stockage import schema
from .jeux import JEUX, Colonne, Jeu

PREFIXE = "opsys-bi:v1:"
USAGE = "pont_bi:lecture"
ACTEUR_SERVEUR = "pont-bi"
_FORME_JETON = re.compile(r"^opsys-bi:v1:([0-9a-f]{32})\.([A-Za-z0-9_-]{43})$")
LIGNES_PAR_REQUETE_MAX = 5000
DUREE_MIN_S, DUREE_MAX_S = 3600, 365 * 86400
QUOTA_MAX = 10_000_000
FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]


class RefusPontBI(Exception):
    """Un refus du pont BI : statut HTTP, code stable, message sans donnée ni secret."""

    def __init__(self, statut: int, code: str, message: str) -> None:
        super().__init__(f"{code} : {message}")
        self.statut = statut
        self.code = code
        self.message = message


def _instant(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Émission, révocation, liste : gestes d'une personne
# ---------------------------------------------------------------------------
def emettre(
    cnx: Connection,
    *,
    acteur: str,
    libelle: str,
    jeux: list[str],
    financier: bool = False,
    quota_requetes_heure: int = 60,
    quota_lignes_jour: int = 100_000,
    duree_s: int = 30 * 86400,
    cle: CleMaitresse | None = None,
    maintenant: float | None = None,
) -> dict[str, Any]:
    """Émet un jeton de lecture. Rend le jeton UNE fois (``jeton``) et ses métadonnées. ``acteur`` doit être une
    personne
    active admin ou propriétaire (relue en base par le coffre). Les jeux sont une partie de la liste fermée ; la portée
    financière est un choix explicite, jamais un défaut."""
    if not isinstance(libelle, str) or not 3 <= len(libelle.strip()) <= 120:
        raise RefusPontBI(422, "libelle_invalide", "libellé de 3 à 120 caractères")
    if not isinstance(jeux, list) or not jeux or len(set(jeux)) != len(jeux) or any(j not in JEUX for j in jeux):
        raise RefusPontBI(422, "jeux_invalides", f"jeux : une partie de {sorted(JEUX)}, sans doublon")
    if not isinstance(financier, bool):
        raise RefusPontBI(422, "financier_invalide", "portée financière : booléen explicite")
    for nom, valeur, maximum in (
        ("quota_requetes_heure", quota_requetes_heure, 100_000),
        ("quota_lignes_jour", quota_lignes_jour, QUOTA_MAX),
    ):
        if type(valeur) is not int or not 1 <= valeur <= maximum:
            raise RefusPontBI(422, "quota_invalide", f"{nom} : entier de 1 à {maximum}")
    if type(duree_s) is not int or not DUREE_MIN_S <= duree_s <= DUREE_MAX_S:
        raise RefusPontBI(422, "duree_invalide", "durée de 1 heure à 365 jours")
    instant = time.time() if maintenant is None else maintenant
    jeton_id = secrets.token_hex(16)
    secret = secrets.token_urlsafe(32)
    nom_secret = f"pont-bi.{jeton_id}"
    try:
        coffre.definir(cnx, acteur=acteur, nom=nom_secret, service="autre", valeur=secret, cle=cle)
    except CoffreErreur as exc:
        raise RefusPontBI(
            403, exc.code.lower(), "émission refusée : une personne admin ou propriétaire est requise"
        ) from None
    cnx.execute(
        insert(schema.PONT_BI_JETONS).values(
            jeton_id=jeton_id,
            libelle=libelle.strip(),
            secret_nom=nom_secret,
            jeux=json.dumps(sorted(jeux)),
            financier=financier,
            quota_requetes_heure=quota_requetes_heure,
            quota_lignes_jour=quota_lignes_jour,
            cree_le=_instant(instant),
            cree_par=acteur,
            expire_epoch=int(instant) + duree_s,
            revoque=False,
        )
    )
    etat.journaliser(
        cnx, acteur, "pont_bi.jeton_emis", jeton_id, {"jeux": sorted(jeux), "financier": financier, "duree_s": duree_s}
    )
    return {
        "jeton": f"{PREFIXE}{jeton_id}.{secret}",
        "jeton_id": jeton_id,
        "libelle": libelle.strip(),
        "jeux": sorted(jeux),
        "financier": financier,
        "quota_requetes_heure": quota_requetes_heure,
        "quota_lignes_jour": quota_lignes_jour,
        "expire_le": _instant(int(instant) + duree_s),
    }


def revoquer(cnx: Connection, *, acteur: str, jeton_id: str, maintenant: float | None = None) -> dict[str, Any]:
    ligne = (
        cnx.execute(select(schema.PONT_BI_JETONS).where(schema.PONT_BI_JETONS.c.jeton_id == jeton_id))
        .mappings()
        .first()
    )
    if ligne is None:
        raise RefusPontBI(404, "jeton_inconnu", "jeton inconnu")
    try:
        coffre.revoquer(cnx, acteur=acteur, nom=ligne["secret_nom"])
    except CoffreErreur as exc:
        raise RefusPontBI(
            403, exc.code.lower(), "révocation refusée : une personne admin ou propriétaire est requise"
        ) from None
    instant = time.time() if maintenant is None else maintenant
    cnx.execute(
        update(schema.PONT_BI_JETONS)
        .where(schema.PONT_BI_JETONS.c.jeton_id == jeton_id)
        .values(revoque=True, revoque_le=_instant(instant), revoque_par=acteur)
    )
    etat.journaliser(cnx, acteur, "pont_bi.jeton_revoque", jeton_id, {})
    return {"jeton_id": jeton_id, "revoque": True}


def lister(cnx: Connection, *, maintenant: float | None = None) -> list[dict[str, Any]]:
    """Les jetons (métadonnées seulement : jamais le secret) avec leur état."""
    instant = time.time() if maintenant is None else maintenant
    sortie = []
    for ligne in cnx.execute(select(schema.PONT_BI_JETONS).order_by(schema.PONT_BI_JETONS.c.cree_le)).mappings():
        sortie.append(
            {
                "jeton_id": ligne["jeton_id"],
                "libelle": ligne["libelle"],
                "jeux": json.loads(ligne["jeux"]),
                "financier": ligne["financier"],
                "quota_requetes_heure": ligne["quota_requetes_heure"],
                "quota_lignes_jour": ligne["quota_lignes_jour"],
                "cree_le": ligne["cree_le"],
                "cree_par": ligne["cree_par"],
                "expire_le": _instant(ligne["expire_epoch"]),
                "etat": "revoque" if ligne["revoque"] else "expire" if ligne["expire_epoch"] <= instant else "actif",
            }
        )
    return sortie


# ---------------------------------------------------------------------------
# Authentification, quotas, journal
# ---------------------------------------------------------------------------
def lire_jeton(entete: str | None) -> tuple[str, str]:
    """``(jeton_id, secret)`` d'un en-tête ``Authorization: Bearer …``. Absent ou mal formé : 401, sans rien dire du
    pourquoi (pas d'oracle)."""
    if not entete or not entete.startswith("Bearer "):
        raise RefusPontBI(401, "non_authentifie", "jeton de lecture requis (Authorization: Bearer)")
    trouve = _FORME_JETON.fullmatch(entete[len("Bearer ") :].strip())
    if trouve is None:
        raise RefusPontBI(401, "non_authentifie", "jeton de lecture requis (Authorization: Bearer)")
    return trouve.group(1), trouve.group(2)


def charger_jeton(cnx: Connection, jeton_id: str, maintenant: float) -> dict[str, Any]:
    ligne = (
        cnx.execute(select(schema.PONT_BI_JETONS).where(schema.PONT_BI_JETONS.c.jeton_id == jeton_id))
        .mappings()
        .first()
    )
    if ligne is None or ligne["revoque"] or ligne["expire_epoch"] <= maintenant:
        raise RefusPontBI(401, "non_authentifie", "jeton de lecture requis (Authorization: Bearer)")
    return {**dict(ligne), "jeux": json.loads(ligne["jeux"])}


def verifier_secret(
    fabrique: FabriqueConnexion,
    jeton: dict[str, Any],
    secret: str,
    *,
    cle: CleMaitresse | None = None,
    maintenant: float | None = None,
) -> None:
    """Compare le secret présenté à la valeur du coffre, en temps constant. Ouvre sa propre transaction (le coffre
    l'exige hors transaction métier). Tout échec est le même 401."""
    try:
        with coffre.utiliser(
            usage=USAGE,
            acteur=ACTEUR_SERVEUR,
            nom=jeton["secret_nom"],
            cle=cle,
            fabrique=fabrique,
            maintenant=maintenant,
        ) as valeur:
            correct = hmac.compare_digest(valeur.encode("utf-8"), secret.encode("utf-8"))
    except CoffreErreur:
        correct = False
    if not correct:
        raise RefusPontBI(401, "non_authentifie", "jeton de lecture requis (Authorization: Bearer)")


def journaliser(
    cnx: Connection,
    *,
    maintenant: float,
    jeton_id: str | None,
    jeu: str | None,
    format: str | None,
    phase: str,
    statut: str,
    code: str | None = None,
    lignes: int | None = None,
) -> None:
    cnx.execute(
        insert(schema.PONT_BI_ACCES).values(
            quand=_instant(maintenant),
            epoch=int(maintenant),
            jeton_id=jeton_id,
            jeu=jeu,
            format=format,
            phase=phase,
            statut=statut,
            code=code,
            lignes=lignes,
        )
    )


def usage(cnx: Connection, jeton_id: str, maintenant: float) -> dict[str, int]:
    """Requêtes acceptées dans la dernière heure et lignes remises dans les dernières 24 h, d'après le journal."""
    acces = schema.PONT_BI_ACCES
    requetes = cnx.execute(
        select(func.count())
        .select_from(acces)
        .where(
            and_(
                acces.c.jeton_id == jeton_id,
                acces.c.phase == "debut",
                acces.c.statut == "accepte",
                acces.c.epoch > int(maintenant) - 3600,
            )
        )
    ).scalar_one()
    lignes = cnx.execute(
        select(func.coalesce(func.sum(acces.c.lignes), 0)).where(
            and_(
                acces.c.jeton_id == jeton_id,
                acces.c.phase == "fin",
                acces.c.statut == "termine",
                acces.c.epoch > int(maintenant) - 86400,
            )
        )
    ).scalar_one()
    return {"requetes_derniere_heure": int(requetes), "lignes_dernieres_24h": int(lignes)}


def controler_quota_requetes(cnx: Connection, jeton: dict[str, Any], maintenant: float) -> None:
    if usage(cnx, jeton["jeton_id"], maintenant)["requetes_derniere_heure"] >= jeton["quota_requetes_heure"]:
        raise RefusPontBI(429, "quota_requetes", "quota de requêtes par heure atteint")


def controler_quota_lignes(cnx: Connection, jeton: dict[str, Any], maintenant: float, a_remettre: int) -> None:
    if usage(cnx, jeton["jeton_id"], maintenant)["lignes_dernieres_24h"] + a_remettre > jeton["quota_lignes_jour"]:
        raise RefusPontBI(429, "quota_lignes", "quota de lignes par jour atteint")


def acces_recents(cnx: Connection, limite: int = 50) -> list[dict[str, Any]]:
    """Le journal d'accès, du plus récent au plus ancien, borné."""
    limite = max(1, min(int(limite), 500))
    requete = select(schema.PONT_BI_ACCES).order_by(schema.PONT_BI_ACCES.c.id.desc()).limit(limite)
    return [dict(ligne) for ligne in cnx.execute(requete).mappings()]


# ---------------------------------------------------------------------------
# Lecture seule des données
# ---------------------------------------------------------------------------
@contextmanager
def lecture_seule(cnx: Connection) -> Iterator[Connection]:
    """La transaction EN LECTURE SEULE pour exporter. SQLite : ``PRAGMA query_only`` pendant le bloc (toute écriture est
    refusée par le moteur). PostgreSQL : ``SET TRANSACTION READ ONLY`` (à poser avant toute requête de la
    transaction)."""
    dialecte = cnx.dialect.name
    if dialecte == "sqlite":
        cnx.exec_driver_sql("PRAGMA query_only = ON")
        try:
            yield cnx
        finally:
            cnx.exec_driver_sql("PRAGMA query_only = OFF")
    elif dialecte == "postgresql":
        cnx.exec_driver_sql("SET TRANSACTION READ ONLY")
        yield cnx
    else:  # pragma: no cover - backends non qualifiés
        raise RefusPontBI(500, "backend_non_qualifie", "backend non pris en charge")


def _filtre_lignes_financieres(jeu: Jeu, financier: bool) -> Any:
    """Sans portée financière, les lignes des mesures « financier » n'existent pas (même dans l'historique)."""
    if financier or not jeu.lignes_financieres_par_mesure:
        return None
    mesures = schema.M8_ENT_MESURES_COURANTES
    interdites = select(mesures.c.metric_id).where(mesures.c.sensibilite == "financier")
    colonne = jeu.table.c.metric_id
    return not_(colonne.in_(interdites))


def lire_jeu(
    cnx: Connection,
    jeu: Jeu,
    *,
    financier: bool,
    limite: int,
    depart: int,
    selection: list[str] | None = None,
) -> tuple[tuple[Colonne, ...], list[dict[str, Any]], int]:
    """``(colonnes, lignes, total)`` d'un jeu : colonnes visibles pour la portée du jeton (financières retirées), lignes
    triées dans l'ordre déclaré, ``limite`` lignes à partir de ``depart``. Lecture seule : un ``select``, rien
    d'autre."""
    if type(limite) is not int or not 1 <= limite <= LIGNES_PAR_REQUETE_MAX or type(depart) is not int or depart < 0:
        raise RefusPontBI(400, "pagination_invalide", f"limite de 1 à {LIGNES_PAR_REQUETE_MAX}, départ ≥ 0")
    visibles = jeu.colonnes_visibles(financier)
    if selection is not None:
        noms = {c.nom for c in visibles}
        if any(n not in noms for n in selection):
            raise RefusPontBI(400, "select_invalide", "colonne inconnue ou hors de la portée du jeton")
        visibles = tuple(c for c in visibles if c.nom in selection)
    filtre = _filtre_lignes_financieres(jeu, financier)
    table = jeu.table
    comptage = select(func.count()).select_from(table)
    requete = select(*[table.c[c.nom] for c in visibles]).order_by(*[table.c[o] for o in jeu.ordre])
    if filtre is not None:
        comptage, requete = comptage.where(filtre), requete.where(filtre)
    total = cnx.execute(comptage).scalar_one()
    lignes = [dict(r) for r in cnx.execute(requete.limit(limite).offset(depart)).mappings()]
    return visibles, lignes, int(total)


def etat_entrepot(cnx: Connection) -> dict[str, Any] | None:
    """La dernière construction de l'entrepôt (provenance de ce que le pont sert), ou ``None``."""
    ligne = (
        cnx.execute(select(schema.M8_ENT_CONSTRUCTIONS).order_by(schema.M8_ENT_CONSTRUCTIONS.c.rang.desc()).limit(1))
        .mappings()
        .first()
    )
    return dict(ligne) if ligne is not None else None
