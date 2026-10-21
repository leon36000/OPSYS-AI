"""Contrat privé des tickets de liaison de cible `_meta`."""

from __future__ import annotations

import pytest

from opsys import liaison_cibles


def test_le_parseur_ne_lit_que_le_meta_mcp_et_ignore_la_cle_absente():
    assert liaison_cibles.depuis_meta_mcp(None) is None
    assert liaison_cibles.depuis_meta_mcp({}) is None
    assert liaison_cibles.depuis_meta_mcp({"progress_token": "x"}) is None


def test_le_parseur_rend_le_ticket_opaque_sans_le_normaliser():
    jeton = "opaque-ticket-fictif-1234567890"

    assert liaison_cibles.depuis_meta_mcp({"opsys/cibleTicket": jeton}) == liaison_cibles.TicketMeta(jeton)


@pytest.mark.parametrize("valeur", [None, "", "  ", 123, ["ticket"], {"ticket": "x"}, "x" * 4097])
def test_le_meta_ticket_present_invalide_echoue_sans_reveler_sa_valeur(valeur):
    with pytest.raises(ValueError) as erreur:
        liaison_cibles.depuis_meta_mcp({"opsys/cibleTicket": valeur})

    assert "opsys/cibleTicket" in str(erreur.value)
    assert repr(valeur) not in str(erreur.value)


def test_la_resolution_m2_exige_un_seul_lead_canonique_et_refuse_les_ids_contradictoires():
    assert liaison_cibles.cible_de_l_outil("m2_transitionner_statut", {"lead_id": "L-1"}) == (
        "m02-revenue-crm", "L-1", "lead"
    )
    with pytest.raises(liaison_cibles.CibleRefusee):
        liaison_cibles.cible_de_l_outil("m2_transitionner_statut", {"lead_id": "L-1", "client_id": "C-2"})


def test_la_resolution_m3_passe_par_un_devis_unique_pas_par_un_lead_fourni_par_le_modele():
    with pytest.raises(liaison_cibles.CibleRefusee):
        liaison_cibles.cible_de_l_outil("m3_marquer_devis_accepte", {"lead_id": "L-1"})
    with pytest.raises(liaison_cibles.CibleRefusee):
        liaison_cibles.cible_de_l_outil("m3_demander_envoi_devis", {"devis_id": "D-1", "lead_id": "L-1"})


def test_la_creation_m3_lie_le_devis_neuf_au_lead_et_refuse_les_cibles_secondaires():
    arguments = {
        "devis_id": "DEV-FICTIF-C02", "lead_id": "LEAD-FICTIF-C02", "chantier_id": None,
        "lignes": [{"description": "Gouttières fictives"}], "taux_marge": "0.20",
        "horodatage": "2026-10-02T12:00:00+00:00",
    }
    assert liaison_cibles.cible_de_l_outil("m3_creer_devis", arguments) == (
        "m03-estimation", "LEAD-FICTIF-C02", "lead"
    )
    assert liaison_cibles.cible_de_l_outil(
        "m3_creer_devis", {**arguments, "chantier_id": "LEAD-FICTIF-C02"}
    ) == ("m03-estimation", "LEAD-FICTIF-C02", "lead")
    for invalide in (
        {**arguments, "lead_id": " "},
        {**arguments, "chantier_id": "CHANTIER-FICTIF-AUTRE"},
        {**arguments, "client_id": "CLIENT-FICTIF"},
        {**arguments, "wct_id": "WCT-FICTIF"},
        {cle: valeur for cle, valeur in arguments.items() if cle != "lead_id"},
    ):
        with pytest.raises(liaison_cibles.CibleRefusee):
            liaison_cibles.cible_de_l_outil("m3_creer_devis", invalide)


def test_le_ticket_de_creation_m3_est_emis_sans_creer_le_devis_et_revalide_lead_et_collision(session):
    import datetime as dt

    from m3_estimation import devis_durable

    from opsys import stockage

    cle_session = _preparer_affaire_durable(session)
    arguments = {
        "devis_id": "DEV-FICTIF-C02", "lead_id": "LEAD-C02", "chantier_id": None,
        "lignes": [{"description": "Gouttières fictives", "quantite": "10", "unite": "pi_lin",
                    "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.20", "horodatage": "2026-09-30T12:00:00+00:00",
    }
    instant = dt.datetime(2026, 9, 30, 12, tzinfo=dt.UTC)
    with session() as cnx:
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement="m03-estimation", agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil="m3_creer_devis",
            arguments=arguments, maintenant=instant,
        )
        devis, verdict = devis_durable.lire_devis(stockage.maillons("m03-estimation", "devis"), arguments["devis_id"])
    assert ticket["ticket"]
    assert devis is None and verdict is not None

    with session() as cnx, pytest.raises(liaison_cibles.CibleRefusee, match="chantier"):
        liaison_cibles.emettre_ticket(
            cnx, departement="m03-estimation", agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil="m3_creer_devis",
            arguments={**arguments, "chantier_id": "CHANTIER-FICTIF"}, maintenant=instant,
        )
    with session() as cnx, pytest.raises(liaison_cibles.CibleRefusee, match="ne correspond pas"):
        liaison_cibles.emettre_ticket(
            cnx, departement="m03-estimation", agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil="m3_creer_devis",
            arguments={**arguments, "lead_id": "LEAD-C02~opp~WCT-FICTIF"}, maintenant=instant,
        )
    with session() as cnx, pytest.raises(liaison_cibles.CibleRefusee, match="autre lead"):
        devis_durable.creer_devis(
            "DEV-EXISTANT-AUTRE-LEAD", "LEAD-AUTRE-FICTIF", None, arguments["lignes"], "0.20",
            arguments["horodatage"], stockage.maillons("m03-estimation", "devis"),
        )
        # Reuse the occupied identifier on a different dossier; the ticket resolver must reject it.
        liaison_cibles.emettre_ticket(
            cnx, departement="m03-estimation", agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil="m3_creer_devis",
            arguments={**arguments, "devis_id": "DEV-EXISTANT-AUTRE-LEAD"}, maintenant=instant,
        )


@pytest.mark.parametrize(
    ("outil", "departement", "arguments"),
    [
        (
            "m3_creer_devis",
            "m03-estimation",
            {
                "devis_id": "DEV-CHAINE-M2-FICTIF",
                "lead_id": "LEAD-C02",
                "chantier_id": None,
                "lignes": [],
                "taux_marge": "0.20",
                "horodatage": "2026-09-30T12:00:00+00:00",
            },
        ),
        (
            "m2_enregistrer_interaction",
            "m02-revenue-crm",
            {
                "lead_id": "LEAD-C02",
                "resume": "interaction fictive",
                "horodatage": "2026-09-30T12:00:00+00:00",
            },
        ),
    ],
)
def test_ticket_refuse_une_chaine_m2_corrompue_sans_ticket_ni_brouillon(
    session, outil, departement, arguments
):
    from m3_estimation import devis_durable
    from sqlalchemy import select, update

    from opsys import stockage
    from opsys.stockage import codec
    from opsys.stockage.schema import LIAISONS_TICKETS, REGISTRES

    cle_session = _preparer_affaire_durable(session)
    with session() as cnx:
        ligne = cnx.execute(
            select(REGISTRES.c.rang, REGISTRES.c.maillon).where(
                REGISTRES.c.departement == "m02-revenue-crm",
                REGISTRES.c.registre == "principal",
            )
        ).one()
        maillon_corrompu = codec.decoder(ligne.maillon)
        maillon_corrompu["statut"] = "converti-corrompu"
        cnx.execute(
            update(REGISTRES)
            .where(
                REGISTRES.c.departement == "m02-revenue-crm",
                REGISTRES.c.registre == "principal",
                REGISTRES.c.rang == ligne.rang,
            )
            .values(maillon=codec.encoder(maillon_corrompu))
        )

        with pytest.raises(liaison_cibles.CibleRefusee, match="chaîne.*M2 invalide"):
            liaison_cibles.emettre_ticket(
                cnx,
                departement=departement,
                agent_id="m02-revenue-crm",
                cle_session=cle_session,
                affaire_id="LEAD-C02",
                origine_affaire="session",
                outil=outil,
                arguments=arguments,
            )
        assert cnx.execute(select(LIAISONS_TICKETS)).all() == []

        if outil == "m3_creer_devis":
            devis, verdict = devis_durable.lire_devis(
                stockage.maillons("m03-estimation", "devis"), arguments["devis_id"]
            )
            assert devis is None and verdict is not None


def test_ticket_refuse_une_chaine_m10_corrompue_sans_ticket_ni_brouillon(session):
    from m3_estimation import devis_durable
    from sqlalchemy import select, update

    from opsys import stockage
    from opsys.stockage import codec
    from opsys.stockage.schema import LIAISONS_TICKETS, REGISTRES

    cle_session = _preparer_affaire_durable(session)
    arguments = {
        "devis_id": "DEV-CHAINE-M10-FICTIF",
        "lead_id": "LEAD-C02",
        "chantier_id": None,
        "lignes": [],
        "taux_marge": "0.20",
        "horodatage": "2026-09-30T12:00:00+00:00",
    }
    with session() as cnx:
        ligne = cnx.execute(
            select(REGISTRES.c.rang, REGISTRES.c.maillon).where(
                REGISTRES.c.departement == "m10-memoire",
                REGISTRES.c.registre == "affaires",
            )
        ).one()
        maillon_corrompu = codec.decoder(ligne.maillon)
        maillon_corrompu["affaire_id"] = "LEAD-CORROMPU-FICTIF"
        cnx.execute(
            update(REGISTRES)
            .where(
                REGISTRES.c.departement == "m10-memoire",
                REGISTRES.c.registre == "affaires",
                REGISTRES.c.rang == ligne.rang,
            )
            .values(maillon=codec.encoder(maillon_corrompu))
        )

        with pytest.raises(liaison_cibles.CibleRefusee, match="chaîne.*M10 invalide"):
            liaison_cibles.emettre_ticket(
                cnx,
                departement="m03-estimation",
                agent_id="m02-revenue-crm",
                cle_session=cle_session,
                affaire_id="LEAD-C02",
                origine_affaire="session",
                outil="m3_creer_devis",
                arguments=arguments,
            )
        assert cnx.execute(select(LIAISONS_TICKETS)).all() == []
        devis, verdict = devis_durable.lire_devis(
            stockage.maillons("m03-estimation", "devis"), arguments["devis_id"]
        )
        assert devis is None and verdict is not None


def test_ticket_de_creation_m3_scelle_le_n3_et_ne_cree_le_brouillon_quapres_approbation(session):
    from pathlib import Path

    from m3_estimation import devis_durable

    from opsys import approbations, identite, stockage
    from opsys.capacites import Capacites
    from opsys.departements import lire_manifeste

    cle_session = _preparer_affaire_durable(session)
    racine = Path(__file__).resolve().parents[1] / "departments" / "m03-estimation"
    departement = lire_manifeste(racine)
    outil = next(outil for outil in departement.charger_outils() if outil.nom == "m3_creer_devis")
    arguments = {
        "devis_id": "DEV-APPROUVE-FICTIF-C02", "lead_id": "LEAD-C02", "chantier_id": "LEAD-C02",
        "lignes": [{"description": "Gouttières fictives", "quantite": "10", "unite": "pi_lin",
                    "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.20", "horodatage": "2026-09-30T12:00:00+00:00",
    }
    with session() as cnx:
        approbations.fixer_mode(cnx, departement.id, "ombre", "admin-c02")
        identite.creer_personne(cnx, "nathan", "Nathan", "mot-de-passe-fictif-long", ["nathan_owner"])
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement=departement.id, agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil=outil.nom, arguments=arguments,
        )
    cap = Capacites({departement.id: departement}, session, appelant=departement.id, memoire=False)
    cap.index[outil.nom] = (departement, outil)
    meta = liaison_cibles.TicketMeta(ticket["ticket"])
    demande = cap.appeler(outil.nom, arguments, ticket_cible=meta)
    assert demande["ok"] is True and demande["statut"] == "en_attente_approbation"
    assert cap.appeler(outil.nom, arguments, ticket_cible=meta)["rejoue"] is True
    with session() as cnx:
        devis, verdict = devis_durable.lire_devis(
            stockage.maillons("m03-estimation", "devis"), arguments["devis_id"]
        )
        assert devis is None and verdict is not None
        approbations.decider(
            cnx, demande["demande_id"], True, "nathan", {outil.nom: outil}, {departement.id: departement}
        )
    with session() as cnx:
        devis, verdict = devis_durable.lire_devis(
            stockage.maillons("m03-estimation", "devis"), arguments["devis_id"]
        )
    assert verdict is None and devis is not None and devis["statut"] == "brouillon"
    assert cap.appeler(outil.nom, arguments, ticket_cible=meta)["rejoue"] is True

    with session() as cnx:
        approbations.fixer_mode(cnx, departement.id, "autonome", "admin-c02")
        ticket_rejeu = liaison_cibles.emettre_ticket(
            cnx, departement=departement.id, agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil=outil.nom, arguments=arguments,
        )
    with session() as cnx:
        nombre_avant = len(stockage.maillons("m03-estimation", "devis"))
    reprise = cap.appeler(
        outil.nom, arguments, ticket_cible=liaison_cibles.TicketMeta(ticket_rejeu["ticket"])
    )
    with session() as cnx:
        nombre_apres = len(stockage.maillons("m03-estimation", "devis"))
    assert reprise["ok"] is True and reprise["resultat"]["accepte"] is True
    assert nombre_apres == nombre_avant

    arguments_divergents = {
        **arguments,
        "lignes": [{**arguments["lignes"][0], "cout_unitaire": "99.00"}],
    }
    with session() as cnx:
        ticket_collision = liaison_cibles.emettre_ticket(
            cnx, departement=departement.id, agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil=outil.nom,
            arguments=arguments_divergents,
        )
    collision = cap.appeler(
        outil.nom, arguments_divergents,
        ticket_cible=liaison_cibles.TicketMeta(ticket_collision["ticket"]),
    )
    with session() as cnx:
        nombre_apres_collision = len(stockage.maillons("m03-estimation", "devis"))
    assert collision["ok"] is True
    assert collision["resultat"]["accepte"] is False
    assert collision["resultat"]["verdict"]["code"] == "REJ-DEVIS-ID-DEJA-UTILISE"
    assert nombre_apres_collision == nombre_avant


def test_ticket_de_creation_m3_refuse_apres_revocation_avant_toute_ecriture(session):
    from pathlib import Path

    from m3_estimation import devis_durable
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    from opsys import stockage
    from opsys.capacites import Capacites
    from opsys.departements import lire_manifeste

    cle_session = _preparer_affaire_durable(session)
    racine = Path(__file__).resolve().parents[1] / "departments" / "m03-estimation"
    departement = lire_manifeste(racine)
    outil = next(outil for outil in departement.charger_outils() if outil.nom == "m3_creer_devis")
    arguments = {
        "devis_id": "DEV-REVOQUE-FICTIF-C02", "lead_id": "LEAD-C02", "chantier_id": None,
        "lignes": [{"description": "Gouttières fictives", "quantite": "10", "unite": "pi_lin",
                    "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.20", "horodatage": "2026-09-30T12:00:00+00:00",
    }
    with session() as cnx:
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement=departement.id, agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil=outil.nom, arguments=arguments,
        )
        lien = liaison_m10.liaison_courante(
            cle_session, registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        )
        assert lien is not None
        liaison_m10.revoquer_session_affaire(
            cle_session, lien["ligne_id"], "nathan", "admin", "appareil", "Révocation fictive avant appel.",
            "2026-09-30T12:01:00+00:00",
            registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires")),
        )
    cap = Capacites({departement.id: departement}, session, appelant=departement.id, memoire=False)
    cap.index[outil.nom] = (departement, outil)
    reponse = cap.appeler(
        outil.nom, arguments, ticket_cible=liaison_cibles.TicketMeta(ticket["ticket"])
    )
    assert reponse["ok"] is False and reponse["erreur"] == "cible_refusee"
    with session() as cnx:
        devis, verdict = devis_durable.lire_devis(
            stockage.maillons("m03-estimation", "devis"), arguments["devis_id"]
        )
    assert devis is None and verdict is not None


def test_migration_cree_le_stockage_meme_base_du_ticket_et_son_lien_approbation(session):
    from sqlalchemy import inspect


    with session() as cnx:
        tables = set(inspect(cnx).get_table_names())
        colonnes_approbation = {col["name"] for col in inspect(cnx).get_columns("approbations")}

    assert "liaisons_tickets" in tables
    assert "ticket_cible_hash" in colonnes_approbation


def test_upgrade_0012_preserve_une_approbation_existante(tmp_path):
    from alembic import command
    from sqlalchemy import text

    from opsys import stockage

    url = f"sqlite:///{tmp_path / 'avant-c02.db'}"
    moteur = stockage.moteur(url)
    config = stockage._config()
    with moteur.begin() as cnx:
        config.attributes["connection"] = cnx
        command.upgrade(config, "0012")
        cnx.execute(text("""
            INSERT INTO approbations
                (id, cree_le, departement, outil, arguments, statut, niveau)
            VALUES ('demande-existante', '2026-09-29T10:00:00+00:00', 'm03-estimation',
                    'm3_demander_envoi_devis', '{}', 'en_attente', 'N4')
        """))

    stockage.migrer(url)
    with moteur.connect() as cnx:
        demande = cnx.execute(text("SELECT id, statut, niveau FROM approbations")).one()
        table = cnx.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='liaisons_tickets'"))

    assert demande == ("demande-existante", "en_attente", "N4")
    assert table.one() == ("liaisons_tickets",)
    stockage.liberer()


def test_empreinte_ticket_approbation_n_est_pas_exposee_dans_les_lectures_publiques(session):
    from sqlalchemy import update

    from opsys import approbations
    from opsys.outils import Niveau
    from opsys.stockage.schema import APPROBATIONS

    with session() as cnx:
        ident = approbations.creer_demande(
            cnx, "m03-estimation", "m3_demander_envoi_devis", {"devis_id": "D-C02"},
            niveau=Niveau.N4,
        )
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
            ticket_cible_hash="f" * 64
        ))
        demande = approbations.lire(cnx, ident)

    assert demande is not None
    assert "ticket_cible_hash" not in demande


def _preparer_affaire_durable(session, lead_id="LEAD-C02"):
    from m2_revenue_crm import ingestion
    from m2_revenue_crm import registre as registre_m2
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    from opsys import stockage

    contrat = {
        "lead_id": lead_id,
        "conversation_id": "CONV-C02",
        "contact": {"nom": "Client fictif", "telephone": "555-0101", "courriel": "x@example.test"},
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "telephone",
    }
    reg_m2 = registre_m2.Registre()
    assert ingestion.ingerer(contrat, reg_m2, "2026-09-30T12:00:00+00:00")[1] is None
    cle_session = "agent:m02-revenue-crm:webchat:direct:contact-c02"
    with session():
        stockage.maillons("m02-revenue-crm", "principal").extend(reg_m2.lire())
        reg_m10 = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        lien, refus = liaison_m10.lier_session_affaire(
            cle_session, lead_id, "nathan", "admin", "appareil", "liaison fictive autorisée",
            "2026-09-30T12:00:00+00:00", reg_m10,
        )
        assert refus is None and lien is not None
    return cle_session


def test_ticket_lie_un_lead_m2_canonique_a_la_liaison_m10_active(session):
    import datetime as dt

    cle_session = _preparer_affaire_durable(session)
    arguments = {"lead_id": "LEAD-C02", "resume": "appel fictif", "horodatage": "2026-09-30T12:00:00+00:00"}
    with session() as cnx:
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement="m02-revenue-crm", agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil="m2_enregistrer_interaction",
            arguments=arguments, maintenant=dt.datetime(2026, 9, 30, 12, tzinfo=dt.UTC),
        )

    assert ticket["ticket"]
    assert ticket["expire_le"] == "2026-09-30T12:02:00+00:00"
    with session() as cnx:
        from sqlalchemy import select

        ligne = cnx.execute(select(liaison_cibles.LIAISONS_TICKETS)).mappings().one()
    assert ligne["ticket_hash"] == liaison_cibles.empreinte_ticket(ticket["ticket"])
    assert ticket["ticket"] not in str(dict(ligne))


def test_ticket_refuse_expiration_arguments_modifies_et_rejeu_repond_sans_reexecuter(session):
    import datetime as dt

    cle_session = _preparer_affaire_durable(session)
    args = {"lead_id": "LEAD-C02", "resume": "appel fictif", "horodatage": "2026-09-30T12:00:00+00:00"}
    instant = dt.datetime(2026, 9, 30, 12, tzinfo=dt.UTC)
    with session() as cnx:
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement="m02-revenue-crm", agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil="m2_enregistrer_interaction",
            arguments=args, maintenant=instant,
        )
    meta = liaison_cibles.TicketMeta(ticket["ticket"])
    with session() as cnx:
        with pytest.raises(liaison_cibles.CibleRefusee, match="arguments"):
            liaison_cibles.verifier_ticket(
                cnx, meta, departement="m02-revenue-crm", outil="m2_enregistrer_interaction",
                arguments={**args, "resume": "modifié"}, maintenant=instant,
            )
        with pytest.raises(liaison_cibles.CibleRefusee, match="expiré"):
            liaison_cibles.verifier_ticket(
                cnx, meta, departement="m02-revenue-crm", outil="m2_enregistrer_interaction",
                arguments=args, maintenant=instant + dt.timedelta(seconds=121),
            )
        valide = liaison_cibles.verifier_ticket(
            cnx, meta, departement="m02-revenue-crm", outil="m2_enregistrer_interaction",
            arguments=args, maintenant=instant + dt.timedelta(seconds=1),
        )
        reponse = {"ok": True, "resultat": {"accepte": True, "resultat": {"ligne": 1}}}
        liaison_cibles.consommer_ticket(cnx, valide, reponse)
    with session() as cnx:
        rejeu = liaison_cibles.verifier_ticket(
            cnx, meta, departement="m02-revenue-crm", outil="m2_enregistrer_interaction",
            arguments=args, maintenant=instant + dt.timedelta(hours=1),
        )
    assert rejeu.reponse_rejouee == reponse


def test_ticket_m3_resout_le_devis_vers_le_lead_reel_et_stocke_le_genre_affaire_m10(session):
    import datetime as dt

    from m2_revenue_crm import registre as registre_m2
    from m2_revenue_crm import statuts
    from m3_estimation import devis_durable

    from opsys import stockage

    cle_session = _preparer_affaire_durable(session)
    ligne = {
        "description": "Gouttières fictives", "quantite": "10", "unite": "pi_lin",
        "cout_unitaire": "10.00", "reference_besoin_materiau": None,
    }
    with session() as cnx:
        reg_m2 = registre_m2.Registre(maillons=stockage.maillons("m02-revenue-crm", "principal"))
        accuse, verdict = statuts.transitionner(
            "LEAD-C02", "qualifie", reg_m2, "2026-09-30T11:59:00+00:00", owner="vendeur-fictif",
            prochaine_action={"description": "Appeler le client", "echeance": "2026-10-01T12:00:00+00:00"},
        )
        assert accuse is not None and verdict is None
        devis_durable.creer_devis(
            "DEV-C02", "LEAD-C02", "LEAD-C02", [ligne], "0.20", "2026-09-30T12:00:00+00:00",
            stockage.maillons("m03-estimation", "devis"),
        )
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement="m03-estimation", agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil="m3_marquer_devis_accepte",
                arguments={"devis_id": "DEV-C02", "approbateur": "nathan",
                           "horodatage": "2026-09-30T12:00:00+00:00"},
            maintenant=dt.datetime(2026, 9, 30, 12, tzinfo=dt.UTC),
        )

    assert ticket["ticket"]
    with session() as cnx:
        from sqlalchemy import select

        ligne_ticket = cnx.execute(select(liaison_cibles.LIAISONS_TICKETS)).mappings().one()
    assert ligne_ticket["genre_affaire"] == "lead"


def test_ticket_m3_refuse_un_chantier_devis_sans_liaison_canonique_concordante(session):
    import datetime as dt

    from m3_estimation import devis_durable

    from opsys import stockage

    cle_session = _preparer_affaire_durable(session)
    arguments = {"devis_id": "DEV-CHANTIER-INCONNU", "approbateur": "Nathan",
                 "horodatage": "2026-09-30T12:00:00+00:00"}
    with session() as cnx:
        devis_durable.creer_devis(
            "DEV-CHANTIER-INCONNU", "LEAD-C02", "CHANTIER-INCONNU-FICTIF",
            [{"description": "Gouttières", "quantite": "10", "unite": "pi_lin",
              "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
            "0.20", "2026-09-30T12:00:00+00:00", stockage.maillons("m03-estimation", "devis"),
        )
        with pytest.raises(liaison_cibles.CibleRefusee, match="chantier"):
            liaison_cibles.emettre_ticket(
                cnx, departement="m03-estimation", agent_id="m02-revenue-crm", cle_session=cle_session,
                affaire_id="LEAD-C02", origine_affaire="session", outil="m3_marquer_devis_accepte",
                arguments=arguments, maintenant=dt.datetime(2026, 9, 30, 12, tzinfo=dt.UTC),
            )


def test_ticket_m3_refuse_de_convertir_un_lead_deja_rattache_a_un_autre_devis(session):
    import datetime as dt

    from m2_revenue_crm import registre as registre_m2
    from m2_revenue_crm import statuts
    from m3_estimation import devis_durable

    from opsys import stockage

    cle_session = _preparer_affaire_durable(session)
    with session() as cnx:
        devis_durable.creer_devis(
            "DEV-PREMIER-C02", "LEAD-C02", None,
            [{"description": "Première soumission", "quantite": "1", "unite": "unite",
              "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
            "0.20", "2026-09-30T12:00:00+00:00", stockage.maillons("m03-estimation", "devis"),
        )
        devis_durable.creer_devis(
            "DEV-CIBLE-C02", "LEAD-C02", None,
            [{"description": "Autre soumission", "quantite": "1", "unite": "unite",
              "cout_unitaire": "20.00", "reference_besoin_materiau": None}],
            "0.20", "2026-09-30T12:00:00+00:00", stockage.maillons("m03-estimation", "devis"),
        )
        registre = registre_m2.Registre(maillons=stockage.maillons("m02-revenue-crm", "principal"))
        accuse, verdict = statuts.transitionner(
            "LEAD-C02", "qualifie", registre, "2026-09-30T12:00:00+00:00", owner="vendeur-fictif",
            prochaine_action={"description": "Appeler le client", "echeance": "2026-10-01T12:00:00+00:00"},
        )
        assert accuse is not None and verdict is None
        accuse, verdict = statuts.transitionner(
            "LEAD-C02", "converti", registre, "2026-09-30T12:01:00+00:00",
            reference_devis_m3="DEV-PREMIER-C02",
        )
        assert accuse is not None and verdict is None

        with pytest.raises(liaison_cibles.CibleRefusee, match="autre devis"):
            liaison_cibles.emettre_ticket(
                cnx, departement="m03-estimation", agent_id="m02-revenue-crm", cle_session=cle_session,
                affaire_id="LEAD-C02", origine_affaire="session", outil="m3_marquer_devis_accepte",
                arguments={"devis_id": "DEV-CIBLE-C02", "approbateur": "Nathan",
                           "horodatage": "2026-09-30T12:02:00+00:00"},
                maintenant=dt.datetime(2026, 9, 30, 12, tzinfo=dt.UTC),
            )


def _preparer_deux_devis_et_affaire_m3(session):
    import datetime as dt
    from pathlib import Path

    from m2_revenue_crm import registre as registre_m2
    from m2_revenue_crm import statuts
    from m3_estimation import devis_durable
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    from opsys import approbations, identite, stockage
    from opsys.departements import lire_manifeste

    cle_session = _preparer_affaire_durable(session)
    horodatage = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    with session() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan", "mot-de-passe-fictif-long", ["nathan_owner"])
        approbations.fixer_mode(cnx, "m03-estimation", "ombre", "admin-c02")
        maillons_devis = stockage.maillons("m03-estimation", "devis")
        for devis_id in ("DEV-C02-TARGET", "DEV-C02-OTHER"):
            devis_durable.creer_devis(
                devis_id, "LEAD-C02", None,
                [{"description": devis_id, "quantite": "1", "unite": "unite",
                  "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
                "0.20", horodatage, maillons_devis,
            )
        reg_m2 = registre_m2.Registre(maillons=stockage.maillons("m02-revenue-crm", "principal"))
        accuse, verdict = statuts.transitionner(
            "LEAD-C02", "qualifie", reg_m2, horodatage, owner="vendeur-fictif",
            prochaine_action={"description": "Appeler le client", "echeance": "2026-10-01T12:00:00+00:00"},
        )
        assert accuse is not None and verdict is None
        reg_m10 = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        lien = liaison_m10.liaison_courante(cle_session, reg_m10)
        assert lien is not None
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement="m03-estimation", agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil="m3_marquer_devis_accepte",
            arguments={"devis_id": "DEV-C02-TARGET", "approbateur": "Nathan", "horodatage": horodatage},
            maintenant=dt.datetime.now(dt.UTC),
        )
    departement = lire_manifeste(Path(__file__).resolve().parents[1] / "departments" / "m03-estimation")
    outil = next(o for o in departement.charger_outils() if o.nom == "m3_marquer_devis_accepte")
    return cle_session, horodatage, ticket, departement, outil


def _convertir_lead_par_autre_devis(session, horodatage):
    import datetime as dt

    from m2_revenue_crm import registre as registre_m2
    from m2_revenue_crm import statuts

    from opsys import stockage

    with session():
        reg_m2 = registre_m2.Registre(maillons=stockage.maillons("m02-revenue-crm", "principal"))
        accuse, verdict = statuts.transitionner(
            "LEAD-C02", "converti", reg_m2,
            (dt.datetime.fromisoformat(horodatage) + dt.timedelta(seconds=1)).isoformat(timespec="seconds"),
            reference_devis_m3="DEV-C02-OTHER",
        )
        assert accuse is not None and verdict is None


def test_ticket_m3_revalide_le_devis_apres_emission_avant_toute_demande_ou_evenement(session):
    from sqlalchemy import func, select

    from opsys.capacites import Capacites
    from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS

    _, horodatage, ticket, departement, outil = _preparer_deux_devis_et_affaire_m3(session)
    _convertir_lead_par_autre_devis(session, horodatage)
    cap = Capacites({departement.id: departement}, session, appelant=departement.id, memoire=False)
    cap.index[outil.nom] = (departement, outil)

    reponse = cap.appeler(
        outil.nom,
        {"devis_id": "DEV-C02-TARGET", "approbateur": "Nathan", "horodatage": horodatage},
        ticket_cible=liaison_cibles.TicketMeta(ticket["ticket"]),
    )

    assert reponse["ok"] is False and reponse["erreur"] == "cible_refusee"
    with session() as cnx:
        assert cnx.execute(select(func.count()).select_from(APPROBATIONS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one() == 0


def test_approbation_m3_refuse_si_un_autre_devis_convertit_le_lead_avant_le_clic(session):
    from m3_estimation import devis_durable
    from sqlalchemy import func, select

    from opsys import approbations, stockage
    from opsys.capacites import Capacites
    from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS

    _, horodatage, ticket, departement, outil = _preparer_deux_devis_et_affaire_m3(session)
    cap = Capacites({departement.id: departement}, session, appelant=departement.id, memoire=False)
    cap.index[outil.nom] = (departement, outil)
    arguments = {"devis_id": "DEV-C02-TARGET", "approbateur": "Nathan", "horodatage": horodatage}
    demande = cap.appeler(
        outil.nom, arguments, ticket_cible=liaison_cibles.TicketMeta(ticket["ticket"])
    )
    assert demande["statut"] == "en_attente_approbation"
    _convertir_lead_par_autre_devis(session, horodatage)

    with session() as cnx, pytest.raises(liaison_cibles.CibleRefusee, match="autre devis"):
        approbations.decider(
            cnx, demande["demande_id"], True, "nathan", {outil.nom: outil}, {departement.id: departement},
            attestation={
                "nom": "professionnel fictif",
                "profession": "entrepreneur",
                "reference_document": "DOC-FICTIF",
            },
        )

    with session() as cnx:
        ligne_demande = approbations.lire(cnx, demande["demande_id"])
        assert ligne_demande["statut"] == "en_attente"
        assert cnx.execute(select(func.count()).select_from(APPROBATIONS)).scalar_one() == 1
        assert cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one() == 0
        devis, verdict = devis_durable.lire_devis(
            stockage.maillons("m03-estimation", "devis"), "DEV-C02-TARGET"
        )
    assert ligne_demande["statut"] == "en_attente"
    assert devis is not None and verdict is None and devis["statut"] == "brouillon"


def test_une_mutation_n3_sans_ticket_exige_appareil_actif_et_portee_de_role(
    session, departements_demo, monkeypatch
):
    from opsys import contexte, idempotence, identite
    from opsys.capacites import Capacites
    from opsys.outils import Autonomie, Niveau, Outil

    nom = "m2_enregistrer_interaction"
    departement = next(iter(departements_demo.values()))
    cap = Capacites(departements_demo, session, appelant=departement.id, memoire=False)
    cap.index[nom] = (departement, Outil(
        nom=nom, description="Mutation fictive de preuve.",
        parametres={"type": "object", "properties": {"lead_id": {"type": "string"}},
                    "required": ["lead_id"], "additionalProperties": False},
        fonction=lambda lead_id: {"accepte": True, "lead_id": lead_id},
        autonomie=Autonomie.T1, niveau=Niveau.N3,
    ))
    monkeypatch.setattr(cap, "_outils_du_role", lambda role: frozenset({nom}) if role == "admin" else frozenset())
    executions = []
    monkeypatch.setattr(cap, "_distribuer", lambda outil, args, **kwargs: executions.append((outil, args)) or {
        "ok": True, "resultat": {"accepte": True}
    })
    with session() as cnx:
        identite.creer_personne(cnx, "admin-c02", "Admin fictif", "long-password-c02", ["admin"])
    meta = idempotence.Meta("action-c02-001", "appareil-c02", "2026-09-30T12:00:00+00:00")

    # Identité de modèle absente et identité révoquée/inactive n'obtiennent aucun ticket implicite.
    assert cap.appeler(nom, {"lead_id": "LEAD-C02"}, meta)["erreur"] == "ticket_cible_requis"
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("inactive", "admin")):
        assert cap.appeler(nom, {"lead_id": "LEAD-C02"}, meta)["erreur"] == "ticket_cible_requis"
    assert executions == []

    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin-c02", "admin")):
        reponse = cap.appeler(nom, {"lead_id": "LEAD-C02"}, meta)

    assert reponse["ok"] is True and reponse["rejoue"] is False
    assert executions == [(nom, {"lead_id": "LEAD-C02"})]


def test_retrait_role_entre_precontrole_et_transaction_n_emet_ni_recu_ni_mutation(
    session, departements_demo, monkeypatch
):
    from sqlalchemy import select

    from opsys import contexte, idempotence, identite
    from opsys.capacites import Capacites
    from opsys.outils import Autonomie, Niveau, Outil
    from opsys.stockage.schema import APPROBATIONS, MUTATIONS_APPLIQUEES

    nom = "m2_enregistrer_interaction"
    departement = next(iter(departements_demo.values()))
    cap = Capacites(departements_demo, session, appelant=departement.id, memoire=False)
    cap.index[nom] = (departement, Outil(
        nom=nom, description="Mutation fictive de preuve.",
        parametres={"type": "object", "properties": {"lead_id": {"type": "string"}},
                    "required": ["lead_id"], "additionalProperties": False},
        fonction=lambda lead_id: {"accepte": True, "lead_id": lead_id},
        autonomie=Autonomie.T1, niveau=Niveau.N3,
    ))
    monkeypatch.setattr(cap, "_outils_du_role", lambda role: frozenset({nom}) if role == "admin" else frozenset())
    executions = []
    monkeypatch.setattr(cap, "_distribuer", lambda outil, args, **kwargs: executions.append((outil, args)) or {
        "ok": True, "resultat": {"accepte": True}
    })
    with session() as cnx:
        identite.creer_personne(cnx, "admin-course-c02", "Admin fictif", "long-password-c02", ["admin"])
    original = cap._humain_n3_cible_valide
    appels = 0

    def retirer_role_apres_precontrole(outil, cnx=None):
        nonlocal appels
        appels += 1
        valide = original(outil, cnx)
        if appels == 1:
            with session() as cnx:
                identite.retirer_role(cnx, "admin-course-c02", "admin")
        return valide

    monkeypatch.setattr(cap, "_humain_n3_cible_valide", retirer_role_apres_precontrole)
    meta = idempotence.Meta("action-course-c02", "appareil-course-c02", "2026-09-30T12:00:00+00:00")
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin-course-c02", "admin")):
        reponse = cap.appeler(nom, {"lead_id": "LEAD-C02"}, meta)

    assert reponse["ok"] is False
    assert reponse["erreur"] == "ticket_cible_requis"
    assert appels == 2
    assert executions == []
    with session() as cnx:
        assert cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all() == []
        assert cnx.execute(select(APPROBATIONS)).mappings().all() == []


def test_un_appel_humain_n4_de_vendeur_cree_une_demande_meme_en_mode_autonome(
    session, monkeypatch
):
    from pathlib import Path

    from sqlalchemy import select

    from opsys import approbations, contexte, idempotence, identite
    from opsys.capacites import Capacites
    from opsys.departements import lire_manifeste
    from opsys.outils import Autonomie, Niveau, Outil
    from opsys.stockage.schema import APPROBATIONS

    racine = Path(__file__).resolve().parents[1] / "departments" / "m03-estimation"
    departement = lire_manifeste(racine)
    nom = "m3_demander_envoi_devis"
    cap = Capacites({departement.id: departement}, session, appelant=departement.id, memoire=False)
    executions = []
    cap.index[nom] = (departement, Outil(
        nom=nom, description="Demande fictive d'envoi N4.",
        parametres={"type": "object", "properties": {"devis_id": {"type": "string"}},
                    "required": ["devis_id"], "additionalProperties": False},
        fonction=lambda devis_id: executions.append(devis_id) or {"accepte": True},
        autonomie=Autonomie.T2, niveau=Niveau.N4,
    ))
    assert nom in cap._outils_du_role("seller")

    with session() as cnx:
        identite.creer_personne(cnx, "vendeur-c02-n4", "Vendeur fictif", "long-password-c02", ["seller"])
        approbations.fixer_mode(cnx, departement.id, "autonome", "admin-c02")

    arguments = {"devis_id": "DEV-N4-FICTIF"}
    meta = idempotence.Meta("demande-n4-c02", "appareil-n4-c02", "2026-09-30T12:00:00+00:00")
    appelante = contexte.IdentiteAppelante("vendeur-c02-n4", "seller")
    with contexte.appele_par_appareil(appelante):
        premiere = cap.appeler(nom, arguments, meta)
        rejouee = cap.appeler(nom, arguments, meta)

    assert premiere["ok"] is True and premiere["statut"] == "en_attente_approbation"
    assert rejouee["demande_id"] == premiere["demande_id"] and rejouee["rejoue"] is True
    assert executions == [], "un appel N4 humain crée une demande, jamais l'effet direct, même en mode autonome"
    with session() as cnx:
        demandes = cnx.execute(select(APPROBATIONS)).mappings().all()
    assert len(demandes) == 1 and demandes[0]["niveau"] == "N4" and demandes[0]["statut"] == "en_attente"


def test_un_appel_humain_n4_refuse_le_role_retire_dans_la_transaction(session, monkeypatch):
    from pathlib import Path

    from sqlalchemy import select

    from opsys import contexte, idempotence, identite
    from opsys.capacites import Capacites
    from opsys.departements import lire_manifeste
    from opsys.outils import Autonomie, Niveau, Outil
    from opsys.stockage.schema import APPROBATIONS, MUTATIONS_APPLIQUEES

    racine = Path(__file__).resolve().parents[1] / "departments" / "m03-estimation"
    departement = lire_manifeste(racine)
    nom = "m3_demander_envoi_devis"
    cap = Capacites({departement.id: departement}, session, appelant=departement.id, memoire=False)
    cap.index[nom] = (departement, Outil(
        nom=nom, description="Demande fictive d'envoi N4.",
        parametres={"type": "object", "properties": {"devis_id": {"type": "string"}},
                    "required": ["devis_id"], "additionalProperties": False},
        fonction=lambda **_: {"accepte": True}, autonomie=Autonomie.T2, niveau=Niveau.N4,
    ))
    with session() as cnx:
        identite.creer_personne(cnx, "vendeur-course-n4", "Vendeur fictif", "long-password-c02", ["seller"])
    original = cap._signataire_appareil_cible_valide
    appels = 0

    def retirer_role_apres_precontrole(nom_outil, cnx=None):
        nonlocal appels
        appels += 1
        valide = original(nom_outil, cnx)
        if appels == 1:
            with session() as cnx:
                identite.retirer_role(cnx, "vendeur-course-n4", "seller")
        return valide

    monkeypatch.setattr(cap, "_signataire_appareil_cible_valide", retirer_role_apres_precontrole, raising=False)
    meta = idempotence.Meta("demande-course-n4", "appareil-course-n4", "2026-09-30T12:00:00+00:00")
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("vendeur-course-n4", "seller")):
        reponse = cap.appeler(nom, {"devis_id": "DEV-N4-FICTIF"}, meta)

    assert appels == 2 and reponse["ok"] is False and reponse["erreur"] == "ticket_cible_requis"
    with session() as cnx:
        assert cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all() == []
        assert cnx.execute(select(APPROBATIONS)).mappings().all() == []


def test_ticket_scelle_est_revalide_apres_retrait_m10_avant_approbation(session, tmp_path):
    from pathlib import Path

    from m3_estimation import devis_durable
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    from opsys import approbations, identite, stockage
    from opsys.capacites import Capacites
    from opsys.departements import lire_manifeste
    from opsys.outils import Autonomie, Niveau, Outil

    cle_session = _preparer_affaire_durable(session)
    with session() as cnx:
        devis_durable.creer_devis(
            "DEV-APP-C02", "LEAD-C02", None,
            [{"description": "Gouttières", "quantite": "10", "unite": "pi_lin",
              "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
            "0.20", "2026-09-30T12:00:00+00:00", stockage.maillons("m03-estimation", "devis"),
        )
    racine = Path(__file__).resolve().parents[1] / "departments" / "m03-estimation"
    departement = lire_manifeste(racine)
    nom = "m3_demander_envoi_devis"
    args = {"devis_id": "DEV-APP-C02", "horodatage": "2026-09-30T12:00:00+00:00"}
    with session() as cnx:
        approbations.fixer_mode(cnx, departement.id, "ombre", "admin-c02")
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement=departement.id, agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil=nom, arguments=args,
        )
    executions = []
    outil = Outil(
        nom=nom, description="Envoi simulé de preuve, sans réseau.",
        parametres={"type": "object", "properties": {"devis_id": {"type": "string"},
                    "horodatage": {"type": "string"}}, "required": ["devis_id", "horodatage"],
                    "additionalProperties": False},
        fonction=lambda **_: executions.append("executed") or {"accepte": True},
        autonomie=Autonomie.T2, niveau=Niveau.N4,
    )
    cap = Capacites({departement.id: departement}, session, appelant=departement.id, memoire=False)
    cap.index[nom] = (departement, outil)
    demande = cap.appeler(nom, args, ticket_cible=liaison_cibles.TicketMeta(ticket["ticket"]))
    assert demande["statut"] == "en_attente_approbation"
    assert executions == []
    with session() as cnx:
        from sqlalchemy import select

        from opsys.stockage.schema import APPROBATIONS

        demande_lue = approbations.lire(cnx, demande["demande_id"])
        hash_lu = cnx.execute(select(liaison_cibles.LIAISONS_TICKETS.c.ticket_hash)).scalar_one()
        hash_demande = cnx.execute(select(APPROBATIONS.c.ticket_cible_hash).where(
            APPROBATIONS.c.id == demande["demande_id"]
        )).scalar_one()
        lien = liaison_m10.liaison_courante(cle_session, registre_m10.Registre(
            maillons=stockage.maillons("m10-memoire", "affaires")
        ))
        assert demande_lue is not None and "ticket_cible_hash" not in demande_lue
        assert hash_demande == hash_lu
        assert hash_lu == liaison_cibles.empreinte_ticket(ticket["ticket"])
        assert lien is not None
        liaison_m10.revoquer_session_affaire(
            cle_session, lien["ligne_id"], "nathan", "admin", "appareil", "Révocation fictive avant décision.",
            "2026-09-30T12:01:00+00:00", registre_m10.Registre(
                maillons=stockage.maillons("m10-memoire", "affaires")
            ),
        )
    with session() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan", "mot-de-passe-fictif-long", ["nathan_owner"])
    with session() as cnx, pytest.raises(liaison_cibles.CibleRefusee, match="révoquée"):
        approbations.decider(
            cnx, demande["demande_id"], True, "nathan", {nom: outil}, {departement.id: departement}
        )
    with session() as cnx:
        demande_finale = approbations.lire(cnx, demande["demande_id"])

    assert demande_finale["statut"] == "en_attente"
    assert executions == []


def test_approbation_execute_un_ticket_scelle_valide_une_fois_et_rejoue_la_reponse(session):
    import datetime as dt
    from pathlib import Path

    from m3_estimation import devis_durable

    from opsys import approbations, identite, stockage
    from opsys.capacites import Capacites
    from opsys.departements import lire_manifeste
    from opsys.outils import Autonomie, Niveau, Outil

    cle_session = _preparer_affaire_durable(session)
    racine = Path(__file__).resolve().parents[1] / "departments" / "m03-estimation"
    departement = lire_manifeste(racine)
    nom = "m3_demander_envoi_devis"
    maintenant = dt.datetime.now(dt.UTC)
    horodatage = maintenant.isoformat(timespec="seconds")
    arguments = {"devis_id": "DEV-APPROUVE-C02", "horodatage": horodatage}
    with session() as cnx:
        devis_durable.creer_devis(
            "DEV-APPROUVE-C02", "LEAD-C02", None,
            [{"description": "Gouttières", "quantite": "10", "unite": "pi_lin",
              "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
            "0.20", horodatage, stockage.maillons("m03-estimation", "devis"),
        )
        approbations.fixer_mode(cnx, departement.id, "ombre", "admin-c02")
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement=departement.id, agent_id="m02-revenue-crm", cle_session=cle_session,
            affaire_id="LEAD-C02", origine_affaire="session", outil=nom, arguments=arguments,
            maintenant=maintenant,
        )
        identite.creer_personne(cnx, "nathan", "Nathan", "mot-de-passe-fictif-long", ["nathan_owner"])

    executions = []
    outil = Outil(
        nom=nom, description="Envoi contrôlé par approbation fictive.",
        parametres={"type": "object", "properties": {"devis_id": {"type": "string"},
                    "horodatage": {"type": "string"}}, "required": ["devis_id", "horodatage"],
                    "additionalProperties": False},
        fonction=lambda **_: executions.append("envoye") or {"accepte": True},
        autonomie=Autonomie.T2, niveau=Niveau.N4,
    )
    cap = Capacites({departement.id: departement}, session, appelant=departement.id, memoire=False)
    cap.index[nom] = (departement, outil)
    demande = cap.appeler(nom, arguments, ticket_cible=liaison_cibles.TicketMeta(ticket["ticket"]))
    assert demande["statut"] == "en_attente_approbation"
    assert executions == []

    with session() as cnx:
        resultat = approbations.decider(
            cnx, demande["demande_id"], True, "nathan", {nom: outil}, {departement.id: departement}
        )
    assert resultat["statut"] == "executee"
    assert executions == ["envoye"]

    # Le secret consommé rejoue le résultat de cette action, sans ouvrir une nouvelle autorisation.
    rejeu = cap.appeler(nom, arguments, ticket_cible=liaison_cibles.TicketMeta(ticket["ticket"]))
    assert rejeu["rejoue"] is True
    assert executions == ["envoye"]
    with session() as cnx:
        from sqlalchemy import select

        ligne = cnx.execute(select(liaison_cibles.LIAISONS_TICKETS)).mappings().one()
    assert ligne["statut"] == "consomme"
    assert ligne["demande_id"] == demande["demande_id"]


def test_cli_revoquer_n_accepte_pas_identite_en_argument_et_authentifie_l_admin(session, monkeypatch, capsys):
    import builtins
    from types import SimpleNamespace

    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    from opsys import identite, memoire_liaison, stockage

    cle_session = _preparer_affaire_durable(session, "LEAD-CLI")
    with session() as cnx:
        identite.creer_personne(cnx, "admin-cli", "Admin", "mot-de-passe-cli-long", ["admin"])
        reg = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        lien = liaison_m10.liaison_courante(cle_session, reg)
    assert lien is not None
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(builtins, "input", lambda _prompt: "admin-cli")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "mot-de-passe-cli-long")

    resultat = memoire_liaison.main([
        "--session", cle_session, "--ligne", lien["ligne_id"], "--motif", "Fermeture demandée par le client.",
    ])

    assert resultat == 0
    assert "liaison révoquée" in capsys.readouterr().out
    with session() as cnx:
        reg = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        assert liaison_m10.affaire_de_la_session(cle_session, reg)["lie"] is False
        assert reg.lire()[-1]["source_decision"] == "cli"


def test_cli_refuse_role_retrait_et_ne_cree_aucun_maillon(session, monkeypatch, capsys):
    import builtins
    from types import SimpleNamespace

    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    from opsys import identite, stockage
    from opsys.memoire_liaison import main

    cle_session = _preparer_affaire_durable(session, "LEAD-CLI-ROLE")
    with session() as cnx:
        identite.creer_personne(cnx, "admin-cli", "Admin", "mot-de-passe-cli-long", ["admin"])
        identite.retirer_role(cnx, "admin-cli", "admin")
        reg = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        lien = liaison_m10.liaison_courante(cle_session, reg)
        avant = len(reg.lire())
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(builtins, "input", lambda _prompt: "admin-cli")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "mot-de-passe-cli-long")

    resultat = main([
        "--session", cle_session, "--ligne", lien["ligne_id"], "--motif", "Fermeture demandée par le client.",
    ])

    assert resultat == 1
    assert "authentification personnelle requise" in capsys.readouterr().err
    with session() as cnx:
        reg = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        assert len(reg.lire()) == avant
        assert liaison_m10.affaire_de_la_session(cle_session, reg)["lie"] is True


def test_cli_refuse_un_cas_perime_apres_une_nouvelle_liaison_sans_effet(session, monkeypatch, capsys):
    import builtins
    from types import SimpleNamespace

    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    from opsys import identite, stockage
    from opsys.memoire_liaison import main

    cle_session = _preparer_affaire_durable(session, "LEAD-CLI-CAS")
    with session() as cnx:
        identite.creer_personne(cnx, "admin-cli", "Admin", "mot-de-passe-cli-long", ["admin"])
        reg = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        ancienne = liaison_m10.liaison_courante(cle_session, reg)
        liaison_m10.lier_session_affaire(
            cle_session, "LEAD-CLI-CAS-2", "admin-cli", "admin", "appareil", "Nouvelle affaire du client.",
            "2026-09-30T12:01:00+00:00", reg,
        )
        avant = len(reg.lire())
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(builtins, "input", lambda _prompt: "admin-cli")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "mot-de-passe-cli-long")

    resultat = main([
        "--session", cle_session, "--ligne", ancienne["ligne_id"], "--motif", "Fermeture demandée par le client.",
    ])

    assert resultat == 1
    assert "liaison modifiée ou absente" in capsys.readouterr().err
    with session() as cnx:
        reg = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        assert len(reg.lire()) == avant
        assert liaison_m10.affaire_de_la_session(cle_session, reg)["affaire_id"] == "LEAD-CLI-CAS-2"
