"""Test OPT-IN du banc d'embeddings contre la VRAIE passerelle LiteLLM de test.

Jamais requis par la CI : il est sauté sauf si OPSYS_LITELLM_TEST_URL et OPSYS_LITELLM_TEST_KEY_FILE sont définies
(la clé est lue dans le fichier, jamais affichée). Une poignée d'appels minuscules (quelques jetons, coût inférieur à
0,001 USD) vérifient que le client et la forme des réponses correspondent au service réel ; ce test ne mesure aucune
qualité.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "install" / "qualification"))

from embeddings_fr import banc, juge, passerelle  # noqa: E402

URL = os.environ.get(passerelle.ENV_URL)
FICHIER_CLE = os.environ.get(passerelle.ENV_CLE_FICHIER)

pytestmark = pytest.mark.skipif(
    not URL or not FICHIER_CLE or not Path(FICHIER_CLE).is_file(),
    reason=f"opt-in : définir {passerelle.ENV_URL} et {passerelle.ENV_CLE_FICHIER} pour viser la passerelle réelle")


@pytest.fixture(scope="module")
def client():
    return passerelle.ClientPasserelle(URL, passerelle.lire_cle(FICHIER_CLE))


@pytest.mark.parametrize("config", banc.CONFIGURATIONS, ids=lambda c: c.identifiant)
def test_chaque_configuration_repond_avec_des_vecteurs_valides(client, config):
    genre = "query" if config.input_type else None
    reponse = client.embeddings(config.modele, [config.prefixe_requete + "gouttière qui coule au coin"],
                                input_type=genre)
    vecteur = reponse.vecteurs[0]
    assert len(vecteur) >= 256 and all(math.isfinite(x) for x in vecteur) and any(vecteur)
    assert reponse.jetons is None or reponse.jetons > 0


def test_une_mauvaise_cle_est_refusee_sans_fuite():
    mauvaise = "cle-de-test-invalide-0000"
    client = passerelle.ClientPasserelle(URL, mauvaise, dormir=lambda s: None)
    with pytest.raises(passerelle.ErreurPasserelle) as exc:
        client.embeddings("opsys-embed-voyage-4-lite", ["essai"])
    assert mauvaise not in str(exc.value) and exc.value.http_status in (400, 401, 403)


def test_le_juge_de_reclassement_rend_un_json_exploitable(client, tmp_path):
    from embeddings_fr.cache import Cache

    passages = {"A": "Le barrage de glace tire sur la gouttière.", "B": "La facture est payée par virement."}
    notes = juge.juger(client, Cache(tmp_path / "c"), "opsys-haiku-5-5", "Q001",
                       "Pourquoi la glace arrache ma gouttière ?", ["A", "B"], passages)
    assert notes is not None and notes["A"] > notes["B"]
