"""PLAN T4.10-b (M4.6) : `preparation.py`, pur, sur un registre EN MÉMOIRE et une lecture de position injectée.

Le verdict NOMME ce qui manque, volet par volet, et n'est « prêt » que si TOUS les volets sont vérifiés. Le volet
équipe est vérifié depuis le profil des équipes (PLAN T4.12) : une équipe admissible, calculée par le code. Les volets
matériel et météo n'ont pas encore de source dans M4 (PLAN T4.14, T4.13) : ils sont « non vérifiables », jamais
« prêts ». Données fictives.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
from m4_field_ops import etats, preparation, registre, verdicts

_SRC = Path(preparation.__file__).resolve()

HORO = "2026-09-29T10:00:00-04:00"
SEL = "sel-preparation-fictif"
POSITION = {"version": 3, "latitude_microdegres": 45_740_117, "longitude_microdegres": -73_454_833}


def _lead(lead_id="LEAD-PREP-1", **surcharges):
    lead = {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100"},
        "service": "gouttieres", "ville": "Repentigny", "urgence_declaree": False, "canal": "texte",
    }
    lead.update(surcharges)
    return lead


def _lire_position_ok(_registre, _chantier_id):
    return dict(POSITION), None


def _lire_position_absente(_registre, chantier_id):
    return None, verdicts.construire_verdict(
        "REJ-COORDONNEES-A-CONFIRMER", detail=f"coordonnées manquantes : à confirmer ({chantier_id})")


@pytest.fixture
def intervention(declarer_services):
    """Une intervention `a_planifier`, née d'un devis accepté."""
    declarer_services()
    reg = registre.Registre()
    accuse, verdict = etats.inscrire_depuis_devis(reg, "DEVIS-PREP-1", _lead(), SEL, HORO)
    assert verdict is None, verdict
    return reg, accuse["intervention_id"]


def _volets(verdict):
    return verdict["volets"]


class TestVerdictNommeCeQuiManque:
    def test_une_intervention_a_planifier_n_est_jamais_prete_avec_les_volets_actuels(self, intervention):
        reg, iid = intervention
        verdict, refus = preparation.evaluer(reg, iid, _lire_position_ok)
        assert refus is None
        assert verdict["statut_intervention"] == "a_planifier"
        assert verdict["statut"] == preparation.VERDICT_NON_VERIFIABLE
        assert verdict["pret"] is False

    def test_soumission_et_adresse_sont_lues_a_leur_source(self, intervention):
        reg, iid = intervention
        volets = _volets(preparation.evaluer(reg, iid, _lire_position_ok)[0])
        assert volets["soumission"]["statut"] == preparation.STATUT_OK
        assert "DEVIS-PREP-1" in volets["soumission"]["detail"]
        assert volets["adresse"]["statut"] == preparation.STATUT_OK
        assert volets["adresse"]["detail"] == "coordonnées confirmées (version 3)"

    @pytest.mark.parametrize("volet", ["equipe", "materiel", "meteo"])
    def test_equipe_materiel_et_meteo_sont_non_verifiables_et_disent_ce_qui_manque(self, intervention, volet):
        reg, iid = intervention
        v = _volets(preparation.evaluer(reg, iid, _lire_position_ok)[0])[volet]
        assert v["statut"] == preparation.STATUT_NON_VERIFIABLE
        assert isinstance(v["manque"], str) and len(v["manque"]) > 20

    def test_une_adresse_non_confirmee_bloque_et_dit_quoi_faire(self, intervention):
        reg, iid = intervention
        verdict, _ = preparation.evaluer(reg, iid, _lire_position_absente)
        assert verdict["statut"] == preparation.VERDICT_BLOQUE and verdict["pret"] is False
        adresse = _volets(verdict)["adresse"]
        assert adresse["statut"] == preparation.STATUT_MANQUE
        assert "à confirmer" in adresse["manque"] and adresse["detail"] == "REJ-COORDONNEES-A-CONFIRMER"
        assert "LEAD-PREP-1" in adresse["manque"], "le chantier d'une intervention est son lead_id, comme la cédule"

    def test_a_fournir_liste_tout_ce_qui_n_est_pas_ok_dans_l_ordre_des_volets(self, intervention):
        reg, iid = intervention
        verdict, _ = preparation.evaluer(reg, iid, _lire_position_absente)
        assert [(f["volet"], f["statut"]) for f in verdict["a_fournir"]] == [
            ("adresse", "manque"), ("equipe", "non_verifiable"),
            ("materiel", "non_verifiable"), ("meteo", "non_verifiable"),
        ]
        assert all(f["manque"] for f in verdict["a_fournir"])
        assert list(_volets(verdict)) == list(preparation.VOLETS)

    def test_une_intervention_sans_devis_est_bloquee_sur_la_soumission(self, declarer_services):
        declarer_services()
        reg = registre.Registre()
        contrat = {
            "lead_id": "L-LEGACY", "conversation_id": "C1", "type_travaux": "renovation_totale",
            "ville": "Montreal", "canal": "telephone", "contact": {"nom": "Dupont", "telephone": "0102030405"},
            "urgence_declaree": False,
        }
        marqueur = {"readiness_ok": True, "lead_id": "L-LEGACY", "hash_tete_registre": None,
                    "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32}
        accuse, verdict = etats.inscrire_intervention(contrat, marqueur, reg, "2025-06-02T08:00:00+00:00", SEL)
        assert verdict is None
        verdict_prep, refus = preparation.evaluer(reg, accuse["intervention_id"], _lire_position_ok)
        assert refus is None and verdict_prep["statut_intervention"] == "planifiee"
        assert verdict_prep["statut"] == preparation.VERDICT_BLOQUE
        assert _volets(verdict_prep)["soumission"]["statut"] == preparation.STATUT_MANQUE


def _profil(**surcharges):
    profil = {
        "liste": [{
            "id": "eq-nord", "membres": ["luc.fictif"], "competences": ["gouttieres"],
            "depot": {"id": "depot-fictif", "latitude_microdegres": 45735000, "longitude_microdegres": -73455000},
            "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}],
        }],
        "services": {"gouttieres": {"duree_min": 90, "competences": ["gouttieres"]}},
    }
    profil.update(surcharges)
    return profil


def _lecteur(profil=None, verdict=None):
    appels = []

    def lire():
        appels.append(1)
        return profil, verdict

    lire.appels = appels
    return lire


def _volets_futurs_ok(monkeypatch):
    """Simule ce que T4.14 (matériel) et T4.13 (météo) livreront : deux volets vérifiés. Ne sert qu'à prouver la
    plomberie ; aucun verdict réel n'est « prêt » tant que ces tâches n'existent pas."""
    def ok(_registre, _inscription, _lire_position, _lire_equipes):
        return {"statut": "ok", "manque": None, "detail": "simulé par le test"}

    monkeypatch.setattr(preparation, "_VOLETS", tuple(
        (nom, ok if nom in ("materiel", "meteo") else fonction) for nom, fonction in preparation._VOLETS))


class TestVoletEquipe:
    """PLAN T4.12 : le volet équipe se vérifie depuis le profil des équipes ; il ne « manque » que faute de profil."""

    def test_une_equipe_admissible_rend_le_volet_ok_et_le_nomme(self, intervention):
        reg, iid = intervention
        lecteur = _lecteur(_profil())
        verdict, refus = preparation.evaluer(reg, iid, _lire_position_ok, lecteur)
        assert refus is None and lecteur.appels, "le volet lit le profil, il ne suppose rien"
        equipe = _volets(verdict)["equipe"]
        assert equipe["statut"] == preparation.STATUT_OK and equipe["manque"] is None
        assert equipe["detail"] == "équipes admissibles pour gouttieres : eq-nord"
        # matériel et météo restent non vérifiables : aucun verdict réel n'est prêt
        assert verdict["statut"] == preparation.VERDICT_NON_VERIFIABLE and verdict["pret"] is False
        assert [f["volet"] for f in verdict["a_fournir"]] == ["materiel", "meteo"]

    def test_sans_lecture_du_profil_le_volet_reste_non_verifiable_jamais_ok(self, intervention):
        reg, iid = intervention
        equipe = _volets(preparation.evaluer(reg, iid, _lire_position_ok)[0])["equipe"]
        assert equipe["statut"] == preparation.STATUT_NON_VERIFIABLE and "aucune n'a été fournie" in equipe["manque"]

    def test_sans_profil_le_volet_manque_et_dit_quoi_declarer(self, intervention):
        reg, iid = intervention
        verdict_profil = {"code": "REJ-EQUIPES-NON-CONFIGUREES",
                          "detail": "aucun profil des équipes déclaré : `opsys equipes declarer --depuis <fichier>`"}
        verdict, _ = preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(None, verdict_profil))
        equipe = _volets(verdict)["equipe"]
        assert equipe["statut"] == preparation.STATUT_MANQUE and "opsys equipes declarer" in equipe["manque"]
        assert equipe["detail"] == "REJ-EQUIPES-NON-CONFIGUREES"
        assert verdict["statut"] == preparation.VERDICT_BLOQUE

    def test_un_profil_invalide_manque_avec_son_code_jamais_lu_comme_ok(self, intervention):
        reg, iid = intervention
        verdict_profil = {"code": "REJ-PROFIL-INVALIDE", "detail": "profil d'entreprise invalide : quart mal formé"}
        equipe = _volets(preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(None, verdict_profil))[0])["equipe"]
        assert equipe["statut"] == preparation.STATUT_MANQUE and equipe["detail"] == "REJ-PROFIL-INVALIDE"
        assert "quart mal formé" in equipe["manque"]

    def test_un_service_sans_duree_au_profil_manque_et_est_nomme(self, intervention):
        reg, iid = intervention
        profil = _profil(services={"reparation": {"duree_min": 60, "competences": []}})
        equipe = _volets(preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(profil))[0])["equipe"]
        assert equipe["statut"] == preparation.STATUT_MANQUE and "'gouttieres'" in equipe["manque"]
        assert equipe["detail"] == "REJ-CHAMP-MANQUANT"

    def test_un_profil_sans_equipe_manque(self, intervention):
        reg, iid = intervention
        profil = _profil()
        del profil["liste"]
        equipe = _volets(preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(profil))[0])["equipe"]
        assert equipe["statut"] == preparation.STATUT_MANQUE and "aucune équipe déclarée" in equipe["manque"]

    def test_aucune_equipe_admissible_manque_et_dit_pourquoi_chacune(self, intervention):
        reg, iid = intervention
        profil = _profil()
        profil["liste"][0]["competences"] = ["revetement"]
        profil["liste"].append({**profil["liste"][0], "id": "eq-courte", "competences": ["gouttieres"],
                                "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 500}]})
        verdict, _ = preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(profil))
        equipe = _volets(verdict)["equipe"]
        assert equipe["statut"] == preparation.STATUT_MANQUE
        assert "aucune équipe admissible pour le service 'gouttieres'" in equipe["manque"]
        assert "eq-courte : aucun quart d'au moins 90 minutes (le plus long : 20 minutes)" in equipe["manque"]
        assert "eq-nord : compétence manquante : gouttieres" in equipe["manque"]
        assert verdict["statut"] == preparation.VERDICT_BLOQUE

    def test_une_intervention_v1_n_a_pas_de_service_donc_le_volet_est_non_verifiable(self, declarer_services):
        declarer_services()
        reg = registre.Registre()
        contrat = {
            "lead_id": "L-V1", "conversation_id": "C1", "type_travaux": "renovation_totale", "ville": "Montreal",
            "canal": "telephone", "contact": {"nom": "Dupont", "telephone": "0102030405"}, "urgence_declaree": False,
        }
        marqueur = {"readiness_ok": True, "lead_id": "L-V1", "hash_tete_registre": None,
                    "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32}
        accuse, _ = etats.inscrire_intervention(contrat, marqueur, reg, "2025-06-02T08:00:00+00:00", SEL)
        verdict, _ = preparation.evaluer(reg, accuse["intervention_id"], _lire_position_ok, _lecteur(_profil()))
        equipe = _volets(verdict)["equipe"]
        assert equipe["statut"] == preparation.STATUT_NON_VERIFIABLE and "lead v1" in equipe["manque"]
        assert "renovation_totale" in equipe["manque"]

    def test_l_empreinte_du_verdict_suit_le_profil(self, intervention):
        reg, iid = intervention
        un, _ = preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(_profil()))
        meme, _ = preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(_profil()))
        autre_profil = _profil()
        autre_profil["liste"].append({**autre_profil["liste"][0], "id": "eq-sud"})
        deux, _ = preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(autre_profil))
        assert un["empreinte"] == meme["empreinte"] != deux["empreinte"]
        assert _volets(deux)["equipe"]["detail"] == "équipes admissibles pour gouttieres : eq-nord, eq-sud"

    def test_le_verdict_ne_nomme_aucun_membre_ni_ne_classe_les_equipes(self, intervention):
        reg, iid = intervention
        texte = json.dumps(preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(_profil()))[0], ensure_ascii=False)
        for interdit in ("luc.fictif", "membres", "score", "note", "classement", "performance"):
            assert interdit not in texte, interdit

    def test_pret_seulement_quand_l_equipe_ET_le_materiel_ET_la_meteo_sont_verifies(self, intervention, monkeypatch):
        reg, iid = intervention
        # aujourd'hui : le profil ne suffit pas
        assert preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(_profil()))[0]["pret"] is False
        _volets_futurs_ok(monkeypatch)  # T4.14 et T4.13 simulés : la plomberie prouvée, pas le produit
        pret, _ = preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(_profil()))
        assert pret["pret"] is True and pret["statut"] == preparation.VERDICT_PRET and pret["a_fournir"] == []
        # sans profil, ou avec une adresse non confirmée, ou sans équipe admissible : jamais prêt, même ainsi
        sans_profil = preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(None, {"code": "X", "detail": "d"}))[0]
        assert sans_profil["pret"] is False and sans_profil["statut"] == preparation.VERDICT_BLOQUE
        assert preparation.evaluer(reg, iid, _lire_position_absente, _lecteur(_profil()))[0]["pret"] is False
        inadmissible = _profil()
        inadmissible["liste"][0]["competences"] = []
        assert preparation.evaluer(reg, iid, _lire_position_ok, _lecteur(inadmissible))[0]["pret"] is False
        # le verdict prêt ouvre la porte de la machine à états (l'empreinte est celle de son contenu)
        accuse, verdict = etats.transitionner(iid, "planifiee", reg, "2026-09-29T12:00:00-04:00", preparation=pret)
        assert verdict is None and accuse["statut"] == "planifiee"


class TestAgregation:
    """`verdict_des_volets` est une fonction pure : le seul endroit où « prêt » peut naître."""

    @staticmethod
    def _v(*statuts):
        return {f"v{i}": {"statut": s, "manque": None, "detail": None} for i, s in enumerate(statuts)}

    def test_pret_seulement_si_tous_les_volets_sont_ok(self):
        assert preparation.verdict_des_volets(self._v("ok", "ok", "ok")) == preparation.VERDICT_PRET

    def test_un_volet_qui_manque_bloque_meme_si_un_autre_est_non_verifiable(self):
        assert preparation.verdict_des_volets(self._v("ok", "manque", "non_verifiable")) == preparation.VERDICT_BLOQUE

    def test_un_volet_non_verifiable_n_est_jamais_ok(self):
        assert preparation.verdict_des_volets(self._v("ok", "non_verifiable")) == preparation.VERDICT_NON_VERIFIABLE

    def test_aucun_volet_n_est_pas_pret(self):
        assert preparation.verdict_des_volets({}) == preparation.VERDICT_NON_VERIFIABLE


class TestRefus:
    def test_intervention_inconnue(self):
        verdict, refus = preparation.evaluer(registre.Registre(), "inconnue", _lire_position_ok)
        assert verdict is None and refus["code"] == "REJ-TRANSITION-ILLEGALE"
        assert "inexistante" in refus["detail"]

    @pytest.mark.parametrize("cible", ["annulee"])
    def test_intervention_terminale(self, intervention, cible):
        reg, iid = intervention
        accuse, verdict = etats.transitionner(iid, cible, reg, "2026-09-29T11:00:00-04:00")
        assert verdict is None and accuse["statut"] == cible
        verdict, refus = preparation.evaluer(reg, iid, _lire_position_ok)
        assert verdict is None and refus["code"] == "REJ-TRANSITION-ILLEGALE"
        assert "sans objet" in refus["detail"] and cible in refus["detail"]

    def test_intervention_deja_partie(self, declarer_services):
        declarer_services()
        reg = registre.Registre()
        contrat = {
            "lead_id": "L-PARTIE", "conversation_id": "C1", "type_travaux": "renovation_totale",
            "ville": "Montreal", "canal": "telephone", "contact": {"nom": "Dupont", "telephone": "0102030405"},
            "urgence_declaree": False,
        }
        marqueur = {"readiness_ok": True, "lead_id": "L-PARTIE", "hash_tete_registre": None,
                    "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32}
        accuse, _ = etats.inscrire_intervention(contrat, marqueur, reg, "2025-06-02T08:00:00+00:00", SEL)
        iid = accuse["intervention_id"]
        etats.transitionner(iid, "en_route", reg, "2025-06-02T08:30:00+00:00",
                            assignation={"intervention_id": iid, "technicien_id": "T1"})
        verdict, refus = preparation.evaluer(reg, iid, _lire_position_ok)
        assert verdict is None and refus["code"] == "REJ-TRANSITION-ILLEGALE" and "en_route" in refus["detail"]


class TestLectureSeule:
    def test_evaluer_n_ecrit_rien(self, intervention):
        reg, iid = intervention
        avant = copy.deepcopy(reg.lire())
        preparation.evaluer(reg, iid, _lire_position_ok)
        preparation.evaluer(reg, iid, _lire_position_absente)
        assert reg.lire() == avant

    def test_meme_registre_meme_verdict_octet_pour_octet(self, intervention):
        reg, iid = intervention
        premier, _ = preparation.evaluer(reg, iid, _lire_position_ok)
        second, _ = preparation.evaluer(reg, iid, _lire_position_ok)
        assert json.dumps(premier, sort_keys=True) == json.dumps(second, sort_keys=True)
        assert len(premier["empreinte"]) == 64

    def test_l_empreinte_change_quand_un_volet_change(self, intervention):
        reg, iid = intervention
        ok, _ = preparation.evaluer(reg, iid, _lire_position_ok)
        absente, _ = preparation.evaluer(reg, iid, _lire_position_absente)
        assert ok["empreinte"] != absente["empreinte"]

    def test_le_verdict_ne_porte_ni_coordonnee_ni_contact_ni_prix(self, intervention):
        reg, iid = intervention
        texte = json.dumps(preparation.evaluer(reg, iid, _lire_position_ok)[0], ensure_ascii=False)
        for interdit in ("45740117", "73454833", "latitude", "longitude", "418-555-0100", "Client Fictif",
                         "Repentigny", "prix", "montant"):
            assert interdit not in texte, interdit


# ---------------------------------------------------------------------------------------------
# Garde par analyse du code : pur (aucun opsys, aucune horloge, aucun aléa, aucun réseau)
# ---------------------------------------------------------------------------------------------
def _arbre():
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def test_le_module_est_pur_sans_opsys_ni_horloge_ni_alea():
    autorises = {"__future__"}
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                assert alias.name in autorises, alias.name
        if isinstance(noeud, ast.ImportFrom):
            assert noeud.module in autorises or noeud.level == 1, (noeud.module, noeud.level)
            if noeud.level == 1:
                assert {a.name for a in noeud.names} <= {"admissibilite", "etats", "verdicts"}
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {"now", "utcnow", "today", "time", "random", "urandom", "monotonic"}
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"random", "time", "datetime", "socket", "float"}


def test_aucun_stub_ni_todo_dans_le_module():
    texte = _SRC.read_text(encoding="utf-8")
    assert "TODO" not in texte and "FIXME" not in texte and "NotImplementedError" not in texte
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.FunctionDef):
            corps = [n for n in noeud.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            assert corps and not all(isinstance(n, ast.Pass) for n in corps), noeud.name


def test_les_verdicts_du_module_sont_tous_au_catalogue():
    codes = {
        n.value for n in ast.walk(_arbre())
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("REJ-")
    }
    assert codes and codes <= verdicts.CODES_M4, codes - verdicts.CODES_M4
