"""Adaptateur SQL NATIF du port `MoteurGraphe` : trois tables append-only (migration 0052), SQLAlchemy Core, SQLite et
PostgreSQL, sans base de graphe ni dépendance de plus.

Pourquoi pas Neo4j (décision de l'architecte r1) : des centaines de milliers de relations au plus pour une PME, des
requêtes de 1 à 4 sauts, un besoin de provenance et de transactions avec le reste de l'instance (le même `COMMIT` que
l'événement qui l'a fait naître). Une base de graphe séparée ajouterait un service, une sauvegarde et un second contrôle
d'accès pour un gain que la mesure (`mesure.py`) n'a pas montré.

Requêtes : une seule lecture SQL par niveau du parcours (jamais une par nœud), bornée par `K_MAX` et les plafonds du
port ; l'état d'une arête est le dernier événement de `graphe_aretes_etats`. Les écritures d'état sont des INSERT
conditionnels à l'état courant (deux confirmations simultanées n'en appliquent qu'une).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Connection, bindparam, insert, literal, select
from sqlalchemy.exc import IntegrityError

from ...stockage.schema import GRAPHE_ARETES as ARETES_T
from ...stockage.schema import GRAPHE_ARETES_ETATS as ETATS_T
from ...stockage.schema import GRAPHE_NOEUDS as NOEUDS_T
from .. import codes
from ..codes import ErreurMnemo
from . import regles, schema
from .port import K_MAX, NOEUDS_MAX, Arete, Chemin, DemandeArete, Noeud, Proposition, Voisinage
from .schema import NoeudRef

_LOT = 400  # nombre maximal d'identifiants dans un `IN (...)`
_PLAFOND_NOEUDS = 200_000
_PLAFOND_ARETES = 500_000


def _noeud(ligne: Mapping[str, Any]) -> Noeud:
    return Noeud(ligne["noeud_id"], ligne["type"], ligne["cle"], ligne["libelle"], ligne["cree_le"])


class GrapheSql:
    """Graphe de l'instance, dans la transaction `cnx` de l'appelant (jamais de commit ici)."""

    def __init__(self, cnx: Connection) -> None:
        self._cnx = cnx

    # -- nœuds -------------------------------------------------------------------------------------------------------
    def noeud(self, type_noeud: str, cle: str) -> Noeud | None:
        ligne = (
            self._cnx.execute(select(NOEUDS_T).where(NOEUDS_T.c.type == type_noeud, NOEUDS_T.c.cle == cle))
            .mappings()
            .first()
        )
        return _noeud(ligne) if ligne else None

    def _noeud_par_id(self, noeud_id: str) -> Noeud:
        ligne = self._cnx.execute(select(NOEUDS_T).where(NOEUDS_T.c.noeud_id == noeud_id)).mappings().first()
        if ligne is None:
            raise ErreurMnemo(codes.NOEUD_INCONNU, "nœud introuvable")
        return _noeud(ligne)

    def poser_noeud(
        self, type_noeud: str, cle: str, libelle: str | None, *, source_ref: str, par: str, quand: str
    ) -> Noeud:
        type_noeud, cle, libelle_propre = schema.valider_noeud(type_noeud, cle, libelle)
        schema.exiger_source_ref(source_ref)
        existant = self.noeud(type_noeud, cle)
        if existant is not None:
            return existant  # idempotent : le premier libellé fait foi, aucune réécriture
        if self._cnx.execute(select(NOEUDS_T.c.noeud_id).limit(1).offset(_PLAFOND_NOEUDS - 1)).first() is not None:
            raise ErreurMnemo(codes.PLAFOND, f"plus de {_PLAFOND_NOEUDS} nœuds : archiver avant d'en ajouter")
        ident = schema.noeud_id(type_noeud, cle)
        try:
            with self._cnx.begin_nested():
                self._cnx.execute(
                    insert(NOEUDS_T).values(
                        noeud_id=ident,
                        type=type_noeud,
                        cle=cle,
                        libelle=libelle_propre,
                        source_ref=source_ref,
                        cree_le=quand,
                        cree_par=par,
                    )
                )
        except IntegrityError:  # course : un autre appel l'a posé entre-temps
            existant = self.noeud(type_noeud, cle)
            if existant is None:
                raise
            return existant
        return Noeud(ident, type_noeud, cle, libelle_propre, quand)

    # -- arêtes ------------------------------------------------------------------------------------------------------
    _COLONNES = (
        ARETES_T.c.arete_id,
        ARETES_T.c.type,
        ARETES_T.c.valide_de,
        ARETES_T.c.sensible,
        ARETES_T.c.origine,
        ARETES_T.c.source_type,
        ARETES_T.c.source_ref,
        ARETES_T.c.confiance,
        ARETES_T.c.de_noeud,
        ARETES_T.c.vers_noeud,
    )

    def _etat_courant(self, arete_id: str) -> dict[str, Any] | None:
        ligne = (
            self._cnx.execute(
                select(ETATS_T).where(ETATS_T.c.arete_id == arete_id).order_by(ETATS_T.c.id.desc()).limit(1)
            )
            .mappings()
            .first()
        )
        return dict(ligne) if ligne else None

    def _construire(self, ligne: Mapping[str, Any], etat: str, valide_a: str | None, cache: dict[str, Noeud]) -> Arete:
        def noeud(ident: str) -> Noeud:
            if ident not in cache:
                cache[ident] = self._noeud_par_id(ident)
            return cache[ident]

        return Arete(
            ligne["arete_id"],
            ligne["type"],
            noeud(ligne["de_noeud"]),
            noeud(ligne["vers_noeud"]),
            ligne["valide_de"],
            valide_a,
            etat,
            bool(ligne["sensible"]),
            ligne["origine"],
            ligne["source_type"],
            ligne["source_ref"],
            ligne["confiance"],
        )

    def arete(self, arete_id: str) -> Arete | None:
        ligne = self._cnx.execute(select(*self._COLONNES).where(ARETES_T.c.arete_id == arete_id)).mappings().first()
        if ligne is None:
            return None
        courant = self._etat_courant(arete_id)
        valide_a = self._valide_a(arete_id)
        return self._construire(ligne, courant["etat"] if courant else "brouillon", valide_a, {})

    def _valide_a(self, arete_id: str) -> str | None:
        return self._cnx.execute(
            select(ETATS_T.c.valide_a).where(ETATS_T.c.arete_id == arete_id, ETATS_T.c.etat == "fermee")
        ).scalar_one_or_none()

    def _ajouter_etat(
        self,
        arete_id: str,
        nouvel_etat: str,
        *,
        attendu: str | None,
        par: str,
        mode: str,
        role: str | None,
        raison: str | None,
        quand: str,
        valide_a: str | None = None,
    ) -> None:
        """INSERT conditionnel : n'écrit que si l'état courant est encore `attendu` ET que la transition est permise."""
        regles.exiger_transition(attendu, nouvel_etat)
        valeurs = {
            "arete_id": arete_id,
            "etat": nouvel_etat,
            "quand": quand,
            "par": par,
            "mode": mode,
            "role": role,
            "raison": raison,
            "valide_a": valide_a,
        }
        if attendu is None:
            if self._etat_courant(arete_id) is not None:
                raise ErreurMnemo(codes.ARETE_TRANSITION, "cette arête a déjà un état")
            self._cnx.execute(insert(ETATS_T).values(**valeurs))
            return
        courant = (
            select(ETATS_T.c.etat)
            .where(ETATS_T.c.arete_id == arete_id)
            .order_by(ETATS_T.c.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        colonnes = list(valeurs)
        sel = select(*(literal(valeurs[c]) for c in colonnes)).where(courant == bindparam("attendu", attendu))
        # RETURNING plutôt que `rowcount` : sur PostgreSQL (psycopg), `rowcount` d'un INSERT … SELECT vaut -1.
        ecrit = self._cnx.execute(insert(ETATS_T).from_select(colonnes, sel).returning(ETATS_T.c.id)).first()
        if ecrit is None:
            raise ErreurMnemo(
                codes.ARETE_TRANSITION, f"l'état courant n'est plus « {attendu} » : {nouvel_etat} non appliqué"
            )

    def proposer_arete(self, demande: DemandeArete, *, par: str, quand: str) -> Proposition:
        sensible = schema.verifier_arete(demande.type, demande.de.type, demande.vers.type)
        valide_de = schema.exiger_date(demande.valide_de, "valide_de")
        schema.exiger_source_ref(demande.source_ref)
        if demande.origine not in schema.ORIGINES or demande.confiance not in schema.CONFIANCES:
            raise ErreurMnemo(codes.ENTREE_INVALIDE, "origine ou confiance hors du schéma")
        if not isinstance(demande.source_type, str) or not 3 <= len(demande.source_type) <= 40:
            raise ErreurMnemo(codes.ENTREE_INVALIDE, "source_type : 3 à 40 caractères")
        if demande.de == demande.vers:
            raise ErreurMnemo(codes.ARETE_NON_AUTORISEE, "une arête ne relie pas un nœud à lui-même")
        de = self.poser_noeud(
            demande.de.type, demande.de.cle, demande.de_libelle, source_ref=demande.source_ref, par=par, quand=quand
        )
        vers = self.poser_noeud(
            demande.vers.type,
            demande.vers.cle,
            demande.vers_libelle,
            source_ref=demande.source_ref,
            par=par,
            quand=quand,
        )
        ident = schema.arete_id(demande.type, de.noeud_id, vers.noeud_id, valide_de)
        existante = self.arete(ident)
        if existante is not None:
            return Proposition(existante, False)
        if self._cnx.execute(select(ARETES_T.c.arete_id).limit(1).offset(_PLAFOND_ARETES - 1)).first() is not None:
            raise ErreurMnemo(codes.PLAFOND, f"plus de {_PLAFOND_ARETES} arêtes : archiver avant d'en ajouter")
        self._cnx.execute(
            insert(ARETES_T).values(
                arete_id=ident,
                type=demande.type,
                de_noeud=de.noeud_id,
                vers_noeud=vers.noeud_id,
                valide_de=valide_de,
                sensible=sensible,
                origine=demande.origine,
                source_type=demande.source_type,
                source_ref=demande.source_ref,
                confiance=demande.confiance,
                cree_le=quand,
                cree_par=par,
            )
        )
        mode = {"bus": "systeme", "systeme": "systeme", "agent": "agent", "humain": "humain"}[demande.origine]
        self._ajouter_etat(
            ident, "brouillon", attendu=None, par=par, mode=mode, role=None, raison="proposition", quand=quand
        )
        return Proposition(
            Arete(
                ident,
                demande.type,
                de,
                vers,
                valide_de,
                None,
                "brouillon",
                sensible,
                demande.origine,
                demande.source_type,
                demande.source_ref,
                demande.confiance,
            ),
            True,
        )

    def _exiger(self, arete_id: str) -> Arete:
        arete = self.arete(arete_id)
        if arete is None:
            raise ErreurMnemo(codes.ARETE_INCONNUE, "arête introuvable")
        return arete

    def confirmer_arete(
        self, arete_id: str, *, par: str, mode: str, role: str | None, raison: str | None, quand: str
    ) -> Arete:
        arete = self._exiger(arete_id)
        if arete.sensible and mode != "humain":
            raise ErreurMnemo(
                codes.HUMAIN_REQUIS, "une arête sensible (donnée personnelle) se confirme par une personne"
            )
        self._ajouter_etat(
            arete_id, "confirmee", attendu=arete.etat, par=par, mode=mode, role=role, raison=raison, quand=quand
        )
        return self._exiger(arete_id)

    def rejeter_arete(self, arete_id: str, *, par: str, mode: str, role: str | None, raison: str, quand: str) -> Arete:
        arete = self._exiger(arete_id)
        self._ajouter_etat(
            arete_id, "rejetee", attendu=arete.etat, par=par, mode=mode, role=role, raison=raison, quand=quand
        )
        return self._exiger(arete_id)

    def fermer_arete(
        self, arete_id: str, valide_a: str, *, par: str, mode: str, role: str | None, raison: str, quand: str
    ) -> Arete:
        arete = self._exiger(arete_id)
        valide_a = schema.exiger_date(valide_a, "valide_a")
        if valide_a <= arete.valide_de:
            raise ErreurMnemo(codes.ENTREE_INVALIDE, "valide_a doit suivre valide_de")
        self._ajouter_etat(
            arete_id,
            "fermee",
            attendu=arete.etat,
            par=par,
            mode=mode,
            role=role,
            raison=raison,
            quand=quand,
            valide_a=valide_a,
        )
        return self._exiger(arete_id)

    # -- lectures bornées --------------------------------------------------------------------------------------------
    def _incidentes(self, ids: Sequence[str], date: str, inclure_brouillons: bool) -> list[Arete]:
        """Les arêtes vivantes à `date` qui touchent l'un des nœuds `ids` : UNE lecture par lot d'identifiants."""
        dernier = (
            select(ETATS_T.c.id)
            .where(ETATS_T.c.arete_id == ARETES_T.c.arete_id)
            .order_by(ETATS_T.c.id.desc())
            .limit(1)
            .correlate(ARETES_T)
            .scalar_subquery()
        )
        etats = ("brouillon", "confirmee", "fermee") if inclure_brouillons else ("confirmee", "fermee")
        trouvees: dict[str, Arete] = {}
        cache: dict[str, Noeud] = {}
        for debut in range(0, len(ids), _LOT):
            lot = list(ids[debut : debut + _LOT])
            requete = (
                select(*self._COLONNES, ETATS_T.c.etat.label("etat"), ETATS_T.c.valide_a.label("valide_a_etat"))
                .join(ETATS_T, ETATS_T.c.id == dernier)
                .where(
                    (ARETES_T.c.de_noeud.in_(lot)) | (ARETES_T.c.vers_noeud.in_(lot)),
                    ETATS_T.c.etat.in_(etats),
                    ARETES_T.c.valide_de <= date,
                )
            )
            for ligne in self._cnx.execute(requete).mappings():
                valide_a = ligne["valide_a_etat"]
                if not regles.vivante(
                    ligne["etat"], ligne["valide_de"], valide_a, date, inclure_brouillons=inclure_brouillons
                ):
                    continue
                trouvees[ligne["arete_id"]] = self._construire(ligne, ligne["etat"], valide_a, cache)
        return list(trouvees.values())

    def voisinage(
        self,
        depart: NoeudRef,
        k: int,
        *,
        a_la_date: str,
        types_arete: Sequence[str] | None = None,
        inclure_brouillons: bool = False,
        noeuds_max: int = NOEUDS_MAX,
    ) -> Voisinage:
        regles.exiger_k(k)
        a_la_date = schema.exiger_date(a_la_date, "a_la_date")
        noeud = self.noeud(depart.type, depart.cle)
        if noeud is None:
            raise ErreurMnemo(codes.NOEUD_INCONNU, "nœud introuvable")
        noeuds, aretes, tronque = regles.parcourir(
            noeud,
            k,
            lambda ids: self._incidentes(ids, a_la_date, inclure_brouillons),
            types_arete=types_arete,
            noeuds_max=noeuds_max,
        )
        return Voisinage(noeud, k, a_la_date, noeuds, aretes, tronque)

    def chemin(
        self, de: NoeudRef, vers: NoeudRef, *, a_la_date: str, k_max: int = K_MAX, inclure_brouillons: bool = False
    ) -> Chemin | None:
        a_la_date = schema.exiger_date(a_la_date, "a_la_date")
        n_de, n_vers = self.noeud(de.type, de.cle), self.noeud(vers.type, vers.cle)
        if n_de is None or n_vers is None:
            raise ErreurMnemo(codes.NOEUD_INCONNU, "un des deux nœuds est introuvable")
        return regles.plus_court_chemin(
            n_de, n_vers, k_max, lambda ids: self._incidentes(ids, a_la_date, inclure_brouillons)
        )

    def pourquoi(self, arete_id: str) -> dict[str, Any]:
        arete = self._exiger(arete_id)
        historique = [
            {
                "etat": r["etat"],
                "quand": r["quand"],
                "par": r["par"],
                "mode": r["mode"],
                "role": r["role"],
                "raison": r["raison"],
                "valide_a": r["valide_a"],
            }
            for r in self._cnx.execute(
                select(ETATS_T).where(ETATS_T.c.arete_id == arete_id).order_by(ETATS_T.c.id)
            ).mappings()
        ]
        return {
            "arete": arete.vers_json(),
            "historique": historique,
            "explication": regles.explication(arete, historique),
        }

    def en_attente(self, limite: int = 50) -> tuple[Arete, ...]:
        dernier = (
            select(ETATS_T.c.id)
            .where(ETATS_T.c.arete_id == ARETES_T.c.arete_id)
            .order_by(ETATS_T.c.id.desc())
            .limit(1)
            .correlate(ARETES_T)
            .scalar_subquery()
        )
        cache: dict[str, Noeud] = {}
        lignes = (
            self._cnx.execute(
                select(*self._COLONNES, ETATS_T.c.etat.label("etat"))
                .join(ETATS_T, ETATS_T.c.id == dernier)
                .where(ETATS_T.c.etat == "brouillon")
                .order_by(ARETES_T.c.sensible.desc(), ARETES_T.c.arete_id)
                .limit(max(1, min(limite, 200)))
            )
            .mappings()
            .all()
        )
        return tuple(self._construire(ligne, "brouillon", None, cache) for ligne in lignes)

    def etat(self) -> Mapping[str, Any]:
        dernier = (
            select(ETATS_T.c.id)
            .where(ETATS_T.c.arete_id == ARETES_T.c.arete_id)
            .order_by(ETATS_T.c.id.desc())
            .limit(1)
            .correlate(ARETES_T)
            .scalar_subquery()
        )
        par_etat: dict[str, int] = {e: 0 for e in schema.ETATS}
        sensibles_en_attente = 0
        for etat, sensible in self._cnx.execute(
            select(ETATS_T.c.etat, ARETES_T.c.sensible).select_from(ARETES_T).join(ETATS_T, ETATS_T.c.id == dernier)
        ):
            par_etat[etat] += 1
            if etat == "brouillon" and sensible:
                sensibles_en_attente += 1
        par_type: dict[str, int] = {t: 0 for t in schema.TYPES_NOEUD}
        for type_noeud in self._cnx.execute(select(NOEUDS_T.c.type)).scalars():
            par_type[type_noeud] += 1
        orphelines = (
            self._cnx.execute(
                select(ARETES_T.c.arete_id)
                .outerjoin(ETATS_T, ETATS_T.c.arete_id == ARETES_T.c.arete_id)
                .where(ETATS_T.c.id.is_(None))
            )
            .scalars()
            .all()
        )
        return {
            "noeuds_par_type": par_type,
            "aretes_par_etat": par_etat,
            "aretes_sensibles_en_attente": sensibles_en_attente,
            "aretes_sans_etat": len(orphelines),
            "moteur": "sql-natif",
        }
