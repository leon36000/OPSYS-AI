"""Double en mémoire du port `MoteurGraphe` : mêmes règles (`schema`, `regles`), listes Python au lieu de tables.

Sert aux tests des appelants (alimentation, outils) sans base, et de seconde implémentation pour le test de parité qui
garantit que le filtre SQL « arête vivante à cette date » donne les mêmes arêtes que `regles.vivante`. Ce n'est PAS un
moteur de production : rien n'y est durable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .. import codes
from ..codes import ErreurMnemo
from . import regles, schema
from .port import K_MAX, NOEUDS_MAX, Arete, Chemin, DemandeArete, Noeud, Proposition, Voisinage
from .schema import NoeudRef


class GrapheMemoire:
    def __init__(self) -> None:
        self._noeuds: dict[str, Noeud] = {}
        self._aretes: dict[str, dict[str, Any]] = {}
        self._etats: dict[str, list[dict[str, Any]]] = {}

    def noeud(self, type_noeud: str, cle: str) -> Noeud | None:
        return self._noeuds.get(schema.noeud_id(type_noeud, cle))

    def poser_noeud(
        self, type_noeud: str, cle: str, libelle: str | None, *, source_ref: str, par: str, quand: str
    ) -> Noeud:
        type_noeud, cle, libelle_propre = schema.valider_noeud(type_noeud, cle, libelle)
        schema.exiger_source_ref(source_ref)
        ident = schema.noeud_id(type_noeud, cle)
        if ident not in self._noeuds:
            self._noeuds[ident] = Noeud(ident, type_noeud, cle, libelle_propre, quand)
        return self._noeuds[ident]

    def _vue(self, ident: str) -> Arete:
        brut = self._aretes[ident]
        evenements = self._etats[ident]
        valide_a = next((e["valide_a"] for e in evenements if e["etat"] == "fermee"), None)
        return Arete(
            ident,
            brut["type"],
            self._noeuds[brut["de"]],
            self._noeuds[brut["vers"]],
            brut["valide_de"],
            valide_a,
            evenements[-1]["etat"],
            brut["sensible"],
            brut["origine"],
            brut["source_type"],
            brut["source_ref"],
            brut["confiance"],
        )

    def arete(self, arete_id: str) -> Arete | None:
        return self._vue(arete_id) if arete_id in self._aretes else None

    def _exiger(self, arete_id: str) -> Arete:
        arete = self.arete(arete_id)
        if arete is None:
            raise ErreurMnemo(codes.ARETE_INCONNUE, "arête introuvable")
        return arete

    def _etat(
        self,
        ident: str,
        etat: str,
        *,
        par: str,
        mode: str,
        role: str | None,
        raison: str | None,
        quand: str,
        valide_a: str | None = None,
    ) -> None:
        courant = self._etats[ident][-1]["etat"] if self._etats.get(ident) else None
        regles.exiger_transition(courant, etat)
        self._etats.setdefault(ident, []).append(
            {
                "etat": etat,
                "quand": quand,
                "par": par,
                "mode": mode,
                "role": role,
                "raison": raison,
                "valide_a": valide_a,
            }
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
        if ident in self._aretes:
            return Proposition(self._vue(ident), False)
        self._aretes[ident] = {
            "type": demande.type,
            "de": de.noeud_id,
            "vers": vers.noeud_id,
            "valide_de": valide_de,
            "sensible": sensible,
            "origine": demande.origine,
            "source_type": demande.source_type,
            "source_ref": demande.source_ref,
            "confiance": demande.confiance,
        }
        mode = {"bus": "systeme", "systeme": "systeme", "agent": "agent", "humain": "humain"}[demande.origine]
        self._etat(ident, "brouillon", par=par, mode=mode, role=None, raison="proposition", quand=quand)
        return Proposition(self._vue(ident), True)

    def confirmer_arete(
        self, arete_id: str, *, par: str, mode: str, role: str | None, raison: str | None, quand: str
    ) -> Arete:
        arete = self._exiger(arete_id)
        if arete.sensible and mode != "humain":
            raise ErreurMnemo(
                codes.HUMAIN_REQUIS, "une arête sensible (donnée personnelle) se confirme par une personne"
            )
        self._etat(arete_id, "confirmee", par=par, mode=mode, role=role, raison=raison, quand=quand)
        return self._vue(arete_id)

    def rejeter_arete(self, arete_id: str, *, par: str, mode: str, role: str | None, raison: str, quand: str) -> Arete:
        self._exiger(arete_id)
        self._etat(arete_id, "rejetee", par=par, mode=mode, role=role, raison=raison, quand=quand)
        return self._vue(arete_id)

    def fermer_arete(
        self, arete_id: str, valide_a: str, *, par: str, mode: str, role: str | None, raison: str, quand: str
    ) -> Arete:
        arete = self._exiger(arete_id)
        valide_a = schema.exiger_date(valide_a, "valide_a")
        if valide_a <= arete.valide_de:
            raise ErreurMnemo(codes.ENTREE_INVALIDE, "valide_a doit suivre valide_de")
        self._etat(arete_id, "fermee", par=par, mode=mode, role=role, raison=raison, quand=quand, valide_a=valide_a)
        return self._vue(arete_id)

    def _incidentes(self, ids: Sequence[str], date: str, inclure_brouillons: bool) -> list[Arete]:
        voulus = set(ids)
        sortie = []
        for ident, brut in self._aretes.items():
            if brut["de"] not in voulus and brut["vers"] not in voulus:
                continue
            vue = self._vue(ident)
            if regles.vivante(vue.etat, vue.valide_de, vue.valide_a, date, inclure_brouillons=inclure_brouillons):
                sortie.append(vue)
        return sortie

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
        historique = [dict(e) for e in self._etats[arete_id]]
        return {
            "arete": arete.vers_json(),
            "historique": historique,
            "explication": regles.explication(arete, historique),
        }

    def en_attente(self, limite: int = 50) -> tuple[Arete, ...]:
        vues = [self._vue(i) for i in self._aretes if self._etats[i][-1]["etat"] == "brouillon"]
        vues.sort(key=lambda a: (not a.sensible, a.arete_id))
        return tuple(vues[: max(1, min(limite, 200))])

    def etat(self) -> Mapping[str, Any]:
        par_etat = {e: 0 for e in schema.ETATS}
        sensibles = 0
        for ident in self._aretes:
            etat = self._etats[ident][-1]["etat"]
            par_etat[etat] += 1
            if etat == "brouillon" and self._aretes[ident]["sensible"]:
                sensibles += 1
        par_type = {t: 0 for t in schema.TYPES_NOEUD}
        for n in self._noeuds.values():
            par_type[n.type] += 1
        return {
            "noeuds_par_type": par_type,
            "aretes_par_etat": par_etat,
            "aretes_sensibles_en_attente": sensibles,
            "aretes_sans_etat": 0,
            "moteur": "memoire",
        }
