"""OPT-IN contre une VRAIE passerelle LiteLLM (jamais requis par la CI).

Variables d'environnement : `OPSYS_LITELLM_TEST_URL` (ex. http://127.0.0.1:14400) et
`OPSYS_LITELLM_TEST_KEY_FILE` (chemin d'un fichier contenant la clé d'essai : lue au moment de l'essai, copiée dans
un coffre TEMPORAIRE, jamais affichée ni écrite ailleurs). Appels minuscules et BORNÉS : un test de connexion Haiku
(8 jetons de sortie), un appel routé de classification (8 jetons) et un seul embedding. Aucun appel du
raisonnement, aucune boucle.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from modeles_aide import PROPRIETAIRE, declarer_profil, preparer_identites

from opsys.roles_modeles import appel, decouverte, passerelle_fournisseur, service
from opsys.secrets_coffre import coffre

FICTIF = True
URL = os.environ.get("OPSYS_LITELLM_TEST_URL")
FICHIER_CLE = os.environ.get("OPSYS_LITELLM_TEST_KEY_FILE")
pytestmark = pytest.mark.skipif(not URL or not FICHIER_CLE or not Path(FICHIER_CLE).is_file(),
                                reason="OPSYS_LITELLM_TEST_URL / OPSYS_LITELLM_TEST_KEY_FILE absents (essai opt-in)")
HAIKU, EMBEDDING = "opsys-haiku-5-5", "opsys-embed-e5-multilingue"


def test_vraie_passerelle_connexion_catalogue_roles_et_appels_minuscules(session, cle_coffre):
    cle = Path(FICHIER_CLE).read_text(encoding="utf-8").strip()
    preparer_identites(session)
    declarer_profil(session)
    with session() as cnx:
        coffre.definir(cnx, acteur=PROPRIETAIRE, nom="passerelle.cle", service="fournisseur_modele", valeur=cle)
        service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_PASSERELLE_CONFIGURER, niveau_confirme="N3",
                          parametres={"mode": "existante", "url_base": URL, "secret_cle": "passerelle.cle",
                                      "reseau_prive_confirme": True})
    catalogue = decouverte.decouvrir(session, acteur=PROPRIETAIRE)
    assert catalogue["statut"] == "succes", catalogue
    noms = {e["nom"] for e in catalogue["entrees"]}
    assert {HAIKU, EMBEDDING} <= noms
    for role, alias in (("llm_rapide", HAIKU), ("embeddings", EMBEDDING)):
        with session() as cnx:
            declare = passerelle_fournisseur.declarer(cnx, acteur=PROPRIETAIRE, role=role, alias=alias,
                                                      secret_cle="passerelle.cle", efvp_ref="EFVP-ESSAI-FICTIVE",
                                                      contrat_ref="CONTRAT-ESSAI-FICTIF")
            assert declare["active"], declare
            service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_AFFECTER, niveau_confirme="N3",
                              parametres={"role": role, "fournisseur_id": declare["identifiant"],
                                          "modele_appel": alias})
    mesure = appel.tester_role(session, acteur=PROPRIETAIRE, role="llm_rapide")
    assert mesure["statut"] == "succes", mesure
    dimension = appel.tester_role(session, acteur=PROPRIETAIRE, role="embeddings")
    assert dimension["statut"] == "succes" and dimension["dimension"] >= 8
    reponse = appel.completer(session, classe="classification", max_tokens=8,
                              messages=[{"role": "user", "content": "Réponds par le seul mot : OK"}])
    assert reponse["role"] == "llm_rapide" and reponse["modele"] == HAIKU and reponse["repli_utilise"] is False
    assert reponse["usage"]["sortie"] <= 8
    assert cle not in str(reponse) and cle not in str(mesure)
