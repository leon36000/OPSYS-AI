"""Parcours d'import manuel d'appels : registre SQLite, transfert humain et port CRM M2."""

from __future__ import annotations

import pytest
from m1_front_office import outils as outils_m1

from opsys import evenements, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import charger_departements

HEURE = "2026-09-29T09:15:00-04:00"
BASE = {
    "source": "export manuel PBX du 29 septembre",
    "evenement_id": "evt-001",
    "appel_id": "call-001",
    "recu_le": HEURE,
    "telephone": "+15145550142",
    "statut": "manque",
}


@pytest.fixture
def capacites_m1(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    outils_m1.utiliser_stockage_durable()
    deps = charger_departements()
    capacites = Capacites({"m01-front-office": deps["m01-front-office"]}, stockage.transaction, memoire=False)
    try:
        yield capacites
    finally:
        outils_m1.reinitialiser_registre()
        stockage.liberer()


def _lignes(departement: str) -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(departement, "principal"))


def _importer(capacites, args):
    retour = capacites.appeler("m1_importer_appel_manuellement", args)
    assert retour.get("ok") is True, retour
    return retour["resultat"]


def test_appel_manque_durable_rejoue_par_autre_id_transport_et_tache_admin(capacites_m1):
    premiere = _importer(capacites_m1, BASE)
    avant = _lignes("m01-front-office")
    autre_transport = {**BASE, "evenement_id": "evt-redelivre-99"}
    seconde = _importer(capacites_m1, autre_transport)

    assert seconde == premiere
    assert len(_lignes("m01-front-office")) == len(avant)
    assert premiere["envoi_automatique"] is False
    assert premiere["tache_rappel"]["statut"] == "ouvert"
    assert outils_m1.attentes()[0]["type"] == "transfert_humain"
    assert "appels importés : manque: 1" in outils_m1.produire_digest("2026-09-29")
    # Une nouvelle instance relit la tâche depuis les maillons SQLite, sans état Python partagé.
    outils_m1.utiliser_stockage_durable()
    assert outils_m1.attentes()[0]["id"] == premiere["tache_rappel"]["transfert_id"]


def test_voicemail_arrive_apres_appel_manque_est_rattache_a_la_tache_ouverte(capacites_m1):
    appel_manque = _importer(capacites_m1, BASE)
    tardif = {
        **BASE,
        "evenement_id": "evt-002",
        "statut": "voicemail",
        "transcription": "Bonjour, mes gouttières fuient à Laval.",
        "consentement_enregistrement": "accorde",
    }
    resultat = _importer(capacites_m1, tardif)
    assert resultat["transcription_conservee"] is True
    assert resultat["traitement"]["decision"] == "TRANSFERT_EN_COURS"
    lignes = _lignes("m01-front-office")
    tardif_signal = next(
        ligne for ligne in lignes
        if ligne.get("signal_id") == "appel-manuel:export manuel PBX du 29 septembre:evt-002"
    )
    assert tardif_signal.get("rattache_au_transfert") == appel_manque["tache_rappel"]["transfert_id"]


def test_voicemail_qualifie_est_ingere_au_vrai_crm_m2(capacites_m1):
    args = {**BASE, "statut": "voicemail", "transcription": "Bonjour, mes gouttières fuient à Laval.",
            "consentement_enregistrement": "accorde"}
    resultat = _importer(capacites_m1, args)
    assert resultat["transcription_conservee"] is True
    assert resultat["traitement"]["decision"] == "TRANSMETTRE_M2"
    assert len([ligne for ligne in _lignes("m01-front-office") if ligne.get("type_entree") == "lead_emis"]) == 1

    # Le vrai répartiteur et le vrai consommateur M2 traitent l'événement publié par M1.
    deps = charger_departements()
    resume = evenements.repartir({"m02-revenue-crm": deps["m02-revenue-crm"]},
                                 maintenant="2026-09-29T10:00:00-04:00")
    assert resume["traites"] == 1
    lignes_m2 = _lignes("m02-revenue-crm")
    assert any(ligne.get("type_entree") == "lead_ingere" for ligne in lignes_m2)


def test_plainte_vocale_devient_escalade_privee_sans_lead_ni_envoi(capacites_m1, declarer_plaintes):
    declarer_plaintes(vocabulaire=True, destinataires=True)
    resultat = _importer(capacites_m1, {
        **BASE, "statut": "voicemail", "transcription": "Je suis insatisfait, c'est une plainte.",
        "consentement_enregistrement": "accorde",
    })
    assert resultat["traitement"]["decision"] == "ESCALADE_PLAINTE"
    assert resultat["tache_rappel"] is None
    assert resultat["envoi_automatique"] is False
    assert not any(ligne.get("type_entree") == "lead_emis" for ligne in _lignes("m01-front-office"))
    assert outils_m1.attentes()[0]["type"] == "plainte_escaladee"


def test_contenu_contradictoire_meme_fait_ne_change_aucun_registre_ni_bus(capacites_m1):
    _importer(capacites_m1, {**BASE, "statut": "voicemail", "transcription": "Gouttières à Laval",
                             "consentement_enregistrement": "accorde"})
    avant_m1 = _lignes("m01-front-office")
    avant_m2 = _lignes("m02-revenue-crm")
    contradiction = {**BASE, "statut": "voicemail", "transcription": "Toiture à Québec",
                     "consentement_enregistrement": "accorde", "evenement_id": "evt-une-autre-livraison"}
    refuse = capacites_m1.appeler("m1_importer_appel_manuellement", contradiction)
    assert refuse["ok"] is False and "REJ-APPEL-CONTRADICTOIRE" in refuse["details"]
    assert _lignes("m01-front-office") == avant_m1
    assert _lignes("m02-revenue-crm") == avant_m2


def test_transcription_sans_consentement_n_est_pas_persistée(capacites_m1):
    resultat = _importer(capacites_m1, {**BASE, "statut": "voicemail", "transcription": "Gouttières à Laval"})
    assert resultat["transcription_conservee"] is False
    signal = next(ligne for ligne in _lignes("m01-front-office") if ligne.get("type_entree") == "signal")
    assert "Gouttières" not in signal["contenu_filtre"]
    assert resultat["tache_rappel"] is not None
