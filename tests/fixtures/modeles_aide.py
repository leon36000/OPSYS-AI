"""Aides communes des tests de la passerelle de modèles (données fictives, aucun réseau réel)."""

from __future__ import annotations

from opsys import identite
from opsys.fournisseurs import registre
from opsys.roles_modeles import passerelle_fournisseur, service
from opsys.roles_modeles import roles as lex
from opsys.secrets_coffre import coffre

FICTIF = True
MOT_DE_PASSE = "mot-de-passe-modeles-fictif-2026"
CLE_AMONT = "cle-amont-fictive-openrouter-9876543210-ZYXW"
PROPRIETAIRE = "proprio_fictif"


def preparer_identites(session) -> None:
    with session() as cnx:
        identite.creer_personne(cnx, PROPRIETAIRE, "Propriétaire fictif", MOT_DE_PASSE, ["nathan_owner"])
        identite.creer_personne(cnx, "vendeur_fictif", "Vendeur fictif", MOT_DE_PASSE, ["seller"])


def declarer_profil(session, *, revenu: int | None = 500_000) -> None:
    with session() as cnx:
        courant = registre.profil_brut(cnx)
        registre.declarer_profil(
            cnx,
            acteur=PROPRIETAIRE,
            usage_commercial=True,
            revenu_annuel_usd=revenu,
            territoires=["CA"],
            heberge_pour_tiers=False,
            revision_attendue=0 if courant is None else courant["revision"],
        )


def definir_secrets(session, cle_passerelle: str) -> None:
    with session() as cnx:
        coffre.definir(
            cnx, acteur=PROPRIETAIRE, nom="passerelle.cle", service="fournisseur_modele", valeur=cle_passerelle
        )
        coffre.definir(
            cnx, acteur=PROPRIETAIRE, nom="passerelle.openrouter", service="fournisseur_modele", valeur=CLE_AMONT
        )


def connecter_passerelle(session, url: str, **extra) -> dict:
    with session() as cnx:
        return service.appliquer(
            cnx,
            acteur=PROPRIETAIRE,
            operation=service.OP_PASSERELLE_CONFIGURER,
            parametres={
                "mode": "integree",
                "url_base": url,
                "secret_cle": "passerelle.cle",
                "secrets_amont": {"openrouter": "passerelle.openrouter"},
                **extra,
            },
            niveau_confirme="N3",
        )


def fournisseur_passerelle(session, role: str, alias: str) -> str:
    with session() as cnx:
        r = passerelle_fournisseur.declarer(
            cnx,
            acteur=PROPRIETAIRE,
            role=role,
            alias=alias,
            secret_cle="passerelle.cle",
            efvp_ref="EFVP-FICTIVE-2026-01",
            contrat_ref="CONTRAT-FICTIF-OPENROUTER",
        )
    assert r["active"], r
    return r["identifiant"]


def affecter(session, role: str, alias: str, *, amont: dict | None = None, **extra) -> dict:
    identifiant = fournisseur_passerelle(session, role, alias)
    parametres = {"role": role, "fournisseur_id": identifiant, "modele_appel": alias, **extra}
    if amont:
        parametres["amont"] = amont
    with session() as cnx:
        return service.appliquer(
            cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_AFFECTER, parametres=parametres, niveau_confirme="N3"
        )


def fournisseur_local(session, identifiant: str, url: str, capacite: str = "llm") -> str:
    """Fournisseur LOCAL fictif (vLLM simulé par un second faux serveur) pour les replis hors ligne."""
    with session() as cnx:
        registre.configurer(
            cnx,
            acteur=PROPRIETAIRE,
            identifiant=identifiant,
            declaration={
                "capacite": capacite,
                "mode": "local",
                "modele": "qwen-local-fictif",
                "point_acces": url,
                "licence": {
                    "code": "Apache-2.0",
                    "poids": "Apache-2.0",
                    "usage_commercial": "autorise",
                    "service_tiers": "autorise",
                    "verification": "verifiee",
                    "integration": "bibliotheque",
                    "source": "test fictif",
                },
            },
        )
        decision = registre.activer(cnx, acteur=PROPRIETAIRE, identifiant=identifiant)
    assert decision.conforme, decision.codes
    return identifiant


__all__ = ["lex"]


# -- fixtures partagées (importées par les modules de test) ----------------------------------------------------------
import pytest  # noqa: E402

from faux_litellm import CLE_FICTIVE, FauxLiteLLM  # noqa: E402
from opsys.secrets_coffre import cle_maitresse  # noqa: E402

AMONT = {
    "llm_rapide": {"fournisseur": "openrouter", "modele": "anthropic/claude-haiku-5.5"},
    "llm_fort": {"fournisseur": "openrouter", "modele": "anthropic/claude-sonnet-5.5"},
    "llm_raisonnement": {"fournisseur": "openrouter", "modele": "anthropic/claude-opus-5.5"},
    "embeddings": {"fournisseur": "openrouter", "modele": "intfloat/multilingual-e5-large"},
}
ALIAS = {"llm_rapide": "opsys-haiku-5-5", "llm_fort": "opsys-sonnet-5-5", "llm_raisonnement": "opsys-opus-5-5",
         "embeddings": "opsys-embed-e5-multilingue", "vl": "opsys-vl-qwen3-30b", "reranker": "opsys-rerank-fictif"}


@pytest.fixture
def cle_coffre(tmp_path, monkeypatch):
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    cle_maitresse.generer_fichier(dossier / "coffre.cle")
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(dossier / "coffre.cle"))
    monkeypatch.delenv(cle_maitresse.ENV_CLE, raising=False)


@pytest.fixture
def faux():
    with FauxLiteLLM() as serveur:
        yield serveur


@pytest.fixture
def faux_local():
    """Second faux serveur : le « vLLM local » du repli hors ligne (aucune clé requise, comme un vLLM local)."""
    with FauxLiteLLM(cle=None) as serveur:
        serveur.modeles = {"qwen-local-fictif": {"mode": "chat", "in": 0, "out": 0}}
        yield serveur


@pytest.fixture
def pret(session, cle_coffre, faux):
    """Instance prête : identités, profil de licence, secrets du coffre et passerelle connectée au faux serveur."""
    preparer_identites(session)
    declarer_profil(session)
    definir_secrets(session, CLE_FICTIVE)
    connecter_passerelle(session, faux.url)
    return session
