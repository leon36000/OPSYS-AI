"""Client /v1/embeddings (stdlib) contre un faux endpoint OpenAI-compatible local."""

from __future__ import annotations

import pytest
from memoire.doubles import plonger, port_ferme, serveur_embeddings

from opsys.memoire.embeddings import ClientEmbeddings, ErreurEmbeddings


def test_plonge_par_lots_remet_dans_l_ordre_des_index_et_envoie_la_cle():
    textes = ["toiture", "fenêtre", "sous-sol", "peinture", "drain français"]
    with serveur_embeddings(cle="jeton-de-test", ordre_inverse=True) as serveur:
        client = ClientEmbeddings(base_url=serveur.url, modele="BAAI/bge-m3", cle="jeton-de-test",
                                  taille_lot=2)
        vecteurs = client.plonger(textes)
    assert vecteurs == [plonger(t) for t in textes]
    assert [r["chemin"] for r in serveur.requetes] == ["/v1/embeddings"] * 3
    assert {r["autorisation"] for r in serveur.requetes} == {"Bearer jeton-de-test"}
    assert serveur.requetes[0]["corps"] == {"model": "BAAI/bge-m3", "input": ["toiture", "fenêtre"]}


def test_liste_vide_ne_fait_aucun_appel():
    with serveur_embeddings() as serveur:
        assert ClientEmbeddings(base_url=serveur.url, modele="m").plonger([]) == []
    assert serveur.requetes == []


@pytest.mark.parametrize(
    ("comportement", "motif"),
    [
        ("http_500", "HTTP 500"),
        ("json_invalide", "non JSON"),
        ("dimension_fausse", "dimension 1023"),
        ("nombre_faux", "1 vecteur"),
        ("valeur_non_finie", "non finie"),
    ],
)
def test_reponse_defectueuse_leve_une_erreur_explicite(comportement, motif):
    with serveur_embeddings(comportement=comportement) as serveur:
        client = ClientEmbeddings(base_url=serveur.url, modele="m")
        with pytest.raises(ErreurEmbeddings, match=motif):
            client.plonger(["a", "b"])


def test_cle_refusee_sans_fuite_de_la_cle():
    with serveur_embeddings(cle="la-bonne-cle") as serveur:
        client = ClientEmbeddings(base_url=serveur.url, modele="m", cle="une-mauvaise-cle")
        with pytest.raises(ErreurEmbeddings, match="HTTP 401") as erreur:
            client.plonger(["a"])
    assert "une-mauvaise-cle" not in str(erreur.value)
    assert "une-mauvaise-cle" not in repr(client)


def test_delai_depasse_et_service_injoignable_sont_explicites():
    with serveur_embeddings(delai_s=1.0) as serveur:
        lent = ClientEmbeddings(base_url=serveur.url, modele="m", delai_s=0.2)
        with pytest.raises(ErreurEmbeddings, match="délai"):
            lent.plonger(["a"])
    absent = ClientEmbeddings(base_url=f"http://127.0.0.1:{port_ferme()}/v1", modele="m", delai_s=2)
    with pytest.raises(ErreurEmbeddings, match="injoignable"):
        absent.plonger(["a"])


def test_entrees_invalides_refusees_avant_tout_appel():
    with serveur_embeddings() as serveur:
        client = ClientEmbeddings(base_url=serveur.url, modele="m")
        with pytest.raises(ValueError, match="texte vide"):
            client.plonger(["ok", "   "])
    assert serveur.requetes == []


def test_configuration_par_variables_d_environnement():
    assert ClientEmbeddings.depuis_env({}) is None  # non configuré : mode plein texte explicite
    with pytest.raises(ErreurEmbeddings, match="OPSYS_EMBEDDINGS_MODELE"):
        ClientEmbeddings.depuis_env({"OPSYS_EMBEDDINGS_URL": "http://embeddings:80/v1"})
    with pytest.raises(ErreurEmbeddings, match="http"):
        ClientEmbeddings.depuis_env({"OPSYS_EMBEDDINGS_URL": "ftp://x/v1", "OPSYS_EMBEDDINGS_MODELE": "m"})
    client = ClientEmbeddings.depuis_env({
        "OPSYS_EMBEDDINGS_URL": "http://embeddings:80/v1/",
        "OPSYS_EMBEDDINGS_MODELE": "BAAI/bge-m3",
        "OPSYS_EMBEDDINGS_CLE": "secret-embeddings",
        "OPSYS_EMBEDDINGS_LOCAL": "1",
    })
    assert client is not None
    assert (client.base_url, client.modele, client.local) == ("http://embeddings:80/v1", "BAAI/bge-m3", True)
    assert "secret-embeddings" not in repr(client)
    distant = ClientEmbeddings.depuis_env({"OPSYS_EMBEDDINGS_URL": "https://api.exemple/v1",
                                           "OPSYS_EMBEDDINGS_MODELE": "m"})
    assert distant is not None and distant.local is False
