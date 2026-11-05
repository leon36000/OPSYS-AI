from __future__ import annotations

import threading

import pytest
from m2_revenue_crm import outils as outils_module
from m2_revenue_crm.outils import outils
from m2_revenue_crm.registre import Registre
from memoire.doubles import postgres_ephemere, raison_sans_docker

from opsys import stockage
from opsys.outils import executer_atomique
from opsys.stockage.maillons import MaillonsDurables

DEPARTEMENT = "m02-revenue-crm"
REGISTRE = "profils_propriete"
H = "2026-11-03T12:00:00+00:00"


def _contrat(lead_id: str, numero: str) -> dict:
    return {
        "lead_id": lead_id,
        "conversation_id": f"conversation-{lead_id}",
        "contact": {
            "nom": f"Client fictif {numero}",
            "telephone": f"418-555-01{numero}",
            "courriel": f"client-{numero}@example.test",
        },
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "telephone",
    }


def test_pg_propositions_publiques_sur_registre_non_principal_preservent_la_chaine(monkeypatch):
    raison = raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)

    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.migrer(url)
        try:
            monkeypatch.setattr(outils_module, "_stockage_durable_actif", True)
            par_nom = {outil.nom: outil for outil in outils()}
            for lead_id, numero in (("lead-race-a", "101"), ("lead-race-b", "102")):
                ingestion = executer_atomique(par_nom["m2_ingerer_lead"], {
                    "contrat": _contrat(lead_id, numero), "horodatage": H,
                })
                assert ingestion["ok"] and ingestion["resultat"]["accepte"], ingestion

            taille_avant = len(stockage.maillons(DEPARTEMENT, REGISTRE))
            barriere = threading.Barrier(2)
            premier_termine = threading.Event()
            courant = threading.local()
            original = MaillonsDurables.append
            observations = []

            def aligner(self, maillon, *, rang_attendu=None):
                if (self.departement, self.registre) == (DEPARTEMENT, REGISTRE):
                    cle = getattr(courant, "cle", None)
                    observations.append(cle)
                    barriere.wait(30)
                    if cle == 1 and not premier_termine.wait(30):
                        raise TimeoutError("la première proposition n'a pas terminé")
                return original(self, maillon, rang_attendu=rang_attendu)

            monkeypatch.setattr(MaillonsDurables, "append", aligner)
            resultats = {}
            erreurs = {}

            def proposer(cle, lead_id, suffixe):
                courant.cle = cle
                try:
                    resultats[cle] = executer_atomique(par_nom["m2_proposer_profil_propriete"], {
                        "lead_id": lead_id,
                        "revision_attendue": 0,
                        "champs": {
                            "adresse": {
                                "ligne": f"{10 + cle} rue Fictive", "ville": "Québec", "code_postal": "G1A 1A1",
                            },
                            "type_batiment": "unifamiliale",
                            "etages": 2,
                            "annee_construction": 1985,
                        },
                        "source": {"type": "constate_vendeur", "reference": f"visite-fictive-{suffixe}"},
                        "horodatage": H,
                    })
                except BaseException as exc:
                    erreurs[cle] = exc
                finally:
                    if cle == 0:
                        premier_termine.set()

            threads = [
                threading.Thread(target=proposer, args=(0, "lead-race-a", "a")),
                threading.Thread(target=proposer, args=(1, "lead-race-b", "b")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)
            assert all(not thread.is_alive() for thread in threads), "threads stalled"

            registre = Registre(maillons=stockage.maillons(DEPARTEMENT, REGISTRE))
            assert registre.valider_chaine() is True
            assert sorted(observations) == [0, 1]
            assert len(resultats) == 1, resultats
            assert len(erreurs) == 1, erreurs
            assert isinstance(next(iter(erreurs.values())), stockage.EcritureConcurrente), erreurs
            assert next(iter(resultats.values()))["ok"]
            assert next(iter(resultats.values()))["resultat"]["accepte"]
            assert registre.taille() == taille_avant + 1
        finally:
            stockage.liberer(url)
