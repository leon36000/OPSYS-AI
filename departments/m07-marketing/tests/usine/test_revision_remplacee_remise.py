"""Une révision remplacée ne se remet plus : texte approuvé puis corrigé par le propriétaire (M7.2/M7.3).

Le propriétaire corrige depuis la console un texte qu'il avait déjà approuvé : la nouvelle révision attend sa
décision (`PROPOSE`). L'ancien texte, son approbation et son créneau approuvé restent au registre (audit), mais
ne sont plus la preuve courante : aucun paquet, créneau ni fait de mesure ne doit en sortir. Données fictives.
"""

from __future__ import annotations

import pytest
from m7_marketing import outils
from m7_marketing.brand import profil_client
from m7_marketing.usine import service
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
_OUTILS = {outil.nom: outil for outil in outils.outils()}
_HORODATAGE = "2026-09-30T10:00:00-04:00"
_NOUVEAU_TEXTE = "Un projet de gouttières terminé avec soin."


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


def _metier(nom, **args):
    reponse = _appel(nom, **args)
    assert reponse["ok"], reponse
    return reponse["resultat"]


def _valeur(nom, **args):
    resultat = _metier(nom, **args)
    assert resultat.get("accepte", True), resultat
    return resultat.get("resultat", resultat)


def _lire(nom):
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def _faits_exportes():
    with stockage.transaction() as cnx:
        return cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m7.contenu_exporte"
        )).scalars().all()


def _approuver_facebook(charge):
    with stockage.transaction():
        stockage.maillons("m07-marketing", "wct_recus").append(charge)
    _valeur("m7_proposer_contenus_chantier", wct_id=charge["wct_id"])
    proposition = next(p for p in _lire("contenus_chantier") if p["plateforme"] == "facebook")
    _valeur("m7_decider_contenu", owner=True, contenu_id=proposition["contenu_id"], decision="approuver",
            horodatage=_HORODATAGE)
    return proposition


def _creneau_approuve(contenu_id, planifie_le="2026-10-04T18:30:00-04:00"):
    slot = _valeur("m7_proposer_creneau_calendrier", contenu_id=contenu_id, planifie_le=planifie_le,
                   horodatage=_HORODATAGE)
    _valeur("m7_decider_creneau_calendrier", owner=True, creneau_id=slot["creneau_id"], decision="approuver",
            horodatage=_HORODATAGE)
    return slot


def _reviser_par_le_proprietaire(contenu_id, texte=_NOUVEAU_TEXTE):
    """La voie console réelle du service (`opsys.console.metier`) : propriétaire humain, CAS de lecture."""
    with (
        stockage.transaction(),
        contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "nathan_owner", source="console")),
        contexte.appeler_en_tant_que("m07-marketing", origine="console"),
    ):
        lecture = service.lire_edition_texte_humain(contenu_id)
        assert lecture["accepte"], lecture
        preuve = lecture["resultat"]
        reponse = service.reviser_texte_humain(
            contenu_id, preuve["revision"], preuve["empreinte_texte"], preuve["snapshot_sha256"], texte,
            "2026-09-30T11:00:00-04:00",
        )
    assert reponse["accepte"] and reponse["resultat"]["modifie"], reponse
    return reponse["resultat"]["contenu_id"]


def test_texte_approuve_puis_corrige_l_ancienne_revision_ne_sort_plus(base_durable, brand_configure, owner, charge):
    ancienne = _approuver_facebook(charge)
    slot = _creneau_approuve(ancienne["contenu_id"])
    brouillon = _valeur("m7_proposer_creneau_calendrier", contenu_id=ancienne["contenu_id"],
                        planifie_le="2026-10-06T18:30:00-04:00", horodatage=_HORODATAGE)
    nouvelle_id = _reviser_par_le_proprietaire(ancienne["contenu_id"])
    assert nouvelle_id != ancienne["contenu_id"]
    historiques = {n: _lire(n) for n in ("decisions_contenu", "calendrier_contenus", "decisions_calendrier")}

    # L'agent (N2, sans humain) ne tire plus un paquet de l'ancien texte.
    agent = _metier("m7_exporter_paquet_manuel", contenu_id=ancienne["contenu_id"], horodatage=_HORODATAGE)
    assert agent["accepte"] is False and agent["verdict"]["code"] == "REJ-CONTENU-PERIME"
    # Le propriétaire non plus, par son créneau approuvé avant la correction.
    remise = _metier("m7_exporter_creneau_manuel", owner=True, creneau_id=slot["creneau_id"], horodatage=_HORODATAGE)
    assert remise["accepte"] is False and remise["verdict"]["code"] == "REJ-CONTENU-PERIME"
    # Aucun nouveau créneau ni décision de créneau sur la révision remplacée.
    nouveau_slot = _metier("m7_proposer_creneau_calendrier", contenu_id=ancienne["contenu_id"],
                           planifie_le="2026-10-05T18:30:00-04:00", horodatage=_HORODATAGE)
    assert nouveau_slot["accepte"] is False and nouveau_slot["verdict"]["code"] == "REJ-CONTENU-PERIME"
    decision = _metier("m7_decider_creneau_calendrier", owner=True, creneau_id=brouillon["creneau_id"],
                       decision="approuver", horodatage=_HORODATAGE)
    assert decision["accepte"] is False and decision["verdict"]["code"] == "REJ-CONTENU-PERIME"
    assert _lire("exports_paquet") == [] and _lire("exports_calendrier") == [] and _faits_exportes() == []
    assert {n: _lire(n) for n in historiques} == historiques  # l'audit reste intact, rien d'ajouté

    # La lecture ne présente plus l'ancien créneau comme remisable, sans rien écrire.
    vue = next(c for c in _valeur("m7_lister_calendrier", wct_id=charge["wct_id"])["creneaux"]
               if c["creneau_id"] == slot["creneau_id"])
    assert vue["statut"] == "CONTENU_NON_APPROUVE"
    assert {n: _lire(n) for n in historiques} == historiques

    # Contrôle positif : la révision courante, approuvée avec son propre créneau, se remet normalement.
    _valeur("m7_decider_contenu", owner=True, contenu_id=nouvelle_id, decision="approuver", horodatage=_HORODATAGE)
    slot_courant = _creneau_approuve(nouvelle_id)
    sortie = _valeur("m7_exporter_creneau_manuel", owner=True, creneau_id=slot_courant["creneau_id"],
                     horodatage=_HORODATAGE)
    assert sortie["paquet"]["texte"] == _NOUVEAU_TEXTE
    (export,) = _lire("exports_paquet")
    assert export["contenu_id"] == nouvelle_id
    assert [e["creneau_id"] for e in _lire("exports_calendrier")] == [slot_courant["creneau_id"]]
    assert len(_faits_exportes()) == 1


def test_paquet_deja_remis_puis_texte_corrige_n_est_plus_reemis(base_durable, brand_configure, owner, charge):
    ancienne = _approuver_facebook(charge)
    slot = _creneau_approuve(ancienne["contenu_id"])
    premiere = _valeur("m7_exporter_creneau_manuel", owner=True, creneau_id=slot["creneau_id"], horodatage=_HORODATAGE)
    assert premiere["deja_exporte"] is False
    # Contrôle positif avant correction : la réémission du même paquet reste idempotente.
    assert _valeur("m7_exporter_creneau_manuel", owner=True, creneau_id=slot["creneau_id"],
                   horodatage=_HORODATAGE)["deja_exporte"] is True
    _reviser_par_le_proprietaire(ancienne["contenu_id"])
    historiques = {n: _lire(n) for n in ("exports_paquet", "exports_calendrier")}
    faits = _faits_exportes()

    for nom, args in (
        ("m7_exporter_paquet_manuel", {"contenu_id": ancienne["contenu_id"]}),
        ("m7_exporter_creneau_manuel", {"creneau_id": slot["creneau_id"], "owner": True}),
    ):
        refus = _metier(nom, horodatage=_HORODATAGE, **args)
        assert refus["accepte"] is False and refus["verdict"]["code"] == "REJ-CONTENU-PERIME", (nom, refus)
    assert {n: _lire(n) for n in historiques} == historiques and _faits_exportes() == faits
