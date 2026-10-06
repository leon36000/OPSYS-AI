"""PLAN T1.4-k, de bout en bout : la personne authentifiée d'un appel d'appareil traverse
`Capacites.appeler` (mode `ombre` réel, validation humaine au départ de T1.4-h) jusque dans M4 et M6,
qui n'en croient plus les arguments.

Les tests par outil et par refus sont dans les départements (`departments/m04-field-ops/tests/
test_acces_par_intervention.py`, `departments/m06-material-control/tests/test_acces_declaration.py`) ;
ici on prouve la CHAÎNE : identité du `_meta` MCP -> `contexte.appele_par_appareil` -> outil -> refus
nommé ou exécution, avec la trace que T1.4-h écrit. Vrais manifestes, vrais outils, vraies personnes ;
données fictives (AGENTS.md).
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import struct
import zlib
from pathlib import Path

import anyio
import pytest
from m4_field_ops import cedule, consentement, etats
from m4_field_ops import registre as registre_m4
from mcp import Client

from opsys import approbations, contexte, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.serveur_mcp import creer_serveur

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[1] / "departments"
DEPARTEMENTS_TESTES = {"m03-estimation", "m04-field-ops", "m06-material-control"}

MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
LEA = contexte.IdentiteAppelante(personne="lea.fictif", role="employee")

SEL = "sel-t1-4-k-fictif"
VILLE = "Montreal"
FIX_GPS = {"latitude": 45.508812, "longitude": -73.587834}
ATTESTATION = {"fictif": True, "appareil_id": "APP-T1-4-K-FICTIF"}
FENETRE_2025 = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}

CODE_NON_ASSIGNEE = "REJ-INTERVENTION-NON-ASSIGNEE"
CODE_IDENTITE_FOURNIE = "REJ-IDENTITE-FOURNIE-DIFFERENTE"


@pytest.fixture
def capacites(session, nathan):
    """Vrais départements M3/M4/M6 (mode `ombre` de leur manifeste), base migrée, nathan présent."""
    departements = charger_departements(RACINE_DEPARTEMENTS)
    assert all(departements[d].mode == "ombre" for d in DEPARTEMENTS_TESTES)
    return Capacites(departements, session, filtre=DEPARTEMENTS_TESTES, memoire=False)


@pytest.fixture
def personnes(session, capacites):
    with session() as cnx:
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "lea.fictif", "Léa Fictive", "mot-de-passe-lea-12345", ["employee"])


def _outil(capacites, nom):
    return capacites.index[nom][1]


def _meta(cle: str) -> idempotence.Meta:
    return idempotence.Meta(cle=cle, appareil="tel-fictif-t1-4-k", horodatage_appareil="2026-09-28T10:15:00-04:00")


def _appeler(capacites, nom, arguments, identite_appelante, cle):
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments, _meta(cle))


def _referentiel():
    return {cedule.tokeniser_ville(SEL, VILLE): {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}


def _contrat(lead_id):
    return {"lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale", "ville": VILLE,
            "canal": "telephone", "contact": {"nom": "Client fictif", "telephone": "0102030405"},
            "urgence_declaree": False}


def _marqueur(lead_id):
    return {"readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
            "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32}


def _preparer(capacites, lead_id, technicien_id) -> str:
    """Agent : planifie l'intervention POUR `technicien_id` (l'identifiant de la personne), consigne son
    consentement GPS et démarre la route (préparation directe : ce n'est pas le geste testé)."""
    plan = executer_atomique(_outil(capacites, "m4_planifier_intervention"), {
        "contrat": _contrat(lead_id), "marqueur": _marqueur(lead_id),
        "horodatage": "2025-06-02T07:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": [technicien_id], "fenetres_disponibles": [FENETRE_2025],
    })
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]
    consent = executer_atomique(_outil(capacites, "m4_definir_consentement_gps"), {
        "technicien_id": technicien_id, "action": "donne", "horodatage": "2025-06-02T06:00:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test", "preuve": {"fictif": True, "reference": "c"},
    })
    assert consent["ok"] is True and consent["resultat"]["accepte"] is True, consent
    depart = executer_atomique(_outil(capacites, "m4_demarrer_route"), {
        "intervention_id": i_id, "technicien_id": technicien_id, "horodatage": "2025-06-02T07:30:00+00:00",
    })
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True, depart
    return i_id


def _args_pointage(i_id, technicien_id, action="arrivee"):
    maintenant = dt.datetime.now(dt.UTC)
    return {"intervention_id": i_id, "technicien_id": technicien_id, "action": action,
            "horodatage": "2000-01-01T00:00:00+00:00", "fix_gps": FIX_GPS, "attestation": ATTESTATION,
            "fenetre_travail": {"debut": (maintenant - dt.timedelta(hours=1)).isoformat(),
                                "fin": (maintenant + dt.timedelta(hours=11)).isoformat()},
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL}


def _statut(capacites, i_id):
    reponse = executer_atomique(_outil(capacites, "m4_statut_intervention"), {"intervention_id": i_id})
    return reponse["resultat"]["statut"]


def _maillons_m4():
    with stockage.transaction():
        return registre_m4.Registre(stockage.maillons("m04-field-ops", "principal")).lire()


def _traces(session):
    with session() as cnx:
        return approbations.lister(cnx)


def _png_minimal() -> bytes:
    def chunk(tag: bytes, donnees: bytes) -> bytes:
        return struct.pack(">I", len(donnees)) + tag + donnees + struct.pack(">I", zlib.crc32(tag + donnees))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff", 9)) + chunk(b"IEND", b""))


def _deposer_photo(capacites) -> str:
    contenu = _png_minimal()
    r = executer_atomique(_outil(capacites, "m4_deposer_fichier"), {
        "empreinte_sha256": hashlib.sha256(contenu).hexdigest(), "taille_octets": len(contenu),
        "type_mime": "image/png", "index_bloc": 0, "nombre_blocs": 1,
        "bloc_base64": base64.b64encode(contenu).decode("ascii"),
    })
    assert r["ok"] and r["resultat"]["accepte"] and r["resultat"]["resultat"]["complet"], r
    return r["resultat"]["resultat"]["reference"]


# -- 1. un employé n'agit pas pour un collègue, même quand T1.4-h l'exécute sans file d'attente ----------
def test_employe_ne_pointe_pas_pour_un_collegue_en_mode_ombre(capacites, personnes, session):
    i_lea = _preparer(capacites, "L-T1-4-K-POINTAGE", "lea.fictif")
    avant = _maillons_m4()

    # Sous son propre identifiant : l'intervention n'est pas la sienne.
    reponse = _appeler(capacites, "m4_pointer", _args_pointage(i_lea, "marc.fictif"), MARC, "mut-1")
    # Sous celui de sa collègue : refusé, jamais préféré en silence.
    usurpe = _appeler(capacites, "m4_pointer", _args_pointage(i_lea, "lea.fictif"), MARC, "mut-2")

    assert reponse["ok"] is True and reponse["resultat"]["verdict"]["code"] == CODE_NON_ASSIGNEE
    assert usurpe["ok"] is True and usurpe["resultat"]["verdict"]["code"] == CODE_IDENTITE_FOURNIE
    assert _maillons_m4() == avant, "rien n'est écrit au registre de M4"
    assert _statut(capacites, i_lea) == "en_route"
    # La tentative reste visible dans le journal des approbations (T1.4-h), avec son issue de refus :
    # jamais « en attente » du propriétaire, jamais exécutée.
    assert [t["statut"] for t in _traces(session)] == ["echec", "echec"]
    assert all(t["decide_par"] == "marc.fictif" and t["resultat"] == {"ok": True, "accepte": False}
               for t in _traces(session))


def test_employe_pointe_bien_le_sien_dans_la_meme_configuration(capacites, personnes, session):
    """Contre-épreuve : le refus ci-dessus ne vient pas d'un montage qui refuserait tout."""
    i_marc = _preparer(capacites, "L-T1-4-K-SIEN", "marc.fictif")

    reponse = _appeler(capacites, "m4_pointer", _args_pointage(i_marc, "marc.fictif"), MARC, "mut-1")

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    assert _statut(capacites, i_marc) == "sur_site"


def test_employe_ne_complete_pas_l_intervention_d_un_collegue(capacites, personnes, session):
    i_lea = _preparer(capacites, "L-T1-4-K-COMPLETION", "lea.fictif")
    for action, horodatage in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
        r = executer_atomique(_outil(capacites, "m4_pointer"), {
            **_args_pointage(i_lea, "lea.fictif", action), "horodatage": horodatage, "fenetre_travail": FENETRE_2025})
        assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    photo = _deposer_photo(capacites)
    avant = _maillons_m4()

    reponse = _appeler(capacites, "m4_completer_intervention", {
        "intervention_id": i_lea, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": {"checklist_complete": True, "photos_apres": [photo], "notes": "RAS.", "signature": None},
        "consentement_marketing": True, "description_factuelle": "Complétion d'un collègue (fictif).",
    }, MARC, "mut-completion")

    assert reponse["ok"] is True and reponse["resultat"]["verdict"]["code"] == CODE_NON_ASSIGNEE
    assert _maillons_m4() == avant, "aucun WCT n'est écrit, aucun événement n'est publié"
    assert _statut(capacites, i_lea) == "sur_site"


# -- 2. le consentement GPS : l'employé retire le SIEN, pas celui d'un autre --------------------------------
def test_l_employe_retire_son_consentement_gps_depuis_son_appareil_en_ombre(capacites, personnes, session):
    i_marc = _preparer(capacites, "L-T1-4-K-RETRAIT", "marc.fictif")
    args = {"technicien_id": "marc.fictif", "action": "retire", "horodatage": "2000-01-01T00:00:00+00:00",
            "version_politique": "POLITIQUE-geolocalisation-v1-test",
            "preuve": {"fictif": True, "reference": "app:retrait:mut-retrait"}}

    reponse = _appeler(capacites, "m4_definir_consentement_gps", args, MARC, "mut-retrait")

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    assert reponse["resultat"]["resultat"]["actif"] is False
    # L'heure du retrait est celle de la RÉCEPTION du serveur, pas la valeur fournie (an 2000).
    assert not reponse["resultat"]["resultat"]["horodatage"].startswith("2000")
    [trace] = _traces(session)
    assert (trace["outil"], trace["niveau"], trace["statut"], trace["decide_par"]) == (
        "m4_definir_consentement_gps", "N3", "executee", "marc.fictif")
    # Effet immédiat : le pointage suivant bascule en mode manuel, le fix fourni est ignoré.
    pointage_apres = _appeler(capacites, "m4_pointer", _args_pointage(i_marc, "marc.fictif"), MARC, "mut-pointage")
    assert pointage_apres["resultat"]["accepte"] is True
    assert pointage_apres["resultat"]["resultat"]["mode_pointage"] == "manuel"
    with stockage.transaction():
        registre = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))
        assert consentement.consentement_actif(registre, "marc.fictif") is False


def test_l_employe_ne_retire_pas_le_consentement_d_un_collegue(capacites, personnes, session):
    _preparer(capacites, "L-T1-4-K-RETRAIT-LEA", "lea.fictif")
    avant = _maillons_m4()

    reponse = _appeler(capacites, "m4_definir_consentement_gps", {
        "technicien_id": "lea.fictif", "action": "retire", "horodatage": "2025-06-02T08:00:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test", "preuve": {"fictif": True, "reference": "x"},
    }, MARC, "mut-retrait-autrui")

    assert reponse["ok"] is True and reponse["resultat"]["verdict"]["code"] == CODE_IDENTITE_FOURNIE
    assert _maillons_m4() == avant
    with stockage.transaction():
        registre = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))
        assert consentement.consentement_actif(registre, "lea.fictif") is True


# -- 3. M4 -> M6 : le WCT réel porte le technicien, M6 ne laisse déclarer que lui ----------------------------
def test_les_materiaux_ne_se_declarent_que_pour_son_propre_wct_de_la_completion_a_la_declaration(
        capacites, personnes, session, monkeypatch):
    i_marc = _preparer(capacites, "L-T1-4-K-M6", "marc.fictif")
    for action, horodatage in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
        r = executer_atomique(_outil(capacites, "m4_pointer"), {
            **_args_pointage(i_marc, "marc.fictif", action), "horodatage": horodatage,
            "fenetre_travail": FENETRE_2025})
        assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    completion = _appeler(capacites, "m4_completer_intervention", {
        "intervention_id": i_marc, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": {"checklist_complete": True, "photos_apres": [_deposer_photo(capacites)],
                               "notes": "RAS.", "signature": None},
    }, MARC, "mut-completion")
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion
    wct_id = completion["resultat"]["resultat"]["wct_id"]

    # Préalable de M6 (coût unitaire) : une réception pour le chantier que la source impose à l'employé
    # (aucun prévu ici : l'intervention), faite par l'agent.
    reception = executer_atomique(_outil(capacites, "m6_receptionner_commande"), {
        "bon_demande": {"po_id": "PO-T1-4-K", "chantier_id": i_marc,
                        "lignes_demandees": [{"materiau_id": "MAT-1", "quantite_demandee": 20.0}],
                        "horodatage": "2025-12-01T00:00:00Z"},
        "reception_po": {"po_id": "PO-T1-4-K", "chantier_id": i_marc,
                         "lignes_recues": [{"materiau_id": "MAT-1", "quantite_recue": 20.0}],
                         "horodatage": "2025-12-02T00:00:00Z"},
        "catalogue_materiaux": {"version": "v1", "unite_monetaire": "CAD",
                                "postes": {"MAT-1": {"cout_unitaire": 5.0, "libelle": "MAT-1"}}},
    })
    assert reception["ok"] is True and reception["resultat"]["accepte"] is True, reception
    arguments = {"wct_id": wct_id, "formulaire": {
        "wct_id": wct_id, "intervention_id": i_marc, "chantier_id": i_marc,
        "lignes_materiaux": [{"type_ligne": "prevu", "materiau_id": "MAT-1", "quantite": 10.0,
                              "unite": "boite", "quantite_estimee": 10.0}]}}

    # Deux secondes distinctes rendent observable l'ordre récent-d'abord du lecteur.
    dates_traces = iter(("2026-10-06T11:00:00+00:00", "2026-10-06T11:00:01+00:00"))
    monkeypatch.setattr(approbations, "_maintenant", lambda: next(dates_traces))

    # Léa (employée, autre technicien) ne peut pas déclarer pour le chantier de Marc.
    refuse = _appeler(capacites, "m6_declarer_materiaux_utilises", arguments, LEA, "mut-m6-lea")
    assert refuse["ok"] is True and refuse["resultat"]["verdict"]["code"] == CODE_NON_ASSIGNEE
    with stockage.transaction():
        assert [m for m in stockage.maillons("m06-material-control", "principal") if m.get("wct_id") == wct_id] == []

    # Marc le peut : le WCT porte SON identifiant, le formulaire concorde avec la source.
    accepte = _appeler(capacites, "m6_declarer_materiaux_utilises", arguments, MARC, "mut-m6-marc")
    assert accepte["ok"] is True and accepte["resultat"]["accepte"] is True, accepte
    with stockage.transaction():
        ecrits = [m for m in stockage.maillons("m06-material-control", "principal") if m.get("wct_id") == wct_id]
    assert [(m["type_mouvement"], m["chantier_id"], m["quantite"]) for m in ecrits] == [
        ("CONSOMMATION", i_marc, -10.0)]
    assert [(t["outil"], t["decide_par"], t["statut"], t["cree_le"])
            for t in _traces(session) if t["outil"].startswith("m6_")] == [
        ("m6_declarer_materiaux_utilises", "marc.fictif", "executee", "2026-10-06T11:00:01+00:00"),
        ("m6_declarer_materiaux_utilises", "lea.fictif", "echec", "2026-10-06T11:00:00+00:00")]


# -- 4. par MCP : l'identité vient du `_meta`, jamais des arguments --------------------------------------------
def test_mcp_l_identite_du_meta_decide_pas_le_technicien_id_des_arguments(capacites, personnes, session):
    i_lea = _preparer(capacites, "L-T1-4-K-MCP", "lea.fictif")
    serveur = creer_serveur(capacites)

    def meta(cle):
        return {"opsys/idempotencyKey": cle, "opsys/appareil": "tel-marc-fictif",
                "opsys/horodatageAppareil": "2026-09-28T10:15:00-04:00",
                "opsys/personne": "marc.fictif", "opsys/role": "employee"}

    async def scenario() -> dict:
        async with Client(serveur) as client:
            # Les arguments désignent Léa et son intervention ; le jeton, lui, est celui de Marc.
            resultat = await client.call_tool("m4_pointer", _args_pointage(i_lea, "lea.fictif"), meta=meta("mut-mcp"))
            return json.loads(resultat.content[0].text)

    reponse = anyio.run(scenario)

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == CODE_IDENTITE_FOURNIE
    assert _statut(capacites, i_lea) == "en_route"
    assert etats.technicien_assigne(registre_m4.Registre(_maillons_m4()), i_lea) == "lea.fictif"
