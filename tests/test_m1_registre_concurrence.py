from __future__ import annotations

import threading
from copy import deepcopy

import pytest
from m1_front_office.outils import outils
from m1_front_office.registre import Registre
from memoire.doubles import postgres_ephemere, raison_sans_docker

from opsys import stockage
from opsys.outils import executer_atomique
from opsys.stockage.maillons import EcritureConcurrente, MaillonsDurables

DEPARTEMENT = "m01-front-office"
REGISTRE = "principal"


def test_refus_de_rang_ne_mutile_pas_l_entree_fournie_par_l_appelant():
    class RefusAppend:
        def __len__(self):
            return 0

        def append_avec_rang_attendu(self, maillon, *, rang_attendu):
            assert rang_attendu == 0
            assert "ligne_id" in maillon and "precedent_ligne_id" in maillon
            raise EcritureConcurrente("rang modifié pendant la préparation")

    entree = {
        "type_entree": "transition_phase",
        "horodatage": "2026-11-03T12:00:00+00:00",
        "payload": {"signal_id": "signal-fictif", "phase_cible": 0},
    }
    avant = deepcopy(entree)
    with pytest.raises(EcritureConcurrente):
        Registre(maillons=RefusAppend()).ajouter(entree)
    assert entree == avant


def test_pg_ouvertures_publiques_concurrentes_preservent_la_chaine(monkeypatch):
    raison = raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)

    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.migrer(url)
        try:
            par_nom = {outil.nom: outil for outil in outils()}
            barriere = threading.Barrier(2)
            premier_termine = threading.Event()
            original = MaillonsDurables.append
            observations = []
            identifiants = ("signal-fictif-A", "signal-fictif-B")

            def aligner(self, maillon, *, rang_attendu=None):
                if (self.departement, self.registre) == (DEPARTEMENT, REGISTRE):
                    signal_id = maillon.get("payload", {}).get("signal_id")
                    if signal_id in identifiants:
                        observations.append(signal_id)
                        barriere.wait(30)
                        if signal_id == identifiants[1] and not premier_termine.wait(30):
                            raise TimeoutError("la première ouverture n'a pas terminé")
                return original(self, maillon, rang_attendu=rang_attendu)

            monkeypatch.setattr(MaillonsDurables, "append", aligner)
            resultats = {}
            erreurs = {}

            def ouvrir(index, signal_id):
                try:
                    resultats[index] = executer_atomique(par_nom["m1_ouvrir_conversation"], {
                        "signal_id": signal_id,
                        "horodatage": "2026-11-03T12:00:00+00:00",
                    })
                except BaseException as exc:
                    erreurs[index] = exc
                finally:
                    if index == 0:
                        premier_termine.set()

            threads = [threading.Thread(target=ouvrir, args=(i, ident)) for i, ident in enumerate(identifiants)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)
            assert all(not thread.is_alive() for thread in threads), "threads stalled"

            chaine = Registre(maillons=stockage.maillons(DEPARTEMENT, REGISTRE))
            valide, detail = chaine.valider_chaine()
            assert valide is True, detail
            assert sorted(observations) == sorted(identifiants)
            assert len(resultats) == 1, resultats
            assert len(erreurs) == 1, erreurs
            assert isinstance(next(iter(erreurs.values())), stockage.EcritureConcurrente), erreurs
            assert next(iter(resultats.values()))["ok"] is True
            assert chaine.taille() == 1
        finally:
            stockage.liberer(url)
