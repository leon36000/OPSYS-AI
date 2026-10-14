"""M9 : une lecture doit utiliser la révision dont la chaîne a été validée.

Contre-test réel PostgreSQL 17, opt-in dans le job frontiere-postgresql. Les
connexions, maillons et valeurs sont fictifs ; aucun service d'entreprise.
"""
from __future__ import annotations

import os
import threading

import psycopg
import pytest
from m9_strategic_intelligence import outils, registre
from memoire.doubles import postgres_ephemere

from opsys import stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES


@pytest.mark.skipif(
    os.environ.get("OPSYS_QUALIFIER_M9_PG17") != "1",
    reason="PostgreSQL 17 réel réservé au job frontiere-postgresql explicite",
)
@pytest.mark.parametrize("nom,arguments", [
    ("m9_lire_etat_consolide", {}),
    ("m9_produire_briefing_matin", {"maintenant": "2026-01-05T07:00:00Z"}),
    ("m9_lire_suite_briefing", {
        "maintenant": "2026-01-05T07:00:00Z", "section": "faits_veille",
    }),
])
def test_lecture_utilise_seulement_la_revision_validee(nom, arguments, monkeypatch):
    with postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url.replace("postgresql://", "postgresql+psycopg://", 1))
        stockage.migrer()
        natifs = {o.nom: o for o in outils.outils()}
        seed = executer_atomique(natifs["m9_etat_consolide"], {"snapshot": {
            "module_source": "source-declaree-fictive",
            "horodatage": "2026-01-04T12:00:00Z",
            "valeurs": {"prevision": "100.00"},
        }})
        assert seed["ok"] and seed["resultat"]["accepte"]
        initial = executer_atomique(natifs[nom], arguments)
        assert initial["ok"] and "100.00" in str(initial)

        validation_finie = threading.Event()
        reprendre = threading.Event()
        reponses = {}
        originale = registre.RegistreSnapshots.valider_chaine

        def valider_et_pauser(self):
            resultat = originale(self)
            assert resultat == (True, "")
            connexion = stockage.connexion_courante()
            assert connexion is not None
            reponses["isolation"] = connexion.get_isolation_level()
            validation_finie.set()
            assert reprendre.wait(10), "coordination fictive non libérée"
            assert stockage.connexion_courante() is connexion
            return resultat

        def lire():
            try:
                reponses["resultat"] = executer_atomique(natifs[nom], arguments)
            except BaseException as exc:
                reponses["exception"] = type(exc).__name__

        # Le point de pause observe la frontière ; il ne remplace ni la chaîne,
        # ni le propriétaire, ni la connexion/transaction de l'exécuteur.
        monkeypatch.setattr(registre.RegistreSnapshots, "valider_chaine", valider_et_pauser)
        lecteur = threading.Thread(target=lire, name="m9-lecture-fictive")
        try:
            with psycopg.connect(url, autocommit=True) as ecrivain:
                ecrivain.execute("SET statement_timeout = '3s'")
                ecrivain.execute("SET lock_timeout = '200ms'")
                filtre = ("m09-strategic-intelligence", "snapshots")
                selection = f'SELECT maillon FROM "{REGISTRES.name}" WHERE departement=%s AND registre=%s AND rang=0'
                brut = ecrivain.execute(selection, filtre).fetchone()[0]
                altere = codec.decoder(brut)
                altere["valeurs"]["prevision"] = "900.00"
                charge = codec.encoder(altere)
                lecteur.start()
                try:
                    assert validation_finie.wait(10), "validation native non atteinte"
                    commande = (
                        f'UPDATE "{REGISTRES.name}" SET maillon=%s '
                        'WHERE departement=%s AND registre=%s AND rang=0'
                    )
                    try:
                        ecrivain.execute(commande, (charge, *filtre))
                        commis = True
                    except psycopg.errors.LockNotAvailable:
                        commis = False
                    attendu = charge if commis else brut
                    assert ecrivain.execute(selection, filtre).fetchone()[0] == attendu
                finally:
                    reprendre.set()
                    lecteur.join(10)
                assert not lecteur.is_alive()
                assert "exception" not in reponses
                resultat = reponses["resultat"]
                assert "900.00" not in str(resultat), "révision corrompue non validée divulguée"
                if resultat["ok"]:
                    assert "100.00" in str(resultat)
                else:
                    assert resultat["erreur"] == "refus_metier"
                    assert resultat["details"].startswith("REJ-SNAPSHOT-CHAINE-INVALIDE")
                if not commis:
                    ecrivain.execute(commande, (charge, *filtre))
                monkeypatch.setattr(registre.RegistreSnapshots, "valider_chaine", originale)
                suivant = executer_atomique(natifs[nom], arguments)
                assert suivant["ok"] is False and suivant["erreur"] == "refus_metier"
                assert suivant["details"].startswith("REJ-SNAPSHOT-CHAINE-INVALIDE")
                assert "900.00" not in str(suivant)
                assert ecrivain.execute(selection, filtre).fetchone()[0] == charge
        finally:
            reprendre.set()
            if lecteur.ident is not None:
                lecteur.join(10)
            monkeypatch.setattr(registre.RegistreSnapshots, "valider_chaine", originale)
            stockage.liberer()
