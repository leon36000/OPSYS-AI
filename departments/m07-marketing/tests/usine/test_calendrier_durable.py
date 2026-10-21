"""Tranche calendrier: mêmes transactions et maillons canoniques que l'usine M7."""

from __future__ import annotations

from pathlib import Path

import pytest
from m7_marketing import outils
from m7_marketing.brand import profil_client
from sqlalchemy import update

from opsys import approbations, contexte, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

FICTIF = True
_OUTILS = {outil.nom: outil for outil in outils.outils()}
_HORODATAGE = "2026-09-30T10:00:00-04:00"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def owner(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", "mot-de-passe-test-1234", ["nathan_owner", "admin"])


@pytest.fixture
def brand_configure(monkeypatch, profil):
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(profil), None))


def _appel(nom, *, owner=False, **args):
    if owner:
        with contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin")):
            return executer_atomique(_OUTILS[nom], args)
    return executer_atomique(_OUTILS[nom], args)


def _valeur(nom, **args):
    reponse = _appel(nom, **args)
    assert reponse["ok"], reponse
    resultat = reponse["resultat"]
    assert resultat.get("accepte", True), resultat
    return resultat.get("resultat", resultat)


def _preparer(base_durable, brand_configure, owner, charge):
    with stockage.transaction():
        stockage.maillons("m07-marketing", "wct_recus").append(charge)
    _valeur("m7_proposer_contenus_chantier", wct_id=charge["wct_id"])
    with stockage.transaction():
        contenus = list(stockage.maillons("m07-marketing", "contenus_chantier"))
    proposition = next(p for p in contenus if p["plateforme"] == "facebook")
    _valeur(
        "m7_decider_contenu",
        owner=True,
        contenu_id=proposition["contenu_id"],
        decision="approuver",
        horodatage=_HORODATAGE,
    )
    return proposition


def test_reprise_et_export_humain_rejouable_sur_registres_canoniques(base_durable, brand_configure, owner, charge):
    proposition = _preparer(base_durable, brand_configure, owner, charge)
    slot = _valeur(
        "m7_proposer_creneau_calendrier",
        contenu_id=proposition["contenu_id"],
        planifie_le="2026-10-04T18:30:00-04:00",
        horodatage=_HORODATAGE,
    )
    assert slot["statut"] == "BROUILLON"
    replay = _valeur(
        "m7_proposer_creneau_calendrier",
        contenu_id=proposition["contenu_id"],
        planifie_le="2026-10-04T18:30:00-04:00",
        horodatage=_HORODATAGE,
    )
    assert replay["deja_present"] and replay["creneau_id"] == slot["creneau_id"]
    assert len(_lire("calendrier_contenus")) == 1

    autorisation = _valeur(
        "m7_decider_creneau_calendrier",
        owner=True,
        creneau_id=slot["creneau_id"],
        decision="approuver",
        horodatage=_HORODATAGE,
    )
    assert autorisation["par"] == "nathan" and autorisation["decision"] == "APPROVED"
    rejeu_decision = _valeur(
        "m7_decider_creneau_calendrier",
        owner=True,
        creneau_id=slot["creneau_id"],
        decision="approuver",
        horodatage=_HORODATAGE,
    )
    assert rejeu_decision["deja_tranche"] is True
    conflit_decision = _appel(
        "m7_decider_creneau_calendrier",
        owner=True,
        creneau_id=slot["creneau_id"],
        decision="rejeter",
        horodatage=_HORODATAGE,
        motif="changer le créneau",
    )
    assert conflit_decision["resultat"]["verdict"]["code"] == "REJ-CRENEAU-CONFLIT"
    paquet = _valeur("m7_exporter_creneau_manuel", owner=True, creneau_id=slot["creneau_id"], horodatage=_HORODATAGE)
    assert paquet["publication"].startswith("non publiée")
    (preuve,) = _lire("exports_calendrier")
    assert preuve["contenu_id"] == proposition["contenu_id"]
    assert preuve["source"] == "remise_manuelle_proprietaire" and preuve["exporte_par"] == "nathan"
    assert preuve["empreinte_texte"] == proposition["empreinte_texte"]
    assert preuve["source_wct"] == slot["source"]

    # Réouverture de l'instance depuis le même fichier SQLite : les maillons suffisent à reconstruire l'état.
    stockage.liberer()
    stockage.migrer(base_durable)
    etat = _valeur("m7_lister_calendrier", wct_id=charge["wct_id"])
    assert etat["creneaux"][0]["statut"] == "APPROVED"
    assert etat["creneaux"][0]["export"]["exporte_par"] == "nathan"
    replay_export = _valeur(
        "m7_exporter_creneau_manuel", owner=True, creneau_id=slot["creneau_id"], horodatage=_HORODATAGE
    )
    assert replay_export["deja_exporte"] is True
    assert len(_lire("exports_calendrier")) == 1


def test_decision_calendrier_utilise_la_file_d_approbation_existante(base_durable, brand_configure, owner, charge):
    proposition = _preparer(base_durable, brand_configure, owner, charge)
    slot = _valeur("m7_proposer_creneau_calendrier", contenu_id=proposition["contenu_id"],
                   planifie_le="2026-10-04T18:30:00-04:00", horodatage=_HORODATAGE)
    arguments = {"creneau_id": slot["creneau_id"], "decision": "approuver", "horodatage": _HORODATAGE}
    manifest = lire_manifeste(Path(__file__).resolve().parents[2])
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(
            cnx, "m07-marketing", "m7_decider_creneau_calendrier", arguments, niveau=Niveau.N3,
        )
    with stockage.transaction() as cnx:
        sortie = approbations.decider(cnx, demande, True, "nathan", _OUTILS, {"m07-marketing": manifest})
    assert sortie["statut"] == "executee"
    assert sortie["reponse"]["resultat"]["resultat"]["source"] == "approbation"


def test_conflit_hash_source_et_retrait_apres_approbation_bloquent_export(
    base_durable,
    brand_configure,
    owner,
    charge,
):
    proposition = _preparer(base_durable, brand_configure, owner, charge)
    slot = _valeur(
        "m7_proposer_creneau_calendrier",
        contenu_id=proposition["contenu_id"],
        planifie_le="2026-10-04T18:30:00-04:00",
        horodatage=_HORODATAGE,
    )
    refus_agent = _appel(
        "m7_decider_creneau_calendrier", creneau_id=slot["creneau_id"], decision="approuver", horodatage=_HORODATAGE
    )
    assert refus_agent["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _lire("decisions_calendrier") == []
    slot_id = slot["creneau_id"]
    # Le hash de source d'un créneau n'est jamais une identité d'argument; altérer le maillon legacy fait échouer fermé.
    with stockage.transaction() as cnx:
        slot_maillon = list(stockage.maillons("m07-marketing", "calendrier_contenus"))[0]
        cnx.execute(
            update(REGISTRES)
            .where(
                (REGISTRES.c.departement == "m07-marketing")
                & (REGISTRES.c.registre == "calendrier_contenus")
                & (REGISTRES.c.rang == 0)
            )
            .values(maillon=codec.encoder({**slot_maillon, "empreinte_texte": "ff" * 32}))
        )
    resultat = _appel(
        "m7_decider_creneau_calendrier", owner=True, creneau_id=slot_id, decision="approuver", horodatage=_HORODATAGE
    )
    assert resultat["ok"] and resultat["resultat"]["accepte"] is False
    assert resultat["resultat"]["verdict"]["code"] == "REJ-CRENEAU-CONFLIT"
    assert _lire("decisions_calendrier") == []

    # Restaurer le maillon avant de tester un vrai retrait de consentement après approbation.
    with stockage.transaction() as cnx:
        cnx.execute(
            update(REGISTRES)
            .where(
                (REGISTRES.c.departement == "m07-marketing")
                & (REGISTRES.c.registre == "calendrier_contenus")
                & (REGISTRES.c.rang == 0)
            )
            .values(maillon=codec.encoder(slot))
        )
    _valeur(
        "m7_decider_creneau_calendrier", owner=True, creneau_id=slot_id, decision="approuver", horodatage=_HORODATAGE
    )
    _valeur(
        "m7_enregistrer_retrait_consentement_marketing",
        wct_id=charge["wct_id"],
        canal="telephone",
        horodatage=_HORODATAGE,
    )
    refus = _appel("m7_exporter_creneau_manuel", owner=True, creneau_id=slot_id, horodatage=_HORODATAGE)
    assert refus["ok"] and refus["resultat"]["accepte"] is False
    assert refus["resultat"]["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"
    assert _lire("exports_calendrier") == []


def _lire(nom):
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))
