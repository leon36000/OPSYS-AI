"""D2 : l'acteur système `opsys-systeme` du recalcul automatique du coût certifié.

Identité de service explicite, sans session humaine simulée : elle n'existe que dans le contexte du réconciliateur
(hors requête HTTP/MCP, hors identité d'appel, hors livraison du bus), et le moteur ne l'accepte que là. Ses
exécutions sont journalisées par le moteur (intention et attestation portent `opsys-systeme`). Base éphémère, fictif.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import pickle
import sys
import threading
import time
from pathlib import Path

import m2_revenue_crm.outils as m2_outils
import m5_financecore.outils as m5_outils
import pytest
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys import moteur_recalcul_m4 as moteur
from opsys import service_acteur_systeme as systeme
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.stockage.schema import SERVICE_RECALCUL_INTENTIONS


def _charger_helpers():
    chemin = Path(__file__).with_name("test_cascade_marge_m5_m8_m10.py")
    nom = "acteur_helpers_cascade_marge"
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


cm = _charger_helpers()
BASE = dt.datetime(2026, 9, 16, 7, 0, 0, tzinfo=cm.DT_TZ)
LEAD, DEVIS, CHANTIER = "LEAD-ACT-fictif", "DEVIS-ACT-fictif", "CH-ACT-fictif"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-acteur-systeme.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_COUT_CERTIFIE_RECONCILIATEUR", "inactif")  # le test pilote l'acteur lui-même
    stockage.migrer(url)
    m2_outils.utiliser_stockage_durable()
    m5_outils.utiliser_stockage_durable()
    try:
        yield url
    finally:
        m2_outils.reinitialiser_registre()
        stockage.liberer()


def _intention(etiquette):
    return hashlib.sha256(f"acteur-{etiquette}".encode()).hexdigest()


def _chantier():
    deps = charger_departements()
    cm._m6_prix_au_livre(cm._outils(deps, "m06-material-control"), 8.0)
    wct_id, _ = cm._chantier_termine(deps, BASE, LEAD, DEVIS, CHANTIER, 40.0, certifie=True)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    cm._poser_politique("m4.recalculer_v3")
    return deps, wct_id


def test_l_acteur_systeme_ne_se_fabrique_pas_et_ne_se_copie_pas():
    with pytest.raises(PermissionError):
        systeme.ActeurSysteme(object())
    with systeme.contexte_reconciliateur() as acteur:
        assert acteur.utilisateur == systeme.IDENTIFIANT == "opsys-systeme"
        for copier in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(PermissionError):
                copier(acteur)
        with pytest.raises(PermissionError), systeme.contexte_reconciliateur():  # non réentrant
            pass
    assert not isinstance(acteur, Session)


@pytest.mark.parametrize("contexte_appel", ["mcp", "identite_console", "departement", "livraison"])
def test_jamais_depuis_une_requete_une_identite_ou_une_livraison(contexte_appel):
    from opsys.evenements import repartiteur

    gestionnaires = {
        "mcp": contexte.transport_mcp,
        "identite_console": lambda: contexte.appele_par_appareil(
            contexte.IdentiteAppelante("admin.fictif", "admin", source="console")),
        "departement": lambda: contexte.appeler_en_tant_que("m05-financecore"),
    }
    if contexte_appel == "livraison":
        jeton = repartiteur._HEURE_LIVRAISON.set(dt.datetime.now(dt.UTC))
        try:
            with pytest.raises(PermissionError), systeme.contexte_reconciliateur():
                pass
        finally:
            repartiteur._HEURE_LIVRAISON.reset(jeton)
        return
    with gestionnaires[contexte_appel](), pytest.raises(PermissionError), systeme.contexte_reconciliateur():
        pass


def test_le_moteur_refuse_l_acteur_systeme_hors_contexte_et_sans_ecriture(base_durable):
    deps, wct_id = _chantier()
    with systeme.contexte_reconciliateur() as acteur:
        pass  # contexte refermé : le jeton ne vaut plus rien
    with stockage.transaction() as cnx, pytest.raises(moteur.RefusRecalculM4) as exc:
        moteur.recalculer(cnx, acteur, acteur=systeme.IDENTIFIANT, wct_id=wct_id, devis_id=DEVIS,
                          intention_id=_intention("hors-contexte"))
    assert exc.value.code == moteur.AUTORITE_REFUSEE
    # dans un autre fil que celui qui l'a ouvert : refusé
    resultat = {}
    with systeme.contexte_reconciliateur() as actif:
        def autre_fil():
            try:
                with stockage.transaction() as cnx:
                    moteur.recalculer(cnx, actif, acteur=systeme.IDENTIFIANT, wct_id=wct_id, devis_id=DEVIS,
                                      intention_id=_intention("autre-fil"))
            except moteur.RefusRecalculM4 as erreur:
                resultat["code"] = erreur.code
        fil = threading.Thread(target=autre_fil)
        fil.start()
        fil.join(30)
    assert resultat == {"code": moteur.AUTORITE_REFUSEE}
    # un acteur déclaré différent est refusé
    with systeme.contexte_reconciliateur() as actif, stockage.transaction() as cnx, pytest.raises(
            moteur.RefusRecalculM4) as exc:
        moteur.recalculer(cnx, actif, acteur="nathan", wct_id=wct_id, devis_id=DEVIS, intention_id=_intention("x"))
    assert exc.value.code == moteur.ACTEUR_INVALIDE
    with stockage.transaction() as cnx:
        assert cnx.execute(select(SERVICE_RECALCUL_INTENTIONS)).all() == []


def test_une_personne_ne_peut_pas_prendre_le_nom_de_l_acteur_systeme(base_durable):
    deps, wct_id = _chantier()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, systeme.IDENTIFIANT, "Usurpation fictive", "mot-de-passe-fictif-assez-long",
                                ["admin"])
    session = Session(systeme.IDENTIFIANT, frozenset({"admin"}), "csrf-fictif", int(time.time()) + 3600)
    with stockage.transaction() as cnx, pytest.raises(moteur.RefusRecalculM4) as exc:
        moteur.recalculer(cnx, session, acteur=systeme.IDENTIFIANT, wct_id=wct_id, devis_id=DEVIS,
                          intention_id=_intention("usurpation"))
    assert exc.value.code == moteur.ACTEUR_INVALIDE


def test_dans_le_contexte_du_reconciliateur_l_acteur_systeme_publie_et_signe(base_durable):
    deps, wct_id = _chantier()
    with systeme.contexte_reconciliateur() as acteur, stockage.transaction() as cnx:
        reponse = moteur.recalculer(cnx, acteur, acteur=systeme.IDENTIFIANT, wct_id=wct_id, devis_id=DEVIS,
                                    intention_id=_intention("publie"))
    assert reponse["statut"] == "publiee"
    assert reponse["attestation"]["acteur"] == "opsys-systeme"
    with stockage.transaction() as cnx:
        (ligne,) = cnx.execute(select(SERVICE_RECALCUL_INTENTIONS)).mappings().all()
        assert ligne["acteur"] == "opsys-systeme" and ligne["wct_id"] == wct_id
        # aucune personne `opsys-systeme` n'a été créée pour l'occasion
        assert identite.personne(cnx, systeme.IDENTIFIANT) is None
    with systeme.contexte_reconciliateur() as acteur, stockage.transaction() as cnx:
        assert moteur.recalculer(cnx, acteur, acteur=systeme.IDENTIFIANT, wct_id=wct_id, devis_id=DEVIS,
                                 intention_id=_intention("publie"))["statut"] == "deja_executee"
