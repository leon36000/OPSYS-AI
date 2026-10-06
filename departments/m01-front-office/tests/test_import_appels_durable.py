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


def test_reprise_voicemail_clos_ajoute_une_note_sans_reouvrir_ni_perdre_motif(capacites_m1):
    from m1_front_office import transferts

    premier = _importer(capacites_m1, {**BASE, "statut": "voicemail"})
    transfert_id = premier["tache_rappel"]["transfert_id"]
    with stockage.transaction():
        reg = outils_m1._obtenir_registre()
        etat = next(e for e in transferts.lire(reg.lire()) if e.identifiant == transfert_id)
        reg.ajouter(transferts.ligne_de_cloture(
            etat, par="admin-fictif", role="admin", voie="appareil",
            motif="Rappel complété, la demande a été prise en charge.", horodatage="2026-09-29T10:00:00-04:00",
        ))
    avant = _lignes("m01-front-office")
    assert len(transferts.lire(avant)) == 1 and not transferts.lire(avant)[0].ouvert

    enrichi = _importer(capacites_m1, {
        **BASE, "statut": "voicemail", "transcription": "Bonjour, mes gouttières fuient à Laval.",
        "consentement_enregistrement": "accorde",
    })

    assert enrichi["accepte"] is True
    assert enrichi["traitement"]["decision"] == "TRANSFERT_CLOS_NOTE_AJOUTEE"
    assert enrichi["tache_rappel"]["transfert_id"] == transfert_id
    assert enrichi["tache_rappel"]["statut"] == "clos"
    apres = _lignes("m01-front-office")
    etats = transferts.lire(apres)
    assert len(etats) == 1 and not etats[0].ouvert
    vue = transferts.vue(etats[0], apres)
    assert vue["cloture"]["motif"] == "Rappel complété, la demande a été prise en charge."
    assert len(vue["messages_suivants"]) == 1
    assert "Bonjour, mes gouttières fuient à Laval." in vue["messages_suivants"][0]["texte"]
    assert len([ligne for ligne in apres if ligne.get("type_entree") == "appel_voicemail_enrichi"]) == 1
    assert not any(ligne.get("type_entree") == "lead_emis" for ligne in apres)


def test_reprise_refuse_consentement_absent_ou_metadonnees_changees_sans_mutation(capacites_m1):
    _importer(capacites_m1, {**BASE, "statut": "voicemail"})
    avant = _lignes("m01-front-office")
    transcript = "Bonjour, mes gouttières fuient à Laval."
    cas = [
        {**BASE, "statut": "voicemail", "transcription": transcript},
        {**BASE, "telephone": "+15145550143", "statut": "voicemail", "transcription": transcript,
         "consentement_enregistrement": "accorde"},
        {**BASE, "recu_le": "2026-09-29T10:15:00-04:00", "statut": "voicemail",
         "transcription": transcript, "consentement_enregistrement": "accorde"},
    ]
    for tentative in cas:
        refuse = capacites_m1.appeler("m1_importer_appel_manuellement", tentative)
        assert refuse["ok"] is False and "REJ-APPEL" in refuse["details"]
        assert _lignes("m01-front-office") == avant


def test_rejeu_transcription_enrichie_stable_et_contenu_divergent_sans_mutation(capacites_m1):
    fallback = _importer(capacites_m1, {**BASE, "statut": "voicemail"})
    transcription = "Bonjour, mes gouttières fuient à Laval."
    arguments = {**BASE, "statut": "voicemail", "transcription": transcription,
                 "consentement_enregistrement": "accorde"}
    premiere = _importer(capacites_m1, arguments)
    apres = _lignes("m01-front-office")
    rejeu = _importer(capacites_m1, {**arguments, "evenement_id": "evt-relivre-fictif"})
    assert rejeu == premiere
    assert _lignes("m01-front-office") == apres
    assert premiere["tache_rappel"]["transfert_id"] == fallback["tache_rappel"]["transfert_id"]

    refuse = capacites_m1.appeler("m1_importer_appel_manuellement", {
        **arguments, "evenement_id": "evt-contradictoire-fictif",
        "transcription": "Je demande une toiture à Québec.",
    })
    assert refuse["ok"] is False and "REJ-APPEL-CONTRADICTOIRE" in refuse["details"]
    assert _lignes("m01-front-office") == apres


def test_echec_final_enrichissement_annule_note_consentement_et_reprise_reussit(capacites_m1, monkeypatch):
    from m1_front_office.registre import Registre

    fallback = _importer(capacites_m1, {**BASE, "statut": "voicemail"})
    avant = _lignes("m01-front-office")
    arguments = {**BASE, "statut": "voicemail", "transcription": "Bonjour, mes gouttières fuient à Laval.",
                 "consentement_enregistrement": "accorde"}
    ajouter = Registre.ajouter

    def echec_fin(self, entree):
        if entree.get("type_entree") == "appel_voicemail_enrichi":
            raise ValueError("REJ-TEST-PANNE-FICTIVE: écriture finale indisponible")
        return ajouter(self, entree)

    with monkeypatch.context() as temporaire:
        temporaire.setattr(Registre, "ajouter", echec_fin)
        refuse = capacites_m1.appeler("m1_importer_appel_manuellement", arguments)
        assert refuse["ok"] is False and "REJ-TEST-PANNE-FICTIVE" in refuse["details"]
        assert _lignes("m01-front-office") == avant

    outils_m1.utiliser_stockage_durable()
    reprise = _importer(capacites_m1, arguments)
    assert reprise["tache_rappel"]["transfert_id"] == fallback["tache_rappel"]["transfert_id"]
    apres = _lignes("m01-front-office")
    assert apres[:len(avant)] == avant
    assert len([ligne for ligne in apres if ligne.get("type_entree") == "appel_voicemail_enrichi"]) == 1
    with stockage.transaction():
        assert outils_m1._obtenir_registre().valider_chaine() == (True, None)
