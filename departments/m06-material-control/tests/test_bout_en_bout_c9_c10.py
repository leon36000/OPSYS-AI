"""Scénario de bout en bout C9 + C10 : les VRAIS outils, les VRAIS registres durables et le VRAI bus de M6, avec une
horloge injectée et des données FICTIVES.

1. Réception de 10 gouttières (PO éphémère) : du stock entre.
2. Un WCT est publié par M4 (le vrai bus) et reçu par M6, sans déclaration de matériaux.
3. `m6_ajuster_stock` corrige le stock à 8 (motif inventaire physique), puis à 0 : l'écart est calculé, audité et
   chaîné ; les empreintes des maillons antérieurs ne bougent pas.
4. Le constat planifié calcule la disponibilité ET les alertes : déclaration d'usage manquante et commande reçue mais
   stock disparu. Aucun nom d'employé dans l'instantané.
5. Les attentes de l'admin portent les alertes ; la lecture paginée les rend.
6. Rejeu : même ajustement (aucune seconde écriture), même constat (aucun second instantané).
"""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from opsys import evenements, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

_spec = importlib.util.spec_from_file_location(
    "fixture_bout_en_bout_c9_c10", Path(__file__).with_name("test_reservation_outils.py")
)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
base, m6 = aide.base, aide.m6

FICTIF = True
GOUTTIERE = aide.GOUTTIERE
INSTANT = "2026-10-20T12:00:00-04:00"
H_ADJUST = "2026-10-20T11:00:00-04:00"
PREUVE = "fichier:sha256:" + "b" * 64


def _outil(nom, arguments):
    outil = next(o for o in aide.m6_outils.outils() if o.nom == nom)
    reponse = executer_atomique(outil, arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _demande(ajustement_id, quantite):
    return {
        "ajustement_id": ajustement_id, "materiau_id": GOUTTIERE, "motif": "inventaire_physique",
        "quantite_apres": quantite, "preuve": PREUVE, "horodatage": H_ADJUST,
    }


def _publier_wct(wct_id="WCT-FICT-C9-C10"):
    charge = {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": "lead-fictif",
        "technicien_id": "eq-fictive-declaree", "horodatage_completion": "2026-10-01T12:00:00+00:00",
        "fix_gps_completion": {"latitude": 45.5, "longitude": -73.5}, "duree_reelle_minutes": 120,
        "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 16, "consommateurs_cibles": ["M6"],
        "devis_id": "DEVIS-FICT-C9-C10", "statut": "completed_pending_review",
    }
    with stockage.transaction():
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=wct_id)
        aide.m6_outils._recevoir_travaux_termines({cle: valeur for cle, valeur in charge.items() if cle != "statut"})


def _maillons(nom):
    with stockage.transaction():
        return list(stockage.maillons(aide._DEPARTEMENT, nom))


def test_bout_en_bout_ajustement_puis_alertes(base, m6, monkeypatch):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: Decimal("100"))
    monkeypatch.setattr(
        aide.m6_outils, "_configuration_alertes", lambda: {"fenetre_jours": 30, "seuil_repetition": 2})
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-DEPOT-FICT-C9-C10")
    _publier_wct()
    empreintes_avant = [(m["index"], m["hash_maillon"]) for m in _maillons("principal")]

    premier = _outil("m6_ajuster_stock", {"ajustement": _demande("AJUST-E2E-1", 8)})
    second = _outil("m6_ajuster_stock", {"ajustement": _demande("AJUST-E2E-2", 0)})
    assert premier["ajustement"]["quantite_avant"] == "10" and premier["ajustement"]["delta"] == "-2"
    assert second["ajustement"]["quantite_avant"] == "8" and second["ajustement"]["delta"] == "-8"
    assert _outil("m6_lire_disponibilite", {"materiau_ids": [GOUTTIERE]})["resultat"]["articles"][0][
        "stock_theorique"] == "0"
    empreintes_apres = [(m["index"], m["hash_maillon"]) for m in _maillons("principal")]
    assert empreintes_apres[: len(empreintes_avant)] == empreintes_avant, "les maillons antérieurs ne sont pas réécrits"

    constat = _outil("m6_constater_disponibilite", {"horodatage": INSTANT})
    assert constat["resultat"]["publie"] is True and constat["resultat"]["alertes"]["alertes"] >= 2
    dernier = _maillons("alertes_approvisionnement")[-1]
    types = {a["type"] for a in dernier["alertes"]}
    assert {"declaration_usage_manquante", "commande_recue_stock_disparu"} <= types
    texte = json.dumps(dernier, ensure_ascii=False).lower()
    for interdit in ("eq-fictive-declaree", "alice", "bruno", "prix", "client", "@"):
        assert interdit not in texte, interdit

    lecture = _outil("m6_lire_alertes_approvisionnement", {"limite": 5})
    assert lecture["resultat"]["constate_le"] == INSTANT and lecture["resultat"]["alertes"]
    with stockage.transaction():
        attentes = aide.m6_outils.attentes()
    alertes = [a for a in attentes if a["type"] == "alerte_approvisionnement"]
    assert len(alertes) >= 2
    assert all(set(a) == {"type", "id", "resume", "niveau", "depuis", "action_proposee"} for a in attentes)

    # Rejeu : même ajustement, aucune seconde écriture ; même constat, aucun second instantané.
    taille_principal = len(_maillons("principal"))
    rejeu_ajustement = _outil("m6_ajuster_stock", {"ajustement": _demande("AJUST-E2E-1", 8)})
    assert rejeu_ajustement["statut"] == "deja_enregistre" and len(_maillons("principal")) == taille_principal
    taille_alertes = len(_maillons("alertes_approvisionnement"))
    _outil("m6_constater_disponibilite", {"horodatage": INSTANT})
    assert len(_maillons("alertes_approvisionnement")) == taille_alertes

    # La chaîne complète reste valide, y compris les deux AJUSTEMENT.
    with stockage.transaction():
        maillons = _maillons("principal")
    from m6_material_control import ajustements
    assert ajustements.verifier_chaine(maillons) == (True, "")
    with stockage.transaction() as cnx:
        bruts = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == aide._DEPARTEMENT, REGISTRES.c.registre == "principal")).all()
    assert sum(1 for ligne in bruts if codec.decoder(ligne.maillon).get("type_mouvement") == "AJUSTEMENT") == 2
