"""Un retrait de consentement signale aussi le paquet exporté d'une révision depuis corrigée (Loi 25, M7.2/M7.3).

Le propriétaire a exporté un paquet (et l'a peut-être publié à la main), puis a corrigé le texte : une nouvelle
révision attend sa décision. Le client retire ensuite son consentement, par l'app admin ou par un STOP à M1. La
réponse doit lister l'ancien paquet déjà exporté parmi ce qui se retire à la main : M7 ne publie jamais, il le dit.
Les contenus bloqués restent les contenus courants. Données fictives.
"""

from __future__ import annotations

import pytest
from m7_marketing import outils
from m7_marketing.brand import profil_client
from m7_marketing.usine import service

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique

FICTIF = True
_OUTILS = {outil.nom: outil for outil in outils.outils()}
_HORODATAGE = "2026-09-30T10:00:00-04:00"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-test-1234", ["nathan_owner", "admin"])
    yield url
    stockage.liberer()


@pytest.fixture
def brand_configure(monkeypatch, profil):
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(profil), None))


def _valeur(nom, *, owner=False, **args):
    if owner:
        with contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin")):
            reponse = executer_atomique(_OUTILS[nom], args)
    else:
        reponse = executer_atomique(_OUTILS[nom], args)
    assert reponse["ok"], reponse
    resultat = reponse["resultat"]
    assert resultat.get("accepte", True), resultat
    return resultat.get("resultat", resultat)


def _lire(nom):
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def _exporter_puis_corriger(charge):
    """Facebook approuvé et exporté, puis corrigé par le propriétaire depuis la console : `(ancienne, nouvelle)`."""
    with stockage.transaction():
        stockage.maillons("m07-marketing", "wct_recus").append(charge)
    _valeur("m7_proposer_contenus_chantier", wct_id=charge["wct_id"])
    ancienne = next(p["contenu_id"] for p in _lire("contenus_chantier") if p["plateforme"] == "facebook")
    _valeur("m7_decider_contenu", owner=True, contenu_id=ancienne, decision="approuver", horodatage=_HORODATAGE)
    _valeur("m7_exporter_paquet_manuel", contenu_id=ancienne, horodatage=_HORODATAGE)
    with (
        stockage.transaction(),
        contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "nathan_owner", source="console")),
        contexte.appeler_en_tant_que("m07-marketing", origine="console"),
    ):
        preuve = service.lire_edition_texte_humain(ancienne)["resultat"]
        reponse = service.reviser_texte_humain(
            ancienne, preuve["revision"], preuve["empreinte_texte"], preuve["snapshot_sha256"],
            "Un projet de gouttières terminé avec soin.", "2026-09-30T11:00:00-04:00",
        )
    assert reponse["accepte"] and reponse["resultat"]["modifie"], reponse
    nouvelle = reponse["resultat"]["contenu_id"]
    assert nouvelle != ancienne and [e["contenu_id"] for e in _lire("exports_paquet")] == [ancienne]
    return ancienne, nouvelle


def _verifier_bilan(bilan, ancienne, nouvelle):
    assert bilan["contenus_deja_exportes"] == [ancienne], bilan
    assert service.A_FAIRE_PAQUET_EXPORTE in bilan["a_faire"], bilan
    # Les contenus bloqués restent les cinq contenus courants (la révision corrigée, pas l'ancienne).
    assert len(bilan["contenus_bloques"]) == 5 and nouvelle in bilan["contenus_bloques"]
    assert ancienne not in bilan["contenus_bloques"]


def test_retrait_admin_liste_le_paquet_exporte_d_une_revision_corrigee(base_durable, brand_configure, charge):
    ancienne, nouvelle = _exporter_puis_corriger(charge)
    bilan = _valeur("m7_enregistrer_retrait_consentement_marketing", owner=True, wct_id=charge["wct_id"],
                    canal="telephone", horodatage=_HORODATAGE)
    _verifier_bilan(bilan, ancienne, nouvelle)
    # Le retrait l'emporte sur la révision remplacée : l'ancien paquet ne se réémet pas, et le motif dit pourquoi.
    for contenu_id in (ancienne, nouvelle):
        reponse = executer_atomique(_OUTILS["m7_exporter_paquet_manuel"],
                                    {"contenu_id": contenu_id, "horodatage": _HORODATAGE})
        assert reponse["resultat"]["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE", reponse
    assert [e["contenu_id"] for e in _lire("exports_paquet")] == [ancienne]


def test_stop_du_bus_liste_le_paquet_exporte_d_une_revision_corrigee(base_durable, brand_configure, charge):
    ancienne, nouvelle = _exporter_puis_corriger(charge)
    stop = {"lead_ids": [charge["lead_id"]], "canal": "sms", "horodatage": "2026-09-30T12:00:00-04:00",
            "signal_id": "sms:SM-STOP-FICTIF"}
    with stockage.transaction():
        bilan = outils.consommateurs()["m1.retrait_consentement"](stop)
    _verifier_bilan(bilan, ancienne, nouvelle)
