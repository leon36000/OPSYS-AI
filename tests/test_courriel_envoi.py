"""Envoi SOUS SAS : un envoi est un brouillon dont la transmission est N3. Sans jeton, jeton rejoué, contenu modifié
après approbation, destinataire ajouté, approbateur non humain ou désactivé, injection d'en-têtes, issue incertaine.
Vrai sas d'approbation, vraie base, vrai coffre ; réseau et serveurs de courrier = doubles. NON testé contre un vrai
fournisseur."""

from __future__ import annotations

import inspect
import json
import threading

import courriel_doubles as dbl
import courriel_qa as qa
import pytest
from sqlalchemy import select

from opsys import approbations, identite, stockage
from opsys.courriel_connecteurs import comptes, envoi, gmail, graph, imap, mbox
from opsys.courriel_connecteurs.envoi import (
    NOM_OUTIL,
    OUTIL_APPROBATION,
    GardeEnvoiSas,
    ServiceEnvoi,
    marquer_reservations_orphelines,
)
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.courriel_connecteurs.modele import (
    BrouillonSortant,
    ContenuBrouillon,
    JetonApprobation,
    PieceSortante,
)
from opsys.outils import Niveau
from opsys.stockage.schema import APPROBATIONS, COURRIEL_BROUILLONS

FICTIF = True
SCOPES_ENVOI = f"{qa.SCOPE_GMAIL_LECTURE} {qa.SCOPE_GMAIL_ENVOI}"
CORPS = "Bonjour, voici les informations demandées pour votre dossier."
SOURCES = ["gmail:msg-0001", "note:rencontre-2026-10-28"]


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = qa.preparer(
        tmp_path, monkeypatch, scope_google=SCOPES_ENVOI, scope_microsoft="Mail.Read Mail.Send offline_access"
    )
    qa.creer_compte(m, usage="lecture_envoi")
    qa.connecter_oauth(m)
    return m


@pytest.fixture
def gm(monde):
    return monde.service.fournisseur("gmail-paul")


def _creer(**surcharges):
    champs = {"a": ["cliente.fictive@example.test"], "objet": "Suite à votre demande", "corps": CORPS}
    champs.update(surcharges)
    with stockage.transaction() as cnx:
        return envoi.creer_brouillon(cnx, "agent-m1", "gmail-paul", **champs)


def _demander(brouillon, **options):
    with stockage.transaction() as cnx:
        return envoi.demander_approbation(
            cnx,
            "agent-m1",
            brouillon.brouillon_id,
            contexte="Réponse à la demande du client.",
            sources=SOURCES,
            **options,
        )


def _decider(demande_id, approuver=True, acteur="nathan"):
    with stockage.transaction() as cnx:
        return approbations.decider(cnx, demande_id, approuver, acteur, {NOM_OUTIL: OUTIL_APPROBATION}, {})


def _approuve(**surcharges):
    brouillon = _creer(**surcharges)
    demande = _demander(brouillon)
    decision = _decider(demande)
    assert decision["statut"] == "executee", decision
    return brouillon, demande


def _statut(brouillon_id):
    with stockage.transaction() as cnx:
        return envoi.statut_brouillon(cnx, brouillon_id)["statut"]


# -- le chemin normal -----------------------------------------------------------------------------
def test_parcours_complet_brouillon_approbation_n3_envoi_une_fois(monde, gm):
    brouillon = _creer(cc=["comptable.fictive@example.test"], cci=["archives@example.test"])
    assert _statut(brouillon.brouillon_id) == "BROUILLON" and monde.gmail.envoyes == []
    demande = _demander(brouillon)
    with stockage.transaction() as cnx:
        sas = approbations.lire(cnx, demande)
    assert sas["statut"] == "en_attente" and sas["niveau"] == "N3" and sas["outil"] == NOM_OUTIL
    assert monde.gmail.envoyes == [] and _statut(brouillon.brouillon_id) == "DEMANDE"  # rien ne part avant la décision
    assert _decider(demande)["statut"] == "executee"
    assert _statut(brouillon.brouillon_id) == "APPROUVE" and monde.gmail.envoyes == []  # approuver n'envoie pas
    recu = ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    assert recu.empreinte == brouillon.empreinte and recu.fournisseur == "gmail"
    assert _statut(brouillon.brouillon_id) == "ENVOYE" and len(monde.gmail.envoyes) == 1
    brut = monde.gmail.envoyes[0].decode()
    assert "To: cliente.fictive@example.test" in brut and "Cc: comptable.fictive@example.test" in brut
    assert "From: paul.fictif@example.test" in brut and CORPS in brut and "Bcc: archives@example.test" in brut


def test_la_demande_au_sas_porte_contexte_sources_empreinte_jamais_le_corps(monde):
    brouillon = _creer(cci=["archives@example.test"])
    demande = _demander(brouillon)
    with stockage.transaction() as cnx:
        sas = approbations.lire(cnx, demande)
    a = sas["arguments"]
    assert a["empreinte"] == brouillon.empreinte and a["contexte"] == "Réponse à la demande du client."
    assert a["sources"] == SOURCES and a["destinataires"]["cci"] == ["archives@example.test"] and a["objet"]
    assert CORPS not in json.dumps(sas)


def test_contexte_et_sources_obligatoires(monde):
    brouillon = _creer()
    for contexte, sources in (
        ("", SOURCES),
        ("ok", []),
        ("ok", "gmail:1"),
        ("x" * 501, SOURCES),
        ("ok", [""]),
        ("ok", ["a\nb"]),
        ("ok", ["s"] * 21),
    ):
        with pytest.raises(ErreurCourriel) as exc, stockage.transaction() as cnx:
            envoi.demander_approbation(cnx, "agent-m1", brouillon.brouillon_id, contexte=contexte, sources=sources)
        assert exc.value.code == "REJ-COURRIEL-APPROBATION-INVALIDE"
    assert _statut(brouillon.brouillon_id) == "BROUILLON"


def test_l_outil_du_sas_est_n3_et_ferme_aux_appareils():
    assert OUTIL_APPROBATION.niveau_effectif is Niveau.N3 and OUTIL_APPROBATION.roles_appareil == frozenset()
    assert not OUTIL_APPROBATION.frontiere_humaine


# -- sans jeton -----------------------------------------------------------------------------------
def test_aucune_methode_d_envoi_sans_jeton_d_approbation():
    for classe in (gmail.FournisseurGmail, graph.FournisseurGraph, imap.FournisseurImap, mbox.FournisseurMbox):
        publiques = {nom: f for nom, f in inspect.getmembers(classe, inspect.isfunction) if not nom.startswith("_")}
        envois = {
            nom: f for nom, f in publiques.items() if any(m in nom for m in ("envoy", "send", "transm", "poster"))
        }
        assert set(envois) <= {"envoyer_brouillon"}, f"{classe.__name__} expose {set(envois)}"
        for nom, f in envois.items():
            assert (
                "jeton" in inspect.signature(f).parameters
                or nom == "envoyer_brouillon"
                and classe is mbox.FournisseurMbox
            )
    assert (
        inspect.signature(gmail.FournisseurGmail.envoyer_brouillon).parameters["jeton"].default
        is inspect.Parameter.empty
    )


def test_envoi_sans_jeton_ou_avec_un_jeton_vide_refuse(monde, gm):
    brouillon = _creer()
    with pytest.raises(TypeError):
        gm.envoyer_brouillon(brouillon)  # type: ignore[call-arg]
    for jeton in (
        None,
        JetonApprobation("", brouillon.empreinte),
        JetonApprobation("   ", brouillon.empreinte),
        JetonApprobation("0123456789ab", brouillon.empreinte),
        "texte",
    ):
        with pytest.raises(ErreurCourriel) as exc:
            gm.envoyer_brouillon(brouillon, jeton)  # type: ignore[arg-type]
        assert exc.value.code == "REJ-COURRIEL-APPROBATION-ABSENTE"
    assert monde.gmail.envoyes == [] and not any("/send" in r.url for r in monde.transport.requetes)


def test_service_envoi_refuse_un_brouillon_non_approuve(monde, gm):
    brouillon = _creer()
    with pytest.raises(ErreurCourriel) as exc:
        ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-NON-APPROUVEE"
    demande = _demander(brouillon)
    with pytest.raises(ErreurCourriel):
        ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    # un jeton fabriqué à la main pour une demande encore en attente n'ouvre rien non plus
    with pytest.raises(ErreurCourriel) as exc:
        gm.envoyer_brouillon(brouillon, JetonApprobation(demande, brouillon.empreinte))
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-NON-APPROUVEE" and monde.gmail.envoyes == []


def test_demande_refusee_par_l_humain_n_autorise_rien(monde, gm):
    brouillon = _creer()
    demande = _demander(brouillon)
    assert _decider(demande, approuver=False)["statut"] == "refusee"
    with pytest.raises(ErreurCourriel) as exc:
        gm.envoyer_brouillon(brouillon, JetonApprobation(demande, brouillon.empreinte))
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-NON-APPROUVEE" and monde.gmail.envoyes == []


def test_personne_sans_role_autorise_ne_peut_pas_approuver(monde, gm):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe", "Employé fictif", "mot-de-passe-employe-1234", ["employee"])
    brouillon = _creer()
    demande = _demander(brouillon)
    with pytest.raises(ValueError, match="aucun rôle autorisé"):
        _decider(demande, acteur="employe")
    assert _statut(brouillon.brouillon_id) == "DEMANDE" and monde.gmail.envoyes == []


# -- jeton rejoué ---------------------------------------------------------------------------------
def test_course_perdue_entre_verification_et_reservation_la_comparaison_echange_protege(monde, gm):
    """Un concurrent gagne APRÈS les vérifications et AVANT la réservation : la comparaison-échange (statut
    APPROUVE) doit refuser, sinon deux envois partiraient."""
    from sqlalchemy import event

    brouillon, demande = _approuve()
    moteur = stockage.moteur()
    declenche = []

    def concurrent(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT courriel_comptes.etat") and not declenche:
            declenche.append(True)
            conn.exec_driver_sql("UPDATE courriel_brouillons SET statut = 'ENVOYE' WHERE statut = 'APPROUVE'")

    event.listen(moteur, "before_cursor_execute", concurrent)
    try:
        with pytest.raises(ErreurCourriel) as exc:
            gm.envoyer_brouillon(brouillon, JetonApprobation(demande, brouillon.empreinte))
    finally:
        event.remove(moteur, "before_cursor_execute", concurrent)
    assert declenche and exc.value.code == "REJ-COURRIEL-BROUILLON-ETAT" and monde.gmail.envoyes == []
    assert _statut(brouillon.brouillon_id) == "ENVOYE"


def test_l_outil_refuse_un_brouillon_dont_la_base_ne_correspond_plus_a_la_demande(monde):
    """Défense en profondeur : même si la ligne reste `DEMANDE` avec la bonne demande, une révision ou une empreinte
    différente (altération, bogue) interdit l'approbation."""
    for colonne, valeur in (("revision", 7), ("empreinte", "e" * 64)):
        brouillon = _creer()
        demande = _demander(brouillon)
        with stockage.transaction() as cnx:
            cnx.execute(COURRIEL_BROUILLONS.update().where(
                COURRIEL_BROUILLONS.c.brouillon_id == brouillon.brouillon_id).values({colonne: valeur}))
        decision = _decider(demande)
        assert decision["statut"] == "echec", colonne
        assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-COURRIEL-APPROBATION-CONTENU-MODIFIE"
        assert _statut(brouillon.brouillon_id) == "DEMANDE"


def test_jeton_a_usage_unique(monde, gm):
    brouillon, demande = _approuve()
    service = ServiceEnvoi(stockage.transaction)
    service.envoyer(gm, brouillon.brouillon_id)
    jeton = JetonApprobation(demande, brouillon.empreinte)
    for _ in range(2):
        with pytest.raises(ErreurCourriel) as exc:
            gm.envoyer_brouillon(brouillon, jeton)
        assert exc.value.code == "REJ-COURRIEL-APPROBATION-REJOUEE"
    with pytest.raises(ErreurCourriel):
        service.envoyer(gm, brouillon.brouillon_id)
    assert len(monde.gmail.envoyes) == 1


def test_envois_concurrents_un_seul_part(monde, gm):
    brouillon, demande = _approuve()
    jeton = JetonApprobation(demande, brouillon.empreinte)
    resultats: list[str] = []

    def tenter():
        try:
            monde.service.fournisseur("gmail-paul").envoyer_brouillon(brouillon, jeton)
            resultats.append("ok")
        except ErreurCourriel as exc:
            resultats.append(exc.code)

    fils = [threading.Thread(target=tenter) for _ in range(4)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert resultats.count("ok") == 1 and len(monde.gmail.envoyes) == 1
    assert all(r in {"ok", "REJ-COURRIEL-APPROBATION-REJOUEE", "REJ-COURRIEL-BROUILLON-ETAT"} for r in resultats), (
        resultats
    )


def test_une_approbation_ne_sert_qu_a_son_brouillon(monde, gm):
    a, demande_a = _approuve(objet="Dossier A")
    b = _creer(objet="Dossier B", corps="Autre contenu entièrement.")
    with pytest.raises(ErreurCourriel) as exc:
        gm.envoyer_brouillon(b, JetonApprobation(demande_a, b.empreinte))
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-INVALIDE"
    with pytest.raises(ErreurCourriel) as exc:
        gm.envoyer_brouillon(b, JetonApprobation(demande_a, a.empreinte))
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-CONTENU-MODIFIE"
    assert monde.gmail.envoyes == []


# -- contenu modifié ------------------------------------------------------------------------------
def test_modification_apres_approbation_annule_l_approbation(monde, gm):
    brouillon, demande = _approuve()
    nouveau = None
    with stockage.transaction() as cnx:
        nouveau = envoi.modifier_brouillon(
            cnx, "agent-m1", brouillon.brouillon_id, revision_attendue=1, corps=CORPS + " Veuillez aussi nous écrire."
        )
    assert nouveau.revision == 2 and nouveau.empreinte != brouillon.empreinte
    assert _statut(brouillon.brouillon_id) == "BROUILLON"
    with pytest.raises(ErreurCourriel) as exc:  # le service ne trouve plus de brouillon approuvé
        ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-NON-APPROUVEE"
    for presente, jeton in (
        (nouveau, JetonApprobation(demande, brouillon.empreinte)),
        (nouveau, JetonApprobation(demande, nouveau.empreinte)),
        (brouillon, JetonApprobation(demande, brouillon.empreinte)),
    ):
        with pytest.raises(ErreurCourriel) as exc:
            gm.envoyer_brouillon(presente, jeton)
        assert exc.value.code in {"REJ-COURRIEL-APPROBATION-CONTENU-MODIFIE", "REJ-COURRIEL-APPROBATION-INVALIDE"}
    assert monde.gmail.envoyes == []


def test_modification_entre_la_demande_et_la_decision_l_outil_refuse(monde, gm):
    brouillon = _creer()
    demande = _demander(brouillon)
    with stockage.transaction() as cnx:
        envoi.modifier_brouillon(cnx, "agent-m1", brouillon.brouillon_id, revision_attendue=1, objet="Objet changé")
    decision = _decider(demande)
    assert decision["statut"] == "echec"
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-COURRIEL-APPROBATION-CONTENU-MODIFIE"
    assert _statut(brouillon.brouillon_id) == "BROUILLON" and monde.gmail.envoyes == []


def test_destinataire_ajoute_apres_approbation(monde, gm):
    brouillon, demande = _approuve()
    c = brouillon.contenu
    for champ, valeur in (
        ("cc", ("espion@example.test",)),
        ("cci", ("espion@example.test",)),
        ("a", (*c.a, "espion@example.test")),
    ):
        modifie = ContenuBrouillon(**{**{f: getattr(c, f) for f in c.__dataclass_fields__}, champ: valeur})
        falsifie = BrouillonSortant(brouillon.brouillon_id, 1, modifie, modifie.empreinte())
        for jeton in (JetonApprobation(demande, brouillon.empreinte), JetonApprobation(demande, modifie.empreinte())):
            with pytest.raises(ErreurCourriel) as exc:
                gm.envoyer_brouillon(falsifie, jeton)
            assert exc.value.code in {"REJ-COURRIEL-APPROBATION-CONTENU-MODIFIE", "REJ-COURRIEL-APPROBATION-INVALIDE"}
    assert monde.gmail.envoyes == [] and _statut(brouillon.brouillon_id) == "APPROUVE"


def test_piece_jointe_remplacee_ou_corps_altere_change_l_empreinte(monde):
    base = _creer(pieces=[PieceSortante("devis.pdf", "application/pdf", dbl.pdf_fictif("A"))])
    autre = _creer(pieces=[PieceSortante("devis.pdf", "application/pdf", dbl.pdf_fictif("B"))])
    assert base.empreinte != autre.empreinte
    c = base.contenu
    assert c.empreinte() == ContenuBrouillon(**{f: getattr(c, f) for f in c.__dataclass_fields__}).empreinte()
    reordonne = ContenuBrouillon(**{**{f: getattr(c, f) for f in c.__dataclass_fields__}, "a": tuple(reversed(c.a))})
    assert reordonne.empreinte() == c.empreinte()  # l'ordre des adresses n'est pas du contenu
    majuscules = ContenuBrouillon(
        **{**{f: getattr(c, f) for f in c.__dataclass_fields__}, "a": tuple(x.upper() for x in c.a)}
    )
    assert majuscules.empreinte() == c.empreinte()  # les adresses sont insensibles à la casse


def test_brouillon_forge_avec_une_empreinte_incoherente_refuse_des_la_construction():
    contenu = ContenuBrouillon("c", "a@example.test", ("b@example.test",), (), (), "objet", "corps")
    with pytest.raises(ValueError):
        BrouillonSortant("b" * 32, 1, contenu, "0" * 64)


def test_brouillon_altere_en_base_est_detecte_a_la_lecture(monde):
    brouillon, _ = _approuve()
    with stockage.transaction() as cnx:
        cnx.execute(COURRIEL_BROUILLONS.update().values(empreinte="f" * 64))
    with pytest.raises(ErreurCourriel) as exc, stockage.transaction() as cnx:
        envoi.lire_brouillon(cnx, brouillon.brouillon_id)
    assert exc.value.code == "REJ-COURRIEL-BROUILLON-INVALIDE"


# -- approbateur ----------------------------------------------------------------------------------
def test_approbateur_desactive_apres_decision_l_approbation_ne_vaut_plus(monde, gm):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "directrice", "Directrice fictive", "mot-de-passe-directrice-12", ["nathan_owner"])
    brouillon = _creer()
    demande = _demander(brouillon)
    assert _decider(demande, acteur="directrice")["statut"] == "executee"
    with stockage.transaction() as cnx:
        identite.activer(cnx, "directrice", False)
    with pytest.raises(ErreurCourriel) as exc:
        ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-INVALIDE" and monde.gmail.envoyes == []


def test_demande_d_un_autre_outil_ne_vaut_pas_approbation_d_envoi(monde, gm):
    brouillon = _creer()
    with stockage.transaction() as cnx:
        faux = approbations.creer_demande(
            cnx,
            "m01-front-office",
            "m1_autre_outil",
            {"empreinte": brouillon.empreinte, "brouillon_id": brouillon.brouillon_id},
            niveau=Niveau.N3,
        )
        cnx.execute(
            APPROBATIONS.update()
            .where(APPROBATIONS.c.id == faux)
            .values(statut="executee", decide_par="nathan", decide_role="nathan_owner")
        )
    with pytest.raises(ErreurCourriel) as exc:
        gm.envoyer_brouillon(brouillon, JetonApprobation(faux, brouillon.empreinte))
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-INVALIDE"


def test_demande_au_niveau_insuffisant_refusee(monde, gm):
    brouillon, demande = _approuve()
    with stockage.transaction() as cnx:
        cnx.execute(APPROBATIONS.update().where(APPROBATIONS.c.id == demande).values(niveau="N2"))
    with pytest.raises(ErreurCourriel) as exc:
        gm.envoyer_brouillon(brouillon, JetonApprobation(demande, brouillon.empreinte))
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-INVALIDE"


def test_approbateur_agent_systeme_refuse(monde, gm):
    brouillon, demande = _approuve()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "bot", "Agent fictif", "mot-de-passe-bot-1234567", ["system_agent"])
        cnx.execute(
            APPROBATIONS.update()
            .where(APPROBATIONS.c.id == demande)
            .values(decide_par="bot", decide_role="system_agent")
        )
    with pytest.raises(ErreurCourriel) as exc:
        gm.envoyer_brouillon(brouillon, JetonApprobation(demande, brouillon.empreinte))
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-INVALIDE"


# -- validation du contenu ------------------------------------------------------------------------
@pytest.mark.parametrize(
    "champs",
    [
        {"a": ["x@example.test\r\nBcc: espion@example.test"]},
        {"a": ["x@example.test\nCc: y@example.test"]},
        {"a": ["Jean <x@example.test>"]},
        {"a": ["x@example.test, y@example.test"]},
        {"a": ["x@example.test;y@example.test"]},
        {"a": []},
        {"a": "x@example.test"},
        {"a": ["pas-une-adresse"]},
        {"a": ["x@example.test"], "cci": ["a\x00@example.test"]},
        {"a": [f"u{i}@example.test" for i in range(51)]},
        {"objet": "Bonjour\r\nBcc: espion@example.test"},
        {"objet": "Salut\nX-Injecté: 1"},
        {"objet": ""},
        {"objet": "x" * 301},
        {"corps": ""},
        {"corps": "a\x00b"},
        {"en_reponse_a": "id>\r\nBcc: x@example.test"},
        {"en_reponse_a": "a b"},
    ],
)
def test_injection_d_en_tetes_et_adresses_invalides_refusees(monde, champs):
    with pytest.raises(ErreurCourriel) as exc:
        _creer(**champs)
    assert exc.value.code == "REJ-COURRIEL-BROUILLON-INVALIDE"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(COURRIEL_BROUILLONS)).first() is None


def test_corps_trop_gros(monde):
    with pytest.raises(ErreurCourriel) as exc:
        _creer(corps="x" * (envoi.CORPS_MAX + 1))
    assert exc.value.code == "REJ-COURRIEL-BROUILLON-TROP-GROS"


def test_expediteur_toujours_celui_du_compte(monde, gm):
    brouillon, _ = _approuve()
    assert brouillon.contenu.de == "paul.fictif@example.test"
    with pytest.raises(TypeError):
        _creer(de="patron@example.test")  # l'appelant ne choisit pas l'expéditeur


@pytest.mark.parametrize(
    "corps",
    [
        "Le montant total est de 12 500 $.",
        "Nous nous engageons à terminer les travaux.",
        "C'est notre faute, nous sommes responsables.",
        "Vous avez le droit de refuser de payer.",
    ],
)
def test_garde_fou_de_sortie_refuse_prix_engagement_aveu_avis_legal(monde, corps):
    with pytest.raises(ErreurCourriel) as exc:
        _creer(corps=corps)
    assert exc.value.code == "REJ-COURRIEL-BROUILLON-GARDE-FOU" and "REJ-" in exc.value.detail


def test_garde_fou_de_sortie_remplacable_par_l_appelant_de_confiance(monde):
    with stockage.transaction() as cnx:
        b = envoi.creer_brouillon(
            cnx,
            "nathan",
            "gmail-paul",
            a=["x@example.test"],
            objet="Prix",
            profil=None,
            corps="Le montant total est de 12 500 $.",
        )
    assert b.contenu.corps.endswith("$.")


@pytest.mark.parametrize(
    "piece",
    [
        PieceSortante("virus.pdf", "application/pdf", b"MZ" + b"\x00" * 50),
        PieceSortante("a.exe", "application/octet-stream", b"MZ" + b"\x00" * 50),
        PieceSortante("a.png", "image/png", dbl.pdf_fictif()),
        PieceSortante("../x.pdf", "application/pdf", dbl.pdf_fictif()),
        PieceSortante("a\r\nb.pdf", "application/pdf", dbl.pdf_fictif()),
        PieceSortante("vide.pdf", "application/pdf", b""),
        PieceSortante("p.html", "text/html", b"<html></html>"),
    ],
)
def test_pieces_sortantes_non_permises(monde, piece):
    with pytest.raises(ErreurCourriel) as exc:
        _creer(pieces=[piece])
    assert exc.value.code == "REJ-COURRIEL-BROUILLON-INVALIDE"


def test_pieces_trop_nombreuses_ou_trop_lourdes(monde):
    pdf = dbl.pdf_fictif()
    with pytest.raises(ErreurCourriel) as exc:
        _creer(pieces=[PieceSortante(f"p{i}.pdf", "application/pdf", pdf) for i in range(6)])
    assert exc.value.code == "REJ-COURRIEL-BROUILLON-TROP-GROS"
    with pytest.raises(ErreurCourriel) as exc:
        _creer(pieces=[PieceSortante("g.pdf", "application/pdf", b"%PDF-" + b"0" * (envoi.PIECES_OCTETS_MAX + 1))])
    assert exc.value.code == "REJ-COURRIEL-BROUILLON-TROP-GROS"


def test_compte_en_lecture_seule_ne_peut_pas_avoir_de_brouillon(tmp_path, monkeypatch):
    m = qa.preparer(tmp_path, monkeypatch)
    qa.creer_compte(m)
    qa.connecter_oauth(m)
    with pytest.raises(ErreurCourriel) as exc, stockage.transaction() as cnx:
        envoi.creer_brouillon(cnx, "agent-m1", "gmail-paul", a=["x@example.test"], objet="o", corps="c")
    assert exc.value.code == "REJ-COURRIEL-ENVOI-NON-SUPPORTE"
    assert m.service.fournisseur("gmail-paul")._garde is None  # aucun sas raccordé à un compte en lecture seule


def test_adaptateur_sans_garde_refuse_tout_envoi(monde):
    brouillon, demande = _approuve()
    sans_garde = gmail.FournisseurGmail(monde.service.fournisseur("gmail-paul")._client)
    with pytest.raises(ErreurCourriel) as exc:
        sans_garde.envoyer_brouillon(brouillon, JetonApprobation(demande, brouillon.empreinte))
    assert exc.value.code == "REJ-COURRIEL-ENVOI-NON-SUPPORTE" and monde.gmail.envoyes == []


# -- issues d'envoi -------------------------------------------------------------------------------
def test_5xx_a_l_envoi_issue_incertaine_jamais_de_reprise_automatique(monde, gm):
    brouillon, demande = _approuve()
    monde.gmail.scripter(dbl.reponse_5xx(500))
    with pytest.raises(ErreurCourriel) as exc:
        ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    assert exc.value.code == "REJ-COURRIEL-ENVOI-INCERTAIN" and not exc.value.reprenable
    assert _statut(brouillon.brouillon_id) == "INCERTAIN"
    assert len([r for r in monde.transport.requetes if r.url.endswith("/messages/send")]) == 1
    with pytest.raises(ErreurCourriel) as exc:
        gm.envoyer_brouillon(brouillon, JetonApprobation(demande, brouillon.empreinte))
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-REJOUEE"


def test_panne_reseau_a_l_envoi_issue_incertaine(monde, gm):
    brouillon, _ = _approuve()
    from opsys.courriel_connecteurs.transport import ErreurTransport

    monde.gmail.scripter(ErreurTransport("delai"))
    with pytest.raises(ErreurCourriel) as exc:
        ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    assert exc.value.code == "REJ-COURRIEL-ENVOI-INCERTAIN" and _statut(brouillon.brouillon_id) == "INCERTAIN"


def test_429_a_l_envoi_non_traite_le_meme_jeton_resert(monde, gm):
    brouillon, _ = _approuve()
    monde.gmail.scripter(dbl.reponse_429("30"))
    with pytest.raises(ErreurCourriel) as exc:
        ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    assert exc.value.code == "REJ-COURRIEL-LIMITE-DEBIT" and exc.value.reessayer_apres_s == 30
    assert _statut(brouillon.brouillon_id) == "APPROUVE" and monde.gmail.envoyes == []
    ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    assert len(monde.gmail.envoyes) == 1 and _statut(brouillon.brouillon_id) == "ENVOYE"


def test_refus_definitif_du_fournisseur_exige_un_nouveau_brouillon_approuve(monde, gm):
    brouillon, demande = _approuve()
    monde.gmail.scripter(dbl._json(400, {"error": {"message": "Invalid To header"}}))
    with pytest.raises(ErreurCourriel) as exc:
        ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    assert exc.value.code == "REJ-COURRIEL-REQUETE-INVALIDE" and _statut(brouillon.brouillon_id) == "ECHEC"
    with pytest.raises(ErreurCourriel) as exc:
        gm.envoyer_brouillon(brouillon, JetonApprobation(demande, brouillon.empreinte))
    assert exc.value.code == "REJ-COURRIEL-APPROBATION-REJOUEE"


def test_reservation_orpheline_devient_incertaine(monde, gm):
    brouillon, demande = _approuve()
    garde = GardeEnvoiSas(stockage.transaction)
    garde.reserver(brouillon, JetonApprobation(demande, brouillon.empreinte), "gmail")  # puis le processus meurt
    assert _statut(brouillon.brouillon_id) == "ENVOI_RESERVE"
    with stockage.transaction() as cnx:
        assert marquer_reservations_orphelines(cnx, plus_vieilles_que_s=900) == 0  # trop récente
        assert marquer_reservations_orphelines(cnx, plus_vieilles_que_s=-1) == 1
    assert _statut(brouillon.brouillon_id) == "INCERTAIN"
    with pytest.raises(ErreurCourriel):
        gm.envoyer_brouillon(brouillon, JetonApprobation(demande, brouillon.empreinte))
    assert monde.gmail.envoyes == []


def test_compte_revoque_apres_approbation_aucun_envoi(monde, gm):
    brouillon, demande = _approuve()
    monde.service.revoquer(qa.ADMIN, "gmail-paul")
    with pytest.raises(ErreurCourriel) as exc:
        gm.envoyer_brouillon(brouillon, JetonApprobation(demande, brouillon.empreinte))
    assert exc.value.code == "REJ-COURRIEL-COMPTE-INACTIF" and monde.gmail.envoyes == []


# -- aucun contenu ni secret dans les traces ------------------------------------------------------
def test_ni_corps_ni_secret_dans_la_base_le_journal_ni_les_erreurs(monde, gm):
    corps = "Contenu confidentiel du brouillon QWERTY-9981."
    brouillon, demande = _approuve(corps=corps)
    ServiceEnvoi(stockage.transaction).envoyer(gm, brouillon.brouillon_id)
    acces = monde.oauth_google.dernier_acces
    stockage.liberer()
    octets = b"".join(p.read_bytes() for p in (monde.tmp_path / "opsys-home").rglob("*") if p.is_file())
    assert corps.encode() not in octets and acces.encode() not in octets
    with stockage.transaction() as cnx:
        journal = json.dumps(comptes.journal(cnx, "gmail-paul", 500), default=str)
    assert corps not in journal and "cliente.fictive" not in journal and acces not in journal
    evenements = {j["evenement"] for j in json.loads(journal)}
    assert {"brouillon.cree", "brouillon.demande", "brouillon.approuve", "envoi.reserve", "envoi.envoye"} <= evenements


def test_journal_refuse_tout_detail_hors_liste_blanche(monde):
    with stockage.transaction() as cnx:
        for details in (
            {"corps": "texte"},
            {"destinataire": "a@example.test"},
            {"jeton": "abc"},
            {"dossier": "x" * 65},
            {"messages": [1, 2]},
            {"statut": {"a": 1}},
        ):
            with pytest.raises(ValueError):
                comptes.journaliser(cnx, "gmail-paul", "test", "nathan", details=details)


def test_journal_append_only(monde):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    with stockage.transaction() as cnx:
        comptes.journaliser(cnx, "gmail-paul", "test", "nathan")
    for requete in ("UPDATE courriel_journal SET code = 'x'", "DELETE FROM courriel_journal"):
        with pytest.raises(DBAPIError, match="journal courriel immuable"), stockage.transaction() as cnx:
            cnx.execute(text(requete))


# -- Graph et IMAP/SMTP ---------------------------------------------------------------------------
def test_envoi_graph_sous_garde(monde):
    qa.creer_compte(monde, "graph-paul", "graph", "lecture_envoi")
    qa.connecter_oauth(monde, "graph-paul")
    with stockage.transaction() as cnx:
        b = envoi.creer_brouillon(
            cnx,
            "agent-m1",
            "graph-paul",
            a=["x@example.test"],
            cci=["archives@example.test"],
            objet="Objet Graph",
            corps=CORPS,
            pieces=[PieceSortante("devis.pdf", "application/pdf", dbl.pdf_fictif())],
        )
        demande = envoi.demander_approbation(cnx, "agent-m1", b.brouillon_id, contexte="ctx", sources=SOURCES)
    graphe = monde.service.fournisseur("graph-paul")
    with pytest.raises(ErreurCourriel):
        graphe.envoyer_brouillon(b, JetonApprobation(demande, b.empreinte))
    assert monde.graph.envoyes == []
    _decider(demande)
    ServiceEnvoi(stockage.transaction).envoyer(graphe, b.brouillon_id)
    (message,) = monde.graph.envoyes
    assert message["saveToSentItems"] is True and message["message"]["subject"] == "Objet Graph"
    assert message["message"]["bccRecipients"][0]["emailAddress"]["address"] == "archives@example.test"
    assert message["message"]["attachments"][0]["name"] == "devis.pdf"
    assert message["message"]["body"] == {"contentType": "Text", "content": CORPS}


def test_envoi_smtp_cci_dans_l_enveloppe_pas_dans_les_en_tetes(monde):
    qa.creer_compte(
        monde,
        "imap-paul",
        "imap",
        "lecture_envoi",
        configuration={
            "hote": "imap.example.test",
            "smtp_hote": "smtp.example.test",
            "utilisateur": monde.serveur_imap.utilisateur,
        },
    )
    monde.service.enregistrer_mot_de_passe_imap(qa.ADMIN, "imap-paul", monde.serveur_imap.mot_de_passe)
    with stockage.transaction() as cnx:
        b = envoi.creer_brouillon(
            cnx,
            "agent-m1",
            "imap-paul",
            a=["x@example.test"],
            cci=["archives@example.test"],
            objet="Objet SMTP",
            corps=CORPS,
        )
        demande = envoi.demander_approbation(cnx, "agent-m1", b.brouillon_id, contexte="ctx", sources=SOURCES)
    boite = monde.service.fournisseur("imap-paul")
    with pytest.raises(ErreurCourriel):
        boite.envoyer_brouillon(b, JetonApprobation(demande, b.empreinte))
    assert monde.serveur_smtp.envoyes == [] and monde.serveur_smtp.connexions == 0  # refusé AVANT toute connexion
    _decider(demande)
    ServiceEnvoi(stockage.transaction).envoyer(boite, b.brouillon_id)
    (envoye,) = monde.serveur_smtp.envoyes
    assert set(envoye["a"]) == {"x@example.test", "archives@example.test"}
    assert b"Bcc:" not in envoye["message"] and b"archives@example.test" not in envoye["message"]
    assert monde.serveur_imap.mot_de_passe.encode() not in envoye["message"]


@pytest.mark.parametrize(
    "panne, code, statut",
    [
        ("refus", "REJ-COURRIEL-ENVOI-ECHEC", "ECHEC"),
        ("coupure", "REJ-COURRIEL-ENVOI-INCERTAIN", "INCERTAIN"),
    ],
)
def test_smtp_refus_definitif_ou_coupure_en_cours_d_envoi(monde, panne, code, statut):
    qa.creer_compte(
        monde,
        "imap-paul",
        "imap",
        "lecture_envoi",
        configuration={
            "hote": "imap.example.test",
            "smtp_hote": "smtp.example.test",
            "utilisateur": monde.serveur_imap.utilisateur,
        },
    )
    monde.service.enregistrer_mot_de_passe_imap(qa.ADMIN, "imap-paul", monde.serveur_imap.mot_de_passe)
    with stockage.transaction() as cnx:
        b = envoi.creer_brouillon(cnx, "agent-m1", "imap-paul", a=["x@example.test"], objet="o", corps=CORPS)
        demande = envoi.demander_approbation(cnx, "agent-m1", b.brouillon_id, contexte="ctx", sources=SOURCES)
    _decider(demande)
    monde.serveur_smtp.refuser_destinataires = panne == "refus"
    monde.serveur_smtp.panne_pendant_envoi = panne == "coupure"
    with pytest.raises(ErreurCourriel) as exc:
        ServiceEnvoi(stockage.transaction).envoyer(monde.service.fournisseur("imap-paul"), b.brouillon_id)
    assert exc.value.code == code and _statut(b.brouillon_id) == statut


def test_smtp_authentification_refusee_rien_n_est_envoye(monde):
    qa.creer_compte(
        monde,
        "imap-paul",
        "imap",
        "lecture_envoi",
        configuration={
            "hote": "imap.example.test",
            "smtp_hote": "smtp.example.test",
            "utilisateur": monde.serveur_imap.utilisateur,
        },
    )
    monde.service.enregistrer_mot_de_passe_imap(qa.ADMIN, "imap-paul", monde.serveur_imap.mot_de_passe)
    with stockage.transaction() as cnx:
        b = envoi.creer_brouillon(cnx, "agent-m1", "imap-paul", a=["x@example.test"], objet="o", corps=CORPS)
        demande = envoi.demander_approbation(cnx, "agent-m1", b.brouillon_id, contexte="ctx", sources=SOURCES)
    _decider(demande)
    monde.serveur_smtp.mot_de_passe = "autre-mot-de-passe"
    with pytest.raises(ErreurCourriel) as exc:
        ServiceEnvoi(stockage.transaction).envoyer(monde.service.fournisseur("imap-paul"), b.brouillon_id)
    assert exc.value.code == "REJ-COURRIEL-IMAP-AUTH" and _statut(b.brouillon_id) == "ECHEC"
    assert monde.serveur_smtp.envoyes == [] and "mot-de-passe-app-fictif" not in str(exc.value)
