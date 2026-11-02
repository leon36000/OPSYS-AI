"""Constats planifiés : la DÉCLARATION (manifeste), le calcul des arguments par créneau, la cadence dérivée du
catalogue, les définitions d'exécuteurs et leurs garde-fous. Pur ou base SQLite jetable ; aucune donnée réelle.

Le socle ne contient aucun horaire ni nom de département : tout ce que ce fichier vérifie vient des `department.yaml`
et du catalogue de M8.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
from pathlib import Path

import planif_qa as pq
import pytest
import yaml
from m8_analytics import cadence_constats

from opsys import departements as modele
from opsys import stockage
from opsys.connecteurs_planification import constats, etat, planificateur
from opsys.departements import ConstatPlanifie, charger_departements, lire_manifeste

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
ATTENDUS = {
    "m1.constat.plaintes": ("m1_constater_plaintes", ("m8_plaintes_periode",)),
    "m2.constat.pipeline": ("m2_constater_pipeline", ("m8_pipeline_leads_ouverts", "m8_taux_conversion_resolus_pct",
                                                      "m8_valeur_ponderee_pipeline_cad")),
    "m4.constat.capacite-equipe": ("m4_constater_capacite_equipe", ("m8_capacite_heures_disponibles",
                                                                    "m8_capacite_heures_planifiees",
                                                                    "m8_charge_planifiee_pct")),
    "m5.constat.cash-libre": ("m5_constater_cash_libre_planifie",
                              ("m8_cash_libre_cad", "m8_solde_tresorerie_cad", "m8_comptes_a_payer_cad",
                               "m8_taxes_a_remettre_cad")),
    "m5.constat.depense-publicitaire": ("m5_constater_depense_publicitaire",
                                        ("m8_depense_pub_comptabilisee_cad", "m8_ecart_depense_pub_comptabilisee_cad")),
    "m5.constat.factures-emises": ("m5_constater_factures_emises", ("m8_factures_emises", "m8_facturation_emise_cad")),
    "m6.constat.disponibilite": ("m6_constater_disponibilite", ("m8_articles_en_rupture", "m8_articles_sur_reserves",
                                                                "m8_reservations_incompletes")),
    "m7.constat.performance-signaux": ("m7_constater_performance_signaux", ("m8_clics_recherche",
                                                                            "m8_impressions_recherche",
                                                                            "m8_visites_site")),
}


# -- les manifestes livrés -------------------------------------------------------------------------------------------
def test_les_huit_constats_sont_declares_par_les_manifestes_des_departements():
    deps = charger_departements(RACINE / "departments")
    declares = {d.nom: d for d in constats.declarations(deps)}
    assert set(declares) == set(ATTENDUS)
    for nom, (outil, mesures) in ATTENDUS.items():
        assert declares[nom].constat.outil == outil and declares[nom].constat.mesures == mesures, nom
        assert outil.startswith(declares[nom].code.lower() + "_")
    assert constats.problemes(deps) == []


def test_chaque_outil_declare_est_agent_seulement_n2_sans_droit_d_appareil_et_sans_frontiere_humaine():
    deps = charger_departements(RACINE / "departments")
    for declaration in constats.declarations(deps):
        outil = next(o for o in deps[declaration.departement].charger_outils() if o.nom == declaration.constat.outil)
        assert outil.niveau_effectif.value == "N2" and outil.autonomie.value == "T1", outil.nom
        assert not outil.roles_appareil and not outil.frontiere_humaine, outil.nom


def test_aucun_horaire_ni_nom_de_departement_dans_le_socle_pour_les_constats():
    source = (RACINE / "src/opsys/connecteurs_planification/constats.py").read_text(encoding="utf-8")
    for interdit in ("m8_clics", "m5_constater", "m7_constater", "m4_constater", "m1_constater", "m2_constater",
                     "m6_constater", "43200", "604800", "cron", "m05-financecore", "m07-marketing"):
        assert interdit not in source, interdit


def test_les_definitions_sont_n2_famille_constats_et_inactives_par_defaut():
    definitions = {d.nom: d for d in constats.definitions_declarees()}
    assert set(definitions) == set(ATTENDUS)
    for nom, definition in definitions.items():
        assert definition.famille == "constats" and definition.niveau == "N2" and not definition.irreversible
        assert definition.transport is None and definition.plafond_appels_jour is None
        assert 15 <= definition.intervalle_defaut_s <= 86400 and len(nom) <= 40
        assert etat.definition(nom) is definition or etat.definition(nom) == definition
    assert set(ATTENDUS) <= set(etat.noms()) and not set(ATTENDUS) & set(etat.NOMS)


def test_la_cadence_par_defaut_est_celle_du_catalogue_pas_une_valeur_recopiee():
    for nom, (_, mesures) in ATTENDUS.items():
        derive = cadence_constats.cadence_par_defaut(mesures)["intervalle_s"]
        assert etat.definition(nom).intervalle_defaut_s == min(max(derive, 15), 86400), nom
    # la capacité hebdomadaire (cadence de source 7 j) est bornée au maximum que le planificateur permet : un jour
    assert cadence_constats.cadence_par_defaut(ATTENDUS["m4.constat.capacite-equipe"][1])["intervalle_s"] > 86400
    assert etat.definition("m4.constat.capacite-equipe").intervalle_defaut_s == 86400


def test_une_declaration_du_proprietaire_dans_m8_change_la_cadence_sans_toucher_au_code(tmp_path, monkeypatch):
    avant = etat.definition("m5.constat.factures-emises").intervalle_defaut_s
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {"fraicheur_mesures_s": {"m8_factures_emises": 7200}}}),
                         encoding="utf-8")
    monkeypatch.setattr(cadence_constats, "_MANIFESTE", manifeste)
    assert etat.definition("m5.constat.factures-emises").intervalle_defaut_s == 3600 != avant
    monkeypatch.undo()
    assert etat.definition("m5.constat.factures-emises").intervalle_defaut_s == avant


def test_une_modification_du_manifeste_de_m8_sur_place_est_vue_au_tour_suivant(tmp_path, monkeypatch):
    """Le propriétaire édite `department.yaml` de M8 SUR PLACE (même chemin) : la cadence suit, sans redémarrage."""
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {}}), encoding="utf-8")
    monkeypatch.setattr(cadence_constats, "_MANIFESTE", manifeste)
    avant = etat.definition("m5.constat.factures-emises").intervalle_defaut_s
    manifeste.write_text(yaml.safe_dump({"configuration": {"fraicheur_mesures_s": {"m8_factures_emises": 7200}}}),
                         encoding="utf-8")
    assert etat.definition("m5.constat.factures-emises").intervalle_defaut_s == 3600 != avant
    manifeste.write_text(yaml.safe_dump({"configuration": {}}), encoding="utf-8")
    assert etat.definition("m5.constat.factures-emises").intervalle_defaut_s == avant


# -- le manifeste : schéma fermé, fail-closed
# ---------------------------------------------------------------------------
def _manifeste(tmp_path, constats_bruts) -> Path:
    dossier = tmp_path / "m05-financecore"
    dossier.mkdir()
    brut = yaml.safe_load((RACINE / "departments/m05-financecore/department.yaml").read_text(encoding="utf-8"))
    brut["constats_planifies"] = constats_bruts
    (dossier / "department.yaml").write_text(yaml.safe_dump(brut, allow_unicode=True), encoding="utf-8")
    (dossier / "SOUL.md").write_text("fictif", encoding="utf-8")
    for skill in brut["skills"]:
        (dossier / "skills" / skill).mkdir(parents=True)
        (dossier / "skills" / skill / "SKILL.md").write_text("fictif", encoding="utf-8")
    return dossier


VALIDE = {"nom": "essai", "outil": "m5_constater_factures_emises", "mesures": ["m8_factures_emises"],
          "appels": [{"horodatage": {"calcul": "instant"}}]}


def test_un_constat_valide_se_lit_avec_ses_appels_tries(tmp_path):
    dossier = _manifeste(tmp_path, [{**VALIDE, "appels": [{"fin": {"calcul": "fin_mois-1"},
                                                          "debut": {"valeur": "texte"}, "n": {"valeur": 3}}]}])
    (constat,) = lire_manifeste(dossier).constats_planifies
    assert constat == ConstatPlanifie("essai", "m5_constater_factures_emises", ("m8_factures_emises",),
                                      ((("debut", "valeur", "texte"), ("fin", "calcul", "fin_mois-1"),
                                        ("n", "valeur", 3)),))


@pytest.mark.parametrize("modification, fragment", [
    ({"inconnue": 1}, "clé(s) inconnue(s)"),
    ({"nom": "Mauvais Nom"}, "nom invalide"),
    ({"nom": "x" * 25}, "nom invalide"),
    ({"outil": "m7_constater_performance_signaux"}, "doit commencer par m5_"),
    ({"mesures": []}, "mesures M8 requises"),
    ({"mesures": ["m8_factures_emises", "m8_factures_emises"]}, "mesures M8 requises"),
    ({"mesures": ["factures"]}, "mesures M8 requises"),
    ({"appels": []}, "appels"),
    ({"appels": [{}]}, "appels"),
    ({"appels": [{"horodatage": {"calcul": "maintenant()"}}]}, "hors grammaire"),
    ({"appels": [{"horodatage": {"calcul": "__import__('os')"}}]}, "hors grammaire"),
    ({"appels": [{"horodatage": {"calcul": "jour-9999"}}]}, "hors grammaire"),
    ({"appels": [{"horodatage": {"calcul": "jour-400"}}]}, "au-delà de 366"),
    ({"appels": [{"horodatage": "instant"}]}, "{calcul: …} ou {valeur: …}"),
    ({"appels": [{"horodatage": {"calcul": "instant", "valeur": "x"}}]}, "{calcul: …} ou {valeur: …}"),
    ({"appels": [{"horodatage": {"valeur": True}}]}, "texte court ou entier"),
    ({"appels": [{"horodatage": {"valeur": ["x"]}}]}, "texte court ou entier"),
    ({"appels": [{"Mauvais": {"valeur": "x"}}]}, "nom d'argument invalide"),
    ({"appels": [{"a": {"valeur": "x"}}] * 5}, "1 à 4 appels"),
    ({"description": "x" * 401}, "description"),
])
def test_un_constat_mal_forme_est_refuse_a_la_lecture_du_manifeste(tmp_path, modification, fragment):
    dossier = _manifeste(tmp_path, [{**VALIDE, **modification}])
    with pytest.raises(ValueError, match=fragment.replace("{", r"\{").replace("}", r"\}").replace("(", r"\(")
                                          .replace(")", r"\)").replace("…", ".")):
        lire_manifeste(dossier)


def test_deux_constats_du_meme_nom_et_un_bloc_non_liste_sont_refuses(tmp_path):
    with pytest.raises(ValueError, match="en double"):
        lire_manifeste(_manifeste(tmp_path, [VALIDE, VALIDE]))
    autre = tmp_path / "autre"
    autre.mkdir()
    with pytest.raises(ValueError, match="liste"):
        lire_manifeste(_manifeste(autre, {"nom": "x"}))


def test_un_manifeste_sans_constat_n_en_declare_aucun():
    assert lire_manifeste(RACINE / "departments/m03-estimation").constats_planifies == ()


# -- le calcul des arguments : un créneau, des dates
# --------------------------------------------------------------------
def _utc(*args):
    return dt.datetime(*args, tzinfo=dt.UTC)


@pytest.mark.parametrize("expression, creneau, attendu", [
    ("instant", _utc(2026, 11, 12, 5, 0), "2026-11-12T05:00:00+00:00"),
    ("jour", _utc(2026, 11, 12, 5, 0), "2026-11-12"),
    ("jour", _utc(2026, 11, 12, 3, 0), "2026-11-11"),  # 22 h la veille à Toronto
    ("jour-1", _utc(2026, 3, 1, 12, 0), "2026-02-28"),
    ("jour+30", _utc(2026, 12, 15, 12, 0), "2027-01-14"),
    ("debut_mois", _utc(2026, 11, 12, 12, 0), "2026-11-01"),
    ("fin_mois", _utc(2026, 11, 12, 12, 0), "2026-11-30"),
    ("debut_mois-1", _utc(2026, 1, 15, 12, 0), "2025-12-01"),
    ("fin_mois-1", _utc(2026, 3, 15, 12, 0), "2026-02-28"),
    ("fin_mois-1", _utc(2028, 3, 15, 12, 0), "2028-02-29"),  # bissextile
    ("fin_mois+1", _utc(2026, 12, 15, 12, 0), "2027-01-31"),
    ("debut_mois+13", _utc(2026, 12, 15, 12, 0), "2028-01-01"),
    ("lundi", _utc(2026, 11, 12, 12, 0), "2026-11-09"),  # jeudi
    ("lundi", _utc(2026, 11, 9, 12, 0), "2026-11-09"),  # déjà lundi
    ("lundi", _utc(2026, 11, 15, 12, 0), "2026-11-09"),  # dimanche
    ("lundi-1", _utc(2026, 11, 12, 12, 0), "2026-11-02"),
    ("lundi+1", _utc(2026, 11, 12, 12, 0), "2026-11-16"),
])
def test_evaluer_calcul(expression, creneau, attendu):
    assert constats.evaluer_calcul(expression, creneau, "America/Toronto") == attendu


def test_un_calcul_hors_grammaire_leve_un_refus_typé_jamais_evalue():
    for expression in ("maintenant", "jour*2", "jour-", "__import__", "instant;ls", "JOUR", ""):
        with pytest.raises(planificateur.RefusExecuteur) as exc:
            constats.evaluer_calcul(expression, _utc(2026, 11, 12, 12, 0), "America/Toronto")
        assert exc.value.code == "REJ-PLAN-CALCUL-INVALIDE"


def test_la_grammaire_du_manifeste_et_celle_de_l_evaluateur_sont_les_memes():
    for expression in ("instant", "jour", "jour-30", "debut_mois", "fin_mois+1", "lundi-2"):
        assert modele.CALCUL_CONSTAT.match(expression) and constats._CALCUL.match(expression)
    for expression in ("instant-1x", "jour--1", "Jour", "debut", "jour 1"):
        assert not modele.CALCUL_CONSTAT.match(expression) and not constats._CALCUL.match(expression)


def test_le_creneau_est_un_multiple_de_l_intervalle_depuis_minuit_local():
    toronto = "America/Toronto"
    # 10 h 07 locale (EST) le 12 novembre : le créneau de 12 h commence à minuit local (05:00 UTC)
    t = _utc(2026, 11, 12, 15, 7).timestamp()
    assert constats.creneau(t, 43200, toronto) == _utc(2026, 11, 12, 5, 0)
    # 13 h locale : le créneau de l'après-midi commence à midi local (17:00 UTC)
    assert constats.creneau(_utc(2026, 11, 12, 18, 0).timestamp(), 43200, toronto) == _utc(2026, 11, 12, 17, 0)
    # tout instant du même créneau donne le même début
    debut = constats.creneau(_utc(2026, 11, 12, 5, 0).timestamp(), 43200, toronto)
    assert debut == constats.creneau(_utc(2026, 11, 12, 16, 59, 59).timestamp(), 43200, toronto)
    assert debut != constats.creneau(_utc(2026, 11, 12, 17, 0).timestamp(), 43200, toronto)
    # un intervalle d'un jour : le jour local
    assert constats.creneau(_utc(2026, 11, 12, 15, 7).timestamp(), 86400, toronto) == _utc(2026, 11, 12, 5, 0)
    # la date locale du créneau est celle de l'instant (jamais la veille)
    for heure in range(0, 24, 3):
        instant = _utc(2026, 11, 12, heure, 30)
        local = instant.astimezone(dt.timezone(dt.timedelta(hours=-5))).date()
        assert constats.creneau(instant.timestamp(), 43200, toronto).astimezone(
            dt.timezone(dt.timedelta(hours=-5))).date() == local


def test_le_creneau_traverse_le_changement_d_heure_sans_dedoubler_ni_perdre_un_creneau():
    toronto = "America/Toronto"
    # retour à l'heure normale le 1er novembre 2026 (2 h -> 1 h) : le jour local fait 25 h, les créneaux de 12 h suivent
    debuts = {constats.creneau((_utc(2026, 11, 1, 4, 0) + dt.timedelta(minutes=30 * k)).timestamp(), 43200, toronto)
              for k in range(52)}
    debuts = {d.isoformat() for d in debuts}
    assert len(debuts) <= 3 and all(d.endswith("+00:00") for d in debuts)
    # deux instants du même créneau, de part et d'autre du changement, donnent le même début
    avant = constats.creneau(_utc(2026, 11, 1, 5, 30).timestamp(), 43200, toronto)  # 01:30 EDT (avant)
    apres = constats.creneau(_utc(2026, 11, 1, 6, 30).timestamp(), 43200, toronto)  # 01:30 EST (après)
    assert avant == apres


# -- l'exécuteur : seulement ce que le manifeste déclare
# ------------------------------------------------------------------
@pytest.fixture
def p(tmp_path, monkeypatch):
    mon = pq.monter(tmp_path, monkeypatch, ("m05-financecore", "m06-material-control", "m08-analytics"))
    yield mon
    pq.demonter()


def test_l_admin_peut_regler_et_activer_un_constat_comme_les_autres_tours(p):
    resultat = p.activer("m6.constat.disponibilite", "ombre", intervalle_s=3600)
    assert resultat["mode"] == "ombre"
    with stockage.transaction() as cnx:
        ligne = etat.ligne(cnx, "m6.constat.disponibilite")
        assert ligne["intervalle_s"] == 3600
    with pytest.raises(etat.RefusOperateur) as refus:
        p.activer("m6.constat.inexistant", "ombre")
    assert refus.value.code == "EXECUTEUR_INCONNU"
    with pytest.raises(etat.RefusOperateur) as refus:
        p.activer("m6.constat.disponibilite", "ombre", intervalle_s=5)
    assert refus.value.code == "INTERVALLE_INVALIDE"


def test_un_departement_absent_est_dit_pas_ignore(p):
    p.departements.pop("m06-material-control")
    p.activer("m6.constat.disponibilite")
    resume = p.tour()
    assert resume["executeurs"]["m6.constat.disponibilite"]["statut"] == "refus"
    assert resume["executeurs"]["m6.constat.disponibilite"]["code"] == "REJ-PLAN-DEPARTEMENT-ABSENT"


def test_un_constat_qui_echoue_ne_bloque_pas_les_autres_et_dit_son_code(p, monkeypatch):
    from m5_financecore import outils_operations

    p.activer("m6.constat.disponibilite")
    p.activer("m5.constat.factures-emises")

    def casse(horodatage):
        raise RuntimeError("panne")

    monkeypatch.setattr(outils_operations, "constater_factures_emises", casse)
    resume = p.tour()["executeurs"]
    assert resume["m5.constat.factures-emises"]["statut"] == "erreur"
    assert resume["m5.constat.factures-emises"]["code"] == "REJ-PLAN-DEFAUT-EXECUTEUR"
    assert resume["m6.constat.disponibilite"]["statut"] == "ok"


def test_une_declaration_illisible_n_expose_aucun_constat_fail_closed(tmp_path, monkeypatch):
    racine = tmp_path / "departments"
    racine.mkdir()
    dossier = racine / "m05-financecore"
    dossier.mkdir()
    (dossier / "department.yaml").write_text("schema: faux\n", encoding="utf-8")
    assert constats.declarees(racine) == ()
    assert constats.definitions_declarees(racine) == ()
    assert constats.executeurs(racine) == []


def test_le_controle_de_coherence_signale_chaque_defaut_de_declaration():
    deps = charger_departements(RACINE / "departments")
    m5 = deps["m05-financecore"]
    base = m5.constats_planifies[0]

    def avec(**changements):
        faux = dataclasses.replace(base, **changements)
        return constats.problemes({**deps, m5.id: dataclasses.replace(m5, constats_planifies=(faux,))})

    assert any("absent du département" in x for x in avec(outil="m5_outil_qui_n_existe_pas"))
    assert any("niveau N4" in x or "niveau N3" in x for x in avec(outil="m5_clore_periode_comptable"))
    assert any("inconnu de" in x for x in avec(appels=((("argument_inventé", "valeur", "x"),),)))
    assert any("requis non fournis" in x for x in avec(appels=((("aujourd_hui", "calcul", "jour"),),)))
    assert any("cadence non dérivable" in x for x in avec(mesures=("m8_mesure_qui_n_existe_pas",)))
    copie = copy.copy(base)
    doublon = {**deps, m5.id: dataclasses.replace(m5, constats_planifies=(copie, copie))}
    assert any("en double" in x for x in constats.problemes(doublon))


def test_le_verificateur_du_depot_refuse_un_constat_invalide_et_accepte_les_manifestes_livres(monkeypatch, capsys):
    import argparse

    from opsys import cli

    args = argparse.Namespace(config_dir=None, paliers=False)
    monkeypatch.setattr(constats, "problemes", lambda departements=None: ["constat d'essai invalide"])
    assert cli.cmd_verifier(args) == 1
    assert "constat d'essai invalide" in capsys.readouterr().err
    monkeypatch.undo()
    assert cli.cmd_verifier(args) == 0
