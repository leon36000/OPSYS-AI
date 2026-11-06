from __future__ import annotations

import copy
import json

from harnais_e2e import PorteAppareil, iso
from harnais_e2e_chantier import AppEmploye, preparer_chantier
from sqlalchemy import insert, select, update

from opsys import cli, stockage
from opsys.stockage.schema import MUTATIONS_APPLIQUEES


def _declarer_simple(moteur, equipe, suffixe):
    chantier = preparer_chantier(
        moteur.departements, suffixe=suffixe, technicien="etienne", debut=moteur.horloge.maintenant,
    )
    app = AppEmploye(moteur, equipe["employe"], chantier, derive_appareil_s=0)
    completion = app.journee_jusqu_a_la_completion()
    wct_id = completion.resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    ack = app.declarer_materiaux(wct_id, 3.0)
    assert ack.metier["accepte"] is True, ack.corps
    return app, chantier, wct_id, app.appels[-1], ack


def _ack(device_id, cle):
    with stockage.transaction() as cnx:
        return cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == device_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == cle,
        )).mappings().one()


def _lier_a_julie(moteur, equipe, monkeypatch, *, creer=True):
    if creer:
        moteur.creer_personne("julie", "Julie fictive", ["employee"], monkeypatch)
    device_id = equipe["employe"].appareil_id
    assert cli.main([
        "appareils", "appairer", device_id, "--personne", "julie", "--role", "employee",
        "--config-dir", str(moteur.config_dir),
    ]) == 0
    return PorteAppareil(moteur, device_id)


def test_rejeu_simple_m6_est_lie_auteur_et_wct_et_conserve_les_acks(equipe, moteur, monkeypatch):
    app, chantier, wct_id, appel, _ = _declarer_simple(moteur, equipe, "identity-binding-individual")
    ligne_avant = _ack(equipe["employe"].appareil_id, appel.cle)
    assert ligne_avant["personne_origine"] == "etienne"
    reponse_stockee = ligne_avant["reponse"]
    taille_registre = len(stockage.maillons("m06-material-control", "principal"))

    # Le rejeu idempotent du même signataire/chantier reste consultable.
    reprise_meme_auteur = app.rejouer(appel)
    assert reprise_meme_auteur.enveloppe["rejoue"] is True
    assert reprise_meme_auteur.metier["accepte"] is True

    julie = _lier_a_julie(moteur, equipe, monkeypatch)
    reprise_autre_auteur = julie.appeler(
        appel.outil, appel.args, cle=appel.cle, horodatage_appareil=appel.horodatage_appareil,
    )
    assert reprise_autre_auteur.enveloppe == {
        "ok": False,
        "erreur": "REJ-IDENTITE-APPAREIL-INVALIDE",
        "details": "Identité ou auteur de déclaration non vérifiable ; aucune confirmation en cache restituée.",
    }

    # Le nouvel auteur ne reçoit pas non plus le détail du conflit d'arguments de l'ancien claim.
    arguments_differents = copy.deepcopy(appel.args)
    arguments_differents["formulaire"]["lignes_materiaux"][0]["quantite"] = 4.0
    conflit_autre_auteur = julie.appeler(
        appel.outil, arguments_differents, cle=appel.cle, horodatage_appareil=appel.horodatage_appareil,
    )
    assert conflit_autre_auteur.enveloppe["erreur"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    with stockage.transaction() as cnx:
        ligne_apres = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel.cle,
        )).mappings().one()
        assert ligne_apres["reponse"] == reponse_stockee
        assert ligne_apres["personne_origine"] == "etienne"
        assert len(stockage.maillons("m06-material-control", "principal")) == taille_registre
    assert chantier.chantier_id != ""
    assert wct_id == appel.args["wct_id"]

    # Pour le même auteur, l'ancienne sémantique du conflit d'idempotence est conservée.
    assert cli.main([
        "appareils", "appairer", equipe["employe"].appareil_id, "--personne", "etienne", "--role", "employee",
        "--config-dir", str(moteur.config_dir),
    ]) == 0
    etienne = PorteAppareil(moteur, equipe["employe"].appareil_id)
    conflit_meme_auteur = etienne.appeler(
        appel.outil, arguments_differents, cle=appel.cle, horodatage_appareil=appel.horodatage_appareil,
    )
    assert conflit_meme_auteur.enveloppe["erreur"] == "mutation_conflit"
    with stockage.transaction() as cnx:
        ligne_finale = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel.cle,
        )).mappings().one()
        assert ligne_finale["reponse"] == reponse_stockee
        assert len(stockage.maillons("m06-material-control", "principal")) == taille_registre


def test_rejeu_simple_m6_refuse_legacy_sans_auteur_sans_recrire_ack(equipe, moteur):
    app, _, _, appel, _ = _declarer_simple(moteur, equipe, "identity-binding-legacy-null")
    with stockage.transaction() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel.cle,
        ).values(personne_origine=None))
        reponse_avant = cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel.cle,
        )).scalar_one()
        taille_registre = len(stockage.maillons("m06-material-control", "principal"))

    reprise = app.rejouer(appel)
    assert reprise.enveloppe["erreur"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel.cle,
        )).mappings().one()
        assert ligne["reponse"] == reponse_avant
        assert ligne["personne_origine"] is None
        assert len(stockage.maillons("m06-material-control", "principal")) == taille_registre


def test_rejeu_simple_m6_equipe_refuse_autre_membre_meme_acces(equipe, moteur, monkeypatch, tmp_path):
    from test_equipe_declaree_appareil import EQUIPE, _journee, declarer_profil, profil_equipes

    suffixe = "identity-binding-team"
    chantier, wct_id, _ = _journee(
        moteur, equipe, ("etienne", "julie"), "etienne", monkeypatch, tmp_path, suffixe,
    )
    appel_cle = f"mat-etienne-{suffixe}"
    arguments = {
        "wct_id": wct_id,
        "formulaire": {
            "wct_id": wct_id,
            "intervention_id": chantier.intervention_id,
            "chantier_id": chantier.chantier_id,
            "lignes_materiaux": [{
                "type_ligne": "prevu", "materiau_id": "gouttiere-alu-5po-fictif", "quantite": 40.0,
                "unite": "pi", "quantite_estimee": 40.0,
            }],
        },
    }
    with stockage.transaction() as cnx:
        ligne_avant = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel_cle,
        )).mappings().one()
        assert ligne_avant["personne_origine"] == "etienne"
        reponse_avant = ligne_avant["reponse"]
        taille_registre = len(stockage.maillons("m06-material-control", "principal"))

    julie = _lier_a_julie(moteur, equipe, monkeypatch, creer=False)
    # Julie a encore accès au même WCT par son appartenance à l'équipe : seule la liaison d'auteur doit refuser.
    reprise = julie.appeler(
        "m6_declarer_materiaux_utilises", arguments, cle=appel_cle,
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert reprise.enveloppe["erreur"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    with stockage.transaction() as cnx:
        ligne_apres = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel_cle,
        )).mappings().one()
        assert ligne_apres["reponse"] == reponse_avant
        assert len(stockage.maillons("m06-material-control", "principal")) == taille_registre

    # L'auteur d'origine perd ensuite son affectation : même son propre ACK n'est plus servi par le WCT courant.
    assert cli.main([
        "appareils", "appairer", equipe["employe"].appareil_id, "--personne", "etienne", "--role", "employee",
        "--config-dir", str(moteur.config_dir),
    ]) == 0
    declarer_profil(tmp_path, "equipes", profil_equipes(EQUIPE, ["julie"], {
        "gouttieres": {"duree_min": 90, "competences": ["gouttieres"]},
    }))
    etienne = PorteAppareil(moteur, equipe["employe"].appareil_id)
    reprise_apres_retrait = etienne.appeler(
        "m6_declarer_materiaux_utilises", arguments, cle=appel_cle,
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert reprise_apres_retrait.enveloppe["erreur"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    with stockage.transaction() as cnx:
        ligne_finale = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == equipe["employe"].appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == appel_cle,
        )).mappings().one()
        assert ligne_finale["reponse"] == reponse_avant
        assert len(stockage.maillons("m06-material-control", "principal")) == taille_registre


def test_rejeu_declaration_m6_avec_preuves_refuse_autre_membre_meme_equipe(
    equipe, moteur, monkeypatch, tmp_path
):
    import sys
    from pathlib import Path

    from m6_material_control import outils as outils_m6

    from opsys import equipes
    from opsys.contexte import IdentiteAppelante
    from opsys.outils import executer_atomique

    tests_m6 = Path(__file__).resolve().parents[2] / "departments/m06-material-control/tests"
    sys.path.insert(0, str(tests_m6))
    try:
        import test_preuves_pertes_bris_appareil as preuve_tests
    finally:
        sys.path.remove(str(tests_m6))

    moteur.creer_personne("bruno", "Bruno fictif", ["employee"], monkeypatch)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    team_id = "eq-rejeu-preuves-identite-fictif"
    equipes.enregistrer_equipes({
        "liste": [{
            "id": team_id,
            "membres": ["etienne", "bruno"],
            "competences": ["gouttieres"],
            "depot": {"id": "depot-preuves-fictif", "latitude_microdegres": 45735000,
                      "longitude_microdegres": -73455000},
            "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}],
        }],
        "services": {"gouttieres": {"duree_min": 90, "competences": ["gouttieres"]}},
    })

    # Le WCT est publié par le producteur M4 avec une équipe déclarée; les deux membres y ont accès.
    identite_initiale = preuve_tests.fx.EMP
    preuve_tests.fx.EMP = IdentiteAppelante(team_id, "employee")
    try:
        intervention_id, wct_id = preuve_tests.fx._seed()
    finally:
        preuve_tests.fx.EMP = identite_initiale

    bon = {
        "po_id": "PO-REJEU-PREUVES-IDENTITE-FICTIF", "chantier_id": intervention_id,
        "lignes_demandees": [{"materiau_id": preuve_tests.fx.MAT, "quantite_demandee": 100}],
        "horodatage": "2026-01-01T00:00:00Z",
    }
    reception = {
        "po_id": bon["po_id"], "chantier_id": intervention_id,
        "lignes_recues": [{"materiau_id": preuve_tests.fx.MAT, "quantite_recue": 100}],
        "horodatage": "2026-01-02T00:00:00Z",
    }
    resultat_reception = executer_atomique(
        next(o for o in outils_m6.outils() if o.nom == "m6_receptionner_commande"),
        {"bon_demande": bon, "reception_po": reception, "catalogue_materiaux": {
            "version": "FICTIF", "unite_monetaire": "CAD",
            "postes": {preuve_tests.fx.MAT: {"cout_unitaire": 2, "libelle": "matériau fictif"}},
        }},
    )
    assert resultat_reception["ok"] and resultat_reception["resultat"]["accepte"], resultat_reception

    arguments = {
        "wct_id": wct_id,
        "formulaire": {
            "wct_id": wct_id, "intervention_id": intervention_id, "chantier_id": intervention_id,
            "lignes_materiaux": [{"type_ligne": "perte", "materiau_id": preuve_tests.fx.MAT,
                                  "quantite": 1.0, "unite": "pi"}],
        },
        "preuves_lignes": [{"position_ligne": 0, "note": "Perte fictive constatée par Étienne.", "photos": []}],
    }
    appareil = equipe["employe"]
    appareil_id = appareil.appareil_id
    cle = "identity-binding-proof-team"
    horodatage = iso(moteur.horloge.maintenant)
    confirmation = appareil.appeler(
        "m6_declarer_materiaux_avec_preuves_appareil", arguments, cle=cle, horodatage_appareil=horodatage,
    )
    assert confirmation.metier["accepte"] is True, confirmation.corps
    with stockage.transaction() as cnx:
        ligne_avant = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == cle,
        )).mappings().one()
        assert ligne_avant["personne_origine"] == "etienne"
        reponse_avant = ligne_avant["reponse"]
        principal = len(stockage.maillons("m06-material-control", "principal"))
        preuves = len(stockage.maillons("m06-material-control", "preuves_pertes_bris"))

    assert cli.main([
        "appareils", "appairer", appareil_id, "--personne", "bruno", "--role", "employee",
        "--config-dir", str(moteur.config_dir),
    ]) == 0
    bruno = PorteAppareil(moteur, appareil_id)
    reprise = bruno.appeler(
        "m6_declarer_materiaux_avec_preuves_appareil", arguments, cle=cle, horodatage_appareil=horodatage,
    )
    assert reprise.enveloppe == {
        "ok": False,
        "erreur": "REJ-IDENTITE-APPAREIL-INVALIDE",
        "details": "Identité ou auteur de déclaration non vérifiable ; aucune confirmation en cache restituée.",
    }
    with stockage.transaction() as cnx:
        ligne_apres = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == appareil_id,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == cle,
        )).mappings().one()
        assert ligne_apres["reponse"] == reponse_avant
        assert len(stockage.maillons("m06-material-control", "principal")) == principal
        assert len(stockage.maillons("m06-material-control", "preuves_pertes_bris")) == preuves


def test_conflit_inter_outil_m6_ne_revele_pas_le_nom_de_l_ancien_outil(equipe, moteur, monkeypatch):
    from opsys import idempotence

    _app, _chantier, wct_id, _appel, _ack_response = _declarer_simple(
        moteur, equipe, "identity-binding-other-tool",
    )
    device_id = equipe["employe"].appareil_id
    key = "claim-other-tool-fictif"
    arguments = {"wct_id": wct_id, "formulaire": {"wct_id": wct_id}}
    fake_tool = "outil_hors_portee_fictif"
    with stockage.transaction() as cnx:
        cnx.execute(insert(MUTATIONS_APPLIQUEES).values(
            appareil=device_id,
            cle_idempotence=key,
            outil=fake_tool,
            empreinte_arguments=idempotence.empreinte_arguments(arguments),
            reponse=stockage.codec.encoder({"ok": True, "resultat": {"secret_fictif": "ne_pas_restituer"}}),
            horodatage_appareil=iso(moteur.horloge.maintenant),
            recu_le=iso(moteur.horloge.maintenant),
            statut="ok",
            personne_origine="etienne",
        ))
    julie = _lier_a_julie(moteur, equipe, monkeypatch)
    reponse = julie.appeler(
        "m6_declarer_materiaux_utilises", arguments, cle=key,
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert reponse.enveloppe == {
        "ok": False,
        "erreur": "mutation_conflit",
        "details": "Clé d'idempotence déjà utilisée ; aucune réponse en cache restituée.",
    }
    assert fake_tool not in json.dumps(reponse.enveloppe)
    assert "secret_fictif" not in json.dumps(reponse.enveloppe)
def test_rejeu_m6_masque_aussi_une_collision_arrivee_apres_le_precheck(equipe, moteur, monkeypatch):
    from opsys import idempotence

    app, _chantier, _wct_id, appel, _ack_response = _declarer_simple(
        moteur, equipe, "identity-binding-race",
    )
    julie = _lier_a_julie(moteur, equipe, monkeypatch)
    new_key = "identity-binding-race-cross-tool"
    args = copy.deepcopy(appel.args)
    fake_tool = "outil_concurrent_hors_portee_fictif"
    original_reclamer = idempotence.reclamer

    def ajouter_claim_concurrent_puis_reclamer(cnx, meta, nom_outil, arguments, recu_le):
        if meta.cle == new_key:
            cnx.execute(insert(MUTATIONS_APPLIQUEES).values(
                appareil=meta.appareil,
                cle_idempotence=meta.cle,
                outil=fake_tool,
                empreinte_arguments=idempotence.empreinte_arguments(arguments),
                reponse=stockage.codec.encoder({"ok": True, "resultat": {"secret_fictif": "ne_pas_restituer"}}),
                horodatage_appareil=meta.horodatage_appareil,
                recu_le=recu_le.isoformat(timespec="seconds"),
                statut="ok",
                personne_origine="etienne",
            ))
        return original_reclamer(cnx, meta, nom_outil, arguments, recu_le)

    monkeypatch.setattr(idempotence, "reclamer", ajouter_claim_concurrent_puis_reclamer)
    reponse = julie.appeler(
        appel.outil, args, cle=new_key, horodatage_appareil=appel.horodatage_appareil,
    )
    assert reponse.enveloppe["erreur"] == "mutation_conflit"
    assert fake_tool not in json.dumps(reponse.enveloppe)
    assert "secret_fictif" not in json.dumps(reponse.enveloppe)
