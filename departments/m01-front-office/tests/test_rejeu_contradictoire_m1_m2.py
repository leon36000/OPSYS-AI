"""Rejeu M1 durable: même signal identique idempotent, contenu divergent explicitement refusé."""
from __future__ import annotations

import pytest
from m1_front_office import outils as m1
from m2_revenue_crm import outils as m2
from sqlalchemy import func, select

from opsys import evenements, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_SORTANTS

SMS = {
    "canal": "sms",
    "expediteur": "+15145550142",
    "message_id": "SMfictif-rejeu-20261001",
    "recu_le": "2026-09-29T09:15:00-04:00",
    "texte": "Bonjour, mes gouttières fuient à Laval.",
}
INSTANT = "2026-09-29T10:00:00-04:00"


@pytest.fixture
def parcours(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys-rejeu.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    m1.utiliser_stockage_durable()
    m2.utiliser_stockage_durable()
    deps = charger_departements()
    yield url, deps
    m1.reinitialiser_registre()
    m2.reinitialiser_registre()
    stockage.liberer()


def _capacites(deps):
    return Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)


def _m1_lignes():
    with stockage.transaction():
        return m1._obtenir_registre().lire()


def _m2_lignes():
    with stockage.transaction():
        return list(stockage.maillons("m02-revenue-crm", "principal"))


def _compte_evenements():
    with stockage.transaction() as cnx:
        return cnx.execute(
            select(func.count()).select_from(EVENEMENTS_SORTANTS).where(
                EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie"
            )
        ).scalar_one()


def _compte_leads_m2():
    return sum(ligne.get("type_entree") == "lead_ingere" for ligne in _m2_lignes())


def test_rejeu_identique_apres_reinitialisation_persiste_une_seule_fois_et_atteint_m2(parcours):
    _, deps = parcours
    premier = _capacites(deps).appeler("m1_recevoir_message_canal", SMS)
    assert premier["ok"] is True, premier
    assert premier["resultat"]["decision"] == "TRANSMETTRE_M2"
    assert len(_m1_lignes()) == 2 and _compte_evenements() == 1

    # Recrée les adaptateurs de registre/capacités sur la même base pour simuler la reprise après arrêt.
    stockage.liberer()
    stockage.migrer()
    m1.utiliser_stockage_durable()
    m2.utiliser_stockage_durable()
    rejoue = _capacites(deps).appeler("m1_recevoir_message_canal", dict(SMS))
    assert rejoue["ok"] is True and rejoue["resultat"]["doublon"] is True, rejoue
    assert len(_m1_lignes()) == 2 and _compte_evenements() == 1
    assert _compte_leads_m2() == 0, "M2 reste vide avant livraison du bus"

    resume = evenements.repartir(deps, maintenant=INSTANT)
    assert resume["echecs"] == resume["quarantaines"] == 0, resume
    assert _compte_leads_m2() == 1
    reprise_bus = evenements.repartir(deps, maintenant=INSTANT)
    assert reprise_bus["echecs"] == reprise_bus["quarantaines"] == 0
    assert _compte_leads_m2() == 1, "la reprise du bus ne crée pas de second lead M2"
    with stockage.transaction():
        assert m1._obtenir_registre().valider_chaine() == (True, None)


@pytest.mark.parametrize(
    "modification",
    [
        {"texte": "Je suis très déçu : mes gouttières à Laval fuient encore après vos travaux."},
        {"expediteur": "+15145550143"},
    ],
    ids=["corps-divergent", "expediteur-divergent"],
)
def test_meme_id_avec_evenement_divergent_est_refuse_sans_nouvelle_ecriture(
    parcours, modification, declarer_plaintes
):
    _, deps = parcours
    declarer_plaintes()
    capacites = _capacites(deps)
    initial = capacites.appeler("m1_recevoir_message_canal", SMS)
    assert initial["ok"] is True, initial
    avant_lignes = _m1_lignes()
    avant_evenements = _compte_evenements()
    divergent = {**SMS, **modification}

    resultat = capacites.appeler("m1_recevoir_message_canal", divergent)
    assert resultat["ok"] is False and resultat["erreur"] == "refus_metier", resultat
    assert "REJ-SIGNAL-CONTRADICTOIRE" in resultat["details"]
    assert _m1_lignes() == avant_lignes
    assert not any(ligne.get("type_entree") == "transfert" for ligne in _m1_lignes())
    assert _compte_evenements() == avant_evenements == 1
    assert _compte_leads_m2() == 0
    with stockage.transaction():
        assert m1._obtenir_registre().valider_chaine() == (True, None)
