"""PLAN T4.1-d : `m4_proposer_cedule` et `m4_appliquer_cedule`, de bout en bout, sur les VRAIS outils, le
registre durable (base SQLite migrée, ADR-0009) et des coordonnées CONFIRMÉES par `m4_confirmer_localisation`,
appelés comme en production (`executer_atomique`).

Scénario fictif de Repentigny à Joliette (`fixtures/scenario_cedule_repentigny_joliette.json`, `fictif: true`) :
six chantiers en deux grappes, deux équipes qui partent chacune de leur dépôt. Le tourniquet de `cedule.py`
(le repli « bridé ») est mesuré sur la même fixture avec la MÊME matrice que le plan proposé.

Les refus sont prouvés SANS écriture : le registre et la table des clés sont comparés avant et après.
"""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import json
from pathlib import Path

import pytest
from m4_field_ops import cedule, distances, etats, tournees
from m4_field_ops import registre as registre_m4
from m4_field_ops.outils import outils
from sqlalchemy import select

from opsys import contexte, identite, openclaw, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.schema import CLES_CHIFFREMENT

FICTIF = True
SCENARIO = json.loads(
    (Path(__file__).parent / "fixtures" / "scenario_cedule_repentigny_joliette.json").read_text(encoding="utf-8")
)
HORLOGE_APPAREIL_DEREGLEE = dt.datetime(2000, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
RECU_LE = dt.datetime(2030, 6, 2, 9, 0, 0, tzinfo=dt.UTC)
HORODATAGE = "2030-01-01T00:00:00+00:00"

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARIE = contexte.IdentiteAppelante(personne="marie.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")
FANTOME = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")

MARQUEUR = {
    "readiness_ok": True, "lead_id": "", "hash_tete_registre": None,
    "horodatage": "2030-01-01T00:00:00+00:00", "empreinte": "ab" * 32,
}
EQUIPES = ["eq-a", "eq-b"]
LEADS = {lead["lead_id"]: lead for lead in SCENARIO["leads"]}
PROCHES = ("L-E2E-01", "L-E2E-02")
ELOIGNE = "L-E2E-10"


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def instance(tmp_path, monkeypatch):
    """Base SQLite migrée ET dossier d'état jetables, avec les personnes fictives du scénario."""
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marie.fictif", "Marie Fictive", "mot-de-passe-marie-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def par_nom(instance):
    return {o.nom: o for o in outils()}


@contextlib.contextmanager
def _appareil(identite_appelante, recu_le=RECU_LE):
    """Ce que le serveur MCP pose pour un appel d'appareil ; sans identité : un appel d'agent."""
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
            pile.enter_context(contexte.receptionne_de(contexte.HorodatageAppareil(
                appareil="tel-fictif-t4-1-d", horodatage_appareil=HORLOGE_APPAREIL_DEREGLEE, recu_le=recu_le)))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _resultat(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _code_refus(reponse):
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _detail_refus(reponse):
    return reponse["resultat"]["verdict"]["detail"]


def _registre():
    return registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))


def _maillons():
    with stockage.transaction():
        return _registre().lire()


def _cles():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(
            CLES_CHIFFREMENT.c.portee, CLES_CHIFFREMENT.c.identifiant, CLES_CHIFFREMENT.c.cle)).all()
    return sorted(tuple(ligne) for ligne in lignes)


def _etat():
    return _maillons(), _cles()


def _du_type(type_entree):
    return [m for m in _maillons() if m["type_entree"] == type_entree]


def _technicien(intervention_id):
    with stockage.transaction():
        return etats.technicien_assigne(_registre(), intervention_id)


def _statut(intervention_id):
    with stockage.transaction():
        return etats.statut_courant(_registre(), intervention_id)


# -- le scénario --------------------------------------------------------------------------------------
def _inscrire(par_nom, lead, horodatage=HORODATAGE):
    """Inscrit le lead par le VRAI outil (qui cédule aussi, en tourniquet, cette seule intervention)."""
    marqueur = {**MARQUEUR, "lead_id": lead["lead_id"]}
    contrat = {
        "lead_id": lead["lead_id"], "conversation_id": f"C-{lead['lead_id']}", "type_travaux": lead["type_travaux"],
        "ville": lead["secteur"], "canal": "telephone", "contact": {"nom": "Client Fictif"},
        "urgence_declaree": lead["urgence_declaree"],
    }
    reponse = _appeler(par_nom, "m4_planifier_intervention", {
        "contrat": contrat, "marqueur": marqueur, "horodatage": horodatage, "sel": SCENARIO["sel_tourniquet"],
        "techniciens_disponibles": EQUIPES,
        "fenetres_disponibles": [{"debut": "2030-01-07T08:00:00-05:00", "fin": "2030-01-07T17:00:00-05:00"}],
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["intervention_id"]


def _confirmer(par_nom, lead, identite_appelante=ADMIN, motif="", **coordonnees):
    donnees = {
        "latitude_microdegres": lead["latitude_microdegres"], "longitude_microdegres": lead["longitude_microdegres"],
        **coordonnees,
    }
    return _appeler(par_nom, "m4_confirmer_localisation", {
        "chantier_id": lead["lead_id"], "action": "confirmee", "horodatage": HORODATAGE,
        "confirme_par": identite_appelante.personne,
        "adresse": {"numero_municipal": "10", "odonyme": "rue Fictive", "municipalite": lead["secteur"]},
        "source": "manuel", "motif": motif, **donnees,
    }, identite_appelante)


@pytest.fixture
def interventions(par_nom):
    """``{lead_id: intervention_id}`` des six leads, coordonnées confirmées par l'admin."""
    ids = {}
    for rang, lead in enumerate(SCENARIO["leads"]):
        ids[lead["lead_id"]] = _inscrire(par_nom, lead, f"2030-01-01T00:00:0{rang}+00:00")
        _resultat(_confirmer(par_nom, lead))
    return ids


def _equipes(depots=None):
    depots = SCENARIO["depots"] if depots is None else depots
    return [
        {
            "id": equipe["id"], "competences": list(equipe["competences"]),
            "depot": {"id": equipe["depot"], **depots[equipe["depot"]]}, "quarts": [dict(SCENARIO["quart"])],
        }
        for equipe in SCENARIO["equipes"]
    ]


def _arguments(interventions, **remplacements):
    """Arguments de `m4_proposer_cedule` pour le scénario ; ``remplacements`` écrase ou ajoute une clé."""
    arguments = {
        "horodatage": HORODATAGE,
        "equipes": _equipes(),
        "durees_par_type_travaux": dict(SCENARIO["durees_par_type_travaux"]),
        "competences_par_type_travaux": copy.deepcopy(SCENARIO["competences_par_type_travaux"]),
        "chantiers": [
            {"intervention_id": iid, "fenetre": dict(SCENARIO["fenetre_client"]), "creneau_fige": None}
            for _lead, iid in sorted(interventions.items())
        ],
        "parametres": dict(SCENARIO["parametres"]),
    }
    arguments.update(remplacements)
    return arguments


def _proposer(par_nom, interventions, identite_appelante=ADMIN, **remplacements):
    return _appeler(par_nom, "m4_proposer_cedule", _arguments(interventions, **remplacements), identite_appelante)


def _appliquer(par_nom, plan_id, identite_appelante=ADMIN, **remplacements):
    donnees = {
        "plan_id": plan_id, "horodatage": HORODATAGE,
        "confirme_par": identite_appelante.personne if identite_appelante else "agent.fictif", **remplacements,
    }
    return _appeler(par_nom, "m4_appliquer_cedule", donnees, identite_appelante)


def _routes(proposition):
    """``{équipe: [chantiers dans l'ordre des visites]}``."""
    return {route["equipe"]: [v["chantier"] for v in route["visites"]] for route in proposition["plan"]}


def _visites(proposition):
    return {
        v["chantier"]: (route["equipe"], route["jour"], v["debut_min"])
        for route in proposition["plan"] for v in route["visites"]
    }


# -- le tourniquet, mesuré sur la même fixture avec la même matrice ----------------------------------
def _points(interventions):
    points = [
        {"id": depot, "latitude_microdeg": p["latitude_microdegres"], "longitude_microdeg": p["longitude_microdegres"]}
        for depot, p in SCENARIO["depots"].items()
    ]
    for lead_id, iid in interventions.items():
        lead = LEADS[lead_id]
        points.append({
            "id": iid, "latitude_microdeg": lead["latitude_microdegres"],
            "longitude_microdeg": lead["longitude_microdegres"],
        })
    return points


def _matrice(interventions):
    parametres = {cle: SCENARIO["parametres"][cle] for cle in distances.BORNES_PARAMETRES}
    matrice, verdict = distances.matrice_palier0(_points(interventions), parametres)
    assert verdict is None, verdict
    return matrice


def _metres(matrice, parcours):
    rang = {identifiant: k for k, identifiant in enumerate(matrice["ids"])}
    return sum(matrice["metres"][rang[a]][rang[b]] for a, b in zip(parcours, parcours[1:], strict=False))


def _tourniquet(interventions, sel=None):
    """Kilomètres (en mètres) du tourniquet de `cedule.generer_cedule` : chaque technicien enchaîne ses
    chantiers dans l'ordre de ses fenêtres, du dépôt au dépôt, mesurés par la matrice fournie."""
    sel = SCENARIO["sel_tourniquet"] if sel is None else sel
    trie = sorted(interventions.items())
    fenetres = [
        {"debut": f"2030-01-07T{8 + 3 * k:02d}:00:00-05:00", "fin": f"2030-01-07T{11 + 3 * k:02d}:00:00-05:00"}
        for k in range(3)
    ]
    resultat, verdict = cedule.generer_cedule(
        [
            {"intervention_id": iid, "lead_id": lead_id, "type_travaux": LEADS[lead_id]["type_travaux"],
             "ville": LEADS[lead_id]["secteur"]}
            for lead_id, iid in trie
        ],
        EQUIPES, fenetres, sel,
    )
    assert verdict is None and resultat["non_cedulees"] == [], (verdict, resultat)
    matrice = _matrice(interventions)
    depot_de = {equipe["id"]: equipe["depot"] for equipe in SCENARIO["equipes"]}
    par_equipe = {}
    for assignation in sorted(resultat["assignations"], key=lambda a: a["fenetre"]["debut"]):
        par_equipe.setdefault(assignation["technicien_id"], []).append(assignation["intervention_id"])
    total = 0
    for equipe, chantiers in par_equipe.items():
        total += _metres(matrice, [depot_de[equipe], *chantiers, depot_de[equipe]])
    return total, par_equipe


# =========================================================================================
# 1. Déclaration : niveau, autonomie, portée d'appareil
# =========================================================================================
def test_les_deux_outils_sont_declares_avec_leur_niveau_et_leur_portee(par_nom):
    proposer, appliquer = par_nom["m4_proposer_cedule"], par_nom["m4_appliquer_cedule"]
    # Brouillon : T1 (écrit un maillon) mais N1, automatique. Le défaut T1 -> N3 mettrait chaque simulation
    # de l'admin en file d'approbation alors que rien n'est assigné.
    assert proposer.autonomie is Autonomie.T1 and proposer.niveau is Niveau.N1
    assert proposer.niveau_effectif is Niveau.N1 and not proposer.frontiere_humaine
    # Application : N3 (défaut de T1, « modification interne non finale »), jamais automatique en ombre.
    assert appliquer.autonomie is Autonomie.T1 and appliquer.niveau is None
    assert appliquer.niveau_effectif is Niveau.N3 and not appliquer.frontiere_humaine
    for outil in (proposer, appliquer):
        assert outil.roles_appareil == frozenset({"admin"}), outil.nom


def test_en_mode_ombre_la_proposition_est_automatique_et_l_application_attend_une_personne(par_nom):
    from opsys import politiques
    assert not politiques.approbation_requise_niveau(par_nom["m4_proposer_cedule"].niveau_effectif, "ombre")
    assert politiques.approbation_requise_niveau(par_nom["m4_appliquer_cedule"].niveau_effectif, "ombre")
    assert politiques.validation_au_depart_possible(par_nom["m4_appliquer_cedule"].niveau_effectif)


def test_les_portees_vues_par_le_core_sont_l_admin_seulement():
    departement = lire_manifeste(Path(__file__).resolve().parents[1])
    roles = openclaw.roles_outils({departement.id: departement})
    for outil in ("m4_proposer_cedule", "m4_appliquer_cedule"):
        assert outil in roles["admin"]
        assert outil not in roles["employee"] and outil not in roles["seller"]


# =========================================================================================
# 2. Le scénario de bout en bout : localisations confirmées, proposition, application
# =========================================================================================
def test_de_la_confirmation_des_positions_a_l_application_du_plan(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions))
    iid = interventions
    routes = _routes(proposition)

    # Ce que l'admin voit d'abord : le mode, les raisons de non-cédule, l'urgence lue au registre.
    assert proposition["mode_distance"] == "haversine_detour" and proposition["mode_bride"] is True
    assert "mode bridé" in proposition["avertissement"]
    assert proposition["non_cedulees"] == [] and proposition["totaux"]["chantiers_cedules"] == 6
    assert proposition["urgences"][iid["L-E2E-11"]] == 1 and proposition["urgences"][iid["L-E2E-01"]] == 0
    assert proposition["deja_proposee"] is False and proposition["horodatage_appareil"]

    # Deux chantiers proches vont à la même équipe, l'un après l'autre ; le chantier éloigné va à l'autre.
    equipe_proches = next(e for e, chantiers in routes.items() if iid["L-E2E-01"] in chantiers)
    chantiers = routes[equipe_proches]
    assert iid["L-E2E-02"] in chantiers
    assert abs(chantiers.index(iid["L-E2E-01"]) - chantiers.index(iid["L-E2E-02"])) == 1
    assert iid[ELOIGNE] not in chantiers and iid[ELOIGNE] in routes[next(e for e in routes if e != equipe_proches)]
    assert set(routes["eq-a"]) == {iid[k] for k in ("L-E2E-01", "L-E2E-02", "L-E2E-03")}
    assert set(routes["eq-b"]) == {iid[k] for k in ("L-E2E-10", "L-E2E-11", "L-E2E-12")}

    # Les kilomètres baissent contre le tourniquet, mesurés par la MÊME matrice.
    matrice = _matrice(interventions)
    assert matrice["empreinte"] == _du_type("cedule_proposee")[0]["sortie"]["meta"]["empreinte_matrice"]
    metres_tourniquet, _ = _tourniquet(interventions)
    assert proposition["totaux"]["distance_m"] < metres_tourniquet
    somme = sum(
        _metres(matrice, [depot, *chantiers, depot])
        for depot, chantiers in (("depot-repentigny", routes["eq-a"]), ("depot-joliette", routes["eq-b"]))
    )
    assert somme == proposition["totaux"]["distance_m"]

    # Proposer n'assigne rien : chaque intervention garde l'assignation provisoire du tourniquet (eq-a).
    assert {_technicien(i) for i in iid.values()} == {"eq-a"}
    assert _du_type("cedule_appliquee") == []

    # Application : l'admin authentifié, sous son nom.
    application = _resultat(_appliquer(par_nom, proposition["plan_id"]))
    assert application["deja_appliquee"] is False and application["appliquee_par"] == "admin.fictif"
    assert application["mode_bride"] is True and application["non_cedulees"] == []
    for chantier, equipe in ((c, e) for e, cs in routes.items() for c in cs):
        assert _technicien(chantier) == equipe
    assert sorted((a["intervention_id"], a["technicien_id"]) for a in application["assignations"]) == sorted(
        (c, e) for e, cs in routes.items() for c in cs)
    assert {a["effet"] for a in application["assignations"]} <= {"assignee", "deja_assignee"}
    assert all(_statut(i) == "planifiee" for i in iid.values())  # assigner n'est pas partir
    with stockage.transaction():
        assert _registre().valider_chaine()


def test_les_kilometres_baissent_contre_le_tourniquet_quel_que_soit_le_sel(par_nom, interventions):
    """Le tourniquet trie sur un hachage de ville salé : on le mesure pour treize sels, pour ne pas juger le
    plan sur un tirage favorable. Le plan proposé n'en dépend pas. Mesuré à la rédaction : le tourniquet
    va de 28 806 m (un sel où le hasard forme les mêmes grappes, dans un autre ordre) à 343 133 m, pour
    26 785 m au plan proposé, soit 187 601 m avec le sel de référence."""
    proposition = _resultat(_proposer(par_nom, interventions))
    plan_km = proposition["totaux"]["distance_m"]
    mesures = []
    for sel in [SCENARIO["sel_tourniquet"], *(f"sel-fictif-{k}" for k in range(1, 13))]:
        metres, par_equipe = _tourniquet(interventions, sel)
        assert sum(len(c) for c in par_equipe.values()) == 6
        assert plan_km < metres, (sel, plan_km, metres)
        mesures.append(metres)
    assert len(mesures) == 13
    assert sum(mesures) > 3 * plan_km * len(mesures)  # en moyenne, plus de trois fois les kilomètres du plan
    assert mesures[0] > 5 * plan_km  # avec le sel de référence, plus de cinq fois


def test_une_equipe_visite_les_deux_proches_avant_l_eloigne_dont_la_fenetre_ouvre_l_apres_midi(
    par_nom, interventions,
):
    """Une seule équipe, trois chantiers : les deux proches (Repentigny, Le Gardeur), puis Joliette, dont le
    client n'est là qu'à partir de 13 h. Le plan les enchaîne dans cet ordre et respecte la fenêtre."""
    iid = interventions
    choisies = [iid[lead] for lead in (*PROCHES, ELOIGNE)]
    chantiers = [
        {"intervention_id": i, "fenetre": {**SCENARIO["fenetre_client"], "debut_min": 780} if i == iid[ELOIGNE]
         else dict(SCENARIO["fenetre_client"]), "creneau_fige": None}
        for i in choisies
    ]
    proposition = _resultat(_proposer(
        par_nom, interventions, equipes=_equipes()[:1], chantiers=chantiers, intervention_ids=choisies))
    assert _routes(proposition) == {"eq-a": [iid["L-E2E-01"], iid["L-E2E-02"], iid[ELOIGNE]]}
    assert _visites(proposition)[iid[ELOIGNE]][2] >= 780
    assert proposition["non_cedulees"] == []


def test_proposer_deux_fois_n_ecrit_rien_de_plus(par_nom, interventions):
    premiere = _resultat(_proposer(par_nom, interventions))
    avant = _etat()
    seconde = _resultat(_proposer(par_nom, interventions))
    assert seconde["plan_id"] == premiere["plan_id"] and seconde["deja_proposee"] is True
    assert seconde["empreinte_sortie"] == premiere["empreinte_sortie"]
    assert _etat() == avant and len(_du_type("cedule_proposee")) == 1


def test_le_maillon_du_plan_ne_porte_aucune_coordonnee_de_chantier(par_nom, interventions):
    _resultat(_proposer(par_nom, interventions))
    maillon = _du_type("cedule_proposee")[0]
    texte = json.dumps(maillon, ensure_ascii=False)
    for lead in SCENARIO["leads"]:
        assert str(lead["latitude_microdegres"]) not in texte and str(lead["longitude_microdegres"]) not in texte
    assert "matrice" not in maillon["entree"]
    # Le dépôt, lui, est un lieu de l'entreprise : il est gardé pour pouvoir revérifier le plan.
    assert maillon["entree"]["equipes"][0]["depot"]["id"] == "depot-repentigny"
    assert maillon["propose_par"] == "admin.fictif"
    assert set(maillon["empreinte_entree"] + maillon["empreinte_sortie"] + maillon["empreinte_etat"]) <= set(
        "0123456789abcdef")


# =========================================================================================
# 3. Un créneau confirmé au client n'est jamais déplacé
# =========================================================================================
def test_un_creneau_fige_est_respecte_meme_contre_la_geographie(par_nom, interventions):
    """Charlemagne (grappe de Repentigny) est promis à l'équipe de Joliette à 10 h : le plan le tient, à
    l'heure dite, même si ce n'est pas le plus court."""
    iid = interventions
    libre = _resultat(_proposer(par_nom, interventions))
    assert _visites(libre)[iid["L-E2E-03"]][0] == "eq-a"
    figes = {iid["L-E2E-03"]: {"equipe": "eq-b", "jour": 0, "debut_min": 600}}
    chantiers = [
        {"intervention_id": i, "fenetre": dict(SCENARIO["fenetre_client"]), "creneau_fige": figes.get(i)}
        for _lead, i in sorted(interventions.items())
    ]
    proposition = _resultat(_proposer(par_nom, interventions, chantiers=chantiers))
    assert _visites(proposition)[iid["L-E2E-03"]] == ("eq-b", 0, 600)
    assert proposition["plan_id"] != libre["plan_id"]
    assert proposition["totaux"]["distance_m"] > libre["totaux"]["distance_m"]  # le prix d'une promesse

    application = _resultat(_appliquer(par_nom, proposition["plan_id"]))
    assert _technicien(iid["L-E2E-03"]) == "eq-b"
    assert {a["technicien_id"] for a in application["assignations"] if a["intervention_id"] == iid["L-E2E-03"]} == {
        "eq-b"}


def test_un_creneau_fige_intenable_refuse_toute_la_proposition_sans_rien_ecrire(par_nom, interventions):
    iid = interventions
    chantiers = [
        {"intervention_id": i, "fenetre": dict(SCENARIO["fenetre_client"]),
         "creneau_fige": {"equipe": "eq-c", "jour": 0, "debut_min": 600} if i == iid["L-E2E-03"] else None}
        for _lead, i in sorted(interventions.items())
    ]
    avant = _etat()
    reponse = _proposer(par_nom, interventions, chantiers=chantiers)
    assert _code_refus(reponse) == "REJ-TOURNEES-CRENEAU-FIGE-INCOMPATIBLE"
    assert "eq-c" in _detail_refus(reponse)
    assert _etat() == avant


# =========================================================================================
# 4. Application : refus si l'état a changé, rien d'écrit
# =========================================================================================
def test_une_coordonnee_modifiee_entre_la_proposition_et_l_application_refuse_sans_rien_ecrire(
    par_nom, interventions,
):
    proposition = _resultat(_proposer(par_nom, interventions))
    lead = LEADS["L-E2E-03"]
    # L'admin corrige la position de Charlemagne (déplacée de quelques kilomètres) : version 2.
    _resultat(_confirmer(
        par_nom, lead, motif="position vérifiée sur place", latitude_microdegres=45790000,
        longitude_microdegres=-73520000))
    avant = _etat()
    reponse = _appliquer(par_nom, proposition["plan_id"])
    assert _code_refus(reponse) == "REJ-CEDULE-ENTREE-CHANGEE"
    assert "proposer de nouveau" in _detail_refus(reponse) and "localisation" in _detail_refus(reponse)
    assert _etat() == avant and _du_type("cedule_appliquee") == []
    # Une nouvelle proposition tient compte de la coordonnée corrigée, puis s'applique.
    nouvelle = _resultat(_proposer(par_nom, interventions))
    assert nouvelle["plan_id"] != proposition["plan_id"]
    assert _resultat(_appliquer(par_nom, nouvelle["plan_id"]))["deja_appliquee"] is False


def test_une_intervention_changee_entre_la_proposition_et_l_application_refuse(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions))
    iid = interventions["L-E2E-12"]
    with stockage.transaction():
        _, verdict = etats.transitionner(iid, "annulee", _registre(), HORODATAGE)
        assert verdict is None
    avant = _etat()
    reponse = _appliquer(par_nom, proposition["plan_id"])
    assert _code_refus(reponse) == "REJ-CEDULE-ENTREE-CHANGEE" and "statut" in _detail_refus(reponse)
    assert _etat() == avant


def test_une_coordonnee_retiree_refuse_aussi(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions))
    lead = LEADS["L-E2E-02"]
    _resultat(_appeler(par_nom, "m4_confirmer_localisation", {
        "chantier_id": lead["lead_id"], "action": "retiree", "horodatage": HORODATAGE,
        "confirme_par": "admin.fictif", "motif": "adresse contestée par le client",
    }, ADMIN))
    avant = _etat()
    assert _code_refus(_appliquer(par_nom, proposition["plan_id"])) == "REJ-CEDULE-ENTREE-CHANGEE"
    assert _etat() == avant


def test_une_autre_assignation_entre_les_deux_refuse(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions))
    with stockage.transaction():
        _, verdict = etats.assigner_technicien(interventions["L-E2E-01"], "eq-b", _registre(), HORODATAGE)
        assert verdict is None
    reponse = _appliquer(par_nom, proposition["plan_id"])
    assert _code_refus(reponse) == "REJ-CEDULE-ENTREE-CHANGEE" and "technicien_assigne" in _detail_refus(reponse)


def test_un_plan_inconnu_est_un_verdict(par_nom, interventions):
    avant = _etat()
    assert _code_refus(_appliquer(par_nom, "0" * 64)) == "REJ-CEDULE-PLAN-INTROUVABLE"
    assert _etat() == avant


def test_appliquer_deux_fois_est_idempotent(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions))
    premiere = _resultat(_appliquer(par_nom, proposition["plan_id"]))
    apres_premiere = _etat()
    seconde = _resultat(_appliquer(par_nom, proposition["plan_id"]))
    assert seconde["deja_appliquee"] is True and seconde["assignations"] == premiere["assignations"]
    assert _etat() == apres_premiere and len(_du_type("cedule_appliquee")) == 1


def test_un_technicien_deja_assigne_n_est_pas_reassigne(par_nom, interventions):
    """L'assignation provisoire du tourniquet (eq-a) est déjà la bonne pour la grappe de Repentigny : aucun
    maillon d'assignation de plus pour elle ; les chantiers de Joliette, eux, changent d'équipe."""
    proposition = _resultat(_proposer(par_nom, interventions))
    avant = len(_du_type("assignation_technicien"))
    application = _resultat(_appliquer(par_nom, proposition["plan_id"]))
    effets = {a["intervention_id"]: a["effet"] for a in application["assignations"]}
    for lead_id in ("L-E2E-01", "L-E2E-02", "L-E2E-03"):
        assert effets[interventions[lead_id]] == "deja_assignee"
    for lead_id in ("L-E2E-10", "L-E2E-11", "L-E2E-12"):
        assert effets[interventions[lead_id]] == "assignee"
    assert len(_du_type("assignation_technicien")) == avant + 3


# =========================================================================================
# 5. Sans coordonnées confirmées : jamais le centre d'une ville
# =========================================================================================
def test_un_chantier_sans_coordonnees_confirmees_est_non_cedule_avec_sa_raison(par_nom, instance):
    ids = {}
    for rang, lead in enumerate(SCENARIO["leads"]):
        ids[lead["lead_id"]] = _inscrire(par_nom, lead, f"2030-01-01T00:00:0{rang}+00:00")
        if lead["lead_id"] != "L-E2E-12":
            _resultat(_confirmer(par_nom, lead))
    proposition = _resultat(_proposer(par_nom, ids))
    assert [ligne["chantier"] for ligne in proposition["non_cedulees"]] == [ids["L-E2E-12"]]
    ligne = proposition["non_cedulees"][0]
    assert ligne["code"] == "coordonnees_manquantes" and "coordonnées manquantes : à confirmer" in ligne["raison"]
    assert proposition["totaux"]["chantiers_cedules"] == 5
    application = _resultat(_appliquer(par_nom, proposition["plan_id"]))
    conservee = application["non_cedulees"][0]
    assert conservee["chantier"] == ids["L-E2E-12"] and conservee["assignation_conservee"] == "eq-a"
    assert _technicien(ids["L-E2E-12"]) == "eq-a"  # aucun outil de désassignation : le repli garde la sienne


# =========================================================================================
# 6. Ce que M4 ne sait pas : un argument, sinon un seul verdict qui dit tout
# =========================================================================================
def test_les_arguments_manquants_sont_un_seul_verdict_qui_liste_tout(par_nom, interventions):
    avant = _etat()
    reponse = _proposer(
        par_nom, interventions, durees_par_type_travaux={"ravalement": 120},
        competences_par_type_travaux={"autre": ["gouttieres"]}, chantiers=[], parametres={"iterations": 500},
    )
    assert _code_refus(reponse) == "REJ-CHAMP-MANQUANT"
    detail = _detail_refus(reponse)
    for attendu in (
        "durees_par_type_travaux.extension", "durees_par_type_travaux.isolation_thermique",
        "competences_par_type_travaux.ravalement", "facteur_detour_milliemes", "vitesse_moyenne_kmh",
        "marge_par_trajet_secondes", "cout_non_cedule_m", "chantiers : entrée de l'intervention",
    ):
        assert attendu in detail, (attendu, detail)
    assert _etat() == avant


def test_aucun_champ_n_a_de_valeur_par_defaut(par_nom, interventions):
    base = _arguments(interventions)
    for cle in ("equipes", "durees_par_type_travaux", "competences_par_type_travaux", "chantiers", "parametres"):
        arguments = {c: v for c, v in base.items() if c != cle}
        reponse = _appeler(par_nom, "m4_proposer_cedule", arguments, ADMIN)
        # T4.12 : le schéma n'exige plus que l'horodatage (le profil des équipes peut tout fournir) ; sans profil,
        # une valeur absente est un verdict qui la nomme ET dit où la déclarer, jamais une valeur par défaut.
        assert _code_refus(reponse) == "REJ-CHAMP-MANQUANT", cle
        assert cle in _detail_refus(reponse) and "opsys equipes declarer" in _detail_refus(reponse), cle
    assert _appeler(par_nom, "m4_proposer_cedule", {}, ADMIN)["erreur"] == "arguments_invalides"  # horodatage requis
    for cle in ("facteur_detour_milliemes", "vitesse_moyenne_kmh", "marge_par_trajet_secondes", "iterations",
                "cout_non_cedule_m"):
        parametres = {c: v for c, v in base["parametres"].items() if c != cle}
        reponse = _proposer(par_nom, interventions, parametres=parametres)
        assert _code_refus(reponse) == "REJ-CHAMP-MANQUANT" and cle in _detail_refus(reponse)
    # Un créneau figé oublié n'est pas « aucun » : il faut dire null.
    chantiers = [{"intervention_id": i, "fenetre": dict(SCENARIO["fenetre_client"])} for i in interventions.values()]
    reponse = _proposer(par_nom, interventions, chantiers=chantiers)
    assert _code_refus(reponse) == "REJ-CHAMP-MANQUANT" and "creneau_fige manquant" in _detail_refus(reponse)


def test_une_valeur_hors_bornes_ou_un_champ_inconnu_est_refuse(par_nom, interventions):
    reponse = _proposer(par_nom, interventions, parametres={**SCENARIO["parametres"], "vitesse_moyenne_kmh": 500})
    assert _code_refus(reponse) == "REJ-CONTRAT-INVALIDE" and "vitesse_moyenne_kmh" in _detail_refus(reponse)
    reponse = _proposer(par_nom, interventions, parametres={**SCENARIO["parametres"], "detour": 1300})
    assert _code_refus(reponse) == "REJ-CONTRAT-INVALIDE" and "detour" in _detail_refus(reponse)
    equipes = _equipes()
    equipes[0]["vehicule"] = "camion"
    reponse = _proposer(par_nom, interventions, equipes=equipes)
    assert _code_refus(reponse) == "REJ-CONTRAT-INVALIDE" and "vehicule" in _detail_refus(reponse)
    reponse = _proposer(par_nom, interventions, durees_par_type_travaux={**SCENARIO["durees_par_type_travaux"],
                                                                         "toiture": 60})
    assert _code_refus(reponse) == "REJ-CONTRAT-INVALIDE" and "toiture" in _detail_refus(reponse)
    reponse = _proposer(par_nom, interventions, moteur="hasard")
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"


def test_une_intervention_inconnue_ou_hors_du_lot_est_refusee(par_nom, interventions):
    chantiers = _arguments(interventions)["chantiers"]
    chantiers.append({"intervention_id": "inconnue", "fenetre": dict(SCENARIO["fenetre_client"]),
                      "creneau_fige": None})
    reponse = _proposer(par_nom, interventions, chantiers=chantiers)
    assert _code_refus(reponse) == "REJ-CONTRAT-INVALIDE" and "inconnue" in _detail_refus(reponse)
    reponse = _proposer(par_nom, interventions, intervention_ids=["inconnue"])
    assert _code_refus(reponse) == "REJ-CEDULE-INTERVENTION-NON-PLANIFIABLE"


def test_sans_intervention_planifiee_rien_a_planifier(par_nom, instance):
    reponse = _appeler(par_nom, "m4_proposer_cedule", {
        "horodatage": HORODATAGE, "equipes": _equipes(), "durees_par_type_travaux": {},
        "competences_par_type_travaux": {}, "chantiers": [], "parametres": dict(SCENARIO["parametres"]),
    }, ADMIN)
    assert _code_refus(reponse) == "REJ-CEDULE-RIEN-A-PLANIFIER"


def test_intervention_ids_restreint_la_proposition_a_ces_interventions(par_nom, interventions):
    choisies = [interventions["L-E2E-01"], interventions["L-E2E-02"]]
    chantiers = [c for c in _arguments(interventions)["chantiers"] if c["intervention_id"] in choisies]
    proposition = _resultat(_proposer(par_nom, interventions, chantiers=chantiers, intervention_ids=choisies))
    assert proposition["totaux"]["chantiers_cedules"] == 2
    assert sorted(v for c in _routes(proposition).values() for v in c) == sorted(choisies)


def test_les_competences_par_type_de_travaux_decident_de_l_equipe(par_nom, interventions):
    """Les ravalements exigent « revetement » ; seule eq-b l'a : les deux ravalements (Repentigny et Joliette)
    vont à eq-b, même le plus proche du dépôt de eq-a."""
    equipes = _equipes()
    equipes[0]["competences"] = ["gouttieres"]
    proposition = _resultat(_proposer(par_nom, interventions, equipes=equipes))
    visites = _visites(proposition)
    for lead_id in ("L-E2E-01", ELOIGNE):
        assert visites[interventions[lead_id]][0] == "eq-b"


# =========================================================================================
# 7. L'urgence déclarée est lue (elle ne l'était pas)
# =========================================================================================
def _lead_urgence(numero, site, urgence):
    lead = LEADS[site]
    return {**lead, "lead_id": f"L-URG-{numero}", "type_travaux": "extension", "urgence_declaree": urgence}


def test_l_urgence_declaree_decide_qui_l_on_garde_quand_il_manque_de_place(par_nom, instance):
    """Une équipe, une demi-journée : la place d'UN chantier de 150 min, entre un chantier tout près du dépôt
    et un autre à L'Assomption. Sans urgence, le plus court gagne (le plus près). Quand le plus loin déclare
    l'urgence, laisser de côté un chantier urgent coûte le double : c'est lui qui est gardé, contre la
    distance. Avant T4.1-d, `urgence_declaree` n'était lue par personne."""
    pres, loin = "L-E2E-01", "L-E2E-04"
    LEADS["L-E2E-04"] = {**LEADS["L-E2E-03"], "lead_id": "L-E2E-04", "secteur": "L'Assomption",
                         "latitude_microdegres": 45822000, "longitude_microdegres": -73427000}
    try:
        equipes = _equipes()[:1]
        equipes[0]["quarts"] = [{"jour": 0, "debut_min": 480, "fin_min": 780}]
        parametres = {**SCENARIO["parametres"], "cout_non_cedule_m": 60000}
        gardes = {}
        for essai, urgent in (("A", None), ("B", "loin")):
            ids = {}
            for numero, site in ((f"{essai}1", pres), (f"{essai}2", loin)):
                lead = _lead_urgence(numero, site, urgent == "loin" and site == loin)
                ids[site] = _inscrire(par_nom, lead, f"2030-02-01T00:00:0{numero[-1]}+00:00" if essai == "A"
                                      else f"2030-02-02T00:00:0{numero[-1]}+00:00")
                _resultat(_confirmer(par_nom, lead))
            chantiers = [
                {"intervention_id": iid, "fenetre": dict(SCENARIO["fenetre_client"]), "creneau_fige": None}
                for iid in ids.values()
            ]
            proposition = _resultat(_proposer(
                par_nom, ids, equipes=equipes, chantiers=chantiers, parametres=parametres,
                intervention_ids=sorted(ids.values())))
            gardes[essai] = (ids, proposition)
    finally:
        LEADS.pop("L-E2E-04", None)
    ids_a, proposition_a = gardes["A"]
    ids_b, proposition_b = gardes["B"]
    assert [v for c in _routes(proposition_a).values() for v in c] == [ids_a[pres]]
    assert [v for c in _routes(proposition_b).values() for v in c] == [ids_b[loin]]
    assert proposition_a["urgences"] == {ids_a[pres]: 0, ids_a[loin]: 0}
    assert proposition_b["urgences"] == {ids_b[pres]: 0, ids_b[loin]: 1}
    assert [ligne["chantier"] for ligne in proposition_b["non_cedulees"]] == [ids_b[pres]]


# =========================================================================================
# 8. Contrôle d'accès : qui peut proposer, appliquer, et sous quel nom
# =========================================================================================
@pytest.mark.parametrize("appelant", [MARC, VENDEUR])
def test_un_employe_ou_un_vendeur_est_refuse_par_les_deux_outils_sans_rien_ecrire(
    par_nom, interventions, appelant,
):
    proposition = _resultat(_proposer(par_nom, interventions))
    avant = _etat()
    reponse = _proposer(par_nom, interventions, appelant, horodatage="2031-01-01T00:00:00+00:00")
    assert _code_refus(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE" and "sans portée" in _detail_refus(reponse)
    assert _code_refus(_appliquer(par_nom, proposition["plan_id"], appelant)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _etat() == avant and _du_type("cedule_appliquee") == []


def test_un_admin_ne_peut_pas_appliquer_sous_le_nom_d_un_autre(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions))
    avant = _etat()
    reponse = _appliquer(par_nom, proposition["plan_id"], ADMIN, confirme_par="marie.fictif")
    assert _code_refus(reponse) == "REJ-IDENTITE-FOURNIE-DIFFERENTE"
    assert _etat() == avant  # refusé, jamais remplacé en silence
    assert _resultat(_appliquer(par_nom, proposition["plan_id"], MARIE))["appliquee_par"] == "marie.fictif"


def test_une_personne_inconnue_ou_desactivee_ne_propose_ni_n_applique_rien(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions))
    avant = _etat()
    assert _code_refus(_proposer(par_nom, interventions, FANTOME)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _code_refus(_appliquer(par_nom, proposition["plan_id"], FANTOME)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _etat() == avant


def test_le_serveur_horodate_l_appel_d_appareil(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions, horodatage="2030-03-03T00:00:00+00:00"))
    assert proposition["horodatage"] == RECU_LE.isoformat()  # l'heure du serveur, jamais celle qu'on affirme
    assert proposition["horodatage_appareil"] == HORLOGE_APPAREIL_DEREGLEE.isoformat()
    application = _resultat(_appliquer(par_nom, proposition["plan_id"], horodatage="2030-03-04T00:00:00+00:00"))
    assert application["horodatage"] == RECU_LE.isoformat()
    assert application["horodatage_appareil"] == HORLOGE_APPAREIL_DEREGLEE.isoformat()
    assert all(m["horodatage"] == RECU_LE.isoformat() for m in _du_type("assignation_technicien")[-3:])


def test_un_appel_d_agent_garde_l_horodatage_qu_il_donne(par_nom, interventions):
    agent = _resultat(_proposer(par_nom, interventions, None, horodatage="2030-03-03T00:00:00+00:00"))
    assert agent["horodatage"] == "2030-03-03T00:00:00+00:00" and "horodatage_appareil" not in agent
    assert agent["propose_par"] is None
    assert _du_type("cedule_proposee")[0]["propose_par"] is None


def test_un_appel_d_agent_sans_identite_applique_sous_le_nom_qu_il_donne(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions, None))
    application = _resultat(_appliquer(par_nom, proposition["plan_id"], None))
    assert application["appliquee_par"] == "agent.fictif"


# =========================================================================================
# 9. Routage : le port de la matrice, mode bridé et repli
# =========================================================================================
class FaussePasserelleRoutage:
    """Fournisseur de trajets FICTIF : lignes droites x 1,5, ou un verdict imposé."""

    def __init__(self, verdict=None):
        self.verdict = verdict

    def descripteur(self):
        return {"mode_distance": "fictif_routage", "fournisseur": "fictif", "version_donnees": "jeu-1"}

    def trajets(self, points):
        if self.verdict is not None:
            return None, self.verdict
        n = len(points)
        metres = [[0] * n for _ in range(n)]
        secondes = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i != j:
                    droite = distances.distance_droite_m(
                        points[i]["latitude_microdeg"], points[i]["longitude_microdeg"],
                        points[j]["latitude_microdeg"], points[j]["longitude_microdeg"])
                    metres[i][j] = droite * 3 // 2
                    secondes[i][j] = droite * 3 // 2 // 12
        return {"metres": metres, "secondes": secondes}, None


def test_un_fournisseur_de_routage_leve_le_mode_brides(instance, interventions):
    par_nom = {o.nom: o for o in outils(fournisseur_matrice=FaussePasserelleRoutage())}
    proposition = _resultat(_proposer(par_nom, interventions))
    assert proposition["mode_distance"] == "fictif_routage" and proposition["mode_bride"] is False
    assert proposition["avertissement"] is None
    assert _resultat(_appliquer(par_nom, proposition["plan_id"]))["mode_bride"] is False


def test_un_trajet_introuvable_est_un_verdict_jamais_une_route_inventee(instance, interventions):
    verdict = distances.verdict_matrice(distances.CODE_TRAJET_INTROUVABLE, "aucune route vers un point")
    par_nom = {o.nom: o for o in outils(fournisseur_matrice=FaussePasserelleRoutage(verdict))}
    avant = _etat()
    assert _code_refus(_proposer(par_nom, interventions)) == "REJ-MATRICE-TRAJET-INTROUVABLE"
    assert _etat() == avant


def test_un_fournisseur_en_panne_donne_un_repli_marque_brides(instance, interventions):
    verdict = distances.verdict_matrice(distances.CODE_FOURNISSEUR_INDISPONIBLE, "sidecar arrêté")
    par_nom = {o.nom: o for o in outils(fournisseur_matrice=FaussePasserelleRoutage(verdict))}
    proposition = _resultat(_proposer(par_nom, interventions))
    assert proposition["mode_bride"] is True and "mode bridé" in proposition["avertissement"]
    maillon = _du_type("cedule_proposee")[0]
    assert maillon["sortie"]["meta"]["mode_bride"] is True


def test_appliquer_avec_un_autre_fournisseur_que_la_proposition_refuse(instance, interventions):
    """Le plan a été calculé sur des routes ; sans le même fournisseur, la matrice n'est plus la même."""
    avec = {o.nom: o for o in outils(fournisseur_matrice=FaussePasserelleRoutage())}
    sans = {o.nom: o for o in outils()}
    proposition = _resultat(_proposer(avec, interventions))
    avant = _etat()
    assert _code_refus(_appliquer(sans, proposition["plan_id"])) == "REJ-CEDULE-ENTREE-CHANGEE"
    assert _etat() == avant


# =========================================================================================
# 10. Le plan stocké est revérifié : un plan altéré n'est jamais appliqué
# =========================================================================================
def test_un_plan_altere_dans_le_registre_est_refuse_par_verifier_plan(par_nom, interventions):
    """Le registre est append-only : on forge ici, à côté, un maillon de plan dont une visite a été déplacée
    hors du quart. L'application le refuse (et ne touche à rien)."""
    proposition = _resultat(_proposer(par_nom, interventions))
    maillon = copy.deepcopy(_du_type("cedule_proposee")[0])
    for cle in ("ligne_id", "precedent_ligne_id"):
        maillon.pop(cle)
    route = maillon["sortie"]["plan"][0]
    route["visites"][0]["debut_min"] += 600
    route["visites"][0]["fin_min"] += 600
    sortie = maillon["sortie"]
    sortie["meta"].pop("empreinte_sortie")
    from m4_field_ops import encodage
    sortie["meta"]["empreinte_sortie"] = encodage.empreinte(sortie)  # re-scellé : seules les contraintes refusent
    maillon["empreinte_sortie"] = sortie["meta"]["empreinte_sortie"]
    maillon["plan_id"] = "forge-" + proposition["plan_id"]
    with stockage.transaction():
        _registre().ajouter(maillon)
    avant = _etat()
    reponse = _appliquer(par_nom, maillon["plan_id"])
    assert _code_refus(reponse) == "REJ-TOURNEES-PLAN-INVALIDE"
    assert _etat() == avant and _du_type("cedule_appliquee") == []


def test_un_plan_dont_l_empreinte_ne_correspond_pas_au_maillon_est_refuse(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions))
    maillon = copy.deepcopy(_du_type("cedule_proposee")[0])
    for cle in ("ligne_id", "precedent_ligne_id"):
        maillon.pop(cle)
    maillon["plan_id"] = "faux-" + proposition["plan_id"]
    maillon["empreinte_sortie"] = "0" * 64
    with stockage.transaction():
        _registre().ajouter(maillon)
    assert _code_refus(_appliquer(par_nom, maillon["plan_id"])) == "REJ-TOURNEES-PLAN-INVALIDE"


def test_le_plan_repasse_verifier_plan_avec_les_coordonnees_d_aujourd_hui(par_nom, interventions):
    proposition = _resultat(_proposer(par_nom, interventions))
    maillon = _du_type("cedule_proposee")[0]
    entree = maillon["entree"]
    # L'entrée rebuilt à la main (positions confirmées lues par l'outil de T4.1-a) redonne l'empreinte stockée.
    matrice = _matrice(interventions)
    reconstruite = {
        "version": tournees.VERSION_ENTREE,
        "equipes": [{**{k: v for k, v in e.items() if k != "depot"}, "depot": e["depot"]["id"]}
                    for e in entree["equipes"]],
        "chantiers": entree["chantiers"], "matrice": matrice, "parametres": entree["parametres"],
    }
    empreinte, verdict = tournees.empreinte_entree(reconstruite)
    assert verdict is None and empreinte == proposition["empreinte_entree"]
    ok, violations = tournees.verifier_plan(reconstruite, maillon["sortie"])
    assert ok, violations


def test_le_scenario_ne_touche_pas_au_reseau_ni_a_l_horloge(instance, interventions, monkeypatch):
    import socket

    def interdit(*_args, **_kwargs):
        raise AssertionError("accès réseau interdit dans la cédule")

    monkeypatch.setattr(socket, "socket", interdit)
    monkeypatch.setattr(socket, "create_connection", interdit)
    monkeypatch.setattr(socket, "getaddrinfo", interdit)
    par_nom = {o.nom: o for o in outils()}
    proposition = _resultat(_proposer(par_nom, interventions))
    assert _resultat(_appliquer(par_nom, proposition["plan_id"]))["deja_appliquee"] is False


def test_schema_des_arguments_refuse_un_champ_inconnu_ou_un_type_faux(par_nom, interventions):
    avant = _etat()
    reponse = _appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": "x", "horodatage": HORODATAGE, "confirme_par": "admin.fictif", "force": True}, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    reponse = _appeler(par_nom, "m4_appliquer_cedule", {
        "plan_id": 12, "horodatage": HORODATAGE, "confirme_par": "admin.fictif"}, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    reponse = _proposer(par_nom, interventions, equipes="eq-a")
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert _etat() == avant
