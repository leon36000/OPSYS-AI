"""Raccord des consommateurs au registre des rôles : embeddings et reranker de M10, choix du moteur OCR.

Sans rôle configuré, le comportement d'avant est EXACTEMENT conservé (fail-closed : « conforme mais non raccordé »).
"""

from __future__ import annotations

import pytest
from connaissances_aide import MAINTENANT, ingerer_et_publier
from modeles_aide import (
    ALIAS,
    AMONT,
    PROPRIETAIRE,
    affecter,
    fournisseur_passerelle,
)

from opsys import stockage
from opsys.connaissances import lecture, ports
from opsys.connaissances.codes import EMBEDDINGS_NON_RACCORDE, FOURNISSEUR_REFUSE, ErreurConnaissances
from opsys.connaissances.recherche import rechercher
from opsys.fournisseurs import registre
from opsys.ingestion_onboarding import extraction_texte
from opsys.ingestion_onboarding.codes import EchecEtape
from opsys.roles_modeles import adaptateurs, appel, service

FICTIF = True
DEP = "m05-financecore"


def _port(session, dep=DEP):
    with session() as cnx:
        return ports.resoudre_embeddeur(cnx, dep)


def _erreur_embeddings(session):
    with session() as cnx, pytest.raises(ErreurConnaissances) as exc:
        ports.resoudre_embeddeur(cnx, DEP)
    return exc.value


def test_sans_role_le_comportement_d_avant_est_conserve(pret):
    e = _erreur_embeddings(pret)
    assert e.code == FOURNISSEUR_REFUSE and "AUCUN_FOURNISSEUR" in e.detail
    assert adaptateurs.embeddings_raccordes() is False
    assert ports._ADAPTATEURS_EMBEDDINGS == {} and ports._ADAPTATEURS_RERANKER == {}


def test_role_affecte_mais_dimension_non_mesuree_reste_non_raccorde(pret):
    affecter(pret, "embeddings", ALIAS["embeddings"])
    e = _erreur_embeddings(pret)
    assert e.code == EMBEDDINGS_NON_RACCORDE and "dimension" in e.detail
    assert adaptateurs.embeddings_raccordes() is False
    with pret() as cnx:
        assert lecture._fournisseur(cnx, "embeddings", DEP, {})["raccorde"] is False


def test_apres_mesure_le_port_embeddings_appelle_la_passerelle_dans_la_transaction(pret, faux):
    affecter(pret, "embeddings", ALIAS["embeddings"], amont=AMONT["embeddings"])
    assert appel.tester_role(pret, acteur=PROPRIETAIRE, role="embeddings")["dimension"] == 8
    assert adaptateurs.embeddings_raccordes() is True
    with pret() as cnx:  # comme un outil MCP : le secret du coffre est résolu dans un point de sauvegarde
        port = ports.resoudre_embeddeur(cnx, DEP)
        profil = port.profil()
        assert (profil.fournisseur_id, profil.modele, profil.dimension) == (
            "embeddings.passerelle.opsys-embed-e5-multilingue",
            "opsys-embed-e5-multilingue",
            8,
        )
        assert profil.config_sha256 == ports.empreinte_configuration(registre.definition(cnx, profil.fournisseur_id))
        vecteurs = ports.plonger_documents(port, ["premier texte", "second texte"])
        requete = ports.plonger_requete(port, "une question")
        assert lecture._fournisseur(cnx, "embeddings", DEP, {})["raccorde"] is True
    assert len(vecteurs) == 2 and len(vecteurs[0]) == 8 and len(requete) == 8
    appels = faux.appels_modele("opsys-embed-e5-multilingue")
    assert len(appels) == 1 + 2 and all(a["autorise"] for a in appels)  # test + lot de 2 + requête
    with pret() as cnx:
        assert service.usage(cnx, "embeddings")["jetons_entree"] > 0  # l'usage est compté


def test_changer_d_alias_change_l_espace_vectoriel(pret, faux):
    affecter(pret, "embeddings", ALIAS["embeddings"])
    appel.tester_role(pret, acteur=PROPRIETAIRE, role="embeddings")
    premier = _port(pret).profil()
    faux.modeles["autre-embedding"] = {"mode": "embedding", "in": 0, "out": 0}
    affecter(pret, "embeddings", "autre-embedding")
    appel.tester_role(pret, acteur=PROPRIETAIRE, role="embeddings")
    second = _port(pret).profil()
    assert second.espace_id != premier.espace_id and second.fournisseur_id != premier.fournisseur_id


def test_indexation_et_recherche_de_bout_en_bout_par_la_passerelle(pret, faux):
    affecter(pret, "embeddings", ALIAS["embeddings"])
    appel.tester_role(pret, acteur=PROPRIETAIRE, role="embeddings")
    with pret() as cnx:
        port = ports.resoudre_embeddeur(cnx, DEP)
        resultat = ingerer_et_publier(cnx, embeddeur=port)
        assert resultat["version_id"]
        envoyes = [a for a in faux.appels if a.get("chemin") == "/v1/embeddings"]
        assert len(envoyes) >= 2  # le test, puis l'indexation des fragments
        trouve = rechercher(
            cnx, requete="taux de la taxe de vente", departements=[DEP], k=3, maintenant=MAINTENANT, embeddeur=port
        )
    assert trouve["statut"] != "aucune_source" and trouve["resultats"]
    assert not [a for a in trouve.get("avertissements", []) if "embeddings" in str(a).lower()]
    assert len([a for a in faux.appels if a.get("chemin") == "/v1/embeddings"]) > len(envoyes)  # la requête aussi


def test_dimension_incoherente_d_un_vecteur_est_refusee(pret, faux):
    affecter(pret, "embeddings", ALIAS["embeddings"])
    appel.tester_role(pret, acteur=PROPRIETAIRE, role="embeddings")
    faux.dimension = 4  # la passerelle change de modèle sous le même alias : jamais mélanger les espaces
    with pret() as cnx:
        port = ports.resoudre_embeddeur(cnx, DEP)
        with pytest.raises(ErreurConnaissances):
            ports.plonger_documents(port, ["texte"])


def test_secret_non_resoluble_dans_l_outil_est_un_refus_type_pas_une_fuite(pret, faux):
    from opsys.secrets_coffre import coffre

    affecter(pret, "embeddings", ALIAS["embeddings"])
    appel.tester_role(pret, acteur=PROPRIETAIRE, role="embeddings")
    with pret() as cnx:
        coffre.revoquer(cnx, acteur=PROPRIETAIRE, nom="passerelle.cle")
    n = len(faux.appels)
    with pret() as cnx:
        port = ports.resoudre_embeddeur(cnx, DEP)
        with pytest.raises(ErreurConnaissances) as exc:
            ports.plonger_requete(port, "x")
    assert "ModelesErreur" in exc.value.detail or "adaptateur" in exc.value.detail
    assert len(faux.appels) == n


def test_reranker_est_un_point_d_extension_raccorde_par_le_role(pret, faux):
    with pret() as cnx:
        assert ports.reranker_disponible(cnx, DEP) == (None, None)  # facultatif : rien de sélectionné
    ident = fournisseur_passerelle(pret, "reranker", ALIAS["reranker"])
    with pret() as cnx:
        service.appliquer(
            cnx,
            acteur=PROPRIETAIRE,
            operation=service.OP_ROLE_AFFECTER,
            niveau_confirme="N3",
            parametres={"role": "reranker", "fournisseur_id": ident, "modele_appel": ALIAS["reranker"]},
        )
    with pret() as cnx:
        port, refus = ports.reranker_disponible(cnx, DEP)
        assert refus is None
        notes = ports.noter(port, "q", ["a", "b"])
        assert notes == [1.0, 0.5] and port.identite().fournisseur_id == ident
    assert len(faux.appels_modele(ALIAS["reranker"])) == 1


# -- OCR --------------------------------------------------------------------------------------------------------------
def _affecter_ocr(session, identifiant):
    with session() as cnx:
        registre.configurer(cnx, acteur=PROPRIETAIRE, identifiant=identifiant, modifications={})
        decision = registre.activer(cnx, acteur=PROPRIETAIRE, identifiant=identifiant)
        assert decision.conforme, decision.codes
        service.appliquer(
            cnx,
            acteur=PROPRIETAIRE,
            operation=service.OP_ROLE_AFFECTER,
            niveau_confirme="N3",
            parametres={"role": "ocr", "fournisseur_id": identifiant, "modele_appel": "moteur"},
        )


def test_ocr_sans_role_message_d_avant(pret, monkeypatch):
    monkeypatch.delenv("OPSYS_INGESTION_OCR_BUNDLE", raising=False)
    with pytest.raises(EchecEtape) as exc:
        extraction_texte.extracteur_ocr_local(b"%PDF-1.4", "0" * 32)
    assert exc.value.code == "REJ-ING-OCR-INDISPONIBLE" and "OPSYS_OCR_BUNDLE" in str(exc.value)
    assert adaptateurs.moteur_ocr_choisi() is None and adaptateurs.refus_moteur_ocr(None) is None


def test_ocr_choisi_tesseract_poursuit_le_chemin_existant(pret, monkeypatch):
    monkeypatch.delenv("OPSYS_INGESTION_OCR_BUNDLE", raising=False)
    _affecter_ocr(pret, "ocr.tesseract-5.5.local")
    assert adaptateurs.moteur_ocr_choisi() == "ocr.tesseract-5.5.local"
    with pytest.raises(EchecEtape) as exc:  # le moteur est bon ; c'est le bundle (opérateur) qui manque, comme avant
        extraction_texte.extracteur_ocr_local(b"%PDF-1.4", "0" * 32)
    assert "OPSYS_OCR_BUNDLE" in str(exc.value)


def test_ocr_choisi_autre_moteur_est_refuse_jamais_remplace_par_tesseract(pret, monkeypatch, tmp_path):
    monkeypatch.setenv("OPSYS_INGESTION_OCR_BUNDLE", str(tmp_path))  # même avec un bundle configuré
    _affecter_ocr(pret, "ocr.paddleocr.local")
    with pytest.raises(EchecEtape) as exc:
        extraction_texte.extracteur_ocr_local(b"%PDF-1.4", "0" * 32)
    assert exc.value.code == "REJ-ING-OCR-INDISPONIBLE"
    assert "ocr.paddleocr.local" in str(exc.value) and "aucun autre moteur" in str(exc.value)
    assert adaptateurs.refus_moteur_ocr("ocr.paddleocr.local") is not None
    assert adaptateurs.refus_moteur_ocr(adaptateurs.OCR_RACCORDE) is None


def test_stockage_sans_transaction_courante_n_est_pas_requis_pour_les_lectures(pret):
    assert stockage.connexion_courante() is None
    assert adaptateurs.moteur_ocr_choisi() is None
