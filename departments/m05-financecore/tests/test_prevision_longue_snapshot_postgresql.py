"""Le calcul public long garde les registres et métadonnées d'un même SELECT PostgreSQL."""
from __future__ import annotations

import importlib
import threading
from pathlib import Path

import pytest
from doubles import postgres_ephemere, raison_sans_docker
from sqlalchemy import select, update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

H = "2026-09-30T17:00:00-04:00"
MONTANT = "689.85"
ATTESTATION = {"nom": "CPA fictif", "profession": "CPA", "reference_document": "DEPOT-LONG-FICTIF"}
CONFIGURATION = {
    "prevision_longue": {
        "mois_historique": 6,
        "scenarios": [{
            "nom": "base", "croissance_revenus_mensuelle": "0", "croissance_charges_mensuelle": "0",
            "saisonnalite": ["1"] * 12, "delai_encaissement_jours": 0, "delai_paiement_jours": 0,
        }],
    },
}


@pytest.fixture
def postgres_long(monkeypatch):
    with postgres_ephemere() as url:
        monkeypatch.setenv(stockage.ENV_URL, url)
        yield url
        stockage.liberer(url)


@pytest.mark.skipif(raison_sans_docker() is not None, reason=str(raison_sans_docker()))
def test_prevision_longue_conserve_sources_et_refuse_chaine_corrompue(postgres_long, monkeypatch):
    url = postgres_long
    from m5_financecore import grand_livre
    from m5_financecore import outils as m5

    from opsys import approbations, identite
    from opsys.capacites import Capacites, outils_executables
    from opsys.departements import lire_manifeste
    from opsys.outils import executer_atomique

    moteur_module = importlib.import_module("opsys.stockage.moteur")
    monkeypatch.setattr(m5, "_configuration_manifeste", lambda: CONFIGURATION)
    monkeypatch.setattr(m5, "_stockage_durable_actif", True)
    stockage.migrer(url)
    m5.utiliser_stockage_durable()
    with stockage.transaction(url) as cnx:
        identite.creer_personne(cnx, "owner.long.fictif", "Propriétaire fictif", "password-long-fictif-123",
                                ["nathan_owner"])
    # Six écritures historiques fictives, proposées/validées par les vrais builders du grand livre.
    plan, refus_plan = m5._plan_comptable_effectif()
    assert refus_plan is None and plan is not None, refus_plan
    with stockage.transaction(url):
        registre_gl = m5._registre_grand_livre()
        assert registre_gl is not None
        for mois in ("2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"):
            proposition, refus = grand_livre.proposer_ecriture(
                registre_gl, plan,
                cle_piece=f"fictif:historique:{mois}",
                piece={"type": "manuelle", "reference": f"historique-{mois}"},
                nature="saisie", date_effet=f"{mois}-15", libelle=f"Historique fictif {mois}",
                lignes_brutes=[
                    {"compte": "1010", "debit": "1000.00", "credit": None},
                    {"compte": "4100", "debit": None, "credit": "1000.00"},
                    {"compte": "5100", "debit": "800.00", "credit": None},
                    {"compte": "1010", "debit": None, "credit": "800.00"},
                ], horodatage=H, origine="saisie",
            )
            assert refus is None and proposition is not None, refus
            validation, refus = grand_livre.valider_ecriture(
                registre_gl, plan, ecriture_id=proposition["ecriture"]["ecriture_id"],
                humain={"par": "CPA fictif", "role": "finance", "voie": "console"}, horodatage=H,
            )
            assert refus is None and validation is not None, refus
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    deps = {"m05-financecore": dep}
    outils = {outil.nom: outil for outil in m5.outils()}
    capacites = Capacites(deps, stockage.transaction)
    disponibles = outils_executables(deps, stockage.transaction)

    def approuver_mouvement(montant: str, source: str) -> None:
        demande = capacites.appeler("m5_enregistrer_mouvement", {
            "montant": montant, "type_mouvement": "ENCAISSEMENT", "horodatage": H,
            "classe_retention": "STANDARD", "source": source,
        })
        assert demande["statut"] == "en_attente_approbation", demande
        with stockage.transaction(url) as cnx:
            decision = approbations.decider(
                cnx, demande["demande_id"], True, "owner.long.fictif", disponibles, deps,
                attestation=ATTESTATION,
            )
        assert decision["statut"] == "executee", decision
        assert decision["reponse"]["resultat"]["accepte"] is True, decision

    def approuver_budget() -> None:
        demande = capacites.appeler("m5_etablir_budget", {
            "libelle": "Budget fictif concurrent",
            "lignes": [
                {"compte": "4100", "mois": "2026-10", "montant": "1200.00"},
                {"compte": "5100", "mois": "2026-10", "montant": "900.00"},
            ],
            "motif": None, "version_attendue": 0, "horodatage": H,
        })
        assert demande["statut"] == "en_attente_approbation", demande
        with stockage.transaction(url) as cnx:
            decision = approbations.decider(
                cnx, demande["demande_id"], True, "owner.long.fictif", disponibles, deps,
            )
        assert decision["statut"] == "executee", decision
        assert decision["reponse"]["resultat"]["accepte"] is True, decision

    approuver_mouvement("10000.00", "solde initial fictif")
    reached = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    stale_result: dict = {}
    blocked = False
    original_snapshot = stockage.lire_instantane_maillons

    def synchronized_snapshot(departement, registres):
        nonlocal blocked
        resultat = original_snapshot(departement, registres)
        if departement == "m05-financecore" and not blocked:
            blocked = True
            reached.set()
            if not release.wait(30):
                raise TimeoutError("writer approval did not finish")
        return resultat

    def reader() -> None:
        try:
            with stockage.transaction(url) as cnx:
                token = moteur_module._CONNEXION.set(cnx)
                try:
                    stale_result.update(executer_atomique(outils["m5_prevoir_tresorerie_longue"], {
                        "aujourd_hui": "2026-09-29", "horizon_mois": 6, "scenario": "base",
                    }))
                finally:
                    moteur_module._CONNEXION.reset(token)
        except BaseException as exc:
            errors.append(exc)

    def writer() -> None:
        try:
            if not reached.wait(30):
                raise TimeoutError("long forecast did not read its register set")
            approuver_mouvement(MONTANT, "encaissement concurrent fictif")
            approuver_budget()
        except BaseException as exc:
            errors.append(exc)
        finally:
            release.set()

    monkeypatch.setattr(stockage, "lire_instantane_maillons", synchronized_snapshot)
    t_reader = threading.Thread(target=reader, daemon=True)
    t_writer = threading.Thread(target=writer, daemon=True)
    t_reader.start()
    t_writer.start()
    t_reader.join(60)
    t_writer.join(60)
    assert not t_reader.is_alive() and not t_writer.is_alive(), "thread timeout"
    assert not errors, errors

    with stockage.transaction(url):
        final_result = executer_atomique(outils["m5_prevoir_tresorerie_longue"], {
            "aujourd_hui": "2026-09-29", "horizon_mois": 6, "scenario": "base",
        })
    assert stale_result["ok"] and stale_result["resultat"]["accepte"] is True, stale_result
    assert final_result["ok"] and final_result["resultat"]["accepte"] is True, final_result
    stale = stale_result["resultat"]["resultat"]
    final = final_result["resultat"]["resultat"]
    source_stale = next(item for item in stale["sources"] if item["registre"] == "mouvements")
    source_final = next(item for item in final["sources"] if item["registre"] == "mouvements")
    budget_stale = next(item for item in stale["sources"] if item["registre"] == "budgets_declares")
    budget_final = next(item for item in final["sources"] if item["registre"] == "budgets_declares")
    assert stale["solde_initial"] == "10000.00"
    assert source_stale["taille"] == 1 and budget_stale["taille"] == 0
    assert final["solde_initial"] == "10689.85"
    assert source_final["taille"] == 2 and budget_final["taille"] == 1
    assert source_stale["tete"] != source_final["tete"]
    assert "tete" not in budget_stale and isinstance(budget_final.get("tete"), str)
    assert stale["couverture"]["mois_budget"] == []
    assert final["couverture"]["mois_budget"] == ["2026-10"]

    # Un snapshot cohérent ne remplace pas la validation de chaîne : altérer un maillon doit rester un refus.
    filtre = (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == "principal")
    with stockage.transaction(url) as cnx:
        rang, texte = cnx.execute(
            select(REGISTRES.c.rang, REGISTRES.c.maillon).where(filtre)
            .order_by(REGISTRES.c.rang.desc()).limit(1)
        ).one()
        valeur = codec.decoder(texte)
        valeur["fictif_corrompu"] = True
        cnx.execute(update(REGISTRES).where(filtre & (REGISTRES.c.rang == rang))
                    .values(maillon=codec.encoder(valeur)))
    with stockage.transaction(url):
        corrompu = executer_atomique(outils["m5_prevoir_tresorerie_longue"], {
            "aujourd_hui": "2026-09-29", "horizon_mois": 6, "scenario": "base",
        })
    assert corrompu["ok"] is True and corrompu["resultat"]["accepte"] is False, corrompu
    assert corrompu["resultat"]["verdict"]["code"] == "REJ-PREVISION-LONGUE-CHAINE-INVALIDE"
