"""Barème et mesure déclarés, par `Capacites` (le chemin réel d'un appareil ou d'un agent), M3 en mode `ombre`
(M3-C1, M3-C2).

Les autres tests de ce chantier appellent les outils par `executer_atomique`. Celui-ci passe par le répartiteur du
socle, sur le VRAI manifeste de M3 : portée d'appareil par rôle, enveloppe d'idempotence d'une mutation
d'appareil, file d'approbation pour un agent en mode `ombre`. On prouve :

- un admin apparié déclare un barème sans file d'approbation (une personne qui agit elle-même) et rejouer la même
  enveloppe ne double rien ; un vendeur n'a pas la portée du barème ; un vendeur déclare la mesure de SON lead
  seulement ;
- un agent (aucune identité d'appareil) est mis en file d'approbation en mode `ombre` ; même approuvée, la demande
  ne déclare rien : l'auteur d'un barème est une personne authentifiée sur son appareil, pas l'agent dont un
  humain approuve l'appel ;
- l'estimation d'un agent par références passe par la file comme avant, et refuse un barème libre une fois
  exécutée.

Données fictives, horloge injectée."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_bareme as cb  # noqa: E402

from opsys import approbations, contexte, evenements, horloge, idempotence, identite, stockage  # noqa: E402
from opsys.capacites import Capacites, outils_executables  # noqa: E402
from opsys.departements import lire_manifeste  # noqa: E402

_RACINE_M3 = Path(__file__).resolve().parents[1]
_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"
DEP = "m03-estimation"
ADMIN = contexte.IdentiteAppelante(personne="admin.un", role="admin")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
AUTRE_VENDEUR = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
PROPRIO = contexte.IdentiteAppelante(personne="proprio", role="admin")


@pytest.fixture
def monde(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-bareme-capacites.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(horloge, "maintenant", lambda: cb.MAINTENANT)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.un", "Admin Un", _MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "proprio", "Propriétaire", _MOT_DE_PASSE, ["admin", "nathan_owner"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", _MOT_DE_PASSE, ["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", _MOT_DE_PASSE, ["seller"])
    with stockage.transaction():
        evenements.publier(
            "m2.lead_assigne", "m02-revenue-crm",
            {"lead_id": cb.LEAD, "proprietaire": "vendeur.un", "horodatage_assignation": "2026-11-01T09:00:00-04:00"},
            evenement_id=f"m2-lead-assigne-{cb.LEAD}",
        )
    departement = lire_manifeste(_RACINE_M3)
    assert departement.mode == "ombre"
    yield Capacites({DEP: departement}, stockage.transaction, appelant=DEP, memoire=False), {DEP: departement}
    stockage.liberer()


def _meta(cle):
    return idempotence.Meta(cle=cle, appareil="tel-fictif-bareme", horodatage_appareil="2026-11-02T08:00:00-05:00")


def _appareil(capacites, identite_, nom, arguments, cle):
    with contexte.appele_par_appareil(identite_):
        return capacites.appeler(nom, arguments, _meta(cle))


def _bareme_args(**surcharges):
    arguments = {"bareme_id": "bareme-fictif", "version_attendue": 0, "lignes": cb.lignes(),
                 "date_effet": cb.JOUR_EFFET_V1, "parametres": cb.PARAMETRES, "soumission": cb.SOUMISSION}
    arguments.update(surcharges)
    return arguments


def _mesure_args(**surcharges):
    arguments = {
        "mesure_id": "mesure-fictive-1", "revision_attendue": 0, "lead_id": cb.LEAD, "service": cb.SERVICE,
        "grandeur": "surface de revêtement", "valeur": "1200", "unite": "pi2", "borne_basse": "1200",
        "borne_haute": "1200", "methode": "releve_sur_place", "confiance": "elevee",
        "mesure_le": "2026-11-02T09:00:00+00:00", "pieces": ["photo-fictive-1"],
    }
    arguments.update(surcharges)
    return arguments


def _decider(departements, demande_id):
    with stockage.transaction() as cnx:
        outils = outils_executables(departements, lambda: contextlib.nullcontext(cnx))
        return approbations.decider(cnx, demande_id, True, "proprio", outils, departements)


def _versions():
    with stockage.transaction():
        return [m for m in stockage.maillons(DEP, "bareme")]


def test_un_admin_apparie_declare_le_bareme_directement_et_la_meme_enveloppe_ne_double_rien(monde):
    capacites, _ = monde
    reponse = _appareil(capacites, ADMIN, "m3_declarer_bareme", _bareme_args(), "cle-bareme-1")
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse  # pas de file : une personne
    assert reponse["resultat"]["resultat"]["bareme_ref"]["version"] == 1
    rejeu = _appareil(capacites, ADMIN, "m3_declarer_bareme", _bareme_args(), "cle-bareme-1")
    assert rejeu["ok"] is True and rejeu.get("rejoue") is True
    assert len(_versions()) == 1


def test_la_meme_cle_avec_d_autres_arguments_est_un_conflit_et_rien_ne_s_ecrit(monde):
    capacites, _ = monde
    _appareil(capacites, ADMIN, "m3_declarer_bareme", _bareme_args(), "cle-bareme-2")
    conflit = _appareil(capacites, ADMIN, "m3_declarer_bareme",
                        _bareme_args(lignes=cb.lignes(cout_unitaire_max="99.00")), "cle-bareme-2")
    assert conflit["ok"] is False
    assert len(_versions()) == 1


def test_un_vendeur_n_a_pas_la_portee_du_bareme_mais_declare_la_mesure_de_son_lead(monde):
    capacites, _ = monde
    hors_portee = _appareil(capacites, VENDEUR, "m3_declarer_bareme", _bareme_args(), "cle-v-1")
    assert hors_portee["ok"] is False and hors_portee["erreur"] in ("hors_portee_role", "outil_inconnu")
    assert _versions() == []
    mesure = _appareil(capacites, VENDEUR, "m3_declarer_mesure", _mesure_args(), "cle-m-1")
    assert mesure["ok"] is True and mesure["resultat"]["accepte"] is True, mesure
    assert mesure["resultat"]["resultat"]["auteur"] == {"personne": "vendeur.un", "role": "seller"}
    autre = _appareil(capacites, AUTRE_VENDEUR, "m3_declarer_mesure", _mesure_args(mesure_id="m-autre"), "cle-m-2")
    assert autre["ok"] is True and autre["resultat"]["accepte"] is False
    assert autre["resultat"]["verdict"]["code"] == "REJ-MESURE-IDENTITE"


def test_un_agent_est_mis_en_file_et_meme_approuvee_la_demande_ne_declare_rien(monde):
    capacites, departements = monde
    demande = capacites.appeler("m3_declarer_bareme", _bareme_args())
    assert demande["ok"] is True and demande["statut"] == "en_attente_approbation", demande
    assert _versions() == []
    # le propriétaire approuve la demande de l'agent : l'outil s'exécute, mais l'auteur d'un barème est une personne
    # authentifiée sur son appareil, pas l'agent dont un humain approuve l'appel : rien n'est écrit.
    resultat = _decider(departements, demande["demande_id"])
    assert resultat["statut"] == "echec"  # l'outil a refusé : la demande approuvée ne vaut pas identité d'auteur
    assert resultat["reponse"]["resultat"]["verdict"]["code"] == "REJ-BAREME-IDENTITE"
    assert _versions() == []


def test_l_estimation_d_un_agent_passe_par_la_file_et_la_garde_s_applique_a_l_execution(monde, monkeypatch):
    capacites, departements = monde
    monkeypatch.delenv("OPSYS_M3_VOIE_LIBRE")  # l'exploitation : la variable d'essai n'est pas posée
    _appareil(capacites, ADMIN, "m3_declarer_bareme", _bareme_args(), "cle-b")
    _appareil(capacites, VENDEUR, "m3_declarer_mesure", _mesure_args(), "cle-m")
    from m2_preparation_estimation import marqueur_m2

    contrat = {"lead_id": cb.LEAD, "conversation_id": "conv-cap-1", "type_travaux": cb.SERVICE, "ville": "Quebec",
               "canal": "formulaire", "contact": {"nom": "Durand", "telephone": "5145550000"},
               "urgence_declaree": False}
    arguments = {
        "contrat": contrat, "marqueur": marqueur_m2(cb.LEAD, contrat=contrat),
        "photos": [{"photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
                    "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme_ref": {"bareme_id": "bareme-fictif", "version": 1}, "mesure_ref": {"mesure_id": "mesure-fictive-1"},
    }
    # un barème libre est mis en file comme toute demande d'agent ; approuvé, il est REFUSÉ à l'exécution
    libre = capacites.appeler("m3_estimer_projet", {**arguments, "quantite": 5})
    assert libre["ok"] is True and libre["statut"] == "en_attente_approbation"
    resultat = _decider(departements, libre["demande_id"])
    assert resultat["statut"] == "echec"
    assert resultat["reponse"]["resultat"]["verdict"]["code"] == "REJ-BAREME-LIBRE-REFUSE"
    with stockage.transaction():
        assert list(stockage.maillons(DEP, "principal")) == []
    sans_libre = capacites.appeler("m3_estimer_projet", arguments)
    assert sans_libre["ok"] is True and sans_libre["statut"] == "en_attente_approbation"
    resultat = _decider(departements, sans_libre["demande_id"])
    assert resultat["statut"] == "executee"
    assert resultat["reponse"]["resultat"]["declaration"]["bareme_ref"]["version"] == 1
    with stockage.transaction():
        assert len(list(stockage.maillons(DEP, "principal"))) == 1


def test_l_outil_d_estimation_ne_s_ouvre_pas_aux_appareils(monde):
    capacites, _ = monde
    reponse = _appareil(capacites, ADMIN, "m3_estimer_projet", {"contrat": {}, "marqueur": {}, "photos": [],
                                                                "seuils": {}}, "cle-est")
    assert reponse["ok"] is False and reponse["erreur"] in ("hors_portee_role", "outil_inconnu")
