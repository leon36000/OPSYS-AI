"""Sources du modèle de soi : les ports de lecture existants (profil d'onboarding, équipes, pack, registres de M10).

Données fictives. Cas hostiles : profil illisible (ne fait rien disparaître), semaine incomplète (inconnue, pas courte),
source dont l'empreinte a changé, ligne de registre inventée, membres d'équipe (personnes) qui ne doivent jamais fuir.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
import yaml
from m10_memoire.registre import Registre

from opsys import equipes, packs
from opsys.mnemo import codes, soi, soi_sources
from opsys.mnemo.codes import ErreurMnemo
from opsys.taxonomie import Service

FICTIF = True
T1 = "2026-10-01T09:00:00+00:00"
T2 = "2026-11-01T09:00:00+00:00"
SHA = "c" * 64


def journee(debut="08:00", fin="16:00"):
    return [{"debut": debut, "fin": fin}]


def profil_equipes(*, complet=True):
    semaine = {
        "fuseau": "America/Montreal",
        "lundi": journee(),
        "mardi": journee(),
        "mercredi": journee(),
        "jeudi": journee(),
        "vendredi": journee(),
        "samedi": [],
        "dimanche": [],
    }
    incomplete = {k: v for k, v in semaine.items() if k != "dimanche"}
    brut = {
        "liste": [
            {
                "id": "eq-nord",
                "membres": ["personne.exemple.a", "personne.exemple.b"],
                "competences": ["gouttieres"],
                "depot": {"id": "depot-exemple", "latitude_microdegres": 45500000, "longitude_microdegres": -73600000},
                "quarts": [{"jour": 0, "debut_min": 420, "fin_min": 930}],
                "effectif_planifie": 3,
                "semaine_type": semaine,
            },
            {
                "id": "eq-sud",
                "membres": ["personne.exemple.c"],
                "competences": ["revetement", "gouttieres"],
                "depot": {"id": "depot-exemple", "latitude_microdegres": 45500000, "longitude_microdegres": -73600000},
                "quarts": [{"jour": 0, "debut_min": 420, "fin_min": 930}],
                "semaine_type": semaine if complet else incomplete,
            },
        ]
    }
    return equipes.normaliser_equipes(brut)


def profil(*, complet=True, **plus):
    base = soi_sources.Profil(
        services=(Service("gouttieres", "Gouttières et descentes"), Service("revetement", "Revêtement extérieur")),
        zone=("Laval", "Longueuil"),
        equipes=profil_equipes(complet=complet),
        pack=packs.charger_pack("generique-pme"),
    )
    for cle, valeur in plus.items():
        setattr(base, cle, valeur)
    return base


def verificateur_tout(source):
    return True


# ------------------------------------------------------------------------------------------------ profil
def test_le_profil_donne_services_zones_equipes_capacite_et_vocabulaire():
    obs, couvertes = soi_sources.observations_profil(profil(), T1)
    par_dim = {}
    for o in obs:
        par_dim.setdefault(o.dimension, {})[o.cle] = o.valeur
    assert set(par_dim["services"]) == {"gouttieres", "revetement"}
    assert par_dim["zones"]["zone_desservie"]["villes"] == ["Laval", "Longueuil"]
    assert par_dim["equipes"]["eq-nord"] == {"competences": ["gouttieres"], "effectif_planifie": 3}
    assert par_dim["equipes"]["eq-sud"]["competences"] == ["gouttieres", "revetement"] or par_dim["equipes"]["eq-sud"][
        "competences"
    ] == ["revetement", "gouttieres"]
    assert par_dim["capacite"]["eq-nord"]["heures_par_semaine"] == "40.00"  # 5 jours de 8 h, samedi et dimanche fermés
    assert par_dim["capacite"]["eq-nord"]["minutes_semaine_type"] == 2400
    assert par_dim["capacite"]["entreprise"]["heures_par_semaine"] == "80.00"
    assert couvertes["services"] == {"gouttieres", "revetement"} and couvertes["capacite"] == {
        "eq-nord",
        "eq-sud",
        "entreprise",
    }
    assert all(o.sources[0]["type"] == "onboarding" for o in obs)


def test_une_semaine_incomplete_est_inconnue_pas_plus_courte():
    obs, _ = soi_sources.observations_profil(profil(complet=False), T1)
    cap = {o.cle: o.valeur for o in obs if o.dimension == "capacite"}
    assert cap["eq-sud"] == {"minutes_semaine_type": None, "heures_par_semaine": None, "effectif_planifie": None}
    assert cap["entreprise"]["heures_par_semaine"] is None  # un total ne se calcule pas sur une équipe inconnue
    assert cap["eq-nord"]["heures_par_semaine"] == "40.00"


def test_les_membres_des_equipes_ne_sont_jamais_recopies():
    obs, _ = soi_sources.observations_profil(profil(), T1)
    texte = json.dumps([[o.dimension, o.cle, o.valeur, list(o.sources)] for o in obs], ensure_ascii=False)
    assert "personne.exemple" not in texte and "depot-exemple" not in texte and "latitude" not in texte


def test_une_partie_illisible_ne_produit_rien_et_ne_fait_rien_disparaitre():
    p = profil(erreurs={"services": "illisible", "equipes": "illisible"}, services=(), equipes=None)
    obs, couvertes = soi_sources.observations_profil(p, T1)
    assert {o.dimension for o in obs} == {"zones", "vocabulaire"} or {o.dimension for o in obs} == {"zones"}
    assert "services" not in couvertes and "equipes" not in couvertes and "capacite" not in couvertes
    absent = profil(services=())  # lisible mais vide : le profil dit bien « aucun service »
    _, couvertes = soi_sources.observations_profil(absent, T1)
    assert couvertes["services"] == set()


def test_le_profil_reel_de_l_instance_est_lu_par_les_modules_du_socle(opsys_home):
    opsys_home.mkdir(parents=True)
    (opsys_home / "entreprise.yaml").write_text(
        yaml.safe_dump(
            {
                "services": ["gouttieres", {"code": "calfeutrage", "libelle": "Calfeutrage"}],
                "zone_desservie": ["Laval"],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    p = soi_sources.lire_profil()
    assert (
        [s.code for s in p.services] == ["gouttieres", "calfeutrage"]
        and p.zone == ("Laval",)
        and p.equipes is None
        and not p.erreurs
    )
    (opsys_home / "entreprise.yaml").write_text("services: [pas, un, objet]\n", encoding="utf-8")
    cassé = soi_sources.lire_profil()
    assert "services" in cassé.erreurs and cassé.services == ()


# ------------------------------------------------------------------------------------------------ registres
def fait_analytique(ligne_id, horodatage, mesures):
    return {"type_entree": "fait_analytique", "ligne_id": ligne_id, "horodatage": horodatage, "mesures": mesures}


def mesure(metric_id, valeur, statut="calculee"):
    return {
        "metric_id": metric_id,
        "nom": "n",
        "domaine": "finance",
        "unite": "CAD",
        "proprietaire": "m05-financecore",
        "statut": statut,
        "valeur": valeur,
        "version_definition": SHA,
        "dernier_fait_le": T1,
        "fraicheur": "a_jour",
    }


def test_les_marges_viennent_de_la_derniere_consolidation_de_m8_sans_recalcul():
    maillons = [
        fait_analytique("1" * 64, T1, [mesure("m8_marge_prevue_cad", "30.00"), mesure("m8_leads_recus", "12")]),
        fait_analytique(
            "2" * 64, T2, [mesure("m8_marge_prevue_cad", "31.50"), mesure("m8_ecart_marge_cad", None, "non_calculable")]
        ),
    ]
    obs = soi_sources.observations_marges(maillons)
    assert [(o.cle, o.valeur["valeur"]) for o in obs] == [("m8_marge_prevue_cad", "31.50")]
    assert obs[0].sources[0]["ref"] == "registre:faits_analytiques:" + "2" * 64
    assert obs[0].sources[0]["departement"] == "m08-analytics" and obs[0].sources[0]["observe_le"] == T2


def completions(n, mois):
    return [(f"{i:064x}", f"2026-{mois[i % len(mois)]:02d}-10T10:00:00+00:00") for i in range(n)]


def test_la_saisonnalite_reste_inconnue_sous_les_seuils():
    assert soi_sources.observations_saisonnalite(completions(29, [1, 2, 3, 4, 5, 6])) == []
    assert (
        soi_sources.observations_saisonnalite(completions(60, [1, 2, 3, 4, 5])) == []
    )  # cinq mois distincts seulement
    obs = soi_sources.observations_saisonnalite(completions(60, [1, 2, 3, 4, 5, 6]))
    assert len(obs) == 1 and obs[0].valeur["observations"] == 60
    assert sum(obs[0].valeur["par_mois"].values()) == 60 and obs[0].valeur["par_mois"]["07"] == 0


# ------------------------------------------------------------------------------------------------ vérification
def registres_avec_ligne():
    ev, aff, fa = Registre(), Registre(), Registre()
    fa.ajouter({"type_entree": "fait_analytique", "horodatage": T1, "mesures": []})
    aff.ajouter(
        {
            "type_entree": "decision_enregistree",
            "horodatage": T1,
            "decision_id": "DEC-FICTIF-1",
            "raison": "r",
            "statut": "validee",
            "options_ecartees": "",
        }
    )
    return {"evenements": ev, "affaires": aff, "faits_analytiques": fa}, fa.lire()[0]["ligne_id"]


def test_une_source_se_verifie_elle_ne_se_declare_pas():
    registres, ligne = registres_avec_ligne()
    p = profil()
    v = soi_sources.verificateur(registres, p, connaissance_existe=lambda vid: vid == "ver123")
    h_services = p.empreinte_partie("services")
    ok = [
        {"type": "fait_departement", "ref": f"registre:faits_analytiques:{ligne}", "departement": "m08-analytics"},
        {"type": "onboarding", "ref": f"entreprise:services:{h_services}"},
        {"type": "onboarding", "ref": f"pack:{p.pack.id}:{p.pack.empreinte.split(':')[-1][:16]}"},
        {"type": "correction_humaine", "ref": "decision:DEC-FICTIF-1"},
        {"type": "fait_departement", "ref": "connaissance:ver123", "departement": "m05-financecore"},
    ]
    assert all(v(s) for s in ok)
    faux = [
        {"type": "fait_departement", "ref": "registre:faits_analytiques:" + "9" * 64, "departement": "m08-analytics"},
        {"type": "fait_departement", "ref": f"registre:faits_analytiques:{ligne}", "departement": "m05-financecore"},
        {"type": "fait_departement", "ref": "registre:inconnu:" + ligne, "departement": "m08-analytics"},
        {"type": "onboarding", "ref": "entreprise:services:0000000000000000"},  # empreinte périmée : le profil a changé
        {"type": "onboarding", "ref": "entreprise:secrets:" + h_services},
        {"type": "onboarding", "ref": "pack:autre-pack:" + "0" * 16},
        {"type": "correction_humaine", "ref": "decision:DEC-INVENTEE"},
        {"type": "fait_departement", "ref": "connaissance:absente", "departement": "m05-financecore"},
        {"type": "fait_departement", "ref": "direction:x:abc123456789", "departement": "m05-financecore"},
    ]
    assert not any(v(s) for s in faux)


def test_un_profil_illisible_ne_prouve_aucune_source_du_profil():
    registres, _ = registres_avec_ligne()
    p = profil()
    h = p.empreinte_partie("services")
    p.erreurs["services"] = "illisible"
    assert not soi_sources.verificateur(registres, p)({"type": "onboarding", "ref": f"entreprise:services:{h}"})


# ------------------------------------------------------------------------------------------------ construire
def test_construire_propose_tout_sans_rien_confirmer_et_rejouer_ne_change_rien():
    reg = Registre()
    obs, couvertes = soi_sources.observations_profil(profil(), T1)
    r = soi_sources.construire(
        reg, obs, couvertes, verificateur_sources=verificateur_tout, par="agent:m10", horodatage=T1
    )
    assert r["decompte"] == {"propose": len(obs)}
    st = soi.etat(reg)
    assert all(e["etat"] == "propose" for e in st.enonces.values())  # rien n'est confirmé par le constructeur
    n = len(reg.lire())
    r2 = soi_sources.construire(
        reg, obs, couvertes, verificateur_sources=verificateur_tout, par="agent:m10", horodatage=T2
    )
    assert r2["decompte"] == {"deja_propose": len(obs)} and len(reg.lire()) == n and r2["revisions"] == []


def test_construire_detecte_la_derive_apres_confirmation_sans_ecraser():
    reg = Registre()
    obs, couvertes = soi_sources.observations_profil(profil(), T1)
    soi_sources.construire(reg, obs, couvertes, verificateur_sources=verificateur_tout, par="agent:m10", horodatage=T1)
    humain = soi.Acteur("direction.fictive", "admin", "approbation")
    for e in list(soi.etat(reg).enonces.values()):
        soi.confirmer(reg, e["enonce_id"], acteur=humain, motif="Confirmé avec la direction", horodatage=T1)
    # le profil change : un service disparaît, la zone s'élargit
    p2 = profil(services=(Service("gouttieres", "Gouttières et descentes"),), zone=("Laval", "Longueuil", "Brossard"))
    obs2, couvertes2 = soi_sources.observations_profil(p2, T2)
    r = soi_sources.construire(
        reg, obs2, couvertes2, verificateur_sources=verificateur_tout, par="agent:m10", horodatage=T2
    )
    assert [x["dimension"] for x in r["revisions"]] == ["zones"]
    assert [(x["dimension"], x["cle"]) for x in r["sources_disparues"]] == [("services", "revetement")]
    st = soi.etat(reg)
    assert st.confirme("zones", "zone_desservie")["valeur"]["villes"] == ["Laval", "Longueuil"]  # intact
    assert st.confirme("services", "revetement") is not None  # toujours confirmé : la direction tranche
    assert [d["cle"] for d in st.derives_ouvertes()] == ["revetement"]
    # le service revient : le signal est levé
    r3 = soi_sources.construire(
        reg,
        *soi_sources.observations_profil(profil(), T2),
        verificateur_sources=verificateur_tout,
        par="agent:m10",
        horodatage=T2,
    )
    assert r3["derives_levees"] == 1 and soi.etat(reg).derives_ouvertes() == []


def test_construire_refuse_une_source_que_le_verificateur_ne_retrouve_pas():
    reg = Registre()
    obs, couvertes = soi_sources.observations_profil(profil(), T1)
    with pytest.raises(ErreurMnemo, match=codes.SOURCE_INTROUVABLE):
        soi_sources.construire(
            reg, obs, couvertes, verificateur_sources=lambda s: False, par="agent:m10", horodatage=T1
        )
    assert reg.lire() == [] or all(m["type_entree"] != "soi_enonce" for m in reg.lire())


def test_l_age_est_calcule_a_partir_de_l_instant_donne_pas_d_une_horloge():
    reg = Registre()
    obs, couvertes = soi_sources.observations_profil(profil(), T1)
    soi_sources.construire(reg, obs, couvertes, verificateur_sources=verificateur_tout, par="agent:m10", horodatage=T1)
    v = soi.vue(reg, lecteur="m10-memoire", maintenant=dt.datetime(2026, 12, 1, tzinfo=dt.UTC))
    assert {e["age_jours"] for e in v["enonces"]} == {61}
