"""PLAN T4.10-b (M4.5) : l'état `a_planifier` et l'inscription d'une intervention depuis un devis accepté, sur un
registre EN MÉMOIRE (aucune base, aucun bus : le consommateur du bus est prouvé par
`test_consommer_devis_accepte.py`).

La table complète des transitions (les seize d'avant, les deux nouvelles, et toutes les illégales) est balayée par
`test_etats.py`. Ici : ce que l'inscription écrit et refuse, et la porte `a_planifier -> planifiee`, qui exige un
verdict de préparation « pret » et reste fermée à tout autre. Données fictives.
"""

from __future__ import annotations

import copy
import json

import pytest
from m4_field_ops import cedule, cedule_tournees, etats, preparation, registre

HORO = "2026-09-29T10:00:00-04:00"
HORO_APRES = "2026-09-29T11:00:00-04:00"
SEL = "sel-a-planifier-fictif"
VILLE = "Repentigny"


def _lead(**surcharges):
    lead = {
        "schema_version": 2, "lead_id": "LEAD-T410", "conversation_id": "conv-secrete-T410",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100", "courriel": "client@exemple-fictif.test"},
        "service": "gouttieres", "ville": VILLE, "urgence_declaree": True, "canal": "texte",
    }
    lead.update(surcharges)
    return lead


@pytest.fixture(autouse=True)
def _services_declares(declarer_services):
    declarer_services()


@pytest.fixture
def reg():
    return registre.Registre()


@pytest.fixture
def inscrite(reg):
    accuse, verdict = etats.inscrire_depuis_devis(reg, "DEVIS-T410", _lead(), SEL, HORO)
    assert verdict is None, verdict
    return accuse


def _verdict_pret(intervention_id):
    volets = {nom: {"statut": "ok", "manque": None, "detail": None} for nom in preparation.VOLETS}
    verdict = {"intervention_id": intervention_id, "statut_intervention": "a_planifier", "statut": "pret",
               "pret": True, "volets": volets, "a_fournir": []}
    verdict["empreinte"] = etats.empreinte_preparation(verdict)
    return verdict


def _lire_position_ok(_registre, _chantier_id):
    return {"version": 1}, None


class TestInscriptionDepuisUnDevis:
    def test_l_intervention_naît_a_planifier_avec_ce_que_le_lead_dit(self, reg, inscrite):
        assert inscrite["statut"] == "a_planifier"
        assert set(inscrite) == {"intervention_id", "ligne_id", "statut", "empreinte_maillon", "tete_chaine",
                                 "horodatage"}
        assert etats.statut_courant(reg, inscrite["intervention_id"]) == "a_planifier"
        assert reg.valider_chaine() is True
        (maillon,) = reg.lire()
        assert maillon["type_entree"] == etats.TYPE_INSCRIPTION
        assert maillon["statut"] == "a_planifier" and maillon["source"] == etats.SOURCE_DEVIS_ACCEPTE
        assert (maillon["lead_id"], maillon["devis_id"], maillon["service"]) == (
            "LEAD-T410", "DEVIS-T410", "gouttieres")
        assert maillon["schema_version"] == 2 and maillon["urgence_declaree"] is True
        assert maillon["horodatage"] == HORO, "l'heure de l'acceptation, jamais une horloge de M4"

    def test_le_maillon_ne_porte_ni_contact_ni_ville_ni_conversation_ni_prix(self, reg, inscrite):
        (maillon,) = reg.lire()
        texte = json.dumps(maillon, ensure_ascii=False)
        for interdit in ("Client Fictif", "418-555-0100", "exemple-fictif", VILLE, "conv-secrete-T410", "contact",
                         "prix", "montant", "cout", "marge"):
            assert interdit not in texte, interdit
        assert maillon["ville_tokenisee"] == cedule.tokeniser_ville(SEL, VILLE)
        assert len(maillon["ville_tokenisee"]) == 64

    def test_un_lead_v2_sans_urgence_declaree_vrai_garde_faux(self, reg):
        accuse, verdict = etats.inscrire_depuis_devis(
            reg, "DEVIS-2", _lead(urgence_declaree=False, lead_id="LEAD-2"), SEL, HORO)
        assert verdict is None
        assert reg.lire()[-1]["urgence_declaree"] is False

    def test_l_identifiant_est_deterministe_et_propre_au_devis(self, reg):
        a, _ = etats.inscrire_depuis_devis(reg, "DEVIS-A", _lead(), SEL, HORO)
        b, _ = etats.inscrire_depuis_devis(registre.Registre(), "DEVIS-A", _lead(), "autre-sel", HORO_APRES)
        c, _ = etats.inscrire_depuis_devis(reg, "DEVIS-B", _lead(), SEL, HORO)
        assert a["intervention_id"] == b["intervention_id"], "ni le sel ni l'heure ne changent l'identité"
        assert a["intervention_id"] != c["intervention_id"]

    def test_la_liste_montre_le_service_sans_technicien_ni_fenetre(self, reg, inscrite):
        (ligne,) = etats.lister_interventions(reg)
        assert ligne == {
            "intervention_id": inscrite["intervention_id"], "statut": "a_planifier", "lead_id": "LEAD-T410",
            "service": "gouttieres", "devis_id": "DEVIS-T410", "technicien_assigne": None,
            "fenetre_planifiee": None,
        }
        assert etats.lister_interventions(reg, statut="a_planifier") == [ligne]
        assert etats.lister_interventions(reg, statut="planifiee") == []

    def test_un_devis_n_a_qu_une_intervention(self, reg, inscrite):
        taille = len(reg.lire())
        accuse, verdict = etats.inscrire_depuis_devis(reg, "DEVIS-T410", _lead(), SEL, HORO_APRES)
        assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE"
        assert "un devis n'a qu'une intervention" in verdict["detail"]
        assert len(reg.lire()) == taille
        assert etats.intervention_du_devis(reg, "DEVIS-T410") == inscrite["intervention_id"]
        assert etats.intervention_du_devis(reg, "AUTRE") is None
        assert etats.intervention_du_devis(reg, "") is None and etats.intervention_du_devis(reg, None) is None

    def test_une_intervention_planifiee_a_la_main_pour_ce_devis_compte_aussi(self, reg):
        contrat = {
            "lead_id": "LEAD-MAIN", "conversation_id": "C", "type_travaux": "renovation_totale", "ville": VILLE,
            "canal": "telephone", "contact": {"nom": "Dupont", "telephone": "0102030405"}, "urgence_declaree": False,
        }
        marqueur = {"readiness_ok": True, "lead_id": "LEAD-MAIN", "hash_tete_registre": None,
                    "horodatage": "2026-09-28T12:00:00+00:00", "empreinte": "ab" * 32}
        legacy, verdict = etats.inscrire_intervention(contrat, marqueur, reg, HORO, SEL, devis_id="DEVIS-MAIN")
        assert verdict is None
        assert etats.intervention_du_devis(reg, "DEVIS-MAIN") == legacy["intervention_id"]
        accuse, verdict = etats.inscrire_depuis_devis(reg, "DEVIS-MAIN", _lead(lead_id="LEAD-MAIN"), SEL, HORO)
        assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE"

    @pytest.mark.parametrize(("devis_id", "code"), [("", "REJ-CHAMP-VIDE"), (None, "REJ-CONTRAT-INVALIDE"),
                                                    (7, "REJ-CONTRAT-INVALIDE")])
    def test_devis_id_invalide(self, reg, devis_id, code):
        accuse, verdict = etats.inscrire_depuis_devis(reg, devis_id, _lead(), SEL, HORO)
        assert accuse is None and verdict["code"] == code and reg.lire() == []

    def test_frontiere_violee(self, reg):
        accuse, verdict = etats.inscrire_depuis_devis(reg, "D", _lead(prix=1200), SEL, HORO)
        assert accuse is None and verdict["code"] == "REJ-FRONTIERE-VIOLEE" and reg.lire() == []

    def test_un_lead_v1_est_refuse_c_est_le_contrat_que_m1_publie_qui_est_attendu(self, reg):
        v1 = {"lead_id": "L", "conversation_id": "C", "type_travaux": "renovation_totale", "ville": VILLE,
              "canal": "telephone", "contact": {"nom": "Dupont"}, "urgence_declaree": False}
        accuse, verdict = etats.inscrire_depuis_devis(reg, "D", v1, SEL, HORO)
        assert accuse is None and verdict["code"] == "REJ-CONTRAT-INVALIDE" and "v2" in verdict["detail"]
        assert etats.inscrire_depuis_devis(reg, "D", "pas un lead", SEL, HORO)[1]["code"] == "REJ-CONTRAT-INVALIDE"
        assert reg.lire() == []

    def test_un_service_hors_du_profil_d_entreprise_est_refuse_sans_repli(self, reg):
        accuse, verdict = etats.inscrire_depuis_devis(reg, "D", _lead(service="service-inconnu"), SEL, HORO)
        assert accuse is None and verdict["code"] == "REJ-ENUM-INVALIDE" and reg.lire() == []

    def test_un_champ_manquant_du_lead_est_refuse(self, reg):
        lead = _lead()
        del lead["ville"]
        accuse, verdict = etats.inscrire_depuis_devis(reg, "D", lead, SEL, HORO)
        assert accuse is None and verdict["code"] == "REJ-CHAMP-MANQUANT" and reg.lire() == []

    @pytest.mark.parametrize("sel", ["", None, 12])
    def test_sel_absent(self, reg, sel):
        accuse, verdict = etats.inscrire_depuis_devis(reg, "D", _lead(), sel, HORO)
        assert accuse is None and verdict["code"] == "REJ-CONTRAT-INVALIDE" and reg.lire() == []

    @pytest.mark.parametrize("horodatage", ["hier", "2026-09-29T10:00:00", None])
    def test_horodatage_invalide(self, reg, horodatage):
        accuse, verdict = etats.inscrire_depuis_devis(reg, "D", _lead(), SEL, horodatage)
        assert accuse is None and verdict["code"] == "REJ-HORODATAGE-INVALIDE" and reg.lire() == []


class TestSortiesDeAPlanifier:
    def test_annuler_est_permis_sans_condition(self, reg, inscrite):
        accuse, verdict = etats.transitionner(inscrite["intervention_id"], "annulee", reg, HORO_APRES)
        assert verdict is None and accuse["statut"] == "annulee" and accuse["statut_precedent"] == "a_planifier"

    @pytest.mark.parametrize("cible", ["en_route", "sur_site", "en_revue", "reportee"])
    def test_on_ne_part_pas_ni_ne_reporte_une_intervention_a_planifier(self, reg, inscrite, cible):
        taille = len(reg.lire())
        motif = "meteo" if cible == "reportee" else None
        accuse, verdict = etats.transitionner(
            inscrite["intervention_id"], cible, reg, HORO_APRES, motif=motif,
            assignation={"intervention_id": inscrite["intervention_id"], "technicien_id": "T1"}
            if cible == "en_route" else None)
        assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE"
        assert len(reg.lire()) == taille

    def test_les_deux_completions_restent_refusees(self, reg, inscrite):
        for cible in ("completed_pending_review", "completed_verified"):
            accuse, verdict = etats.transitionner(inscrite["intervention_id"], cible, reg, HORO_APRES)
            assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE"


class TestPorteAPlanifieeVersPlanifiee:
    """`a_planifier -> planifiee` exige un verdict de préparation « pret » de CETTE intervention. Tant que
    l'équipe, le matériel et la météo n'ont pas de source dans M4, aucun verdict réel ne l'est."""

    def test_sans_verdict_la_porte_est_fermee_et_rien_n_est_ecrit(self, reg, inscrite):
        taille = len(reg.lire())
        accuse, verdict = etats.transitionner(inscrite["intervention_id"], "planifiee", reg, HORO_APRES)
        assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE"
        assert "préparation" in verdict["detail"] and "pret" in verdict["detail"]
        assert len(reg.lire()) == taille
        assert etats.statut_courant(reg, inscrite["intervention_id"]) == "a_planifier"

    def test_un_verdict_pret_ouvre_la_porte_et_la_transition_consigne_son_empreinte(self, reg, inscrite):
        iid = inscrite["intervention_id"]
        pret = _verdict_pret(iid)
        accuse, verdict = etats.transitionner(iid, "planifiee", reg, HORO_APRES, preparation=pret)
        assert verdict is None and accuse["statut"] == "planifiee" and accuse["statut_precedent"] == "a_planifier"
        maillon = reg.lire()[-1]
        assert maillon["empreinte_preparation"] == pret["empreinte"]
        assert "volets" not in maillon and "preparation" not in maillon, "l'empreinte, pas le verdict"
        # devenue planifiable : la cédule par tournées la voit désormais
        instantane = cedule_tournees._Instantane(reg.lire())
        a_planifier, refus = cedule_tournees._interventions_a_planifier(
            instantane, cedule_tournees._inscriptions(instantane), None)
        assert refus is None and [i["intervention_id"] for i in a_planifier] == [iid]

    def test_le_verdict_reel_d_aujourd_hui_ne_l_ouvre_jamais(self, reg, inscrite):
        iid = inscrite["intervention_id"]
        reel, refus = preparation.evaluer(reg, iid, _lire_position_ok)
        assert refus is None and reel["pret"] is False
        accuse, verdict = etats.transitionner(iid, "planifiee", reg, HORO_APRES, preparation=reel)
        assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE"
        assert etats.statut_courant(reg, iid) == "a_planifier"

    @pytest.mark.parametrize("truquage", [
        lambda v: v.update(statut="bloque"),
        lambda v: v.update(pret=False),
        lambda v: v.update(intervention_id="une-autre"),
        lambda v: v.update(empreinte="0" * 64),
        lambda v: v.pop("empreinte"),
        lambda v: v["volets"]["meteo"].update(statut="non_verifiable"),
        lambda v: v["volets"].pop("meteo"),
        lambda v: v.update(volets={}),
        lambda v: v.update(volets="ok"),
    ], ids=["statut-bloque", "pret-faux", "autre-intervention", "empreinte-fausse", "sans-empreinte",
            "volet-non-verifiable", "volet-retire-sans-recalcul", "aucun-volet", "volets-pas-un-objet"])
    def test_un_verdict_truque_ou_d_une_autre_intervention_ne_passe_pas(self, reg, inscrite, truquage):
        iid = inscrite["intervention_id"]
        verdict_pret = _verdict_pret(iid)
        truquage(verdict_pret)
        taille = len(reg.lire())
        accuse, verdict = etats.transitionner(iid, "planifiee", reg, HORO_APRES, preparation=verdict_pret)
        assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE"
        assert len(reg.lire()) == taille

    def test_un_dictionnaire_quelconque_ne_passe_pas(self, reg, inscrite):
        for preparation_bidon in ({}, {"pret": True}, {"statut": "pret", "pret": True}, "pret", 1, [], True):
            accuse, verdict = etats.transitionner(
                inscrite["intervention_id"], "planifiee", reg, HORO_APRES, preparation=preparation_bidon)
            assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE", preparation_bidon

    def test_le_verdict_d_une_autre_intervention_ne_sert_pas(self, reg, inscrite):
        autre, _ = etats.inscrire_depuis_devis(reg, "DEVIS-AUTRE", _lead(lead_id="LEAD-AUTRE"), SEL, HORO)
        pret_d_une_autre = _verdict_pret(autre["intervention_id"])
        accuse, verdict = etats.transitionner(
            inscrite["intervention_id"], "planifiee", reg, HORO_APRES, preparation=pret_d_une_autre)
        assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE"

    def test_le_verdict_n_est_accepte_que_pour_cette_transition(self, reg, inscrite):
        iid = inscrite["intervention_id"]
        accuse, verdict = etats.transitionner(iid, "annulee", reg, HORO_APRES, preparation=_verdict_pret(iid))
        assert accuse is None and verdict["code"] == "REJ-ENUM-INVALIDE"
        assert "réservée à la transition a_planifier -> planifiee" in verdict["detail"]

    def test_le_verdict_n_est_pas_accepte_pour_les_transitions_d_avant(self, reg):
        contrat = {
            "lead_id": "L-AV", "conversation_id": "C", "type_travaux": "renovation_totale", "ville": VILLE,
            "canal": "telephone", "contact": {"nom": "Dupont", "telephone": "0102030405"}, "urgence_declaree": False,
        }
        marqueur = {"readiness_ok": True, "lead_id": "L-AV", "hash_tete_registre": None,
                    "horodatage": "2026-09-28T12:00:00+00:00", "empreinte": "ab" * 32}
        accuse, _ = etats.inscrire_intervention(contrat, marqueur, reg, HORO, SEL)
        iid = accuse["intervention_id"]
        accuse, verdict = etats.transitionner(
            iid, "en_route", reg, HORO_APRES, assignation={"intervention_id": iid, "technicien_id": "T1"},
            preparation=_verdict_pret(iid))
        assert accuse is None and verdict["code"] == "REJ-ENUM-INVALIDE"
        # reportee -> planifiee n'a jamais exigé de préparation : inchangé
        assert etats.transitionner(iid, "reportee", reg, HORO_APRES, motif="meteo")[1] is None
        assert etats.transitionner(iid, "planifiee", reg, "2026-09-29T12:00:00-04:00")[1] is None


class TestCeduleParTourneesInchangee:
    def test_une_intervention_a_planifier_n_entre_pas_dans_la_cedule(self, reg, inscrite):
        """L'état est additif : la cédule par tournées ne planifie toujours que `planifiee`."""
        instantane = cedule_tournees._Instantane(copy.deepcopy(reg.lire()))
        inscriptions = cedule_tournees._inscriptions(instantane)
        rien, refus = cedule_tournees._interventions_a_planifier(instantane, inscriptions, None)
        assert rien is None and refus["code"] == "REJ-CEDULE-RIEN-A-PLANIFIER"
        demandee, refus = cedule_tournees._interventions_a_planifier(
            instantane, inscriptions, [inscrite["intervention_id"]])
        assert demandee is None and refus["code"] == "REJ-CEDULE-INTERVENTION-NON-PLANIFIABLE"
        assert cedule_tournees.STATUT_PLANIFIABLE == "planifiee"
