"""Fraîcheur attendue d'une lecture de M8 (`fraicheur_attendue_s`, docs/FRAICHEUR-ATTENDUE-LECTURES.md).

Ce que ce fichier prouve :
- non déclarée (livraison : `configuration.fraicheur_lectures_s` vide) : la réponse de la lecture est EXACTEMENT celle
  d'avant, aucune clé de plus, aucune fenêtre inventée ni dérivée (rétrocompatibilité des consommateurs) ;
- déclarée et valide : la fenêtre et sa `version_definition_fraicheur` sont exposées, le reste de la réponse ne change
  pas ;
- invalide (booléen, décimal, texte, zéro, négatif, trop grand) : refusée et dite, jamais exposée ni corrigée ;
- la version de définition est déterministe (recalculée à la main avec hashlib), change avec la fenêtre et l'outil, et
  ne touche aucune `version_definition` de métrique ;
- aucun nouveau grant : mêmes outils, mêmes paramètres, mêmes rôles et paliers.
Faits et fenêtres fictifs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from m8_analytics import encodage, entonnoir, fraicheur_lectures, mesures_chantier
from m8_analytics import outils as m8_outils
from m8_analytics.outils import outils
from m8_analytics.registre import RegistreSnapshots

from opsys.outils import Autonomie, executer

FICTIF = True

_VUE = fraicheur_lectures.LECTURE_VUE_EXECUTIVE
_CHANTIER = fraicheur_lectures.LECTURE_MESURES_CHANTIER
_MANIFESTE_REEL = Path(__file__).resolve().parents[1] / "department.yaml"
_CLES = fraicheur_lectures.CLES_REPONSE


def _faits_chantier():
    return [
        {
            "type_entree": "wct", "wct_id": "w1", "intervention_id": "i1", "devis_id": "d1",
            "technicien_id": "tech-fictif", "horodatage_completion": "2026-09-28T14:00:00-04:00",
            "duree_reelle_minutes": 90, "statut": "completed_verified",
        },
        {
            "type_entree": "devis", "devis_id": "d1", "prix_total": "600.00", "cout_total": "480.00",
            "duree_estimee_minutes": "100", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
        },
    ]


def _par_nom():
    faits_entonnoir = [entonnoir.fait_lead_recu({
        "lead_id": "lead-1-fictif", "client_id": "a" * 64, "horodatage_association": "2026-09-29T09:15:00-04:00",
    })]
    return {
        o.nom: o
        for o in outils(RegistreSnapshots(), [], _faits_chantier(), faits_entonnoir, faits_cash_libre_cible=[])
    }


@pytest.fixture
def declarer(tmp_path, monkeypatch):
    """Pose `department.yaml/configuration` du test ; sans appel, M8 lit le vrai manifeste (rien de déclaré)."""
    def poser(configuration):
        manifeste = tmp_path / "department.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": configuration}), encoding="utf-8")
        monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)

    return poser


@pytest.fixture(autouse=True)
def m6_absent(monkeypatch):
    """Aucun autre département n'est lu : la vue dit son manque M6 (déterministe, sans effet)."""
    monkeypatch.setattr(m8_outils, "charger_departements", lambda: {})


def _vue():
    reponse = executer(_par_nom()[_VUE], {})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _chantier(wct_id="w1"):
    reponse = executer(_par_nom()[_CHANTIER], {"wct_id": wct_id})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _sans(reponse):
    return {cle: valeur for cle, valeur in reponse.items() if cle not in _CLES}


def _empreinte_a_la_main(lecture, secondes):
    """Forme canonique de `encodage.encoder_canonique` reconstruite sans l'appeler : `<longueur>:<json compact>` d'un
    dictionnaire normalisé `["__dict__", [[clé, valeur], …]]` trié par clé."""
    corps = json.dumps(
        ["__dict__", [["fraicheur_attendue_s", secondes], ["lecture", lecture]]],
        separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(f"{len(corps)}:{corps}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Non déclarée : rien ne change
# ---------------------------------------------------------------------------
def test_le_manifeste_livre_ne_declare_aucune_fenetre():
    configuration = yaml.safe_load(_MANIFESTE_REEL.read_text(encoding="utf-8"))["configuration"]

    assert configuration[fraicheur_lectures.CLE_CONFIGURATION] == {}
    assert m8_outils._fraicheur_attendue(_VUE) == {} and m8_outils._fraicheur_attendue(_CHANTIER) == {}


def test_non_declaree_les_deux_lectures_ne_portent_aucune_cle_de_fraicheur():
    vue, chantier = _vue(), _chantier()

    assert not (_CLES & set(vue)) and not (_CLES & set(chantier))
    assert set(vue) == {"vue", "portee", "entonnoir", "marge_reelle", "stock_a_commander", "cash_libre", "manques"}
    assert set(chantier) == {
        "wct_id", "trouve", "devis_id", "horodatage_completion", "mesures", "manques", "seuils", "seuils_a_configurer",
    }


@pytest.mark.parametrize("bloc", [None, {}])
def test_bloc_vide_ou_nul_et_autres_cles_sans_rapport_sont_identiques_au_manifeste_livre(declarer, bloc):
    reference = (_vue(), _chantier())
    declarer({fraicheur_lectures.CLE_CONFIGURATION: bloc, "autre": 1})

    assert (_vue(), _chantier()) == reference


def test_une_lecture_sans_declaration_a_cote_d_une_autre_reste_sans_cle(declarer):
    declarer({"fraicheur_lectures_s": {_VUE: 3600}})

    assert not (_CLES & set(_chantier()))


def test_un_chantier_inconnu_n_a_aucun_instant_a_dater_donc_aucune_fenetre(declarer):
    declarer({"fraicheur_lectures_s": {_CHANTIER: 3600}})

    inconnu = _chantier("absent")

    assert inconnu == {"wct_id": "absent", "trouve": False, "verdict": "REJ-CHANTIER-INCONNU:absent"}


# ---------------------------------------------------------------------------
# Déclarée et valide
# ---------------------------------------------------------------------------
def test_declaree_la_vue_expose_la_fenetre_et_sa_version_sans_rien_changer_d_autre(declarer):
    sans_declaration = _vue()
    declarer({"fraicheur_lectures_s": {_VUE: 86400}})

    vue = _vue()

    assert vue["fraicheur_attendue_s"] == 86400
    assert vue["version_definition_fraicheur"] == _empreinte_a_la_main(_VUE, 86400)
    assert _sans(vue) == sans_declaration
    assert not ({"fraicheur_attendue_refusee", "fraicheur_attendue_ignorees"} & set(vue))


def test_declaree_les_mesures_d_un_chantier_exposent_la_fenetre_de_leur_propre_lecture(declarer):
    sans_declaration = _chantier()
    declarer({"fraicheur_lectures_s": {_CHANTIER: 7200, _VUE: 60}})

    chantier = _chantier()

    assert chantier["fraicheur_attendue_s"] == 7200 and type(chantier["fraicheur_attendue_s"]) is int
    assert chantier["version_definition_fraicheur"] == _empreinte_a_la_main(_CHANTIER, 7200)
    assert _sans(chantier) == sans_declaration


def test_les_bornes_sont_acceptees_une_seconde_et_trois_mille_six_cent_cinquante_jours(declarer):
    for secondes in (1, 3650 * 86400):
        declarer({"fraicheur_lectures_s": {_VUE: secondes}})
        assert _vue()["fraicheur_attendue_s"] == secondes


def test_la_declaration_ne_change_aucune_version_de_definition_de_metrique(declarer):
    avant = [(m["metric_id"], m["version_definition"]) for m in _vue()["entonnoir"]["mesures"]]
    declarer({"fraicheur_lectures_s": {_VUE: 86400}})

    apres = [(m["metric_id"], m["version_definition"]) for m in _vue()["entonnoir"]["mesures"]]

    assert apres == avant and avant
    for definition in mesures_chantier.charger_definitions().values():
        assert "fraicheur_attendue_s" not in definition


# ---------------------------------------------------------------------------
# Valeurs invalides : refusées, dites, jamais exposées
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "invalide",
    [True, False, 0, -1, -3600, 3.5, 3600.0, "3600", "", None, [3600], {"s": 3600}, 3650 * 86400 + 1, 10**12],
)
def test_une_valeur_invalide_est_refusee_et_aucune_fenetre_n_est_exposee(declarer, invalide):
    declarer({"fraicheur_lectures_s": {_VUE: invalide}})

    vue = _vue()

    assert "fraicheur_attendue_s" not in vue and "version_definition_fraicheur" not in vue
    refus = vue["fraicheur_attendue_refusee"]
    assert set(refus) == {"raison", "source"} and refus["raison"]
    assert refus["source"] == fraicheur_lectures.SOURCE
    assert _sans(vue) == _sans_declaration_reelle(declarer)


def _sans_declaration_reelle(declarer):
    declarer({})
    return _vue()


def test_un_bloc_qui_n_est_pas_un_dictionnaire_est_refuse_pour_chaque_lecture(declarer):
    for illisible in ([86400], "86400", 86400):
        declarer({"fraicheur_lectures_s": illisible})
        for reponse in (_vue(), _chantier()):
            assert "fraicheur_attendue_s" not in reponse and "fraicheur_attendue_refusee" in reponse


def test_une_cle_qui_n_est_pas_une_lecture_declarable_est_dite_jamais_ignoree_en_silence(declarer):
    declarer({"fraicheur_lectures_s": {_VUE: 3600, "m8_lire_vue_executif": 60, "m8_lire_mesures_contenus": 60}})

    for reponse in (_vue(), _chantier()):
        assert reponse["fraicheur_attendue_ignorees"] == ["m8_lire_mesures_contenus", "m8_lire_vue_executif"]
    assert _vue()["fraicheur_attendue_s"] == 3600 and "fraicheur_attendue_s" not in _chantier()


def test_une_valeur_invalide_sur_une_lecture_n_empeche_pas_l_autre(declarer):
    declarer({"fraicheur_lectures_s": {_VUE: 0, _CHANTIER: 600}})

    assert "fraicheur_attendue_refusee" in _vue() and "fraicheur_attendue_s" not in _vue()
    assert _chantier()["fraicheur_attendue_s"] == 600 and "fraicheur_attendue_refusee" not in _chantier()


def test_declarer_refuse_une_lecture_non_declarable():
    with pytest.raises(ValueError):
        fraicheur_lectures.declarer("m8_lire_mesures_contenus", {})


# ---------------------------------------------------------------------------
# Version de définition : déterministe
# ---------------------------------------------------------------------------
def test_la_version_est_deterministe_et_change_avec_la_fenetre_et_la_lecture():
    a = fraicheur_lectures.version_definition(_VUE, 86400)

    assert a == fraicheur_lectures.version_definition(_VUE, 86400) == _empreinte_a_la_main(_VUE, 86400)
    assert a == encodage.empreinte({"lecture": _VUE, "fraicheur_attendue_s": 86400})
    assert len(a) == 64 and int(a, 16) >= 0
    assert fraicheur_lectures.version_definition(_VUE, 86401) != a
    assert fraicheur_lectures.version_definition(_CHANTIER, 86400) != a


def test_la_version_reste_identique_d_une_lecture_a_l_autre_de_la_meme_declaration(declarer):
    declarer({"fraicheur_lectures_s": {_VUE: 86400}})

    assert _vue()["version_definition_fraicheur"] == _vue()["version_definition_fraicheur"]
    declarer({"fraicheur_lectures_s": {_VUE: 172800}})
    assert _vue()["version_definition_fraicheur"] == _empreinte_a_la_main(_VUE, 172800)


# ---------------------------------------------------------------------------
# Aucun nouveau grant
# ---------------------------------------------------------------------------
def test_aucun_outil_parametre_role_ou_palier_de_plus():
    par_nom = _par_nom()

    for nom, parametres in ((_VUE, {"aujourd_hui"}), (_CHANTIER, {"wct_id"})):
        outil = par_nom[nom]
        assert outil.autonomie == Autonomie.T0 and not outil.frontiere_humaine
        assert outil.roles_appareil == frozenset({"admin"})
        assert set(outil.parametres["properties"]) == parametres
        assert outil.parametres["additionalProperties"] is False
        assert len(outil.description) <= 1024
    assert not any("fraicheur" in nom for nom in par_nom)
    assert len(par_nom) == len(set(par_nom))


def test_le_module_est_pur_sans_import_opsys_ni_horloge():
    source = (Path(fraicheur_lectures.__file__)).read_text(encoding="utf-8")

    assert "import opsys" not in source and "from opsys" not in source
    for interdit in ("datetime", "time.", "now("):
        assert interdit not in source
