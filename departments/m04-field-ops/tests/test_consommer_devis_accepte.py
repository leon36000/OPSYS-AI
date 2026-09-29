"""M4 consomme `m3.devis_accepte` (ADR-0009 §3, PLAN T4.10-b ; DEFINITION-PRODUIT §6 « soumission acceptée -> M4
planifie », §7 M4.5 et M4.6) : le devis accepté fait naître une intervention `a_planifier`, sans import de M2 ni de M3,
et `m4_verifier_preparation` dit ce qui manque avant de la cédule, jamais « prêt » par défaut.

VRAI bus (`evenements.repartir`, manifestes réels), base SQLite migrée, VRAIS outils (`executer_atomique`). Seul M4
reçoit les événements ici (les comptes de `repartir()` sont ceux de M4). Le devis ne porte ni service, ni ville, ni
urgence : M4 les relit à la source du bus, dans le `m1.lead_qualifie` publié pour le lead ; un fait absent lève
(réessais, puis quarantaine), jamais une valeur par défaut. Le trajet complet M1 -> M2 -> M3 -> M4 (avec M5, M6 et
M8 comme avant) est prouvé par `tests/test_cascade_devis_accepte.py` du socle. Données fictives.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json

import pytest
from m4_field_ops import cedule
from m4_field_ops.outils import outils
from sqlalchemy import func, select

from opsys import cles_chiffrement, contexte, evenements, identite, stockage
from opsys import equipes as equipes_entreprise
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import CLES_CHIFFREMENT, EVENEMENTS_RECUS

M4 = "m04-field-ops"
ACCEPTE_LE = "2026-09-20T15:30:00-04:00"
RECU_LE = "2026-09-15T09:15:00-04:00"
DEBUT = dt.datetime(2026, 9, 20, 16, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
VILLE = "Repentigny"
PRIX_TOTAL = "1234.56"

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")


def _lead(lead_id: str, **surcharges) -> dict:
    lead = {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": f"sms-secrete-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "+15145550142", "courriel": f"{lead_id}@exemple-fictif.test"},
        "service": "gouttieres", "ville": VILLE, "urgence_declaree": False, "canal": "texte", "source": "sms",
    }
    lead.update(surcharges)
    return lead


def _publier_lead(lead: dict, evenement_id: str | None = None) -> str:
    identifiant = evenement_id or f"m1-lead-qualifie-{lead['lead_id']}"
    evenements.publier(
        "m1.lead_qualifie", "m01-front-office",
        {"lead": lead, "horodatage": RECU_LE, "signal_id": f"sms:{lead['lead_id']}"}, evenement_id=identifiant)
    return identifiant


def _devis_accepte(devis_id: str, lead_id: str, horodatage: str = ACCEPTE_LE) -> dict:
    return {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{
            "reference_ligne": f"{devis_id}-L0", "description": "Gouttières 5po aluminium (fictif)",
            "quantite": "40", "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": PRIX_TOTAL,
            "reference_besoin_materiau": "gouttiere_5po_alu",
        }],
        "cout_total": "987.65", "prix_total": PRIX_TOTAL, "taux_marge": "0.25",
        "horodatage_acceptation": horodatage,
    }


def _publier_devis(devis_id: str, lead_id: str, evenement_id: str | None = None,
                   horodatage: str = ACCEPTE_LE) -> str:
    identifiant = evenement_id or f"m3-devis-accepte-{devis_id}"
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte(devis_id, lead_id, horodatage),
                       evenement_id=identifiant)
    return identifiant


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def par_nom(instance):
    return {o.nom: o for o in outils()}


def _deps_bus():
    """Seul M4 reçoit `m3.devis_accepte` ici : les comptes de `repartir()` sont ceux de M4."""
    return {M4: charger_departements()[M4]}


def _repartir(instant: str = "2026-09-20T16:00:00-04:00") -> dict[str, int]:
    return evenements.repartir(_deps_bus(), maintenant=instant)


def _repartir_jusqu_au_bout(tours: int = 6) -> dict[str, int]:
    """Livre à intervalles de 100 s (le plus long délai de réessai est de 16 s) : cinq échecs ferment un événement."""
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(tours):
        resume = _repartir((DEBUT + dt.timedelta(seconds=100 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
    return total


def _maillons() -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons(M4, "principal"))


def _inscriptions() -> list[dict]:
    return [m for m in _maillons() if m["type_entree"] == "intervention_inscrite"]


def _recu(evenement_id: str) -> dict:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == M4)
        )).mappings().first()
    assert ligne is not None, f"aucun reçu pour {evenement_id}"
    return dict(ligne)


def _resultat(evenement_id: str) -> dict:
    return codec.decoder(_recu(evenement_id)["resultat"])


def _nb_cles() -> int:
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(CLES_CHIFFREMENT)).scalar_one()


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _plat(reponse):
    """Réponse d'un outil qui rend son résultat à plat (`m4_planifier_intervention`)."""
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _liste(reponse):
    """Réponse d'un outil de lecture qui rend une liste (`m4_lister_interventions`)."""
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


class TestManifeste:
    def test_la_fonction_est_branchee_au_vrai_manifeste_sans_import_entre_departements(self):
        dep = charger_departements()[M4]
        assert dep.evenements_consomme == ("m6.variance_chantier", "m3.devis_accepte", "m6.materiel_pret")
        assert dep.evenements_publie == ("m4.travaux_termines",)
        assert dep.charger_consommateurs()["m3.devis_accepte"].__name__ == "_recevoir_devis_accepte"
        assert set(dep.evenements_consomme) == set(dep.charger_consommateurs())
        assert evenements.verifier_coherence(charger_departements()) == []

    def test_les_dependances_disent_ce_que_m4_lit(self):
        assert set(charger_departements()[M4].dependances) == {
            "m01-front-office", "m03-estimation", "m06-material-control"}


class TestNominal:
    def test_le_devis_accepte_fait_naitre_une_intervention_a_planifier(self, instance):
        _publier_lead(_lead("LEAD-A"))
        evenement_id = _publier_devis("DEVIS-A", "LEAD-A")

        resume = _repartir()
        assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}

        (inscription,) = _inscriptions()
        assert inscription["statut"] == "a_planifier" and inscription["source"] == "m3.devis_accepte"
        assert (inscription["lead_id"], inscription["devis_id"]) == ("LEAD-A", "DEVIS-A")
        assert inscription["horodatage"] == ACCEPTE_LE, "l'heure de l'acceptation, jamais une horloge de M4"
        resultat = _resultat(evenement_id)
        assert resultat == {"traite": True, "devis_id": "DEVIS-A", "lead_id": "LEAD-A",
                            "intervention_id": inscription["intervention_id"], "statut": "a_planifier",
                            "service": "gouttieres"}
        assert evenements.etat()["quarantaine"] == []

    def test_service_et_urgence_viennent_du_lead_que_m1_a_publie(self, instance):
        _publier_lead(_lead("LEAD-B1", service="revetement", urgence_declaree=True))
        _publier_lead(_lead("LEAD-B2", service="soffite_fascia", urgence_declaree=False))
        _publier_devis("DEVIS-B1", "LEAD-B1")
        _publier_devis("DEVIS-B2", "LEAD-B2")
        assert _repartir()["traites"] == 2

        par_lead = {i["lead_id"]: i for i in _inscriptions()}
        assert (par_lead["LEAD-B1"]["service"], par_lead["LEAD-B1"]["urgence_declaree"]) == ("revetement", True)
        assert (par_lead["LEAD-B2"]["service"], par_lead["LEAD-B2"]["urgence_declaree"]) == ("soffite_fascia", False)

    def test_aucun_contact_ni_ville_ni_prix_n_entre_au_registre_de_m4(self, instance):
        _publier_lead(_lead("LEAD-C"))
        evenement_id = _publier_devis("DEVIS-C", "LEAD-C")
        _repartir()

        contenu = json.dumps(_maillons(), ensure_ascii=False, sort_keys=True)
        for interdit in ("Client Fictif", "+15145550142", "exemple-fictif", VILLE, "sms-secrete", "contact", PRIX_TOTAL,
                         "987.65", "prix_total", "cout_total", "taux_marge", "lignes"):
            assert interdit not in contenu, interdit
        resultat = json.dumps(_resultat(evenement_id), ensure_ascii=False)
        for interdit in ("Client Fictif", VILLE, "sms-secrete", PRIX_TOTAL):
            assert interdit not in resultat, interdit

    def test_la_ville_est_tokenisee_avec_un_sel_d_instance_stable_du_coffre(self, instance):
        _publier_lead(_lead("LEAD-D1"))
        _publier_lead(_lead("LEAD-D2"))
        _publier_devis("DEVIS-D1", "LEAD-D1")
        _publier_devis("DEVIS-D2", "LEAD-D2")
        _repartir()

        jetons = {i["ville_tokenisee"] for i in _inscriptions()}
        assert len(jetons) == 1, "même ville, même sel d'instance : même jeton"
        with stockage.transaction() as cnx:
            sel = cles_chiffrement.lire(cnx, "m04-field-ops/sel-ville", "instance")
        assert sel is not None and _nb_cles() == 1, "un seul secret, créé une fois"
        assert jetons == {cedule.tokeniser_ville(sel.hex(), VILLE)}
        assert sel.hex() not in json.dumps(_maillons()), "le sel ne quitte jamais le coffre"

    def test_l_intervention_est_visible_de_l_admin_et_annulable(self, par_nom):
        _publier_lead(_lead("LEAD-E"))
        _publier_devis("DEVIS-E", "LEAD-E")
        _repartir()

        (ligne,) = _liste(_appeler(par_nom, "m4_lister_interventions", {"statut": "a_planifier"}, ADMIN))
        assert ligne["statut"] == "a_planifier" and ligne["service"] == "gouttieres"
        assert ligne["devis_id"] == "DEVIS-E" and ligne["technicien_assigne"] is None
        assert _liste(_appeler(par_nom, "m4_lister_interventions", {"statut": "planifiee"}, ADMIN)) == []
        # l'employé ne voit pas une intervention qui n'est à personne
        assert _liste(_appeler(par_nom, "m4_lister_interventions", {}, MARC)) == []

        accuse = _ok(_appeler(par_nom, "m4_annuler_intervention", {
            "intervention_id": ligne["intervention_id"], "horodatage": "2026-09-21T09:00:00-04:00"}))
        assert accuse["statut"] == "annulee" and accuse["statut_precedent"] == "a_planifier"


class TestIdempotence:
    def test_un_evenement_rejoue_ne_cree_pas_de_seconde_intervention(self, instance):
        _publier_lead(_lead("LEAD-F"))
        evenement_id = _publier_devis("DEVIS-F", "LEAD-F")
        _repartir()
        maillons = json.dumps(_maillons(), sort_keys=True)

        assert _publier_devis("DEVIS-F", "LEAD-F", evenement_id=evenement_id) == evenement_id  # no-op du bus
        assert _repartir("2026-09-20T16:05:00-04:00")["livres"] == 0
        assert json.dumps(_maillons(), sort_keys=True) == maillons

    def test_le_meme_devis_sous_un_autre_evenement_est_deja_applique(self, instance):
        _publier_lead(_lead("LEAD-G"))
        _publier_devis("DEVIS-G", "LEAD-G")
        _repartir()
        maillons = json.dumps(_maillons(), sort_keys=True)
        (inscription,) = _inscriptions()

        autre = _publier_devis("DEVIS-G", "LEAD-G", evenement_id="rejeu-par-un-autre-producteur")
        resume = _repartir("2026-09-20T16:05:00-04:00")
        assert resume["traites"] == 1 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
        assert _resultat(autre) == {"traite": True, "devis_id": "DEVIS-G", "lead_id": "LEAD-G",
                                    "intervention_id": inscription["intervention_id"], "deja_applique": True}
        assert json.dumps(_maillons(), sort_keys=True) == maillons

    def test_une_intervention_planifiee_a_la_main_pour_ce_devis_n_a_pas_de_double(self, par_nom):
        """Le flux d'avant : `m4_planifier_intervention` avec le `devis_id`. Le bus le reconnaît AVANT toute lecture
        (aucun `m1.lead_qualifie` n'est même nécessaire) : pas de seconde intervention à côté de la sienne."""
        contrat = {
            "lead_id": "LEAD-H", "conversation_id": "C-H", "type_travaux": "renovation_totale", "ville": VILLE,
            "canal": "telephone", "contact": {"nom": "Dupont", "telephone": "0102030405"}, "urgence_declaree": False,
        }
        marqueur = {"readiness_ok": True, "lead_id": "LEAD-H", "hash_tete_registre": None,
                    "horodatage": "2026-09-15T12:00:00+00:00", "empreinte": "ab" * 32}
        plan = _plat(_appeler(par_nom, "m4_planifier_intervention", {
            "contrat": contrat, "marqueur": marqueur, "horodatage": "2026-09-18T08:00:00+00:00", "sel": "sel-fictif",
            "techniciens_disponibles": ["T1"],
            "fenetres_disponibles": [{"debut": "2026-09-22T07:00:00+00:00", "fin": "2026-09-22T19:00:00+00:00"}],
            "devis_id": "DEVIS-H"}))
        evenement_id = _publier_devis("DEVIS-H", "LEAD-H")

        assert _repartir()["traites"] == 1
        assert [i["intervention_id"] for i in _inscriptions()] == [plan["intervention_id"]]
        assert _resultat(evenement_id)["deja_applique"] is True
        assert _resultat(evenement_id)["intervention_id"] == plan["intervention_id"]


class TestFaitsManquants:
    def test_sans_lead_de_m1_le_devis_est_reessaye_puis_mis_en_quarantaine_sans_valeur_par_defaut(self, instance):
        evenement_id = _publier_devis("DEVIS-I", "LEAD-I")

        total = _repartir_jusqu_au_bout()
        assert total["quarantaines"] == 1 and total["echecs"] == 4 and total["traites"] == 0, total
        recu = _recu(evenement_id)
        assert recu["statut"] == "quarantaine" and recu["tentatives"] == 5
        erreur = recu["derniere_erreur"]
        assert "FaitDeLeadManquant" in erreur and "service, ville et urgence du chantier introuvables" in erreur
        assert "m1-lead-qualifie-LEAD-I" in erreur and "m4_planifier_intervention" in erreur
        assert _maillons() == [] and _nb_cles() == 0, "ni intervention, ni sel créé pour rien"
        (en_quarantaine,) = evenements.etat()["quarantaine"]
        assert en_quarantaine["type_evenement"] == "m3.devis_accepte" and en_quarantaine["consommateur"] == M4

    def test_ordre_inverse_le_devis_arrive_avant_le_lead_puis_tout_se_rejoue_sans_doublon(self, instance):
        evenement_id = _publier_devis("DEVIS-J", "LEAD-J")
        premier = _repartir("2026-09-20T16:00:00-04:00")
        assert premier["echecs"] == 1 and premier["traites"] == 0 and premier["quarantaines"] == 0, premier
        assert _recu(evenement_id)["statut"] == "echec" and _inscriptions() == []

        _publier_lead(_lead("LEAD-J"))  # M1 publie enfin le lead
        suite = _repartir("2026-09-20T16:05:00-04:00")  # le délai de réessai est écoulé
        assert suite["traites"] == 1 and suite["echecs"] == 0, suite

        (inscription,) = _inscriptions()
        assert inscription["lead_id"] == "LEAD-J" and inscription["devis_id"] == "DEVIS-J"
        assert _recu(evenement_id)["statut"] == "traite"
        assert _repartir("2026-09-20T16:10:00-04:00")["livres"] == 0
        assert len(_inscriptions()) == 1

    def test_le_lead_publie_sous_l_identifiant_d_un_autre_ne_sert_pas(self, instance):
        """L'identifiant d'événement est une convention : la charge doit être celle du lead demandé."""
        _publier_lead(_lead("LEAD-AUTRE"), evenement_id="m1-lead-qualifie-LEAD-K")
        evenement_id = _publier_devis("DEVIS-K", "LEAD-K")

        total = _repartir_jusqu_au_bout()
        assert total["quarantaines"] == 1, total
        assert "FaitDeLeadManquant" in _recu(evenement_id)["derniere_erreur"]
        assert _inscriptions() == []

    def test_un_service_retire_du_profil_depuis_la_qualification_est_refuse_sans_ecriture(self, instance):
        _publier_lead(_lead("LEAD-L", service="service-retire-du-profil"))
        evenement_id = _publier_devis("DEVIS-L", "LEAD-L")

        total = _repartir_jusqu_au_bout()
        assert total["quarantaines"] == 1, total
        erreur = _recu(evenement_id)["derniere_erreur"]
        assert "InscriptionDevisRefusee" in erreur and "REJ-ENUM-INVALIDE" in erreur
        assert _maillons() == []
        assert _nb_cles() == 0, "le sel créé pendant la tentative est annulé avec elle"

    def test_un_horodatage_d_acceptation_invalide_est_refuse_sans_ecriture(self, instance):
        _publier_lead(_lead("LEAD-M"))
        evenement_id = _publier_devis("DEVIS-M", "LEAD-M", horodatage="hier après-midi")

        total = _repartir_jusqu_au_bout()
        assert total["quarantaines"] == 1, total
        assert "REJ-HORODATAGE-INVALIDE" in _recu(evenement_id)["derniere_erreur"]
        assert _maillons() == [] and _nb_cles() == 0


class TestVerifierPreparation:
    """`m4_verifier_preparation` (T0) : le verdict nomme ce qui manque, volet par volet, jamais « prêt » par défaut."""

    def _naitre(self, par_nom, lead_id="LEAD-P", devis_id="DEVIS-P") -> str:
        _publier_lead(_lead(lead_id))
        _publier_devis(devis_id, lead_id)
        assert _repartir()["traites"] == 1
        (ligne,) = _liste(_appeler(par_nom, "m4_lister_interventions", {"statut": "a_planifier"}, ADMIN))
        return ligne["intervention_id"]

    def test_sans_adresse_confirmee_le_verdict_bloque_et_dit_quoi_faire(self, par_nom):
        iid = self._naitre(par_nom)
        verdict = _ok(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iid}, ADMIN))

        assert verdict["statut"] == "bloque" and verdict["pret"] is False
        assert verdict["statut_intervention"] == "a_planifier"
        volets = verdict["volets"]
        assert volets["soumission"]["statut"] == "ok" and "DEVIS-P" in volets["soumission"]["detail"]
        assert volets["adresse"]["statut"] == "manque" and "à confirmer" in volets["adresse"]["manque"]
        assert volets["adresse"]["detail"] == "REJ-COORDONNEES-A-CONFIRMER"
        # T4.12 : sans profil des équipes, l'équipe n'est plus « non vérifiable » (M4 sait la lire) : elle MANQUE, et le
        # volet dit quoi déclarer. T4.14-b : sans charge de M6, le matériel reste non vérifiable. T4.13 : sans profil
        # météo, la météo MANQUE (seuil à configurer) et dit quoi déclarer.
        assert volets["equipe"]["statut"] == "manque" and "opsys equipes declarer" in volets["equipe"]["manque"]
        assert volets["materiel"]["statut"] == "non_verifiable" and volets["materiel"]["manque"]
        assert volets["meteo"]["statut"] == "manque" and "opsys meteo declarer" in volets["meteo"]["manque"]
        assert volets["meteo"]["detail"] == "REJ-METEO-NON-CONFIGUREE"
        assert [f["volet"] for f in verdict["a_fournir"]] == ["adresse", "equipe", "materiel", "meteo"]

    def test_meme_avec_l_adresse_confirmee_le_verdict_n_est_pas_pret(self, par_nom):
        iid = self._naitre(par_nom)
        _ok(_appeler(par_nom, "m4_confirmer_localisation", {
            "chantier_id": "LEAD-P", "action": "confirmee", "horodatage": "2026-09-21T09:00:00-04:00",
            "confirme_par": "admin.fictif", "adresse": {
                "numero_municipal": "100", "odonyme": "boulevard Iberville", "municipalite": VILLE},
            "source": "manuel", "latitude_microdegres": 45741500, "longitude_microdegres": -73450500,
            "motif": "relevé sur place (fictif)"}, ADMIN))

        verdict = _ok(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iid}, ADMIN))
        assert verdict["volets"]["adresse"]["statut"] == "ok"
        assert verdict["volets"]["adresse"]["detail"] == "coordonnées confirmées (version 1)"
        assert verdict["statut"] == "bloque" and verdict["pret"] is False, "sans profil, l'équipe manque"
        assert [f["volet"] for f in verdict["a_fournir"]] == ["equipe", "materiel", "meteo"]
        # Le profil déclaré (gouttières : durée et compétence ; une équipe qui les a), l'équipe devient vérifiée ;
        # sans charge de M6 ni règles météo, le verdict n'est pas « prêt », jamais.
        equipes_entreprise.enregistrer_equipes({
            "liste": [{"id": "equipe-fictive", "membres": ["marc.fictif"], "competences": ["gouttieres"],
                       "depot": {"id": "depot-fictif", "latitude_microdegres": 45735000,
                                 "longitude_microdegres": -73455000},
                       "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}]}],
            "services": {"gouttieres": {"duree_min": 90, "competences": ["gouttieres"]}},
        })
        verdict = _ok(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iid}, ADMIN))
        assert verdict["volets"]["equipe"]["statut"] == "ok"
        assert "equipe-fictive" in verdict["volets"]["equipe"]["detail"]
        assert verdict["statut"] == "bloque" and verdict["pret"] is False, "la météo manque : seuil à configurer"
        assert [f["volet"] for f in verdict["a_fournir"]] == ["materiel", "meteo"]
        texte = json.dumps(verdict, ensure_ascii=False)
        for interdit in ("45741500", "-73450500", "latitude", "longitude", "Client Fictif", VILLE, PRIX_TOTAL):
            assert interdit not in texte, interdit

    def test_la_lecture_n_ecrit_rien(self, par_nom):
        iid = self._naitre(par_nom)
        avant = json.dumps(_maillons(), sort_keys=True)
        cles = _nb_cles()
        _ok(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iid}, ADMIN))
        _ok(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iid}))  # appel d'agent
        assert json.dumps(_maillons(), sort_keys=True) == avant and _nb_cles() == cles

    def test_intervention_inconnue_ou_hors_preparation(self, par_nom):
        assert _refus(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": "inconnue"}, ADMIN)) == (
            "REJ-TRANSITION-ILLEGALE")
        iid = self._naitre(par_nom)
        _ok(_appeler(par_nom, "m4_annuler_intervention", {
            "intervention_id": iid, "horodatage": "2026-09-21T09:00:00-04:00"}))
        assert _refus(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iid}, ADMIN)) == (
            "REJ-TRANSITION-ILLEGALE")

    @pytest.mark.parametrize("appelant", [MARC, VENDEUR], ids=["employe", "vendeur"])
    def test_reserve_a_l_admin_refuse_aussi_dans_l_outil(self, par_nom, appelant):
        iid = self._naitre(par_nom)
        avant = json.dumps(_maillons(), sort_keys=True)
        assert _refus(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": iid}, appelant)) == (
            "REJ-IDENTITE-APPAREIL-INVALIDE")
        assert json.dumps(_maillons(), sort_keys=True) == avant

    def test_l_outil_est_de_lecture_et_de_portee_admin_seulement(self, par_nom):
        outil = par_nom["m4_verifier_preparation"]
        assert outil.autonomie.name == "T0" and outil.roles_appareil == frozenset({"admin"})
        assert not outil.frontiere_humaine

    def test_un_identifiant_absent_ou_vide_ne_donne_jamais_un_verdict(self, par_nom):
        reponse = executer_atomique(par_nom["m4_verifier_preparation"], {})
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
        assert _refus(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": ""}, ADMIN)) == (
            "REJ-TRANSITION-ILLEGALE")
