"""PLAN T4.2 (POLITIQUE-geolocalisation.md) : consentement, chiffrement et rétention/destruction
des fixes GPS — de bout en bout, par les VRAIS outils sur le registre durable (ADR-0009), comme
`test_approbations_m4.py` et `test_paie_horloge_appareil.py`.

Trois volets :
    1. m4_pointer n'enregistre un fix GPS QUE si le consentement est actif (§4) — sinon mode
       manuel, jamais rejeté.
    2. Le fix retenu est chiffré dans le registre durable (§5) — jamais les coordonnées en clair —
       et reste lisible (m4_lire_position_gps, §7) tant que sa clé existe ; chaque lecture est
       journalisée (§6).
    3. m4_purger_retention_gps (N5, ADR-0009 §4/§5) détruit cette clé une fois l'échéance atteinte
       (fail-closed sans fin_contrat_travail, ou avant l'échéance) : la position redevient
       irrécupérable SANS jamais casser la chaîne de hash du registre.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m4_field_ops import cedule
from m4_field_ops import registre as registre_mod
from m4_field_ops.outils import outils

from opsys import approbations, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Niveau, executer_atomique

_M4_RACINE = Path(__file__).resolve().parents[1]

SEL = "sel-geoloc-gps"
VILLE = "Montreal"
FIX_GPS_COHERENT = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-GEOLOC"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
VERSION_POLITIQUE = "POLITIQUE-geolocalisation-v1-test"
PREUVE_CONSENTEMENT = {"fictif": True, "reference": "formulaire-signe-gps-001"}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _dep_m4():
    return lire_manifeste(_M4_RACINE)


def _referentiel():
    token = cedule.tokeniser_ville(SEL, VILLE)
    return {token: {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}


def _contrat(lead_id):
    return {
        "lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale",
        "ville": VILLE, "canal": "telephone",
        "contact": {"nom": "Client", "telephone": "0102030405"}, "urgence_declaree": False,
    }


def _marqueur(lead_id):
    return {
        "readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32,
    }


def _planifier_et_router(par_nom, lead_id, technicien_id="T1"):
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": _contrat(lead_id), "marqueur": _marqueur(lead_id),
        "horodatage": "2025-06-02T08:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": [technicien_id], "fenetres_disponibles": [FENETRE],
    })
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]
    depart = executer_atomique(par_nom["m4_demarrer_route"], {
        "intervention_id": i_id, "technicien_id": technicien_id, "horodatage": "2025-06-02T08:30:00+00:00",
    })
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True, depart
    return i_id


def _donner_consentement(par_nom, technicien_id="T1", horodatage="2025-06-02T07:00:00+00:00"):
    reponse = executer_atomique(par_nom["m4_definir_consentement_gps"], {
        "technicien_id": technicien_id, "action": "donne", "horodatage": horodatage,
        "version_politique": VERSION_POLITIQUE, "preuve": PREUVE_CONSENTEMENT,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _retirer_consentement(par_nom, technicien_id="T1", horodatage="2025-06-02T07:30:00+00:00"):
    reponse = executer_atomique(par_nom["m4_definir_consentement_gps"], {
        "technicien_id": technicien_id, "action": "retire", "horodatage": horodatage,
        "version_politique": VERSION_POLITIQUE, "preuve": PREUVE_CONSENTEMENT,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _reg_durable():
    return registre_mod.Registre(stockage.maillons("m04-field-ops", "principal"))


# =====================================================================================
# 1. Consentement, mode manuel, chiffrement — via m4_pointer
# =====================================================================================
def test_pointer_sans_consentement_bascule_mode_manuel_jamais_rejete(base_durable):
    """§4 : m4_pointer n'enregistre un fix GPS QUE si le consentement est actif — l'ABSENCE de
    consentement ne rejette jamais le pointage (l'employé peut toujours pointer), elle bascule en
    mode manuel."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _planifier_et_router(par_nom, "L-SANS-CONSENT")

    with stockage.transaction():
        r = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": "arrivee",
            "horodatage": "2025-06-02T09:00:00+00:00", "fix_gps": FIX_GPS_COHERENT,
            "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
        })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    accuse = r["resultat"]["resultat"]
    assert accuse["mode_pointage"] == "manuel"
    assert accuse["gps_coherent"] is None
    # Sans GPS pour confirmer la présence sur site, l'arrivée route en_revue (fail-closed) — même
    # patron qu'une incohérence GPS, jamais un statut distinct inventé.
    assert accuse["statut"] == "en_revue"

    with stockage.transaction():
        reg = _reg_durable()
    maillon = next(m for m in reg.lire() if m.get("ligne_id") == accuse["ligne_id"])
    assert "latitude" not in maillon and "longitude" not in maillon and "position_chiffree" not in maillon
    assert maillon["mode_pointage"] == "manuel"
    demande = next(m for m in reg.lire() if m.get("type_entree") == "demande_revue")
    assert demande["causes_possibles"] == ["mode_manuel_sans_fix_gps"]


def test_pointer_avec_consentement_actif_chiffre_le_fix_jamais_en_clair(base_durable):
    par_nom = {o.nom: o for o in outils()}
    i_id = _planifier_et_router(par_nom, "L-AVEC-CONSENT")
    _donner_consentement(par_nom)

    with stockage.transaction():
        r = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": "arrivee",
            "horodatage": "2025-06-02T09:00:00+00:00", "fix_gps": FIX_GPS_COHERENT,
            "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
        })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    accuse = r["resultat"]["resultat"]
    assert accuse["gps_chiffre"] is True
    assert accuse["gps_coherent"] is True  # la cohérence est calculée AVANT le chiffrement
    assert accuse["statut"] == "sur_site"

    with stockage.transaction():
        reg = _reg_durable()
    maillon = next(m for m in reg.lire() if m.get("ligne_id") == accuse["ligne_id"])
    assert "latitude" not in maillon and "longitude" not in maillon
    assert maillon["gps_chiffre"] is True
    assert isinstance(maillon["position_chiffree"], str) and maillon["position_chiffree"] != ""
    # Invariant (même esprit que « aucune ville en clair », test_pointage.py) : ni le registre ni
    # l'accusé ne portent jamais les coordonnées en clair une fois chiffrées.
    for objet in (maillon, accuse):
        serialise = str(objet)
        assert str(FIX_GPS_COHERENT["latitude"]) not in serialise
        assert str(FIX_GPS_COHERENT["longitude"]) not in serialise


def test_retrait_consentement_immediat_ignore_un_fix_reel_fourni_ensuite(base_durable):
    """§4 : « le retrait désactive immédiatement le punch géorépéré » — même si l'appelant (agent,
    appareil bogué) fournit encore un fix réel, il est ignoré, jamais enregistré."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _planifier_et_router(par_nom, "L-RETRAIT-IMMEDIAT")
    _donner_consentement(par_nom)
    _retirer_consentement(par_nom)

    with stockage.transaction():
        r = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": "arrivee",
            "horodatage": "2025-06-02T09:00:00+00:00", "fix_gps": FIX_GPS_COHERENT,
            "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
        })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    assert r["resultat"]["resultat"]["mode_pointage"] == "manuel"


def test_pointer_hors_appel_appareil_fix_null_est_deja_un_mode_manuel_legitime(base_durable):
    """`fix_gps=None` reste accepté indépendamment du consentement (appareil sans signal) : la
    forme nullable (_FIX_GPS) n'est pas réservée au retrait de consentement."""
    par_nom = {o.nom: o for o in outils()}
    i_id = _planifier_et_router(par_nom, "L-FIX-NULL")
    _donner_consentement(par_nom)

    with stockage.transaction():
        r = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": "arrivee",
            "horodatage": "2025-06-02T09:00:00+00:00", "fix_gps": None,
            "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
        })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    assert r["resultat"]["resultat"]["mode_pointage"] == "manuel"


# =====================================================================================
# 2. m4_lire_position_gps — droit d'accès (§7) et journalisation (§6)
# =====================================================================================
def _pointer_geo_trace(par_nom, lead_id="L-LECTURE", technicien_id="T1"):
    i_id = _planifier_et_router(par_nom, lead_id, technicien_id)
    _donner_consentement(par_nom, technicien_id)
    with stockage.transaction():
        r = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": technicien_id, "action": "arrivee",
            "horodatage": "2025-06-02T09:00:00+00:00", "fix_gps": FIX_GPS_COHERENT,
            "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
        })
    assert r["ok"] is True and r["resultat"]["accepte"] is True, r
    return i_id, r["resultat"]["resultat"]["ligne_id"]


def test_lire_position_gps_dechiffre_et_journalise_l_acces(base_durable):
    par_nom = {o.nom: o for o in outils()}
    _, ligne_id = _pointer_geo_trace(par_nom)

    with stockage.transaction():
        lecture = executer_atomique(par_nom["m4_lire_position_gps"], {
            "ligne_id": ligne_id, "accede_par": "supervisor-1", "horodatage": "2025-06-02T10:00:00+00:00",
        })
    assert lecture["ok"] is True and lecture["resultat"]["accepte"] is True, lecture
    assert lecture["resultat"]["resultat"] == FIX_GPS_COHERENT

    with stockage.transaction():
        reg = _reg_durable()
    dernier = reg.lire()[-1]
    assert dernier["type_entree"] == "acces_position_gps"
    assert dernier["ligne_id_position"] == ligne_id
    assert dernier["accede_par"] == "supervisor-1"
    assert dernier["resultat"] == "dechiffre"
    assert reg.valider_chaine() is True


def test_lire_position_gps_ligne_id_inconnu_refuse_nomme(base_durable):
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction():
        lecture = executer_atomique(par_nom["m4_lire_position_gps"], {
            "ligne_id": "ligne-inexistante", "accede_par": "supervisor-1",
            "horodatage": "2025-06-02T10:00:00+00:00",
        })
    assert lecture["ok"] is True and lecture["resultat"]["accepte"] is False
    assert lecture["resultat"]["verdict"]["code"] == "REJ-POSITION-INTROUVABLE"


def test_lire_position_gps_mode_manuel_refuse_et_journalise_introuvable(base_durable):
    par_nom = {o.nom: o for o in outils()}
    i_id = _planifier_et_router(par_nom, "L-LECTURE-MANUEL")  # aucun consentement donné
    with stockage.transaction():
        r = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": "arrivee",
            "horodatage": "2025-06-02T09:00:00+00:00", "fix_gps": FIX_GPS_COHERENT,
            "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": _referentiel(), "ville": VILLE, "sel": SEL,
        })
    ligne_id = r["resultat"]["resultat"]["ligne_id"]

    with stockage.transaction():
        lecture = executer_atomique(par_nom["m4_lire_position_gps"], {
            "ligne_id": ligne_id, "accede_par": "supervisor-1", "horodatage": "2025-06-02T10:00:00+00:00",
        })
    assert lecture["resultat"]["accepte"] is False
    assert lecture["resultat"]["verdict"]["code"] == "REJ-POSITION-INTROUVABLE"
    with stockage.transaction():
        reg = _reg_durable()
    assert reg.lire()[-1]["resultat"] == "introuvable"


# =====================================================================================
# 3. m4_purger_retention_gps — rétention et destruction (§5), N5 (ADR-0009 §4/§5)
# =====================================================================================
def test_purger_fin_contrat_manquante_fail_closed_aucune_destruction(base_durable):
    par_nom = {o.nom: o for o in outils()}
    _, ligne_id = _pointer_geo_trace(par_nom, lead_id="L-PURGE-SANS-FIN-CONTRAT")

    with stockage.transaction():
        purge = executer_atomique(par_nom["m4_purger_retention_gps"], {
            "technicien_id": "T1", "fin_contrat_travail": "", "horodatage": "2026-01-01T00:00:00+00:00",
            "motif": "Test.",
        })
    assert purge["ok"] is True and purge["resultat"]["accepte"] is False
    assert purge["resultat"]["verdict"]["code"] == "REJ-RETENTION-DONNEE-MANQUANTE"

    # Rien détruit : la position reste lisible.
    with stockage.transaction():
        lecture = executer_atomique(par_nom["m4_lire_position_gps"], {
            "ligne_id": ligne_id, "accede_par": "audit-1", "horodatage": "2026-01-01T00:00:00+00:00",
        })
    assert lecture["resultat"]["accepte"] is True


def test_purger_echeance_non_atteinte_refuse_aucune_destruction(base_durable):
    par_nom = {o.nom: o for o in outils()}
    _, ligne_id = _pointer_geo_trace(par_nom, lead_id="L-PURGE-TROP-TOT")

    with stockage.transaction():
        purge = executer_atomique(par_nom["m4_purger_retention_gps"], {
            "technicien_id": "T1", "fin_contrat_travail": "2025-07-01T00:00:00+00:00",
            "horodatage": "2025-12-01T00:00:00+00:00",  # < 12 mois après fin_contrat_travail
            "motif": "Test.",
        })
    assert purge["ok"] is True and purge["resultat"]["accepte"] is False
    assert purge["resultat"]["verdict"]["code"] == "REJ-RETENTION-NON-ECHUE"

    with stockage.transaction():
        lecture = executer_atomique(par_nom["m4_lire_position_gps"], {
            "ligne_id": ligne_id, "accede_par": "audit-1", "horodatage": "2025-12-01T00:00:00+00:00",
        })
    assert lecture["resultat"]["accepte"] is True


def test_purger_motif_vide_refuse(base_durable):
    par_nom = {o.nom: o for o in outils()}
    _, ligne_id = _pointer_geo_trace(par_nom, lead_id="L-PURGE-MOTIF-VIDE")
    purge = executer_atomique(par_nom["m4_purger_retention_gps"], {
        "technicien_id": "T1", "fin_contrat_travail": "2024-01-01T00:00:00+00:00",
        "horodatage": "2026-06-02T09:00:01+00:00", "motif": "   ",
    })
    assert purge["resultat"]["accepte"] is False
    assert purge["resultat"]["verdict"]["code"] == "REJ-CHAMP-VIDE"


def test_purger_echeance_atteinte_detruit_la_cle_registre_reste_intact(base_durable):
    """Le cœur de la preuve (PLAN T4.2, mécanisme de destruction) : après la purge, le fix GPS
    déjà écrit devient irrécupérable (REJ-POSITION-DETRUITE) MAIS le registre reste un maillon
    inchangé, sa chaîne de hash toujours valide — la destruction ne l'a jamais touché."""
    par_nom = {o.nom: o for o in outils()}
    i_id, ligne_id = _pointer_geo_trace(par_nom, lead_id="L-PURGE-OK")

    with stockage.transaction():
        reg_avant = _reg_durable()
        tete_avant = reg_avant.tete()
        taille_avant = reg_avant.taille()
        maillon_avant = next(m for m in reg_avant.lire() if m.get("ligne_id") == ligne_id)

    with stockage.transaction():
        purge = executer_atomique(par_nom["m4_purger_retention_gps"], {
            "technicien_id": "T1", "fin_contrat_travail": "2024-01-01T00:00:00+00:00",
            # Échéance = max(fin_contrat_travail, dernier punch T1) + 12 mois ; le dernier punch
            # (_pointer_geo_trace, "2025-06-02T09:00:00+00:00") est plus tardif que fin_contrat_travail
            # ici (§5 : « selon la plus longue des deux périodes »), donc c'est lui qui fixe l'échéance.
            "horodatage": "2026-06-02T09:00:01+00:00", "motif": "Rétention échue, RH confirmée.",
        })
    assert purge["ok"] is True and purge["resultat"]["accepte"] is True, purge
    assert purge["resultat"]["resultat"]["cle_detruite"] is True

    with stockage.transaction():
        reg_apres = _reg_durable()
        maillon_apres = next(m for m in reg_apres.lire() if m.get("ligne_id") == ligne_id)

    # Le maillon de pointage lui-même n'a PAS bougé d'un octet.
    assert maillon_apres == maillon_avant
    assert reg_apres.tete() != tete_avant  # un maillon d'audit a été ajouté (purge_retention_gps)
    assert reg_apres.taille() == taille_avant + 1
    assert reg_apres.valider_chaine() is True  # la chaîne entière reste intègre

    maillon_purge = reg_apres.lire()[-1]
    assert maillon_purge["type_entree"] == "purge_retention_gps"
    assert maillon_purge["cle_detruite"] is True
    assert "latitude" not in maillon_purge and "position_chiffree" not in str(maillon_purge.get("motif", ""))

    # La lecture (droit d'accès, §7) échoue maintenant nommément — la preuve que la destruction a
    # fonctionné, jamais une exception ni un plantage.
    with stockage.transaction():
        lecture = executer_atomique(par_nom["m4_lire_position_gps"], {
            "ligne_id": ligne_id, "accede_par": "audit-1", "horodatage": "2026-06-02T09:00:02+00:00",
        })
    assert lecture["ok"] is True and lecture["resultat"]["accepte"] is False
    assert lecture["resultat"]["verdict"]["code"] == "REJ-POSITION-DETRUITE"


def test_purger_rejouee_idempotente_cle_deja_detruite(base_durable):
    par_nom = {o.nom: o for o in outils()}
    _pointer_geo_trace(par_nom, lead_id="L-PURGE-REJOUEE")
    args = {
        "technicien_id": "T1", "fin_contrat_travail": "2024-01-01T00:00:00+00:00",
        "horodatage": "2026-06-02T09:00:01+00:00", "motif": "Première purge.",
    }
    with stockage.transaction():
        premiere = executer_atomique(par_nom["m4_purger_retention_gps"], args)
    assert premiere["resultat"]["resultat"]["cle_detruite"] is True

    with stockage.transaction():
        seconde = executer_atomique(par_nom["m4_purger_retention_gps"], {**args, "motif": "Rejouée."})
    assert seconde["ok"] is True and seconde["resultat"]["accepte"] is True
    assert seconde["resultat"]["resultat"]["cle_detruite"] is False  # rien à détruire, pas une erreur


def test_purger_ne_touche_jamais_la_cle_d_un_autre_technicien(base_durable):
    par_nom = {o.nom: o for o in outils()}
    _, ligne_id_t1 = _pointer_geo_trace(par_nom, lead_id="L-PURGE-T1", technicien_id="T1")
    _, ligne_id_t2 = _pointer_geo_trace(par_nom, lead_id="L-PURGE-T2", technicien_id="T2")

    with stockage.transaction():
        purge_t1 = executer_atomique(par_nom["m4_purger_retention_gps"], {
            "technicien_id": "T1", "fin_contrat_travail": "2024-01-01T00:00:00+00:00",
            "horodatage": "2026-06-02T09:00:01+00:00", "motif": "Purge T1 seulement.",
        })
    assert purge_t1["resultat"]["accepte"] is True and purge_t1["resultat"]["resultat"]["cle_detruite"] is True

    with stockage.transaction():
        lecture_t2 = executer_atomique(par_nom["m4_lire_position_gps"], {
            "ligne_id": ligne_id_t2, "accede_par": "audit-1", "horodatage": "2026-01-01T00:00:01+00:00",
        })
    assert lecture_t2["resultat"]["accepte"] is True, lecture_t2  # T2 intact


# -- Outil déclare N5 (ADR-0009 §4) ---------------------------------------------------------------
def test_outil_purger_retention_gps_declare_n5():
    par_nom = {o.nom: o for o in outils()}
    assert par_nom["m4_purger_retention_gps"].niveau_effectif is Niveau.N5


# -- N5 : même frontière FIXE que le reste du socle (ADR-0009 §5), jamais un agent seul -----------
def test_purge_par_nathan_owner_avec_attestation_professionnelle_execute(base_durable):
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    i_id, ligne_id = _pointer_geo_trace(par_nom, lead_id="L-PURGE-APPROUVEE")

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan St-Louis", "mot-de-passe-nathan-1234", ["nathan_owner"])
        ident = approbations.creer_demande(
            cnx, "m04-field-ops", "m4_purger_retention_gps",
            {"technicien_id": "T1", "fin_contrat_travail": "2024-01-01T00:00:00+00:00",
             "horodatage": "2026-06-02T09:00:01+00:00", "motif": "Rétention échue."},
            niveau=Niveau.N5,
        )
        decision = approbations.decider(
            cnx, ident, True, "nathan", par_nom, {"m04-field-ops": dep},
            motif="Confirmé conforme à la politique.",
            attestation={"nom": "Me Personne Fictive", "profession": "avocate",
                         "reference_document": "attestation-fictive-001"},
        )
    assert decision["statut"] == "executee", decision
    assert decision["reponse"]["resultat"]["resultat"]["cle_detruite"] is True

    with stockage.transaction():
        lecture = executer_atomique(par_nom["m4_lire_position_gps"], {
            "ligne_id": ligne_id, "accede_par": "audit-1", "horodatage": "2026-06-02T09:00:02+00:00",
        })
    assert lecture["resultat"]["verdict"]["code"] == "REJ-POSITION-DETRUITE"


def test_purge_par_nathan_owner_sans_attestation_refusee_rien_execute(base_durable):
    """N5 exige l'attestation du professionnel EN PLUS de la signature du propriétaire
    (ADR-0009 §5) : sans elle, refus nommé, rien exécuté — même nathan_owner ne suffit pas seul."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    _, ligne_id = _pointer_geo_trace(par_nom, lead_id="L-PURGE-SANS-ATTESTATION")

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan St-Louis", "mot-de-passe-nathan-1234", ["nathan_owner"])
        ident = approbations.creer_demande(
            cnx, "m04-field-ops", "m4_purger_retention_gps",
            {"technicien_id": "T1", "fin_contrat_travail": "2024-01-01T00:00:00+00:00",
             "horodatage": "2026-01-01T00:00:00+00:00", "motif": "Rétention échue."},
            niveau=Niveau.N5,
        )
        with pytest.raises(ValueError, match="attestation"):
            approbations.decider(cnx, ident, True, "nathan", par_nom, {"m04-field-ops": dep})

    with stockage.transaction():
        lecture = executer_atomique(par_nom["m4_lire_position_gps"], {
            "ligne_id": ligne_id, "accede_par": "audit-1", "horodatage": "2026-01-01T00:00:01+00:00",
        })
    assert lecture["resultat"]["accepte"] is True  # rien détruit : la demande n'a pas abouti


def test_purge_par_manager_seul_refusee_rien_execute(base_durable):
    """N5 reste une frontière FIXE de l'ADR (jamais configurable par department.yaml) : un manager,
    autorisé pour N3/N4, n'est PAS autorisé pour N5 — voir aussi
    test_approbations_m4.py::test_department_yaml_declare_n3_n4_manager_admin_nathan_owner."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    _, ligne_id = _pointer_geo_trace(par_nom, lead_id="L-PURGE-MANAGER-REFUSE")

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "gerant", "Une Gérante", "mot-de-passe-gerante-1234", ["manager"])
        ident = approbations.creer_demande(
            cnx, "m04-field-ops", "m4_purger_retention_gps",
            {"technicien_id": "T1", "fin_contrat_travail": "2024-01-01T00:00:00+00:00",
             "horodatage": "2026-01-01T00:00:00+00:00", "motif": "Rétention échue."},
            niveau=Niveau.N5,
        )
        with pytest.raises(ValueError, match="aucun rôle autorisé"):
            approbations.decider(cnx, ident, True, "gerant", par_nom, {"m04-field-ops": dep})

    with stockage.transaction():
        lecture = executer_atomique(par_nom["m4_lire_position_gps"], {
            "ligne_id": ligne_id, "accede_par": "audit-1", "horodatage": "2026-01-01T00:00:01+00:00",
        })
    assert lecture["resultat"]["accepte"] is True
