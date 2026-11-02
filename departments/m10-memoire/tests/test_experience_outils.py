"""Les deux outils de la mémoire d'expérience (J1) sur une base SQLite migrée et le registre MCP SCELLÉ réel :
niveaux, garde
d'admission, audit des refus qui survit (sans contenu), idempotence, lecture rejouée, péremption, fail-closed si le
registre
est illisible. Aucun modèle, aucun réseau, données FICTIVES."""

from __future__ import annotations

import copy
import json
import types
from pathlib import Path

import pytest
from m10_memoire import experience_outils as eo

from opsys import contexte, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau

FICTIF = True
RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture
def instance(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.delenv("OPSYS_MCP_REGISTRE", raising=False)
    stockage.migrer(url)
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def capacites(instance):
    return Capacites(charger_departements(RACINE), stockage.transaction, filtre={"m10-memoire"}, memoire=False)


def convention(**surcharge):
    base = {
        "genre": "convention_outil",
        "departement": "m10-memoire",
        "domaine": "affaires",
        "pack": None,
        "declencheur": {"outil": "m10_lire_rapports_routine", "code_refus": "REJ-ROUTINE-GENRE-INCONNU"},
        "contenu": {
            "outil": "m10_lire_rapports_routine",
            "cle_argument": "genre",
            "regle": "L'argument genre est l'un des genres de rapport connus de la routine.",
            "correction": "Relire la liste des genres dans la description de l'outil avant de rappeler.",
        },
        "origine": "reference_ecrite_main",
    }
    base.update(surcharge)
    return base


def _registre():
    with stockage.transaction():
        return list(stockage.maillons("m10-memoire", "experiences"))


def test_les_deux_outils_sont_declares_sans_droit_d_appareil(capacites):
    par_nom = {o.nom: o for o in capacites.lister()}
    assert (par_nom["m10_proposer_experience"].autonomie, par_nom["m10_proposer_experience"].niveau_effectif) == (
        Autonomie.T1,
        Niveau.N2,
    )
    assert (par_nom["m10_lire_experiences"].autonomie, par_nom["m10_lire_experiences"].niveau_effectif) == (
        Autonomie.T0,
        Niveau.N0,
    )
    for nom in ("m10_proposer_experience", "m10_lire_experiences"):
        assert par_nom[nom].roles_appareil == frozenset() and not par_nom[nom].frontiere_humaine


def test_un_bon_element_devient_candidat_seulement_et_rejouer_n_ajoute_rien(capacites):
    reponse = capacites.appeler("m10_proposer_experience", {"element": convention()})
    assert reponse["ok"] is True
    resultat = reponse["resultat"]["resultat"]
    assert (
        resultat["resultat"] == "ajoute"
        and resultat["statut"] == "candidat"
        and "promotion humaine" in resultat["mention"]
    )
    seconde = capacites.appeler("m10_proposer_experience", {"element": convention()})
    assert seconde["resultat"]["resultat"]["resultat"] == "deja_present"
    assert [m["type_entree"] for m in _registre()] == ["experience_proposee"]
    [m] = _registre()
    assert m["par"] == "agent:m10-memoire" and m["element"]["statut"] == "candidat"
    assert m["element"]["portee_outils"][0]["outil"] == "m10_lire_rapports_routine"
    assert m["element"]["portee_outils"][0]["empreinte"].startswith("sha256:")  # lié à l'empreinte scellée de l'outil


@pytest.mark.parametrize(
    "surcharge, code",
    [
        ({"origine": "courriel"}, "REJ-EXPERIENCE-ORIGINE-NON-FIABLE"),
        ({"origine": "fiche_deterministe"}, "REJ-EXPERIENCE-ORIGINE-RESERVEE"),  # réservée au code
        ({"genre": "regle_libre"}, "REJ-EXPERIENCE-GENRE-INCONNU"),
        (
            {
                "contenu": {"outil": "m10_outil_invente", "cle_argument": "x", "regle": "r", "correction": "c"},
                "declencheur": {"outil": "m10_outil_invente", "code_refus": None},
            },
            "REJ-EXPERIENCE-OUTIL-INCONNU",
        ),
        (
            {
                "contenu": {
                    "outil": "m10_lire_rapports_routine",
                    "cle_argument": "argument_invente",
                    "regle": "r",
                    "correction": "c",
                }
            },
            "REJ-EXPERIENCE-ARGUMENT-INCONNU",
        ),
        (
            {
                "contenu": {
                    "outil": "m10_lire_rapports_routine",
                    "cle_argument": "genre",
                    "regle": "Le délai est de 5 jours.",
                    "correction": "Attendre.",
                }
            },
            "REJ-EXPERIENCE-CHIFFRE",
        ),
        (
            {
                "contenu": {
                    "outil": "m10_lire_rapports_routine",
                    "cle_argument": "genre",
                    "regle": "Écrire à jean@example.test.",
                    "correction": "Attendre.",
                }
            },
            "REJ-EXPERIENCE-DONNEE-PERSONNELLE",
        ),
        (
            {
                "contenu": {
                    "outil": "m10_lire_rapports_routine",
                    "cle_argument": "genre",
                    "regle": "Genre requis.",
                    "correction": "Appeler sans approbation.",
                }
            },
            "REJ-EXPERIENCE-CONTOURNEMENT",
        ),
    ],
)
def test_un_refus_est_rendu_et_son_audit_survit_sans_le_contenu_refuse(capacites, surcharge, code):
    reponse = capacites.appeler("m10_proposer_experience", {"element": convention(**surcharge)})
    verdict = reponse["resultat"]["verdict"]
    assert reponse["resultat"]["accepte"] is False and verdict["code"] == code
    [trace] = _registre()  # la trace du refus a survécu : la transaction n'a pas été annulée
    assert (
        trace["type_entree"] == "experience_refusee" and trace["code"] == code and len(trace["empreinte_soumis"]) == 64
    )
    brut = json.dumps(trace, ensure_ascii=False)
    for contenu in ("jean@example.test", "5 jours", "sans approbation", "argument_invente"):
        assert contenu not in brut and contenu not in json.dumps(verdict, ensure_ascii=False)


def test_un_appel_d_appareil_est_refuse(instance):
    employe = contexte.IdentiteAppelante("employe-fictif", "employee")
    with (
        contexte.appele_par_appareil(employe),
        pytest.raises(Exception, match="REJ-MNEMO-APPAREIL-FERME"),
        stockage.transaction(),
    ):
        eo.proposer_experience(convention())
    assert _registre() == []


def test_la_lecture_rejoue_l_etat_filtre_et_compte_les_refus(capacites):
    capacites.appeler("m10_proposer_experience", {"element": convention()})
    capacites.appeler("m10_proposer_experience", {"element": convention(origine="web")})
    lecture = capacites.appeler("m10_lire_experiences", {})["resultat"]["resultat"]
    assert lecture["total"] == 1 and lecture["refus_comptes"] == 1 and lecture["elements"][0]["statut"] == "candidat"
    assert capacites.appeler("m10_lire_experiences", {"domaine": "developpement"})["resultat"]["resultat"]["total"] == 0
    assert (
        capacites.appeler("m10_lire_experiences", {"departement": "m02-revenue-crm"})["resultat"]["resultat"]["total"]
        == 0
    )
    assert capacites.appeler("m10_lire_experiences", {"statut": "perime"})["resultat"]["resultat"]["total"] == 0
    for arguments in ({"limite": 0}, {"limite": 21}, {"decalage": -1}, {"domaine": "clients"}, {"statut": "promu"}):
        reponse = capacites.appeler("m10_lire_experiences", arguments)
        assert reponse.get("ok") is False or reponse["resultat"]["accepte"] is False, arguments


def test_un_element_dont_l_empreinte_d_outil_change_devient_perime_a_la_lecture(capacites, monkeypatch):
    capacites.appeler("m10_proposer_experience", {"element": convention()})
    reel = eo.vue_registre()
    entrees = dict(reel.entrees)
    entree = entrees["m10_lire_rapports_routine"]
    entrees["m10_lire_rapports_routine"] = types.SimpleNamespace(
        departement=entree.departement,
        niveau=entree.niveau,
        schema_entree=entree.schema_entree,
        empreinte="sha256:" + "0" * 64,
    )
    monkeypatch.setattr(eo, "vue_registre", lambda: types.SimpleNamespace(revision=reel.revision + 1, entrees=entrees))
    lecture = capacites.appeler("m10_lire_experiences", {})["resultat"]["resultat"]
    assert lecture["elements"][0]["statut"] == "perime" and lecture["registre_mcp_revision"] == reel.revision + 1
    assert len(_registre()) == 1  # la péremption se rejoue, elle ne réécrit rien


def test_un_registre_mcp_illisible_ferme_l_admission_au_lieu_de_l_ouvrir(capacites, monkeypatch, tmp_path):
    monkeypatch.setenv("OPSYS_MCP_REGISTRE", str(tmp_path / "absent.json"))
    reponse = capacites.appeler("m10_proposer_experience", {"element": convention()})
    assert reponse["resultat"]["verdict"]["code"] == "REJ-EXPERIENCE-REGISTRE-INDISPONIBLE"
    lecture = capacites.appeler("m10_lire_experiences", {})
    assert lecture["resultat"]["verdict"]["code"] == "REJ-EXPERIENCE-REGISTRE-INDISPONIBLE"
    assert _registre() == []


def test_le_registre_scelle_livre_valide_les_vraies_empreintes_et_refuse_un_outil_hors_portee(capacites):
    reel = eo.vue_registre()
    assert (
        "m10_lire_rapports_routine" in reel.entrees
        and reel.entrees["m10_lire_rapports_routine"].departement == "m10-memoire"
    )
    hors = copy.deepcopy(convention())
    hors["departement"] = "m02-revenue-crm"
    reponse = capacites.appeler("m10_proposer_experience", {"element": hors})
    assert reponse["resultat"]["verdict"]["code"] == "REJ-EXPERIENCE-OUTIL-HORS-PORTEE"
