"""Outils de M10 pour ses routines planifiées : énumérer les affaires à consolider, auditer le non-oubli, calculer les
KPI,
lire les rapports. Adaptateur de `routines` (pur).

Quatre outils, tous INTERNES (aucun contact externe) et agent seulement (aucun droit d'appareil) :

- `m10_lister_affaires_a_consolider` (N0) : l'énumérateur déterministe des affaires touchées un jour. La consolidation
d'une
  affaire reste `m10_consolider_affaire` (inchangé, idempotent) ;
- `m10_executer_audit_non_oubli` (N2) : l'audit hebdomadaire, dont l'ATTENDU est relu du bus (reçus « traité » de M10),
puis
  consigné au registre `rapports_routine` (`ecrire` faux : lecture seule, c'est ce que fait l'ombre) ;
- `m10_calculer_kpis` (N2) : les cinq KPI du manifeste, calculables ou dits non calculables, consignés au même registre
;
- `m10_lire_rapports_routine` (N0) : le résultat consultable (dernier audit, derniers KPI, consolidations récentes).

Le rapport est RECALCULÉ ici, côté serveur, à chaque écriture : un appelant ne peut pas y faire consigner un contenu
qu'il a
composé. Une écriture identique à une ligne existante (même clé = genre, fin, empreinte du contenu) n'ajoute rien.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import select

from opsys import service_acteur_systeme as systeme
from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage import codec
from opsys.stockage.concurrence import verrou_consultatif
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

from . import audit, consolidation, registre, routines, validation
from . import outils as _o

CONSOMMATEUR = "m10-memoire"
PUBLICATIONS_MAX = 5000  # au-delà, l'audit refuse la fenêtre (fail-closed) plutôt que d'en lire une partie
_REGISTRE_RAPPORTS = registre.Registre(maillons=stockage.maillons("m10-memoire", "rapports_routine"))
_AFFAIRE_JOUR = {"type": "string", "description": "AAAA-MM-JJ, jour touché (date telle qu'écrite au registre)."}
_DECALAGE_ENUMERATION: ContextVar[int] = ContextVar("m10_decalage_enumeration", default=0)


@contextmanager
def decalage_enumeration_interne(decalage: int) -> Iterator[None]:
    """Curseur temporaire du planificateur; aucun argument ni état public du registre MCP."""
    if not systeme.planificateur_en_cours():
        raise PermissionError("curseur interne réservé au planificateur")
    if type(decalage) is not int or decalage < 0:
        raise ValueError("décalage interne entier positif ou nul requis")
    jeton = _DECALAGE_ENUMERATION.set(decalage)
    try:
        yield
    finally:
        _DECALAGE_ENUMERATION.reset(jeton)


def _verdict(code: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "verdict": validation.construire_verdict(code, detail)}


def _jour_valide(jour: Any) -> bool:
    import datetime as dt
    import re

    try:
        return (
            isinstance(jour, str)
            and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", jour, re.ASCII) is not None
            and dt.date.fromisoformat(jour).isoformat() == jour
        )
    except ValueError:
        return False


def _instant_valide(valeur: Any) -> dict[str, Any] | None:
    try:
        routines.instant(valeur)
    except ValueError as exc:
        code, _, detail = str(exc).partition(": ")
        return _verdict(code, detail)
    return None


def _refus_hors_planificateur() -> dict[str, Any] | None:
    """L'écriture d'un rapport n'appartient qu'au planificateur durable : l'instant vient de SON horloge, jamais d'un
    argument d'agent (un agent pourrait sinon occuper la clé d'un rapport avec un instant forgé). Refusé avant toute
    lecture."""
    if systeme.planificateur_en_cours():
        return None
    return _verdict(
        "REJ-ROUTINE-PLANIFICATEUR-REQUIS", "écriture réservée au planificateur durable (acteur système, tour en cours)"
    )


def _ecrire_rapport(genre: str, horodatage: str, cle_fin: str, contenu: dict[str, Any]) -> bool:
    cnx = stockage.connexion_courante()
    if cnx is None or not cnx.in_transaction():
        raise RuntimeError("REJ-ROUTINE-STOCKAGE: une transaction de l'instance est requise")
    verrou_consultatif(cnx, "m10-rapports-routine")
    cle = f"{genre}|{cle_fin}|{routines.empreinte(contenu)[:16]}"
    if any(m.get("cle") == cle for m in _REGISTRE_RAPPORTS.lire()):
        return False
    _REGISTRE_RAPPORTS.ajouter(
        {
            "type_entree": routines.TYPE_RAPPORT,
            "horodatage": horodatage,
            "genre": genre,
            "cle": cle,
            "fin": cle_fin,
            "contenu": contenu,
        }
    )
    return True


# -- 1. l'énumérateur -------------------------------------------------------------------------------------------------
def lister_affaires_a_consolider(jour: str, limite: int = 50) -> dict[str, Any]:
    refus = _o._refus_lecture_admin()
    if refus is not None:
        return refus
    if not _jour_valide(jour):
        return _verdict("REJ-ROUTINE-JOUR-INVALIDE", "jour doit être une date calendaire AAAA-MM-JJ")
    if type(limite) is not int or not 1 <= limite <= routines.LIMITE_MAX:
        return _verdict("REJ-ROUTINE-LIMITE-INVALIDE", f"limite entière de 1 à {routines.LIMITE_MAX}")
    decalage = _DECALAGE_ENUMERATION.get()
    return {
        "accepte": True,
        "resultat": routines.enumerer(
            jour, limite, _o._REGISTRE_EVENEMENTS.lire(), _o._REGISTRE_AFFAIRES.lire(), decalage=decalage
        ),
    }


# -- 2. l'audit hebdomadaire
# ---------------------------------------------------------------------------------------------
def _publications(debut_iso: str) -> list[dict[str, Any]] | None:
    """Les publications du bus de types audités depuis `debut_iso`, avec le statut du reçu de M10 ; `None` si la fenêtre
    dépasse `PUBLICATIONS_MAX`."""
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise RuntimeError("REJ-ROUTINE-STOCKAGE: une transaction de l'instance est requise")
    lignes = cnx.execute(
        select(
            EVENEMENTS_SORTANTS.c.evenement_id,
            EVENEMENTS_SORTANTS.c.type_evenement,
            EVENEMENTS_SORTANTS.c.charge,
        )
        .where(
            EVENEMENTS_SORTANTS.c.type_evenement.in_(audit.types_audites()), EVENEMENTS_SORTANTS.c.cree_le >= debut_iso
        )
        .order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)
        .limit(PUBLICATIONS_MAX + 1)
    ).all()
    if len(lignes) > PUBLICATIONS_MAX:
        return None
    recus = {
        r.evenement_id: r.statut
        for r in cnx.execute(
            select(EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.statut).where(
                EVENEMENTS_RECUS.c.consommateur == CONSOMMATEUR,
                EVENEMENTS_RECUS.c.evenement_id.in_([x.evenement_id for x in lignes]) if lignes else False,
            )
        )
    }
    return [
        {"type_evenement": x.type_evenement, "charge": codec.decoder(x.charge), "recu": recus.get(x.evenement_id)}
        for x in lignes
    ]


def executer_audit_non_oubli(fin: str, jours: int = routines.JOURS_AUDIT_DEFAUT, ecrire: bool = True) -> dict[str, Any]:
    refus = _o._refus_lecture_admin() or _instant_valide(fin)
    if refus is not None:
        return refus
    if type(jours) is not int or not 1 <= jours <= routines.JOURS_AUDIT_MAX or type(ecrire) is not bool:
        return _verdict("REJ-ROUTINE-FENETRE-INVALIDE", f"jours : entier de 1 à {routines.JOURS_AUDIT_MAX}")
    if ecrire and (refus := _refus_hors_planificateur()) is not None:
        return refus
    fin_utc = routines.instant(fin).astimezone(UTC)
    publications = _publications((fin_utc - timedelta(days=jours)).isoformat())
    if publications is None:
        return _verdict(
            "REJ-AUDIT-FENETRE-TROP-GRANDE",
            f"plus de {PUBLICATIONS_MAX} publications dans la fenêtre : réduire `jours`",
        )
    rapport = routines.rapport_audit(
        fin,
        jours,
        routines.attendus_du_bus(publications),
        _o._REGISTRE_EVENEMENTS.lire(),
        _o._REGISTRE_AFFAIRES.lire(),
        {"evenements": _o._REGISTRE_EVENEMENTS, "affaires": _o._REGISTRE_AFFAIRES},
    )
    ecrit = _ecrire_rapport(routines.GENRE_AUDIT, fin, fin, rapport) if ecrire else False
    return {"accepte": True, "resultat": {"ecrit": ecrit, **rapport}}


# -- 3. les KPI
# ----------------------------------------------------------------------------------------------------------
def calculer_kpis(jour: str, debut_cycle: str, fin_cycle: str, horodatage: str, ecrire: bool = True) -> dict[str, Any]:
    refus = (
        _o._refus_lecture_admin()
        or _instant_valide(debut_cycle)
        or _instant_valide(fin_cycle)
        or _instant_valide(horodatage)
    )
    if refus is not None:
        return refus
    if not _jour_valide(jour) or type(ecrire) is not bool:
        return _verdict("REJ-ROUTINE-JOUR-INVALIDE", "jour doit être une date calendaire AAAA-MM-JJ")
    if routines.instant(debut_cycle) >= routines.instant(fin_cycle):
        return _verdict("REJ-ROUTINE-CYCLE-INVALIDE", "debut_cycle doit précéder fin_cycle")
    if ecrire and (refus := _refus_hors_planificateur()) is not None:
        return refus
    calcul = routines.kpis(jour, debut_cycle, fin_cycle, _o._REGISTRE_AFFAIRES.lire(), _REGISTRE_RAPPORTS.lire())
    ecrit = _ecrire_rapport(routines.GENRE_KPIS, horodatage, jour, calcul) if ecrire else False
    return {"accepte": True, "resultat": {"ecrit": ecrit, **calcul}}


# -- 4. la lecture
# ---------------------------------------------------------------------------------------------------------
def lire_rapports_routine(genre: str, limite: int = 1) -> dict[str, Any]:
    refus = _o._refus_lecture_admin()
    if refus is not None:
        return refus
    if genre not in (*routines.genres(), "consolidation"):
        return _verdict("REJ-ROUTINE-GENRE-INCONNU", f"genre parmi {[*routines.genres(), 'consolidation']}")
    if type(limite) is not int or not 1 <= limite <= 14:
        return _verdict("REJ-ROUTINE-LIMITE-INVALIDE", "limite entière de 1 à 14")
    if genre == "consolidation":
        par_jour: dict[str, dict[str, set[str] | int]] = {}
        for maillon in _o._REGISTRE_AFFAIRES.lire():
            if maillon.get("type_entree") == consolidation.TYPE_ENTREE_FAIT:
                bloc = par_jour.setdefault(maillon["jour"], {"faits": 0, "affaires": set()})
                bloc["faits"] += 1
                bloc["affaires"].add(maillon["affaire_id"])
        jours = sorted(par_jour, reverse=True)[:limite]
        return {
            "accepte": True,
            "resultat": {
                "genre": genre,
                "jours": [
                    {"jour": j, "faits": par_jour[j]["faits"], "affaires": len(par_jour[j]["affaires"])} for j in jours
                ],
            },
        }
    trouves = [m for m in _REGISTRE_RAPPORTS.lire() if m.get("genre") == genre]
    return {
        "accepte": True,
        "resultat": {
            "genre": genre,
            "rapports": [
                {"horodatage": m["horodatage"], "fin": m["fin"], "contenu": m["contenu"]}
                for m in trouves[-limite:][::-1]
            ],
        },
    }


def outils_routines() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m10_lister_affaires_a_consolider",
            description=(
                "Énumère, pour un jour donné (date telle qu'écrite au registre Événements), les affaires touchées et "
                "celles "
                "dont le fait durable manque ou ne cite pas toutes les sources du jour : exactement celles pour "
                "lesquelles "
                "m10_consolider_affaire écrirait un maillon. Tri stable, borné par `limite` (`reste` dit le "
                "surplus). Une "
                "affaire à l'identifiant hors forme est comptée (`affaires_refusees`) et jamais désignée. Lecture "
                "seule."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "jour": _AFFAIRE_JOUR,
                    "limite": {"type": "integer", "minimum": 1, "maximum": routines.LIMITE_MAX},
                },
                "required": ["jour"],
                "additionalProperties": False,
            },
            fonction=lister_affaires_a_consolider,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom="m10_executer_audit_non_oubli",
            description=(
                "Audit hebdomadaire « non-oubli » : l'attendu est relu du bus (événements que M10 a reçus comme "
                "traités, "
                "sur `jours` jours finissant à `fin`) ; questions-tests déterministes (trace des événements livrés, "
                "chaînes "
                "intactes, jours consolidés, révisions en attente, âge de la dernière mémoire), chacune avec son "
                "compte. "
                "Consigne le rapport au registre des rapports (idempotent) ; `ecrire` faux : lecture seule."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "fin": {"type": "string", "description": "Instant de l'audit, ISO-8601 avec fuseau."},
                    "jours": {"type": "integer", "minimum": 1, "maximum": routines.JOURS_AUDIT_MAX},
                    "ecrire": {"type": "boolean"},
                },
                "required": ["fin"],
                "additionalProperties": False,
            },
            fonction=executer_audit_non_oubli,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m10_calculer_kpis",
            description=(
                "Calcule les KPI de M10 déclarés au manifeste : ceux que les registres permettent (révisions "
                "arbitrées, "
                "affaires consolidées pendant le cycle `[debut_cycle, fin_cycle[`, oublis du dernier audit) avec "
                "numérateur "
                "et dénominateur, et dit « non calculable » avec ce qui manque pour les autres (jamais zéro). "
                "Consigne le "
                "résultat au registre des rapports (idempotent) ; `ecrire` faux : lecture seule."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "jour": _AFFAIRE_JOUR,
                    "debut_cycle": {
                        "type": "string",
                        "description": "Début de la journée du cycle, ISO-8601 avec fuseau.",
                    },
                    "fin_cycle": {"type": "string", "description": "Fin (exclue) de la journée du cycle."},
                    "horodatage": {"type": "string"},
                    "ecrire": {"type": "boolean"},
                },
                "required": ["jour", "debut_cycle", "fin_cycle", "horodatage"],
                "additionalProperties": False,
            },
            fonction=calculer_kpis,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m10_lire_rapports_routine",
            description=(
                "Lit le résultat des routines planifiées : `audit_non_oubli` (derniers rapports), `kpis` (derniers "
                "calculs) "
                "ou `consolidation` (faits durables par jour, le plus récent d'abord). Lecture seule."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "genre": {"type": "string", "enum": [*routines.genres(), "consolidation"]},
                    "limite": {"type": "integer", "minimum": 1, "maximum": 14},
                },
                "required": ["genre"],
                "additionalProperties": False,
            },
            fonction=lire_rapports_routine,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
    )
