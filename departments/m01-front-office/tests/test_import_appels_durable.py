"""Parcours d'import manuel d'appels : registre SQLite, transfert humain et port CRM M2."""

from __future__ import annotations

import hashlib
import json

import pytest
from m1_front_office import outils as outils_m1
from m2_revenue_crm import outils as outils_m2

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
    outils_m2.utiliser_stockage_durable()
    deps = charger_departements()
    capacites = Capacites({"m01-front-office": deps["m01-front-office"]}, stockage.transaction, memoire=False)
    try:
        yield capacites
    finally:
        outils_m1.reinitialiser_registre()
        outils_m2.reinitialiser_registre()
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


def _clore_rappel_fictif(transfert_id):
    from m1_front_office import transferts

    with stockage.transaction():
        reg = outils_m1._obtenir_registre()
        etat = next(e for e in transferts.lire(reg.lire()) if e.identifiant == transfert_id)
        reg.ajouter(transferts.ligne_de_cloture(
            etat, par="admin-fictif", role="admin", voie="appareil",
            motif="Rappel FICTIF terminé par une personne.", horodatage="2026-09-29T10:00:00-04:00",
        ))


@pytest.mark.parametrize(("texte", "type_transfert", "decision", "niveau"), [
    ("Je suis insatisfait, c'est une plainte.", "plainte", "ESCALADE_PLAINTE", "N4"),
    ("Il y a une odeur de gaz.", "urgence", "ESCALADE_URGENCE", "N5"),
])
@pytest.mark.parametrize("clos", [False, True])
def test_reprise_prioritaire_conserve_ventes_et_ouvre_escalade_canonique(
    capacites_m1, declarer_plaintes, texte, type_transfert, decision, niveau, clos,
):
    from m1_front_office import transferts

    declarer_plaintes(vocabulaire=True, destinataires=True)
    premier = _importer(capacites_m1, {**BASE, "statut": "voicemail"})
    origine = premier["tache_rappel"]["transfert_id"]
    if clos:
        _clore_rappel_fictif(origine)
    avant = _lignes("m01-front-office")
    ventes = next(e for e in transferts.lire(avant) if e.identifiant == origine)
    args = {**BASE, "statut": "voicemail", "transcription": texte, "consentement_enregistrement": "accorde"}

    resultat = _importer(capacites_m1, args)

    assert resultat["traitement"]["decision"] == decision
    prioritaire = resultat["traitement"]["transfert"]
    assert prioritaire["type_transfert"] == type_transfert and prioritaire["niveau"] == niveau
    assert prioritaire["transfert_id"] != origine
    assert resultat["tache_rappel"]["transfert_id"] == origine
    assert resultat["tache_rappel"]["statut"] == ("clos" if clos else "ouvert")
    assert resultat["envoi_automatique"] is False
    apres = _lignes("m01-front-office")
    assert apres[:len(avant)] == avant
    ventes_apres = next(e for e in transferts.lire(apres) if e.identifiant == origine)
    assert ventes_apres == ventes
    attente = next(a for a in outils_m1.attentes() if a["id"] == prioritaire["transfert_id"])
    assert attente["type"] == f"{type_transfert}_escaladee" and attente["niveau"] == niveau
    enrichissement = next(ligne for ligne in apres if ligne.get("type_entree") == "appel_voicemail_enrichi")
    assert enrichissement["transfert_id"] == origine
    signal = next(ligne for ligne in apres if ligne.get("signal_id") == enrichissement["signal_id"])
    assert signal[transferts.MARQUE] == prioritaire["transfert_id"]
    assert not any(ligne.get("type_entree") == "lead_emis" for ligne in apres)
    assert _lignes("m02-revenue-crm") == []
    assert _importer(capacites_m1, {**args, "evenement_id": "evt-rejeu-prioritaire-fictif"}) == resultat
    assert _lignes("m01-front-office") == apres
    with stockage.transaction():
        assert outils_m1._obtenir_registre().valider_chaine() == (True, None)


@pytest.mark.parametrize("consentement", [None, "refuse"])
def test_reprise_consentie_apres_premiere_transcription_non_consentie(capacites_m1, consentement):
    args = {**BASE, "statut": "voicemail", "transcription": "Gouttières à Laval",
            "consentement_enregistrement": consentement}
    premier = _importer(capacites_m1, args)
    avant = _lignes("m01-front-office")

    reprise = _importer(capacites_m1, {**args, "consentement_enregistrement": "accorde"})

    assert reprise["transcription_conservee"] is True
    assert reprise["tache_rappel"]["transfert_id"] == premier["tache_rappel"]["transfert_id"]
    assert _lignes("m01-front-office")[:len(avant)] == avant
    assert _lignes("m02-revenue-crm") == []


@pytest.mark.parametrize("consentement", [None, "refuse"])
def test_fallback_v2_rejeu_exact_refuse_divergence_et_accepte_reprise_consentie(capacites_m1, consentement):
    args = {**BASE, "statut": "voicemail", "transcription": "Gouttières à Laval",
            "consentement_enregistrement": consentement}
    premier = _importer(capacites_m1, args)
    avant = _lignes("m01-front-office")
    base = next(ligne for ligne in avant if ligne.get("type_entree") == "appel_importe")
    assert base["representation_fallback"] == "voicemail_manuel_v2"
    metier = {cle: valeur for cle, valeur in args.items() if cle != "evenement_id"}
    canonique = {**metier, "transcription": None, "consentement_enregistrement": None}
    assert base["empreinte"] == hashlib.sha256(
        json.dumps(canonique, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    assert base["empreinte_reception"] == hashlib.sha256(json.dumps(
        {"representation": "voicemail_reception_v2", "contenu": metier}, sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()
    assert "Gouttières" not in json.dumps(avant, ensure_ascii=False)
    assert _importer(capacites_m1, {**args, "evenement_id": "evt-reception-relivree-fictif"}) == premier
    assert _lignes("m01-front-office") == avant
    for ecart in ({"transcription": "Toiture à Québec"},
                  {"consentement_enregistrement": "refuse" if consentement is None else None}):
        refuse = capacites_m1.appeler("m1_importer_appel_manuellement", {**args, **ecart})
        assert refuse["ok"] is False and "REJ-APPEL-CONTRADICTOIRE" in refuse["details"]
        assert _lignes("m01-front-office") == avant
    enrichi = _importer(capacites_m1, {**args, "consentement_enregistrement": "accorde"})
    assert enrichi["transcription_conservee"] is True
    assert enrichi["tache_rappel"]["transfert_id"] == premier["tache_rappel"]["transfert_id"]
    apres = _lignes("m01-front-office")
    assert apres[:len(avant)] == avant
    assert not any(ligne.get("type_entree") == "lead_emis" for ligne in apres)
    assert _lignes("m02-revenue-crm") == []
    assert _importer(capacites_m1, {
        **args, "consentement_enregistrement": "accorde", "evenement_id": "evt-enrichi-relivre-fictif",
    }) == enrichi
    assert _lignes("m01-front-office") == apres


@pytest.mark.parametrize(("texte", "consentement", "enrichissable"), [
    (None, None, True), ("Gouttières à Laval", None, False), (None, "refuse", False),
])
def test_representations_historiques_conservent_rejeu_et_preuve_fallback(
    capacites_m1, monkeypatch, texte, consentement, enrichissable,
):
    from m1_front_office.registre import Registre

    args = {**BASE, "statut": "voicemail", "transcription": texte, "consentement_enregistrement": consentement}
    metier = {cle: valeur for cle, valeur in args.items() if cle != "evenement_id"}
    empreinte_historique = hashlib.sha256(json.dumps(metier, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    ajouter = Registre.ajouter

    def ancienne_representation(self, entree):
        # Fixture historique reconstruite AVANT append natif, jamais un maillon stocké réécrit.
        entree = dict(entree)
        if entree.get("type_entree") == "appel_importe":
            entree.pop("representation_fallback", None)
            entree.pop("empreinte_reception", None)
            entree["empreinte"] = empreinte_historique
        return ajouter(self, entree)

    with monkeypatch.context() as temporaire:
        temporaire.setattr(Registre, "ajouter", ancienne_representation)
        premier = _importer(capacites_m1, args)
    avant = _lignes("m01-front-office")
    assert _importer(capacites_m1, {**args, "evenement_id": "evt-historique-rejeu-fictif"}) == premier
    assert _lignes("m01-front-office") == avant
    refuse = capacites_m1.appeler("m1_importer_appel_manuellement", {**args, "transcription": "Autre contenu fictif"})
    assert refuse["ok"] is False and "REJ-APPEL-CONTRADICTOIRE" in refuse["details"]
    assert _lignes("m01-front-office") == avant
    reprise = capacites_m1.appeler("m1_importer_appel_manuellement", {
        **args, "transcription": "Gouttières à Laval", "consentement_enregistrement": "accorde",
    })
    if enrichissable:
        assert reprise["ok"] is True and reprise["resultat"]["transcription_conservee"] is True
    else:
        assert reprise["ok"] is False and "REJ-APPEL-REPRISE-PREUVE-INVALIDE" in reprise["details"]
        assert _lignes("m01-front-office") == avant
    with stockage.transaction():
        assert outils_m1._obtenir_registre().valider_chaine() == (True, None)


@pytest.mark.parametrize("representation", [
    {"representation_fallback": "voicemail_manuel_v2"},
    {"empreinte_reception": "a" * 64},
    {"representation_fallback": "voicemail_manuel_v3", "empreinte_reception": "a" * 64},
    {"representation_fallback": True, "empreinte_reception": "a" * 64},
    {"representation_fallback": "voicemail_manuel_v2", "empreinte_reception": "INVALIDE"},
])
def test_attestation_partielle_ou_inconnue_refuse_rejeu_sans_downgrade(
    capacites_m1, monkeypatch, representation,
):
    from m1_front_office.registre import Registre

    ajouter = Registre.ajouter

    def attestation_fictive_invalide(self, entree):
        entree = dict(entree)
        if entree.get("type_entree") == "appel_importe":
            entree.pop("representation_fallback", None)
            entree.pop("empreinte_reception", None)
            entree.update(representation)
        return ajouter(self, entree)

    with monkeypatch.context() as temporaire:
        temporaire.setattr(Registre, "ajouter", attestation_fictive_invalide)
        _importer(capacites_m1, {**BASE, "statut": "voicemail"})
    avant = _lignes("m01-front-office")
    for ecart in ({}, {"transcription": "Gouttières à Laval", "consentement_enregistrement": "accorde"}):
        refuse = capacites_m1.appeler("m1_importer_appel_manuellement", {**BASE, "statut": "voicemail", **ecart})
        assert refuse["ok"] is False and "REJ-APPEL" in refuse["details"]
        assert _lignes("m01-front-office") == avant


@pytest.mark.parametrize("clos", [False, True])
def test_panne_finale_escalade_reprise_rollback_puis_reussite(capacites_m1, declarer_plaintes, monkeypatch, clos):
    from m1_front_office.registre import Registre

    declarer_plaintes(vocabulaire=True, destinataires=True)
    premier = _importer(capacites_m1, {**BASE, "statut": "voicemail"})
    if clos:
        _clore_rappel_fictif(premier["tache_rappel"]["transfert_id"])
    avant = _lignes("m01-front-office")
    args = {**BASE, "statut": "voicemail", "transcription": "Il y a une odeur de gaz.",
            "consentement_enregistrement": "accorde"}
    ajouter = Registre.ajouter

    def panne_fictive(self, entree):
        if entree.get("type_entree") == "appel_voicemail_enrichi":
            raise ValueError("REJ-TEST-PANNE-FICTIVE: append final")
        return ajouter(self, entree)

    with monkeypatch.context() as temporaire:
        temporaire.setattr(Registre, "ajouter", panne_fictive)
        refuse = capacites_m1.appeler("m1_importer_appel_manuellement", args)
        assert refuse["ok"] is False and "REJ-TEST-PANNE-FICTIVE" in refuse["details"]
        assert _lignes("m01-front-office") == avant
    outils_m1.utiliser_stockage_durable()
    resultat = _importer(capacites_m1, args)
    assert resultat["traitement"]["decision"] == "ESCALADE_URGENCE"
    assert resultat["tache_rappel"]["transfert_id"] == premier["tache_rappel"]["transfert_id"]
    apres = _lignes("m01-front-office")
    assert len([ligne for ligne in apres if ligne.get("type_entree") == "appel_voicemail_enrichi"]) == 1
    assert not any(ligne.get("type_entree") == "lead_emis" for ligne in apres)
    with stockage.transaction():
        assert outils_m1._obtenir_registre().valider_chaine() == (True, None)


def test_fallback_manuel_ne_peut_emprunter_source_voice_call(capacites_m1):
    refuse = capacites_m1.appeler("m1_importer_appel_manuellement", {
        **BASE, "statut": "voicemail", "source": "voice-call:twilio-fictif", "transcription": "Gouttières à Laval",
    })
    assert refuse["ok"] is False and "REJ-SOURCE-RESERVEE" in refuse["details"]
    assert _lignes("m01-front-office") == []
