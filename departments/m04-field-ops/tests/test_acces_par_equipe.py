"""PLAN T4.12 (hors spécification, isolé) : un employé agit aussi sur l'intervention assignée à l'ÉQUIPE dont il est
membre selon le profil de l'entreprise. Sans cela, les équipes qu'assigne la cédule (`m4_appliquer_cedule` : le
`technicien_id` de l'assignation est l'identifiant de l'équipe) seraient invisibles de leurs propres membres.

`acces.py` pur, puis les VRAIS outils sur une base migrée et le VRAI profil (`entreprise.yaml`). Chaque refus prouve
qu'aucun maillon n'a été écrit. Fictif : personnes, équipes et interventions.
"""

from __future__ import annotations

import contextlib
import copy
import datetime as dt

import pytest
import yaml
from m4_field_ops import acces, etats
from m4_field_ops import registre as registre_m4
from m4_field_ops.outils import outils

from opsys import contexte, identite, stockage, taxonomie
from opsys import equipes as equipes_entreprise
from opsys.outils import executer_atomique

FICTIF = True
HORO = "2030-01-01T08:00:00+00:00"
LUC = contexte.IdentiteAppelante(personne="luc.fictif", role="employee")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
NADIA = contexte.IdentiteAppelante(personne="nadia.fictif", role="employee")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
PROFIL = {
    "liste": [
        {"id": "eq-a", "membres": ["luc.fictif", "marc.fictif"], "competences": ["gouttieres"],
         "depot": {"id": "depot-fictif", "latitude_microdegres": 45735000, "longitude_microdegres": -73455000},
         "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}]},
        {"id": "eq-b", "membres": ["nadia.fictif"], "competences": ["gouttieres"],
         "depot": {"id": "depot-fictif", "latitude_microdegres": 45735000, "longitude_microdegres": -73455000},
         "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}]},
    ],
}


# =========================================================================================
# 1. `acces.py`, pur
# =========================================================================================
class _Registre:
    def __init__(self, technicien):
        self.technicien = technicien

    def lire(self, depuis=None):
        if self.technicien is None:
            return [{"type_entree": "intervention_inscrite", "intervention_id": "I1", "statut": "planifiee"}]
        return [
            {"type_entree": "intervention_inscrite", "intervention_id": "I1", "statut": "planifiee"},
            {"type_entree": "assignation_technicien", "intervention_id": "I1", "technicien_id": self.technicien},
        ]


def _employe(equipes=()):
    acteur, verdict = acces.acteur_de("luc.fictif", "employee", equipes)
    assert verdict is None
    return acteur


def test_un_acteur_porte_ses_equipes_et_sans_equipe_il_n_en_a_aucune():
    assert acces.acteur_de("luc.fictif", "employee")[0].equipes == ()
    assert _employe(["eq-a"]).equipes == ("eq-a",)
    assert acces.acteur_de("x", "vendeur", ("eq-a",))[0] is None  # un autre rôle n'a aucune portée, équipe ou non


@pytest.mark.parametrize(("technicien", "equipes", "attendu_ok"), [
    ("luc.fictif", (), True),              # assignée à lui : comme avant T4.12
    ("luc.fictif", ("eq-a",), True),
    ("eq-a", ("eq-a",), True),             # assignée à son équipe
    ("eq-a", ("eq-b", "eq-a"), True),
    ("eq-a", (), False),                   # équipe inconnue du profil (ou profil absent) : fail-closed
    ("eq-b", ("eq-a",), False),            # l'équipe d'un autre
    ("marc.fictif", ("eq-a",), False),     # un collègue de la même équipe, déjà parti : plus à l'équipe
    (None, ("eq-a",), False),              # assignée à personne : jamais à quelqu'un
    (None, (), False),
])
def test_controler_intervention_accepte_la_personne_ou_son_equipe_et_rien_d_autre(technicien, equipes, attendu_ok):
    verdict = acces.controler_intervention(_Registre(technicien), "I1", _employe(equipes))
    assert (verdict is None) is attendu_ok
    if not attendu_ok:
        assert verdict["code"] == "REJ-INTERVENTION-NON-ASSIGNEE"
        assert "eq-" not in verdict["detail"], "le refus ne révèle ni équipe ni assignation"


def test_l_intervention_inconnue_et_celle_d_une_equipe_etrangere_ont_le_meme_refus():
    inconnue = acces.controler_intervention(_Registre("eq-b"), "I-INCONNUE", _employe(("eq-a",)))
    etrangere = acces.controler_intervention(_Registre("eq-b"), "I1", _employe(("eq-a",)))
    assert inconnue == etrangere


def test_l_admin_et_l_agent_gardent_tout_les_equipes_n_y_changent_rien():
    admin, admin_en_equipe = acces.acteur_de("a", "admin", ())[0], acces.acteur_de("a", "admin", ("eq-a",))[0]
    for acteur in (None, admin, admin_en_equipe):
        assert acces.controler_intervention(_Registre("eq-b"), "I1", acteur) is None
    liste = [
        {"intervention_id": "I1", "technicien_assigne": "eq-b"},
        {"intervention_id": "I2", "technicien_assigne": None},
    ]
    assert acces.interventions_visibles(liste, None) == liste
    assert acces.interventions_visibles(liste, acces.acteur_de("a", "admin", ())[0]) == liste


def test_interventions_visibles_montre_les_siennes_et_celles_de_ses_equipes():
    liste = [
        {"intervention_id": "I1", "technicien_assigne": "luc.fictif"},
        {"intervention_id": "I2", "technicien_assigne": "eq-a"},
        {"intervention_id": "I3", "technicien_assigne": "eq-b"},
        {"intervention_id": "I4", "technicien_assigne": None},
        {"intervention_id": "I5", "technicien_assigne": "marc.fictif"},
    ]
    assert [i["intervention_id"] for i in acces.interventions_visibles(liste, _employe(("eq-a",)))] == ["I1", "I2"]
    assert [i["intervention_id"] for i in acces.interventions_visibles(liste, _employe(()))] == ["I1"]


def test_controler_technicien_reste_l_identite_de_la_personne_jamais_l_equipe():
    acteur = _employe(("eq-a",))
    assert acces.controler_technicien(acteur, "luc.fictif") is None
    assert acces.controler_technicien(acteur, "eq-a")["code"] == "REJ-IDENTITE-FOURNIE-DIFFERENTE"
    assert acces.controler_technicien(acteur, "marc.fictif")["code"] == "REJ-IDENTITE-FOURNIE-DIFFERENTE"


# =========================================================================================
# 2. Les vrais outils, le vrai profil
# =========================================================================================
@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    with stockage.transaction() as cnx:
        for identifiant, roles in (("admin.fictif", ["admin"]), ("luc.fictif", ["employee"]),
                                   ("marc.fictif", ["employee"]), ("nadia.fictif", ["employee"]),
                                   ("vendeur.fictif", ["seller"])):
            identite.creer_personne(cnx, identifiant, identifiant.title(), "mot-de-passe-fictif-1234", roles)
    equipes_entreprise.enregistrer_equipes(PROFIL)
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def par_nom(instance):
    return {o.nom: o for o in outils()}


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
            pile.enter_context(contexte.receptionne_de(contexte.HorodatageAppareil(
                appareil="tel-fictif-t4-12", horodatage_appareil=dt.datetime(2000, 1, 1, tzinfo=dt.UTC),
                recu_le=dt.datetime(2030, 1, 2, 9, 0, tzinfo=dt.UTC))))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _registre():
    return registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))


def _maillons():
    with stockage.transaction():
        return _registre().lire()


def _lead(lead_id):
    return {"schema_version": 2, "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
            "contact": {"nom": "Client Fictif"}, "service": "gouttieres", "ville": "Repentigny",
            "urgence_declaree": False, "canal": "texte"}


def _planifiees(chantiers_a_creer):
    """Interventions `planifiee` (porte « prêt » avec un verdict fabriqué, comme test_etats_a_planifier), assignées."""
    ids = {}
    with stockage.transaction():
        reg = _registre()
        for nom, technicien in chantiers_a_creer:
            accuse, verdict = etats.inscrire_depuis_devis(reg, f"DEVIS-{nom}", _lead(f"LEAD-{nom}"), "sel", HORO)
            assert verdict is None, verdict
            iid = accuse["intervention_id"]
            volets = {n: {"statut": "ok", "manque": None, "detail": None}
                      for n in ("soumission", "adresse", "equipe", "materiel", "meteo")}
            pret = {"intervention_id": iid, "statut_intervention": "a_planifier", "statut": "pret", "pret": True,
                    "volets": volets, "a_fournir": []}
            pret["empreinte"] = etats.empreinte_preparation(pret)
            assert etats.transitionner(iid, "planifiee", reg, HORO, preparation=pret)[1] is None
            assert etats.assigner_technicien(iid, technicien, reg, HORO)[1] is None
            ids[nom] = iid
    return ids


def _liste(par_nom, identite_appelante):
    reponse = _appeler(par_nom, "m4_lister_interventions", {}, identite_appelante)
    assert reponse["ok"] is True, reponse
    return {ligne["intervention_id"]: ligne for ligne in reponse["resultat"]}


def _statut(par_nom, iid, identite_appelante):
    reponse = _appeler(par_nom, "m4_statut_intervention", {"intervention_id": iid}, identite_appelante)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]["statut"]


def _partir(par_nom, iid, technicien_id, identite_appelante):
    return _appeler(par_nom, "m4_demarrer_route", {
        "intervention_id": iid, "technicien_id": technicien_id, "horodatage": HORO}, identite_appelante)


def test_un_membre_voit_les_interventions_de_son_equipe_et_les_siennes_pas_celles_d_une_autre(par_nom):
    ids = _planifiees((("a", "eq-a"), ("b", "eq-b"), ("luc", "luc.fictif")))
    assert set(_liste(par_nom, LUC)) == {ids["a"], ids["luc"]}
    assert set(_liste(par_nom, MARC)) == {ids["a"]}
    assert set(_liste(par_nom, NADIA)) == {ids["b"]}
    assert set(_liste(par_nom, ADMIN)) == set(ids.values()), "l'admin voit tout"
    assert set(_liste(par_nom, None)) == set(ids.values()), "l'agent voit tout, comme avant"
    assert _liste(par_nom, LUC)[ids["a"]]["technicien_assigne"] == "eq-a"
    assert _statut(par_nom, ids["a"], MARC) == "planifiee"
    assert _statut(par_nom, ids["b"], MARC) is None, "celle d'une autre équipe est indiscernable d'une inconnue"
    assert _statut(par_nom, ids["a"], NADIA) is None


def test_un_membre_part_sur_l_intervention_de_son_equipe_et_elle_devient_la_sienne_seule(par_nom):
    ids = _planifiees((("a", "eq-a"),))
    accuse = _appeler(par_nom, "m4_demarrer_route", {
        "intervention_id": ids["a"], "technicien_id": "marc.fictif", "horodatage": HORO}, MARC)
    assert accuse["resultat"]["accepte"] is True, accuse
    with stockage.transaction():
        assert etats.technicien_assigne(_registre(), ids["a"]) == "marc.fictif"
        assert etats.statut_courant(_registre(), ids["a"]) == "en_route"
    # Marc est maintenant le technicien : son coéquipier Luc n'agit plus sur cette intervention
    assert _statut(par_nom, ids["a"], MARC) == "en_route"
    assert _statut(par_nom, ids["a"], LUC) is None
    assert ids["a"] not in _liste(par_nom, LUC) and ids["a"] in _liste(par_nom, MARC)


def test_un_employe_d_une_autre_equipe_ne_part_pas_et_rien_n_est_ecrit(par_nom):
    ids = _planifiees((("a", "eq-a"),))
    avant = _maillons()
    reponse = _partir(par_nom, ids["a"], "nadia.fictif", NADIA)
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-INTERVENTION-NON-ASSIGNEE"
    assert _maillons() == avant


def test_l_identifiant_de_l_equipe_n_est_jamais_un_technicien_id_admis_pour_un_employe(par_nom):
    ids = _planifiees((("a", "eq-a"),))
    avant = _maillons()
    reponse = _partir(par_nom, ids["a"], "eq-a", LUC)
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-FOURNIE-DIFFERENTE"
    assert _maillons() == avant


def test_sans_profil_valide_l_equipe_ne_donne_aucun_acces_fail_closed(par_nom, instance):
    ids = _planifiees((("a", "eq-a"), ("luc", "luc.fictif")))
    fichier = taxonomie.fichier_profil()
    complet = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    for contenu in ({k: v for k, v in complet.items() if k != "equipes"}, {**complet, "equipes": {"salaire": 1}}):
        fichier.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
        assert set(_liste(par_nom, LUC)) == {ids["luc"]}, "seule l'assignation à sa personne reste"
        assert set(_liste(par_nom, MARC)) == set()
        avant = _maillons()
        assert _partir(par_nom, ids["a"], "marc.fictif", MARC)["resultat"]["verdict"]["code"] == \
            "REJ-INTERVENTION-NON-ASSIGNEE"
        assert _maillons() == avant


def test_un_retrait_du_profil_retire_l_acces_a_la_lecture_suivante(par_nom):
    ids = _planifiees((("a", "eq-a"),))
    assert set(_liste(par_nom, MARC)) == {ids["a"]}
    retire = copy.deepcopy(PROFIL)
    retire["liste"][0]["membres"] = ["luc.fictif"]
    equipes_entreprise.enregistrer_equipes(retire)
    assert set(_liste(par_nom, MARC)) == set() and set(_liste(par_nom, LUC)) == {ids["a"]}


def test_un_role_sans_portee_reste_refuse_meme_s_il_est_nomme_membre(par_nom, instance):
    """Un jeton `seller` n'a aucune portée sur M4 : le profil ne lui en donne pas, même s'il le nomme membre."""
    avec_vendeur = copy.deepcopy(PROFIL)
    avec_vendeur["liste"][1]["membres"].append("vendeur.fictif")
    equipes_entreprise.enregistrer_equipes(avec_vendeur)
    ids = _planifiees((("b", "eq-b"),))
    reponse = _appeler(par_nom, "m4_statut_intervention", {"intervention_id": ids["b"]},
                       contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller"))
    assert reponse["ok"] is False
