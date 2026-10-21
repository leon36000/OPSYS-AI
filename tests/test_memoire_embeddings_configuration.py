"""Configuration du découpage embeddings sans changer le défaut distant."""

import pytest

from opsys.memoire.embeddings import ClientEmbeddings, ErreurEmbeddings


def test_depuis_env_configure_lot_local_sans_changer_le_defaut():
    base = {"OPSYS_EMBEDDINGS_URL": "http://127.0.0.1:8001/v1", "OPSYS_EMBEDDINGS_MODELE": "BAAI/bge-m3"}
    assert ClientEmbeddings.depuis_env(base).taille_lot == 32
    assert ClientEmbeddings.depuis_env({**base, "OPSYS_EMBEDDINGS_TAILLE_LOT": "1"}).taille_lot == 1
    assert ClientEmbeddings.depuis_env({**base, "OPSYS_EMBEDDINGS_TAILLE_LOT": "32"}).taille_lot == 32


@pytest.mark.parametrize("valeur", ["", "0", "01", "33", "1.5", "1e1", "oui", "+1", " 1 ", "9" * 1000])
def test_depuis_env_refuse_lot_vide_hors_borne_ou_non_canonique(valeur):
    env = {
        "OPSYS_EMBEDDINGS_URL": "http://127.0.0.1:8001/v1",
        "OPSYS_EMBEDDINGS_MODELE": "BAAI/bge-m3",
        "OPSYS_EMBEDDINGS_TAILLE_LOT": valeur,
    }
    with pytest.raises(ErreurEmbeddings, match="OPSYS_EMBEDDINGS_TAILLE_LOT"):
        ClientEmbeddings.depuis_env(env)
