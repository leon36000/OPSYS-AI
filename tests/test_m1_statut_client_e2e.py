"""M1-G de bout en bout sur les VRAIS outils et registres : M1 (identité + lead) -> port privé -> M2 (dossier).

Une demande SMS réelle de M1 crée le lead ; le VRAI consommateur M2 l'ingère par le VRAI bus ; une vérification
d'identité est rejouée depuis le registre de M1 (deux moyens attestés) ; `m1_statut_client` lit alors le dossier par le
port privé `lecteur_statut_client` et ne rend qu'un statut en gabarit fixe. Données fictives.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from m1_front_office import identite_client as ic
from m1_front_office import outils as m1_outils
from m1_front_office import reception
from m2_revenue_crm import outils as m2_outils

from opsys import contexte, evenements, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Niveau, executer_atomique

RACINE = Path(__file__).resolve().parents[1]
NUMERO = "+15145550142"
RECU = "2031-01-15T08:00:00-05:00"
H = "2031-01-15T09:00:00-05:00"
APRES = "2031-01-15T09:10:00-05:00"
VID = "vi-" + "a" * 16


@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    m1_outils.utiliser_stockage_durable()
    m2_outils.utiliser_stockage_durable()
    deps = charger_departements()
    yield deps
    m1_outils.reinitialiser_registre()
    m2_outils.reinitialiser_registre()
    stockage.liberer()


def _lead(deps):
    m1 = Capacites({"m01-front-office": deps["m01-front-office"]}, stockage.transaction, memoire=False)
    r = m1.appeler("m1_recevoir_message_canal", {
        "canal": "sms", "expediteur": NUMERO, "message_id": "SM-STATUT-1", "recu_le": RECU,
        "texte": "Bonjour, mes gouttières fuient à Laval, c'est urgent.",
    })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    with stockage.transaction():
        ligne = next(x for x in m1_outils._obtenir_registre().lire() if x.get("type_entree") == "lead_emis")
    return ligne["lead"]["lead_id"], ligne["conversation_id"]


def _ingerer(deux_deps):
    for _ in range(4):
        r = evenements.repartir({"m02-revenue-crm": deux_deps["m02-revenue-crm"]})
        if r["livres"] == 0:
            return
    raise AssertionError("le bus n'a pas atteint la quiescence")


def _verifier(cle):
    lignes = [{
        "type_entree": ic.TYPE_OUVERTE, "horodatage": H, "verification_id": VID, "cle": cle, "canal": "courriel",
        "finalite": "statut_dossier", "signal_id": "verification:" + VID, "sel": "sel-fictif",
        "empreinte_code": None, "brouillon_id": None, "expire_le": "2031-01-15T09:30:00-05:00",
        "conserver_jusqu_au": "2031-04-15T09:00:00-04:00",
    }]
    for moyen in ("rappel_numero_dossier", "connaissance_dossier"):
        lignes.append({"type_entree": ic.TYPE_ATTESTATION, "horodatage": H, "verification_id": VID, "moyen": moyen})
    with stockage.transaction():
        reg = stockage.maillons("m01-front-office", "verifications_identite")
        for ligne in lignes:
            reg.append(ligne)


def test_le_dossier_d_un_client_verifie_est_lu_par_le_vrai_m2(monde):
    lead_id, cle = _lead(monde)
    assert reception.identifiant_de_conversation("sms", NUMERO) == cle
    _ingerer(monde)
    _verifier(cle)
    capacites = Capacites(
        {"m01-front-office": monde["m01-front-office"], "m02-revenue-crm": monde["m02-revenue-crm"]},
        stockage.transaction, memoire=False,
    )
    r = capacites.appeler("m1_statut_client", {
        "verification_id": VID, "sujet": "dossier", "horodatage": APRES,
    })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    resultat = r["resultat"]["resultat"]
    assert resultat["statut"] == "repondu" and resultat["source"] == "m02-revenue-crm"
    assert "Voici l'état de votre dossier : en cours de prise en charge." in resultat["reponse"]
    assert "+15145550142" not in str(resultat), "aucun contact ne sort du gabarit"


DEVIS = "DEVIS-STATUT-1"


def _devis(monde, lead_id):
    outils = {o.nom: o for o in monde["m03-estimation"].charger_outils()}
    reponse = executer_atomique(outils["m3_creer_devis"], {
        "devis_id": DEVIS, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{
            "description": "Gouttières 5po aluminium (fictif)", "quantite": "40", "unite": "pi",
            "cout_unitaire": "8.00", "reference_besoin_materiau": "gouttiere-alu-5po-fictif",
        }],
        "taux_marge": "0.25", "horodatage": H,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def test_une_soumission_reelle_est_lue_sans_prix(monde):
    lead_id, cle = _lead(monde)
    _ingerer(monde)
    _verifier(cle)
    _devis(monde, lead_id)
    capacites = Capacites(
        {
            "m01-front-office": monde["m01-front-office"],
            "m03-estimation": monde["m03-estimation"],
        },
        stockage.transaction, memoire=False,
    )
    r = capacites.appeler("m1_statut_client", {
        "verification_id": VID, "sujet": "soumission", "reference": DEVIS, "horodatage": APRES,
    })
    resultat = r["resultat"]["resultat"]
    assert resultat["statut"] == "repondu" and resultat["source"] == "m03-estimation"
    assert "Voici l'état de votre soumission : en préparation." in resultat["reponse"]
    assert "prix" not in str(resultat).lower() and "cout" not in str(resultat).lower()


def test_le_port_privé_exige_le_contexte_m1_et_sa_liste_fermee(monde):
    port = Capacites._lecteur_statut_client(monde, stockage.transaction)
    hors = port("m2_trouver_client_de_lead", {"lead_id": "lead-fictif"})
    assert hors["ok"] is False and hors["erreur"] == "contexte_m1_requis"
    with contexte.appeler_en_tant_que("m01-front-office", origine="m02-revenue-crm"):
        mauvaise_origine = port("m2_trouver_client_de_lead", {"lead_id": "lead-fictif"})
        assert mauvaise_origine["ok"] is False and mauvaise_origine["erreur"] == "contexte_m1_requis"
    with contexte.appeler_en_tant_que("m01-front-office"):
        interdit = port("m2_lister_leads", {"horodatage": APRES})
        assert interdit["ok"] is False and interdit["erreur"] == "lecture_non_autorisee"
        avec_arguments_non_objet = port("m2_trouver_client_de_lead", ["lead-fictif"])  # type: ignore[arg-type]
        assert avec_arguments_non_objet["ok"] is False and avec_arguments_non_objet["erreur"] == "arguments_invalides"
    # Département absent : refus nommé, jamais une valeur par défaut.
    seul_m1 = {"m01-front-office": monde["m01-front-office"]}
    port_sans_m3 = Capacites._lecteur_statut_client(seul_m1, stockage.transaction)
    with contexte.appeler_en_tant_que("m01-front-office"):
        absent = port_sans_m3("m3_lire_devis", {"devis_id": "D-1", "role": "employe"})
        assert absent["ok"] is False and absent["erreur"] == "lecteur_statut_client_indisponible"



def test_le_port_refuse_un_outil_absent_ou_non_t0(monde, monkeypatch):
    original = Capacites.__init__

    def sans_m3(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if kwargs.get("filtre") == {"m03-estimation"}:
            self.index.pop("m3_lire_devis", None)

    monkeypatch.setattr(Capacites, "__init__", sans_m3)
    port = Capacites._lecteur_statut_client(monde, stockage.transaction)
    with contexte.appeler_en_tant_que("m01-front-office"):
        absent = port("m3_lire_devis", {"devis_id": "D-1", "role": "employe"})
        assert absent["ok"] is False and absent["erreur"] == "lecteur_statut_client_indisponible"

    def non_t0(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if kwargs.get("filtre") == {"m03-estimation"}:
            departement, outil = self.index["m3_lire_devis"]
            self.index["m3_lire_devis"] = (departement, dataclasses.replace(outil, niveau=Niveau.N1))

    monkeypatch.setattr(Capacites, "__init__", non_t0)
    port = Capacites._lecteur_statut_client(monde, stockage.transaction)
    with contexte.appeler_en_tant_que("m01-front-office"):
        refuse = port("m3_lire_devis", {"devis_id": "D-1", "role": "employe"})
        assert refuse["ok"] is False and refuse["erreur"] == "lecture_non_autorisee"


def test_un_dossier_sans_lead_ne_lit_pas_m2(monde):
    _verifier("sms-" + "z" * 24)
    capacites = Capacites(
        {"m01-front-office": monde["m01-front-office"], "m02-revenue-crm": monde["m02-revenue-crm"]},
        stockage.transaction, memoire=False,
    )
    r = capacites.appeler("m1_statut_client", {"verification_id": VID, "sujet": "dossier", "horodatage": APRES})
    resultat = r["resultat"]["resultat"]
    assert resultat["statut"] == "repli" and resultat["motif"] == "lead_introuvable"
    assert resultat["reponse"] == "Je vais vérifier avec l'équipe."
