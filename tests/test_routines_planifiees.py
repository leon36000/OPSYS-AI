"""Routines planifiées : la DÉCLARATION (manifeste), la cadence suivie ou déclarée, les définitions d'exécuteurs, le
contrôle de
cohérence et les garde-fous. Pur ou base SQLite jetable ; aucune donnée réelle.

Le socle ne contient aucun horaire, aucun nom de département ni aucun nom d'outil : tout ce que ce fichier vérifie
vient des
`department.yaml` de M1 et de M10.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re
from pathlib import Path

import pytest
import yaml

from opsys import profils
from opsys.connecteurs_planification import etat, inventaire, planificateur, routines
from opsys.connecteurs_planification.planificateur import Contexte, NiveauInterdit, Ports
from opsys.departements import RoutinePlanifiee, charger_departements, lire_manifeste

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
LIRE_M1, CONSIGNER_M1 = "m1_lire_attentes_reception", "m1_consigner_a_voir_reception"
ATTENDUES = {
    "m1.routine.digest-reception": ("m1", (LIRE_M1, CONSIGNER_M1), ("suit", "digest-front-office"), 900),
    "m1.routine.rappels-et-suivis": ("m1", (LIRE_M1, CONSIGNER_M1), ("intervalle_s", 900), 900),
    "m1.routine.urgences": ("m1", (LIRE_M1, CONSIGNER_M1), ("intervalle_s", 300), 300),
    "m1.routine.kpis-reception": ("m1", ("m1_calculer_kpis",), ("cron", "30 6 * * *"), 900),
    "m10.routine.consolidation-affaires": (
        "m10",
        ("m10_lister_affaires_a_consolider", "m10_consolider_affaire"),
        ("suit", "consolidation-nocturne"),
        900,
    ),
    "m10.routine.audit-non-oubli": ("m10", ("m10_executer_audit_non_oubli",), ("cron", "30 4 * * 1"), 900),
    "m10.routine.kpis-memoire": ("m10", ("m10_calculer_kpis",), ("cron", "45 4 * * *"), 900),
}


# -- les manifestes livrés ---------------------------------------------------------------------------------------------
def test_les_routines_de_m1_et_de_m10_sont_declarees_par_leurs_manifestes():
    deps = charger_departements(RACINE / "departments")
    declarees = {d.nom: d for d in routines.declarations(deps)}
    assert set(declarees) == set(ATTENDUES)
    for nom, (code, outils, cadence, _) in ATTENDUES.items():
        assert declarees[nom].code.lower() == code and declarees[nom].routine.outils == outils, nom
        assert declarees[nom].routine.cadence == cadence, nom
    assert routines.problemes(deps) == []


def test_chaque_outil_de_routine_est_agent_seulement_n0_ou_n2_sans_droit_d_appareil_ni_frontiere_humaine():
    deps = charger_departements(RACINE / "departments")
    for declaration in routines.declarations(deps):
        par_nom = {o.nom: o for o in deps[declaration.departement].charger_outils()}
        for nom in declaration.routine.outils:
            outil = par_nom[nom]
            assert outil.niveau_effectif.value in ("N0", "N2") and outil.autonomie.value in ("T0", "T1"), nom
            assert not outil.roles_appareil and not outil.frontiere_humaine, nom


def test_le_socle_ne_contient_ni_horaire_ni_nom_de_departement_ni_nom_d_outil_pour_les_routines():
    for fichier in ("routines.py",):
        source = (RACINE / "src/opsys/connecteurs_planification" / fichier).read_text(encoding="utf-8")
        for interdit in (
            "m1_lire",
            "m1_consigner",
            "m1_calculer",
            "m10_",
            "digest-front-office",
            "consolidation-nocturne",
            "m01-front-office",
            "m10-memoire",
            "0 7 * * 1-5",
            "0 3 * * *",
            "30 4 * * 1",
        ):
            assert interdit not in source, (fichier, interdit)


def test_les_definitions_sont_n2_famille_routines_et_sans_transport_ni_plafond():
    definitions = {d.nom: d for d in routines.definitions_declarees()}
    assert set(definitions) == set(ATTENDUES)
    for nom, definition in definitions.items():
        assert definition.famille == "routines" and definition.niveau == "N2" and not definition.irreversible, nom
        assert definition.transport is None and definition.plafond_appels_jour is None and len(nom) <= 40
        assert definition.intervalle_defaut_s == ATTENDUES[nom][3]
        assert etat.definition(nom) == definition and nom in etat.noms() and nom not in etat.NOMS
        assert "aucun contact externe" in definition.description and "en ombre" in definition.description


def test_chaque_routine_declaree_a_un_executeur_livre_et_une_decision_d_inventaire():
    executeurs = {e.nom: e for e in planificateur.executeurs_par_defaut()}
    for nom in ATTENDUES:
        for methode in ("ressources", "cle_bail", "constater", "traiter"):
            assert callable(getattr(executeurs[nom], methode)), (nom, methode)
    tours = [t for t in inventaire.TOURS if t.executeur in ATTENDUES]
    assert {t.executeur for t in tours} == set(ATTENDUES)
    assert all(t.decision == "brancher_maintenant" and t.niveau == "N2" for t in tours)
    # La consolidation d'affaires n'est plus « à construire » : l'énumérateur existe.
    assert inventaire.par_identifiant()["m10.consolider_affaire"].decision == "brancher_maintenant"
    assert not [t for t in inventaire.TOURS if t.decision == "a_construire"]


# -- la cadence : suivie, déclarée, jamais recopiée
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "cron, minute, heure, jours",
    [
        ("0 7 * * 1-5", 0, 7, {1, 2, 3, 4, 5}),
        ("30 4 * * 1", 30, 4, {1}),
        ("45 4 * * *", 45, 4, {1, 2, 3, 4, 5, 6, 7}),
        ("0 3 * * 0,6", 0, 3, {6, 7}),
        ("15 22 * * 7", 15, 22, {7}),
        ("5 8 * * 1,3-4", 5, 8, {1, 3, 4}),
    ],
)
def test_analyser_cron_lit_minute_heure_et_jours(cron, minute, heure, jours):
    planning = routines.analyser_cron(cron)
    assert (planning.minute, planning.heure, set(planning.jours)) == (minute, heure, jours)


@pytest.mark.parametrize(
    "cron",
    [
        "*/5 * * * *",
        "0 */2 * * *",
        "0 7 1 * *",
        "0 7 * 11 *",
        "60 7 * * *",
        "0 24 * * *",
        "0 7 * * 8",
        "0 7 * * 5-1",
        "0 7 * *",
        "0 7 * * MON",
        "a b * * *",
        "0 7 * * 1-5 x",
        "",
    ],
)
def test_une_cadence_qu_on_ne_sait_pas_lire_est_refusee_jamais_devinee(cron):
    with pytest.raises(ValueError):
        routines.analyser_cron(cron)


def test_la_cadence_suivie_est_celle_de_la_planification_du_manifeste_et_change_avec_elle():
    deps = charger_departements(RACINE / "departments")
    digest = next(d for d in routines.declarations(deps) if d.nom == "m1.routine.digest-reception")
    assert routines.planning_de(digest, deps) == routines.analyser_cron("0 7 * * 1-5")
    m1 = deps["m01-front-office"]
    decalee = tuple(
        dataclasses.replace(p, cron="15 8 * * 2") if p.nom == "digest-front-office" else p for p in m1.planifications
    )
    modifie = {**deps, m1.id: dataclasses.replace(m1, planifications=decalee)}
    planning = routines.planning_de(digest, modifie)
    assert (planning.heure, planning.minute, set(planning.jours)) == (8, 15, {2})  # rien n'est recopié dans le socle
    sans = {**deps, m1.id: dataclasses.replace(m1, planifications=())}
    with pytest.raises(planificateur.RefusExecuteur) as exc:
        routines.planning_de(digest, sans)
    assert exc.value.code == "REJ-PLAN-ROUTINE-CADENCE-ABSENTE"


def test_une_routine_a_intervalle_n_a_pas_d_heure():
    deps = charger_departements(RACINE / "departments")
    urgences = next(d for d in routines.declarations(deps) if d.nom == "m1.routine.urgences")
    assert routines.planning_de(urgences, deps) is None


def _ctx(instant: dt.datetime, deps=None) -> Contexte:
    t = instant.timestamp()
    return Contexte(Ports(horloge=lambda: t), None, "essai", deps, t)


def test_l_heure_declaree_est_atteinte_une_fois_par_jour_prevu_en_heure_locale():
    deps = charger_departements(RACINE / "departments")
    declaration = next(d for d in routines.declarations(deps) if d.nom == "m1.routine.digest-reception")
    executeur = routines.implementations()[declaration.cle](declaration)
    utc = dt.UTC
    # jeudi 12 novembre 2026 : 6 h 59 locale (11 h 59 UTC) non, 7 h 00 locale (12 h 00 UTC) oui
    assert executeur.echeance(_ctx(dt.datetime(2026, 11, 12, 11, 59, tzinfo=utc), deps)) == (False, "2026-11-12")
    assert executeur.echeance(_ctx(dt.datetime(2026, 11, 12, 12, 0, tzinfo=utc), deps)) == (True, "2026-11-12")
    assert executeur.echeance(_ctx(dt.datetime(2026, 11, 12, 23, 59, tzinfo=utc), deps)) == (True, "2026-11-12")
    # le jour LOCAL, pas le jour UTC : 23 h locale le jeudi = 04 h UTC le vendredi
    assert executeur.echeance(_ctx(dt.datetime(2026, 11, 13, 4, 0, tzinfo=utc), deps)) == (True, "2026-11-12")
    # samedi et dimanche : jamais dû
    assert not executeur.echeance(_ctx(dt.datetime(2026, 11, 14, 15, 0, tzinfo=utc), deps))[0]
    assert not executeur.echeance(_ctx(dt.datetime(2026, 11, 15, 15, 0, tzinfo=utc), deps))[0]


def test_le_changement_d_heure_ne_fait_ni_sauter_ni_doubler_le_creneau():
    planning = routines.analyser_cron("30 2 * * *")  # 2 h 30 n'existe pas le 14 mars 2027 (Toronto)
    from zoneinfo import ZoneInfo

    toronto = ZoneInfo("America/Toronto")
    atteints = [planning.atteint(dt.datetime(2027, 3, 14, h, m, tzinfo=toronto)) for h, m in ((1, 59), (3, 0), (12, 0))]
    assert atteints == [False, True, True]  # le premier sondage après le saut l'atteint ; un seul jour local
    automne = [planning.atteint(dt.datetime(2026, 11, 1, h, m, tzinfo=toronto)) for h, m in ((1, 59), (2, 30), (3, 0))]
    assert automne == [False, True, True]


# -- le manifeste : schéma fermé, fail-closed --------------------------------------------------------------------------
def _manifeste(tmp_path, routines_brutes, planifications=None) -> Path:
    dossier = tmp_path / "m01-front-office"
    dossier.mkdir()
    brut = yaml.safe_load((RACINE / "departments/m01-front-office/department.yaml").read_text(encoding="utf-8"))
    brut["routines_planifiees"] = routines_brutes
    if planifications is not None:
        brut["planifications"] = planifications
    (dossier / "department.yaml").write_text(yaml.safe_dump(brut, allow_unicode=True), encoding="utf-8")
    (dossier / "SOUL.md").write_text("fictif", encoding="utf-8")
    for skill in brut["skills"]:
        (dossier / "skills" / skill).mkdir(parents=True)
        (dossier / "skills" / skill / "SKILL.md").write_text("fictif", encoding="utf-8")
    return dossier


VALIDE = {"nom": "essai", "outils": [LIRE_M1], "cadence": {"intervalle_s": 600}}


def test_une_routine_valide_se_lit(tmp_path):
    (routine,) = lire_manifeste(_manifeste(tmp_path, [{**VALIDE, "description": "  Un  essai.  "}])).routines_planifiees
    assert routine == RoutinePlanifiee("essai", (LIRE_M1,), ("intervalle_s", 600), "Un essai.")


@pytest.mark.parametrize(
    "modification, fragment",
    [
        ({"inconnue": 1}, "clé(s) inconnue(s)"),
        ({"nom": "Mauvais Nom"}, "nom invalide"),
        ({"nom": "x" * 25}, "nom invalide"),
        ({"outils": []}, "1 à 4 outils"),
        ({"outils": ["m10_consolider_affaire"]}, "1 à 4 outils"),  # outil d'un autre département
        ({"outils": [LIRE_M1, LIRE_M1]}, "1 à 4 outils"),
        ({"outils": [LIRE_M1] * 5}, "1 à 4 outils"),
        ({"cadence": {}}, "un seul de"),
        ({"cadence": {"intervalle_s": 600, "cron": "0 7 * * *"}}, "un seul de"),
        ({"cadence": {"toutes_les": 5}}, "inconnue"),
        ({"cadence": {"intervalle_s": 5}}, "intervalle_s de 15 à 86400"),
        ({"cadence": {"intervalle_s": 86401}}, "intervalle_s de 15 à 86400"),
        ({"cadence": {"intervalle_s": True}}, "intervalle_s de 15 à 86400"),
        ({"cadence": {"intervalle_s": "600"}}, "intervalle_s de 15 à 86400"),
        ({"cadence": {"cron": "tous les jours"}}, "cron invalide"),
        ({"cadence": {"cron": ""}}, "texte requis"),
        ({"cadence": {"suit": 3}}, "texte requis"),
        ({"description": "x" * 401}, "description"),
    ],
)
def test_une_routine_mal_formee_est_refusee_a_la_lecture_du_manifeste(tmp_path, modification, fragment):
    with pytest.raises(ValueError, match=re.escape(fragment)):
        lire_manifeste(_manifeste(tmp_path, [{**VALIDE, **modification}]))


def test_deux_routines_du_meme_nom_et_un_bloc_non_liste_sont_refuses(tmp_path):
    with pytest.raises(ValueError, match="en double"):
        lire_manifeste(_manifeste(tmp_path, [VALIDE, VALIDE]))
    autre = tmp_path / "autre"
    autre.mkdir()
    with pytest.raises(ValueError, match="liste"):
        lire_manifeste(_manifeste(autre, {"nom": "x"}))


def test_un_manifeste_sans_routine_n_en_declare_aucune_et_remplacee_par_est_valide_avant_lecture(tmp_path):
    assert lire_manifeste(RACINE / "departments/m03-estimation").routines_planifiees == ()
    base = {"nom": "p", "cron": "0 7 * * 1-5", "consigne": "x"}
    dossier = _manifeste(tmp_path, [VALIDE], [{**base, "remplacee_par": "essai"}])
    assert lire_manifeste(dossier).planifications[0].remplacee_par == "essai"
    autre = tmp_path / "autre"
    autre.mkdir()
    with pytest.raises(ValueError, match="remplacee_par"):
        lire_manifeste(_manifeste(autre, [VALIDE], [{**base, "remplacee_par": "Pas Un Nom"}]))


# -- l'agent n'est plus déclenché : jamais deux déclencheurs
# ---------------------------------------------------------------
def test_une_planification_remplacee_n_est_plus_installee_comme_automatisation_d_agent():
    deps = charger_departements(RACINE / "departments")
    m1, m10 = deps["m01-front-office"], deps["m10-memoire"]
    assert {p.nom for p in m1.planifications if p.remplacee_par} == {"digest-front-office"}
    assert {p.nom for p in m10.planifications if p.remplacee_par} == {"consolidation-nocturne"}
    assert [j["id"] for j in profils.jobs_cron(m1)["jobs"]] == []
    assert sorted(j["id"] for j in profils.jobs_cron(m10)["jobs"]) == [
        "m10-memoire-digest-memoire",
        "m10-memoire-mnemo-quotidien",
    ]


def test_openclaw_n_installe_pas_l_automatisation_d_une_planification_remplacee():
    from opsys import openclaw

    source = (RACINE / "src/opsys/openclaw.py").read_text(encoding="utf-8")
    assert (
        "if plan.remplacee_par is not None:" in source
        and "continue" in source.split("remplacee_par is not None:")[1][:200]
    )
    assert hasattr(openclaw, "generer")


# -- le contrôle de cohérence
# --------------------------------------------------------------------------------------------
def test_le_controle_signale_chaque_defaut_de_declaration():
    deps = charger_departements(RACINE / "departments")
    m1 = deps["m01-front-office"]
    base = next(r for r in m1.routines_planifiees if r.nom == "urgences")

    def avec(**changements):
        faux = dataclasses.replace(base, **changements)
        autres = tuple(r for r in m1.routines_planifiees if r.nom != "urgences")
        return routines.problemes({**deps, m1.id: dataclasses.replace(m1, routines_planifiees=(*autres, faux))})

    assert any("absent du département" in x for x in avec(outils=("m1_outil_qui_n_existe_pas",)))
    assert any("niveau N" in x and "exigé" in x for x in avec(outils=("m1_confirmer_rendez_vous",)))
    assert any("agent seulement" in x for x in avec(outils=("m1_produire_digest",)))  # droit d'appareil
    assert any("cadence illisible" in x for x in avec(cadence=("cron", "*/5 * * * *")))
    assert any("cadence illisible" in x for x in avec(cadence=("suit", "planification-inconnue")))
    assert any("aucun exécuteur livré" in x for x in avec(nom="sans-executeur"))
    doublon = {**deps, m1.id: dataclasses.replace(m1, routines_planifiees=(base, base))}
    assert any("en double" in x for x in routines.problemes(doublon))


def test_une_planification_remplacee_doit_nommer_une_routine_qui_la_suit():
    deps = charger_departements(RACINE / "departments")
    m1 = deps["m01-front-office"]

    def avec(remplacee_par):
        plans = tuple(
            dataclasses.replace(p, remplacee_par=remplacee_par) if p.nom == "digest-front-office" else p
            for p in m1.planifications
        )
        return routines.problemes({**deps, m1.id: dataclasses.replace(m1, planifications=plans)})

    assert avec("digest-reception") == []
    assert any("n'existe pas ou ne la suit pas" in x for x in avec("urgences"))  # existe, mais ne la suit pas
    assert any("n'existe pas ou ne la suit pas" in x for x in avec("fantome"))


def test_le_verificateur_du_depot_refuse_une_routine_invalide_et_accepte_les_manifestes_livres(monkeypatch, capsys):
    import argparse

    from opsys import cli

    args = argparse.Namespace(config_dir=None, paliers=False)
    monkeypatch.setattr(routines, "problemes", lambda departements=None: ["routine d'essai invalide"])
    assert cli.cmd_verifier(args) == 1
    assert "routine d'essai invalide" in capsys.readouterr().err
    monkeypatch.undo()
    assert cli.cmd_verifier(args) == 0


def test_une_declaration_illisible_n_expose_aucune_routine_fail_closed(tmp_path):
    racine = tmp_path / "departments"
    dossier = racine / "m01-front-office"
    dossier.mkdir(parents=True)
    (dossier / "department.yaml").write_text("schema: faux\n", encoding="utf-8")
    assert routines.declarees(racine) == () and routines.definitions_declarees(racine) == ()
    assert routines.executeurs(racine) == []


# -- les garde-fous de l'exécuteur
# ------------------------------------------------------------------------------------------
def test_un_outil_hors_de_la_liste_fermee_de_la_declaration_n_est_jamais_appele():
    deps = charger_departements(RACINE / "departments")
    declaration = next(d for d in routines.declarations(deps) if d.nom == "m1.routine.digest-reception")
    restreinte = dataclasses.replace(declaration, routine=dataclasses.replace(declaration.routine, outils=(LIRE_M1,)))
    executeur = routines.implementations()[declaration.cle](restreinte)
    ctx = _ctx(dt.datetime(2026, 11, 12, 12, 0, tzinfo=dt.UTC), deps)
    with pytest.raises(NiveauInterdit) as exc:
        executeur._appeler(ctx, CONSIGNER_M1, {"groupe": "digest", "maintenant": "2026-11-12T12:00:00+00:00"})
    assert exc.value.code == "REJ-PLAN-OUTIL-HORS-LISTE"


def test_la_reponse_refusee_d_un_outil_devient_un_refus_type():
    with pytest.raises(planificateur.RefusExecuteur) as exc:
        routines.ExecuteurRoutine.resultat({"accepte": False, "verdict": {"code": "REJ-ROUTINE-JOUR-INVALIDE"}})
    assert exc.value.code == "REJ-ROUTINE-JOUR-INVALIDE"
    with pytest.raises(planificateur.RefusExecuteur) as exc:
        routines.ExecuteurRoutine.resultat({"accepte": False, "verdict": "texte sans code"})
    assert exc.value.code == "REJ-PLAN-ROUTINE-REFUSEE"
    with pytest.raises(planificateur.RefusExecuteur) as exc:
        routines.ExecuteurRoutine.resultat(["pas", "un", "dict"])
    assert exc.value.code == "REJ-PLAN-ROUTINE-REPONSE-ILLISIBLE"
    assert routines.ExecuteurRoutine.resultat({"accepte": True, "resultat": {"n": 1}}) == {"n": 1}


# -- le créneau « déjà fait » se lit au journal append-only ---------------------------------------------------------
def test_un_creneau_n_est_fait_que_par_une_ligne_en_succes_du_bon_mode_et_du_bon_executeur(tmp_path, monkeypatch):
    import planif_qa as pq

    from opsys import service_acteur_systeme as systeme
    from opsys import stockage
    from opsys.connecteurs_planification import journal

    plan = pq.monter(tmp_path, monkeypatch, ("m01-front-office",))
    try:
        deps = plan.departements
        declaration = next(d for d in routines.declarations(deps) if d.nom == "m1.routine.digest-reception")
        executeur = routines.implementations()[declaration.cle](declaration)
        ctx = _ctx(dt.datetime(2026, 11, 12, 12, 0, tzinfo=dt.UTC), deps)

        def consigner(evenement, mode, statut=None, ressource="2026-11-12", nom=executeur.nom):
            with stockage.transaction() as cnx:
                journal.journaliser(
                    cnx, nom, evenement, systeme.IDENTIFIANT, ressource=ressource, mode=mode, statut=statut
                )

        assert executeur.deja_fait("2026-11-12", ctx) is False
        consigner("ressource", "actif", "erreur")  # un échec n'est pas un créneau fait : il se reprend
        consigner("ressource", "ombre", "ok")  # une ligne d'ombre ne vaut pas un passage actif
        consigner("aurait", "ombre")  # un « aurait » non plus, en mode actif
        consigner("ressource", "actif", "ok", ressource="2026-11-11")  # un autre créneau
        consigner("ressource", "actif", "ok", nom="m1.routine.urgences")  # un autre exécuteur
        assert executeur.deja_fait("2026-11-12", ctx) is False
        consigner("ressource", "actif", "ok")
        assert executeur.deja_fait("2026-11-12", ctx) is True
        # En ombre, seul un « aurait » d'ombre compte (jamais un passage actif) : le 13, passage actif réussi
        # réussi mais aucun « aurait ».
        consigner("ressource", "actif", "ok", ressource="2026-11-13")
        ctx.mode = "ombre"
        assert executeur.deja_fait("2026-11-13", ctx) is False
        consigner("aurait", "ombre", ressource="2026-11-13")
        assert executeur.deja_fait("2026-11-13", ctx) is True
    finally:
        pq.demonter()


def test_l_ecriture_des_routines_n_est_permise_qu_a_l_acteur_du_planificateur_en_cours_de_tour():
    import threading

    from opsys import service_acteur_systeme as systeme

    assert systeme.planificateur_en_cours() is False
    with systeme.contexte_reconciliateur():  # l'autre acteur système (réconciliateur) ne vaut pas
        assert systeme.planificateur_en_cours() is False
    with systeme.contexte_planificateur():
        assert systeme.planificateur_en_cours() is True
        vu_par_un_autre_fil: list[bool] = []
        fil = threading.Thread(target=lambda: vu_par_un_autre_fil.append(systeme.planificateur_en_cours()))
        fil.start()
        fil.join()
        assert vu_par_un_autre_fil == [False]  # un autre fil n'hérite pas du tour
    assert systeme.planificateur_en_cours() is False  # le tour est fini
