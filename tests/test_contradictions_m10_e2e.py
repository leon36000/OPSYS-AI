"""Contradictions de la mémoire de M10, de bout en bout : les VRAIS outils de M10, le VRAI bus, la file
d'approbation réelle
et le VRAI planificateur durable à horloge INJECTÉE (aucun sleep). Données FICTIVES.

Scénario d'une semaine : deux faits d'AUTORITÉS différentes se contredisent dans les affaires (un ancien rapport contre
un journal) et dans le développement (la matrice vivante contre une ancienne documentation, ingérées d'un dépôt Git
fictif) ; une règle du propriétaire est contredite par un journal (CRITIQUE). La nuit, le planificateur range, marque et
propose ; en ombre il dit seulement ce qu'il « aurait » fait ; le critique ouvre UNE demande au sas ; une personne
l'approuve ; rien n'est supprimé et rejouer ne double rien.

Limite dite sans euphémisme : SQLite seulement, horloge injectée, aucun modèle, aucune donnée réelle.
"""

from __future__ import annotations

import json
import re
import subprocess

import planif_qa as pq
import planif_routines_monde as w
import pytest
from m10_memoire import contradictions_outils as co
from m10_memoire import ingestion_projet as ing
from m10_memoire import verite
from m10_memoire.outils import _REGISTRE_AFFAIRES
from sqlalchemy import select

from opsys import approbations, contexte, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.stockage.schema import EVENEMENTS_SORTANTS, PLANIFICATEUR_JOURNAL

FICTIF = True
LUNDI, MARDI = "2026-11-09", "2026-11-10"
ROUTINE = "m10.routine.contradictions-memoire"
MATRICE = json.dumps(
    {"requirements": [{"id": "M10.5", "current_status": "PARTIEL"}, {"id": "M10.6", "current_status": "ABSENT"}]}
)
ANCIEN_RAPPORT = (
    "# Ancien rapport fictif\n\n```m10-affirmations\n"
    '[{"sujet": "exigence:M10.5", "attribut": "statut", "valeur": "FAIT_PROUVE"},\n'
    ' {"sujet": "exigence:M10.6", "attribut": "statut", "valeur": "ABSENT"}]\n```\n'
)


@pytest.fixture
def plan(tmp_path, monkeypatch, declarer_services):
    plan = w.monter(tmp_path, monkeypatch, declarer_services)
    w.aller_a(plan, w.local(LUNDI, "20:00"))
    yield plan
    w.demonter()


def _git(depot, *args):
    subprocess.run(["git", "-C", str(depot), *args], check=True, capture_output=True)


@pytest.fixture
def depot(tmp_path):
    racine = tmp_path / "depot-fictif"
    (racine / "docs/reprise/MATRICES-20261031").mkdir(parents=True)
    (racine / "docs/architecture").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(racine)], check=True)
    _git(racine, "config", "user.email", "dev@example.test")
    _git(racine, "config", "user.name", "Dev Fixture")
    (racine / "docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M10.json").write_text(MATRICE, encoding="utf-8")
    (racine / "docs/architecture/RAPPORT-ANCIEN.md").write_text(ANCIEN_RAPPORT, encoding="utf-8")
    _git(racine, "add", "-A")
    _git(racine, "commit", "-qm", "dépôt fictif")
    return racine


def _agent(fonction, *args, **kwargs):
    with contexte.appeler_en_tant_que("m10-memoire"), stockage.transaction():
        return fonction(*args, **kwargs)


def _ligne_evenement():
    return w.evenements_m10()[0]["ligne_id"]


def _consigner(**surcharge):
    base = {
        "domaine": "affaires",
        "sujet": "devis:D-12",
        "attribut": "statut",
        "valeur": "FAIT_PROUVE",
        "classe": "memoire_ancienne",
        "source_ref": "registre:evenements:" + _ligne_evenement(),
    }
    base.update(surcharge)
    reponse = _agent(co.consigner_affirmation, **base)
    assert reponse["accepte"] is True, reponse
    return reponse


def _registre(nom):
    with stockage.transaction():
        return list(stockage.maillons("m10-memoire", nom))


def _file(domaine, etat="tous"):
    with stockage.transaction():
        return co.lire_contradictions(domaine, "contradictions", etat)["resultat"]


def _demandes(statut="en_attente"):
    with stockage.transaction() as cnx:
        return approbations.lister(cnx, statut)


def _approuver(plan, demande_id):
    capacites = Capacites(plan.departements, stockage.transaction, filtre={"m10-memoire"}, memoire=False)
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx,
            demande_id,
            True,
            pq.ADMIN,
            outils_executables(capacites.departements, stockage.transaction),
            capacites.departements,
        )


def _declarer_regle_du_proprietaire(plan):
    """L'agent propose, le propriétaire approuve : la seule voie d'une autorité haute dans les affaires."""
    capacites = Capacites(plan.departements, stockage.transaction, filtre={"m10-memoire"}, memoire=False)
    with stockage.transaction():
        ligne = _REGISTRE_AFFAIRES.ajouter(
            {
                "type_entree": "decision_enregistree",
                "horodatage": "2026-11-09T09:00:00-05:00",
                "decision_id": "dec-regle-envoi",
                "raison": "Aucun courriel sans approbation.",
                "statut": "validee",
                "options_ecartees": "aucune",
            }
        )
    reponse = capacites.appeler(
        "m10_declarer_affirmation_humaine",
        {
            "domaine": "affaires",
            "sujet": "regle:envoi_courriel",
            "attribut": "gate_humain",
            "valeur": "non",
            "classe": "decision_proprietaire",
            "source_ref": "registre:affaires:" + ligne,
            "motif": "Décision explicite du propriétaire, consignée au registre des décisions.",
        },
    )
    assert reponse["statut"] == "en_attente_approbation"
    resultat = _approuver(plan, reponse["demande_id"])
    assert resultat["statut"] == "executee", resultat


def _journal_planificateur():
    with stockage.transaction() as cnx:
        return [dict(r) for r in cnx.execute(select(PLANIFICATEUR_JOURNAL)).mappings()]


def _monde_de_la_semaine(plan, depot):
    w.semer_une_journee_d_affaires(plan)
    # Affaires : l'ancien rapport (mémoire ancienne) contre le journal : non critique, rangs différents.
    _consigner(classe="memoire_ancienne", valeur="FAIT_PROUVE")
    _consigner(classe="journal", valeur="PARTIEL")
    # Affaires : une règle du propriétaire contredite par un journal : critique.
    _declarer_regle_du_proprietaire(plan)
    _consigner(classe="journal", sujet="regle:envoi_courriel", attribut="gate_humain", valeur="oui")
    # Développement : la matrice vivante contre une ancienne documentation, ingérées d'un dépôt Git.
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(pq.ADMIN, "admin")):
        rapport = ing.ingerer(depot, horodatage="2026-11-09T21:00:00+00:00")
    assert rapport["affirmations"]["ajoutees"] == 4


def test_rien_ne_tourne_par_defaut(plan, depot):
    _monde_de_la_semaine(plan, depot)
    resume = w.tour(plan, w.local(MARDI, "04:20"))
    assert resume[ROUTINE]["statut"] == "inactif" and _registre("contradictions") == []


def test_la_nuit_en_ombre_dit_ce_qu_elle_aurait_fait_sans_rien_ecrire(plan, depot):
    _monde_de_la_semaine(plan, depot)
    w.activer(plan, (ROUTINE,), mode="ombre")
    resume = w.tour(plan, w.local(MARDI, "04:20"))
    assert resume[ROUTINE]["statut"] == "ombre"
    assert _registre("contradictions") == [] and _demandes() == []
    [aurait] = [x for x in w.journal() if x["executeur"] == ROUTINE and x["evenement"] == "aurait"]
    assert aurait["mode"] == "ombre" and aurait["details"] == {
        "aurait": 1,
        "contradictions": 3,
        "demandes": 1,
        "traites": 2,
    }
    w.tour(plan, w.local(MARDI, "04:35"))  # l'ombre ne répète pas son constat au sondage suivant
    assert len([x for x in w.journal() if x["executeur"] == ROUTINE and x["evenement"] == "aurait"]) == 1


def test_la_semaine_de_bout_en_bout(plan, depot):
    _monde_de_la_semaine(plan, depot)
    with stockage.transaction() as cnx:
        evenements_avant = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id)).all()
    w.activer(plan, (ROUTINE,))
    # Avant 4 h 10 : rien. Au sondage suivant l'heure déclarée : le passage.
    w.tour(plan, w.local(MARDI, "03:50"))
    assert w.tour(plan, w.local(MARDI, "04:00"))[ROUTINE]["statut"] == "pas_echu"
    assert _registre("contradictions") == []
    resume = w.tour(plan, w.local(MARDI, "04:20"))[ROUTINE]
    assert resume["statut"] == "ok" and (
        resume["contradictions"],
        resume["traites"],
        resume["demandes"],
        resume["differees"],
    ) == (3, 2, 1, 0)

    # -- affaires : l'ancien rapport contre le journal -> le journal est retenu, l'ancien rapport marqué, la trace reste
    affaires = _file("affaires")
    assert affaires["compte"]["resolue_auto"] == 1 and affaires["compte"]["en_attente_humain"] == 1
    [auto] = [x for x in _file("affaires", "resolue_auto")["contradictions"]]
    assert auto["a"]["classe"] == "journal" and auto["b"]["classe"] == "memoire_ancienne" and auto["critique"] is False
    assert (
        sorted(auto["marques"].values()) == ["dominee", "retenue"]
        and auto["marques"][auto["b"]["ligne_id"]] == "dominee"
    )
    with stockage.transaction():
        toutes = co.lire_contradictions("affaires", "affirmations")["resultat"]["affirmations"]
    assert {a["valeur"] for a in toutes if a["cle"] == "affaires|devis:D-12|statut"} == {
        "FAIT_PROUVE",
        "PARTIEL",
    }  # rien d'effacé

    # -- affaires : la règle du propriétaire contredite -> CRITIQUE : contestée des deux côtés, une demande au sas
    [critique] = [x for x in _file("affaires", "en_attente_humain")["contradictions"]]
    assert critique["critique"] is True and set(critique["marques"].values()) == {"contestee"}
    assert critique["a"]["classe"] == "decision_proprietaire" and critique["proposition"]["retenue"] == "a"
    [demande] = _demandes()
    assert (demande["departement"], demande["outil"], demande["niveau"]) == (
        "m10-memoire",
        "m10_decider_contradiction",
        "N3",
    )
    assert (
        demande["arguments"]["contradiction_id"] == critique["contradiction_id"]
        and demande["arguments"]["decision"] == "retenir_a"
    )
    assert critique["demande"]["statut"] == "en_attente"

    # -- développement : la matrice vivante l'emporte sur l'ancienne documentation (domaine séparé)
    developpement = _file("developpement")
    assert developpement["compte"]["resolue_auto"] == 1 and developpement["total"] == 1
    [matrice] = developpement["contradictions"]
    assert (matrice["cle"], matrice["a"]["classe"], matrice["b"]["classe"]) == (
        "developpement|exigence:M10.5|statut",
        "matrice_vivante",
        "documentation",
    )
    assert matrice["a"]["emetteur"].endswith("MATRICE-EXIGENCES-M10.json")
    assert all(x["domaine"] == "affaires" for x in affaires["contradictions"])  # jamais mêlés

    # -- rejouer ne double rien : les sondages suivants, un redémarrage, une deuxième instance
    avant = [m["ligne_id"] for m in _registre("contradictions")]
    for heure in ("04:35", "05:10", "11:00"):
        assert w.tour(plan, w.local(MARDI, heure))[ROUTINE].get("contradictions", 0) == 0
    w.rembobiner(plan, (ROUTINE,))
    assert w.tour(plan, w.local(MARDI, "11:30"))[ROUTINE].get("contradictions", 0) == 0
    assert [m["ligne_id"] for m in _registre("contradictions")] == avant and len(_demandes()) == 1

    # -- la personne approuve : la décision est appliquée, les marques changent, aucune affirmation n'est supprimée
    affirmations_avant = len(_registre("affirmations"))
    resultat = _approuver(plan, demande["id"])
    assert resultat["statut"] == "executee" and resultat["reponse"]["resultat"]["accepte"] is True
    [decidee] = _file("affaires", "decidee")["contradictions"]
    assert decidee["decision"]["par"] == pq.ADMIN and sorted(decidee["marques"].values()) == ["dominee", "retenue"]
    assert decidee["marques"][decidee["a"]["ligne_id"]] == "retenue"  # la décision du propriétaire
    assert len(_registre("affirmations")) == affirmations_avant
    assert _demandes() == [] and w.tour(plan, w.local("2026-11-11", "04:20"))[ROUTINE].get("contradictions", 0) == 0

    # -- les registres restent des chaînes intactes ; rien de personnel ni d'externe
    for nom in ("affirmations", "contradictions"):
        ok, raison = co.registre.Registre(maillons=stockage.maillons("m10-memoire", nom)).valider_chaine()
        assert ok, raison
    with stockage.transaction() as cnx:
        assert cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id)).all() == evenements_avant
    texte = json.dumps(_journal_planificateur(), ensure_ascii=False, default=str) + json.dumps(
        _registre("contradictions"), ensure_ascii=False
    )
    for personnel in (*w.PERSONNEL, "D-12", "M10.5", "regle:envoi_courriel"):
        assert personnel not in json.dumps(_journal_planificateur(), ensure_ascii=False, default=str), personnel
    assert (
        re.search(r"[A-Za-z0-9._-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}", texte) is None
    )  # aucun courriel (les « @empreinte » sont des références)


def test_un_agent_ne_peut_pas_forger_une_autorite_pour_gagner_une_contradiction(plan, depot):
    """Le journal tente de se déclarer « décision du propriétaire » : refusé, il reste un journal et perd contre la "
    "règle."""
    w.semer_une_journee_d_affaires(plan)
    for classe in ("decision_proprietaire", "constitution", "matrice_vivante"):
        refus = _agent(
            co.consigner_affirmation,
            "affaires",
            "regle:envoi_courriel",
            "gate_humain",
            "oui",
            classe,
            "registre:evenements:" + _ligne_evenement(),
        )
        assert refus["verdict"]["code"] == "REJ-AFFIRMATION-CLASSE-NON-ADMISE", classe
    assert _registre("affirmations") == []


def test_un_ordre_de_verite_inverse_donne_une_autre_proposition_et_s_inscrit_dans_la_contradiction(
    plan, depot, monkeypatch, tmp_path
):
    """L'ordre est une donnée : changer le fichier change la proposition ET l'empreinte de l'ordre consignée."""
    w.semer_une_journee_d_affaires(plan)
    _consigner(classe="memoire_ancienne", valeur="FAIT_PROUVE")
    _consigner(classe="journal", valeur="PARTIEL")
    livre = verite.CHEMIN_DEFAUT
    donnees = json.loads(livre.read_text(encoding="utf-8"))
    donnees["classes"] = list(reversed(donnees["classes"]))
    inverse = tmp_path / "ordre-inverse.json"
    inverse.write_text(json.dumps(donnees), encoding="utf-8")
    monkeypatch.setattr(verite, "CHEMIN_DEFAUT", inverse)
    w.activer(plan, (ROUTINE,))
    w.tour(plan, w.local(MARDI, "04:20"))
    [auto] = _file("affaires")["contradictions"]
    assert (
        auto["a"]["classe"] == "memoire_ancienne" and auto["proposition"]["retenue"] == "a"
    )  # l'ancien rapport l'emporte
    assert auto["ordre_version"] == verite.depuis_dict(donnees).version
    [detection] = [m for m in _registre("contradictions") if m["type_entree"] == "contradiction_detectee"]
    assert detection["ordre_empreinte"] == verite.depuis_dict(donnees).empreinte
    assert (
        detection["ordre_empreinte"] != verite.charger(livre).empreinte
    )  # on sait selon QUEL ordre la proposition a été faite
