"""Rétention Loi 25 : purges irréversibles gouvernées par le planificateur.

Preuves : inactif par défaut ; aperçu à blanc ; première activation = décision humaine liée à l'empreinte de ce qui a
été
vu ; sans décision valide rien ne s'efface ; ensuite la purge est automatique, idempotente, sans réécrire un registre
chaîné ; les empreintes qui évitent la réingestion restent ; ce qui n'est pas échu n'est pas touché. Vraie base, vrai
coffre, vraie file d'onboarding, vrai registre de M1 ; seuls le réseau et le courrier sont des doubles. Données
fictives."""

from __future__ import annotations

import json
from pathlib import Path

import cablage_qa as cq
import courriel_doubles as dbl
import courriel_qa as qa
import ingestion_onboarding_qa as onboarding_qa
import pytest
from sqlalchemy import func, select, text

from opsys import cles_chiffrement, stockage
from opsys.connecteurs_planification import etat, journal, planificateur
from opsys.connecteurs_planification import exec_retention as er
from opsys.ingestion_onboarding import depot
from opsys.retention import echeances, voix
from opsys.stockage.schema import (
    COURRIEL_BROUILLONS,
    COURRIEL_MESSAGES,
    INGESTION_BROUILLONS,
    INGESTION_DOCUMENTS,
    INGESTION_LOTS,
    INGESTION_TACHES,
    PLANIFICATEUR_APPROBATIONS,
    RETENTION_ECHEANCES,
)

FICTIF = True
F1 = onboarding_qa.texte_corpus("factures/F1-quincaillerie.txt")
JOUR = 86400


@pytest.fixture
def c(tmp_path, monkeypatch):
    mon = cq.monter(tmp_path, monkeypatch)
    qa.creer_compte(mon.monde, configuration={"reception_m1": 1})
    qa.connecter_oauth(mon.monde)
    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("UPDATE courriel_comptes SET retention_jours = 30")
    yield mon
    cq.demonter()


def _facture(i: int = 1, **options) -> bytes:
    return dbl.courriel_brut(objet=f"Facture {i}", corps=f"voir pièce {i}", message_id=f"<f{i}@example.test>",
                             pieces=[("facture.pdf", "application/pdf", onboarding_qa.pdf_texte(F1))], **options)


def _compter(table, *conditions) -> int:
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(table).where(*conditions)).scalar_one()


def _journal(executeur: str) -> list[dict]:
    with stockage.transaction() as cnx:
        return journal.lire(cnx, executeur)


def _archives() -> list[Path]:
    return sorted(depot.dossier_depot().glob("courriel-*.zip"))


def _synchroniser(c, *courriels: bytes) -> None:
    for courriel in courriels:
        c.monde.gmail.ajouter(courriel)
    c.activer("courriel.synchro")
    c.tour()
    c.activer("courriel.synchro", "inactif", motif="fin de la synchronisation d'essai")


# ========================================================================================== gouvernance
def test_la_retention_est_inactive_par_defaut_et_ne_purge_rien(c):
    _synchroniser(c, _facture(1))
    c.horloge.avancer(60 * JOUR)
    resume = c.tour()
    for nom in ("retention.courriel", "retention.cles", "retention.traces", "retention.effacements"):
        assert resume["executeurs"][nom]["statut"] == "inactif"
    assert _compter(INGESTION_DOCUMENTS, INGESTION_DOCUMENTS.c.chiffre.is_not(None)) >= 1
    assert len(_archives()) == 1


def test_l_ombre_dresse_l_apercu_sans_rien_effacer(c):
    _synchroniser(c, _facture(1))
    c.horloge.avancer(60 * JOUR)
    c.activer("retention.courriel", "ombre")
    r = c.tour(avance=1)["executeurs"]["retention.courriel"]
    assert r["statut"] == "ombre" and r["aurait"] >= 2  # un lot et une archive au moins
    assert _compter(INGESTION_DOCUMENTS, INGESTION_DOCUMENTS.c.chiffre.is_not(None)) >= 1 and len(_archives()) == 1
    assert _compter(COURRIEL_MESSAGES, COURRIEL_MESSAGES.c.lot_id.is_not(None)) == 1


def test_la_premiere_activation_exige_l_ombre_la_confirmation_et_l_apercu_courant(c):
    _synchroniser(c, _facture(1))
    c.horloge.avancer(60 * JOUR)
    apercu = planificateur.apercu("retention.courriel", ports=c.ports)
    assert apercu["nombre"] >= 2 and len(apercu["empreinte"]) == 64
    texte = json.dumps(apercu["elements"])
    assert "facture.pdf" not in texte and "client.fictif@example.test" not in texte  # des références, pas un contenu

    def essayer(**extra):
        with stockage.transaction() as cnx:
            return etat.appliquer(cnx, cq.session_admin(), "retention.courriel", "actif", motif="essai fictif",
                                  maintenant=c.horloge(), **extra)

    bon = {"apercu_empreinte": apercu["empreinte"], "confirme_irreversible": True,
           "apercu_courant": lambda: (apercu["empreinte"], apercu["nombre"])}
    with pytest.raises(etat.RefusOperateur) as exc:  # jamais directement : l'ombre d'abord
        essayer(**bon)
    assert exc.value.code == "OMBRE_REQUISE"
    c.activer("retention.courriel", "ombre")
    for extra, code in ((dict(bon, confirme_irreversible=False), "CONFIRMATION_IRREVERSIBLE_REQUISE"),
                        ({"confirme_irreversible": True}, "APERCU_REQUIS"),
                        (dict(bon, apercu_courant=lambda: ("0" * 64, 1)), "APERCU_CHANGE")):
        with pytest.raises(etat.RefusOperateur) as exc:
            essayer(**extra)
        assert exc.value.code == code
    assert _compter(PLANIFICATEUR_APPROBATIONS) == 0  # aucune décision n'a été consignée
    essayer(**bon)
    with stockage.transaction() as cnx:
        ap = etat.approbation_valide(cnx, "retention.courriel", c.horloge())
    assert ap["approuve_par"] == "nathan" and ap["nb_elements"] == apercu["nombre"]
    assert ap["apercu_empreinte"] == apercu["empreinte"]


def test_la_decision_est_append_only_et_liee_a_la_revision(c):
    c.activer("retention.courriel", "ombre")
    c.activer("retention.courriel", "actif")
    with stockage.transaction() as cnx, pytest.raises(Exception, match="immuables"):
        cnx.exec_driver_sql("UPDATE planificateur_approbations SET nb_elements = 99")
    with stockage.transaction() as cnx, pytest.raises(Exception, match="immuables"):
        cnx.exec_driver_sql("DELETE FROM planificateur_approbations")
    with stockage.transaction() as cnx:
        assert etat.approbation_valide(cnx, "retention.courriel", c.horloge()) is not None
    # repasser en ombre (une nouvelle révision) : plus aucune décision ne vaut
    c.activer("retention.courriel", "ombre")
    with stockage.transaction() as cnx:
        assert etat.approbation_valide(cnx, "retention.courriel", c.horloge()) is None
    # remettre « actif » sans nouvelle décision humaine est impossible ; avec elle, la précédente ne sert plus
    with stockage.transaction() as cnx, pytest.raises(etat.RefusOperateur):
        etat.appliquer(cnx, cq.session_admin(), "retention.courriel", "actif", motif="sans décision",
        maintenant=c.horloge())


def test_la_decision_expire_avec_l_execution(c):
    c.activer("retention.courriel", "ombre")
    c.activer("retention.courriel", "actif")
    c.horloge.avancer(91 * JOUR)
    with stockage.transaction() as cnx:
        assert etat.approbation_valide(cnx, "retention.courriel", c.horloge()) is None


def test_un_executeur_inscrit_actif_sans_decision_valide_n_efface_rien(c):
    """Même si la ligne d'état était écrite à la main (aucun agent ne le peut), le tour refuse d'effacer."""
    _synchroniser(c, _facture(1))
    c.horloge.avancer(60 * JOUR)
    with stockage.transaction() as cnx:
        cnx.execute(text(
            "INSERT INTO planificateur_executeurs (executeur, mode, intervalle_s, expire_le, prochain_passage, "
            "revision, "
            "modifie_par, modifie_le, motif) VALUES ('retention.courriel', 'actif', 30, :e, 0, 1, 'x', 't', 'motif')"),
            {"e": int(c.horloge()) + JOUR})
    r = c.tour(avance=1)["executeurs"]["retention.courriel"]
    assert r["statut"] == "refus" and r["code"] == "REJ-PLAN-APPROBATION-IRREVERSIBLE-ABSENTE"
    assert _compter(INGESTION_DOCUMENTS, INGESTION_DOCUMENTS.c.chiffre.is_not(None)) >= 1 and len(_archives()) == 1
    # et l'exécuteur lui-même (appelé hors tour) le refuse aussi
    with planificateur.systeme.contexte_planificateur() as acteur:
        ctx = planificateur.Contexte(c.ports, acteur, "p", None, c.horloge())
        with pytest.raises(planificateur.RefusExecuteur) as exc:
            er.RetentionCourriel().traiter("politique", ctx, None)
        assert exc.value.code == er.CODE_SANS_APPROBATION


def test_le_coupe_circuit_arrete_aussi_la_retention(c, monkeypatch):
    _synchroniser(c, _facture(1))
    c.horloge.avancer(60 * JOUR)
    c.activer("retention.courriel", "ombre")
    c.activer("retention.courriel", "actif")
    monkeypatch.setenv(etat.ENV_PLANIFICATEUR, "0")
    assert c.tour(avance=1) == {"raison": "desactive", "executeurs": {}}
    assert len(_archives()) == 1


# ========================================================================================== courriel
def _actif(c, nom: str) -> None:
    c.activer(nom, "ombre")
    c.activer(nom, "actif")


def test_la_retention_du_courriel_rend_le_contenu_illisible_et_garde_les_empreintes(c):
    _synchroniser(c, _facture(1))
    assert len(_archives()) == 1
    with stockage.transaction() as cnx:
        lot = cnx.execute(select(INGESTION_LOTS.c.lot_id)).scalar_one()
        messages_avant = cnx.execute(select(COURRIEL_MESSAGES.c.cle_message, COURRIEL_MESSAGES.c.empreinte)).all()
    c.horloge.avancer(60 * JOUR)
    _actif(c, "retention.courriel")
    r = c.tour(avance=1)["executeurs"]["retention.courriel"]
    assert r["statut"] == "ok" and r["purges"] >= 2
    assert _compter(INGESTION_DOCUMENTS, INGESTION_DOCUMENTS.c.chiffre.is_not(None)) == 0
    assert _compter(INGESTION_TACHES, INGESTION_TACHES.c.chiffre.is_not(None)) == 0
    assert _archives() == []
    assert _compter(INGESTION_BROUILLONS, INGESTION_BROUILLONS.c.chiffre != "",
    INGESTION_BROUILLONS.c.statut != "VALIDE") == 0
    assert _compter(INGESTION_BROUILLONS, INGESTION_BROUILLONS.c.statut.in_(("PRET", "A_VERIFIER"))) == 0
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(INGESTION_LOTS)).scalar_one() == 1  # la ligne du lot reste
        # les empreintes (anti-réingestion) restent ; seul le lien vers le lot disparaît
        assert cnx.execute(select(COURRIEL_MESSAGES.c.cle_message,
        COURRIEL_MESSAGES.c.empreinte)).all() == messages_avant
        assert cnx.execute(select(COURRIEL_MESSAGES.c.lot_id)).scalar_one() is None
        assert lot  # le lot existait
    # le contenu purgé ne se relit plus (refus typé, pas un crash)
    from opsys.ingestion_onboarding import service as onboarding
    from opsys.ingestion_onboarding.codes import IngestionErreur

    with stockage.transaction() as cnx:
        ids = [b["brouillon_id"] for b in onboarding.lire_lot(cnx, lot, vue="brouillons", limite=50)["brouillons"]]
        for bid in ids:
            with pytest.raises(IngestionErreur):
                onboarding.lire_brouillon(cnx, bid)
    # le journal du compte consigne la purge, sans contenu
    with stockage.transaction() as cnx:
        from opsys.courriel_connecteurs import comptes

        evenements = [j for j in comptes.journal(cnx, "gmail-paul", 100) if j["evenement"] == "retention.purge"]
    assert len(evenements) >= 1 and "facture" not in repr(evenements) and "example.test" not in repr(evenements)


def test_un_nouveau_passage_de_synchro_ne_reingere_pas_un_courriel_purge(c):
    _synchroniser(c, _facture(1))
    c.horloge.avancer(60 * JOUR)
    _actif(c, "retention.courriel")
    c.tour(avance=1)
    messages = _compter(COURRIEL_MESSAGES)
    lots = _compter(INGESTION_LOTS)
    # le fournisseur renvoie encore le même courriel (amorçage rejoué) : les empreintes l'écartent
    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("UPDATE courriel_comptes SET curseurs = '{}'")
        cnx.exec_driver_sql("DELETE FROM courriel_refs")
    c.activer("courriel.synchro")
    c.tour(avance=1)
    assert _compter(COURRIEL_MESSAGES) == messages and _compter(INGESTION_LOTS) == lots
    assert len(_archives()) == 0


def test_la_purge_est_idempotente(c):
    _synchroniser(c, _facture(1))
    c.horloge.avancer(60 * JOUR)
    _actif(c, "retention.courriel")
    c.tour(avance=1)
    r = c.tour()["executeurs"]["retention.courriel"]
    assert r["statut"] == "ok" and r["purges"] == 0


def test_ce_qui_n_est_pas_echu_n_est_pas_touche(c):
    _synchroniser(c, _facture(1))
    c.horloge.avancer(29 * JOUR)  # rétention de 30 jours : pas encore échue
    _actif(c, "retention.courriel")
    assert c.tour(avance=1)["executeurs"]["retention.courriel"]["purges"] == 0
    assert _compter(INGESTION_DOCUMENTS, INGESTION_DOCUMENTS.c.chiffre.is_not(None)) >= 1 and len(_archives()) == 1
    c.horloge.avancer(2 * JOUR)  # maintenant échue
    assert c.tour()["executeurs"]["retention.courriel"]["purges"] >= 2


def test_un_lot_n_est_purge_que_lorsque_tous_ses_messages_sont_echus(c):
    _synchroniser(c, _facture(1))
    qa.creer_compte(c.monde, "gmail-long", adresse="long.fictif@example.test")
    with stockage.transaction() as cnx:
        lot = cnx.execute(select(INGESTION_LOTS.c.lot_id)).scalar_one()
        # un second compte, à rétention longue, référence le MÊME lot (même pièce dédoublonnée)
        cnx.exec_driver_sql("UPDATE courriel_comptes SET retention_jours = 3650 WHERE compte_id = 'gmail-long'")
        cnx.execute(text(
            "INSERT INTO courriel_messages (compte_id, cle_message, empreinte, statut, lot_id, nb_pieces, "
            "nb_pieces_transmises, vu_le) VALUES ('gmail-long', 'k', 'e', 'INGERE', :l, 1, 1, :v)"),
            {"l": lot, "v": echeances.instant(int(c.horloge()))})
    c.horloge.avancer(60 * JOUR)
    _actif(c, "retention.courriel")
    assert c.tour(avance=1)["executeurs"]["retention.courriel"]["purges"] == 0
    assert _compter(INGESTION_DOCUMENTS, INGESTION_DOCUMENTS.c.chiffre.is_not(None)) >= 1


def test_un_brouillon_valide_ou_en_cours_d_approbation_n_est_jamais_purge(c):
    _synchroniser(c, _facture(1))
    with stockage.transaction() as cnx:
        lot = cnx.execute(select(INGESTION_LOTS.c.lot_id)).scalar_one()
        doc = cnx.execute(select(INGESTION_DOCUMENTS.c.document_id)).scalars().first()
        cnx.execute(text(
            "INSERT INTO ingestion_brouillons (brouillon_id, lot_id, document_id, genre, cle_metier, statut, raisons, "
            "cles, nonce, chiffre, revision, decision, reference_definitive, cree_le, modifie_le) VALUES "
            "('bvalide', :l, :d, 'crm_client', 'cle-v', 'VALIDE', '[]', '[]', 'n', 'CONTENU-VALIDE', 2, '{}', 'ref-1', "
            "'t', 't')"), {"l": lot, "d": doc})
    c.horloge.avancer(60 * JOUR)
    _actif(c, "retention.courriel")
    c.tour(avance=1)
    with stockage.transaction() as cnx:
        assert cnx.execute(select(INGESTION_BROUILLONS.c.chiffre).where(
            INGESTION_BROUILLONS.c.brouillon_id == "bvalide")).scalar_one() == "CONTENU-VALIDE"


def test_les_brouillons_sortants_termines_sont_vides_les_autres_non(c):
    _synchroniser(c, dbl.courriel_brut(objet="Question", message_id="<q@example.test>"))
    qa.creer_compte(c.monde, "gmail-envoi", usage="lecture_envoi", adresse="envoi.fictif@example.test")
    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("UPDATE courriel_comptes SET retention_jours = 30, etat = 'connecte', "
                            "consentement_le = 't', secret_nom = 's' WHERE compte_id = 'gmail-envoi'")
        for bid, statut, extra in (("b-termine", "ENVOYE", ", approuve_par = 'nathan', demande_id = 'd1'"),
                                    ("b-approuve", "APPROUVE", ", approuve_par = 'nathan', demande_id = 'd2'"),
                                    ("b-brouillon", "BROUILLON", "")):
            cnx.execute(text(
                "INSERT INTO courriel_brouillons (brouillon_id, compte_id, revision, statut, empreinte, cle_reference, "
                "nonce, chiffre, cree_par, cree_le, modifie_le) VALUES (:i, 'gmail-envoi', 1, 'BROUILLON', 'e', 'k', "
                "'n', 'SCELLE', 'm1', :t, :t)"), {"i": bid, "t": echeances.instant(int(c.horloge()))})
            if statut != "BROUILLON":
                cnx.exec_driver_sql(f"UPDATE courriel_brouillons SET statut = '{statut}'{extra} "
                                    f"WHERE brouillon_id = '{bid}'")
    c.horloge.avancer(60 * JOUR)
    _actif(c, "retention.courriel")
    c.tour(avance=1)
    with stockage.transaction() as cnx:
        etats = dict(cnx.execute(select(COURRIEL_BROUILLONS.c.brouillon_id, COURRIEL_BROUILLONS.c.chiffre)).all())
    assert etats == {"b-termine": "", "b-brouillon": "", "b-approuve": "SCELLE"}


def test_le_journal_de_la_retention_ne_porte_ni_contenu_ni_adresse(c):
    _synchroniser(c, _facture(1))
    c.horloge.avancer(60 * JOUR)
    _actif(c, "retention.courriel")
    c.tour(avance=1)
    texte = repr(_journal("retention.courriel"))
    assert "example.test" not in texte and "facture" not in texte.lower().replace("retention", "")


# ========================================================================================== clés détruites (M1, voix)
def _recus_m1() -> list[dict]:
    return [x for x in cq.lignes_m1() if x["type_entree"] == "reception_courriel_connecteur_v1"]


def _chaine_m1_valide() -> bool:
    from m1_front_office import outils as outils_m1

    with stockage.transaction():
        ok, _ = outils_m1._obtenir_registre().valider_chaine()
    return ok


def _recevoir_chez_m1(c) -> str:
    c.monde.gmail.ajouter(dbl.courriel_brut(objet="Gouttière qui fuit", message_id="<m1@client.example.test>",
                                            corps="Bonjour, ma gouttière fuit à Laval."))
    c.activer("courriel.synchro")
    c.tour()  # amorçage : l'historique n'entre pas chez M1
    c.monde.gmail.ajouter(dbl.courriel_brut(objet="Question neuve", message_id="<m2@client.example.test>",
                                            corps="Bonjour, mes gouttières fuient à Laval."))
    c.tour()
    (recu,) = _recus_m1()
    return recu["signal_id"]


def test_l_adresse_recue_par_m1_est_scellee_lisible_puis_effacee_sans_casser_la_chaine(c):
    signal = _recevoir_chez_m1(c)
    (recu,) = _recus_m1()
    assert recu["expediteur"] is None and recu["objet"] is None
    assert "client.fictif@example.test" not in json.dumps(_recus_m1())  # ni l'adresse ni l'objet en clair
    # LIMITE DITE : le lead publié à M2 (donnée d'affaires) et le texte neutralisé du signal restent au registre ; leur
    # rétention est une autre décision (docs/architecture/PLANIFICATION.md §6).
    lead = next(x for x in cq.lignes_m1() if x["type_entree"] == "lead_emis")
    assert lead["lead"]["contact"] == {"courriel": "client.fictif@example.test"}
    lu = c.capacites.appeler("m1_lire_courriels_recus", {"signal_id": signal})["resultat"]["resultat"]
    assert lu["expediteur"] == "client.fictif@example.test" and lu["objet"] == "Question neuve"
    avant = _chaine_m1_valide()
    assert avant is True
    with stockage.transaction() as cnx:
        (echeance,) = cnx.execute(select(RETENTION_ECHEANCES)).mappings().all()
    assert echeance["domaine"] == "m1_courriel" and echeance["statut"] == "en_attente"
    assert echeance["portee"] == echeances.PORTEE_M1_COURRIEL and "client" not in echeance["ref"]
    c.horloge.avancer(60 * JOUR)
    _actif(c, "retention.cles")
    r = c.tour(avance=1)["executeurs"]["retention.cles"]
    assert r["statut"] == "ok" and r["purges"] == 1
    # la clé est détruite : l'adresse est irrécupérable, la chaîne reste valide
    with stockage.transaction() as cnx:
        assert cles_chiffrement.lire(cnx, echeances.PORTEE_M1_COURRIEL, signal) is None
        assert cnx.execute(select(RETENTION_ECHEANCES.c.statut)).scalar_one() == "purgee"
    assert _chaine_m1_valide() is True
    apres = c.capacites.appeler("m1_lire_courriels_recus", {"signal_id": signal})["resultat"]["resultat"]
    assert apres["expediteur"] is None and apres["objet"] is None
    # on ne peut plus répondre à une adresse effacée : refus typé, rien n'est préparé
    refus = c.capacites.appeler("m1_preparer_reponse_courriel", {"signal_id": signal, "corps": "Bonjour, merci."})
    assert not refus["ok"] and "REJ-M1-COURRIEL-EFFACE" in json.dumps(refus)
    # rejouer ne détruit rien de plus
    assert c.tour()["executeurs"]["retention.cles"]["purges"] == 0


def test_l_adresse_non_echue_reste_lisible(c):
    signal = _recevoir_chez_m1(c)
    c.horloge.avancer(10 * JOUR)
    _actif(c, "retention.cles")
    assert c.tour(avance=1)["executeurs"]["retention.cles"]["purges"] == 0
    lu = c.capacites.appeler("m1_lire_courriels_recus", {"signal_id": signal})["resultat"]["resultat"]
    assert lu["expediteur"] == "client.fictif@example.test"


def test_une_ligne_du_registre_ecrite_avant_ce_changement_reste_lisible_et_n_est_pas_reecrite(c):
    """Les lignes anciennes (adresse en clair) ne sont pas purgeables : dit, jamais réécrit."""
    from m1_front_office import courriel_pii

    ancienne = {"type_entree": "reception_courriel_connecteur_v1", "signal_id": "courriel:ancien",
                "expediteur": "ancien@example.test", "objet": "Ancien"}
    with stockage.transaction():
        ouverte = courriel_pii.ouvrir(ancienne)
    assert ouverte["expediteur"] == "ancien@example.test" and ouverte == {**ancienne}


def test_une_enveloppe_deplacee_sur_un_autre_courriel_ne_s_ouvre_pas(c):
    from m1_front_office import courriel_pii

    _recevoir_chez_m1(c)
    (recu,) = _recus_m1()
    autre = {**recu, "signal_id": "courriel:autre"}
    with stockage.transaction() as cnx:
        cles_chiffrement.obtenir_ou_creer(cnx, echeances.PORTEE_M1_COURRIEL, "courriel:autre",
        "2026-11-01T00:00:00+00:00")
    with stockage.transaction(), pytest.raises(ValueError, match="REJ-M1-COURRIEL-ALTERE"):
        courriel_pii.ouvrir(autre)


def test_aucune_cle_hors_de_la_liste_fermee_n_est_jamais_detruite(c):
    """La rétention GPS de M4 (N5, attestation du professionnel) reste hors de portée, même avec une ligne forgée."""
    with stockage.transaction() as cnx:
        cles_chiffrement.obtenir_ou_creer(cnx, "m04-field-ops/gps", "tech-1", "2026-11-01T00:00:00+00:00")
        forgee = {"domaine": "voix", "ref": "x" * 12, "portee": "m04-field-ops/gps", "identifiant": "tech-1"}
        with pytest.raises(echeances.RetentionRefusee) as exc:
            echeances.detruire(cnx, forgee, "2026-11-01T00:00:00+00:00")
        assert exc.value.code == "REJ-RETENTION-PORTEE-INTERDITE"
        with pytest.raises(echeances.RetentionRefusee):
            echeances.enregistrer(cnx, "gps", "r" * 12, "tech-1", 10, "t")
        assert cles_chiffrement.lire(cnx, "m04-field-ops/gps", "tech-1") is not None


# -- voix ------------------------------------------------------------------------------------------------------------
def test_un_enregistrement_vocal_est_chiffre_lisible_puis_efface_a_l_echeance(c):
    t0 = int(c.horloge())
    with stockage.transaction() as cnx:
        info = voix.conserver(cnx, session_id="session-fictive-0001", portee="audio",
        octets=b"AUDIO-FICTIF-SECRET" * 20,
                              retention_jours=7, maintenant_epoch=t0)
    fichier = voix.chemin("session-fictive-0001", "audio")
    assert fichier.is_file() and oct(fichier.stat().st_mode & 0o777) == "0o600"
    assert b"AUDIO-FICTIF-SECRET" not in fichier.read_bytes()  # jamais en clair sur le disque
    assert "session-fictive" not in str(fichier)  # nom pseudonyme
    with stockage.transaction() as cnx:
        assert voix.lire(cnx, session_id="session-fictive-0001", portee="audio") == b"AUDIO-FICTIF-SECRET" * 20
        with pytest.raises(echeances.RetentionRefusee) as exc:  # jamais d'écrasement
            voix.conserver(cnx, session_id="session-fictive-0001", portee="audio", octets=b"x", retention_jours=7,
                           maintenant_epoch=t0)
        assert exc.value.code == "REJ-VOIX-DEJA-CONSERVE"
    assert info["echeance_epoch"] == t0 + 7 * JOUR
    c.horloge.avancer(6 * JOUR)
    _actif(c, "retention.cles")
    assert c.tour(avance=1)["executeurs"]["retention.cles"]["purges"] == 0 and fichier.is_file()
    c.horloge.avancer(2 * JOUR)
    assert c.tour()["executeurs"]["retention.cles"]["purges"] == 1
    assert not fichier.exists()
    with stockage.transaction() as cnx, pytest.raises(echeances.RetentionRefusee) as exc:
        voix.lire(cnx, session_id="session-fictive-0001", portee="audio")
    assert exc.value.code == "REJ-VOIX-ENREGISTREMENT-PURGE"


@pytest.mark.parametrize("jours", [0, 91, -1, True, "30"])
def test_la_retention_vocale_hors_de_1_a_90_jours_est_refusee_et_rien_n_est_ecrit(c, jours):
    with stockage.transaction() as cnx, pytest.raises(echeances.RetentionRefusee) as exc:
        voix.conserver(cnx, session_id="session-fictive-0002", portee="audio", octets=b"x", retention_jours=jours,
                       maintenant_epoch=int(c.horloge()))
    assert exc.value.code == "REJ-VOIX-RETENTION-INVALIDE"
    assert not voix.chemin("session-fictive-0002", "audio").exists() and _compter(RETENTION_ECHEANCES) == 0


def test_le_retrait_du_consentement_efface_tout_de_suite_sans_attendre_le_planificateur(c):
    t0 = int(c.horloge())
    with stockage.transaction() as cnx:
        voix.conserver(cnx, session_id="session-fictive-0003", portee="transcription", octets=b"TRANSCRIPTION-FICTIVE",
                       retention_jours=30, maintenant_epoch=t0)
    with stockage.transaction() as cnx:
        r = voix.retirer(cnx, session_id="session-fictive-0003", portee="transcription", maintenant_epoch=t0 + 5)
    assert r["fichier_efface"] is True and not voix.chemin("session-fictive-0003", "transcription").exists()
    with stockage.transaction() as cnx:
        assert cles_chiffrement.lire(cnx, echeances.PORTEE_VOIX, "session-fictive-0003/transcription") is None
        again = voix.retirer(cnx, session_id="session-fictive-0003", portee="transcription", maintenant_epoch=t0 + 6)
    assert again["fichier_efface"] is False  # rejouable
    with stockage.transaction() as cnx, pytest.raises(echeances.RetentionRefusee):
        voix.retirer(cnx, session_id="session-inconnue-9", portee="audio", maintenant_epoch=t0)


# -- traces ----------------------------------------------------------------------------------------------------------
@pytest.fixture
def traces(tmp_path):
    from opsys.observabilite.traces import JournalTraces

    dossier = tmp_path / "traces"
    dossier.mkdir()
    for nom in ("traces-20260101.jsonl", "traces-20260601.jsonl"):
        (dossier / nom).write_text("", encoding="utf-8")
    return dossier, JournalTraces


def test_la_retention_des_traces_retire_les_vieux_segments_jamais_celui_du_jour(c, traces):
    import datetime as dt

    dossier, JournalTraces = traces
    aujourd_hui = dt.datetime.fromtimestamp(c.horloge(), dt.UTC)
    (dossier / f"traces-{aujourd_hui:%Y%m%d}.jsonl").write_text("", encoding="utf-8")
    journal_traces = JournalTraces(dossier, b"\x01" * 32, retention_jours=30, maintenant=lambda: aujourd_hui)
    c.ports.dossier_traces = lambda: journal_traces
    apercu = planificateur.apercu("retention.traces", ports=c.ports)
    assert {e["ref"] for e in apercu["elements"]} == {"traces-20260101.jsonl", "traces-20260601.jsonl"}
    c.activer("retention.traces", "ombre")
    assert c.tour(avance=1)["executeurs"]["retention.traces"]["aurait"] == 2
    assert len(list(dossier.glob("traces-*.jsonl"))) == 3  # l'ombre n'efface rien
    c.activer("retention.traces", "actif")
    assert c.tour(avance=1)["executeurs"]["retention.traces"]["purges"] == 2
    assert [p.name for p in dossier.glob("traces-*.jsonl")] == [f"traces-{aujourd_hui:%Y%m%d}.jsonl"]
    assert len(journal_traces.purges()) == 1 and journal_traces.purges()[0]["segments"] == [
        "traces-20260101.jsonl", "traces-20260601.jsonl"]


def test_la_retention_des_traces_sans_journal_ou_sans_cle_le_dit(c, tmp_path, monkeypatch):
    c.activer("retention.traces", "ombre")
    c.ports.dossier_traces = None
    assert c.tour(avance=1)["executeurs"]["retention.traces"]["statut"] == "attente_transport"
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "vide"))
    from opsys.connecteurs_planification import hote

    assert hote.journal_traces() is None  # aucun dossier de traces : rien à purger, rien d'inventé


def test_la_retention_declaree_des_traces_vient_de_l_environnement_et_une_valeur_invalide_est_refusee():
    from opsys.observabilite.erreurs import ErreurObservabilite
    from opsys.observabilite.traces import retention_jours_env

    assert retention_jours_env({}) == 30 and retention_jours_env({"OPSYS_TRACES_RETENTION_JOURS": "45"}) == 45
    for invalide in ("0", "-3", "trois", "3651", "30.5"):
        with pytest.raises(ErreurObservabilite):
            retention_jours_env({"OPSYS_TRACES_RETENTION_JOURS": invalide})


# -- reprise des effacements autorisés -------------------------------------------------------------------------------
def test_la_reprise_termine_un_effacement_deja_autorise_et_ne_detruit_aucune_cle(c):
    with stockage.transaction() as cnx:
        cles_chiffrement.obtenir_ou_creer(cnx, "autre/portee", "garde-moi", "2026-11-01T00:00:00+00:00")
        cnx.exec_driver_sql(
            "INSERT INTO effacements_cles (purge_id, portee, identifiant, demande_id, cree_le, cle_detruite, "
            "etat_fichiers, motif) VALUES ('" + "a" * 32 + "', 'x/y', 'z', NULL, '2026-11-01T00:00:00+00:00', 1, "
            "'en_attente', NULL)")
    c.activer("retention.effacements")
    r = c.tour()["executeurs"]["retention.effacements"]
    assert r["statut"] == "ok" and r["traites"] == 1
    with stockage.transaction() as cnx:
        assert cnx.exec_driver_sql("SELECT etat_fichiers FROM effacements_cles").scalar_one() == "termine"
        assert cles_chiffrement.lire(cnx, "autre/portee", "garde-moi") is not None  # aucune clé n'a été détruite
    assert c.tour()["executeurs"]["retention.effacements"]["statut"] == "ok"  # plus rien à reprendre
