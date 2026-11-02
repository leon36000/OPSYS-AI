"""Les cinq outils de contradictions de M10 sur une base SQLite migrée : niveaux, canaux, isolation des domaines,
écriture
réservée au planificateur, sas d'approbation (N3), plafonds, idempotence. Passe par les VRAIS outils (`Capacites`, mode
`ombre` du manifeste) et la file d'approbation réelle. Données FICTIVES."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m10_memoire import contradictions as c
from m10_memoire import contradictions_outils as co
from m10_memoire import outils as outils_m10
from m10_memoire import verite

from opsys import approbations, contexte, identite, stockage
from opsys import service_acteur_systeme as systeme
from opsys.capacites import Capacites, outils_executables
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau

FICTIF = True
RACINE = Path(__file__).resolve().parents[2]
H = "2026-11-02T04:10:00-05:00"
MOTIF = "Source plus à jour, vérifiée avec la matrice."


@pytest.fixture
def instance(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def capacites(instance):
    return Capacites(charger_departements(RACINE), stockage.transaction, filtre={"m10-memoire"}, memoire=False)


def _ligne(nom="decision-fictive"):
    """Une ligne réelle du registre Affaires : la source qu'une affirmation cite."""
    with stockage.transaction():
        return outils_m10._REGISTRE_AFFAIRES.ajouter(
            {
                "type_entree": "decision_enregistree",
                "horodatage": H,
                "decision_id": nom,
                "raison": "Raison fictive.",
                "statut": "validee",
                "options_ecartees": "aucune",
            }
        )


def _args(**surcharge):
    base = {
        "domaine": "affaires",
        "sujet": "devis:D-12",
        "attribut": "statut",
        "valeur": "accepte",
        "classe": "journal",
        "source_ref": "registre:affaires:" + _ligne(),
    }
    base.update(surcharge)
    return base


def _consigner(capacites, **surcharge):
    return capacites.appeler("m10_consigner_affirmation", _args(**surcharge))


def _humaine(sujet, valeur, attribut="gate_humain", classe="decision_proprietaire"):
    """Écrit au registre, comme `m10_declarer_affirmation_humaine` approuvée, l'affirmation d'une personne."""
    ordre = verite.charger()
    ligne = _ligne(f"ref-{sujet}")
    valide = c.valider(
        {
            "domaine": "affaires",
            "sujet": sujet,
            "attribut": attribut,
            "valeur": valeur,
            "classe": classe,
            "ref": "registre:affaires:" + ligne,
            "emetteur": "humain:nathan",
        },
        ordre,
        "humain",
    )
    with stockage.transaction():
        prepare = c.preparer(c.affirmations(co._REGISTRE_AFFIRMATIONS.lire()), valide, H, ordre)
        co._REGISTRE_AFFIRMATIONS.ajouter(
            {**prepare["entree"], "par": "nathan", "role": "nathan_owner", "source_decision": "approbation"}
        )


def _rafraichir(ecrire=True, horodatage=H):
    with systeme.contexte_planificateur(), stockage.transaction():
        return co.rafraichir_contradictions(horodatage, ecrire)


def _registre(nom):
    with stockage.transaction():
        return list(stockage.maillons("m10-memoire", nom))


def _appel_agent(fonction, *args, **kwargs):
    with contexte.appeler_en_tant_que("m10-memoire"), stockage.transaction():
        return fonction(*args, **kwargs)


def _approuver(capacites, demande_id, par="nathan"):
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx,
            demande_id,
            True,
            par,
            outils_executables(capacites.departements, stockage.transaction),
            capacites.departements,
        )


# -- 1. déclarations ----------------------------------------------------------------------------------------------
def test_les_cinq_outils_ont_les_niveaux_voulus_aucun_droit_d_appareil(capacites):
    par_nom = {o.nom: o for o in capacites.lister()}
    attendus = {
        "m10_consigner_affirmation": (Autonomie.T1, Niveau.N2),
        "m10_declarer_affirmation_humaine": (Autonomie.T1, Niveau.N3),
        "m10_lire_contradictions": (Autonomie.T0, Niveau.N0),
        "m10_rafraichir_contradictions": (Autonomie.T1, Niveau.N2),
        "m10_decider_contradiction": (Autonomie.T1, Niveau.N3),
    }
    for nom, (autonomie, niveau) in attendus.items():
        outil = par_nom[nom]
        assert (outil.autonomie, outil.niveau_effectif) == (autonomie, niveau), nom
        assert outil.roles_appareil == frozenset() and not outil.frontiere_humaine, nom
        assert outil.parametres["additionalProperties"] is False, nom


def test_le_manifeste_declare_la_routine_et_les_registres(capacites):
    manifeste = capacites.departements["m10-memoire"]
    routine = next(r for r in manifeste.routines_planifiees if r.nom == "contradictions-memoire")
    assert routine.outils == ("m10_rafraichir_contradictions",) and routine.cadence == ("cron", "10 4 * * *")


# -- 2. consigner (canal agent) -----------------------------------------------------------------------------------
def test_un_agent_consigne_un_fait_sourcee_la_double_soumission_ne_change_rien(capacites):
    premiere = _consigner(capacites)
    assert premiere["ok"] is True and premiere["resultat"]["resultat"]["resultat"] == "ajoutee"
    ligne = premiere["resultat"]["resultat"]["ligne_id"]
    arguments = _args(source_ref=_registre("affirmations")[0]["ref"])
    seconde = capacites.appeler("m10_consigner_affirmation", arguments)
    assert seconde["resultat"]["resultat"] == {"resultat": "inchangee", "ligne_id": ligne}
    assert len(_registre("affirmations")) == 1
    [entree] = _registre("affirmations")
    assert entree["emetteur"] == "agent:m10-memoire" and entree["canal"] == "agent" and entree["classe"] == "journal"


def test_un_agent_ne_peut_pas_se_donner_une_autorite_haute_ni_ecrire_au_developpement(capacites):
    for surcharge, code in (
        ({"classe": "constitution"}, "REJ-AFFIRMATION-CLASSE-NON-ADMISE"),
        ({"classe": "decision_proprietaire"}, "REJ-AFFIRMATION-CLASSE-NON-ADMISE"),
        ({"classe": "matrice_vivante"}, "REJ-AFFIRMATION-CLASSE-NON-ADMISE"),
        ({"domaine": "developpement", "sujet": "exigence:M10.4"}, "REJ-AFFIRMATION-CLASSE-NON-ADMISE"),
        (
            {"domaine": "developpement", "sujet": "exigence:M10.4", "classe": "documentation"},
            "REJ-AFFIRMATION-CLASSE-NON-ADMISE",
        ),
    ):
        reponse = _consigner(capacites, **surcharge)
        assert reponse["resultat"]["accepte"] is False and reponse["resultat"]["verdict"]["code"] == code, surcharge
    assert _registre("affirmations") == []


def test_une_affirmation_sans_source_reelle_ou_avec_une_valeur_personnelle_est_refusee(capacites):
    inconnue = _consigner(capacites, source_ref="registre:affaires:" + "f" * 64)
    assert inconnue["resultat"]["verdict"]["code"] == "REJ-AFFIRMATION-REFERENCE-INTROUVABLE"
    for valeur in ("jean.tremblay@example.test", "514-555-0123", "le client veut annuler"):
        reponse = _consigner(capacites, valeur=valeur)
        assert reponse["resultat"]["accepte"] is False, valeur
        assert valeur not in json.dumps(reponse, ensure_ascii=False)  # le refus ne cite pas la valeur
    assert _registre("affirmations") == []


def test_un_secret_qui_a_la_forme_d_un_jeton_n_entre_pas_au_registre(capacites):
    secret = "sk-" + "a1b2c3d4" * 4  # valeur FACTICE construite à l'exécution
    for surcharge in (
        {"valeur": secret},
        {"sujet": f"devis:{secret}"},
        {"attribut": "jeton"} | {"valeur": f"Bearer{secret}"},
    ):
        reponse = _consigner(capacites, **surcharge)
        assert reponse["resultat"]["accepte"] is False and reponse["resultat"]["verdict"]["code"] in (
            "REJ-AFFIRMATION-SECRET",
            "REJ-AFFIRMATION-VALEUR-INVALIDE",
        ), surcharge
        assert secret not in json.dumps(reponse, ensure_ascii=False)
    assert _registre("affirmations") == []


def test_un_identifiant_d_affaire_hexadecimal_long_n_est_pas_pris_pour_un_secret(capacites):
    reponse = _consigner(capacites, sujet="affaire:" + "0123456789abcdef" * 2)
    assert reponse["resultat"]["accepte"] is True


def test_un_appel_d_appareil_est_refuse_par_chaque_outil(instance):
    employe = contexte.IdentiteAppelante("employe-fictif", "employee")
    with contexte.appele_par_appareil(employe), contexte.appeler_en_tant_que("m10-memoire"), stockage.transaction():
        for refus in (
            co.consigner_affirmation(**_args(source_ref="registre:affaires:" + "a" * 64)),
            co.lire_contradictions("affaires"),
            co.rafraichir_contradictions(H, False),
        ):
            assert refus["verdict"]["code"] == "REJ-MNEMO-APPAREIL-FERME"
    assert _registre("affirmations") == [] and _registre("contradictions") == []


# -- 3. la voie humaine (N3) ----------------------------------------------------------------------------------------
def test_la_declaration_d_une_autorite_haute_est_une_proposition_qu_une_personne_approuve(capacites):
    arguments = {
        **_args(classe="decision_proprietaire", sujet="regle:envoi", attribut="gate_humain", valeur="non"),
        "motif": MOTIF,
    }
    reponse = capacites.appeler("m10_declarer_affirmation_humaine", arguments)
    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    assert _registre("affirmations") == []  # rien n'est écrit tant que personne n'a approuvé
    resultat = _approuver(capacites, reponse["demande_id"])
    assert resultat["statut"] == "executee" and resultat["reponse"]["resultat"]["accepte"] is True
    [entree] = _registre("affirmations")
    assert (
        entree["classe"],
        entree["emetteur"],
        entree["canal"],
        entree["par"],
        entree["role"],
        entree["source_decision"],
    ) == ("decision_proprietaire", "humain:nathan", "humain", "nathan", "nathan_owner", "approbation")


def test_la_declaration_humaine_exige_un_motif(capacites):
    arguments = _args(classe="decision_proprietaire", sujet="regle:envoi", attribut="gate_humain", valeur="non")
    reponse = capacites.appeler("m10_declarer_affirmation_humaine", {**arguments, "motif": "court"})
    resultat = _approuver(capacites, reponse["demande_id"])
    assert resultat["reponse"]["resultat"]["verdict"]["code"] == "REJ-HUMAIN-MOTIF-INVALIDE"
    assert _registre("affirmations") == []


def test_un_appel_direct_d_agent_sans_approbation_ne_peut_pas_declarer(instance):
    refus = _appel_agent(co.declarer_affirmation_humaine, **_args(classe="decision_proprietaire"), motif=MOTIF)
    assert refus["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    refus = _appel_agent(co.decider_contradiction, "x", "retenir_a", MOTIF)
    assert refus["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _registre("affirmations") == [] and _registre("contradictions") == []


def test_la_voie_humaine_n_ouvre_pas_la_constitution_dans_les_affaires(capacites):
    reponse = capacites.appeler(
        "m10_declarer_affirmation_humaine", {**_args(classe="constitution", sujet="regle:envoi"), "motif": MOTIF}
    )
    resultat = _approuver(capacites, reponse["demande_id"])
    assert resultat["reponse"]["resultat"]["verdict"]["code"] == "REJ-AFFIRMATION-CLASSE-NON-ADMISE"
    assert _registre("affirmations") == []


# -- 4. le rafraîchissement ---------------------------------------------------------------------------------------
def _deux_sources_non_critiques(capacites):
    _consigner(capacites, classe="memoire_ancienne", valeur="FAIT_PROUVE", sujet="devis:D-12", attribut="statut")
    # Un deuxième émetteur : la même source qui se réexprime remplacerait la première (supersede), sans contradiction.
    ordre = verite.charger()
    ligne = _ligne("autre-source")
    valide = c.valider(
        {
            "domaine": "affaires",
            "sujet": "devis:D-12",
            "attribut": "statut",
            "valeur": "PARTIEL",
            "classe": "journal",
            "ref": "registre:affaires:" + ligne,
            "emetteur": "agent:m01-front-office",
        },
        ordre,
        "agent",
    )
    with stockage.transaction():
        prepare = c.preparer(c.affirmations(co._REGISTRE_AFFIRMATIONS.lire()), valide, H, ordre)
        co._REGISTRE_AFFIRMATIONS.ajouter(prepare["entree"])


def test_le_calcul_a_blanc_dit_ce_qui_serait_fait_sans_rien_ecrire(capacites):
    _deux_sources_non_critiques(capacites)
    blanc = _rafraichir(ecrire=False)["resultat"]
    assert (
        blanc["ecrit"] is False
        and blanc["nouvelles"] == 1
        and blanc["auto_resolues"] == 1
        and blanc["demandes_a_ouvrir"] == 0
    )
    assert _registre("contradictions") == []


def test_l_ecriture_est_reservee_au_planificateur_l_instant_ne_vient_pas_d_un_agent(capacites):
    _deux_sources_non_critiques(capacites)
    refus = _appel_agent(co.rafraichir_contradictions, "2099-12-31T04:10:00-05:00", True)
    assert refus["verdict"]["code"] == "REJ-ROUTINE-PLANIFICATEUR-REQUIS"
    assert _appel_agent(co.rafraichir_contradictions, "2099-12-31T04:10:00-05:00", False)["accepte"] is True
    with systeme.contexte_planificateur():
        pass  # un tour fini : l'acteur système fermé ne vaut plus rien
    assert _appel_agent(co.rafraichir_contradictions, H)["verdict"]["code"] == "REJ-ROUTINE-PLANIFICATEUR-REQUIS"
    assert _registre("contradictions") == []


@pytest.mark.parametrize(
    "horodatage, ecrire", [("hier", True), ("2026-11-02T04:10:00", True), (H, "oui"), (None, True)]
)
def test_les_arguments_invalides_du_rafraichissement_sont_refuses(instance, horodatage, ecrire):
    with systeme.contexte_planificateur(), stockage.transaction():
        refus = co.rafraichir_contradictions(horodatage, ecrire)
    assert refus["accepte"] is False
    assert _registre("contradictions") == []


def test_une_contradiction_non_critique_est_resolue_marquee_et_la_trace_reste(capacites):
    _deux_sources_non_critiques(capacites)
    bilan = _rafraichir()["resultat"]
    assert (bilan["ecrit"], bilan["nouvelles"], bilan["auto_resolues"], bilan["demandes_ouvertes"]) == (True, 1, 1, 0)
    types = [m["type_entree"] for m in _registre("contradictions")]
    assert types == ["contradiction_detectee", "contradiction_marque", "contradiction_marque"]
    with stockage.transaction():
        vue = co.lire_contradictions("affaires", "contradictions", "tous")["resultat"]
        affirmations = co.lire_contradictions("affaires", "affirmations")["resultat"]
    [contradiction] = vue["contradictions"]
    assert contradiction["statut"] == "resolue_auto" and contradiction["proposition"]["retenue"] == "a"
    assert sorted(contradiction["marques"].values()) == ["dominee", "retenue"]
    assert {a["marque"] for a in affirmations["affirmations"]} == {"dominee", "retenue"}
    assert {a["valeur"] for a in affirmations["affirmations"]} == {"FAIT_PROUVE", "PARTIEL"}  # les deux restent
    assert vue["ordre"]["version"] == verite.charger().version
    # idempotent : un deuxième passage n'ajoute rien
    avant = len(_registre("contradictions"))
    assert _rafraichir()["resultat"]["nouvelles"] == 0 and len(_registre("contradictions")) == avant


def test_une_contradiction_critique_ouvre_une_demande_au_sas_avec_la_proposition_de_l_ordre(capacites):
    _humaine("regle:envoi_courriel", "non")
    _consigner(capacites, classe="journal", valeur="oui", sujet="regle:envoi_courriel", attribut="gate_humain")
    bilan = _rafraichir()["resultat"]
    assert (bilan["critiques"], bilan["auto_resolues"], bilan["demandes_ouvertes"]) == (1, 0, 1)
    with stockage.transaction() as cnx:
        [demande] = approbations.lister(cnx, "en_attente")
    assert (demande["departement"], demande["outil"], demande["niveau"]) == (
        "m10-memoire",
        "m10_decider_contradiction",
        "N3",
    )
    arguments = demande["arguments"]
    assert set(arguments) == {"contradiction_id", "decision", "motif"} and arguments["decision"] == "retenir_a"
    with stockage.transaction():
        [contradiction] = co.lire_contradictions("affaires")["resultat"]["contradictions"]
    assert contradiction["statut"] == "en_attente_humain" and contradiction["critique"] is True
    assert set(contradiction["marques"].values()) == {"contestee"}  # rien n'est tranché sans personne
    assert contradiction["demande"] == {"id": contradiction["demande_id"], "statut": "en_attente"}
    # la proposition est la décision du propriétaire, pas le journal
    assert contradiction["a"]["classe"] == "decision_proprietaire" and contradiction["proposition"]["retenue"] == "a"
    # un deuxième passage n'ouvre pas une deuxième demande
    assert _rafraichir()["resultat"]["demandes_ouvertes"] == 0
    with stockage.transaction() as cnx:
        assert len(approbations.lister(cnx, "en_attente")) == 1


def test_l_approbation_applique_la_decision_les_marques_changent_et_rien_n_est_supprime(capacites):
    _humaine("regle:envoi_courriel", "non")
    _consigner(capacites, classe="journal", valeur="oui", sujet="regle:envoi_courriel", attribut="gate_humain")
    _rafraichir()
    with stockage.transaction() as cnx:
        [demande] = approbations.lister(cnx, "en_attente")
    avant = len(_registre("affirmations"))
    resultat = _approuver(capacites, demande["id"])
    assert resultat["statut"] == "executee" and resultat["reponse"]["resultat"]["accepte"] is True
    with stockage.transaction():
        [contradiction] = co.lire_contradictions("affaires", "contradictions", "decidee")["resultat"]["contradictions"]
    assert contradiction["decision"]["par"] == "nathan" and contradiction["decision"]["role"] == "nathan_owner"
    assert sorted(contradiction["marques"].values()) == ["dominee", "retenue"]
    assert len(_registre("affirmations")) == avant
    # une décision est définitive
    reponse = _appel_agent(co.decider_contradiction, contradiction["contradiction_id"], "retenir_b", MOTIF)
    assert reponse["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    ok, raison = co._REGISTRE_CONTRADICTIONS.valider_chaine()
    assert ok, raison


def test_un_agent_propose_la_decision_elle_attend_une_personne(capacites):
    _humaine("regle:envoi_courriel", "non")
    _consigner(capacites, classe="journal", valeur="oui", sujet="regle:envoi_courriel", attribut="gate_humain")
    _rafraichir()
    with stockage.transaction():
        ident = co.lire_contradictions("affaires")["resultat"]["contradictions"][0]["contradiction_id"]
    reponse = capacites.appeler(
        "m10_decider_contradiction", {"contradiction_id": ident, "decision": "retenir_b", "motif": MOTIF}
    )
    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    assert [m["type_entree"] for m in _registre("contradictions")].count("contradiction_decidee") == 0


def test_la_decision_d_une_contradiction_inconnue_ou_d_une_decision_hors_enumere_est_refusee(capacites):
    for arguments in (
        {"contradiction_id": "inconnue", "decision": "retenir_a", "motif": MOTIF},
        {"contradiction_id": "inconnue", "decision": "fusionner", "motif": MOTIF},
    ):
        reponse = capacites.appeler("m10_decider_contradiction", arguments)
        if reponse.get("erreur"):
            continue  # refusé dès le schéma (énuméré fermé)
        resultat = _approuver(capacites, reponse["demande_id"])
        assert resultat["reponse"]["resultat"]["accepte"] is False
    assert _registre("contradictions") == []


def test_le_sas_n_est_jamais_inonde_cinq_demandes_par_passage_puis_le_reste(capacites):
    for i in range(7):
        _humaine(f"regle:r{i}", "non")
        _consigner(capacites, classe="journal", valeur="oui", sujet=f"regle:r{i}", attribut="gate_humain")
    premier = _rafraichir()["resultat"]
    assert (premier["nouvelles"], premier["demandes_ouvertes"], premier["demandes_differees"]) == (
        7,
        co.DEMANDES_PAR_PASSAGE,
        2,
    )
    second = _rafraichir()["resultat"]
    assert (second["nouvelles"], second["demandes_ouvertes"], second["demandes_differees"]) == (0, 2, 0)
    with stockage.transaction() as cnx:
        assert len(approbations.lister(cnx, "en_attente")) == 7


def test_le_plafond_de_demandes_ouvertes_arrete_les_nouvelles_demandes(capacites, monkeypatch):
    monkeypatch.setattr(co, "DEMANDES_OUVERTES_MAX", 2)
    for i in range(4):
        _humaine(f"regle:p{i}", "non")
        _consigner(capacites, classe="journal", valeur="oui", sujet=f"regle:p{i}", attribut="gate_humain")
    bilan = _rafraichir()["resultat"]
    assert (bilan["demandes_ouvertes"], bilan["demandes_differees"]) == (2, 2)
    assert _rafraichir()["resultat"]["demandes_ouvertes"] == 0  # tant que des personnes n'ont pas décidé


def test_une_egalite_critique_est_comptee_sans_demande(capacites):
    _consigner(capacites, classe="journal", valeur="a1", attribut="gate_humain", sujet="regle:x")
    ordre = verite.charger()
    ligne = _ligne("autre")
    valide = c.valider(
        {
            "domaine": "affaires",
            "sujet": "regle:x",
            "attribut": "gate_humain",
            "valeur": "b1",
            "classe": "journal",
            "ref": "registre:affaires:" + ligne,
            "emetteur": "agent:m01-front-office",
        },
        ordre,
        "agent",
    )
    with stockage.transaction():
        co._REGISTRE_AFFIRMATIONS.ajouter(
            c.preparer(c.affirmations(co._REGISTRE_AFFIRMATIONS.lire()), valide, H, ordre)["entree"]
        )
    bilan = _rafraichir()["resultat"]
    assert (bilan["critiques"], bilan["sans_proposition"], bilan["demandes_ouvertes"]) == (1, 1, 0)
    with stockage.transaction() as cnx:
        assert approbations.lister(cnx, "en_attente") == []


# -- 5. la lecture ----------------------------------------------------------------------------------------------
def test_les_domaines_ne_se_melangent_jamais_a_la_lecture(capacites):
    _deux_sources_non_critiques(capacites)
    _rafraichir()
    with stockage.transaction():
        assert co.lire_contradictions("affaires", "contradictions", "tous")["resultat"]["total"] == 1
        developpement = co.lire_contradictions("developpement", "contradictions", "tous")["resultat"]
        assert developpement["total"] == 0 and developpement["contradictions"] == []
        assert co.lire_contradictions("developpement", "affirmations")["resultat"]["total"] == 0


@pytest.mark.parametrize(
    "arguments",
    [
        ("clients",),
        ("affaires", "carte"),
        ("affaires", "contradictions", "au_hasard"),
        ("affaires", "contradictions", "tous", 0),
        ("affaires", "contradictions", "tous", 21),
        ("affaires", "contradictions", "tous", 5, -1),
        ("affaires", "contradictions", "tous", True),
    ],
)
def test_une_lecture_invalide_est_refusee(instance, arguments):
    with stockage.transaction():
        refus = co.lire_contradictions(*arguments)
    assert refus["accepte"] is False


def test_la_lecture_est_paginee_et_bornee(capacites):
    for i in range(6):
        _consigner(capacites, classe="journal", sujet=f"devis:L-{i}", valeur="v")
    with stockage.transaction():
        page = co.lire_contradictions("affaires", "affirmations", limite=4)["resultat"]
        suite = co.lire_contradictions("affaires", "affirmations", limite=4, decalage=4)["resultat"]
    assert page["total"] == 6 and len(page["affirmations"]) == 4 and page["suivant"] == 4
    assert len(suite["affirmations"]) == 2 and suite["suivant"] is None
    assert len(json.dumps(page, ensure_ascii=False)) <= 6000


def test_une_affirmation_remplacee_reste_visible_marquee_remplacee_jamais_supprimee(capacites):
    _consigner(capacites, valeur="accepte")
    _consigner(capacites, valeur="refuse")  # la même source se corrige : supersede
    with stockage.transaction():
        vue = co.lire_contradictions("affaires", "affirmations")["resultat"]
    assert [(a["valeur"], a["etat"]) for a in vue["affirmations"]] == [("accepte", "remplacee"), ("refuse", "active")]
    assert len(_registre("affirmations")) == 2  # deux maillons : l'ancien n'est ni supprimé ni modifié


def test_la_file_par_defaut_ne_montre_que_ce_qui_attend_quelqu_un(capacites):
    _deux_sources_non_critiques(capacites)  # D-12 : résolue automatiquement
    _humaine("regle:envoi_courriel", "non")
    _consigner(capacites, classe="journal", valeur="oui", sujet="regle:envoi_courriel", attribut="gate_humain")
    _rafraichir()
    with stockage.transaction():
        par_defaut = co.lire_contradictions("affaires")["resultat"]
        tout = co.lire_contradictions("affaires", "contradictions", "tous")["resultat"]
        resolues = co.lire_contradictions("affaires", "contradictions", "resolue_auto")["resultat"]
    assert [x["statut"] for x in par_defaut["contradictions"]] == ["en_attente_humain"] and par_defaut["total"] == 1
    assert sorted(x["statut"] for x in tout["contradictions"]) == ["en_attente_humain", "resolue_auto"]
    assert tout["total"] == 2
    assert [x["statut"] for x in resolues["contradictions"]] == ["resolue_auto"]
    assert par_defaut["compte"]["resolue_auto"] == 1  # le compte par état, lui, dit tout


def test_aucune_donnee_personnelle_ne_sort_de_la_file(capacites):
    _humaine("regle:envoi_courriel", "non")
    _consigner(capacites, classe="journal", valeur="oui", sujet="regle:envoi_courriel", attribut="gate_humain")
    _rafraichir()
    with stockage.transaction():
        texte = json.dumps(co.lire_contradictions("affaires", "contradictions", "tous")["resultat"], ensure_ascii=False)
    assert "@" not in texte and "example.test" not in texte
