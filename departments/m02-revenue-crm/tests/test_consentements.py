"""PLAN T4.9 (M2.7, §7 M2 « opt-in respecté ») : le registre de consentement de contact, module pur.

Ce qui est prouvé ici, sans base ni horloge : la construction fail-closed d'un consentement (canal écrit, énoncé
versionné, source, preuve sans numéro, instants) et d'un retrait (STOP, sans contact) ; le périmètre d'une PERSONNE (les
leads d'un même client) ; l'état d'un canal (`retire` prime sur tout, `actif`, `absent`) ; les canaux permis (l'appel
toujours, un message seulement avec un consentement actif). Données fictives (`fictif: true`) : aucun vrai numéro, aucun
vrai client. """

from __future__ import annotations

import json

import pytest
from m2_revenue_crm import consentements, verdicts

FICTIF = True

RECUEILLI = "2026-09-20T10:00:00-04:00"
ENREGISTRE = "2026-09-20T10:05:00-04:00"
PREUVE = {"type": "formulaire", "reference": "formulaire-web-2026-09-20-0042"}
STOP_LE = "2026-09-25T09:00:00-04:00"


def _consentement(**surcharges):
    arguments = {
        "lead_id": "lead-1", "client_id": "client-a", "canal": "sms", "enonce_version": "consentement-sms-v1",
        "source": "formulaire", "preuve": dict(PREUVE), "recueilli_le": RECUEILLI, "enregistre_le": ENREGISTRE,
        "enregistre_par": "vendeur.un", "voie": "appareil",
    }
    arguments.update(surcharges)
    return consentements.construire_consentement(**arguments)


def _retrait(**surcharges):
    arguments = {"lead_id": "lead-1", "canal": "sms", "signal_id": "sms:SM-STOP-1", "horodatage": STOP_LE}
    arguments.update(surcharges)
    return consentements.construire_retrait(**arguments)


def _ok(resultat):
    entree, verdict = resultat
    assert verdict is None, verdict
    return entree


def _code(resultat):
    entree, verdict = resultat
    assert entree is None and verdict is not None, resultat
    assert verdicts.est_verdict(verdict["code"])
    return verdict["code"]


# ---------------------------------------------------------------------------------------------------------
# Les constantes : ce que la politique nomme
# ---------------------------------------------------------------------------------------------------------
def test_les_canaux_sont_l_appel_et_les_deux_canaux_ecrits():
    assert consentements.CANAL_APPEL == "appel"
    assert consentements.CANAUX_ECRITS == ("sms", "courriel")
    assert consentements.CANAUX_RELANCE == ("appel", "sms", "courriel")


def test_la_source_et_la_preuve_reprennent_les_mots_de_la_politique():
    # POLITIQUE-consentement-sms §4 : source (formulaire, appel, kiosque) ; §3 : preuve (écran, formulaire, double
    # opt-in).
    assert consentements.SOURCES_CONSENTEMENT == ("formulaire", "appel", "kiosque")
    assert set(consentements.TYPES_PREUVE) >= {"ecran", "formulaire", "double_opt_in"}
    assert consentements.VOIES == ("appareil", "approbation")


# ---------------------------------------------------------------------------------------------------------
# construire_consentement
# ---------------------------------------------------------------------------------------------------------
def test_un_consentement_valide_garde_exactement_ses_champs_et_aucun_contact():
    entree = _ok(_consentement())
    assert entree == {
        "type_entree": "consentement_contact", "consentement_id": entree["consentement_id"], "lead_id": "lead-1",
        "client_id": "client-a", "canal": "sms", "enonce_version": "consentement-sms-v1", "source": "formulaire",
        "preuve": PREUVE, "recueilli_le": RECUEILLI, "enregistre_le": ENREGISTRE, "enregistre_par": "vendeur.un",
        "voie": "appareil",
    }
    assert entree["preuve"] is not PREUVE, "le maillon ne partage pas l'objet de l'appelant"


def test_l_identifiant_est_deterministe_et_change_avec_chaque_fait_qui_compte():
    base = _ok(_consentement())["consentement_id"]
    assert _ok(_consentement())["consentement_id"] == base
    # Ni la personne qui l'inscrit, ni l'heure d'inscription, ni la preuve ne font un autre consentement.
    assert _ok(_consentement(enregistre_par="admin.fictif", enregistre_le="2026-09-20T11:00:00-04:00",
                             preuve={"type": "ecran", "reference": "ecran-2026-0001"}))["consentement_id"] == base
    # Le lead, le canal, la version de l'énoncé et l'instant du consentement, oui.
    for surcharge in (
        {"lead_id": "lead-2"}, {"canal": "courriel"}, {"enonce_version": "consentement-sms-v2"},
        {"recueilli_le": "2026-09-20T09:59:00-04:00"},
    ):
        assert _ok(_consentement(**surcharge))["consentement_id"] != base, surcharge


def test_un_lead_sans_client_est_accepte_avec_client_nul():
    assert _ok(_consentement(client_id=None))["client_id"] is None


def test_le_nom_de_la_personne_est_nettoye_des_espaces():
    assert _ok(_consentement(enregistre_par="  vendeur.un  "))["enregistre_par"] == "vendeur.un"


@pytest.mark.parametrize("surcharge", [
    {"lead_id": ""}, {"lead_id": "   "}, {"lead_id": None}, {"lead_id": 5},
    {"client_id": ""}, {"client_id": 5},
    {"canal": "appel"}, {"canal": "whatsapp"}, {"canal": None}, {"canal": ""},
    {"enonce_version": ""}, {"enonce_version": "avec espace"}, {"enonce_version": "x" * 65}, {"enonce_version": None},
    {"enonce_version": "é-accent"},
    {"source": "telephone"}, {"source": None}, {"source": ""},
    {"preuve": None}, {"preuve": {}}, {"preuve": {"type": "formulaire"}},
    {"preuve": {"type": "formulaire", "reference": "formulaire-1", "extra": "x"}},
    {"preuve": {"type": "signature", "reference": "formulaire-1"}},
    {"preuve": {"type": None, "reference": "formulaire-1"}},
    {"preuve": {"type": "formulaire", "reference": ""}}, {"preuve": {"type": "formulaire", "reference": "ab"}},
    {"preuve": {"type": "formulaire", "reference": "avec des espaces"}},
    {"preuve": {"type": "formulaire", "reference": "x" * 121}}, {"preuve": {"type": "formulaire", "reference": 42}},
    {"enregistre_par": ""}, {"enregistre_par": "  "}, {"enregistre_par": None},
    {"voie": "agent"}, {"voie": None}, {"voie": ""},
])
def test_un_champ_invalide_est_refuse_avec_le_verdict_du_consentement(surcharge):
    assert _code(_consentement(**surcharge)) == "REJ-CONSENTEMENT-INVALIDE"


@pytest.mark.parametrize("reference", ["514-555-0142", "5145550142", "+1-514-555-0142", "vendeur@exemple-fictif.test"])
def test_une_reference_ne_peut_pas_etre_un_numero_ni_un_courriel(reference):
    verdict = _consentement(preuve={"type": "formulaire", "reference": reference})[1]
    assert verdict["code"] == "REJ-CONSENTEMENT-INVALIDE"
    assert "jamais un numéro" in verdict["detail"]


@pytest.mark.parametrize("reference", ["abc", "REC-123456", "note-appel-2026-09-20-A12", "form:web/2026-09-20#0042"])
def test_une_reference_de_document_est_acceptee(reference):
    assert _ok(_consentement(preuve={"type": "verbal_documente", "reference": reference}))["preuve"]["reference"] == (
        reference)


@pytest.mark.parametrize("champ", ["recueilli_le", "enregistre_le"])
@pytest.mark.parametrize("valeur", ["", "hier", "2026-09-20", "2026-09-20T10:00:00", None, 5])
def test_un_instant_sans_fuseau_ou_illisible_est_refuse(champ, valeur):
    assert _code(_consentement(**{champ: valeur})) == "REJ-HORODATAGE-INVALIDE"


def test_un_consentement_ne_peut_pas_etre_recueilli_apres_son_inscription():
    assert _code(_consentement(recueilli_le="2026-09-20T10:05:01-04:00")) == "REJ-CONSENTEMENT-INVALIDE"
    # Pile à l'instant de l'inscription, c'est permis ; les instants sont comparés en UTC, pas en texte.
    assert _ok(_consentement(recueilli_le=ENREGISTRE))["recueilli_le"] == ENREGISTRE
    assert _ok(_consentement(recueilli_le="2026-09-20T14:04:59+00:00"))["recueilli_le"] == "2026-09-20T14:04:59+00:00"
    assert _code(_consentement(recueilli_le="2026-09-20T14:05:01+00:00")) == "REJ-CONSENTEMENT-INVALIDE"


def test_le_refus_precede_toute_inscription_et_dit_le_champ():
    verdict = _consentement(canal="appel")[1]
    assert "canal" in verdict["detail"] and "appel" in verdict["detail"]
    assert "enonce_version" in _consentement(enonce_version="x y")[1]["detail"]
    assert "source" in _consentement(source="x")[1]["detail"]
    assert "preuve.type" in _consentement(preuve={"type": "x", "reference": "abcdef"})[1]["detail"]
    assert "recueilli_le" in _consentement(recueilli_le="2026-09-21T10:00:00-04:00")[1]["detail"]


def test_l_ordre_des_controles_est_celui_documente():
    # Deux fautes : c'est la première (le canal) qui parle.
    verdict = _consentement(canal="appel", source="x")[1]
    assert "canal" in verdict["detail"]
    verdict = _consentement(source="x", enregistre_par="")[1]
    assert "source" in verdict["detail"]


# ---------------------------------------------------------------------------------------------------------
# construire_retrait
# ---------------------------------------------------------------------------------------------------------
def test_un_retrait_valide_ne_garde_que_le_lead_le_canal_le_signal_et_l_heure():
    entree = _ok(_retrait())
    assert entree == {
        "type_entree": "retrait_contact", "retrait_id": entree["retrait_id"], "lead_id": "lead-1", "canal": "sms",
        "signal_id": "sms:SM-STOP-1", "horodatage": STOP_LE, "source": "bus:m1.retrait_consentement",
    }
    texte = json.dumps(entree)
    for numero in ("+1514", "514", "@"):
        assert numero not in texte


def test_le_meme_stop_pour_le_meme_lead_est_le_meme_retrait_et_un_autre_lead_un_autre():
    base = _ok(_retrait())["retrait_id"]
    assert _ok(_retrait())["retrait_id"] == base
    assert _ok(_retrait(canal="courriel", horodatage="2026-09-26T09:00:00-04:00"))["retrait_id"] == base
    assert _ok(_retrait(lead_id="lead-2"))["retrait_id"] != base
    assert _ok(_retrait(signal_id="sms:SM-STOP-2"))["retrait_id"] != base


@pytest.mark.parametrize("surcharge", [
    {"lead_id": ""}, {"lead_id": None}, {"lead_id": "  "}, {"lead_id": 3},
    {"canal": "appel"}, {"canal": "voix"}, {"canal": None},
    {"signal_id": ""}, {"signal_id": None}, {"signal_id": " "},
])
def test_un_retrait_mal_forme_est_refuse(surcharge):
    assert _code(_retrait(**surcharge)) == "REJ-CONSENTEMENT-INVALIDE"


@pytest.mark.parametrize("valeur", ["", "hier", "2026-09-25", "2026-09-25T09:00:00", None, 7])
def test_un_retrait_sans_heure_lisible_avec_fuseau_est_refuse(valeur):
    assert _code(_retrait(horodatage=valeur)) == "REJ-HORODATAGE-INVALIDE"


# ---------------------------------------------------------------------------------------------------------
# canaux_retires
# ---------------------------------------------------------------------------------------------------------
def test_un_retrait_fait_taire_tous_les_canaux_ecrits_jamais_l_appel():
    assert consentements.canaux_retires("sms") == ("sms", "courriel")
    assert consentements.canaux_retires("courriel") == ("sms", "courriel")
    assert consentements.canaux_retires("appel") == ()
    assert consentements.canaux_retires("telepathie") == ()
    assert consentements.canaux_retires(None) == ()


# ---------------------------------------------------------------------------------------------------------
# perimetre : le consentement est celui d'une personne
# ---------------------------------------------------------------------------------------------------------
def test_le_perimetre_reunit_les_leads_du_meme_client():
    clients = {"lead-1": "client-a", "lead-2": "client-a", "lead-3": "client-b", "lead-4": None}
    opportunites = {"client-a": ["lead-1", "lead-2"], "client-b": ["lead-3"]}
    assert consentements.perimetre("lead-1", clients, opportunites) == frozenset({"lead-1", "lead-2"})
    assert consentements.perimetre("lead-2", clients, opportunites) == frozenset({"lead-1", "lead-2"})
    assert consentements.perimetre("lead-3", clients, opportunites) == frozenset({"lead-3"})


def test_un_lead_sans_client_ou_inconnu_n_est_que_lui_meme():
    assert consentements.perimetre("lead-4", {"lead-4": None}, {}) == frozenset({"lead-4"})
    assert consentements.perimetre("lead-9", {}, {"client-a": ["lead-1"]}) == frozenset({"lead-9"})


def test_le_lead_vise_fait_toujours_partie_de_son_perimetre_meme_si_le_lien_est_incomplet():
    assert consentements.perimetre("lead-1", {"lead-1": "client-a"}, {"client-a": ["lead-2"]}) == frozenset(
        {"lead-1", "lead-2"})
    assert consentements.perimetre("lead-1", {"lead-1": "client-a"}, {}) == frozenset({"lead-1"})


# ---------------------------------------------------------------------------------------------------------
# etat_du_canal
# ---------------------------------------------------------------------------------------------------------
PERSONNE = frozenset({"lead-1", "lead-2"})


def test_sans_aucun_fait_le_canal_est_absent():
    assert consentements.etat_du_canal("sms", PERSONNE, [], []) == {"etat": "absent"}


def test_un_consentement_de_la_personne_rend_le_canal_actif_avec_son_enonce_et_sa_preuve():
    consentement = _ok(_consentement(lead_id="lead-2"))
    etat = consentements.etat_du_canal("sms", PERSONNE, [consentement], [])
    assert etat == {
        "etat": "actif", "enonce_version": "consentement-sms-v1", "source": "formulaire", "preuve_type": "formulaire",
        "recueilli_le": RECUEILLI,
    }
    assert "reference" not in json.dumps(etat), "la référence de la preuve reste au registre"


def test_un_consentement_n_est_pas_celui_d_un_autre_canal_ni_d_une_autre_personne():
    sms = _ok(_consentement(canal="sms"))
    assert consentements.etat_du_canal("courriel", PERSONNE, [sms], []) == {"etat": "absent"}
    assert consentements.etat_du_canal("sms", frozenset({"lead-9"}), [sms], []) == {"etat": "absent"}


def test_le_consentement_le_plus_recent_fait_foi_et_a_egalite_le_dernier_ecrit():
    ancien = _ok(_consentement(enonce_version="v1", recueilli_le="2026-09-01T09:00:00-04:00"))
    recent = _ok(_consentement(enonce_version="v2", recueilli_le="2026-09-10T09:00:00-04:00"))
    assert consentements.etat_du_canal("sms", PERSONNE, [ancien, recent], [])["enonce_version"] == "v2"
    assert consentements.etat_du_canal("sms", PERSONNE, [recent, ancien], [])["enonce_version"] == "v2"
    egal_a = _ok(_consentement(enonce_version="v3", recueilli_le="2026-09-10T09:00:00-04:00"))
    assert consentements.etat_du_canal("sms", PERSONNE, [recent, egal_a], [])["enonce_version"] == "v3"
    # Les instants se comparent en UTC : 09:00 -04:00 est postérieur à 12:00 +00:00.
    en_utc = _ok(_consentement(enonce_version="v4", recueilli_le="2026-09-10T12:00:00+00:00"))
    assert consentements.etat_du_canal("sms", PERSONNE, [en_utc, recent], [])["enonce_version"] == "v2"


def test_un_retrait_prime_sur_tout_consentement_quel_que_soit_l_ordre_ou_l_heure():
    consentement = _ok(
        _consentement(recueilli_le="2026-09-25T09:30:00-04:00", enregistre_le="2026-09-26T09:00:00-04:00"))
    retrait = _ok(_retrait())  # le STOP est AVANT ce consentement : il gagne quand même
    for consentements_lus, retraits_lus in (([consentement], [retrait]), ([], [retrait])):
        etat = consentements.etat_du_canal("sms", PERSONNE, consentements_lus, retraits_lus)
        assert etat == {
            "etat": "retire", "retire_le": STOP_LE, "source": "bus:m1.retrait_consentement", "canal_du_retrait": "sms",
        }


def test_un_stop_par_sms_retire_aussi_le_courriel_mais_pas_l_appel():
    retrait = _ok(_retrait(canal="sms"))
    courriel = _ok(_consentement(canal="courriel"))
    assert consentements.etat_du_canal("courriel", PERSONNE, [courriel], [retrait])["etat"] == "retire"
    permis, etats = consentements.canaux_permis(PERSONNE, [courriel], [retrait])
    assert permis == ["appel"] and etats["sms"]["etat"] == etats["courriel"]["etat"] == "retire"


def test_le_retrait_d_un_autre_client_ne_touche_pas_cette_personne():
    retrait = _ok(_retrait(lead_id="lead-9"))
    assert consentements.etat_du_canal("sms", PERSONNE, [], [retrait]) == {"etat": "absent"}


def test_le_premier_retrait_date_le_retrait():
    tard = _ok(_retrait(signal_id="sms:SM-STOP-2", horodatage="2026-09-27T09:00:00-04:00"))
    tot = _ok(_retrait(lead_id="lead-2", signal_id="sms:SM-STOP-1", horodatage="2026-09-24T09:00:00-04:00"))
    assert consentements.etat_du_canal("sms", PERSONNE, [], [tard, tot])["retire_le"] == "2026-09-24T09:00:00-04:00"
    assert consentements.etat_du_canal("sms", PERSONNE, [], [tot, tard])["retire_le"] == "2026-09-24T09:00:00-04:00"
    # Les instants se comparent en UTC, pas en texte : 12:59 UTC précède 09:00 -04:00 (13:00 UTC), même si le texte
    # « 09:00:00-04:00 » se range avant « 12:59:00+00:00 ».
    utc = _ok(_retrait(lead_id="lead-2", signal_id="sms:SM-STOP-3", horodatage="2026-09-24T12:59:00+00:00"))
    assert consentements.etat_du_canal("sms", PERSONNE, [], [tot, utc])["retire_le"] == "2026-09-24T12:59:00+00:00"
    assert consentements.etat_du_canal("sms", PERSONNE, [], [utc, tot])["retire_le"] == "2026-09-24T12:59:00+00:00"


# ---------------------------------------------------------------------------------------------------------
# canaux_permis
# ---------------------------------------------------------------------------------------------------------
def test_sans_consentement_actif_l_appel_est_le_seul_canal_permis():
    permis, etats = consentements.canaux_permis(PERSONNE, [], [])
    assert permis == ["appel"]
    assert etats == {"sms": {"etat": "absent"}, "courriel": {"etat": "absent"}}


def test_un_consentement_actif_ajoute_son_canal_dans_l_ordre_du_catalogue():
    sms, courriel = _ok(_consentement(canal="sms")), _ok(_consentement(canal="courriel"))
    assert consentements.canaux_permis(PERSONNE, [sms], [])[0] == ["appel", "sms"]
    assert consentements.canaux_permis(PERSONNE, [courriel], [])[0] == ["appel", "courriel"]
    assert consentements.canaux_permis(PERSONNE, [courriel, sms], [])[0] == ["appel", "sms", "courriel"]


def test_canaux_permis_lit_les_iterables_une_seule_fois():
    sms = _ok(_consentement(canal="sms"))
    permis, _ = consentements.canaux_permis(PERSONNE, iter([sms]), iter([]))
    assert permis == ["appel", "sms"]
