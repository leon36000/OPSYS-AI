"""Preuve du branchement du devis durable de M3 sur le stockage durable de l'instance (ADR-0009,
PLAN T2.3-a), et de l'atomicité de l'événement `m3.devis_accepte` : publié dans la MÊME
transaction que l'acceptation, et SEULEMENT à ce moment. Même patron que
`test_registre_durable.py` (base SQLite temporaire migrée, `stockage.transaction()`, nouvelle
instance = redémarrage simulé).

Les appels passent par les outils RÉELS (`executer`/`executer_atomique`, comme un agent) plutôt
que par les fonctions nues de `devis_durable.py` : ce fichier prouve le CÂBLAGE de bout en bout
(schéma JSON -> adaptateur `outils.py` -> module pur -> stockage durable -> bus d'événements),
pas la logique métier elle-même (déjà couverte par `test_devis_durable.py`, en mémoire).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import devis_durable  # noqa: E402
from m3_estimation.outils import outils, registre_devis_production  # noqa: E402

from opsys import evenements, stockage  # noqa: E402
from opsys.outils import executer_atomique, valider_arguments  # noqa: E402
from opsys.stockage import codec  # noqa: E402
from opsys.stockage.schema import EVENEMENTS_SORTANTS  # noqa: E402

_HORODATAGE = "2026-09-28T14:00:00-04:00"


def _ligne(**surcharges):
    ligne = {
        "description": "Gouttière alu 5 po",
        "quantite": "30",
        "unite": "pi_lin",
        "cout_unitaire": "10.00",
        "reference_besoin_materiau": "besoin-goutt-001",
    }
    ligne.update(surcharges)
    return ligne


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


def _appeler(nom, arguments):
    return executer_atomique(_outil(nom), arguments)


def _creer(devis_id, **surcharges):
    arguments = {
        "devis_id": devis_id,
        "lead_id": "lead-001",
        "chantier_id": None,
        "lignes": [_ligne()],
        "taux_marge": "0.20",
        "horodatage": _HORODATAGE,
    }
    arguments.update(surcharges)
    return _appeler("m3_creer_devis", arguments)


def _compte_evenements(where=None) -> int:
    requete = select(func.count()).select_from(EVENEMENTS_SORTANTS)
    if where is not None:
        requete = requete.where(where)
    with stockage.transaction() as cnx:
        return cnx.execute(requete).scalar_one()


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


# -- relecture par une nouvelle instance, depuis le stockage durable --------------------------
def test_creer_devis_puis_relecture_par_une_nouvelle_instance_depuis_le_stockage_durable(base_durable):
    cree = _creer("M3-DEVIS-stock-001")
    assert cree["ok"] is True, cree
    assert cree["resultat"]["accepte"] is True

    # "Nouvelle instance" : aucun état Python en cache entre les deux appels — seule la base a
    # persisté ce qui a été écrit ci-dessus, exactement ce qui se passe entre deux redémarrages
    # du processus OPSYS (comme test_registre_durable.py).
    lu = _appeler("m3_lire_devis", {"devis_id": "M3-DEVIS-stock-001"})
    assert lu["ok"] is True, lu
    devis = lu["resultat"]["resultat"]
    assert devis["statut"] == "brouillon"
    # vers_json (opsys.outils) convertit chaque Decimal en texte, jamais en float.
    assert devis["cout_total"] == "300.00"
    assert devis["prix_total"] == "360.00"
    assert devis["taux_marge"] == "0.20"
    assert devis["lignes"][0]["cout_unitaire"] == "10.00"
    assert devis["lignes"][0]["prix_ligne"] == "360.00"


def test_deux_appels_de_registre_devis_production_partagent_le_meme_devis(base_durable):
    """Deux appels à `registre_devis_production()` sans état partagé simulent deux processus de
    l'instance (serveur MCP, console) : chacun relit la collection "devis" à chaque usage, voit
    les écritures de l'autre — même preuve que `test_registre_durable.py` pour le registre
    "principal"."""
    with stockage.transaction():
        processus_a = registre_devis_production()
        devis_durable.creer_devis(
            "M3-DEVIS-stock-002", "lead-002", None, [_ligne()], "0.20", _HORODATAGE, processus_a
        )

    processus_b = registre_devis_production()
    assert len(processus_b) == 1

    with stockage.transaction():
        devis_durable.marquer_devis_envoye("M3-DEVIS-stock-002", _HORODATAGE, processus_b)

    assert len(registre_devis_production()) == 2
    etat, verdict = devis_durable.lire_devis(registre_devis_production(), "M3-DEVIS-stock-002")
    assert verdict is None
    assert etat["statut"] == "envoye"


def test_idempotence_de_creer_devis_a_travers_loutil_ne_grossit_pas_le_registre_durable(base_durable):
    premier = _creer("M3-DEVIS-stock-idem")
    assert premier["ok"] is True and premier["resultat"]["accepte"] is True
    assert len(registre_devis_production()) == 1

    second = _creer("M3-DEVIS-stock-idem")  # rejeu identique, ex. après une panne réseau
    assert second["ok"] is True and second["resultat"]["accepte"] is True
    assert len(registre_devis_production()) == 1, "un rejeu identique ne doit écrire aucun second maillon"


# -- événement m3.devis_accepte : même transaction, et SEULEMENT à l'acceptation ----------------
def test_creer_et_lire_un_devis_ne_publient_jamais_levenement(base_durable):
    _creer("M3-DEVIS-stock-003")
    _appeler("m3_lire_devis", {"devis_id": "M3-DEVIS-stock-003"})
    assert _compte_evenements() == 0


def test_marquer_devis_accepte_publie_levenement_dans_la_meme_transaction(base_durable):
    cree = _creer("M3-DEVIS-stock-004", chantier_id="chantier-004")
    assert cree["ok"] is True
    assert _compte_evenements() == 0, "aucun événement avant l'acceptation"

    reponse = _appeler(
        "m3_marquer_devis_accepte",
        {"devis_id": "M3-DEVIS-stock-004", "approbateur": "nathan", "horodatage": _HORODATAGE},
    )
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["resultat"]["statut"] == "accepte"

    assert _compte_evenements() == 1
    with stockage.transaction() as cnx:
        ligne = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_accepte")
        ).mappings().one()
    assert ligne["producteur"] == "m03-estimation"
    # evenement_id déterministe (PLAN T2.3-b, même patron que m6.variance_chantier :
    # f"m6-variance-{wct_id}") : défense en profondeur, jamais le devis_id nu comme identifiant
    # d'événement (cohérence de nommage avec le reste du bus).
    assert ligne["evenement_id"] == "m3-devis-accepte-M3-DEVIS-stock-004"
    charge = codec.decoder(ligne["charge"])
    assert charge["devis_id"] == "M3-DEVIS-stock-004"
    assert charge["lead_id"] == "lead-001"
    assert charge["chantier_id"] == "chantier-004"
    assert charge["cout_total"] == "300.00"
    assert charge["prix_total"] == "360.00"
    assert charge["taux_marge"] == "0.20"
    assert charge["horodatage_acceptation"] == _HORODATAGE
    assert charge["lignes"] == [
        {
            "reference_ligne": "M3-DEVIS-stock-004-L0",
            "description": "Gouttière alu 5 po",
            "quantite": "30",
            "unite": "pi_lin",
            "prix_unitaire": "12.00",
            "prix_ligne": "360.00",
            "reference_besoin_materiau": "besoin-goutt-001",
        }
    ]
    # Séparation coût/prix (audit M3) : aucun COÛT par ligne dans l'événement (le prix, lui, EST
    # porté — PLAN T2.3-b, pour que M5 facture sans rien recalculer différemment).
    assert "cout_unitaire" not in charge["lignes"][0]
    assert "cout_ligne" not in charge["lignes"][0]

    # La charge publiée est VALIDE au sens du catalogue (aucune erreur de schéma) : le fait que
    # evenements.publier n'ait pas levé ChargeInvalide le prouve déjà, mais on le vérifie ici
    # directement et explicitement, sur la charge relue en base (pas un objet Python interne).
    schema = evenements.schema("m3.devis_accepte")
    assert valider_arguments(schema, charge) == []


def test_evenement_devis_accepte_redelivre_avec_le_meme_evenement_id_est_un_no_op(base_durable):
    """Relivraison (PLAN T2.3-b) : publier deux fois la MÊME charge sous le MÊME evenement_id
    déterministe (ex. un rejeu après une panne réseau entre l'écriture et la réponse au
    producteur) ne crée jamais un second événement — défense en profondeur, même garantie que
    `opsys.evenements.publier` documente pour tout evenement_id fourni explicitement."""
    _creer("M3-DEVIS-stock-008")
    with stockage.transaction():
        devis, verdict = devis_durable.marquer_devis_accepte(
            "M3-DEVIS-stock-008", "nathan", _HORODATAGE, registre_devis_production()
        )
        assert verdict is None
        charge = devis_durable.charge_evenement_devis_accepte(devis)
        ident = "m3-devis-accepte-M3-DEVIS-stock-008"
        premier = evenements.publier("m3.devis_accepte", "m03-estimation", charge, evenement_id=ident)
        second = evenements.publier("m3.devis_accepte", "m03-estimation", charge, evenement_id=ident)

    assert premier == second == ident
    assert _compte_evenements() == 1


def test_marquer_devis_accepte_une_deuxieme_fois_rejete_et_ne_republie_pas_levenement(base_durable):
    _creer("M3-DEVIS-stock-006")
    premiere = _appeler(
        "m3_marquer_devis_accepte",
        {"devis_id": "M3-DEVIS-stock-006", "approbateur": "nathan", "horodatage": _HORODATAGE},
    )
    assert premiere["ok"] is True and premiere["resultat"]["accepte"] is True
    assert _compte_evenements() == 1

    seconde = _appeler(
        "m3_marquer_devis_accepte",
        {"devis_id": "M3-DEVIS-stock-006", "approbateur": "nathan", "horodatage": _HORODATAGE},
    )
    assert seconde["ok"] is True  # rejet MÉTIER (verdict), pas une exception : ok=True quand même
    assert seconde["resultat"]["accepte"] is False
    assert seconde["resultat"]["verdict"]["code"] == "REJ-DEVIS-TRANSITION-ILLEGALE"
    assert _compte_evenements() == 1, "un second accepte rejeté ne publie jamais un second événement"


def test_rejet_de_marquer_devis_accepte_sans_approbateur_ne_publie_rien_devis_reste_brouillon(base_durable):
    _creer("M3-DEVIS-stock-005")

    reponse = _appeler(
        "m3_marquer_devis_accepte",
        {"devis_id": "M3-DEVIS-stock-005", "approbateur": "", "horodatage": _HORODATAGE},
    )
    assert reponse["ok"] is True  # rejet MÉTIER (verdict), pas une exception : ok=True quand même
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-DEVIS-APPROBATEUR-ABSENT"
    assert _compte_evenements() == 0

    lu = _appeler("m3_lire_devis", {"devis_id": "M3-DEVIS-stock-005"})
    assert lu["resultat"]["resultat"]["statut"] == "brouillon"


def test_echec_apres_lacceptation_annule_aussi_lecriture_du_registre_meme_transaction(base_durable, monkeypatch):
    """Preuve d'atomicité DIRECTE : si la publication de l'événement échoue (charge invalide),
    la transition ACCEPTE déjà écrite dans le MÊME appel est annulée avec elle — même mécanisme
    que `tests/test_evenements.py::test_atomicite_ecriture_et_evenement_annulees_ensemble`,
    exercé ici sur le vrai outil `m3_marquer_devis_accepte`."""
    _creer("M3-DEVIS-stock-007")

    # Sabote SEULEMENT la construction de la charge (pas la transition elle-même) pour forcer
    # evenements.publier à lever ChargeInvalide APRÈS que le maillon "accepte" a été écrit.
    monkeypatch.setattr(devis_durable, "charge_evenement_devis_accepte", lambda devis: {})

    reponse = _appeler(
        "m3_marquer_devis_accepte",
        {"devis_id": "M3-DEVIS-stock-007", "approbateur": "nathan", "horodatage": _HORODATAGE},
    )
    assert reponse["ok"] is False, reponse
    assert reponse["erreur"] == "refus_metier"

    assert _compte_evenements() == 0

    etat, verdict = devis_durable.lire_devis(registre_devis_production(), "M3-DEVIS-stock-007")
    assert verdict is None
    assert etat["statut"] == "brouillon", "la transition ACCEPTE doit être annulée avec l'événement raté"
