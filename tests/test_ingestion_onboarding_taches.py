"""Table de tâches durable de l'ingestion d'onboarding : reprise après interruption sans doublon, bail, CAS, échecs
reprenables puis file morte, refus typés du port d'extraction (aucun repli), OCR et PDF refusés. Corpus fictif."""

from __future__ import annotations

import time

import ingestion_onboarding_qa as qa
import pytest
from sqlalchemy import func, select, update

from opsys import stockage
from opsys.fournisseurs import registre
from opsys.ingestion_onboarding import port_extraction, service, taches
from opsys.ingestion_onboarding.codes import EchecEtape
from opsys.stockage.schema import INGESTION_BROUILLONS, INGESTION_JOURNAL, INGESTION_TACHES

FICTIF = True
T0 = 2_000_000_000


class Arret(BaseException):
    """Un arrêt brutal simulé (processus tué) : rien ne l'attrape dans le service."""


@pytest.fixture
def instance(tmp_path, monkeypatch):
    return qa.preparer_instance(tmp_path, monkeypatch)


class Horloge:
    def __init__(self, depart=T0):
        self.t = depart

    def __call__(self):
        return self.t


def _deposer(membres, mutation="m-1", nom="depot.zip"):
    qa.deposer_fichier(nom, qa.zip_onboarding(membres))
    with stockage.transaction() as cnx:
        return service.deposer(cnx, "nathan", nom=nom, mutation_id=mutation)


def _avancer(lot, horloge=None, **kwargs):
    return service.avancer(stockage.transaction, "nathan", lot["lot_id"], budget=500, horloge=horloge,
                           extracteur_pdf=kwargs.pop("extracteur_pdf", qa.extracteur_pdf_en_processus), **kwargs)


def _brouillons():
    with stockage.transaction() as cnx:
        return [dict(r) for r in cnx.execute(select(INGESTION_BROUILLONS).order_by(
            INGESTION_BROUILLONS.c.genre, INGESTION_BROUILLONS.c.cle_metier)).mappings()]


def _signature(brouillons):
    return [(b["genre"], b["cle_metier"], b["statut"], b["raisons"]) for b in brouillons]


def _taches(lot):
    with stockage.transaction() as cnx:
        return [dict(r) for r in cnx.execute(select(INGESTION_TACHES).where(
            INGESTION_TACHES.c.lot_id == lot["lot_id"])).mappings()]


def _corpus():
    membres = qa.corpus_complet()
    return {nom: octets for nom, octets in membres.items() if not nom.startswith("__MACOSX")}


# -------------------------------------------------------------------------------- reprise après interruption
def test_un_arret_brutal_apres_reservation_reprend_a_l_echeance_du_bail_sans_doublon(instance, monkeypatch, tmp_path):
    reference = _avancer(_deposer(_corpus()))
    attendu = _signature(_brouillons())
    assert reference["statut"] == "TERMINE" and len(attendu) == 11

    # Seconde instance, même corpus : l'arrêt survient pendant l'étape « validation » de la 3e facture.
    (tmp_path / "bis").mkdir()
    qa.preparer_instance(tmp_path / "bis", monkeypatch)
    lot = _deposer(_corpus())
    executer = service._executer_etape
    appels = {"validation": 0}

    def executer_puis_tomber(entrees, **kwargs):
        if entrees["etape"] == "validation":
            appels["validation"] += 1
            if appels["validation"] == 3:
                raise Arret
        return executer(entrees, **kwargs)

    monkeypatch.setattr(service, "_executer_etape", executer_puis_tomber)
    horloge = Horloge()
    with pytest.raises(Arret):
        _avancer(lot, horloge)
    monkeypatch.setattr(service, "_executer_etape", executer)
    en_bail = [t for t in _taches(lot) if t["statut"] == "BAIL"]
    assert len(en_bail) == 1 and en_bail[0]["etape"] == "validation" and en_bail[0]["tentatives"] == 1

    # Pendant le bail : un autre porteur avance tout le reste, mais pas ce document (son étape est tenue).
    pendant = _avancer(lot, horloge, porteur="porteur-b")
    assert pendant["statut"] == "EN_COURS" and pendant["compteurs"]["taches"]["BAIL"] == 1

    # À l'échéance, la même tâche (même ligne, tentative 2) reprend et le lot se termine.
    horloge.t += taches.QUOTAS["bail_secondes"] + 1
    apres = _avancer(lot, horloge, porteur="porteur-c")
    assert apres["statut"] == "TERMINE"
    reprise = [t for t in _taches(lot) if t["tache_id"] == en_bail[0]["tache_id"]][0]
    assert reprise["statut"] == "TERMINEE" and reprise["tentatives"] == 2
    assert _signature(_brouillons()) == attendu, "même résultat qu'une exécution sans arrêt, aucun doublon"
    assert len(_taches(lot)) == 7 * 13, "aucune tâche en double : clé (document, étape)"
    with stockage.transaction() as cnx:
        evenements = [r[0] for r in cnx.execute(select(INGESTION_JOURNAL.c.evenement).where(
            INGESTION_JOURNAL.c.tache_id == en_bail[0]["tache_id"]).order_by(INGESTION_JOURNAL.c.id))]
    assert evenements == ["tache.reservee", "tache.reprise_bail_expire", "tache.terminee"]


def test_un_arret_pendant_la_conclusion_annule_le_brouillon_et_la_reprise_l_ecrit_une_fois(instance, monkeypatch):
    lot = _deposer({"f1.txt": qa.texte_corpus("factures/F1-quincaillerie.txt").encode("utf-8")})
    conclure = service._conclure

    def conclure_puis_tomber(port, lot_, tache, *args, **kwargs):
        if tache["etape"] == "proposition":
            assert port.cnx.execute(select(func.count()).select_from(INGESTION_BROUILLONS)).scalar_one() == 1
            raise Arret
        return conclure(port, lot_, tache, *args, **kwargs)

    monkeypatch.setattr(service, "_conclure", conclure_puis_tomber)
    horloge = Horloge()
    with pytest.raises(Arret):
        _avancer(lot, horloge)
    assert _brouillons() == [], "la transaction de conclusion est annulée avec son brouillon"
    monkeypatch.setattr(service, "_conclure", conclure)
    horloge.t += taches.QUOTAS["bail_secondes"] + 1
    assert _avancer(lot, horloge)["statut"] == "TERMINE"
    [brouillon] = _brouillons()
    assert brouillon["statut"] == "PRET"
    assert _avancer(lot, horloge)["taches_executees"] == 0, "un lot terminé n'exécute plus rien"
    assert len(_brouillons()) == 1


def test_le_porteur_d_un_bail_repris_ne_peut_plus_rien_ecrire(instance):
    lot = _deposer({"f1.txt": b"FACTURE fictive"})
    horloge = Horloge()
    with stockage.transaction() as cnx:
        tache_a = taches.TachesSQLite(cnx, maintenant=horloge).reserver(lot["lot_id"], "porteur-a")
    horloge.t += taches.QUOTAS["bail_secondes"] + 1
    with stockage.transaction() as cnx:
        tache_b = taches.TachesSQLite(cnx, maintenant=horloge).reserver(lot["lot_id"], "porteur-b")
    assert tache_b["tache_id"] == tache_a["tache_id"] and tache_b["revision"] == tache_a["revision"] + 1
    with stockage.transaction() as cnx:
        port = taches.TachesSQLite(cnx, maintenant=horloge)
        assert port.terminer(tache_a, "porteur-a", nonce=None, chiffre=None, empreinte=None) is False
        assert port.echouer(tache_a, "porteur-a", "REJ-ING-ISOLATION-INDISPONIBLE", reprenable=True) is None
        assert port.terminer(tache_b, "porteur-b", nonce=None, chiffre=None, empreinte=None) is True
        assert port.terminer(tache_b, "porteur-b", nonce=None, chiffre=None, empreinte=None) is False


def test_une_panne_temporaire_reessaie_avec_delai_croissant_puis_file_morte(instance):
    lot = _deposer({"f1.pdf": qa.pdf_texte("FACTURE\nDocument fictif")})
    horloge = Horloge()

    def isolation_absente(_source):
        raise EchecEtape("REJ-ING-ISOLATION-INDISPONIBLE", "bwrap absent (simulé)", reprenable=True)

    def etat_texte():
        return [t for t in _taches(lot) if t["etape"] == "texte"][0]

    _avancer(lot, horloge, extracteur_pdf=isolation_absente)
    assert (etat_texte()["statut"], etat_texte()["tentatives"]) == ("ECHEC_REPRENABLE", 1)
    assert etat_texte()["disponible_des"] == T0 + 30
    rien = _avancer(lot, horloge, extracteur_pdf=isolation_absente)
    assert rien["taches_executees"] == 0, "le délai n'est pas écoulé"
    horloge.t = T0 + 31
    _avancer(lot, horloge, extracteur_pdf=isolation_absente)
    assert (etat_texte()["statut"], etat_texte()["tentatives"], etat_texte()["disponible_des"]) == (
        "ECHEC_REPRENABLE", 2, T0 + 31 + 60)
    horloge.t = T0 + 31 + 61
    fin = _avancer(lot, horloge, extracteur_pdf=isolation_absente)
    assert etat_texte()["statut"] == "FILE_MORTE" and fin["statut"] == "TERMINE"
    assert fin["compteurs"]["documents"] == {"NON_TRAITE": 1}
    assert {t["statut"] for t in _taches(lot) if t["rang_etape"] > 3} == {"SAUTEE"}


def test_une_tache_aux_tentatives_epuisees_passe_en_file_morte_au_lieu_d_etre_reservee(instance):
    lot = _deposer({"f1.txt": b"FACTURE fictive"})
    with stockage.transaction() as cnx:
        cnx.execute(update(INGESTION_TACHES).where(INGESTION_TACHES.c.etape == "empreinte").values(
            tentatives=taches.QUOTAS["tentatives"]))
    fin = _avancer(lot, Horloge())
    assert fin["compteurs"]["taches"] == {"FILE_MORTE": 1, "SAUTEE": 6}
    with stockage.transaction() as cnx:
        assert cnx.execute(select(INGESTION_JOURNAL.c.code).where(
            INGESTION_JOURNAL.c.evenement == "tache.file_morte")).scalar_one() == "REJ-ING-FILE-MORTE"


# ------------------------------------------------------------------------ port d'extraction : aucun repli
def _une_facture():
    return {"f1.txt": qa.texte_corpus("factures/F1-quincaillerie.txt").encode("utf-8")}


def _issue_extraction(lot):
    tache = [t for t in _taches(lot) if t["etape"] == "extraction"][0]
    return tache["statut"], tache["code"]


def test_sans_fournisseur_selectionne_refus_type_et_aucun_brouillon(tmp_path, monkeypatch):
    qa.preparer_instance(tmp_path, monkeypatch, fournisseur=False)
    lot = _deposer(_une_facture())
    fin = _avancer(lot)
    assert _issue_extraction(lot) == ("TERMINEE", "REJ-ING-FOURNISSEUR-REFUSE")
    assert fin["compteurs"]["documents"] == {"NON_TRAITE": 1} and _brouillons() == []


def test_fournisseur_inactif_ou_devenu_non_conforme_jamais_remplace(instance, monkeypatch):
    with stockage.transaction() as cnx:
        registre.desactiver(cnx, acteur="nathan", identifiant=qa.IDENTIFIANT_SIMULE)
    with stockage.transaction() as cnx, pytest.raises(EchecEtape) as exc:
        port_extraction.resoudre(cnx)
    assert exc.value.code == "REJ-ING-FOURNISSEUR-REFUSE" and "FOURNISSEUR_INACTIF" in exc.value.detail

    with stockage.transaction() as cnx:
        registre.configurer(cnx, acteur="nathan", identifiant="llm.qa-seuil", declaration={
            "capacite": "llm", "mode": "local", "modele": "qa-seuil", "point_acces": qa.POINT_ACCES_SIMULE,
            "licence": {"code": "Licence à seuil fictive", "poids": None, "usage_commercial": "sous_seuil",
                        "seuil_revenu_usd": 2_000_000, "service_tiers": "autorise", "integration": "bibliotheque",
                        "source": "tests OPSYS (fictif)"}})
        assert registre.activer(cnx, acteur="nathan", identifiant="llm.qa-seuil").conforme
        registre.selectionner(cnx, acteur="nathan", capacite="llm", identifiant="llm.qa-seuil",
                              departement="m05-financecore")
        registre.declarer_profil(cnx, acteur="nathan", usage_commercial=True, revenu_annuel_usd=3_000_000,
                                 territoires=["CA"], heberge_pour_tiers=False, revision_attendue=1)
    lot = _deposer(_une_facture())
    _avancer(lot)
    assert _issue_extraction(lot) == ("TERMINEE", "REJ-ING-FOURNISSEUR-REFUSE")
    with stockage.transaction() as cnx, pytest.raises(EchecEtape) as exc:
        port_extraction.resoudre(cnx)
    assert "REFUS_POLITIQUE" in exc.value.detail and "SEUIL_REVENU_DEPASSE" in exc.value.detail
    assert _brouillons() == [], "ni le défaut global ni un autre fournisseur n'a servi"


def test_un_fournisseur_conforme_non_raccorde_n_est_jamais_appele(instance, monkeypatch):
    monkeypatch.delitem(port_extraction._ADAPTATEURS, qa.POINT_ACCES_SIMULE)
    lot = _deposer(_une_facture())
    _avancer(lot)
    assert _issue_extraction(lot) == ("TERMINEE", "REJ-ING-EXTRACTEUR-NON-RACCORDE")
    assert port_extraction._ADAPTATEURS == {}, "aucun adaptateur réel (aucun appel réseau) dans cette tranche"


def test_une_sortie_d_adaptateur_invalide_ou_hors_schema(instance, monkeypatch):
    monkeypatch.setitem(port_extraction._ADAPTATEURS, qa.POINT_ACCES_SIMULE, lambda pages, f: ["pas", "un objet"])
    lot = _deposer(_une_facture())
    _avancer(lot, Horloge())
    assert _issue_extraction(lot)[0] == "ECHEC_REPRENABLE"

    monkeypatch.setitem(port_extraction._ADAPTATEURS, qa.POINT_ACCES_SIMULE,
                        lambda pages, f: {**qa.adaptateur_simule(pages, f), "tps": 15.2})
    lot = _deposer({"f2.txt": qa.texte_corpus("factures/F2-materiaux.txt").encode("utf-8")}, mutation="m-2")
    _avancer(lot)
    [brouillon] = _brouillons()
    assert brouillon["statut"] == "A_VERIFIER" and brouillon["raisons"] == '["REJ-ING-FACTURE-SCHEMA"]'


# ----------------------------------------------------------------------------------- texte : PDF et OCR
def test_pdf_scanne_sans_ocr_configure_puis_avec_ocr(instance, monkeypatch):
    image = {"ok": False, "code": "PDF_IMAGE_OU_MIXTE"}
    lot = _deposer({"scan.pdf": qa.pdf_texte("scan fictif")})
    monkeypatch.delenv("OPSYS_OCR_BUNDLE", raising=False)
    fin = _avancer(lot, extracteur_pdf=lambda s: image)
    assert fin["compteurs"]["documents"] == {"NON_TRAITE": 1}
    assert [t["code"] for t in _taches(lot) if t["etape"] == "texte"] == ["REJ-ING-OCR-INDISPONIBLE"]

    texte = qa.texte_corpus("factures/F1-quincaillerie.txt")
    candidat = {"pages": [{"numero": 1, "tokens": [{"texte": ligne} for ligne in texte.splitlines()]}]}
    lot = _deposer({"scan2.pdf": qa.pdf_texte("scan fictif 2")}, mutation="m-2")
    _avancer(lot, extracteur_pdf=lambda s: image, extracteur_ocr=lambda s, d: candidat)
    with stockage.transaction() as cnx:
        [ligne] = cnx.execute(select(INGESTION_BROUILLONS.c.brouillon_id)).all()
        brouillon = service.lire_brouillon(cnx, ligne[0])
    assert brouillon["contenu"]["texte_source"] == "ocr"
    assert brouillon["contenu"]["avertissements"] == ["texte issu d'OCR : relire les montants contre l'original"]


def test_pdf_refuse_par_le_parseur_natif_et_isolation_reelle_sans_bwrap(instance):
    lot = _deposer({"chiffre.pdf": qa.pdf_texte("x")})
    fin = _avancer(lot, extracteur_pdf=lambda s: {"ok": False, "code": "PDF_CHIFFRE"})
    assert fin["compteurs"]["documents"] == {"REFUSE": 1}
    assert [t["code"] for t in _taches(lot) if t["etape"] == "texte"] == ["REJ-ING-PDF-REFUSE"]


def test_profil_d_identite_illisible_refus_type(instance):
    (stockage.dossier_opsys() / "entreprise.yaml").write_text("identite_fiscale: [pas, un, objet]\n",
                                                              encoding="utf-8")
    lot = _deposer(_une_facture())
    _avancer(lot)
    assert [t["code"] for t in _taches(lot) if t["etape"] == "validation"] == ["REJ-ING-PROFIL-INVALIDE"]


def test_avancer_refuse_un_lot_inconnu_et_un_budget_hors_bornes(instance):
    from opsys.ingestion_onboarding.codes import IngestionErreur

    with pytest.raises(IngestionErreur) as exc:
        service.avancer(stockage.transaction, "nathan", "0" * 32)
    assert exc.value.code == "REJ-ING-LOT-INCONNU"
    with pytest.raises(IngestionErreur) as exc:
        service.avancer(stockage.transaction, "nathan", "0" * 32, budget=0)
    assert exc.value.code == "REJ-ING-ARGUMENT-INVALIDE"
    with pytest.raises(IngestionErreur) as exc:
        service.avancer(stockage.transaction, "nathan", "pas-un-id")
    assert exc.value.code == "REJ-ING-ARGUMENT-INVALIDE"


def test_l_horloge_par_defaut_est_celle_du_systeme():
    assert abs(service._horloge() - int(time.time())) <= 2


def test_deux_homonymes_sans_cle_forte_donnent_deux_brouillons_sans_collision(instance):
    """Même nom, aucun autre champ : aucune clé forte, deux fiches (règle faible signalée), deux clés métier
    distinctes ; un autre fichier au même homonyme ne s'y rattache pas d'office."""
    liste = "Nom,Téléphone\nPaul Fictif,\nPaul Fictif,\n"
    lot = _deposer({"clients.csv": liste.encode("utf-8")})
    assert _avancer(lot)["statut"] == "TERMINE"
    premiers = _brouillons()
    assert [(b["statut"], b["cles"]) for b in premiers] == [("A_VERIFIER", "[]"), ("A_VERIFIER", "[]")]
    autre = "Nom,Courriel\nPaul Fictif,\n"
    lot = _deposer({"autres-clients.csv": autre.encode("utf-8")}, mutation="m-2", nom="depot2.zip")
    _avancer(lot)
    assert len(_brouillons()) == 3
