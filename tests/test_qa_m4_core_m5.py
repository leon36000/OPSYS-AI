"""QA exploratoire à usage local : lien réel M3/M4/M5, sources fictives."""

import importlib.util
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from m4_field_ops import (
    calendrier_civil,
    cedule,
    cedule_tournees,
    ecarts,
    equipes_pointees_v3,
    etats,
    outbox,
    preparation,
    visites_chantier,
)
from m4_field_ops.registre import Registre

from opsys import contexte, evenements, stockage
from opsys.outils import executer_atomique

spec = importlib.util.spec_from_file_location(
    "qa_preparation_console", Path(__file__).with_name("test_console_preparation_chantier.py")
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, catalogue, affaire = f.client_crm, f.catalogue, f.affaire

spec_cf = importlib.util.spec_from_file_location(
    "qa_m4_cf", Path(__file__).parents[1] / "departments/m04-field-ops/tests/conftest.py"
)
cf = importlib.util.module_from_spec(spec_cf)
spec_cf.loader.exec_module(cf)
deposer_photo_test = cf.deposer_photo_test

spec_v2 = importlib.util.spec_from_file_location(
    "qa_v2_m4", Path(__file__).parents[1] / "departments/m04-field-ops/tests/test_temps_certifies_v2.py"
)
v2 = importlib.util.module_from_spec(spec_v2)
spec_v2.loader.exec_module(v2)


@pytest.fixture(autouse=True)
def devis_avec_chantier(monkeypatch):
    import os

    if os.environ.get("QA_CASE") in ("wct_avant_devis", "ordre_TDW", "ordre_WDT", "ordre_WTD", "ordre_TWD"):
        drainer_original = f.b._drainer

        def drainer_sans_m5(deps, *args, **kwargs):
            return drainer_original({k: v for k, v in deps.items() if k != "m05-financecore"}, *args, **kwargs)

        monkeypatch.setattr(f.b, "_drainer", drainer_sans_m5)

    def creer(deps, lead_id, devis_id):
        m3 = f.b._outils(deps, "m03-estimation")
        f.b._ok(
            executer_atomique(
                m3["m3_creer_devis"],
                {
                    "devis_id": devis_id,
                    "lead_id": lead_id,
                    "chantier_id": "DEPOT-FICTIF",
                    "lignes": [
                        {
                            "description": "Gouttières fictives",
                            "quantite": "40",
                            "unite": "pi",
                            "cout_unitaire": "8.00",
                            "reference_besoin_materiau": f.b.MATERIAU_ID,
                        },
                        {
                            "description": "Main-d’œuvre fictive",
                            "quantite": "1",
                            "unite": "forfait",
                            "cout_unitaire": "160.00",
                            "reference_besoin_materiau": None,
                        },
                    ],
                    "taux_marge": "0.25",
                    "horodatage": "2026-09-29T15:00:00-04:00",
                    "prix_total": "600.00",
                },
            )
        )
        f.b._ok(
            executer_atomique(
                m3["m3_marquer_devis_accepte"],
                {"devis_id": devis_id, "approbateur": "Admin fictif", "horodatage": f.b.ACCEPTE_LE},
            )
        )
        return f"m3-devis-accepte-{devis_id}"

    monkeypatch.setattr(f.b, "_devis_accepte", creer)


def test_probe_preparation(affaire, session, deposer_photo_test, catalogue, monkeypatch):
    m6 = f.b._outils(affaire["deps"], "m06-material-control")
    bon = dict(
        po_id="PO-QA-FICTIF",
        chantier_id="DEPOT-FICTIF",
        horodatage=f.b.ACCEPTE_LE,
        lignes_demandees=[dict(materiau_id=f.b.MATERIAU_ID, quantite_demandee=40)],
    )
    reception = dict(
        po_id=bon["po_id"],
        chantier_id=bon["chantier_id"],
        horodatage=f.b.ACCEPTE_LE,
        lignes_recues=[dict(materiau_id=f.b.MATERIAU_ID, quantite_recue=40)],
    )
    catalogue_fictif = dict(
        version="v1", unite_monetaire="CAD", postes={f.b.MATERIAU_ID: dict(cout_unitaire=8, libelle="FICTIF")}
    )
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(f.AUTH.utilisateur, "admin", source="console")):
        f.b._ok(
            executer_atomique(
                m6["m6_receptionner_commande"],
                dict(bon_demande=bon, reception_po=reception, catalogue_materiaux=catalogue_fictif),
            )
        )
    assert f.b._drainer(affaire["deps"], f.b.DEBUT)["echecs"] == 0
    spec_prep = importlib.util.spec_from_file_location(
        "qa_prep_m4", Path(__file__).parents[1] / "departments/m04-field-ops/tests/test_preparation.py"
    )
    prep_test = importlib.util.module_from_spec(spec_prep)
    spec_prep.loader.exec_module(prep_test)
    with session():
        reg = Registre(stockage.maillons("m04-field-ops", "principal"))
        inscriptions = [x for x in etats.lister_interventions(reg) if x["devis_id"] == affaire["devis"]]
        assert len(inscriptions) == 1
        iid = inscriptions[0]["intervention_id"]
        pure = v2._base.fixture.pur
        from opsys import equipes

        equipes.enregistrer_equipes({"liste": [{**e, "membres": [e["id"] + ".fictif"]} for e in pure._aide._equipes()]})
        positions = pure._aide.Positions({affaire["lead"]: pure._aide.SITES["ch-01"]})
        profil = prep_test._profil(liste=[{**x, "membres": ["fictif"]} for x in pure._aide._equipes()])
        prep, refus = preparation.evaluer(reg, iid, positions, prep_test._lecteur(profil), prep_test._lecteur_meteo())
        assert refus is None
        assert prep["pret"]
        accuse, refus = etats.transitionner(iid, "planifiee", reg, "2030-01-01T00:00:00+00:00", preparation=prep)
        assert refus is None, refus
        args = pure._aide._arguments({affaire["lead"]: iid})
        args.pop("durees_par_type_travaux")
        args.pop("competences_par_type_travaux")
        args["durees_par_service"] = {"gouttieres": 150}
        args["competences_par_service"] = {"gouttieres": []}
        resultat, refus = cedule_tournees.proposer(reg, args, positions, pure.HORODATAGE, moteur="dp")
        assert refus is None, refus
        plan1 = resultat["plan_id"]
        assert cedule_tournees.appliquer(reg, plan1, positions, pure.HORODATAGE, "admin.fictif")[1] is None
        calendrier_civil.confirmer(reg, plan1, {"0": "2030-06-03"}, 0, "admin.fictif", pure.HORODATAGE)
        ligne = calendrier_civil.lire_semaine(reg, "2030-06-03")["interventions"][0]
        ancre = {k: ligne[k] for k in v2._base.fixture.CHAMPS_ANCRE}
        visites = Registre(stockage.maillons("m04-field-ops", "visites_chantier"))
        ref = {
            cedule.tokeniser_ville("sel-fictif", "Laval"): {"latitude": 45.75, "longitude": -73.45, "rayon_km": 25.0}
        }

        def session_visite(ancre_jour, revision, jour, pauses):
            prev = v2._base.ecrire(
                reg, visites, ancre_jour, revision=revision, cle=f"qa-{jour}", heure=f"{jour}T07:30:00-04:00"
            )
            equipe = v2._base.fixture.notes._creneau(v2._base.fixture.notes._sources(reg), ancre_jour)["equipe_id"]
            if jour == "2030-06-03":
                # Un compte personne partage le même identifiant que cette équipe fictive.
                # Il ne devient pas présent et ne constitue pas la preuve du pointage d'équipe.
                from opsys import identite as identites

                identites.creer_personne(
                    stockage.connexion_courante(), equipe, "Homonyme fictif", "Fictif#12345678", roles=["employee"]
                )
                assert identites.personne(stockage.connexion_courante(), equipe) is not None
            assign = {"intervention_id": iid, "technicien_id": equipe}
            visites_chantier.ouvrir(reg, visites, prev["visite_id"], f"{jour}T08:00:00-04:00")
            assert etats.transitionner(iid, "en_route", reg, f"{jour}T08:30:00-04:00", assignation=assign)[1] is None
            fenetre = {"debut": f"{jour}T08:00:00-04:00", "fin": f"{jour}T18:00:00-04:00"}
            actions = [("arrivee", "09:00:00"), *pauses, ("depart", "12:00:00" if pauses else "13:00:00")]
            for action, heure in actions:
                instant = datetime.fromisoformat(f"{jour}T{heure}-04:00")
                arguments = dict(
                    intervention_id=iid,
                    technicien_id=equipe,
                    action=action,
                    horodatage=instant.isoformat(),
                    fix_gps=None,
                    attestation={"fictif": True, "appareil_id": "fictif"},
                    fenetre_travail=fenetre,
                    referentiel_villes=ref,
                    ville="Laval",
                    sel="sel-fictif",
                )
                with (
                    contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin", source="console")),
                    contexte.appeler_en_tant_que("m04-field-ops", origine="console"),
                    contexte.receptionne_de(contexte.HorodatageAppareil("console:admin.fictif", instant, instant)),
                ):
                    recu = equipes_pointees_v3.enregistrer(
                        stockage.connexion_courante(),
                        arguments,
                        prev["visite_id"],
                        equipe,
                        f"{jour}-{action}",
                        equipes_pointees_v3.empreinte_sources(stockage.connexion_courante()),
                    )
                if action in ("arrivee", "depart"):
                    demande = next(
                        m
                        for m in reg.lire()
                        if m.get("type_entree") == "demande_revue" and m.get("pointage_ligne_id") == recu["pointage_id"]
                    )
                    _, erreur = ecarts.resoudre_demande(demande["demande_id"], "validee", instant.isoformat(), reg)
                    assert erreur is None, erreur
            visites_chantier.fermer(reg, visites, prev["visite_id"], f"{jour}T{actions[-1][1][:2]}:01:00-04:00")
            return equipe

        equipe1 = session_visite(ancre, 0, "2030-06-03", [("pause_debut", "10:00:00"), ("pause_fin", "10:30:00")])
        assert (
            etats.transitionner(
                iid, "reportee", reg, "2030-06-03T12:02:00-04:00", motif="meteo", registre_visites=visites
            )[1]
            is None
        )
        assert etats.transitionner(iid, "planifiee", reg, "2030-06-03T12:03:00-04:00")[1] is None
        equipe2 = next(x for x in pure._aide._equipes() if x["id"] != equipe1)
        args["equipes"] = [equipe2]
        plan2, refus = cedule_tournees.proposer(reg, args, positions, "2030-06-03T12:04:00-04:00", moteur="dp")
        assert refus is None, refus
        assert (
            cedule_tournees.appliquer(reg, plan2["plan_id"], positions, "2030-06-03T12:04:00-04:00", "admin.fictif")[1]
            is None
        )
        datee = calendrier_civil.confirmer(
            reg, plan2["plan_id"], {"0": "2030-06-07"}, 0, "admin.fictif", "2030-06-03T12:05:00-04:00"
        )
        ancre2 = {
            "intervention_id": iid,
            "plan_id": plan2["plan_id"],
            "source_application_id": next(
                m["source_application_id"] for m in reg.lire() if m.get("ligne_id") == datee["ligne_id"]
            ),
            "source_ligne_id": datee["ligne_id"],
        }
        equipe2_id = session_visite(ancre2, 1, "2030-06-07", [])

    # Complétion par l'outil propriétaire : photo réellement déposée en fixture.
    m4 = {o.nom: o for o in affaire["deps"]["m04-field-ops"].charger_outils()}
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin", source="console")),
        contexte.appeler_en_tant_que("m04-field-ops", origine="console"),
    ):
        photo = deposer_photo_test(m4)
        completion = executer_atomique(
            m4["m4_completer_intervention"],
            dict(
                intervention_id=iid,
                horodatage="2030-06-07T13:02:00-04:00",
                preuves_completion=dict(checklist_complete=True, photos_apres=[photo], notes="FICTIF", signature=None),
            ),
        )
    assert completion["ok"] and completion["resultat"]["accepte"], completion
    wct_id = completion["resultat"]["resultat"]["wct_id"]
    with session():
        reg = Registre(stockage.maillons("m04-field-ops", "principal"))
        _, erreur = outbox.resoudre_revue_completion(
            iid, "verifiee", "2030-06-07T13:04:00-04:00", reg, motif="Revue fictive"
        )
        assert erreur is None, erreur
    assert evenements.charge_publiee("m4.travaux_termines", wct_id)["devis_id"] == affaire["devis"]
    from m4_field_ops import temps_certifies_v3

    with (
        session() as cnx,
        contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin", source="console")),
        contexte.appeler_en_tant_que("m04-field-ops", origine="console"),
    ):
        projection = temps_certifies_v3.projeter(cnx, iid, wct_id)["projection"]
        premiere = projection["visites"][0]
        assert premiere["equipe_pointee"]["identifiant"] == equipe1
        assert premiere["equipe_pointee"]["statut"] == "identifiee"
        assert premiere["presence_individuelle"]["statut"] == "inconnue"
    # Deux tarifs fictifs établis par le vrai port de déclaration M5.
    import os

    from m5_financecore import outils as m5

    def enregistrer_tarifs():
        with (
            session(),
            contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin", source="console")),
            contexte.appeler_en_tant_que("m05-financecore", origine="console"),
        ):
            for index, (equipe, taux) in enumerate(((equipe1, "100"), (equipe2_id, "120"))):
                snapshot = m5._lire_tarifs_equipes()
                m5._inscrire_tarif_equipe(
                    dict(
                        equipe_id=equipe,
                        taux=taux,
                        unite="heure-equipe",
                        devise="CAD",
                        source="tarif-fictif",
                        version="1",
                        date_effet="2030-01-01",
                        date_fin="2030-12-31",
                        remplace_id=None,
                    ),
                    mutation_id=f"FICTIF-AVANT-{index}",
                    source_attendue=snapshot["source"],
                )

    ordre = os.environ.get("QA_CASE", "")
    if ordre not in ("ordre_DWT", "ordre_WDT", "ordre_WTD"):
        enregistrer_tarifs()
    # Politique fictive uniquement dans cette base isolée.
    import os
    import time

    from sqlalchemy import insert, select

    from opsys.stockage.schema import OPSYS_INSTANCE, SERVICE_POLITIQUES

    with session() as cnx:
        instance_id = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
        if os.environ.get("QA_NEGATIVE") != "no_policy":
            cnx.execute(
                insert(SERVICE_POLITIQUES).values(
                    instance_id=instance_id,
                    consommateur="m05-financecore",
                    operation="m4.verifier_v3",
                    revision=1,
                    active=True,
                    expire_le=int(time.time())
                    + (10 * 86400 if os.environ.get("QA_CASE", "").startswith(("wct_avant_devis", "ordre_")) else 120),
                )
            )
    import os

    from sqlalchemy import update

    from opsys import service_capability as sc
    from opsys.stockage.schema import EVENEMENTS_SORTANTS, JOURNAL

    mode = os.environ.get("QA_CASE", "positif")
    if mode.startswith("ordre_"):
        import datetime as dt_qa

        from opsys.evenements import repartiteur
        from opsys.stockage.schema import EVENEMENTS_RECUS, WCT_ATTENTES

        moment = dt_qa.datetime.now(dt_qa.UTC)
        with session() as cnx:
            wct_evt = dict(
                cnx.execute(select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == wct_id))
                .mappings()
                .one()
            )
            devis_evt = dict(
                cnx.execute(
                    select(EVENEMENTS_SORTANTS).where(
                        EVENEMENTS_SORTANTS.c.evenement_id == "m3-devis-accepte-" + affaire["devis"]
                    )
                )
                .mappings()
                .one()
            )
        consommateurs = affaire["deps"]["m05-financecore"].charger_consommateurs()

        def livrer_devis():
            assert (
                repartiteur._livrer_une_paire(devis_evt, "m05-financecore", consommateurs["m3.devis_accepte"], moment)
                == "traite"
            )

        def livrer_wct():
            return repartiteur._livrer_une_paire(
                wct_evt, "m05-financecore", consommateurs["m4.travaux_termines"], moment
            )

        if mode == "ordre_TDW":
            livrer_devis()
        if mode in ("ordre_WDT", "ordre_WTD", "ordre_TWD"):
            assert livrer_wct() == "attente"
            with session() as cnx:
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "attente"
                )
                assert len(list(stockage.maillons("m05-financecore", "wct_recus"))) == 1
            if mode == "ordre_WTD":
                enregistrer_tarifs()
            livrer_devis()
            if mode == "ordre_WDT":
                enregistrer_tarifs()
            plus_tard = moment + dt_qa.timedelta(days=2)
            monkeypatch.setattr(sc, "time", lambda: plus_tard.timestamp())
            reprise = evenements.repartir(
                {"m05-financecore": affaire["deps"]["m05-financecore"]}, maintenant=plus_tard.isoformat()
            )
            assert reprise["echecs"] == 0
            with session() as cnx:
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "terminee"
                )
        else:
            assert livrer_wct() == "traite"
        with session() as cnx:
            recu_wct = dict(
                cnx.execute(
                    select(EVENEMENTS_RECUS).where(
                        EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == "m05-financecore"
                    )
                )
                .mappings()
                .one()
            )
            traces_service = list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))
            assert recu_wct["statut"] == "traite" and len(traces_service) == 1
            trace = list(stockage.maillons("m05-financecore", "rentabilite"))[-1]
            main = trace["rentabilite"]["cout_reel"]["main_d_oeuvre"]["cout"]
            if mode == "ordre_DWT":
                assert main is None and trace["verdict"] == "PARTIELLE"
            else:
                assert main == Decimal("730.00")
        if mode == "ordre_DWT":
            enregistrer_tarifs()
            assert livrer_wct() is None
            with session() as cnx:
                assert (
                    dict(
                        cnx.execute(
                            select(EVENEMENTS_RECUS).where(
                                EVENEMENTS_RECUS.c.evenement_id == wct_id,
                                EVENEMENTS_RECUS.c.consommateur == "m05-financecore",
                            )
                        )
                        .mappings()
                        .one()
                    )
                    == recu_wct
                )
                assert list(stockage.maillons("m05-financecore", "rentabilite_service_v1")) == traces_service
        return
    if mode == "wct_avant_devis":
        import datetime as dt_qa

        from opsys.evenements import repartiteur

        with session() as cnx:
            evenement = dict(
                cnx.execute(select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == wct_id))
                .mappings()
                .one()
            )
            assert not list(stockage.maillons("m05-financecore", "devis_recus"))
        consumer = affaire["deps"]["m05-financecore"].charger_consommateurs()["m4.travaux_termines"]
        moment = dt_qa.datetime.now(dt_qa.UTC)
        cas_attente = os.environ.get("QA_NEGATIVE", "")
        if cas_attente in ("quota", "queue_passtarvation", "review_readers"):
            from opsys.stockage.schema import EVENEMENTS_RECUS, WCT_ATTENTES

            nombre_faux = 1000 if cas_attente == "quota" else (199 if cas_attente == "review_readers" else 200)
            fake_events = [
                dict(
                    evenement_id=f"{i + 1:064x}",
                    type_evenement="m4.travaux_termines",
                    producteur="m04-field-ops",
                    charge="{}",
                    cree_le=moment.isoformat(),
                )
                for i in range(nombre_faux)
            ]
            fake_waits = [
                dict(
                    evenement_id=f"{i + 1:064x}",
                    consommateur="m05-financecore",
                    instance_id=instance_id,
                    devis_id=f"devis-{i}",
                    lead_id=f"lead-{i}",
                    recu_sha256="0" * 64,
                    etat="attente",
                    cree_epoch=int(moment.timestamp()),
                    expire_epoch=int(moment.timestamp()) + 604800,
                    revision_politique=1,
                    source_m3=None,
                )
                for i in range(nombre_faux)
            ]
            with session() as cnx:
                cnx.execute(insert(EVENEMENTS_SORTANTS), fake_events)
                cnx.execute(
                    insert(EVENEMENTS_RECUS),
                    [
                        dict(evenement_id=f"{i + 1:064x}", consommateur="m05-financecore", statut="echec", tentatives=0)
                        for i in range(nombre_faux)
                    ],
                )
                cnx.execute(insert(WCT_ATTENTES), fake_waits)
        temps_livraison = moment.replace(tzinfo=None) if cas_attente == "naive" else moment
        statut = repartiteur._livrer_une_paire(evenement, "m05-financecore", consumer, temps_livraison)
        if cas_attente in ("no_policy", "quota", "naive"):
            from opsys.stockage import codec
            from opsys.stockage.schema import EVENEMENTS_RECUS, WCT_ATTENTES

            assert statut == "traite"
            with session() as cnx:
                recu = (
                    cnx.execute(
                        select(EVENEMENTS_RECUS).where(
                            EVENEMENTS_RECUS.c.evenement_id == wct_id,
                            EVENEMENTS_RECUS.c.consommateur == "m05-financecore",
                        )
                    )
                    .mappings()
                    .one()
                )
                assert recu["statut"] == "traite" and len(list(stockage.maillons("m05-financecore", "wct_recus"))) == 1
                assert cnx.execute(select(WCT_ATTENTES).where(WCT_ATTENTES.c.evenement_id == wct_id)).first() is None
                if cas_attente in ("quota", "naive"):
                    assert codec.decoder(recu["resultat"])["attente_non_creee"] == (
                        "quota" if cas_attente == "quota" else "horodatage_invalide"
                    )
            return
        if statut != "attente":
            from opsys.stockage.schema import EVENEMENTS_RECUS

            with session() as cnx:
                detail = cnx.execute(
                    select(EVENEMENTS_RECUS.c.derniere_erreur).where(
                        EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == "m05-financecore"
                    )
                ).scalar_one()
            pytest.fail("WCT avant devis: " + str(detail))
        from opsys.stockage.schema import EVENEMENTS_RECUS, WCT_ATTENTES

        with session() as cnx:
            recus = list(stockage.maillons("m05-financecore", "wct_recus"))
            assert len(recus) == 1 and recus[0]["wct_id"] == wct_id
            assert not list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))
            attente = cnx.execute(select(WCT_ATTENTES).where(WCT_ATTENTES.c.evenement_id == wct_id)).mappings().one()
            recu_bus = (
                cnx.execute(
                    select(EVENEMENTS_RECUS).where(
                        EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == "m05-financecore"
                    )
                )
                .mappings()
                .one()
            )
            assert attente["etat"] == "attente" and recu_bus["statut"] == "echec"
            assert recu_bus["tentatives"] == 0 and recu_bus["resultat"] is not None
            assert {
                "devis_id": affaire["devis"],
                "statut": "en_attente_devis_accepte",
            } in m5.lister_attentes_facturation()["attentes_devis"]
        if cas_attente == "review_readers":
            from opsys.evenements.bus import copier_cohorte_provenance_m5_m8

            with session() as cnx:
                cohorte, _ = copier_cohorte_provenance_m5_m8(cnx, type_evenement="m5.rentabilite_chantier")
                assert all(r.consommateur == "m08-analytics" for r in cohorte.recus)
                assert all(pub.type_evenement == "m5.rentabilite_chantier" for pub in cohorte.publications)
                assert not any(r.evenement_id == wct_id for r in cohorte.recus)
            lecture = evenements.etat()
            assert lecture["comptes"].get("attente_piece") == 200, lecture
            assert lecture["comptes"].get("echec", 0) == 0 and not lecture["quarantaine"], lecture

            def echouer(charge):
                raise RuntimeError("echec QA explicite")

            for i in range(5):
                maintenant = moment + dt_qa.timedelta(seconds=i * 120)
                etat = repartiteur._livrer_une_paire(evenement, "qa-autre", echouer, maintenant)
                assert etat == ("quarantaine" if i == 4 else "echec"), etat
                lecture = evenements.etat()
                assert lecture["comptes"].get("attente_piece") == 200, lecture
                if i < 4:
                    assert lecture["comptes"].get("echec") == 1 and not lecture["quarantaine"], lecture
                else:
                    assert lecture["comptes"].get("echec", 0) == 0 and lecture["comptes"].get("quarantaine") == 1, (
                        lecture
                    )
                    assert lecture["quarantaine"][0]["tentatives"] == 5, lecture
            print("LECTURE 200 attentes; 0 erreur; autre consommateur echec puis quarantaine apres 5 essais")
            return
        if cas_attente == "horloge_future":
            futur_non_autorise = (moment + dt_qa.timedelta(days=30)).isoformat()
            evenements.repartir({}, maintenant=futur_non_autorise)
            with session() as cnx:
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "attente"
                )
        if cas_attente == "restart_wait":
            stockage.liberer()
            with session() as cnx:
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "attente"
                )
        assert evenements.etat()["comptes"].get("attente_piece", 0) >= 1
        requetes_source = []
        if cas_attente == "source_api":
            import copy
            import threading

            from m3_estimation import service_attente_devis as service_m3
            from m5_financecore import service_attente_devis as service_m5

            class FausseRequete:
                def _verifier(self):
                    raise AssertionError("requête arbitraire accédée")

            with pytest.raises(ValueError):
                service_m3.verifier(FausseRequete())
            with pytest.raises(ValueError):
                service_m5.verifier(FausseRequete())
            original = service_m3.verifier

            def verifier_requete(req):
                requetes_source.append(req)
                with pytest.raises(sc.RefusAutorite):
                    copy.copy(req)
                with monkeypatch.context() as local:
                    local.setattr(sc, "monotonic", lambda: req.echeance + 1)
                    with pytest.raises(sc.RefusAutorite):
                        req._verifier()
                refus = []

                def autre_thread():
                    try:
                        req._verifier()
                    except sc.RefusAutorite:
                        refus.append(True)

                fil = threading.Thread(target=autre_thread)
                fil.start()
                fil.join(timeout=5)
                assert not fil.is_alive() and refus == [True]
                return original(req)

            monkeypatch.setattr(service_m3, "verifier", verifier_requete)
        if cas_attente == "other_consumer":
            appels = []

            class AutreConsommateur:
                id = "qa-autre"
                evenements_consomme = ["m4.travaux_termines"]

                def charger_consommateurs(self):
                    def recevoir(charge):
                        appels.append(charge["wct_id"])
                        return {"traite": True}

                    return {"m4.travaux_termines": recevoir}

            assert evenements.repartir({"qa-autre": AutreConsommateur()}, maintenant=moment.isoformat())["traites"] >= 1
            assert appels == [wct_id]
        if cas_attente == "revoke":
            with session() as cnx:
                sc._revoquer(cnx, instance_id, "m05-financecore")
        assert repartiteur._livrer_une_paire(evenement, "m05-financecore", consumer, moment) is None
        jours = 8 if cas_attente == "expire" else 2
        plus_tard = (moment + dt_qa.timedelta(days=jours)).isoformat()
        # Horloge de politique fictive avancée aussi ; la capacité conserve son délai monotone réel de 30 s.
        monkeypatch.setattr(sc, "time", lambda: moment.timestamp() + jours * 86400)
        suite = evenements.repartir({"m05-financecore": affaire["deps"]["m05-financecore"]}, maintenant=plus_tard)
        assert suite["echecs"] == 0
        with session():
            devis = list(stockage.maillons("m05-financecore", "devis_recus"))
            assert any(d["devis_id"] == affaire["devis"] for d in devis)
            assert list(stockage.maillons("m05-financecore", "wct_recus")) == recus
        if cas_attente == "restart_piece":
            stockage.liberer()
            with session() as cnx:
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "attente"
                )
        if cas_attente == "partial_poison":
            with session() as cnx:
                filtre = (EVENEMENTS_RECUS.c.evenement_id == wct_id) & (
                    EVENEMENTS_RECUS.c.consommateur == "m05-financecore"
                )
                raw = cnx.execute(select(EVENEMENTS_RECUS.c.resultat).where(filtre)).scalar_one()
                cnx.execute(update(EVENEMENTS_RECUS).where(filtre).values(resultat='{"devis_id":"faux",' + raw[1:]))
        if cas_attente == "wct_poison":
            from opsys.stockage import codec

            with session() as cnx:
                raw = cnx.execute(
                    select(EVENEMENTS_SORTANTS.c.charge).where(EVENEMENTS_SORTANTS.c.evenement_id == wct_id)
                ).scalar_one()
                assert raw.startswith("{")
                double = '{"wct_id":"faux",' + raw[1:]
                cnx.execute(
                    update(EVENEMENTS_SORTANTS)
                    .where(EVENEMENTS_SORTANTS.c.evenement_id == wct_id)
                    .values(charge=double)
                )
        if cas_attente in ("poison", "m5_json_double"):
            from opsys.stockage.schema import REGISTRES

            with session() as cnx:
                filtre = (
                    (REGISTRES.c.departement == "m05-financecore")
                    & (REGISTRES.c.registre == "devis_recus")
                    & (REGISTRES.c.rang == 0)
                )
                raw = cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one()
                valeur = "{}" if cas_attente == "poison" else '{"devis_id":"faux",' + raw[1:]
                cnx.execute(update(REGISTRES).where(filtre).values(maillon=valeur))
        if cas_attente == "m3_json_double":
            with session() as cnx:
                eid = "m3-devis-accepte-" + affaire["devis"]
                raw = cnx.execute(
                    select(EVENEMENTS_SORTANTS.c.charge).where(EVENEMENTS_SORTANTS.c.evenement_id == eid)
                ).scalar_one()
                cnx.execute(
                    update(EVENEMENTS_SORTANTS)
                    .where(EVENEMENTS_SORTANTS.c.evenement_id == eid)
                    .values(charge='{"devis_id":"faux",' + raw[1:])
                )
        if cas_attente == "badlink":
            from opsys.stockage import codec

            with session() as cnx:
                eid = "m3-devis-accepte-" + affaire["devis"]
                raw = cnx.execute(
                    select(EVENEMENTS_SORTANTS.c.charge).where(EVENEMENTS_SORTANTS.c.evenement_id == eid)
                ).scalar_one()
                faux = codec.decoder(raw)
                faux["lead_id"] = "autre-fictif"
                cnx.execute(
                    update(EVENEMENTS_SORTANTS)
                    .where(EVENEMENTS_SORTANTS.c.evenement_id == eid)
                    .values(charge=codec.encoder(faux))
                )
        if cas_attente in ("source_m3", "source_m3_tardive", "m3_ambigu"):
            from opsys.evenements import attente_wct
            from opsys.stockage.schema import REGISTRES

            with session() as cnx:
                if cas_attente == "source_m3_tardive":
                    attente_wct.reconcilier(cnx, dt_qa.datetime.fromisoformat(plus_tard))
                    assert (
                        cnx.execute(
                            select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)
                        ).scalar_one()
                        == "prete"
                    )
                if cas_attente == "m3_ambigu":
                    registre_m3 = stockage.maillons("m03-estimation", "devis")
                    acceptee = next(
                        x for x in registre_m3 if x.get("devis_id") == affaire["devis"] and x.get("statut") == "accepte"
                    )
                    registre_m3.append(acceptee)
                else:
                    cnx.execute(
                        update(REGISTRES)
                        .where(
                            REGISTRES.c.departement == "m03-estimation",
                            REGISTRES.c.registre == "devis",
                            REGISTRES.c.rang == 0,
                        )
                        .values(maillon="{}")
                    )
        if cas_attente == "revoke_ready":
            from opsys.evenements import attente_wct

            with session() as cnx:
                attente_wct.reconcilier(cnx, dt_qa.datetime.fromisoformat(plus_tard))
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "prete"
                )
                sc._revoquer(cnx, instance_id, "m05-financecore")
        if cas_attente in ("trigger_m3", "trigger_m5", "trigger_policy", "trigger_inbox", "late_m3"):
            from opsys.evenements import attente_wct
            from opsys.stockage.schema import REGISTRES

            cible_dep = "m05-financecore" if cas_attente == "trigger_m5" else "m03-estimation"
            cible_reg = "devis_recus" if cas_attente == "trigger_m5" else "devis"
            with session() as cnx:
                attente_wct.reconcilier(cnx, dt_qa.datetime.fromisoformat(plus_tard))
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "prete"
                )
                avant_raw = cnx.execute(
                    select(REGISTRES.c.maillon).where(
                        REGISTRES.c.departement == cible_dep, REGISTRES.c.registre == cible_reg, REGISTRES.c.rang == 0
                    )
                ).scalar_one()
                avant_inbox = cnx.execute(
                    select(EVENEMENTS_RECUS.c.resultat).where(
                        EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == "m05-financecore"
                    )
                ).scalar_one()
                if cas_attente == "trigger_inbox":
                    cnx.exec_driver_sql(
                        "CREATE TRIGGER qa_attaque_source AFTER INSERT ON wct_attentes_audit "
                        "WHEN NEW.action='terminee' BEGIN "
                        "UPDATE evenements_recus SET resultat='{}' WHERE evenement_id=NEW.evenement_id "
                        "AND consommateur='m05-financecore'; END"
                    )
                elif cas_attente == "trigger_policy":
                    cnx.exec_driver_sql(
                        "CREATE TRIGGER qa_attaque_source AFTER INSERT ON wct_attentes_audit "
                        "WHEN NEW.action='terminee' BEGIN "
                        "INSERT INTO service_politiques(instance_id,consommateur,operation,revision,active,expire_le) "
                        "SELECT instance_id,consommateur,operation,2,0,expire_le FROM service_politiques "
                        "WHERE operation='m4.verifier_v3' AND revision=1; END"
                    )
                elif cas_attente != "late_m3":
                    cnx.exec_driver_sql(
                        "CREATE TRIGGER qa_attaque_source AFTER INSERT ON wct_attentes_audit "
                        "WHEN NEW.action='terminee' BEGIN "
                        "UPDATE registres_maillons SET maillon='{}' WHERE departement='"
                        + cible_dep
                        + "' AND registre='"
                        + cible_reg
                        + "' AND rang=0; END"
                    )
            publier_original = m5._publier_rentabilite
            if cas_attente == "late_m3":

                def publier_modifier_m3(*args, **kw):
                    sortie = publier_original(*args, **kw)
                    stockage.connexion_courante().execute(
                        update(REGISTRES)
                        .where(
                            REGISTRES.c.departement == cible_dep,
                            REGISTRES.c.registre == cible_reg,
                            REGISTRES.c.rang == 0,
                        )
                        .values(maillon="{}")
                    )
                    return sortie

                monkeypatch.setattr(m5, "_publier_rentabilite", publier_modifier_m3)
            assert (
                repartiteur._livrer_une_paire(
                    evenement, "m05-financecore", consumer, dt_qa.datetime.fromisoformat(plus_tard)
                )
                == "echec"
            )
            with session() as cnx:
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "prete"
                )
                assert (
                    cnx.execute(
                        select(REGISTRES.c.maillon).where(
                            REGISTRES.c.departement == cible_dep,
                            REGISTRES.c.registre == cible_reg,
                            REGISTRES.c.rang == 0,
                        )
                    ).scalar_one()
                    == avant_raw
                )
                assert not list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))
                assert (
                    cnx.execute(
                        select(EVENEMENTS_RECUS.c.resultat).where(
                            EVENEMENTS_RECUS.c.evenement_id == wct_id,
                            EVENEMENTS_RECUS.c.consommateur == "m05-financecore",
                        )
                    ).scalar_one()
                    == avant_inbox
                )
                if cas_attente != "late_m3":
                    cnx.exec_driver_sql("DROP TRIGGER qa_attaque_source")
            if cas_attente == "late_m3":
                monkeypatch.setattr(m5, "_publier_rentabilite", publier_original)
            plus_tard = (dt_qa.datetime.fromisoformat(plus_tard) + dt_qa.timedelta(seconds=10)).isoformat()
        if cas_attente == "crash":
            from opsys.evenements import attente_wct

            with session() as cnx:
                attente_wct.reconcilier(cnx, dt_qa.datetime.fromisoformat(plus_tard))
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "prete"
                )

            def consommer_puis_interrompre(charge):
                consumer(charge)
                raise RuntimeError("interruption fictive après écriture")

            assert (
                repartiteur._livrer_une_paire(
                    evenement, "m05-financecore", consommer_puis_interrompre, dt_qa.datetime.fromisoformat(plus_tard)
                )
                == "echec"
            )
            with session() as cnx:
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "prete"
                )
                assert not list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))
            plus_tard = (dt_qa.datetime.fromisoformat(plus_tard) + dt_qa.timedelta(seconds=10)).isoformat()
        if cas_attente in ("quarantaine", "expire_prete", "review_hidden_failure"):
            from opsys.evenements import attente_wct

            with session() as cnx:
                attente_wct.reconcilier(cnx, dt_qa.datetime.fromisoformat(plus_tard))
                assert (
                    cnx.execute(select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)).scalar_one()
                    == "prete"
                )
            if cas_attente in ("quarantaine", "review_hidden_failure"):

                def echouer(_charge):
                    raise RuntimeError("échec fictif")

                base = dt_qa.datetime.fromisoformat(plus_tard)
                for i in range(5):
                    monkeypatch.setattr(sc, "time", lambda i=i: (base + dt_qa.timedelta(seconds=30 * i)).timestamp())
                    statut_echec = repartiteur._livrer_une_paire(
                        evenement, "m05-financecore", echouer, base + dt_qa.timedelta(seconds=30 * i)
                    )
                    assert statut_echec == ("quarantaine" if i == 4 else "echec")
                    if cas_attente == "review_hidden_failure" and i < 4:
                        observation = evenements.etat()
                        assert observation["comptes"].get("echec", 0) == 1, observation
                with session() as cnx:
                    assert (
                        cnx.execute(
                            select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)
                        ).scalar_one()
                        == "refusee"
                    )
                    assert (
                        cnx.execute(
                            select(EVENEMENTS_RECUS.c.statut).where(
                                EVENEMENTS_RECUS.c.evenement_id == wct_id,
                                EVENEMENTS_RECUS.c.consommateur == "m05-financecore",
                            )
                        ).scalar_one()
                        == "quarantaine"
                    )
                    assert not list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))
                return
            plus_tard = (moment + dt_qa.timedelta(days=8)).isoformat()
            monkeypatch.setattr(sc, "time", lambda: moment.timestamp() + 8 * 86400)
        if cas_attente == "concurrent":
            import threading

            barriere = threading.Barrier(2)
            erreurs = []

            def repartir_concurrent():
                try:
                    barriere.wait(timeout=5)
                    evenements.repartir({"m05-financecore": affaire["deps"]["m05-financecore"]}, maintenant=plus_tard)
                except Exception as exc:
                    erreurs.append(repr(exc))

            fils = [threading.Thread(target=repartir_concurrent) for _ in range(2)]
            for fil in fils:
                fil.start()
            for fil in fils:
                fil.join(timeout=25)
            assert not any(fil.is_alive() for fil in fils) and not erreurs, erreurs
        reprise = evenements.repartir({"m05-financecore": affaire["deps"]["m05-financecore"]}, maintenant=plus_tard)
        assert reprise["echecs"] == 0
        if cas_attente in (
            "expire",
            "expire_prete",
            "revoke",
            "revoke_ready",
            "poison",
            "badlink",
            "source_m3",
            "source_m3_tardive",
            "m3_ambigu",
            "wct_poison",
            "m3_json_double",
            "m5_json_double",
            "partial_poison",
        ):
            with session() as cnx:
                etat_attente = cnx.execute(
                    select(WCT_ATTENTES.c.etat).where(WCT_ATTENTES.c.evenement_id == wct_id)
                ).scalar_one()
                assert etat_attente == ("expiree" if cas_attente in ("expire", "expire_prete") else "refusee")
                recu_bus = (
                    cnx.execute(
                        select(EVENEMENTS_RECUS).where(
                            EVENEMENTS_RECUS.c.evenement_id == wct_id,
                            EVENEMENTS_RECUS.c.consommateur == "m05-financecore",
                        )
                    )
                    .mappings()
                    .one()
                )
                assert recu_bus["statut"] == ("echec" if cas_attente == "partial_poison" else "traite")
                assert not list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))
                assert list(stockage.maillons("m05-financecore", "wct_recus")) == recus
            return
        with session() as cnx:
            attente = cnx.execute(select(WCT_ATTENTES).where(WCT_ATTENTES.c.evenement_id == wct_id)).mappings().one()
            recu_bus = (
                cnx.execute(
                    select(EVENEMENTS_RECUS).where(
                        EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == "m05-financecore"
                    )
                )
                .mappings()
                .one()
            )
            assert attente["etat"] == "terminee" and recu_bus["statut"] == "traite"
            from opsys.stockage.schema import WCT_ATTENTES_AUDIT

            audits = (
                cnx.execute(
                    select(WCT_ATTENTES_AUDIT)
                    .where(WCT_ATTENTES_AUDIT.c.evenement_id == wct_id)
                    .order_by(WCT_ATTENTES_AUDIT.c.id)
                )
                .mappings()
                .all()
            )
            assert [x["action"] for x in audits] == ["attente", "prete", "terminee"]
            assert audits[1]["source_m3"] and audits[1]["source_m3"] == audits[2]["source_m3"]
            assert audits[1]["source_m5"] and audits[1]["source_m5"] == audits[2]["source_m5"]
            assert len(list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))) == 1
            assert list(stockage.maillons("m05-financecore", "wct_recus")) == recus
            trace = list(stockage.maillons("m05-financecore", "rentabilite"))[-1]
            assert trace["rentabilite"]["cout_reel"]["main_d_oeuvre"]["cout"] == Decimal("730.00")
        if cas_attente == "source_api":
            assert requetes_source
            with pytest.raises(sc.RefusAutorite):
                requetes_source[-1]._verifier()
        return
    with session() as cnx:
        traces_avant = list(stockage.maillons("m05-financecore", "rentabilite"))
        events_avant = list(
            cnx.execute(
                select(EVENEMENTS_SORTANTS.c.evenement_id).where(
                    EVENEMENTS_SORTANTS.c.type_evenement == "m5.rentabilite_chantier"
                )
            ).scalars()
        )
    marqueurs = []
    if mode in (
        "revocation_apres_publication",
        "tarif_apres_publication",
        "recu_apres_publication",
        "recu_json_apres_publication",
    ):
        publier_original = m5._publier_rentabilite

        def publier_et_revoquer(*args, **kwargs):
            resultat = publier_original(*args, **kwargs)
            traces = list(stockage.maillons("m05-financecore", "rentabilite"))
            if traces and "provenance_service_v1" in traces[-1]:
                marqueurs.append("evenement_insere")
                if mode == "recu_json_apres_publication":
                    import json

                    from opsys.stockage.schema import REGISTRES

                    cnx = stockage.connexion_courante()
                    condition = (
                        (REGISTRES.c.departement == "m05-financecore")
                        & (REGISTRES.c.registre == "wct_recus")
                        & (REGISTRES.c.rang == 0)
                    )
                    raw = cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one()
                    ident = json.loads(raw)["wct_id"]
                    double = '{"wct_id":' + json.dumps(ident) + "," + raw[1:]
                    assert json.loads(double) == json.loads(raw)
                    assert cnx.execute(update(REGISTRES).where(condition).values(maillon=double)).rowcount == 1
                elif mode == "recu_apres_publication":
                    registre = stockage.maillons("m05-financecore", "wct_recus")
                    registre.append(list(registre)[0])
                elif mode == "revocation_apres_publication":
                    sc._revoquer(stockage.connexion_courante(), instance_id, "m05-financecore")
                else:
                    from opsys.stockage.schema import REGISTRES

                    changement = stockage.connexion_courante().execute(
                        update(REGISTRES)
                        .where(
                            REGISTRES.c.departement == "m05-financecore",
                            REGISTRES.c.registre == m5._NOM_REGISTRE_TARIFS_EQUIPES,
                            REGISTRES.c.rang == 0,
                        )
                        .values(maillon="{}")
                    )
                    assert changement.rowcount == 1
            return resultat

        monkeypatch.setattr(m5, "_publier_rentabilite", publier_et_revoquer)
    if mode == "historique_ancien":
        # Simule un reçu historique R7 : aucun lien d'attestation Core n'existait.
        def ancien_sans_attestation(cap, enveloppe, rang):
            return cap.verifier_projection(enveloppe)

        monkeypatch.setattr(sc._Capacite, "attester_trace_m4", ancien_sans_attestation)
    if mode == "ref_invalide":
        verifier_reference = sc._Capacite.attester_trace_m4
        refs_test = []

        def fausser_reference(cap, enveloppe, rang):
            ref = verifier_reference(cap, enveloppe, rang)
            refs_test.append(True)
            return {**ref, "id": True}

        monkeypatch.setattr(sc._Capacite, "attester_trace_m4", fausser_reference)
    if mode == "revocation_tardive":
        verifier_original = sc._Capacite.verifier_projection
        verifications = []

        def verifier_tardif(cap, enveloppe):
            verifications.append(True)
            if len(verifications) == 4:
                sc._revoquer(stockage.connexion_courante(), instance_id, "m05-financecore")
            return verifier_original(cap, enveloppe)

        monkeypatch.setattr(sc._Capacite, "verifier_projection", verifier_tardif)
    if mode in ("revocation", "audit", "audit_type", "audit_duplicate", "tarif"):
        original_consigner = m5._consigner_rentabilite

        def injecter(*args, **kwargs):
            resultat = original_consigner(*args, **kwargs)
            if kwargs.get("provenance_service") is not None:
                cnx = stockage.connexion_courante()
                if mode == "revocation":
                    sc._revoquer(cnx, instance_id, "m05-financecore")
                elif mode == "audit":
                    audit_id = projection["visites"][0]["equipe_pointee"]["preuves"][0]["audit_id"]
                    cnx.execute(update(JOURNAL).where(JOURNAL.c.id == audit_id).values(par="intrus.fictif"))
                elif mode == "tarif":
                    from opsys.stockage.schema import REGISTRES

                    changed = cnx.execute(
                        update(REGISTRES)
                        .where(
                            REGISTRES.c.departement == "m05-financecore",
                            REGISTRES.c.registre == m5._NOM_REGISTRE_TARIFS_EQUIPES,
                            REGISTRES.c.rang == 0,
                        )
                        .values(maillon="{}")
                    )
                    assert changed.rowcount == 1
                    marqueurs.append("tarif_modifie")
                elif mode == "audit_duplicate":
                    import json

                    audit_id = projection["visites"][0]["equipe_pointee"]["preuves"][0]["audit_id"]
                    raw = cnx.execute(select(JOURNAL.c.details).where(JOURNAL.c.id == audit_id)).scalar_one()
                    assert json.loads(raw)["role"] == "admin" and raw.lstrip().startswith("{")
                    duplicate = '{"role":"admin",' + raw.lstrip()[1:]
                    assert json.loads(duplicate) == json.loads(raw)
                    cnx.execute(update(JOURNAL).where(JOURNAL.c.id == audit_id).values(details=duplicate))
                    marqueurs.append("audit_duplicate_modifie")
                else:
                    import json

                    ids = [p["audit_id"] for v in projection["visites"] for p in v["equipe_pointee"]["preuves"]]
                    found = False
                    for audit_id in ids:
                        raw = cnx.execute(select(JOURNAL.c.details).where(JOURNAL.c.id == audit_id)).scalar_one()
                        details = json.loads(raw)
                        for key, valeur in details["source_rangs"].items():
                            if type(valeur) is int and valeur == 1:
                                details["source_rangs"][key] = True
                                cnx.execute(
                                    update(JOURNAL)
                                    .where(JOURNAL.c.id == audit_id)
                                    .values(details=json.dumps(details, ensure_ascii=False))
                                )
                                found = True
                                break
                        if found:
                            break
                    assert found, "fixture doit contenir un rang entier 1"
                    marqueurs.append("audit_type_modifie")

            return resultat

        monkeypatch.setattr(m5, "_consigner_rentabilite", injecter)
    if mode in ("recu_duplique", "recu_sans_empreinte", "recu_corrompu", "recu_type", "recu_json_double", "recu_hash"):
        from m5_financecore import port_service_m4 as port

        original_port = port.publier

        def fausser_recu(devis_id, *, cap=None):
            import json

            from opsys.stockage.schema import REGISTRES

            cnx = stockage.connexion_courante()
            registre = stockage.maillons("m05-financecore", "wct_recus")
            recus = list(registre)
            matches = [i for i, r in enumerate(recus) if r["wct_id"] == wct_id]
            assert len(matches) == 1
            rang = matches[0]
            recu = dict(recus[rang])
            if mode == "recu_duplique":
                registre.append(recu)
            else:
                if mode == "recu_sans_empreinte":
                    recu.pop("empreinte_charge")
                elif mode == "recu_corrompu":
                    recu["intervention_id"] = "AUTRE-INTERVENTION-FICTIVE"
                elif mode == "recu_hash":
                    recu["empreinte_charge"] = "0" * 64
                elif mode == "recu_type":
                    assert type(recu["duree_reelle_minutes"]) is int
                    recu["duree_reelle_minutes"] = float(recu["duree_reelle_minutes"])
                brut = json.dumps(recu)
                if mode == "recu_json_double":
                    brut = '{"wct_id":' + json.dumps(recu["wct_id"]) + "," + brut[1:]
                    assert json.loads(brut) == recu
                res = cnx.execute(
                    update(REGISTRES)
                    .where(
                        REGISTRES.c.departement == "m05-financecore",
                        REGISTRES.c.registre == "wct_recus",
                        REGISTRES.c.rang == rang,
                    )
                    .values(maillon=brut)
                )
                assert res.rowcount == 1
            marqueurs.append(mode)
            return original_port(devis_id, cap=cap)

        monkeypatch.setattr(port, "publier", fausser_recu)
    r = evenements.repartir(
        {"m05-financecore": affaire["deps"]["m05-financecore"]}, maintenant="2030-06-08T12:00:00-04:00"
    )
    if mode in (
        "recu_duplique",
        "recu_sans_empreinte",
        "recu_corrompu",
        "recu_type",
        "recu_json_double",
        "recu_hash",
        "recu_apres_publication",
        "recu_json_apres_publication",
        "revocation",
        "audit",
        "audit_type",
        "audit_duplicate",
        "tarif",
        "ref_invalide",
        "revocation_tardive",
        "revocation_apres_publication",
        "tarif_apres_publication",
    ):
        assert r["echecs"] == 1, r
        if mode.startswith("recu_") and mode not in ("recu_apres_publication", "recu_json_apres_publication"):
            assert marqueurs == [mode]
        if mode in ("audit_type", "audit_duplicate"):
            from opsys.stockage.schema import EVENEMENTS_RECUS

            assert marqueurs == [mode + "_modifie"]
            with session() as cnx:
                detail = cnx.execute(
                    select(EVENEMENTS_RECUS.c.derniere_erreur).where(
                        EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == "m05-financecore"
                    )
                ).scalar_one()
                assert "AUDIT-INVALIDE" in detail
        if mode == "ref_invalide":
            from opsys.stockage.schema import EVENEMENTS_RECUS

            assert len(refs_test) == 1
            with session() as cnx:
                detail = cnx.execute(
                    select(EVENEMENTS_RECUS.c.derniere_erreur).where(
                        EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == "m05-financecore"
                    )
                ).scalar_one()
                assert "référence Core historique indisponible" in detail
        if mode in (
            "revocation_apres_publication",
            "tarif_apres_publication",
            "recu_apres_publication",
            "recu_json_apres_publication",
        ):
            assert marqueurs == ["evenement_insere"]
        if mode in ("tarif", "tarif_apres_publication"):
            if mode == "tarif":
                assert marqueurs == ["tarif_modifie"]
            with session():
                assert len(m5._instantane_tarifs_equipes()["lignes"]) == 2
        if mode == "revocation_tardive":
            assert len(verifications) == 4
        with session() as cnx:
            assert list(stockage.maillons("m05-financecore", "rentabilite")) == traces_avant
            assert (
                list(
                    cnx.execute(
                        select(EVENEMENTS_SORTANTS.c.evenement_id).where(
                            EVENEMENTS_SORTANTS.c.type_evenement == "m5.rentabilite_chantier"
                        )
                    ).scalars()
                )
                == events_avant
            )
        return
    if r["echecs"]:
        from opsys.stockage.schema import EVENEMENTS_RECUS

        with session() as cnx:
            detail = cnx.execute(
                select(EVENEMENTS_RECUS.c.derniere_erreur).where(
                    EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == "m05-financecore"
                )
            ).scalar_one()
        pytest.fail("livraison fictive: " + str(detail))
    assert r["traites"] >= 1 and r["echecs"] == 0, r
    if mode == "lecture_m5_courante":
        from opsys import service_lecture_m4
        from opsys.stockage.schema import EVENEMENTS_RECUS
        from sqlalchemy import func
        from m3_estimation import service_attente_devis, service_lecture_devis

        class FausseRequete:
            def _verifier(self):
                raise AssertionError("requête arbitraire appelée")
        with pytest.raises(ValueError):
            service_lecture_devis.verifier(FausseRequete())
        with pytest.raises(ValueError):
            service_attente_devis._verifier_commun(FausseRequete())

        with session() as cnx, contexte.appeler_en_tant_que("m05-financecore"):
            baseline = m5.lire_rentabilite_chantier(devis_id=affaire["devis"], autorise_couts=True)
            assert baseline["resultat"]["chantiers"][0]["rentabilite"]["cout_reel"]["complet"] is False
            with pytest.raises(sc.RefusAutorite):
                with service_lecture_m4._ouvrir_qa(cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"]):
                    pass
            cnx.execute(insert(SERVICE_POLITIQUES).values(instance_id=instance_id,
                consommateur="m05-financecore", operation="m4.relire_faits_pour_m5_v1",
                revision=1, active=True, expire_le=int(time.time()) + 120))
            before = dict(cnx.execute(select(EVENEMENTS_RECUS).where(
                EVENEMENTS_RECUS.c.evenement_id == wct_id,
                EVENEMENTS_RECUS.c.consommateur == "m05-financecore")).mappings().one())
            cas_lecture = os.environ.get("QA_NEGATIVE", "")
            if cas_lecture in ("wct_json", "devis_json", "trace_json", "trace_corrompue", "tarif_tardif", "trace_tardive", "facture_tardive", "variance_tardive", "devis_m3_avant", "devis_m3_tardif", "devis_m5_divergent", "recu_v1_absent", "wct_type", "devis_type", "trace_type", "reference_type", "reference_v1_fausse", "revoque"):
                from opsys.stockage.schema import REGISTRES
                from m5_financecore import port_lecture_courante_m4 as port_lecture
                with pytest.raises(sc.RefusAutorite):
                    with service_lecture_m4._ouvrir_qa(cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"]):
                        if cas_lecture in ("wct_type", "devis_type", "trace_type"):
                            nom = {"wct_type":"wct_recus", "devis_type":"devis_recus", "trace_type":"rentabilite"}[cas_lecture]
                            filtre = (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == nom)
                            cnx.execute(update(REGISTRES).where(filtre).values(maillon="[]"))
                        elif cas_lecture == "reference_v1_fausse":
                            from opsys.stockage import codec
                            from m5_financecore import encodage
                            filtre = (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == "rentabilite_service_v1")
                            valeur = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
                            valeur["reference_core"]["id"] += 1000000
                            corps = {k: v for k, v in valeur.items() if k != "empreinte"}
                            valeur["empreinte"] = encodage.empreinte("m5.publication_service.v1", corps)
                            cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(valeur)))
                        elif cas_lecture == "reference_type":
                            from opsys.stockage import codec
                            from m5_financecore import encodage
                            filtre = (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == "rentabilite_service_v1")
                            valeur = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
                            valeur["reference_core"] = []
                            corps = {k: v for k, v in valeur.items() if k != "empreinte"}
                            valeur["empreinte"] = encodage.empreinte("m5.publication_service.v1", corps)
                            cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(valeur)))
                        elif cas_lecture in ("wct_json", "devis_json", "trace_json", "trace_corrompue"):
                            nom = {"wct_json": "wct_recus", "devis_json": "devis_recus",
                                   "trace_json": "rentabilite", "trace_corrompue": "rentabilite"}[cas_lecture]
                            filtre = (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == nom)
                            if cas_lecture == "trace_corrompue":
                                from opsys.stockage import codec
                                rang = cnx.execute(select(func.max(REGISTRES.c.rang)).where(filtre)).scalar_one()
                                dernier = filtre & (REGISTRES.c.rang == rang)
                                contenu = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(dernier)).scalar_one())
                                contenu["rentabilite"]["cout_reel"]["main_d_oeuvre"]["cout"] = Decimal("1")
                                cnx.execute(update(REGISTRES).where(dernier).values(maillon=codec.encoder(contenu)))
                            else:
                                cnx.execute(update(REGISTRES).where(filtre).values(maillon='{"x":1,"x":2}'))
                        elif cas_lecture == "devis_m3_avant":
                            filtre = (REGISTRES.c.departement == "m03-estimation") & (REGISTRES.c.registre == "devis")
                            rang_max = cnx.execute(select(func.max(REGISTRES.c.rang)).where(filtre)).scalar_one()
                            from opsys.stockage import codec
                            mutation = {"type_entree":"transition_devis", "devis_id":affaire["devis"],
                                        "statut":"annule", "horodatage":"2030-06-08T00:00:00+00:00"}
                            cnx.execute(insert(REGISTRES).values(departement="m03-estimation", registre="devis",
                                rang=rang_max + 1, maillon=codec.encoder(mutation)))
                        elif cas_lecture == "devis_m5_divergent":
                            filtre = (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == "devis_recus")
                            from opsys.stockage import codec
                            contenu = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
                            contenu["prix_total"] = "1.00"
                            cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(contenu)))
                        elif cas_lecture == "recu_v1_absent":
                            from sqlalchemy import delete
                            filtre = (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == "rentabilite_service_v1")
                            cnx.execute(delete(REGISTRES).where(filtre))
                        elif cas_lecture == "revoque":
                            cnx.execute(insert(SERVICE_POLITIQUES).values(instance_id=instance_id,
                                consommateur="m05-financecore", operation="m4.relire_faits_pour_m5_v1",
                                revision=2, active=False, expire_le=int(time.time()) + 120))
                        else:
                            original_capture = port_lecture._capturer
                            appels = []
                            def capturer_avec_mutation(connexion):
                                appels.append(1)
                                if len(appels) == 2:
                                    if cas_lecture == "devis_m3_tardif":
                                        from opsys.stockage import codec
                                        filtre = (REGISTRES.c.departement == "m03-estimation") & (REGISTRES.c.registre == "devis")
                                        rang_max = cnx.execute(select(func.max(REGISTRES.c.rang)).where(filtre)).scalar_one()
                                        mutation = {"type_entree":"transition_devis", "devis_id":affaire["devis"],
                                                    "statut":"annule", "horodatage":"2030-06-08T00:00:00+00:00"}
                                        cnx.execute(insert(REGISTRES).values(departement="m03-estimation", registre="devis",
                                            rang=rang_max + 1, maillon=codec.encoder(mutation)))
                                    else:
                                        registre = {"tarif_tardif":"tarifs_equipes", "trace_tardive":"rentabilite",
                                                    "facture_tardive":"factures", "variance_tardive":"variance_recue"}[cas_lecture]
                                        filtre = (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == registre)
                                        rang_max = cnx.execute(select(func.max(REGISTRES.c.rang)).where(filtre)).scalar_one()
                                        cnx.execute(insert(REGISTRES).values(departement="m05-financecore", registre=registre,
                                            rang=0 if rang_max is None else rang_max + 1, maillon='{"fictif":true}'))
                                return original_capture(connexion)
                            monkeypatch.setattr(port_lecture, "_capturer", capturer_avec_mutation)
                        m5.lire_rentabilite_chantier(devis_id=affaire["devis"], autorise_couts=True)
                assert dict(cnx.execute(select(EVENEMENTS_RECUS).where(
                    EVENEMENTS_RECUS.c.evenement_id == wct_id,
                    EVENEMENTS_RECUS.c.consommateur == "m05-financecore")).mappings().one()) == before
                return
            ecrivain_bloque = []
            if cas_lecture == "devis_m3_concurrent":
                import sqlite3
                import threading
                from m5_financecore import port_lecture_courante_m4 as port_lecture
                original_capture = port_lecture._capturer
                def capturer_avec_ecrivain(connexion):
                    if not ecrivain_bloque:
                        def ecrire():
                            try:
                                with sqlite3.connect(cnx.engine.url.database, timeout=0.05) as autre:
                                    autre.execute("UPDATE registres_maillons SET maillon=maillon WHERE departement=? AND registre=?", ("m03-estimation", "devis"))
                                ecrivain_bloque.append("commit")
                            except sqlite3.OperationalError as exc:
                                ecrivain_bloque.append(str(exc))
                        t = threading.Thread(target=ecrire)
                        t.start(); t.join(timeout=3)
                        assert not t.is_alive() and ecrivain_bloque and "locked" in ecrivain_bloque[0]
                    return original_capture(connexion)
                monkeypatch.setattr(port_lecture, "_capturer", capturer_avec_ecrivain)
            with service_lecture_m4._ouvrir_qa(cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"]):
                fresh = m5.lire_rentabilite_chantier(devis_id=affaire["devis"], autorise_couts=True)
                chantier = fresh["resultat"]["chantiers"][0]
                assert chantier["rentabilite"]["cout_reel"]["main_d_oeuvre"]["cout"] == Decimal("730.00")
                assert chantier["trace"]["a_jour"] is True
            assert dict(cnx.execute(select(EVENEMENTS_RECUS).where(
                EVENEMENTS_RECUS.c.evenement_id == wct_id,
                EVENEMENTS_RECUS.c.consommateur == "m05-financecore")).mappings().one()) == before
        return
    if mode == "console_sans_policy":
        from opsys.stockage.schema import WCT_ATTENTES

        with session() as cnx:
            assert not list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))
            assert not cnx.execute(select(WCT_ATTENTES)).all()
            traces = list(stockage.maillons("m05-financecore", "rentabilite"))
            assert traces and traces[-1]["verdict"] == "PARTIELLE"
        url = f"/crm/lead/{affaire['lead']}/soumissions/{affaire['devis']}/couts-travaux/export.json"
        response = catalogue.get(url)
        assert response.status_code == 200, response.text
        vue_sans_politique = response.json()["vue"]
        assert vue_sans_politique["historique_service"]["nombre"] == 0
        assert (
            vue_sans_politique["chantier"]["trace"]["a_jour"] is False
            or vue_sans_politique["chantier"]["rentabilite"]["verdict"] == "PARTIELLE"
        )
        return
    from opsys.stockage.schema import SERVICE_AUDIT

    with session() as cnx:
        assert (
            cnx.execute(
                select(SERVICE_AUDIT.c.action).where(
                    SERVICE_AUDIT.c.evenement_id == wct_id, SERVICE_AUDIT.c.consommateur == "m05-financecore"
                )
            )
            .scalars()
            .all()
            .count("usage")
            >= 4
        )
        traces = list(stockage.maillons("m05-financecore", "rentabilite"))
        trace = traces[-1]
        assert trace["wct_id"] == wct_id and trace["provenance_service_v1"]["source_m4"]
        assert trace["rentabilite"]["cout_reel"]["main_d_oeuvre"]["cout"] == Decimal("730.00")
        events = list(
            cnx.execute(
                select(EVENEMENTS_SORTANTS.c.evenement_id).where(
                    EVENEMENTS_SORTANTS.c.type_evenement == "m5.rentabilite_chantier"
                )
            ).scalars()
        )
        assert len(events) > len(events_avant)
    avant = f.m.base._instantane_base(session)
    url = f"/crm/lead/{affaire['lead']}/soumissions/{affaire['devis']}/couts-travaux"
    page = catalogue.get(url)
    assert page.status_code == 200, page.text
    assert "Publications de service" in page.text and "730.00" in page.text
    export = catalogue.get(url + "/export.json")
    assert export.status_code == 200, export.text
    vue = export.json()["vue"]
    assert vue["ventilation_m4"]["cout_main_oeuvre"] == "730.00"
    assert vue["historique_service"]["nombre"] == 1
    assert vue["historique_service"]["traces"][0]["fraicheur"] == "historique_non_revalidee"
    assert vue["historique_v3"]["nombre"] == 0
    assert export.headers["cache-control"] == "no-store"
    assert f.m.base._instantane_base(session) == avant
    if mode == "lecture_revocation":
        from opsys import identite, service_history_m4
        from opsys.console import memoire_chantier as autorite

        historique_original = service_history_m4.lire_historique
        admin_original = autorite._admin
        controles = []

        def lecture_revoquee(cnx, session_admin, recu):
            def admin_revoque(c, sess):
                controles.append(True)
                if len(controles) == 2:
                    identite.retirer_role(c, sess.utilisateur, "admin")
                return admin_original(c, sess)

            with monkeypatch.context() as local:
                local.setattr(autorite, "_admin", admin_revoque)
                return historique_original(cnx, session_admin, recu)

        with monkeypatch.context() as local:
            local.setattr(service_history_m4, "lire_historique", lecture_revoquee)
            refuse = catalogue.get(url + "/export.json")
        assert len(controles) == 2 and refuse.status_code == 403
        assert "730.00" not in refuse.text
        return
    # La preuve service est vérifiée séparément du reçu console humain.
    preuve_attendue = "historique_non_verifiable" if mode == "historique_ancien" else "liaison_historique_verifiee"
    assert vue["historique_service"]["traces"][0]["preuve_core"] == preuve_attendue
    if mode == "historique_ancien":
        assert "Liaison historique non vérifiable" in page.text
    else:
        assert "Liaison historique vérifiée" in page.text
    with session():
        audit_id = list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))[-1]["reference_core"]["id"]
    with session() as cnx:
        cnx.execute(update(SERVICE_AUDIT).where(SERVICE_AUDIT.c.id == audit_id).values(action="revocation"))
    try:
        page_invalide = catalogue.get(url)
        export_invalide = catalogue.get(url + "/export.json")
        assert page_invalide.status_code == 503 and export_invalide.status_code == 503
        assert "730.00" not in export_invalide.text
    finally:
        with session() as cnx:
            cnx.execute(update(SERVICE_AUDIT).where(SERVICE_AUDIT.c.id == audit_id).values(action="usage"))
    assert catalogue.get(url).status_code == 200
    with session():
        apres = list(stockage.maillons("m05-financecore", "rentabilite"))
        recus_apres = list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))
    rejoue = evenements.repartir(
        {"m05-financecore": affaire["deps"]["m05-financecore"]}, maintenant="2030-06-08T12:00:00-04:00"
    )
    assert rejoue["traites"] == 0 and rejoue["echecs"] == 0
    with session():
        assert list(stockage.maillons("m05-financecore", "rentabilite")) == apres
        assert list(stockage.maillons("m05-financecore", "rentabilite_service_v1")) == recus_apres
    if mode == "v2_apres_tarif":
        from opsys import service_history_m4, service_recalcul_m4
        from opsys.stockage import codec
        from opsys.stockage.schema import (
            EVENEMENTS_RECUS,
            SERVICE_RECALCUL_ATTESTATIONS,
            SERVICE_RECALCUL_INTENTIONS,
            SERVICE_RECALCUL_RESULTATS,
        )

        with session() as cnx:
            ancien = list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))
            assert len(ancien) == 1
            histoire_v1 = service_history_m4.lire_historique(cnx, f.AUTH, ancien[0])
            assert histoire_v1["fraicheur"] == "historique_non_revalidee"
            reception_avant = dict(
                cnx.execute(
                    select(EVENEMENTS_RECUS).where(
                        EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == "m05-financecore"
                    )
                )
                .mappings()
                .one()
            )
        with (
            session(),
            contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin", source="console")),
            contexte.appeler_en_tant_que("m05-financecore", origine="console"),
        ):
            snapshot = m5._lire_tarifs_equipes()
            premier = next(x for x in snapshot["lignes"] if x["equipe_id"] == equipe1)
            revision = {
                k: premier[k]
                for k in (
                    "equipe_id",
                    "taux",
                    "unite",
                    "devise",
                    "source",
                    "version",
                    "date_effet",
                    "date_fin",
                    "remplace_id",
                )
            }
            revision.update(taux="101", source="tarif-revise-fictif", version="2", remplace_id=premier["ligne_id"])
            m5._inscrire_tarif_equipe(revision, mutation_id="FICTIF-REVISION-V2", source_attendue=snapshot["source"])
        with session() as cnx:
            charges = sorted(
                [
                    codec.decoder(x)
                    for x in cnx.execute(
                        select(EVENEMENTS_SORTANTS.c.charge).where(
                            EVENEMENTS_SORTANTS.c.type_evenement == "m5.rentabilite_chantier"
                        )
                    ).scalars()
                ],
                key=lambda x: x["sequence"],
            )
            assert charges[-1]["verdict"] == "PARTIELLE"
            assert service_history_m4.lire_historique(cnx, f.AUTH, ancien[0]) == histoire_v1
            with pytest.raises(sc.RefusAutorite):
                service_recalcul_m4._executer_qa(
                    cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"], intention_id="b" * 64
                )
            with pytest.raises(sc.RefusAutorite, match="NON_QUALIFIE"):
                service_recalcul_m4.ouvrir(cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"], intention_id="b" * 64)
            cnx.execute(
                insert(SERVICE_POLITIQUES).values(
                    instance_id=instance_id,
                    consommateur="m05-financecore",
                    operation="m4.recalculer_v3",
                    revision=1,
                    active=True,
                    expire_le=int(time.time()) + 120,
                )
            )
            cas = os.environ.get("QA_NEGATIVE", "")
            if cas in ("typed_frontiere_m5", "typed_frontiere_core"):
                from m5_financecore import port_service_m4 as port

                if cas == "typed_frontiere_m5":
                    original = service_recalcul_m4._CapaciteRecalcul.attester_recalcul_m4

                    def fausser(cap, enveloppe, rang, empreinte):
                        ref = original(cap, enveloppe, rang, empreinte)
                        assert type(ref["revision_recalcul"]) is int and ref["revision_recalcul"] == 1
                        return {**ref, "revision_recalcul": True}

                    monkeypatch.setattr(service_recalcul_m4._CapaciteRecalcul, "attester_recalcul_m4", fausser)
                else:
                    original = port.publier

                    def fausser_resultat(*args, **kwargs):
                        resultat = original(*args, **kwargs)
                        return {**resultat, "attestation": {**resultat["attestation"], "revision_recalcul": True}}

                    monkeypatch.setattr(port, "publier", fausser_resultat)
                traces_avant = list(stockage.maillons("m05-financecore", "rentabilite"))
                with pytest.raises(sc.RefusAutorite):
                    service_recalcul_m4._executer_qa(
                        cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"], intention_id="b" * 64
                    )
                assert list(stockage.maillons("m05-financecore", "rentabilite")) == traces_avant
                assert not cnx.execute(select(SERVICE_RECALCUL_INTENTIONS)).all()
                assert not cnx.execute(select(SERVICE_RECALCUL_ATTESTATIONS)).all()
                assert not cnx.execute(select(SERVICE_RECALCUL_RESULTATS)).all()
                assert not list(stockage.maillons("m05-financecore", "rentabilite_recalcul_v2"))
            else:
                reponse = service_recalcul_m4._executer_qa(
                    cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"], intention_id="b" * 64
                )
                assert reponse["statut"] == "publiee"
                assert reponse["attestation"]["operation"] == "m4.recalculer_v3"
                traces = list(stockage.maillons("m05-financecore", "rentabilite"))
                assert traces[-1]["rentabilite"]["cout_reel"]["main_d_oeuvre"]["cout"] == Decimal("732.50")
                assert list(stockage.maillons("m05-financecore", "rentabilite_service_v1")) == ancien
                assert service_history_m4.lire_historique(cnx, f.AUTH, ancien[0]) == histoire_v1
                historique_v2 = service_recalcul_m4.lire_historique_v2(cnx, f.AUTH, "b" * 64)
                assert historique_v2["statut"] == "historique_non_revalidee"
                assert historique_v2["attestation"] == reponse["attestation"]
                if os.environ.get("QA_NEGATIVE") in ("fresh_v2", "fresh_v2_bool", "reference_v2_fausse"):
                    from opsys import service_lecture_m4
                    from opsys.stockage.schema import REGISTRES
                    from m5_financecore import encodage

                    cnx.execute(insert(SERVICE_POLITIQUES).values(instance_id=instance_id,
                        consommateur="m05-financecore", operation="m4.relire_faits_pour_m5_v1",
                        revision=1, active=True, expire_le=int(time.time()) + 120))
                    with contexte.appeler_en_tant_que("m05-financecore"):
                        if os.environ.get("QA_NEGATIVE") in ("fresh_v2_bool", "reference_v2_fausse"):
                            with pytest.raises(sc.RefusAutorite):
                                with service_lecture_m4._ouvrir_qa(cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"]):
                                    filtre = (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == "rentabilite_recalcul_v2")
                                    valeur = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
                                    if os.environ.get("QA_NEGATIVE") == "fresh_v2_bool":
                                        valeur["reference_core"]["revision_recalcul"] = True
                                    else:
                                        valeur["reference_core"]["audit_recalcul_id"] += 1000000
                                    corps = {k: v for k, v in valeur.items() if k != "empreinte"}
                                    valeur["empreinte"] = encodage.empreinte("m5.publication_recalcul.v2", corps)
                                    cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(valeur)))
                                    m5.lire_rentabilite_chantier(devis_id=affaire["devis"], autorise_couts=True)
                        else:
                            with service_lecture_m4._ouvrir_qa(cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"]):
                                actuel = m5.lire_rentabilite_chantier(devis_id=affaire["devis"], autorise_couts=True)
                                chantier = actuel["resultat"]["chantiers"][0]
                                assert chantier["rentabilite"]["cout_reel"]["main_d_oeuvre"]["cout"] == Decimal("732.50")
                                assert chantier["trace"]["a_jour"] is True
                if cas == "history_core":
                    from opsys import service_lecture_m4 as lecture

                    cnx.execute(insert(SERVICE_POLITIQUES).values(
                        instance_id=instance_id, consommateur="m05-financecore",
                        operation="m4.relire_faits_pour_m5_v1", revision=1, active=True,
                        expire_le=int(time.time()) + 120))
                    ref_v1 = ancien[0]["reference_core"]
                    ref_v2 = reponse["attestation"]
                    with contexte.appeler_en_tant_que("m05-financecore"):
                        with lecture._ouvrir_qa(cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"]) as cap:
                            cap.projection_m4()
                            with contexte.appeler_en_tant_que("m03-estimation"), pytest.raises(sc.RefusAutorite):
                                cap.verifier_reference_publication(ref_v1)
                            v1 = cap.verifier_reference_publication(ref_v1)
                            preuve_v2 = cap.verifier_reference_publication(ref_v2)
                            assert v1["statut"] == preuve_v2["statut"] == "historique_non_revalide"
                            assert v1["trace_rang"] == ancien[0]["trace_rang"]
                            assert v1["trace_sha256"] == lecture.empreinte_trace_v1(traces[v1["trace_rang"]])
                            assert preuve_v2["reference"] == ref_v2
                            assert preuve_v2["version_resultat"] == reponse["version"]
                            for ref in ({**ref_v1, "id": ref_v1["id"] + 100000},
                                        {**ref_v1, "revision": True},
                                        {**ref_v2, "audit_recalcul_id": ref_v2["audit_recalcul_id"] + 100000},
                                        {**ref_v2, "revision_recalcul": True},
                                        {**ref_v2, "trace_rang": True},
                                        {**ref_v2, "devis_id": "autre-fictif"}):
                                with pytest.raises(sc.RefusAutorite):
                                    cap.verifier_reference_publication(ref)
                        with pytest.raises(sc.RefusAutorite):  # noqa: SIM117
                            with lecture._ouvrir_qa(cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"]) as cap2:
                                cap2.projection_m4()
                                cap2.verifier_reference_publication(ref_v2)
                                cnx.execute(update(SERVICE_AUDIT).where(
                                    SERVICE_AUDIT.c.id == ref_v2["audit_recalcul_id"]).values(action="revocation"))
                        v2_audit = cnx.execute(select(SERVICE_AUDIT.c.action).where(
                            SERVICE_AUDIT.c.id == ref_v2["audit_recalcul_id"])).scalar_one()
                        assert v2_audit == "usage"
                assert (
                    service_recalcul_m4._executer_qa(
                        cnx, f.AUTH, wct_id=wct_id, devis_id=affaire["devis"], intention_id="b" * 64
                    )["statut"]
                    == "deja_executee"
                )
            assert (
                dict(
                    cnx.execute(
                        select(EVENEMENTS_RECUS).where(
                            EVENEMENTS_RECUS.c.evenement_id == wct_id,
                            EVENEMENTS_RECUS.c.consommateur == "m05-financecore",
                        )
                    )
                    .mappings()
                    .one()
                )
                == reception_avant
            )
    return
    # Les taux fictifs sont écrits dans le registre privé réel : ils ne prouvent
    # pas que les personnes pointées représentent une équipe historique.
    from m5_financecore import outils as m5

    with (
        session() as cnx,
        contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin", source="console")),
        contexte.appeler_en_tant_que("m05-financecore", origine="console"),
    ):
        initial = m5._lire_tarifs_equipes()
        tarif = dict(
            equipe_id=equipe1,
            taux="100",
            unite="heure-equipe",
            devise="CAD",
            source="tarif-fictif",
            version="1",
            date_effet="2030-01-01",
            date_fin="2030-12-31",
            remplace_id=None,
        )
        for index, faux in enumerate(
            (
                {"devise": "USD"},
                {"unite": "heure-personne"},
                {"version": ""},
                {"source": ""},
                {"date_fin": "2029-12-31"},
            )
        ):
            with pytest.raises(ValueError):
                m5._inscrire_tarif_equipe(
                    tarif | faux, mutation_id=f"FICTIF-INVALIDE-{index}", source_attendue=initial["source"]
                )
            assert m5._lire_tarifs_equipes() == initial
        # Un tarif valide mais expiré n'est pas celui de la visite réelle. Un
        # savepoint permet de vérifier ce cas sans conserver la donnée d'essai.
        savepoint = cnx.begin_nested()
        m5._inscrire_tarif_equipe(
            tarif | {"date_effet": "2029-01-01", "date_fin": "2029-12-31"},
            mutation_id="FICTIF-EXPIRE",
            source_attendue=initial["source"],
        )
        source_apres_expire = m5._lire_tarifs_equipes()["source"]
        m5._inscrire_tarif_equipe(
            tarif | {"equipe_id": equipe2_id, "taux": "120"},
            mutation_id="FICTIF-VALIDE",
            source_attendue=source_apres_expire,
        )
        from opsys.console import rentabilite_chantier as port_m5

        recu = next(x for x in stockage.maillons("m05-financecore", "wct_recus") if x["wct_id"] == wct_id)
        vue_expiree = port_m5._ventilation_m4(cnx, f.AUTH, recu, affaire["lead"])
        assert vue_expiree["statut"] == "INCOMPLET" and vue_expiree["cout_main_oeuvre"] is None
        assert vue_expiree["cout_main_oeuvre_connu"] == Decimal("480.00")  # seule la seconde équipe
        savepoint.rollback()
        assert m5._lire_tarifs_equipes() == initial
        for index, (equipe, taux) in enumerate(((equipe1, "100"), (equipe2_id, "120"))):
            snapshot = m5._lire_tarifs_equipes()
            m5._inscrire_tarif_equipe(
                dict(
                    equipe_id=equipe,
                    taux=taux,
                    unite="heure-equipe",
                    devise="CAD",
                    source="tarif-fictif",
                    version="1",
                    date_effet="2030-01-01",
                    date_fin="2030-12-31",
                    remplace_id=None,
                ),
                mutation_id=f"FICTIF-HTTP-TARIF-{index}",
                source_attendue=snapshot["source"],
            )
        assert len(m5._lire_tarifs_equipes()["lignes"]) == 2
    avant = f.m.base._instantane_base(session)
    url = f"/crm/lead/{affaire['lead']}/soumissions/{affaire['devis']}/couts-travaux"
    page = catalogue.get(url)
    assert page.status_code == 200
    assert "Ventilation M4 complémentaire" in page.text and "390 minutes" in page.text
    assert "Équipes indéterminées : 0" in page.text and "730.00" in page.text
    export = catalogue.get(url + "/export.json")
    assert export.status_code == 200, export.text
    volet = export.json()["vue"]["ventilation_m4"]
    assert volet["statut"] == "COMPLET" and volet["minutes_travail"] == 390
    assert volet["equipes_indeterminees"] == 0 and volet["cout_main_oeuvre"] == "730.00"
    assert volet["wct_id"] == wct_id and volet["revue"] == "verifiee"
    assert "composition_declaree" not in export.text and "membres" not in export.text
    assert export.headers["cache-control"] == "no-store"
    assert f.m.base._instantane_base(session) == avant
    source = export.json()["vue"]["source_calculee"]
    trace_url = url + "/tracer"
    import re

    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    mutation = re.search(r'name="mutation_id" value="([^"]+)"', page.text).group(1)
    commande = {"csrf": csrf, "source_attendue": source, "mutation_id": mutation}
    from opsys.console import rentabilite_chantier as port

    with session() as cnx:
        sauvegarde = cnx.begin_nested()
        stockage.maillons("m05-financecore", "rentabilite_mutations_v3").append(
            {
                "mutation_id": mutation,
                "intention": {
                    "lead_id": affaire["lead"],
                    "devis_id": affaire["devis"],
                    "source_attendue": source,
                    "auteur": "admin.fictif",
                },
                "version_entrees": "faux",
            }
        )
        with pytest.raises(port.lecture.Refus, match="RECU-INVALIDE"):
            port.tracer_ventilation(cnx, affaire["deps"], f.AUTH, affaire["lead"], affaire["devis"], source, mutation)
        sauvegarde.rollback()
        sauvegarde = cnx.begin_nested()
        stockage.maillons("m05-financecore", "rentabilite_mutations_v3").append("recu-invalide")
        with pytest.raises(port.lecture.Refus, match="RECU-INVALIDE"):
            port.tracer_ventilation(cnx, affaire["deps"], f.AUTH, affaire["lead"], affaire["devis"], source, mutation)
        sauvegarde.rollback()
    assert catalogue.post(trace_url, data={**commande, "csrf": "incorrect"}).status_code == 403
    assert f.m.base._instantane_base(session) == avant
    consigner_initial = m5._consigner_rentabilite

    def interposer_ecriture(*args, **kwargs):
        stockage.maillons("m05-financecore", "rentabilite").append({"type_entree": "concurrent-fictif"})
        return consigner_initial(*args, **kwargs)

    with monkeypatch.context() as remplacement:
        remplacement.setattr(m5, "_consigner_rentabilite", interposer_ecriture)
        assert catalogue.post(trace_url, data=commande).status_code == 409
    assert f.m.base._instantane_base(session) == avant
    from opsys import identite

    def revoquer_apres_trace(*args, **kwargs):
        resultat = consigner_initial(*args, **kwargs)
        identite.retirer_role(stockage.connexion_courante(), "admin.fictif", "admin")
        return resultat

    with monkeypatch.context() as remplacement:
        remplacement.setattr(m5, "_consigner_rentabilite", revoquer_apres_trace)
        assert catalogue.post(trace_url, data=commande).status_code == 403
    assert f.m.base._instantane_base(session) == avant
    reponse = catalogue.post(trace_url, data=commande, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text
    with session():
        traces = list(stockage.maillons("m05-financecore", "rentabilite"))
    trace = [t for t in traces if t.get("devis_id") == affaire["devis"]][-1]
    assert trace["rentabilite"]["cout_reel"]["main_d_oeuvre"]["cout"] == Decimal("730.00")
    assert trace["verdict"] == "PARTIELLE"  # la variance M6 est encore inconnue
    vue_apres = catalogue.get(url + "/export.json").json()["vue"]
    assert vue_apres["chantier"]["trace"]["a_jour"] is True
    assert vue_apres["chantier"]["rentabilite"]["cout_reel"]["main_d_oeuvre"]["cout"] == "730.00"
    assert catalogue.post(trace_url, data=commande, follow_redirects=False).status_code == 303
    assert (
        catalogue.post(trace_url, data={**commande, "source_attendue": "f" * 64}, follow_redirects=False).status_code
        == 409
    )
    with session():
        assert list(stockage.maillons("m05-financecore", "rentabilite")) == traces
    # Déclaration et prix fictifs via les outils M6, puis vraie livraison de la variance.
    m6deps = affaire["deps"]["m06-material-control"]
    assert evenements.repartir({"m06-material-control": m6deps}, maintenant="2030-06-08T12:00:00-04:00")["echecs"] == 0
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin", source="console")):
        prix = executer_atomique(
            m6["m6_enregistrer_prix"],
            dict(
                materiau_id=f.b.MATERIAU_ID,
                fournisseur_id="FICTIF",
                prix_unitaire=8.0,
                devise="CAD",
                date_effet="2030-01-01",
                source_document="QA-FICTIF",
                unite="pi",
            ),
        )
        assert prix["ok"] and prix["resultat"]["accepte"], prix
        declaree = executer_atomique(
            m6["m6_declarer_materiaux_utilises"],
            dict(
                wct_id=wct_id,
                formulaire=dict(
                    wct_id=wct_id,
                    intervention_id=iid,
                    chantier_id="DEPOT-FICTIF",
                    lignes_materiaux=[
                        dict(
                            type_ligne="prevu",
                            materiau_id=f.b.MATERIAU_ID,
                            quantite=40,
                            quantite_estimee=40,
                            unite="pi",
                        )
                    ],
                ),
            ),
        )
        assert declaree["ok"] and declaree["resultat"]["accepte"], declaree
    assert (
        evenements.repartir(
            {"m05-financecore": affaire["deps"]["m05-financecore"]}, maintenant="2030-06-08T12:00:00-04:00"
        )["echecs"]
        == 0
    )
    page2 = catalogue.get(url)
    export2 = catalogue.get(url + "/export.json").json()["vue"]
    assert export2["chantier"]["rentabilite"]["verdict"] == "CALCULEE", export2["chantier"]["rentabilite"]["manque"]
    csrf2 = re.search(r'name="csrf" value="([^"]+)"', page2.text).group(1)
    mutation2 = re.search(r'name="mutation_id" value="([^"]+)"', page2.text).group(1)
    assert (
        catalogue.post(
            trace_url,
            data={"csrf": csrf2, "source_attendue": export2["source_calculee"], "mutation_id": mutation2},
            follow_redirects=False,
        ).status_code
        == 303
    )
    from sqlalchemy import select

    from opsys.stockage import codec
    from opsys.stockage.schema import EVENEMENTS_SORTANTS

    with session() as cnx:
        charges = sorted(
            [
                codec.decoder(x)
                for x in cnx.execute(
                    select(EVENEMENTS_SORTANTS.c.charge).where(
                        EVENEMENTS_SORTANTS.c.type_evenement == "m5.rentabilite_chantier"
                    )
                ).scalars()
            ],
            key=lambda x: x["sequence"],
        )
        assert charges[-1]["verdict"] == "PARTIELLE"  # la trace V3 historique n'est pas diffusée comme actuelle
        derniere_trace = list(stockage.maillons("m05-financecore", "rentabilite"))[-1]
        assert derniere_trace["verdict"] == "CALCULEE"
        assert derniere_trace["rentabilite"]["cout_reel"]["cout_total"] == Decimal("1050.00")
        assert derniere_trace["rentabilite"]["marge_reelle"] == Decimal("-450.00")
    # Une révision de tarif maintient l'événement aval dans l'état conservateur.
    with (
        session(),
        contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin", source="console")),
        contexte.appeler_en_tant_que("m05-financecore", origine="console"),
    ):
        snapshot = m5._lire_tarifs_equipes()
        premier = next(x for x in snapshot["lignes"] if x["equipe_id"] == equipe1)
        revision = {
            k: premier[k]
            for k in (
                "equipe_id",
                "taux",
                "unite",
                "devise",
                "source",
                "version",
                "date_effet",
                "date_fin",
                "remplace_id",
            )
        }
        revision.update(taux="101", source="tarif-revise-fictif", version="2", remplace_id=premier["ligne_id"])
        m5._inscrire_tarif_equipe(revision, mutation_id="FICTIF-REVISION", source_attendue=snapshot["source"])
    actualisee = catalogue.get(url + "/export.json").json()["vue"]
    assert actualisee["chantier"]["trace"]["a_jour"] is False
    assert actualisee["ventilation_m4"]["cout_main_oeuvre"] == "732.50"
    assert actualisee["historique_v3"]["nombre"] == 2
    assert actualisee["historique_v3"]["traces"][0]["provenance"] == derniere_trace["provenance_v3"]
    with session() as cnx:
        charges = sorted(
            [
                codec.decoder(x)
                for x in cnx.execute(
                    select(EVENEMENTS_SORTANTS.c.charge).where(
                        EVENEMENTS_SORTANTS.c.type_evenement == "m5.rentabilite_chantier"
                    )
                ).scalars()
            ],
            key=lambda x: x["sequence"],
        )
        assert charges[-1]["verdict"] == "PARTIELLE", "invalidation aval manquante après révision du tarif"
    # Relecture et rejeu du répartiteur ne doublent pas la réception.
    with session():
        recus_avant = list(stockage.maillons("m05-financecore", "wct_recus"))
    assert len([x for x in recus_avant if x["wct_id"] == wct_id]) == 1
    rejeu = evenements.repartir(
        {"m05-financecore": affaire["deps"]["m05-financecore"]}, maintenant="2030-06-08T12:01:00-04:00"
    )
    assert rejeu["echecs"] == 0
    with session():
        assert list(stockage.maillons("m05-financecore", "wct_recus")) == recus_avant
    # Révocation SQL effective : la page et l'export deviennent inaccessibles.
    with session() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    apres_revocation = f.m.base._instantane_base(session)
    assert catalogue.get(url).status_code == 403
    assert catalogue.get(url + "/export.json").status_code == 403
    assert catalogue.post(trace_url, data=commande).status_code == 403
    assert f.m.base._instantane_base(session) == apres_revocation
