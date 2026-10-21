"""Preuve du branchement du registre M4 sur le stockage durable de l'instance (ADR-0009).

`registre.py` reste pur : il ignore que ses maillons viennent d'une liste Python ou de
`opsys.stockage.MaillonsDurables`. Ce test rejoue le MÊME scénario métier — intervention
inscrite, transition en_route, pointage arrivée puis départ, complétion avec Work Completion
Trigger (outbox, CA-M4-11) — en mémoire et en durable (base SQLite temporaire), et prouve qu'ils
se comportent à l'identique :

- mêmes ligne_id (la chaîne de hash ne connaît pas son support) ;
- `valider_chaine()` vraie après relecture par une instance NEUVE (redémarrage simulé, rien en
  cache Python — seule la base persiste) ;
- l'outbox relue après ce « redémarrage » rend les mêmes Work Completion Trigger qu'à l'écriture ;
- une altération faite directement en base — hors du registre, par une requête SQL brute sur
  `registres_maillons`, comme le ferait un bogue ou une attaque qui contourne le module pur — est
  détectée par `valider_chaine()` exactement comme le serait une altération faite en mémoire (cf.
  `test_registre.py::TestChainage`).

Import : comme `test_outils_agent.py`, ce fichier ne touche pas `sys.path` — il s'appuie sur le
`pythonpath` du `pyproject.toml` racine. Aucune garde AST du département (`garde_ecriture_unique`
de l'outbox, `garde_absence_horloge`/`garde_conformite_r020` du digest) ne porte sur ce fichier :
toutes scannent `src/`, jamais `tests/` — aucune adaptation n'a donc été nécessaire.
"""

from __future__ import annotations

import pytest
from m4_field_ops import cedule, etats, outbox, pointage
from m4_field_ops.registre import Registre, VerificationError
from sqlalchemy import select, update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

_DEPARTEMENT = "m04-field-ops"
_NOM_REGISTRE = "principal"

SEL = "sel-de-test-durable"
VILLE = "Montreal"
GPS = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-DURABLE"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}

CONTRAT = {
    "lead_id": "L-DURABLE-1",
    "conversation_id": "C1",
    "type_travaux": "renovation_totale",
    "ville": VILLE,
    "canal": "telephone",
    "contact": {"nom": "Dupont", "telephone": "0102030405"},
    "urgence_declaree": True,
}
MARQUEUR = {
    "readiness_ok": True,
    "lead_id": "L-DURABLE-1",
    "hash_tete_registre": None,
    "horodatage": "2025-06-01T12:00:00+00:00",
    "empreinte": "ab" * 32,
}

H_INSCRIPTION = "2025-06-02T08:00:00+00:00"
H_ROUTE = "2025-06-02T08:30:00+00:00"
H_ARRIVEE = "2025-06-02T09:00:00+00:00"
H_DEPART = "2025-06-02T11:30:00+00:00"          # 150 minutes après l'arrivée
H_COMPLETION = "2025-06-02T11:35:00+00:00"

# Rangs d'écriture du scénario ci-dessous (ordre stable) : 0=inscription, 1=transition en_route,
# 2=pointage arrivée, 3=transition sur_site AUTOMATIQUE (pointage.enregistrer_pointage route lui-
# même une arrivée cohérente : pas d'appel explicite dans ce fichier, cf. pointage.py), 4=pointage
# départ (cohérent : aucune transition supplémentaire), 5=composite terminee+wct.
_RANG_POINTAGE_ARRIVEE = 2
_NB_MAILLONS_SCENARIO = 6


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _jouer_scenario(reg: Registre) -> str:
    """Rejoue le scénario CA-M4-11 de bout en bout sur `reg` : inscription, transition
    en_route, pointage arrivée (route automatiquement vers sur_site, cohérent avec le
    référentiel) puis départ, complétion avec Work Completion Trigger. Retourne
    intervention_id ; la suite complète des maillons écrits se relit avec `reg.lire()`, jamais
    reconstruite à la main ici (fragile : plusieurs fonctions métier écrivent plus d'un maillon
    par appel, ex. un pointage d'arrivée cohérent qui déclenche lui-même une transition)."""
    referentiel_villes = {
        cedule.tokeniser_ville(SEL, VILLE): {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0},
    }

    acc, ver = etats.inscrire_intervention(CONTRAT, MARQUEUR, reg, H_INSCRIPTION, SEL)
    assert acc is not None, f"inscription refusée : {ver}"
    i_id = acc["intervention_id"]
    assignation = {"intervention_id": i_id, "technicien_id": "T1"}

    acc_route, ver_route = etats.transitionner(i_id, "en_route", reg, H_ROUTE, assignation=assignation)
    assert acc_route is not None, f"transition en_route refusée : {ver_route}"

    for action, horo in (("arrivee", H_ARRIVEE), ("depart", H_DEPART)):
        acc_p, ver_p = pointage.enregistrer_pointage(
            i_id, "T1", action, horo, GPS, ATTESTATION, assignation,
            FENETRE, referentiel_villes, VILLE, SEL, reg,
        )
        assert acc_p is not None, f"pointage {action} refusé : {ver_p}"
        assert acc_p["gps_coherent"] is True, "le scénario suppose un GPS cohérent (pas de revue)"

    accuse, verdict = outbox.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is not None, f"complétion refusée : {verdict}"
    assert accuse["duree_reelle_minutes"] == 150

    assert reg.taille() == _NB_MAILLONS_SCENARIO
    return i_id


# -- même scénario, en mémoire et en durable -----------------------------------------------
def test_meme_scenario_memes_ligne_id_en_memoire_et_en_durable(base_durable):
    memoire = Registre()
    i_id_memoire = _jouer_scenario(memoire)

    with stockage.transaction():
        durable = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        i_id_durable = _jouer_scenario(durable)

    lignes_memoire = memoire.lire()
    lignes_durables = durable.lire()
    assert type(lignes_durables) is list  # copie profonde -> liste, jamais MaillonsDurables
    ids_memoire = [m["ligne_id"] for m in lignes_memoire]
    ids_durables = [m["ligne_id"] for m in lignes_durables]

    # Autant de ligne_id distincts que de maillons : aucune collision de hash sur ce scénario.
    assert len(set(ids_memoire)) == _NB_MAILLONS_SCENARIO
    assert i_id_durable == i_id_memoire
    # La chaîne de hash ne connaît pas son support : mêmes entrées -> mêmes ligne_id, dans le
    # même ordre, que le registre soit une liste Python ou adossé au stockage durable.
    assert ids_durables == ids_memoire
    assert lignes_durables == lignes_memoire
    assert durable.tete() == memoire.tete()
    assert durable.taille() == memoire.taille() == _NB_MAILLONS_SCENARIO
    assert durable.valider_chaine() is True
    assert memoire.valider_chaine() is True


# -- redémarrage simulé : nouvelle instance, rien en cache -----------------------------------
def test_valider_chaine_et_outbox_apres_redemarrage(base_durable):
    """`redemarre` ne partage AUCUN état Python avec `ecrivain` — nouveau Registre, nouveau
    MaillonsDurables — seule la base persiste, exactement ce qui se passe entre deux démarrages
    du processus OPSYS."""
    with stockage.transaction():
        ecrivain = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        i_id = _jouer_scenario(ecrivain)
        tete_ecrite = ecrivain.tete()
        wct_ecrits = outbox.lire_outbox(ecrivain)

    redemarre = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    assert redemarre.taille() == _NB_MAILLONS_SCENARIO
    assert redemarre.tete() == tete_ecrite
    assert redemarre.valider_chaine() is True
    redemarre.assert_chaine()  # ne doit pas lever

    # L'outbox (CA-M4-11) relue après « redémarrage » rend le(s) même(s) WCT qu'à l'écriture :
    # le Work Completion Trigger qui pilote la cascade « travaux terminés » survit au redémarrage.
    wct_relus = outbox.lire_outbox(redemarre)
    assert wct_relus == wct_ecrits
    assert len(wct_relus) == 1
    index, wct = wct_relus[0]
    assert wct["intervention_id"] == i_id
    assert wct["duree_reelle_minutes"] == 150
    assert wct["consommateurs_cibles"] == list(outbox.CONSOMMATEURS_CIBLES)

    ok, msg = outbox.verifier_invariants_outbox(redemarre)
    assert ok, msg


# -- altération hors du module pur : détectée -------------------------------------------------
def test_alteration_directe_en_base_detectee_par_valider_chaine(base_durable):
    with stockage.transaction():
        ecrivain = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
        _jouer_scenario(ecrivain)

    # Altération hors du registre : une requête SQL brute sur registres_maillons, comme le
    # ferait un bogue ou une attaque qui contourne complètement le module pur `registre.py`.
    filtre = (
        (REGISTRES.c.departement == _DEPARTEMENT)
        & (REGISTRES.c.registre == _NOM_REGISTRE)
        & (REGISTRES.c.rang == _RANG_POINTAGE_ARRIVEE)
    )
    with stockage.transaction() as cnx:
        texte_original = cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one()
        maillon = codec.decoder(texte_original)
        assert maillon["type_entree"] == pointage.TYPE_POINTAGE and maillon["action"] == "arrivee"
        maillon["latitude"] = 0.0  # contenu changé, ligne_id NON recalculé
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(maillon)))

    releve = Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    assert releve.valider_chaine() is False
    with pytest.raises(VerificationError, match="incohérent"):
        releve.assert_chaine()


# -- deux processus sur la même chaîne (serveur MCP et console) ------------------------------
def test_deux_catalogues_de_production_partagent_la_chaine_durable(base_durable):
    """Deux catalogues `outils()` sans argument simulent deux processus de l'instance : chacun
    relit la chaîne à chaque usage, voit les écritures de l'autre, et la chaîne reste valide."""
    from m4_field_ops.outils import outils

    from opsys.outils import executer_atomique

    processus_a = {o.nom: o for o in outils()}
    processus_b = {o.nom: o for o in outils()}
    with stockage.transaction():
        acc, ver = etats.inscrire_intervention(
            CONTRAT, MARQUEUR, Registre(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE)), H_INSCRIPTION, SEL,
        )
    assert acc is not None, f"inscription refusée : {ver}"
    i_id = acc["intervention_id"]

    route = executer_atomique(processus_a["m4_demarrer_route"],
                              {"intervention_id": i_id, "technicien_id": "T1", "horodatage": H_ROUTE})
    assert route["ok"] is True, route
    statut_vu_par_b = executer_atomique(processus_b["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut_vu_par_b["ok"] is True and statut_vu_par_b["resultat"]["statut"] == "en_route"

    report = executer_atomique(processus_b["m4_signaler_report"],
                               {"intervention_id": i_id, "motif": "meteo", "horodatage": H_ARRIVEE})
    assert report["ok"] is True, report
    statut_vu_par_a = executer_atomique(processus_a["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut_vu_par_a["resultat"]["statut"] == "reportee"
    assert Registre(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE)).valider_chaine() is True
