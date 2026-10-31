"""Bus d'événements du socle (ADR-0009 §3, PLAN T1.2-a) : `publier`, `repartir`, `etat`, catalogue,
cohérence des déclarations `department.yaml`. Aucun département réel n'est impliqué (T1.2-b à
T1.2-d) : les départements de démonstration de `tests/fixtures/departements` et des consommateurs
en mémoire (`dataclasses.replace`, patron déjà utilisé par `test_tableau_de_bord.py`) en tiennent
lieu, sans jamais toucher au manifeste partagé sur disque.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import shutil
import sys
from contextvars import copy_context
from decimal import Decimal

import demo_consommateur_echec
import demo_consommateur_ok
import pytest
import yaml
from sqlalchemy import func, select

from opsys import evenements, stockage
from opsys.outils import Outil, executer_atomique
from opsys.stockage.moteur import connexion_courante
from opsys.stockage.schema import EVENEMENTS_SORTANTS

_SCHEMA_ECHOUER = {"type": "object", "properties": {"echouer": {"type": "boolean"}}, "required": ["echouer"]}


@pytest.fixture(autouse=True)
def _reset_consommateurs_demo():
    demo_consommateur_ok.APPELS.clear()
    demo_consommateur_echec.TENTATIVES.clear()
    yield


@pytest.fixture
def deps_succes(departements_demo):
    base = departements_demo["m09-demo"]
    dep = dataclasses.replace(
        base, module_outils="demo_consommateur_ok",
        evenements_publie=("opsys.demo_complete",), evenements_consomme=("opsys.demo_complete",),
    )
    return {dep.id: dep}


@pytest.fixture
def deps_bus(departements_demo):
    """Deux consommateurs abonnés à `opsys.demo_complete` : un qui réussit toujours, un qui échoue
    toujours — pour vérifier qu'un consommateur en échec n'en bloque jamais un autre."""
    base = departements_demo["m09-demo"]
    succes = dataclasses.replace(
        base, module_outils="demo_consommateur_ok",
        evenements_publie=("opsys.demo_complete",), evenements_consomme=("opsys.demo_complete",),
    )
    echec = dataclasses.replace(
        base, id="m09-demo-echec", module_outils="demo_consommateur_echec",
        evenements_consomme=("opsys.demo_complete",),
    )
    return {succes.id: succes, echec.id: echec}


def _compte_sortants(where=None) -> int:
    requete = select(func.count()).select_from(EVENEMENTS_SORTANTS)
    if where is not None:
        requete = requete.where(where)
    with stockage.transaction() as cnx:
        return cnx.execute(requete).scalar_one()


# -- atomicité : écriture métier + événement, une seule transaction ----------------------------
def _ecrire_et_publier(echouer: bool) -> dict:
    stockage.maillons("m-demo-atomicite", "principal").append({"ecrit": True})
    evenements.publier("opsys.demo_complete", "m-demo-atomicite", {"message": "x"})
    if echouer:
        raise ValueError("refus métier après écriture et publication")
    return {"ok": True}


def test_atomicite_ecriture_et_evenement_annulees_ensemble(session):
    outil = Outil("m9_atomicite_demo", "Écrit un maillon et publie un événement, échoue au besoin.",
                  _SCHEMA_ECHOUER, _ecrire_et_publier)

    reponse = executer_atomique(outil, {"echouer": True})
    assert reponse["ok"] is False
    assert len(stockage.maillons("m-demo-atomicite", "principal")) == 0
    assert _compte_sortants() == 0

    reponse_ok = executer_atomique(outil, {"echouer": False})
    assert reponse_ok["ok"] is True
    assert len(stockage.maillons("m-demo-atomicite", "principal")) == 1
    assert _compte_sortants() == 1


# -- catalogue : type inconnu et charge invalide, aucune écriture ------------------------------
def test_catalogue_type_inconnu_rejete_sans_ecriture(session):
    with pytest.raises(evenements.TypeEvenementInconnu):
        evenements.publier("type.qui.nexiste.pas", "test", {"message": "x"})
    assert _compte_sortants() == 0


def test_catalogue_charge_invalide_rejetee_sans_ecriture(session):
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier("opsys.demo_complete", "test", {})  # "message" manquant
    assert _compte_sortants() == 0


# -- validation complète (JSON Schema 2020-12) : objets et tableaux imbriqués compris -------------
def _variance_evaluee(**overrides) -> dict:
    base = {
        "evenement_id": "m6-variance-wct-1-evaluee",
        "wct_id": "wct-1",
        "intervention_id": "int-1",
        "chantier_id": "ch-1",
        "statut_variance": "evaluee",
        "signal_critique": False,
        "seuil_pourcentage": 0.3,
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "lignes": [{
            "materiau": "gouttiere-5po", "unite": "pi", "quantite_prevue": "100",
            "quantite_reelle": "104", "ecart_pourcentage": "4.0", "critique": False,
        }],
    }
    base.update(overrides)
    return base


def _devis_accepte(**overrides) -> dict:
    base = {
        "devis_id": "devis-1",
        "lead_id": "lead-1",
        "chantier_id": "ch-1",
        "lignes": [{
            "reference_ligne": "devis-1-L0", "description": "Gouttière 5 po", "quantite": "4",
            "unite": "pi", "prix_unitaire": "19.38", "prix_ligne": "77.52",
            "reference_besoin_materiau": "gouttiere-5po",
        }],
        "cout_total": "62.00",
        "prix_total": "77.52",
        "taux_marge": "0.25",
        "horodatage_acceptation": "2026-09-20T10:00:00-04:00",
    }
    base.update(overrides)
    return base


def test_catalogue_schemas_sont_des_json_schema_valides():
    from jsonschema import Draft202012Validator

    for type_evenement in evenements.types_connus():
        Draft202012Validator.check_schema(evenements.schema(type_evenement))


def test_catalogue_accepte_des_charges_imbriquees_conformes(session):
    evenements.publier("m6.variance_chantier", "m06-material-control", _variance_evaluee())
    evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte())
    assert _compte_sortants() == 2


def test_catalogue_valide_les_elements_dun_tableau_imbrique(session):
    ligne_incomplete = dict(_variance_evaluee()["lignes"][0])
    del ligne_incomplete["critique"]
    with pytest.raises(evenements.ChargeInvalide, match="critique"):
        evenements.publier("m6.variance_chantier", "m06-material-control",
                           _variance_evaluee(lignes=[ligne_incomplete]))
    assert _compte_sortants() == 0


def test_catalogue_m3_devis_accepte_refuse_un_cout_par_ligne(session):
    """Séparation coût/prix (audit M3) : le coût d'une ligne ne sort jamais de M3 par le bus."""
    ligne = dict(_devis_accepte()["lignes"][0], cout_unitaire="15.50")
    with pytest.raises(evenements.ChargeInvalide, match="cout_unitaire"):
        evenements.publier("m3.devis_accepte", "m03-estimation", _devis_accepte(lignes=[ligne]))
    assert _compte_sortants() == 0


# -- catalogue m4.travaux_termines : le WCT réel de M4 (outbox.py::CHAMPS_WCT), plus les champs
# optionnels M5/M7 (audits) -- voir src/opsys/evenements/catalogue/m4.travaux_termines.json.
def _wct_exemple(**overrides) -> dict:
    base = {
        "wct_id": "wct-abc123",
        "intervention_id": "int-1",
        "lead_id": "lead-1",
        "technicien_id": "tech-1",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 120,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"],
        "devis_id": "devis-1",
        "statut": "completed_verified",
    }
    base.update(overrides)
    return base


def test_catalogue_m4_travaux_termines_accepte_un_wct_valide(session):
    assert evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_exemple())


def test_catalogue_m4_travaux_termines_accepte_les_champs_optionnels_m7(session):
    charge = _wct_exemple(
        ville="Repentigny", type_travaux="gouttières", photos=["chantier-1.jpg"],
        description_factuelle="Installation de gouttières en aluminium.",
        consentement_marketing=True, client_satisfait=True,
    )
    assert evenements.publier("m4.travaux_termines", "m04-field-ops", charge)


def test_catalogue_m4_travaux_termines_accepte_le_consentement_a_la_demande_d_avis_et_sa_preuve(session):
    """PLAN T1.5-d : clés additives, optionnelles, jamais requises ; `consentement_marketing` reste distinct."""
    charge = _wct_exemple(
        consentement_demande_avis=True, consentement_marketing=False,
        consentement_recueilli_par="etienne", consentement_recueilli_le="2026-09-28T18:05:00+00:00",
        consentement_version_texte="consentement-client-fr-CA-v1",
    )
    assert evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    requis = set(evenements.schema("m4.travaux_termines")["required"])
    assert not requis & {"consentement_demande_avis", "consentement_recueilli_par",
                         "consentement_recueilli_le", "consentement_version_texte"}


@pytest.mark.parametrize("cle,mauvaise_valeur", [
    ("consentement_demande_avis", "oui"),
    ("consentement_demande_avis", None),
    ("consentement_recueilli_par", 7),
    ("consentement_recueilli_le", 1748864105),
    ("consentement_version_texte", ["v1"]),
])
def test_catalogue_m4_travaux_termines_rejette_un_consentement_ou_une_preuve_mal_types(session, cle, mauvaise_valeur):
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_exemple(**{cle: mauvaise_valeur}))
    assert _compte_sortants() == 0


def test_catalogue_m4_travaux_termines_accepte_devis_et_revue_absents(session):
    # devis_id et revue_id sont requis mais nullables (outbox.py : None si sans devis / sans écart).
    assert evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_exemple(devis_id=None, revue_id="rev-1"))


@pytest.mark.parametrize(
    "modification",
    [
        lambda c: c.pop("duree_reelle_minutes"),
        lambda c: c.pop("devis_id"),  # requis (même si nullable) : absent, pas seulement null
        lambda c: c.update(statut="termine"),  # ancien statut, remplacé par T1.1-b
        lambda c: c.update(champ_invente="x"),
    ],
)
def test_catalogue_m4_travaux_termines_rejette_un_wct_invalide(session, modification):
    charge = _wct_exemple()
    modification(charge)
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    assert _compte_sortants() == 0


# -- idempotence -----------------------------------------------------------------------------
def test_idempotence_evenement_id_fourni_deux_fois(session):
    id1 = evenements.publier("opsys.demo_complete", "test", {"message": "a"}, evenement_id="fixe-1")
    id2 = evenements.publier("opsys.demo_complete", "test", {"message": "a"}, evenement_id="fixe-1")
    assert id1 == id2 == "fixe-1"
    assert _compte_sortants(EVENEMENTS_SORTANTS.c.evenement_id == "fixe-1") == 1


def _publication_fictive_atomique(type_evenement, producteur, charge):
    stockage.maillons("m-demo-conflit-publication", "principal").append({
        "fictif": True, "type_evenement": type_evenement, "producteur": producteur, "charge": charge,
    })
    ident = evenements.publier(type_evenement, producteur, charge, evenement_id="fictif-enveloppe-fixe")
    return {"fictif": True, "evenement_id": ident}


def _outil_publication_fictive():
    return Outil("m9_publication_fictive", "Qualification fictive de l'atomicité de publication", {
        "type": "object", "properties": {
            "type_evenement": {"type": "string"}, "producteur": {"type": "string"},
            "charge": {"type": "object"},
        }, "required": ["type_evenement", "producteur", "charge"],
    }, _publication_fictive_atomique)


@pytest.mark.parametrize("difference", ["charge", "producteur", "type_evenement"])
def test_conflit_enveloppe_annule_ecriture_metier_apres_reouverture(session, difference):
    from opsys.stockage import codec

    original = {
        "type_evenement": "opsys.demo_complete", "producteur": "m-demo-fictif",
        "charge": {"message": "A-fictif-prive"},
    }
    outil = _outil_publication_fictive()
    assert executer_atomique(outil, original)["ok"] is True
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(EVENEMENTS_SORTANTS)).mappings().one()
    autre = {**original, "charge": dict(original["charge"])}
    if difference == "charge":
        autre["charge"] = {"message": "B-fictif-prive"}
    elif difference == "producteur":
        autre["producteur"] = "m-demo-autre-fictif"
    else:
        autre["type_evenement"] = "m4.travaux_termines"
        autre["charge"] = _wct_exemple()
    reponse = executer_atomique(outil, autre)
    stockage.liberer()
    assert reponse["ok"] is False
    assert reponse["erreur"] == "refus_metier"
    assert "conflit" in reponse["details"].lower()
    assert "fictif-enveloppe-fixe" in reponse["details"]
    assert "A-fictif-prive" not in reponse["details"]
    assert "B-fictif-prive" not in reponse["details"]
    assert list(stockage.maillons("m-demo-conflit-publication", "principal")) == [
        {"fictif": True, **original},
    ]
    with stockage.transaction() as cnx:
        apres = cnx.execute(select(EVENEMENTS_SORTANTS)).mappings().one()
    assert dict(apres) == dict(avant)
    assert codec.decoder(apres["charge"]) == original["charge"]


def test_rejeu_enveloppe_identique_preserve_evenement_sans_dedupliquer_metier(session):
    original = {
        "type_evenement": "opsys.demo_complete", "producteur": "m-demo-fictif",
        "charge": {"message": "rejeu-fictif"},
    }
    outil = _outil_publication_fictive()
    assert executer_atomique(outil, original)["ok"] is True
    with stockage.transaction() as cnx:
        avant = dict(cnx.execute(select(EVENEMENTS_SORTANTS)).mappings().one())
    assert executer_atomique(outil, original)["ok"] is True
    stockage.liberer()
    assert len(stockage.maillons("m-demo-conflit-publication", "principal")) == 2
    with stockage.transaction() as cnx:
        assert dict(cnx.execute(select(EVENEMENTS_SORTANTS)).mappings().one()) == avant


def test_deja_publie_reflete_la_table_du_bus(session):
    assert evenements.deja_publie("fixe-2") is False
    evenements.publier("opsys.demo_complete", "test", {"message": "a"}, evenement_id="fixe-2")
    assert evenements.deja_publie("fixe-2") is True
    assert evenements.deja_publie("fixe-3") is False


def test_rejeu_ignore_ordre_cles_mais_conserve_tableaux_et_premiere_date(session):
    charge = _wct_exemple()
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="ordre-fictif")
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(EVENEMENTS_SORTANTS)).one()
    reordonnee = dict(reversed(list(charge.items())))
    reordonnee["fix_gps_completion"] = dict(reversed(list(charge["fix_gps_completion"].items())))
    assert evenements.publier(
        "m4.travaux_termines", "m04-field-ops", reordonnee, evenement_id="ordre-fictif",
    ) == "ordre-fictif"
    reordonnee["consommateurs_cibles"] = list(reversed(charge["consommateurs_cibles"]))
    with pytest.raises(evenements.ConflitPublication, match="charge"):
        evenements.publier("m4.travaux_termines", "m04-field-ops", reordonnee, evenement_id="ordre-fictif")
    stockage.liberer()
    with stockage.transaction() as cnx:
        assert cnx.execute(select(EVENEMENTS_SORTANTS)).one() == avant


@pytest.mark.parametrize("premier,second", [(120, 120.0), (Decimal("120.0"), Decimal("120.00"))])
def test_rejeu_ne_confond_pas_representations_numeriques_valides(session, premier, second):
    assert premier == second  # Python equality alone would accept the conflicting envelope.
    charge = _wct_exemple()
    charge["fix_gps_completion"]["longitude"] = premier
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="nombre-fictif")
    relue = evenements.charge_publiee("m4.travaux_termines", "nombre-fictif")
    evenements.publier("m4.travaux_termines", "m04-field-ops", relue, evenement_id="nombre-fictif")
    charge["fix_gps_completion"]["longitude"] = second
    with pytest.raises(evenements.ConflitPublication, match="charge"):
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id="nombre-fictif")


# -- charge_publiee : relit la charge dans le magasin du bus, jamais une copie ------------------------
def test_charge_publiee_rend_la_charge_publiee_telle_quelle(session):
    charge = _wct_exemple(ville="Repentigny", photos=["chantier-1.jpg"], type_travaux="gouttières")
    evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=charge["wct_id"])

    relue = evenements.charge_publiee("m4.travaux_termines", charge["wct_id"])

    assert relue == charge  # objets et tableaux imbriqués compris (fix_gps_completion, photos)


def test_charge_publiee_inconnue_rend_none(session):
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_exemple(), evenement_id="wct-abc123")

    assert evenements.charge_publiee("m4.travaux_termines", "wct-jamais-publie") is None


def test_charge_publiee_ne_rend_jamais_la_charge_d_un_autre_type(session):
    # L'id existe, mais pour `opsys.demo_complete` : demander ce même id comme un WCT n'en donne rien.
    evenements.publier("opsys.demo_complete", "test", {"message": "a"}, evenement_id="partage-1")

    assert evenements.charge_publiee("m4.travaux_termines", "partage-1") is None
    assert evenements.charge_publiee("opsys.demo_complete", "partage-1") == {"message": "a"}


def test_charge_publiee_type_hors_catalogue_est_une_erreur_de_programmation(session):
    with pytest.raises(evenements.TypeEvenementInconnu):
        evenements.charge_publiee("type.qui.nexiste.pas", "n-importe-quoi")


def test_charge_publiee_est_decodee_a_chaque_appel_et_n_ecrit_rien(session):
    evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_exemple(), evenement_id="wct-abc123")
    avant = _compte_sortants()

    premiere = evenements.charge_publiee("m4.travaux_termines", "wct-abc123")
    premiere["fix_gps_completion"]["latitude"] = 0.0  # un appelant qui abîme sa copie...
    premiere["devis_id"] = "devis-forge"

    seconde = evenements.charge_publiee("m4.travaux_termines", "wct-abc123")
    assert seconde["fix_gps_completion"]["latitude"] == 45.75  # ...n'abîme jamais le bus
    assert seconde["devis_id"] == "devis-1"
    assert _compte_sortants() == avant


def _publier_puis_relire_dans_l_outil(echouer: bool) -> dict:
    evenements.publier("opsys.demo_complete", "m-demo-lecture", {"message": "vu"}, evenement_id="lu-dans-tx")
    assert evenements.charge_publiee("opsys.demo_complete", "lu-dans-tx") == {"message": "vu"}
    if echouer:
        raise ValueError("refus métier après publication")
    return {"ok": True}


def test_charge_publiee_lit_dans_la_transaction_courante(session):
    outil = Outil("m9_lecture_demo", "Publie puis relit un événement dans la même transaction.",
                  _SCHEMA_ECHOUER, _publier_puis_relire_dans_l_outil)

    # Dans l'outil, la charge non commitée est visible ; si l'outil échoue, elle disparaît avec lui.
    assert executer_atomique(outil, {"echouer": True})["ok"] is False
    assert evenements.charge_publiee("opsys.demo_complete", "lu-dans-tx") is None

    assert executer_atomique(outil, {"echouer": False})["ok"] is True
    assert evenements.charge_publiee("opsys.demo_complete", "lu-dans-tx") == {"message": "vu"}


def test_idempotence_evenement_id_par_defaut_est_unique(session):
    id1 = evenements.publier("opsys.demo_complete", "test", {"message": "a"})
    id2 = evenements.publier("opsys.demo_complete", "test", {"message": "b"})
    assert id1 != id2
    assert _compte_sortants() == 2


def test_heure_de_livraison_est_bornee_a_la_paire_meme_en_cas_d_echec(session, deps_succes, monkeypatch):
    from opsys.evenements.repartiteur import horodatage_livraison

    instants = []

    def recevoir(_charge):
        instants.append(horodatage_livraison().isoformat())
        if len(instants) == 1:
            raise ValueError("echec fictif")
        return {"ok": True}

    monkeypatch.setattr(demo_consommateur_ok, "consommateurs", lambda: {"opsys.demo_complete": recevoir})
    evenements.publier("opsys.demo_complete", "test", {"message": "heure"})
    assert horodatage_livraison() is None
    assert evenements.repartir(deps_succes, maintenant="2026-09-28T00:00:00+00:00")["echecs"] == 1
    assert horodatage_livraison() is None
    assert evenements.repartir(deps_succes, maintenant="2026-09-28T00:01:00+00:00")["traites"] == 1
    assert instants == ["2026-09-28T00:00:00+00:00", "2026-09-28T00:01:00+00:00"]
    assert horodatage_livraison() is None


def test_redelivery_ne_reexecute_jamais_un_evenement_traite(session, deps_succes):
    evenements.publier("opsys.demo_complete", "test", {"message": "une-fois"})

    resume1 = evenements.repartir(deps_succes, maintenant="2026-09-28T00:00:00+00:00")
    assert resume1 == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert demo_consommateur_ok.APPELS == ["une-fois"]

    resume2 = evenements.repartir(deps_succes, maintenant="2026-09-28T01:00:00+00:00")
    assert resume2 == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert demo_consommateur_ok.APPELS == ["une-fois"]  # jamais rejoué

    etat = evenements.etat()
    assert etat["comptes"] == {"traite": 1}
    assert etat["quarantaine"] == []


def test_reentree_meme_paire_ne_duplique_pas_effet_apres_reouverture(session, deps_succes, monkeypatch):
    appels = []
    resumes_imbriques = []

    def recevoir(charge):
        appels.append(charge["message"])
        if len(appels) == 1:
            resumes_imbriques.append(evenements.repartir(deps_succes))
        stockage.maillons("m-demo-reentree", "recus").append({"fictif": True, "message": charge["message"]})
        return {"fictif": True}

    monkeypatch.setattr(demo_consommateur_ok, "consommateurs", lambda: {"opsys.demo_complete": recevoir})
    evenements.publier("opsys.demo_complete", "test-fictif", {"message": "unique"}, evenement_id="reentrant-1")

    assert evenements.repartir(deps_succes)["traites"] == 1
    stockage.liberer()
    assert len(stockage.maillons("m-demo-reentree", "recus")) == 1
    assert appels == ["unique"]
    assert resumes_imbriques == [{"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 1}]
    assert evenements.etat()["comptes"] == {"traite": 1}
    assert _compte_sortants() == 1
    assert evenements.repartir(deps_succes)["livres"] == 0


def test_reentree_autre_evenement_meme_consommateur_progresse(session, deps_succes, monkeypatch):
    appels = []
    resumes_imbriques = []

    def recevoir(charge):
        appels.append(charge["message"])
        if len(appels) == 1:
            resumes_imbriques.append(evenements.repartir(deps_succes))
        stockage.maillons("m-demo-autre-evenement", "recus").append({"fictif": True, "message": charge["message"]})
        return {"fictif": True}

    monkeypatch.setattr(demo_consommateur_ok, "consommateurs", lambda: {"opsys.demo_complete": recevoir})
    for message in ("premier", "second"):
        evenements.publier("opsys.demo_complete", "test-fictif", {"message": message}, evenement_id=message)

    assert evenements.repartir(deps_succes)["traites"] == 1
    assert appels == ["premier", "second"]
    assert resumes_imbriques == [{"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 1}]
    assert len(stockage.maillons("m-demo-autre-evenement", "recus")) == 2
    assert evenements.etat()["comptes"] == {"traite": 2}


def test_reentree_contexte_capture_meme_connexion_ne_duplique_pas(session, deps_succes, monkeypatch):
    appels = []
    connexions = []

    def recevoir(charge):
        appels.append(charge["message"])
        with stockage.transaction() as cnx:
            connexions.append(cnx)
        if len(appels) == 1:
            contexte.run(evenements.repartir, deps_succes)
        stockage.maillons("m-demo-contexte-reentree", "recus").append({"fictif": True})
        return {"fictif": True}

    monkeypatch.setattr(demo_consommateur_ok, "consommateurs", lambda: {"opsys.demo_complete": recevoir})
    evenements.publier("opsys.demo_complete", "test-fictif", {"message": "contexte-capture"})
    with stockage.transaction() as native:
        contexte = copy_context()
        assert evenements.repartir(deps_succes)["traites"] == 1
        assert all(cnx is native for cnx in connexions)

    stockage.liberer()
    assert len(stockage.maillons("m-demo-contexte-reentree", "recus")) == 1
    assert appels == ["contexte-capture"]
    assert evenements.etat()["comptes"] == {"traite": 1}


def test_reentree_meme_evenement_autre_consommateur_progresse(session, deps_succes, monkeypatch):
    appels = []
    resumes_imbriques = []
    autre = dataclasses.replace(
        next(iter(deps_succes.values())), id="m09-demo-autre", module_outils="demo_consommateur_echec",
    )
    deps = {**deps_succes, autre.id: autre}

    def recevoir(charge):
        appels.append("premier")
        if len(appels) == 1:
            resumes_imbriques.append(evenements.repartir(deps))
        stockage.maillons("m-demo-autre-consommateur", "premier").append({"fictif": True})
        return {"fictif": True}

    def recevoir_autre(charge):
        appels.append("autre")
        stockage.maillons("m-demo-autre-consommateur", "autre").append({"fictif": True})
        return {"fictif": True}

    monkeypatch.setattr(demo_consommateur_ok, "consommateurs", lambda: {"opsys.demo_complete": recevoir})
    monkeypatch.setattr(demo_consommateur_echec, "consommateurs", lambda: {"opsys.demo_complete": recevoir_autre})
    evenements.publier("opsys.demo_complete", "test-fictif", {"message": "deux-consommateurs"})

    assert evenements.repartir(deps)["traites"] == 1
    assert appels == ["premier", "autre"]
    assert resumes_imbriques == [{"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 1}]
    assert len(stockage.maillons("m-demo-autre-consommateur", "premier")) == 1
    assert len(stockage.maillons("m-demo-autre-consommateur", "autre")) == 1
    assert evenements.etat()["comptes"] == {"traite": 2}


@pytest.mark.parametrize("interruption", [RuntimeError, BaseException], ids=["echec", "baseexception"])
def test_reentree_exception_nettoie_paire_et_reessai_meme_connexion(session, deps_succes, monkeypatch, interruption):
    connexions = []
    resumes_imbriques = []
    t0 = dt.datetime(2026, 9, 28, tzinfo=dt.UTC)

    def recevoir(charge):
        with stockage.transaction() as cnx:
            connexions.append(cnx)
        if len(connexions) == 1:
            resumes_imbriques.append(evenements.repartir(deps_succes, maintenant=t0.isoformat()))
        stockage.maillons("m-demo-reprise", "recus").append({"fictif": True})
        if len(connexions) == 1:
            raise interruption("interruption fictive après écriture")
        return {"fictif": True}

    monkeypatch.setattr(demo_consommateur_ok, "consommateurs", lambda: {"opsys.demo_complete": recevoir})
    evenements.publier("opsys.demo_complete", "test-fictif", {"message": "reprise"})

    with stockage.transaction() as cnx:
        if interruption is BaseException:
            with pytest.raises(BaseException, match="interruption fictive"):
                evenements.repartir(deps_succes, maintenant=t0.isoformat())
            assert evenements.etat()["comptes"] == {}
        else:
            assert evenements.repartir(deps_succes, maintenant=t0.isoformat())["echecs"] == 1
            assert evenements.etat()["comptes"] == {"echec": 1}
            assert evenements.repartir(deps_succes, maintenant=t0.isoformat())["livres"] == 0
        assert len(stockage.maillons("m-demo-reprise", "recus")) == 0
        assert evenements.repartir(deps_succes, maintenant=(t0 + dt.timedelta(seconds=3)).isoformat())["traites"] == 1
        assert connexions == [cnx, cnx]

    assert resumes_imbriques == [{"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 1}]
    stockage.liberer()
    assert len(stockage.maillons("m-demo-reprise", "recus")) == 1
    assert evenements.etat()["comptes"] == {"traite": 1}


def test_reentree_rollback_exterieur_et_connexion_reprise_du_pool(session, deps_succes, monkeypatch):
    connexions = []
    pilotes = []
    infos = []

    def recevoir(charge):
        with stockage.transaction() as cnx:
            connexions.append(cnx)
            pilotes.append(cnx.connection.dbapi_connection)
            infos.append(cnx.info)
        evenements.repartir(deps_succes)
        stockage.maillons("m-demo-rollback-reentree", "recus").append({"fictif": True})
        return {"fictif": True}

    monkeypatch.setattr(demo_consommateur_ok, "consommateurs", lambda: {"opsys.demo_complete": recevoir})
    evenements.publier("opsys.demo_complete", "test-fictif", {"message": "rollback"})

    with pytest.raises(ValueError, match="rollback extérieur fictif"), stockage.transaction():
        assert evenements.repartir(deps_succes)["traites"] == 1
        raise ValueError("rollback extérieur fictif")

    assert len(stockage.maillons("m-demo-rollback-reentree", "recus")) == 0
    assert evenements.etat()["comptes"] == {}
    assert _compte_sortants() == 1
    assert evenements.repartir(deps_succes)["traites"] == 1
    assert connexions[0] is not connexions[1]
    assert pilotes[0] is pilotes[1]
    assert infos[0] is infos[1]
    stockage.liberer()
    assert len(stockage.maillons("m-demo-rollback-reentree", "recus")) == 1
    assert evenements.etat()["comptes"] == {"traite": 1}


@pytest.mark.parametrize("arreter", ["close", "invalidate"])
def test_connexion_arretee_ne_masque_pas_baseexception_et_permet_reprise(session, deps_succes, monkeypatch, arreter):
    interruption = BaseException("interruption fictive après arrêt de connexion")
    connexions = []

    def recevoir(charge):
        native = connexion_courante()
        assert native is not None
        connexions.append(native)
        stockage.maillons("m-demo-arret-connexion", "recus").append({"fictif": True})
        if len(connexions) == 1:
            getattr(native, arreter)()
            raise interruption
        return {"fictif": True}

    monkeypatch.setattr(demo_consommateur_ok, "consommateurs", lambda: {"opsys.demo_complete": recevoir})
    evenements.publier("opsys.demo_complete", "test-fictif", {"message": "arret-connexion"})

    with pytest.raises(BaseException) as levee:
        evenements.repartir(deps_succes)
    assert levee.value is interruption
    assert len(stockage.maillons("m-demo-arret-connexion", "recus")) == 0
    assert evenements.etat()["comptes"] == {}
    assert _compte_sortants() == 1
    assert evenements.repartir(deps_succes)["traites"] == 1
    assert len(connexions) == 2
    stockage.liberer()
    assert len(stockage.maillons("m-demo-arret-connexion", "recus")) == 1
    assert evenements.etat()["comptes"] == {"traite": 1}


def test_interruption_reservation_ne_retient_pas_connexion_native(session, deps_succes, monkeypatch):
    interruption = BaseException("interruption fictive pendant réservation")
    appels = []
    stockage_connexion = []

    def recevoir(charge):
        appels.append(charge["message"])
        stockage.maillons("m-demo-reservation-interrompue", "recus").append({"fictif": True})
        return {"fictif": True}

    def interrompre(frame, evenement, arg):
        if (
            evenement == "line"
            and frame.f_code.co_filename == evenements.repartir.__code__.co_filename
            and frame.f_code.co_name == "_livrer_une_paire"
        ):
            native = connexion_courante()
            if native is not None:
                references = [v for v in native.info.values() if isinstance(v, dict) and native in v]
                if references:
                    stockage_connexion.extend(references)
                    raise interruption
        return interrompre

    monkeypatch.setattr(demo_consommateur_ok, "consommateurs", lambda: {"opsys.demo_complete": recevoir})
    evenements.publier("opsys.demo_complete", "test-fictif", {"message": "reservation"})
    with stockage.transaction() as native:
        precedent = sys.gettrace()
        try:
            sys.settrace(interrompre)
            with pytest.raises(BaseException) as levee:
                evenements.repartir(deps_succes)
        finally:
            sys.settrace(precedent)
        assert levee.value is interruption
        assert appels == []
        assert stockage_connexion
        assert all(native not in dico for dico in stockage_connexion)
        assert evenements.repartir(deps_succes)["traites"] == 1

    assert appels == ["reservation"]
    assert len(stockage.maillons("m-demo-reservation-interrompue", "recus")) == 1


# -- consommateur en échec : réessais espacés, quarantaine, isolation --------------------------
def test_consommateur_en_echec_reessais_espaces_puis_quarantaine(session, deps_bus):
    evenements.publier("opsys.demo_complete", "test", {"message": "echoue"})
    t0 = dt.datetime(2026, 9, 28, tzinfo=dt.UTC)

    # tentative 1 : le consommateur qui réussit est traité malgré l'échec de l'autre (isolation)
    resume = evenements.repartir(deps_bus, maintenant=t0.isoformat())
    assert resume == {"livres": 2, "traites": 1, "echecs": 1, "quarantaines": 0, "ignores": 0}
    assert demo_consommateur_ok.APPELS == ["echoue"]
    assert len(demo_consommateur_echec.TENTATIVES) == 1

    # relivraison immédiate : le second n'est pas encore dû (backoff), rien de neuf à faire
    resume_immediat = evenements.repartir(deps_bus, maintenant=t0.isoformat())
    assert resume_immediat == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}

    # tentatives 2 à 4 : toujours en échec, jamais bloquantes pour le reste
    t = t0
    for _ in range(3):
        t += dt.timedelta(seconds=100)  # au-delà du plus grand backoff possible (2**4 = 16 s)
        r = evenements.repartir(deps_bus, maintenant=t.isoformat())
        assert r == {"livres": 1, "traites": 0, "echecs": 1, "quarantaines": 0, "ignores": 0}

    # tentative 5 : quarantaine
    t += dt.timedelta(seconds=100)
    r5 = evenements.repartir(deps_bus, maintenant=t.isoformat())
    assert r5 == {"livres": 1, "traites": 0, "echecs": 0, "quarantaines": 1, "ignores": 0}
    assert len(demo_consommateur_echec.TENTATIVES) == 5

    # plus aucune relivraison automatique une fois en quarantaine
    t += dt.timedelta(seconds=10_000)
    r_apres = evenements.repartir(deps_bus, maintenant=t.isoformat())
    assert r_apres == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert len(demo_consommateur_echec.TENTATIVES) == 5  # pas de 6e appel

    # les écritures du consommateur en échec sont annulées à CHAQUE tentative
    assert len(stockage.maillons("m-demo-evenements-echec", "recus")) == 0
    # le consommateur qui réussit, lui, reste acquis (une seule fois)
    assert len(stockage.maillons("m-demo-evenements-ok", "recus")) == 1

    etat = evenements.etat()
    assert etat["comptes"] == {"traite": 1, "quarantaine": 1}
    assert len(etat["quarantaine"]) == 1
    ligne = etat["quarantaine"][0]
    assert ligne["consommateur"] == "m09-demo-echec"
    assert ligne["tentatives"] == 5
    assert "RuntimeError" in ligne["derniere_erreur"]


# -- verifier_coherence : cohérence des déclarations department.yaml/evenements ----------------
def test_verifier_coherence_type_absent_du_catalogue(departements_demo):
    base = departements_demo["m09-demo"]
    dep = dataclasses.replace(base, evenements_consomme=("type.bidon",), module_outils="demo_consommateur_ok")
    problemes = evenements.verifier_coherence({dep.id: dep})
    assert any("absent du catalogue" in p for p in problemes)


def test_verifier_coherence_type_consomme_sans_fonction(departements_demo):
    base = departements_demo["m09-demo"]
    # demo_consommateur_ok ne fournit une fonction que pour "opsys.demo_complete" : déclarer aussi
    # "m4.travaux_termines" (un type réel du catalogue) sans fonction assortie doit être détecté,
    # distinctement d'un type absent du catalogue.
    dep = dataclasses.replace(
        base, module_outils="demo_consommateur_ok",
        evenements_consomme=("opsys.demo_complete", "m4.travaux_termines"),
    )
    problemes = evenements.verifier_coherence({dep.id: dep})
    assert any("m4.travaux_termines" in p and "sans fonction" in p for p in problemes)
    assert not any("absent du catalogue" in p for p in problemes)


def test_verifier_coherence_fonction_orpheline(departements_demo):
    base = departements_demo["m09-demo"]
    dep = dataclasses.replace(
        base, module_outils="demo_consommateur_ok",
        evenements_publie=("opsys.demo_complete",), evenements_consomme=(),
    )
    problemes = evenements.verifier_coherence({dep.id: dep})
    assert any("orpheline" in p for p in problemes)


def test_verifier_coherence_declaration_coherente_ne_signale_rien(departements_demo):
    base = departements_demo["m09-demo"]
    dep = dataclasses.replace(
        base, module_outils="demo_consommateur_ok",
        evenements_publie=("opsys.demo_complete",), evenements_consomme=("opsys.demo_complete",),
    )
    assert evenements.verifier_coherence({dep.id: dep}) == []


def test_verifier_coherence_ignore_departement_hors_du_bus(departements_demo):
    base = departements_demo["m09-demo"]
    assert evenements.verifier_coherence({base.id: base}) == []


# -- CLI : opsys-metier verifier et opsys-metier evenements etat|repartir -------------------------------------
def _manifeste_avec_evenements(racine_demo, tmp_path, evenements_section: dict):
    cible = tmp_path / "departements"
    shutil.copytree(racine_demo, cible)
    manifeste = cible / "m09-demo" / "department.yaml"
    donnees = yaml.safe_load(manifeste.read_text(encoding="utf-8"))
    donnees["evenements"] = evenements_section
    manifeste.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    return cible


def test_cli_verifier_detecte_une_declaration_incoherente(racine_demo, tmp_path, monkeypatch, capsys):
    from opsys import cli

    cible = _manifeste_avec_evenements(racine_demo, tmp_path, {"consomme": ["type.bidon.inexistant"]})
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(cible))
    assert cli.main(["verifier"]) == 1
    assert "absent du catalogue" in capsys.readouterr().err


def test_cli_verifier_accepte_une_declaration_coherente(racine_demo, tmp_path, monkeypatch, capsys):
    from opsys import cli

    cible = _manifeste_avec_evenements(
        racine_demo, tmp_path, {"publie": ["opsys.demo_complete"], "consomme": ["opsys.demo_complete"]}
    )
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(cible))
    assert cli.main(["verifier"]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_evenements_etat_et_repartir(opsys_home, racine_demo, monkeypatch, capsys):
    import json

    from opsys import cli
    from opsys import stockage as stockage_cli

    # m09-demo, non modifié : evenements.consomme est vide, donc rien n'y est abonné ici.
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine_demo))
    stockage_cli.migrer()
    try:
        evenements.publier("opsys.demo_complete", "test", {"message": "cli"})
        assert cli.main(["evenements", "etat"]) == 0
        etat_initial = json.loads(capsys.readouterr().out)
        assert etat_initial == {"comptes": {}, "quarantaine": []}  # aucun département n'y est abonné ici

        assert cli.main(["evenements", "repartir"]) == 0
        resume = json.loads(capsys.readouterr().out)
        assert resume == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    finally:
        stockage_cli.liberer()


# -- serveur : boucle de fond, arrêt propre, désactivable -------------------------------------
_JETON_TEST = "jeton-de-test-suffisamment-long-0123456789"


def test_serveur_boucle_repartiteur_appelle_repartir_et_s_arrete_proprement(departements_demo, session, monkeypatch):
    import time

    from starlette.testclient import TestClient

    from opsys.serveur_mcp import application_http_departements

    appels: list[int] = []
    monkeypatch.setattr(evenements, "repartir", lambda deps: appels.append(1) or {})
    monkeypatch.delenv("OPSYS_EVENEMENTS_REPARTITEUR", raising=False)

    app = application_http_departements(departements_demo, session, _JETON_TEST, hote="127.0.0.1")
    with TestClient(app):
        for _ in range(100):
            if appels:
                break
            time.sleep(0.02)
    assert appels  # au moins un tour avant même le premier sommeil de 3 s (arrêt propre : pas de blocage)


def test_serveur_boucle_repartiteur_desactivable_par_variable_environnement(departements_demo, session, monkeypatch):
    import time

    from starlette.testclient import TestClient

    from opsys.serveur_mcp import application_http_departements

    appels: list[int] = []
    monkeypatch.setattr(evenements, "repartir", lambda deps: appels.append(1) or {})
    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")

    app = application_http_departements(departements_demo, session, _JETON_TEST, hote="127.0.0.1")
    with TestClient(app):
        time.sleep(0.3)  # bien en deçà de l'intervalle de 3 s : rien ne doit s'être produit
    assert appels == []


# -- parité PostgreSQL -----------------------------------------------------------------------
def test_postgresql_bus_evenements_se_comporte_comme_sqlite(monkeypatch, deps_bus):
    from memoire.doubles import postgres_ephemere, raison_sans_docker

    raison = raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)

    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)

            id1 = evenements.publier("opsys.demo_complete", "test", {"message": "pg"}, evenement_id="pg-1")
            id2 = evenements.publier("opsys.demo_complete", "test", {"message": "pg"}, evenement_id="pg-1")
            assert id1 == id2 == "pg-1"
            assert _compte_sortants(EVENEMENTS_SORTANTS.c.evenement_id == "pg-1") == 1

            with pytest.raises(evenements.TypeEvenementInconnu):
                evenements.publier("type.bidon", "test", {})
            with pytest.raises(evenements.ChargeInvalide):
                evenements.publier("opsys.demo_complete", "test", {})

            t0 = dt.datetime(2026, 9, 28, tzinfo=dt.UTC)
            resume = evenements.repartir(deps_bus, maintenant=t0.isoformat())
            assert resume == {"livres": 2, "traites": 1, "echecs": 1, "quarantaines": 0, "ignores": 0}
            resume_immediat = evenements.repartir(deps_bus, maintenant=t0.isoformat())
            assert resume_immediat == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
            assert demo_consommateur_ok.APPELS == ["pg"]
            assert len(stockage.maillons("m-demo-evenements-echec", "recus")) == 0

            etat = evenements.etat()
            assert etat["comptes"] == {"traite": 1, "echec": 1}
        finally:
            stockage.liberer()
