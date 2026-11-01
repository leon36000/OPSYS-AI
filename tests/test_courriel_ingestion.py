"""Ingestion : un compte Gmail / Graph / IMAP / export mbox alimente la file d'onboarding EXISTANTE en brouillon à
confirmer. Idempotence, déduplication, reprise après interruption, quota de débit, pièces refusées, aucune donnée
définitive. Vraie file d'onboarding, vraie base, vrai coffre ; réseau et serveurs de courrier = doubles."""

from __future__ import annotations

import hashlib
import io
import os
import zipfile

import courriel_doubles as dbl
import courriel_qa as qa
import ingestion_onboarding_qa as onboarding_qa
import pytest
from sqlalchemy import func, select

from opsys import stockage
from opsys.courriel_connecteurs import comptes, ingestion
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.courriel_connecteurs.ingestion import IngestionCourriel, LimiteurDebit
from opsys.ingestion_onboarding import service as onboarding
from opsys.ingestion_onboarding import taches
from opsys.stockage.schema import COURRIEL_MESSAGES, INGESTION_LOTS

FICTIF = True
F1 = onboarding_qa.texte_corpus("factures/F1-quincaillerie.txt")
F2 = onboarding_qa.texte_corpus("factures/F2-materiaux.txt")


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = qa.preparer(tmp_path, monkeypatch)
    qa.creer_compte(m)
    qa.connecter_oauth(m)
    return m


def _ing(monde, **options):
    return IngestionCourriel(
        stockage.transaction,
        acteur="nathan",
        signaler=monde.service.signaler_erreur,
        taille_page=options.pop("taille_page", 50),
        **options,
    )


def _facture(i=1, texte=F1, nom="facture.pdf", **options):
    contenu = onboarding_qa.pdf_texte(texte) if nom.endswith(".pdf") else texte.encode()
    mime = "application/pdf" if nom.endswith(".pdf") else "text/plain"
    return dbl.courriel_brut(
        objet=f"Facture {i}",
        corps=f"voir pièce {i}",
        message_id=f"<f{i}@example.test>",
        pieces=[(nom, mime, contenu)],
        **options,
    )


def _compter(table):
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(table)).scalar_one()


def _avancer(lot_id):
    return onboarding.avancer(
        stockage.transaction, "nathan", lot_id, budget=500, extracteur_pdf=onboarding_qa.extracteur_pdf_en_processus
    )


# -- bout en bout ---------------------------------------------------------------------------------
def test_bout_en_bout_courriels_vers_brouillons_ap_a_confirmer(monde):
    monde.gmail.ajouter(_facture(1, F1, "F1.pdf"))
    monde.gmail.ajouter(_facture(2, F2, "F2.txt"))
    monde.gmail.ajouter(dbl.courriel_brut(objet="Sans pièce", message_id="<s@example.test>"))
    monde.gmail.ajouter(
        dbl.courriel_brut(
            objet="Virus",
            message_id="<v@example.test>",
            pieces=[("facture.pdf", "application/pdf", b"MZ" + b"\x00" * 100)],
        )
    )
    monde.gmail.ajouter(_facture(5, F1, "copie-F1.pdf"))  # même PDF que le message 1 : dédoublonné par SHA-256
    provider = monde.service.fournisseur("gmail-paul")
    rapport = _ing(monde).synchroniser("gmail-paul", provider, "INBOX")
    assert rapport.statut == "termine" and rapport.mode == "brouillon_a_confirmer"
    assert (rapport.messages_lus, rapport.nouveaux, rapport.doublons) == (5, 5, 0)
    assert rapport.pieces_transmises == 3 and rapport.pieces_non_transmises == {"dangereux": 1}
    assert len(rapport.lots) == 1
    avance = _avancer(rapport.lots[0])
    assert avance["statut"] == "TERMINE"
    with stockage.transaction() as cnx:
        lot = onboarding.lire_lot(cnx, rapport.lots[0], vue="documents", limite=50)
        brouillons = onboarding.lire_lot(cnx, rapport.lots[0], vue="brouillons", limite=50)["brouillons"]
    statuts = sorted(d["statut"] for d in lot["documents"])
    assert (
        statuts.count("TERMINE") == 2 and len(lot["documents"]) == 2
    )  # F1.pdf et F2.txt ; la copie n'est qu'un membre
    assert sorted(b["genre"] for b in brouillons) == ["ap_facture_fournisseur"] * 2
    assert all(
        b["statut"] in {"PRET", "A_VERIFIER"} and b["reference_definitive"] is None and b["decision"] is None
        for b in brouillons
    ), "rien n'est définitif : tout attend une décision humaine"
    with stockage.transaction() as cnx:
        vue = comptes.lire(cnx, "gmail-paul")
    assert (
        vue["messages_total"] == 5
        and vue["derniere_synchro_statut"] == "termine"
        and vue["derniere_erreur_code"] is None
    )


def test_aucun_contenu_de_courriel_dans_la_base_des_comptes_ni_dans_le_journal(monde):
    monde.gmail.ajouter(
        dbl.courriel_brut(
            objet="Sujet confidentiel XYZ",
            corps="Corps confidentiel ABC",
            de="jean.tremblay@example.test",
            message_id="<c@example.test>",
        )
    )
    _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    stockage.liberer()
    octets = b"".join(p.read_bytes() for p in (monde.tmp_path / "opsys-home").rglob("*") if p.is_file())
    for secret in (
        b"Sujet confidentiel XYZ",
        b"Corps confidentiel ABC",
        b"jean.tremblay@example.test",
        b"c@example.test",
    ):
        assert secret not in octets, secret


# -- idempotence et déduplication
# -------------------------------------------------------------------------------------------
def test_deuxieme_passage_complet_ne_cree_ni_lot_ni_message(monde):
    for i in range(4):
        monde.gmail.ajouter(_facture(i, F1.replace("QF-2026-0418", f"QF-{i}"), f"F{i}.pdf"))
    provider = monde.service.fournisseur("gmail-paul")
    r1 = _ing(monde).synchroniser("gmail-paul", provider, "INBOX")
    lots, vus = _compter(INGESTION_LOTS), _compter(COURRIEL_MESSAGES)
    # reconnexion : on efface le curseur, tout est relu depuis le début
    with stockage.transaction() as cnx:
        comptes.enregistrer_synchro(
            cnx, "gmail-paul", "nathan", curseurs_a_jour={"INBOX": None}, statut="reprise", ajoutes=0
        )
    r2 = _ing(monde).synchroniser("gmail-paul", provider, "INBOX")
    assert (r1.nouveaux, r2.nouveaux, r2.deja_vus, r2.messages_lus) == (4, 0, 4, 0)  # références connues : aucun appel
    assert _compter(INGESTION_LOTS) == lots and _compter(COURRIEL_MESSAGES) == vus and r2.lots == []


def test_meme_message_dans_deux_dossiers_traite_une_fois(monde):
    brut = _facture(1, F1, "F1.pdf")
    monde.gmail.ajouter(brut, labels=("INBOX",))
    monde.gmail.ajouter(brut, labels=("Label_1",))
    with stockage.transaction() as cnx:
        cnx.execute(comptes.COURRIEL_COMPTES.update().values(dossiers_suivis='["INBOX", "Label_1"]'))
    rapports = _ing(monde).synchroniser_compte("gmail-paul", monde.service.fournisseur("gmail-paul"))
    assert rapports["INBOX"].nouveaux == 1 and rapports["Label_1"].nouveaux == 0 and rapports["Label_1"].doublons == 1


def test_meme_message_id_contenu_modifie_est_une_version_distincte(monde):
    monde.gmail.ajouter(_facture(1, F1, "F1.pdf"))
    r1 = _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    monde.gmail.ajouter(_facture(1, F2, "F1.pdf"))  # même Message-ID <f1@...>, autre pièce
    r2 = _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert r1.nouveaux == 1 and r2.nouveaux == 1 and _compter(COURRIEL_MESSAGES) == 2


def test_cle_d_idempotence_cloisonnee_par_compte(monde):
    qa.creer_compte(monde, "gmail-autre", adresse="autre.fictif@example.test")
    brut = _facture(1, F1, "F1.pdf")
    monde.gmail.ajouter(brut)
    ing = _ing(monde)
    ing.synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    with stockage.transaction() as cnx:
        cle = cnx.execute(select(COURRIEL_MESSAGES.c.cle_message, COURRIEL_MESSAGES.c.compte_id)).first()
    assert cle.compte_id == "gmail-paul"


# -- reprise après interruption
# -----------------------------------------------------------------------------------------------
class Interrupteur:
    """Enveloppe un fournisseur et échoue (erreur de transport typée) à la n-ième lecture de message."""

    def __init__(self, reel, echec_a: int):
        self.reel, self.n, self.echec_a = reel, 0, echec_a
        self.identifiant = reel.identifiant

    def __getattr__(self, nom):
        return getattr(self.reel, nom)

    def lire_message(self, ref):
        self.n += 1
        if self.n == self.echec_a:
            raise ErreurCourriel("REJ-COURRIEL-RESEAU", "coupure simulée", 503, reprenable=True)
        return self.reel.lire_message(ref)


def test_interruption_au_milieu_reprise_sans_perte_ni_doublon(monde):
    for i in range(9):
        monde.gmail.ajouter(_facture(i, F1.replace("QF-2026-0418", f"QF-{i}"), f"F{i}.pdf"))
    reel = monde.service.fournisseur("gmail-paul")
    r1 = _ing(monde, taille_page=4).synchroniser("gmail-paul", Interrupteur(reel, echec_a=6), "INBOX")
    assert (
        r1.statut == "erreur" and r1.code == "REJ-COURRIEL-RESEAU" and r1.nouveaux == 4
    )  # une page complète est déjà validée
    with stockage.transaction() as cnx:
        assert comptes.lire(cnx, "gmail-paul")["derniere_erreur_code"] == "REJ-COURRIEL-RESEAU"
        assert comptes.lire(cnx, "gmail-paul")["etat"] == "connecte"  # un incident réseau n'oblige pas à reconnecter
    r2 = _ing(monde, taille_page=4).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert r2.statut == "termine" and r2.nouveaux == 5 and r2.doublons == 0
    assert _compter(COURRIEL_MESSAGES) == 9
    with stockage.transaction() as cnx:
        assert comptes.lire(cnx, "gmail-paul")["derniere_erreur_code"] is None
        deposes = cnx.execute(select(func.sum(INGESTION_LOTS.c.nb_documents))).scalar_one()
    assert deposes == 9  # neuf factures distinctes, chacune déposée UNE fois


def test_arret_apres_le_depot_avant_la_validation_rejoue_le_meme_lot(monde, monkeypatch):
    monde.gmail.ajouter(_facture(1, F1, "F1.pdf"))
    ing = _ing(monde)
    reel = ing._deposer
    appels = {"n": 0}

    def depose_puis_meurt(*args, **kwargs):
        resultat = reel(*args, **kwargs)
        appels["n"] += 1
        if appels["n"] == 1:
            raise KeyboardInterrupt  # le processus est tué APRÈS le dépôt, AVANT la validation du curseur
        return resultat

    monkeypatch.setattr(ing, "_deposer", depose_puis_meurt)
    with pytest.raises(KeyboardInterrupt):
        ing.synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert _compter(INGESTION_LOTS) == 1 and _compter(COURRIEL_MESSAGES) == 0
    r = _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert (
        r.nouveaux == 1 and _compter(INGESTION_LOTS) == 1
    )  # l'archive est identique : même clé de mutation, lot rejoué
    assert len(r.lots) == 1


def test_curseur_expire_nouvel_amorcage_sans_doublon(monde):
    for i in range(3):
        monde.gmail.ajouter(_facture(i, F1.replace("QF-2026-0418", f"QF-{i}"), f"F{i}.pdf"))
    _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    monde.gmail.ajouter(_facture(9, F2, "F9.pdf"))
    monde.gmail.purger_historique()
    r = _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert r.statut == "termine" and r.reprises_curseur == 1 and r.nouveaux == 1 and r.deja_vus == 3
    assert _compter(COURRIEL_MESSAGES) == 4


# -- quota de débit -------------------------------------------------------------------------------
def test_quota_de_debit_arret_sans_avancer_le_curseur_puis_reprise(monde):
    for i in range(10):
        monde.gmail.ajouter(dbl.courriel_brut(objet=f"m{i}", message_id=f"<q{i}@example.test>"))
    temps = dbl.Horloge(1000.0)
    limiteur = LimiteurDebit(3, temps)
    provider = monde.service.fournisseur("gmail-paul")
    ing = _ing(monde, taille_page=5, limiteur=limiteur)
    r1 = ing.synchroniser("gmail-paul", provider, "INBOX")
    assert r1.statut == "quota" and r1.code == "REJ-COURRIEL-QUOTA-DEBIT" and r1.nouveaux == 3 and r1.messages_lus == 3
    with stockage.transaction() as cnx:
        assert comptes.curseurs(cnx, "gmail-paul") == {}  # page non terminée : curseur NON avancé
    total, lus = r1.nouveaux, r1.messages_lus
    for _ in range(10):
        temps.t += 60  # le seau se remplit : trois messages de plus par minute, même si la page en compte cinq
        r = ing.synchroniser("gmail-paul", provider, "INBOX")
        total, lus = total + r.nouveaux, lus + r.messages_lus
        if r.statut == "termine":
            break
    assert (
        total == 10 and lus == 10 and _compter(COURRIEL_MESSAGES) == 10
    )  # chaque message lu UNE seule fois chez le fournisseur
    assert r.deja_vus >= 1 and r.doublons == 0


def test_limiteur_a_jetons():
    t = dbl.Horloge(0.0)
    lim = LimiteurDebit(60, t)
    assert all(lim.prendre() for _ in range(60)) and not lim.prendre()
    t.t += 1.0
    assert lim.prendre() and not lim.prendre()  # 60 par minute = 1 par seconde
    t.t += 3600
    assert sum(lim.prendre() for _ in range(100)) == 60  # jamais plus que la capacité
    with pytest.raises(ValueError):
        LimiteurDebit(0)


# -- pièces jointes : tri sans exécution ----------------------------------------------------------
@pytest.mark.parametrize(
    "nom, mime, octets, raison",
    [
        ("a.exe", "application/octet-stream", b"MZ" + b"\x00" * 64, "dangereux"),
        ("a.pdf", "application/pdf", b"MZ" + b"\x00" * 64, "dangereux"),
        ("a.png", "image/png", dbl.pdf_fictif(), "type_incoherent"),
        ("a.zip", "application/zip", b"PK\x03\x04" + b"\x00" * 40, "type_non_accepte"),
        ("a.docm", "application/octet-stream", b"PK\x03\x04" + b"\x00" * 40, "dangereux"),
        ("a.svg", "image/svg+xml", b"<svg onload='x()'></svg>", "dangereux"),
        ("a.bin", "application/octet-stream", bytes(range(256)) * 4, "type_non_accepte"),
    ],
)
def test_pieces_refusees_avec_leur_raison_et_jamais_transmises(monde, nom, mime, octets, raison):
    monde.gmail.ajouter(dbl.courriel_brut(pieces=[(nom, mime, octets)]))
    r = _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert r.pieces_transmises == 0 and r.pieces_non_transmises == {raison: 1} and r.lots == []
    assert _compter(INGESTION_LOTS) == 0


def test_pdf_declare_octet_stream_est_accepte_d_apres_sa_signature(monde):
    monde.gmail.ajouter(
        dbl.courriel_brut(
            message_id="<o@example.test>", pieces=[("facture", "application/octet-stream", onboarding_qa.pdf_texte(F1))]
        )
    )
    r = _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert r.pieces_transmises == 1


def test_csv_transmis_comme_csv(monde):
    monde.gmail.ajouter(
        dbl.courriel_brut(
            message_id="<csv@example.test>",
            pieces=[("clients.csv", "text/csv", b"nom,courriel\nJean Fictif,jean@example.test\n")],
        )
    )
    r = _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert r.pieces_transmises == 1
    archive = next(tmp for tmp in (stockage.dossier_opsys() / "imports" / "onboarding").glob("courriel-*.zip"))
    with zipfile.ZipFile(archive) as z:
        assert [n.rsplit(".", 1)[1] for n in z.namelist()] == ["csv"]


def test_noms_de_pieces_jamais_utilises_dans_l_archive(monde):
    monde.gmail.ajouter(
        dbl.courriel_brut(
            message_id="<n@example.test>",
            pieces=[("../../../../etc/cron.d/evil.pdf", "application/pdf", onboarding_qa.pdf_texte(F1))],
        )
    )
    _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    archive = next((stockage.dossier_opsys() / "imports" / "onboarding").glob("courriel-*.zip"))
    with zipfile.ZipFile(archive) as z:
        (nom,) = z.namelist()
    assert nom == hashlib.sha256(onboarding_qa.pdf_texte(F1)).hexdigest()[:16] + ".pdf" and "/" not in nom


# -- archive : déterminisme, aucune écrasement ----------------------------------------------------
def test_archive_deterministe_quel_que_soit_l_ordre():
    a = ingestion.construire_archive([("b.txt", b"deux"), ("a.txt", b"un")])
    b = ingestion.construire_archive([("a.txt", b"un"), ("b.txt", b"deux")])
    assert a == b
    with zipfile.ZipFile(io.BytesIO(a)) as z:
        assert all(i.compress_type == zipfile.ZIP_STORED and i.date_time == (1980, 1, 1, 0, 0, 0) for i in z.infolist())


def test_depot_d_archive_idempotent_sans_ecrasement_ni_lien(tmp_path):
    dossier = tmp_path / "depot"
    octets = ingestion.construire_archive([("a.txt", b"un")])
    nom = ingestion.deposer_archive(octets, dossier)
    assert ingestion.deposer_archive(octets, dossier) == nom
    assert oct((dossier / nom).stat().st_mode & 0o777) == "0o600"
    (dossier / nom).write_bytes(b"autre contenu")  # collision de nom avec un contenu différent
    with pytest.raises(ErreurCourriel) as exc:
        ingestion.deposer_archive(octets, dossier)
    assert exc.value.code == "REJ-COURRIEL-INGESTION-REFUSEE"
    (dossier / nom).unlink()
    cible = tmp_path / "cible.txt"
    cible.write_text("intact")
    os.symlink(cible, dossier / nom)
    with pytest.raises(ErreurCourriel):
        ingestion.deposer_archive(octets, dossier)
    assert cible.read_text() == "intact"


# -- quota de la file d'onboarding ----------------------------------------------------------------
def test_quota_de_lots_de_la_file_d_onboarding_arrete_sans_perdre_la_page_suivante(monde, monkeypatch):
    monkeypatch.setitem(taches.QUOTAS, "lots_en_cours", 1)
    for i in range(4):
        monde.gmail.ajouter(_facture(i, F1.replace("QF-2026-0418", f"QF-{i}"), f"F{i}.pdf"))
    provider = monde.service.fournisseur("gmail-paul")
    ing = _ing(monde, taille_page=2)
    r1 = ing.synchroniser("gmail-paul", provider, "INBOX")
    assert (
        r1.statut == "erreur" and r1.code == "REJ-COURRIEL-INGESTION-REFUSEE" and r1.nouveaux == 2 and len(r1.lots) == 1
    )
    _avancer(r1.lots[0])
    r2 = ing.synchroniser("gmail-paul", provider, "INBOX")
    assert r2.statut == "termine" and r2.nouveaux == 2 and _compter(COURRIEL_MESSAGES) == 4


# -- erreurs du compte ----------------------------------------------------------------------------
def test_jeton_refuse_reconnexion_requise_curseur_inchange(monde):
    monde.gmail.ajouter(dbl.courriel_brut())
    provider = monde.service.fournisseur("gmail-paul")
    monde.oauth_google.invalid_grant = True
    monde.horloge.t += 4000
    r = _ing(monde).synchroniser("gmail-paul", provider, "INBOX")
    assert r.statut == "erreur" and r.code == "REJ-COURRIEL-JETON-REVOQUE"
    with stockage.transaction() as cnx:
        vue = comptes.lire(cnx, "gmail-paul")
        assert vue["etat"] == "reconnexion_requise" and vue["derniere_synchro_statut"] == "erreur"
    with pytest.raises(ErreurCourriel) as exc:  # un compte en reconnexion ne synchronise plus
        _ing(monde).synchroniser("gmail-paul", provider, "INBOX")
    assert exc.value.code == "REJ-COURRIEL-COMPTE-INACTIF"


def test_message_hostile_ne_bloque_pas_les_suivants(monde):
    monde.gmail.ajouter(dbl.courriel_brut(objet="a", message_id="<a@example.test>"))
    monde.gmail.ajouter(b"   \n  ")  # illisible
    monde.gmail.ajouter(dbl.courriel_brut(objet="b", message_id="<b@example.test>"))
    r = _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert r.statut == "termine" and r.nouveaux == 2 and r.refuses == 1


def test_message_supprime_entre_le_listage_et_la_lecture_est_ignore(monde):
    monde.gmail.ajouter(dbl.courriel_brut(objet="a", message_id="<a@example.test>"))
    disparu = monde.gmail.ajouter(dbl.courriel_brut(objet="b", message_id="<b@example.test>"))
    del monde.gmail.messages[disparu]  # supprimé SANS entrée d'historique : le listage le voit déjà
    r = _ing(monde).synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert r.nouveaux == 1


def test_compte_non_connecte_refuse(monde):
    qa.creer_compte(monde, "gmail-neuf", adresse="neuf.fictif@example.test", consentement=False)
    with pytest.raises(ErreurCourriel) as exc:
        _ing(monde).synchroniser("gmail-neuf", monde.service.fournisseur("gmail-paul"), "INBOX")
    assert exc.value.code == "REJ-COURRIEL-COMPTE-INACTIF"


# -- Graph, IMAP et mbox passent par la même ingestion --------------------------------------------
def test_graph_meme_ingestion(monde):
    qa.creer_compte(monde, "graph-paul", "graph", dossiers=("inbox",))
    qa.connecter_oauth(monde, "graph-paul")
    monde.graph.ajouter(_facture(1, F1, "F1.pdf"))
    monde.graph.ajouter(_facture(2, F2, "F2.pdf"))
    rapports = _ing(monde).synchroniser_compte("graph-paul", monde.service.fournisseur("graph-paul"))
    assert rapports["inbox"].nouveaux == 2 and rapports["inbox"].pieces_transmises == 2
    monde.graph.ajouter(_facture(3, F1.replace("QF-2026-0418", "QF-3"), "F3.pdf"))
    assert _ing(monde).synchroniser("graph-paul", monde.service.fournisseur("graph-paul"), "inbox").nouveaux == 1


def test_uidvalidity_change_references_nouvelles_mais_messages_deja_vus_sont_des_doublons(monde):
    qa.connecter_imap(monde, "imap-paul")
    for i in range(3):
        monde.serveur_imap.ajouter(_facture(i, F1.replace("QF-2026-0418", f"QF-{i}"), f"F{i}.pdf"))
    r1 = _ing(monde).synchroniser("imap-paul", monde.service.fournisseur("imap-paul"), "INBOX")
    monde.serveur_imap.changer_uidvalidity()  # le serveur a renuméroté : toutes les références changent
    r2 = _ing(monde).synchroniser("imap-paul", monde.service.fournisseur("imap-paul"), "INBOX")
    assert (r1.nouveaux, r2.reprises_curseur, r2.nouveaux, r2.doublons, r2.deja_vus) == (3, 1, 0, 3, 0)
    assert r2.lots == [] and _compter(COURRIEL_MESSAGES) == 3


def test_imap_meme_ingestion(monde):
    qa.connecter_imap(monde, "imap-paul")
    monde.serveur_imap.ajouter(_facture(1, F1, "F1.pdf"))
    r = _ing(monde).synchroniser("imap-paul", monde.service.fournisseur("imap-paul"), "INBOX")
    assert r.nouveaux == 1 and r.pieces_transmises == 1


def _mbox(messages):
    sortie = b""
    for i, m in enumerate(messages):
        sortie += f"From {i}@xxx Mon Mar 01 00:00:0{i % 10} +0000 2021\n".encode() + m.replace(b"\r\n", b"\n") + b"\n"
    return sortie


def test_mbox_historique_reprenable_meme_ingestion(monde):
    dossier = stockage.dossier_opsys() / "imports" / "courriel"
    dossier.mkdir(parents=True)
    contenu = _mbox([_facture(i, F1.replace("QF-2026-0418", f"QF-{i}"), f"F{i}.pdf") for i in range(6)])
    (dossier / "historique.mbox").write_bytes(contenu)
    qa.creer_compte(
        monde,
        "export-2024",
        "mbox",
        adresse="historique@example.test",
        configuration={"fichier": "historique.mbox"},
        dossiers=("historique.mbox",),
    )
    assert monde.service.connecter_export_mbox(qa.ADMIN, "export-2024")["etat"] == "connecte"
    provider = monde.service.fournisseur("export-2024")
    r1 = _ing(monde, taille_page=2).synchroniser("export-2024", Interrupteur(provider, echec_a=4), "historique.mbox")
    assert r1.statut == "erreur" and r1.nouveaux == 2
    r2 = _ing(monde, taille_page=2).synchroniser(
        "export-2024", monde.service.fournisseur("export-2024"), "historique.mbox"
    )
    assert r2.statut == "termine" and r2.nouveaux == 4 and _compter(COURRIEL_MESSAGES) == 6
    assert (dossier / "historique.mbox").read_bytes() == contenu  # lecture seule


def test_export_mbox_nom_inexistant_refuse_a_la_connexion(monde):
    qa.creer_compte(monde, "export-x", "mbox", adresse="x@example.test", configuration={"fichier": "absent.mbox"})
    with pytest.raises(ErreurCourriel) as exc:
        monde.service.connecter_export_mbox(qa.ADMIN, "export-x")
    assert exc.value.code == "REJ-COURRIEL-MBOX-ABSENT"
