"""Critère FACULTATIF « rapidité » de l'indice d'adéquation (M4.11), appris par M3 par couple (équipe, type de travaux).
Module pur, données fictives, chiffres calculés à la main en fractions exactes."""

from __future__ import annotations

import contextlib
import copy
import sys
from fractions import Fraction
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m4_field_ops import adequation_equipe as ae  # noqa: E402
from m4_field_ops import calibration_projection as cp  # noqa: E402
from m4_field_ops.outils import outils  # noqa: E402

from opsys import contexte  # noqa: E402

FICTIF = True
BRUT = {"poids": {"capacite": "1", "charge": "0", "distance": "0", "qualite": "0", "rapidite": "3"},
        "distance_reference_km": 50, "historique_minimum": 5}


def parametres(**poids):
    brut = copy.deepcopy(BRUT)
    brut["poids"].update(poids)
    p, verdict = ae.lire_parametres(brut)
    assert verdict is None, verdict
    return p


def rapidite(indice, bas, haut, chantiers=9):
    return {"chantiers": chantiers, "indice_median": indice, "borne_basse": bas, "borne_haute": haut}


def equipe(identifiant, rap=None, membres=2):
    e = {"equipe_id": identifiant, "competences": ["c1"], "membres_declares": membres,
         "capacite": {"minutes_disponibles": 2400, "minutes_planifiees": 600}}
    if rap is not None:
        e["rapidite"] = rap
    return e


def entrees(*equipes):
    return {"intervention": {"intervention_id": "int-1", "service": "service_a", "date": "2030-06-04", "duree_min": 120,
                             "competences_requises": ["c1"]}, "equipes": list(equipes)}


def ordre(*equipes, **poids):
    r, verdict = ae.ordonner(entrees(*equipes), parametres(**poids))
    assert verdict is None, verdict
    return r


def test_l_equipe_plus_rapide_passe_devant_a_capacite_egale_avec_un_sous_indice_exact():
    r = ordre(equipe("eq-lente", rapidite("1.1", "1.05", "1.15")), equipe("eq-vite", rapidite("0.9", "0.85", "0.95")))
    assert [x["equipe_id"] for x in r["ordre"]] == ["eq-vite", "eq-lente"]
    detail = {c["critere"]: c for c in r["ordre"][0]["criteres"]}
    # capacité identique : (1800-120)/1800 = 14/15 ; rapidité 1/(1 + 0,9) = 10/19. Poids 1 et 3 : (14/15 + 30/19)/4.
    attendu = (Fraction(14, 15) + 3 * Fraction(10, 19)) / 4
    assert detail["rapidite"]["sous_indice"] == "0.5263" and detail["rapidite"]["poids_effectif"] == "0.7500"
    assert abs(float(r["ordre"][0]["adequation"]) - float(attendu)) < 0.0001
    valeur = detail["rapidite"]["valeur"]
    assert "0.9 de la durée habituelle" in valeur and "0.85 à 0.95" in valeur
    assert r["rapidite_concluante"] is True and r["poids_declares"]["rapidite"] == "3.0000"


def test_intervalles_qui_se_chevauchent_ne_sont_pas_concluants_et_le_disent():
    r = ordre(equipe("eq-a", rapidite("0.97", "0.90", "1.04")), equipe("eq-b", rapidite("1.01", "0.95", "1.08")))
    assert r["rapidite_concluante"] is False


def test_equipe_neuve_ou_trop_petite_est_non_evaluable_nommee_a_part_jamais_zero():
    r = ordre(equipe("eq-a", rapidite("0.9", "0.85", "0.95")), equipe("eq-b", rapidite("1.1", "1.05", "1.15")),
              equipe("eq-neuve"), equipe("eq-seule", rapidite("0.5", "0.4", "0.6"), membres=1))
    assert [x["equipe_id"] for x in r["ordre"]] == ["eq-a", "eq-b"]
    sorties = {n["equipe_id"]: n for n in r["non_evaluables"]}
    assert set(sorties) == {"eq-neuve", "eq-seule"}
    assert all(n["motifs"] == ["rapidite_non_evaluable"] and "jamais notée zéro" in n["detail"]
               for n in sorties.values())
    assert "rapidite" in r["criteres_actifs"]


def test_une_seule_equipe_evaluable_le_critere_est_ecarte_pour_toutes_sans_en_exclure_aucune():
    r = ordre(equipe("eq-a", rapidite("0.9", "0.85", "0.95")), equipe("eq-neuve"))
    assert {x["equipe_id"] for x in r["ordre"]} == {"eq-a", "eq-neuve"} and r["non_evaluables"] == []
    assert "rapidite" not in r["criteres_actifs"]
    assert any(e["critere"] == "rapidite" and "eq-neuve" in e["raison"] for e in r["criteres_ecartes"])


def test_sans_poids_de_rapidite_le_critere_n_existe_pas_et_rien_ne_change():
    sans, _ = ae.ordonner(entrees(equipe("eq-a"), equipe("eq-b")),
                          ae.lire_parametres({**BRUT, "poids": {k: v for k, v in BRUT["poids"].items()
                                                                if k != "rapidite"}})[0])
    avec_donnee, _ = ae.ordonner(entrees(equipe("eq-a", rapidite("0.5", "0.4", "0.6")), equipe("eq-b")),
                                 ae.lire_parametres({**BRUT, "poids": {**BRUT["poids"], "rapidite": None}})[0])
    assert sans["criteres_actifs"] == avec_donnee["criteres_actifs"] == ["capacite"]
    assert [x["adequation"] for x in sans["ordre"]] == [x["adequation"] for x in avec_donnee["ordre"]]
    assert "rapidite" not in sans["poids_declares"] and "rapidite_concluante" not in sans
    assert ae.lire_parametres({**BRUT, "poids": {**BRUT["poids"], "rapidite": "0"}})[0]["poids"][ae.RAPIDITE] == 0


@pytest.mark.parametrize("mauvaise", [
    {"chantiers": 0, "indice_median": "1", "borne_basse": "0.9", "borne_haute": "1.1"},
    {"chantiers": 5, "indice_median": "0", "borne_basse": "0", "borne_haute": "1"},
    {"chantiers": 5, "indice_median": "1.5", "borne_basse": "1.0", "borne_haute": "1.2"},   # médiane hors intervalle
    {"chantiers": 5, "indice_median": 1, "borne_basse": "0.9", "borne_haute": "1.1"},
    {"chantiers": 5, "indice_median": "1", "borne_basse": "0.9"},
    {"chantiers": 5, "indice_median": "1", "borne_basse": "0.9", "borne_haute": "1.1", "technicien": "x"},
    "rapide",
])
def test_donnee_de_rapidite_mal_formee_refusee(mauvaise):
    r, verdict = ae.ordonner(entrees(equipe("eq-a", mauvaise), equipe("eq-b")), parametres())
    assert r is None and verdict["code"] in ("REJ-ADEQUATION-ENTREE-INVALIDE", "REJ-ADEQUATION-ATTRIBUT-INTERDIT")


def test_la_calibration_des_poids_sur_cas_fictifs_reste_celle_des_quatre_criteres():
    assert ae.CRITERES == ("capacite", "charge", "distance", "qualite") and ae.RAPIDITE == "rapidite"


# ------------------------------------------------------------------------------- équipe pseudonymisée de M4
class RegistreDouble:
    def __init__(self, maillons):
        self.maillons = maillons

    def taille(self):
        return len(self.maillons)

    def valider_chaine(self):
        return True

    def lire(self):
        return list(self.maillons)


def maillons_wct(*couples):
    """(wct_id, intervention_id, technicien) -> maillons d'assignation et de fin de travaux fictifs."""
    sortie = []
    for wct_id, intervention, technicien in couples:
        sortie.append({"type_entree": cp.etats.TYPE_ASSIGNATION, "intervention_id": intervention,
                       "technicien_id": technicien})
        sortie.append({cp.outbox.CLE_WCT: {"wct_id": wct_id, "intervention_id": intervention},
                       "intervention_id": intervention})
    return sortie


@pytest.fixture
def cle_wct():
    return cp.outbox.CLE_WCT


def test_lire_equipes_rend_un_pseudonyme_stable_seulement_pour_une_equipe_declaree_d_au_moins_deux_membres(cle_wct):
    registre = RegistreDouble(maillons_wct(("w1", "i1", "eq-nord"), ("w2", "i2", "eq-solo"),
                                           ("w3", "i3", "marc.fictif"),
                                           ("w4", "i4", None)))
    r = cp.lire_equipes(["w1", "w2", "w3", "w4", "w-inconnu"], registre, {"eq-nord": 2, "eq-solo": 1})
    par = {x["wct_id"]: x for x in r["equipes"]}
    assert par["w1"] == {"wct_id": "w1", "equipe_ref": cp.equipe_ref("eq-nord"), "motif": None}
    assert par["w2"]["equipe_ref"] is None and par["w2"]["motif"] == "equipe_de_moins_de_deux_membres"
    assert par["w3"]["equipe_ref"] is None and par["w3"]["motif"] == "assignation_non_equipe_declaree"
    assert par["w4"]["equipe_ref"] is None and par["w-inconnu"]["motif"] == "wct_absent"
    assert cp.equipe_ref("eq-nord") == cp.equipe_ref("eq-nord") != cp.equipe_ref("eq-sud")
    texte = repr(r)
    assert "eq-nord" not in texte and "marc.fictif" not in texte and cp.equipe_ref("eq-nord").startswith("eq-")


@pytest.mark.parametrize("mauvais", [None, [], ["a", "a"], [""], [1], ["x"] * 201, "w1"])
def test_lire_equipes_refuse_les_identifiants_hostiles(mauvais, cle_wct):
    assert cp.lire_equipes(mauvais, RegistreDouble([]), {})["equipes"] == []


def test_lecture_des_equipes_par_wct_refusee_hors_de_m3():
    outil = next(o for o in outils() if o.nom == "m4_lire_equipes_faits_m3")
    for origine in (None, "m05-financecore", "m04-field-ops"):
        with contexte.appeler_en_tant_que(origine) if origine else contextlib.nullcontext():
            r = outil.fonction(["w1"])
        assert r == {"equipes": [], "refus": [{"motif": "departement_appelant_non_autorise"}]}, origine
