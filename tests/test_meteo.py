"""Profil météo de l'entreprise (PLAN T4.13) : lu dans `entreprise.yaml`, jamais inventé, aucun seuil par défaut.

Fixture FICTIVE (`fictif: true`) : `tests/fixtures/meteo_fictive.json`. Le fournisseur est fermé par défaut ; Open-Meteo
ne s'ouvre qu'avec un forfait commercial (décision du propriétaire, PLAN T4.13, GATE NATHAN).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from opsys import etat, meteo, taxonomie
from opsys.meteo import ProfilInvalide

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "meteo_fictive.json").read_text(encoding="utf-8"))


def profil_fictif() -> dict:
    assert FIXTURE["fictif"] is True
    return copy.deepcopy(FIXTURE["profil"])


def _ecrire_yaml(contenu: str) -> Path:
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(contenu, encoding="utf-8")
    return fichier


def _avec(service="gouttieres", **modifs) -> dict:
    """Le profil fictif dont le service donné reçoit ces sous-clés (une valeur `None` retire la clé)."""
    profil = profil_fictif()
    for cle, valeur in modifs.items():
        if valeur is None:
            profil["services"][service].pop(cle, None)
        else:
            profil["services"][service][cle] = valeur
    return profil


def _seuil(mesure, valeur):
    profil = profil_fictif()
    profil["services"]["gouttieres"]["seuils"][mesure] = valeur
    return profil


# ---------------------------------------------------------------------------
# Sans profil : un verdict qui dit quoi déclarer, jamais un seuil par défaut
# ---------------------------------------------------------------------------
def test_sans_profil_aucun_seuil_n_est_invente_et_le_verdict_dit_quoi_declarer(opsys_home):
    profil, verdict = meteo.charger_meteo()
    assert profil is None
    assert verdict["code"] == meteo.VERDICT_METEO_NON_CONFIGUREE
    assert str(taxonomie.fichier_profil()) in verdict["detail"]
    assert "opsys-metier meteo declarer --depuis" in verdict["detail"] and "--par" in verdict["detail"]
    assert "seuil à configurer" in verdict["detail"]
    assert meteo.lire_meteo() is None


def test_un_profil_de_services_sans_meteo_n_a_pas_de_meteo(opsys_home, declarer_services):
    declarer_services("gouttieres")
    assert meteo.charger_meteo()[0] is None
    assert meteo.verifier_profil() == []  # l'absence n'est pas une erreur


def test_un_profil_vide_est_l_absence_pas_un_profil_valide(opsys_home):
    _ecrire_yaml("meteo: {}\n")
    assert meteo.charger_meteo()[1]["code"] == meteo.VERDICT_METEO_NON_CONFIGUREE
    with pytest.raises(ProfilInvalide, match="vide"):
        meteo.enregistrer_meteo({})


# ---------------------------------------------------------------------------
# Déclaration, relecture, cohabitation avec les autres clés
# ---------------------------------------------------------------------------
def test_un_profil_declare_se_relit_a_l_identique_et_les_autres_cles_restent(opsys_home, declarer_services):
    declarer_services("gouttieres", "revetement")
    taxonomie.enregistrer_zone_desservie(["Laval"])
    fichier = meteo.enregistrer_meteo(profil_fictif())
    assert fichier == taxonomie.fichier_profil()
    profil, verdict = meteo.charger_meteo()
    assert verdict is None and profil == profil_fictif()
    assert [s.code for s in taxonomie.lire_services()] == ["gouttieres", "revetement"]
    assert taxonomie.lire_zone_desservie() == ("Laval",)
    taxonomie.enregistrer_services(["reparation"])  # déclarer une autre clé n'écrase pas la météo
    assert meteo.lire_meteo() == profil_fictif()
    assert yaml.safe_load(fichier.read_text(encoding="utf-8"))["meteo"] == profil_fictif()


def test_declarer_remplace_la_cle_entiere(opsys_home):
    meteo.enregistrer_meteo(profil_fictif())
    meteo.enregistrer_meteo({"services": {"reparation": {"sans_objet": list(meteo.RISQUES)}}})
    assert list(meteo.lire_meteo()["services"]) == ["reparation"]


def test_la_declaration_est_canonique_services_mesures_et_risques_tries(opsys_home):
    brut = {
        "services": {
            "revetement": {
                "sans_objet": ["chaleur", "gel"],
                "seuils": {"verglas": {"blocage": True}, "vent_kmh": {"blocage": 10}},
            },
            "gouttieres": {"sans_objet": list(meteo.RISQUES)},
        },
    }
    propre = meteo.normaliser_meteo(brut)
    assert list(propre["services"]) == ["gouttieres", "revetement"]
    assert list(propre["services"]["revetement"]["seuils"]) == ["vent_kmh", "verglas"]
    assert propre["services"]["revetement"]["sans_objet"] == ["gel", "chaleur"]


def test_l_empreinte_est_stable_et_suit_le_contenu(opsys_home):
    assert meteo.empreinte_meteo(profil_fictif()) == meteo.empreinte_meteo(profil_fictif())
    autre = _seuil("vent_kmh", {"validation": 35, "blocage": 51})
    assert meteo.empreinte_meteo(autre) != meteo.empreinte_meteo(profil_fictif())
    assert len(meteo.empreinte_meteo(profil_fictif())) == 64


def test_la_declaration_signee_va_au_journal_sans_le_nom_de_la_variable_de_la_cle(session):
    profil = profil_fictif()
    profil.update(
        {"fournisseur": "open_meteo", "open_meteo": {"forfait": "commercial", "cle_env": "OPSYS_CLE_FICTIVE"}}
    )
    meteo.enregistrer_meteo(profil, par="nathan")
    with etat.session() as cnx:
        (entree, *_) = etat.lire_journal(cnx)
    assert entree["par"] == "nathan" and entree["action"] == "entreprise.meteo"
    assert entree["details"]["fournisseur"] == "open_meteo" and entree["details"]["forfait"] == "commercial"
    assert entree["details"]["services"] == ["gouttieres", "revetement"]
    assert "OPSYS_CLE_FICTIVE" not in json.dumps(entree["details"])
    assert entree["details"]["empreinte"] == meteo.empreinte_meteo(meteo.lire_meteo())


# ---------------------------------------------------------------------------
# Validation : chaque refus dit quoi corriger, rien n'est arrondi ni deviné
# ---------------------------------------------------------------------------
REFUS = [
    ("cle_inconnue_du_profil", {"cle_pirate": 1}, "clés inconnues"),
    ("profil_pas_un_objet", ["services"], "doit être un objet"),
    ("services_vide", {"services": {}}, "est vide"),
    ("services_pas_un_objet", {"services": ["gouttieres"]}, "doit être un objet"),
    ("code_de_service_invalide", {"services": {"Gouttières": {"sans_objet": ["vent"]}}}, "code de service invalide"),
    ("service_vide", {"services": {"gouttieres": {}}}, "est vide"),
    ("cle_de_service_inconnue", {"services": {"gouttieres": {"limites": {}}}}, "clés inconnues"),
    ("seuils_vide", {"services": {"gouttieres": {"seuils": {}}}}, "objet non vide"),
    ("mesure_inconnue", {"services": {"gouttieres": {"seuils": {"neige_cm": {"blocage": 5}}}}}, "mesures inconnues"),
    ("seuil_sans_niveau", {"services": {"gouttieres": {"seuils": {"vent_kmh": {}}}}}, "au moins un niveau"),
    ("niveau_inconnu", {"services": {"gouttieres": {"seuils": {"vent_kmh": {"alerte": 30}}}}}, "clés inconnues"),
    (
        "booleen_pris_pour_un_entier",
        {"services": {"gouttieres": {"seuils": {"vent_kmh": {"blocage": True}}}}},
        "un entier est attendu",
    ),
    (
        "decimal_refuse",
        {"services": {"gouttieres": {"seuils": {"vent_kmh": {"blocage": 4.5}}}}},
        "un entier est attendu",
    ),
    (
        "texte_refuse",
        {"services": {"gouttieres": {"seuils": {"vent_kmh": {"blocage": "40"}}}}},
        "un entier est attendu",
    ),
    ("vent_negatif", {"services": {"gouttieres": {"seuils": {"vent_kmh": {"blocage": -1}}}}}, "entre 0 et 300"),
    ("vent_trop_grand", {"services": {"gouttieres": {"seuils": {"vent_kmh": {"blocage": 301}}}}}, "entre 0 et 300"),
    (
        "probabilite_au_dessus_de_100",
        {"services": {"gouttieres": {"seuils": {"pluie_probabilite_pct": {"blocage": 101}}}}},
        "entre 0 et 100",
    ),
    ("gel_trop_froid", {"services": {"gouttieres": {"seuils": {"gel_c": {"blocage": -61}}}}}, "entre -60 et 40"),
    (
        "validation_apres_le_blocage",
        {"services": {"gouttieres": {"seuils": {"vent_kmh": {"validation": 50, "blocage": 40}}}}},
        "au plus égale au blocage",
    ),
    (
        "gel_validation_sous_le_blocage",
        {"services": {"gouttieres": {"seuils": {"gel_c": {"validation": -3, "blocage": 0}}}}},
        "au moins égale au blocage",
    ),
    ("verglas_pas_un_booleen", {"services": {"gouttieres": {"seuils": {"verglas": {"blocage": 1}}}}}, "true ou false"),
    (
        "verglas_jamais_vrai",
        {"services": {"gouttieres": {"seuils": {"verglas": {"blocage": False}}}}},
        "au moins un niveau",
    ),
    ("sans_objet_pas_une_liste", {"services": {"gouttieres": {"sans_objet": "vent"}}}, "une liste de risques"),
    ("sans_objet_risque_inconnu", {"services": {"gouttieres": {"sans_objet": ["neige"]}}}, "risque inconnu"),
    ("sans_objet_en_double", {"services": {"gouttieres": {"sans_objet": ["vent", "vent"]}}}, "en double"),
    (
        "risque_juge_et_sans_objet",
        {"services": {"gouttieres": {"seuils": {"vent_kmh": {"blocage": 40}}, "sans_objet": ["vent"]}}},
        "à la fois jugés",
    ),
    ("fuseau_mal_forme", {"fuseau": "Montréal"}, "base des fuseaux"),
    ("fournisseur_inconnu", {"fournisseur": "meteomedia", "fuseau": "America/Toronto"}, "msc_geomet ou open_meteo"),
    ("fournisseur_sans_fuseau", {"fournisseur": "msc_geomet"}, "exige 'meteo.fuseau'"),
    (
        "open_meteo_sans_fournisseur",
        {"open_meteo": {"forfait": "commercial", "cle_env": "OPSYS_CLE_FICTIVE"}},
        "n'a de sens qu'avec",
    ),
    (
        "open_meteo_sans_forfait_declare",
        {"fournisseur": "open_meteo", "fuseau": "America/Toronto"},
        "exige 'meteo.open_meteo'",
    ),
    (
        "open_meteo_gratuit",
        {
            "fournisseur": "open_meteo",
            "fuseau": "America/Toronto",
            "open_meteo": {"forfait": "gratuit", "cle_env": "OPSYS_CLE_FICTIVE"},
        },
        "non commercial",
    ),
    (
        "open_meteo_sans_cle",
        {"fournisseur": "open_meteo", "fuseau": "America/Toronto", "open_meteo": {"forfait": "commercial"}},
        "clés manquantes",
    ),
    (
        "open_meteo_cle_dans_le_fichier",
        {
            "fournisseur": "open_meteo",
            "fuseau": "America/Toronto",
            "open_meteo": {"forfait": "commercial", "cle_env": "sk-ceci-est-une-cle"},
        },
        "la clé n'entre jamais dans ce fichier",
    ),
]


@pytest.mark.parametrize(
    ("brut", "message"), [(brut, message) for _, brut, message in REFUS], ids=[nom for nom, _, _ in REFUS]
)
def test_une_declaration_invalide_est_refusee_avec_le_message_qui_dit_quoi_corriger(opsys_home, brut, message):
    with pytest.raises(ProfilInvalide, match=message):
        meteo.normaliser_meteo(brut)
    with pytest.raises(ProfilInvalide):
        meteo.enregistrer_meteo(brut)
    assert not taxonomie.fichier_profil().exists(), "un refus n'écrit rien"


def test_le_forfait_gratuit_d_open_meteo_est_refuse_pour_l_entreprise_avec_la_raison_de_la_licence(opsys_home):
    with pytest.raises(ProfilInvalide) as erreur:
        meteo.normaliser_meteo(
            {
                "fournisseur": "open_meteo",
                "fuseau": "America/Toronto",
                "open_meteo": {"forfait": "gratuit", "cle_env": "OPSYS_CLE_FICTIVE"},
            }
        )
    texte = str(erreur.value)
    assert "usage non commercial" in texte and "décision du propriétaire" in texte and "2026-09-29" in texte


def test_open_meteo_commercial_est_accepte_avec_le_nom_d_une_variable_jamais_la_cle(opsys_home):
    propre = meteo.normaliser_meteo(
        {
            "fournisseur": "open_meteo",
            "fuseau": "America/Toronto",
            "open_meteo": {"forfait": "commercial", "cle_env": "OPSYS_CLE_FICTIVE"},
        }
    )
    assert propre["open_meteo"] == {"forfait": "commercial", "cle_env": "OPSYS_CLE_FICTIVE"}


def test_msc_geomet_avec_un_fuseau_est_accepte_sans_reglage_de_plus(opsys_home):
    propre = meteo.normaliser_meteo({"fournisseur": "msc_geomet", "fuseau": "America/Toronto"})
    assert propre == {"fournisseur": "msc_geomet", "fuseau": "America/Toronto"}


def test_sans_cle_fournisseur_le_profil_ne_ferme_ni_n_ouvre_rien(opsys_home):
    assert "fournisseur" not in meteo.normaliser_meteo(profil_fictif())


def test_un_seuil_egal_pour_validation_et_blocage_est_permis(opsys_home):
    propre = meteo.normaliser_meteo(_seuil("vent_kmh", {"validation": 40, "blocage": 40}))
    assert propre["services"]["gouttieres"]["seuils"]["vent_kmh"] == {"validation": 40, "blocage": 40}


def test_les_bornes_sont_incluses(opsys_home):
    for mesure, (_, _, bornes) in meteo.MESURES.items():
        if bornes is None:
            continue
        for borne in bornes:
            propre = meteo.normaliser_meteo(
                {
                    "services": {
                        "s": {
                            "seuils": {mesure: {"blocage": borne}},
                            "sans_objet": [r for r in meteo.RISQUES if r != meteo.MESURES[mesure][0]],
                        }
                    }
                }
            )
            assert propre["services"]["s"]["seuils"][mesure] == {"blocage": borne}


# ---------------------------------------------------------------------------
# Profil invalide : jamais lu comme absent
# ---------------------------------------------------------------------------
def test_un_profil_invalide_est_un_verdict_distinct_de_l_absence(opsys_home):
    _ecrire_yaml("meteo:\n  services:\n    gouttieres:\n      seuils:\n        vent_kmh: {blocage: quarante}\n")
    profil, verdict = meteo.charger_meteo()
    assert profil is None and verdict["code"] == "REJ-PROFIL-INVALIDE"
    assert verdict["code"] != meteo.VERDICT_METEO_NON_CONFIGUREE
    assert "un entier est attendu" in verdict["detail"]
    with pytest.raises(ProfilInvalide):
        meteo.lire_meteo()


def test_un_fichier_illisible_n_est_pas_un_profil_vide(opsys_home):
    _ecrire_yaml("meteo: [\n")
    assert meteo.charger_meteo()[1]["code"] == "REJ-PROFIL-INVALIDE"


# ---------------------------------------------------------------------------
# Ce qu'il reste à décider
# ---------------------------------------------------------------------------
def test_risques_a_decider_sans_regles_les_cinq():
    assert meteo.risques_a_decider(None) == list(meteo.RISQUES) == meteo.risques_a_decider({})


def test_risques_a_decider_ni_juges_ni_sans_objet():
    regles = {"seuils": {"vent_kmh": {"blocage": 40}, "pluie_mm_h": {"blocage": 3}}, "sans_objet": ["chaleur"]}
    assert meteo.risques_a_decider(regles) == ["gel", "verglas"]
    assert meteo.risques_a_decider(profil_fictif()["services"]["gouttieres"]) == []
    assert meteo.risques_a_decider(profil_fictif()["services"]["revetement"]) == []


def test_a_declarer_sans_profil_dit_de_declarer_le_profil():
    (manque,) = meteo.a_declarer(None, ["gouttieres"])
    assert "opsys-metier meteo declarer" in manque


def test_a_declarer_nomme_les_services_qui_ont_des_risques_sans_decision():
    profil = meteo.normaliser_meteo({"services": {"gouttieres": {"seuils": {"vent_kmh": {"blocage": 40}}}}})
    manques = meteo.a_declarer(profil, ["gouttieres", "revetement"])
    assert any("'gouttieres'" in m and "pluie, gel, verglas, chaleur" in m for m in manques)
    assert any("'revetement'" in m and "vent, pluie, gel, verglas, chaleur" in m for m in manques)
    assert meteo.a_declarer(meteo.normaliser_meteo(profil_fictif()), ["gouttieres", "revetement"]) == []


def test_le_fournisseur_n_est_jamais_un_manque():
    profil = meteo.normaliser_meteo(profil_fictif())
    assert "fournisseur" not in profil
    assert not any("fournisseur" in m for m in meteo.a_declarer(profil, ["gouttieres"]))


# ---------------------------------------------------------------------------
# opsys-metier verifier
# ---------------------------------------------------------------------------
def test_verifier_profil_un_profil_present_doit_parler_de_services_declares(opsys_home, declarer_services):
    declarer_services("gouttieres")
    meteo.enregistrer_meteo(profil_fictif())  # 'revetement' n'est pas déclaré
    (probleme,) = meteo.verifier_profil()
    assert "'revetement'" in probleme and "services déclarés : gouttieres" in probleme
    declarer_services("gouttieres", "revetement")
    assert meteo.verifier_profil() == []


def test_verifier_profil_signale_un_profil_invalide(opsys_home):
    _ecrire_yaml("meteo:\n  fuseau: 12\n")
    (probleme,) = meteo.verifier_profil()
    assert "base des fuseaux" in probleme


# ---------------------------------------------------------------------------
# Le catalogue des mesures
# ---------------------------------------------------------------------------
def test_chaque_risque_a_au_moins_une_mesure_et_chaque_mesure_un_risque_connu():
    assert {risque for risque, _, _ in meteo.MESURES.values()} == set(meteo.RISQUES)
    assert meteo.RISQUES == ("vent", "pluie", "gel", "verglas", "chaleur")


def test_le_gel_se_mesure_vers_le_bas_et_le_reste_vers_le_haut():
    sens = {mesure: sens for mesure, (_, sens, _) in meteo.MESURES.items()}
    assert sens["gel_c"] == "<=" and sens["verglas"] == "presence"
    assert {m for m, s in sens.items() if s == ">="} == {
        "vent_kmh",
        "rafales_kmh",
        "pluie_mm_h",
        "pluie_probabilite_pct",
        "chaleur_c",
    }


def test_le_module_n_ouvre_aucune_connexion_et_ne_lit_aucune_cle():
    texte = Path(meteo.__file__).read_text(encoding="utf-8")
    for interdit in ("import socket", "urllib", "requests", "httpx", "os.environ", "getenv"):
        assert interdit not in texte, interdit
