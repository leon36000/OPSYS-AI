"""PLAN T4.14-b (M4.6) : `materiel.py`, pur, sur un registre EN MÉMOIRE et des charges `m6.materiel_pret` fictives.

M4 retient, par devis, la charge de plus grande révision (quel que soit l'ordre d'arrivée) et ne dit « prêt » que si
M6 le dit ET que la réservation est active ET qu'aucune ligne ne manque. Aucune charge : rien n'est affirmé. Données
fictives (`fictif: true` au sens d'AGENTS.md : identifiants, quantités et matériaux de test).
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
from m4_field_ops import materiel, registre

_SRC = Path(materiel.__file__).resolve()
FICTIF = True
DEVIS = "DEVIS-MAT-1"


def _ligne(materiau="gouttiere-5po-fictif", besoin="100", reservee="0", manquante=None, unite="pi"):
    manquante = str(int(besoin) - int(reservee)) if manquante is None else manquante
    return {"materiau_id": materiau, "unite": unite, "quantite_besoin": besoin, "quantite_reservee": reservee,
            "quantite_manquante": manquante}


def _charge(revision=1, statut="a_commander", active=True, devis=DEVIS, lignes=None, manquantes=None,
            chantier="CHANTIER-FICTIF", declencheur="devis_accepte"):
    lignes = [_ligne()] if lignes is None else lignes
    if manquantes is None:
        manquantes = [ligne for ligne in lignes if ligne["quantite_manquante"] != "0"]
    return {
        "evenement_id": f"m6-materiel-pret-{devis}-{revision}", "devis_id": devis, "chantier_id": chantier,
        "revision": revision, "statut": statut, "reservation_active": active, "declencheur": declencheur,
        "horodatage": f"2026-09-30T10:{revision:02d}:00-04:00", "lignes": lignes, "lignes_manquantes": manquantes,
    }


def _pret(revision=3):
    return _charge(revision, "pret", True, lignes=[_ligne(reservee="100")], manquantes=[])


def _registre_de(*charges):
    reg = registre.Registre()
    for charge in charges:
        reg.ajouter(materiel.maillon_de_la_charge(charge))
    return reg


class TestMaillon:
    def test_le_maillon_garde_ce_que_la_lecture_utilise_et_l_horodatage_du_fait(self):
        charge = _charge(2, "partiel", True, lignes=[_ligne(reservee="60"), _ligne("vis", "20", "20", "0", "boite")])
        maillon = materiel.maillon_de_la_charge(charge)
        assert maillon["type_entree"] == materiel.TYPE_MATERIEL_PRET_RECU == "materiel_pret_recu"
        assert maillon["horodatage"] == charge["horodatage"], "l'heure du fait de M6, jamais celle de la réception"
        assert set(maillon) == {"type_entree", "horodatage", *materiel.CLES_RETENUES}
        assert maillon["lignes_manquantes"] == [_ligne(reservee="60")]

    def test_chantier_id_et_le_detail_des_lignes_ne_sont_pas_gardes(self):
        maillon = materiel.maillon_de_la_charge(_charge(chantier="CHANTIER-SECRET"))
        texte = json.dumps(maillon)
        assert "chantier" not in texte and "CHANTIER-SECRET" not in texte and "lignes\"" not in texte
        assert "lignes" not in maillon and "chantier_id" not in maillon

    @pytest.mark.parametrize("revision", [0, -1, True, False, "3", 2.0, None])
    def test_une_revision_qui_n_est_pas_un_entier_d_au_moins_1_est_refusee(self, revision):
        charge = _charge()
        charge["revision"] = revision
        with pytest.raises(ValueError, match="revision"):
            materiel.maillon_de_la_charge(charge)

    def test_la_charge_n_est_pas_modifiee(self):
        charge = _charge(2, "partiel", True, lignes=[_ligne(reservee="60")])
        avant = copy.deepcopy(charge)
        materiel.maillon_de_la_charge(charge)
        assert charge == avant


class TestRetenue:
    def test_aucune_charge_rien_n_est_retenu(self):
        assert materiel.charge_retenue(registre.Registre(), DEVIS) is None

    def test_la_plus_grande_revision_gagne_dans_l_ordre_normal(self):
        reg = _registre_de(_charge(1), _charge(2, "partiel"), _pret(3))
        assert materiel.charge_retenue(reg, DEVIS)["revision"] == 3

    @pytest.mark.parametrize("ordre", [(3, 2, 1), (2, 3, 1), (1, 3, 2), (3, 1, 2), (2, 1, 3)])
    def test_la_plus_grande_revision_gagne_dans_tous_les_ordres_d_arrivee(self, ordre):
        par_revision = {1: _charge(1), 2: _charge(2, "partiel"), 3: _pret(3)}
        reg = _registre_de(*(par_revision[r] for r in ordre))
        retenue = materiel.charge_retenue(reg, DEVIS)
        assert retenue["revision"] == 3 and retenue["statut"] == "pret"

    def test_chaque_devis_a_sa_propre_charge(self):
        reg = _registre_de(_charge(1, devis="D-A"), _pret(4), _charge(2, "partiel", devis="D-A"))
        assert materiel.charge_retenue(reg, "D-A")["revision"] == 2
        assert materiel.charge_retenue(reg, DEVIS)["revision"] == 4
        assert materiel.charge_retenue(reg, "D-INCONNU") is None

    @pytest.mark.parametrize("devis_id", [None, "", 0, ["D"], {"devis": DEVIS}])
    def test_un_devis_absent_ou_mal_forme_ne_retient_rien(self, devis_id):
        assert materiel.charge_retenue(_registre_de(_charge(1)), devis_id) is None

    def test_les_maillons_d_un_autre_type_ne_comptent_pas(self):
        reg = registre.Registre()
        reg.ajouter({"type_entree": "pointage", "horodatage": "2026-09-30T10:00:00-04:00", "devis_id": DEVIS,
                     "revision": 99})
        assert materiel.charge_retenue(reg, DEVIS) is None

    def test_la_lecture_n_ecrit_rien(self):
        reg = _registre_de(_charge(1), _charge(2, "partiel"))
        avant = copy.deepcopy(reg.lire())
        materiel.charge_retenue(reg, DEVIS)
        assert reg.lire() == avant


class TestEtat:
    def test_pret_seulement_si_statut_pret_reservation_active_et_aucune_ligne_manquante(self):
        assert materiel.etat_du_materiel(_pret()) == materiel.ETAT_PRET

    def test_partiel_et_a_commander_sont_repris_tels_quels(self):
        assert materiel.etat_du_materiel(_charge(2, "partiel", True)) == materiel.ETAT_PARTIEL
        assert materiel.etat_du_materiel(_charge(1, "a_commander", True)) == materiel.ETAT_A_COMMANDER

    def test_partiel_et_a_commander_sont_repris_meme_quand_la_reservation_n_est_pas_active(self):
        assert materiel.etat_du_materiel(_charge(2, "partiel", False)) == materiel.ETAT_PARTIEL
        assert materiel.etat_du_materiel(_charge(1, "a_commander", False)) == materiel.ETAT_A_COMMANDER

    def test_un_pret_dont_la_reservation_est_liberee_n_est_jamais_pret(self):
        charge = _pret()
        charge["reservation_active"] = False
        assert materiel.etat_du_materiel(charge) == materiel.ETAT_A_COMMANDER

    def test_un_pret_qui_a_encore_des_lignes_manquantes_n_est_jamais_pret(self):
        charge = _pret()
        charge["lignes_manquantes"] = [_ligne(reservee="90")]
        assert materiel.etat_du_materiel(charge) == materiel.ETAT_PARTIEL

    @pytest.mark.parametrize("active", [None, "true", 1, "oui"])
    def test_une_reservation_active_qui_n_est_pas_le_booleen_vrai_n_est_pas_active(self, active):
        charge = _pret()
        charge["reservation_active"] = active
        assert materiel.etat_du_materiel(charge) == materiel.ETAT_A_COMMANDER

    def test_un_statut_hors_enumere_n_est_jamais_pret(self):
        charge = _pret()
        charge["statut"] = "ok"
        assert materiel.etat_du_materiel(charge) == materiel.ETAT_PARTIEL
        charge["reservation_active"] = False
        assert materiel.etat_du_materiel(charge) == materiel.ETAT_A_COMMANDER


class TestTexte:
    def test_une_phrase_par_ligne_manquante_avec_l_unite(self):
        texte = materiel.lignes_manquantes_en_texte([
            _ligne(reservee="60"), _ligne("vis-inox-fictif", "20", "0", "20", "boite"),
        ])
        assert texte == (
            "gouttiere-5po-fictif : 40 pi manquantes sur 100 ; vis-inox-fictif : 20 boite manquantes sur 20"
        )

    def test_une_unite_absente_ne_laisse_pas_d_espace_double(self):
        assert materiel.lignes_manquantes_en_texte([_ligne(unite=None)]) == (
            "gouttiere-5po-fictif : 100 manquantes sur 100")

    def test_aucune_ligne_aucun_texte(self):
        assert materiel.lignes_manquantes_en_texte([]) == ""


# ---------------------------------------------------------------------------------------------
# Garde par analyse du code : pur (aucun opsys, aucune horloge, aucun aléa, aucun réseau)
# ---------------------------------------------------------------------------------------------
def _arbre():
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def test_le_module_est_pur_sans_opsys_ni_m6_ni_horloge_ni_alea():
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.Import):
            assert not noeud.names, "aucun import direct : stdlib seulement par __future__"
        if isinstance(noeud, ast.ImportFrom):
            assert noeud.module == "__future__", (noeud.module, noeud.level)
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {"now", "utcnow", "today", "time", "random", "urandom", "monotonic"}
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"random", "time", "datetime", "socket", "float", "opsys", "m6_material_control"}


def test_aucun_stub_ni_todo_dans_le_module():
    texte = _SRC.read_text(encoding="utf-8")
    assert "TODO" not in texte and "FIXME" not in texte and "NotImplementedError" not in texte
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.FunctionDef):
            corps = [n for n in noeud.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            assert corps and not all(isinstance(n, ast.Pass) for n in corps), noeud.name


def test_le_module_ne_lit_pas_chantier_id():
    """`chantier_id` est nullable et M4 ne le devine pas : aucun accès au champ dans le module."""
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
            assert noeud.value != "chantier_id"
