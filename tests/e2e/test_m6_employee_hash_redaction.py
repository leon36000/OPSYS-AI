from __future__ import annotations

import copy
import datetime as dt
import json

import pytest
from harnais_e2e_chantier import AppEmploye, preparer_chantier
from m6_material_control import livre_prix
from sqlalchemy import delete, select, update

from opsys import stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante, appele_par_appareil, appeler_en_tant_que
from opsys.stockage.schema import (
    ARTEFACTS,
    MUTATIONS_APPLIQUEES,
    PERSONNES,
    ROLES_PERSONNES,
)


def test_employee_hash_redaction_prevents_new_and_legacy_http_disclosure(equipe, moteur):
    # Prix fictif, entré dans le registre de prix par l'API de domaine M6; la déclaration terrain passe par HTTP.
    source_prix = {
        "source": "LIVRE_PRIX",
        "marquage": "SOURCE_DECLAREE",
        "prix": [{
            "fournisseur_id": "fournisseur-revue-fictif",
            "source_document": "DOC-PRIX-REVUE-FICTIF",
            "date_effet": "2026-01-01",
        }],
    }
    with stockage.transaction():
        livre = stockage.maillons("m06-material-control", "livre_prix")
        _, refus = livre_prix.enregistrer_prix(
            "gouttiere-alu-5po-fictif", "fournisseur-revue-fictif", 12.34, "CAD", "2026-01-01",
            livre, "DOC-PRIX-REVUE-FICTIF", "pi",
        )
        assert refus is None

    chantier = preparer_chantier(
        moteur.departements, suffixe="employee-hash-fictif", technicien="etienne",
        debut=moteur.horloge.maintenant,
    )
    app = AppEmploye(moteur, equipe["employe"], chantier, derive_appareil_s=0)
    completion = app.journee_jusqu_a_la_completion()
    assert completion.metier["accepte"] is True, completion.corps
    wct_id = completion.resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)

    declaration = app.declarer_materiaux(wct_id, 40.0)
    assert declaration.statut == 200
    assert declaration.metier["accepte"] is True, declaration.corps
    raw_tool_reply = declaration.enveloppe
    assert raw_tool_reply["ok"] is True
    metier = raw_tool_reply["resultat"]
    assert metier["accepte"] is True
    assert metier["registre"]["taille"] >= 1
    assert metier["registre"]["hash_tete"] is None

    appel = app.appels[-1]
    with stockage.transaction() as cnx:
        maillons = list(stockage.maillons("m06-material-control", "principal"))
        accuse = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel.cle,
        )).mappings().one()
        ack_persistant = stockage.codec.decoder(accuse["reponse"])
    dernier = next(m for m in reversed(maillons) if m.get("wct_id") == wct_id)
    assert len(dernier["hash_maillon"]) == 64
    assert dernier["cout_unitaire"] == 12.34
    assert dernier["origine_cout"] == source_prix
    assert ack_persistant["resultat"]["registre"]["hash_tete"] is None

    # Simule une ligne d'idempotence écrite par l'ancienne version, qui conservait l'ACK complet. Le rejeu
    # doit expurger sa copie de réponse sans réécrire ce reçu historique.
    ack_legacy = copy.deepcopy(ack_persistant)
    ack_legacy["resultat"]["registre"]["hash_tete"] = dernier["hash_maillon"]
    with stockage.transaction() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel.cle,
        ).values(reponse=stockage.codec.encoder(ack_legacy)))

    reprise = app.rejouer(appel)
    assert reprise.enveloppe["rejoue"] is True
    assert reprise.metier["registre"]["hash_tete"] is None
    with stockage.transaction() as cnx:
        ack_apres_rejeu = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel.cle,
        )).mappings().one()
        assert stockage.codec.decoder(ack_apres_rejeu["reponse"]) == ack_legacy

    # Une seconde déclaration sur un autre WCT conserve le même format expurgé après un nouveau mouvement.
    debut_2 = moteur.horloge.maintenant + dt.timedelta(days=1)
    moteur.horloge.maintenant = debut_2
    chantier_2 = preparer_chantier(
        moteur.departements, suffixe="employee-hash-fictif-2", technicien="etienne", debut=debut_2,
    )
    app_2 = AppEmploye(moteur, equipe["employe"], chantier_2, derive_appareil_s=0)
    completion_2 = app_2.journee_jusqu_a_la_completion()
    assert completion_2.metier["accepte"] is True, completion_2.corps
    wct_2 = completion_2.resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    declaration_2 = app_2.declarer_materiaux(wct_2, 40.0)
    assert declaration_2.metier["accepte"] is True, declaration_2.corps
    reponse_2 = declaration_2.metier["registre"]
    with stockage.transaction():
        maillons_2 = list(stockage.maillons("m06-material-control", "principal"))
    dernier_2 = next(m for m in reversed(maillons_2) if m.get("wct_id") == wct_2)
    assert dernier_2["origine_cout"] == source_prix
    assert reponse_2["hash_tete"] is None
    assert dernier_2["cout_unitaire"] == 12.34
    assert dernier_2["hash_precedent"] == dernier["hash_maillon"]


def test_admin_employee_tool_response_keeps_registry_hash(equipe, moteur):
    chantier = preparer_chantier(
        moteur.departements, suffixe="admin-hash-fictif", technicien="etienne",
        debut=moteur.horloge.maintenant,
    )
    app = AppEmploye(moteur, equipe["employe"], chantier, derive_appareil_s=0)
    completion = app.journee_jusqu_a_la_completion()
    assert completion.metier["accepte"] is True, completion.corps
    wct_id = completion.resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    formulaire = {
        "wct_id": wct_id, "intervention_id": chantier.intervention_id, "chantier_id": chantier.chantier_id,
        "lignes_materiaux": [{
            "type_ligne": "non_prevu", "materiau_id": "gouttiere-alu-5po-fictif", "quantite": 1.0, "unite": "pi",
        }],
    }
    reponse = equipe["admin"].appeler(
        "m6_declarer_materiaux_utilises", {"wct_id": wct_id, "formulaire": formulaire},
        cle="admin-hash-fictif", horodatage_appareil=app.heure_appareil(),
    )
    assert reponse.metier["accepte"] is True, reponse.corps
    assert len(reponse.metier["registre"]["hash_tete"]) == 64


def test_employee_hash_is_censored_before_truncation_and_artifact_persistence(equipe, moteur):
    # Simule une réponse de confirmation trop volumineuse à la frontière commune de sortie. Le hash
    # est placé au début pour vérifier aussi l'aperçu, tandis que l'artefact permet de relire le texte
    # complet si une origine fiable est présente.
    secret = "a" * 64
    capacites = Capacites(
        moteur.departements,
        stockage.transaction,
        filtre={"m06-material-control"},
        appelant="m06-material-control",
        limite_sortie=512,
    )
    reponse = {
        "ok": True,
        "resultat": {
            "accepte": True,
            "registre": {"taille": 12, "hash_tete": secret},
            "lignes": [{"description": "donnée fictive " + ("x" * 400)} for _ in range(8)],
        },
    }
    with appele_par_appareil(IdentiteAppelante("etienne", "employee")), appeler_en_tant_que(
        "m06-material-control", origine="m06-material-control",
    ):
        sortie = capacites._tronquer(
            reponse,
            "m6_declarer_materiaux_utilises",
            departement="m06-material-control",
            origine="m06-material-control",
        )

    assert sortie["tronque"] is True
    assert secret not in json.dumps(sortie, ensure_ascii=False)
    assert '"hash_tete": null' in sortie["apercu"]
    with stockage.transaction() as cnx:
        artefacts = cnx.execute(select(ARTEFACTS.c.contenu).where(
            ARTEFACTS.c.source == "m6_declarer_materiaux_utilises",
            ARTEFACTS.c.origine == "m06-material-control",
        )).scalars().all()
    assert len(artefacts) == 1
    assert secret not in artefacts[0]
    assert '"hash_tete": null' in artefacts[0]


def test_employee_plain_replay_after_role_revocation_returns_unknown_without_rewriting_ack(equipe, moteur):
    chantier = preparer_chantier(
        moteur.departements, suffixe="employee-role-revoked-hash-fictif", technicien="etienne",
        debut=moteur.horloge.maintenant,
    )
    app = AppEmploye(moteur, equipe["employe"], chantier, derive_appareil_s=0)
    wct_id = app.journee_jusqu_a_la_completion().resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    ack = app.declarer_materiaux(wct_id, 2.0)
    assert ack.metier["accepte"] is True, ack.corps
    appel = app.appels[-1]
    with stockage.transaction() as cnx:
        ligne_ack = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel.cle,
        )).mappings().one()
        reponse_avant = ligne_ack["reponse"]
        taille_stock = len(stockage.maillons("m06-material-control", "principal"))
        cnx.execute(delete(ROLES_PERSONNES).where(
            ROLES_PERSONNES.c.identifiant == "etienne", ROLES_PERSONNES.c.role == "employee",
        ))

    reprise = app.rejouer(appel)
    assert reprise.enveloppe["ok"] is False
    assert reprise.enveloppe["erreur"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    with stockage.transaction() as cnx:
        ligne_apres = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel.cle,
        )).mappings().one()
        assert ligne_apres["reponse"] == reponse_avant
        assert len(stockage.maillons("m06-material-control", "principal")) == taille_stock


@pytest.mark.parametrize("retrait", ["role", "compte"])
def test_admin_plain_replay_after_role_or_account_revocation_does_not_return_hash(equipe, moteur, retrait):
    chantier = preparer_chantier(
        moteur.departements, suffixe=f"admin-{retrait}-revoked-hash-fictif", technicien="etienne",
        debut=moteur.horloge.maintenant,
    )
    app_employe = AppEmploye(moteur, equipe["employe"], chantier, derive_appareil_s=0)
    wct_id = app_employe.journee_jusqu_a_la_completion().resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    formulaire = {
        "wct_id": wct_id, "intervention_id": chantier.intervention_id, "chantier_id": chantier.chantier_id,
        "lignes_materiaux": [{
            "type_ligne": "non_prevu", "materiau_id": "gouttiere-alu-5po-fictif", "quantite": 1.0, "unite": "pi",
        }],
    }
    args = {"wct_id": wct_id, "formulaire": formulaire}
    key = f"admin-{retrait}-revoked-hash-fictif"
    timestamp = app_employe.heure_appareil()
    ack = equipe["admin"].appeler(
        "m6_declarer_materiaux_utilises", args, cle=key, horodatage_appareil=timestamp,
    )
    assert ack.metier["accepte"] is True, ack.corps
    assert len(ack.metier["registre"]["hash_tete"]) == 64
    with stockage.transaction() as cnx:
        ligne_ack = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["admin"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == key,
        )).mappings().one()
        reponse_avant = ligne_ack["reponse"]
        taille_stock = len(stockage.maillons("m06-material-control", "principal"))
        if retrait == "role":
            cnx.execute(delete(ROLES_PERSONNES).where(
                ROLES_PERSONNES.c.identifiant == "nathan", ROLES_PERSONNES.c.role == "admin",
            ))
        else:
            cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == "nathan").values(actif=False))

    reprise = equipe["admin"].appeler(
        "m6_declarer_materiaux_utilises", args, cle=key, horodatage_appareil=timestamp,
    )
    assert reprise.enveloppe["ok"] is False
    assert reprise.enveloppe["erreur"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    with stockage.transaction() as cnx:
        ligne_apres = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["admin"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == key,
        )).mappings().one()
        assert ligne_apres["reponse"] == reponse_avant
        assert len(stockage.maillons("m06-material-control", "principal")) == taille_stock


def test_employee_proof_ack_redacts_new_and_legacy_hashes_on_http_replay(equipe, moteur):
    source_prix = {
        "source": "LIVRE_PRIX", "marquage": "SOURCE_DECLAREE", "prix": [{
            "fournisseur_id": "fournisseur-preuves-fictif",
            "source_document": "DOC-PREUVES-FICTIF", "date_effet": "2026-01-01",
        }],
    }
    with stockage.transaction():
        refus = livre_prix.enregistrer_prix(
            "gouttiere-alu-5po-fictif", "fournisseur-preuves-fictif", 12.34, "CAD", "2026-01-01",
            stockage.maillons("m06-material-control", "livre_prix"), "DOC-PREUVES-FICTIF", "pi",
        )[1]
        assert refus is None
    chantier = preparer_chantier(
        moteur.departements, suffixe="employee-proof-hash-fictif", technicien="etienne",
        debut=moteur.horloge.maintenant,
    )
    app = AppEmploye(moteur, equipe["employe"], chantier, derive_appareil_s=0)
    completion = app.journee_jusqu_a_la_completion()
    assert completion.metier["accepte"] is True, completion.corps
    wct_id = completion.resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    args = {
        "wct_id": wct_id,
        "formulaire": {
            "wct_id": wct_id, "intervention_id": chantier.intervention_id, "chantier_id": chantier.chantier_id,
            "lignes_materiaux": [{
                "type_ligne": "perte", "materiau_id": "gouttiere-alu-5po-fictif", "quantite": 1.0, "unite": "pi",
            }],
        },
        "preuves_lignes": [{"position_ligne": 0, "note": "Dommage fictif observé.", "photos": []}],
    }
    key = "employee-proof-cost-hash-fictif"
    timestamp = app.heure_appareil()
    confirmation = equipe["employe"].appeler(
        "m6_declarer_materiaux_avec_preuves_appareil", args, cle=key, horodatage_appareil=timestamp,
    )
    assert confirmation.statut == 200, confirmation.corps
    assert confirmation.metier["accepte"] is True, confirmation.corps
    ack = confirmation.metier
    movement_ref = ack["resultat"]["preuves"][0]["reference_mouvement"]
    assert movement_ref["registre"] == "principal" and movement_ref["index"] == 0
    with stockage.transaction() as cnx:
        mouvement = next(iter(stockage.maillons("m06-material-control", "principal")))
        mutation = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == key,
        )).mappings().one()
        ack_persistant = stockage.codec.decoder(mutation["reponse"])
    assert mouvement["cout_unitaire"] == 12.34
    assert mouvement["origine_cout"] == source_prix
    assert movement_ref["hash_maillon"] is None
    assert ack["resultat"]["preuves"][0]["reference_preuve"]["hash_maillon"] is None
    assert ack["registre"]["hash_tete"] is None
    proof_ack_stored = ack_persistant["resultat"]
    assert proof_ack_stored["resultat"]["preuves"][0]["reference_mouvement"]["hash_maillon"] is None
    assert proof_ack_stored["resultat"]["preuves"][0]["reference_preuve"]["hash_maillon"] is None
    assert proof_ack_stored["registre"]["hash_tete"] is None

    # Restaure une ancienne forme complète seulement dans la DB SQLite temporaire pour éprouver le rejeu legacy.
    ack_legacy = copy.deepcopy(ack_persistant)
    proof = ack_legacy["resultat"]["resultat"]["preuves"][0]
    proof["reference_mouvement"]["hash_maillon"] = mouvement["hash_maillon"]
    with stockage.transaction() as cnx:
        chain_preuves = list(stockage.maillons("m06-material-control", "preuves_pertes_bris"))
        preuve_maillon = chain_preuves[proof["reference_preuve"]["index"]]
        proof["reference_preuve"]["hash_maillon"] = preuve_maillon["hash_maillon"]
        ack_legacy["resultat"]["registre"]["hash_tete"] = mouvement["hash_maillon"]
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == key,
        ).values(reponse=stockage.codec.encoder(ack_legacy)))

    replay = equipe["employe"].appeler(
        "m6_declarer_materiaux_avec_preuves_appareil", args, cle=key, horodatage_appareil=timestamp,
    )
    assert replay.enveloppe["rejoue"] is True
    replay_ref = replay.metier["resultat"]["preuves"][0]["reference_mouvement"]
    assert replay_ref == movement_ref
    assert replay.metier["resultat"]["preuves"][0]["reference_preuve"]["hash_maillon"] is None
    with stockage.transaction() as cnx:
        mutation_apres = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == key,
        )).mappings().one()
        assert stockage.codec.decoder(mutation_apres["reponse"]) == ack_legacy
        assert len(list(stockage.maillons("m06-material-control", "principal"))) == 1


def test_proof_replay_after_role_revocation_is_still_blocked_before_cache_read(equipe, moteur):
    with stockage.transaction():
        refus = livre_prix.enregistrer_prix(
            "gouttiere-alu-5po-fictif", "fournisseur-preuves-revocation-fictif", 12.34, "CAD", "2026-01-01",
            stockage.maillons("m06-material-control", "livre_prix"), "DOC-PREUVES-REVOCATION-FICTIF", "pi",
        )[1]
        assert refus is None
    chantier = preparer_chantier(
        moteur.departements, suffixe="employee-proof-role-revoked-fictif", technicien="etienne",
        debut=moteur.horloge.maintenant,
    )
    app = AppEmploye(moteur, equipe["employe"], chantier, derive_appareil_s=0)
    wct_id = app.journee_jusqu_a_la_completion().resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    args = {
        "wct_id": wct_id,
        "formulaire": {
            "wct_id": wct_id, "intervention_id": chantier.intervention_id, "chantier_id": chantier.chantier_id,
            "lignes_materiaux": [{"type_ligne": "perte", "materiau_id": "gouttiere-alu-5po-fictif",
                                  "quantite": 1.0, "unite": "pi"}],
        },
        "preuves_lignes": [{"position_ligne": 0, "note": "Observation fictive.", "photos": []}],
    }
    timestamp, key = app.heure_appareil(), "employee-proof-role-revoked-cache-fictif"
    ack = equipe["employe"].appeler(
        "m6_declarer_materiaux_avec_preuves_appareil", args, cle=key, horodatage_appareil=timestamp,
    )
    assert ack.metier["accepte"] is True, ack.corps
    with stockage.transaction() as cnx:
        ligne_ack = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == key,
        )).mappings().one()
        reponse_avant = ligne_ack["reponse"]
        taille_principal = len(stockage.maillons("m06-material-control", "principal"))
        taille_preuves = len(stockage.maillons("m06-material-control", "preuves_pertes_bris"))
        cnx.execute(delete(ROLES_PERSONNES).where(
            ROLES_PERSONNES.c.identifiant == "etienne", ROLES_PERSONNES.c.role == "employee",
        ))

    replay = equipe["employe"].appeler(
        "m6_declarer_materiaux_avec_preuves_appareil", args, cle=key, horodatage_appareil=timestamp,
    )
    assert replay.enveloppe["ok"] is False
    assert replay.enveloppe["erreur"] == "REJ-M6-PREUVES-IDENTITE-INVALIDE"
    with stockage.transaction() as cnx:
        ligne_apres = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == key,
        )).mappings().one()
        assert ligne_apres["reponse"] == reponse_avant
        assert len(stockage.maillons("m06-material-control", "principal")) == taille_principal
        assert len(stockage.maillons("m06-material-control", "preuves_pertes_bris")) == taille_preuves
