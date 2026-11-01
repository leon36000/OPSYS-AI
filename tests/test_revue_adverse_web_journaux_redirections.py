"""Revue adverse « web » : secrets dans les journaux, redirections HTTP avec jeton, validations à `$`, journal d'accès.

Chaque test est un exploit : ROUGE sur le code d'origine, vert une fois le correctif posé.
Aucune donnée réelle, aucun accès hors de la boucle locale (serveurs HTTP éphémères sur 127.0.0.1).
"""

from __future__ import annotations

import contextlib
import io
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from opsys import fichiers, passerelle
from opsys.console.journaux_http import MasquerRecherche
from opsys.evaluation import repondants
from opsys.memoire.embeddings import ClientEmbeddings, ErreurEmbeddings
from opsys.secrets_coffre import masquage

FICTIF = True
SECRET_ACTIF = "S3cr3t-Valeur-Active-Fictive-XYZ"
JETON_BEARER = "Bearer abcdefghijklmnop1234"


# ======================================================================================= web-01 : exc_info des journaux
@pytest.fixture
def journal_capture():
    masquage.installer()
    masquage.enregistrer(SECRET_ACTIF)
    tampon = io.StringIO()
    gestionnaire = logging.StreamHandler(tampon)
    gestionnaire.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    journal = logging.getLogger("revue_adverse_web.journal")
    journal.addHandler(gestionnaire)
    journal.setLevel(logging.DEBUG)
    journal.propagate = False
    try:
        yield journal, tampon
    finally:
        journal.removeHandler(gestionnaire)
        masquage.oublier(SECRET_ACTIF)


def test_la_trace_d_une_exception_ne_laisse_pas_fuir_un_secret_actif(journal_capture):
    journal, tampon = journal_capture
    try:
        raise RuntimeError(f"échec du fournisseur avec {SECRET_ACTIF}")
    except RuntimeError:
        journal.exception("appel fournisseur")
    sortie = tampon.getvalue()
    assert SECRET_ACTIF not in sortie
    assert masquage.MASQUE in sortie
    assert "RuntimeError" in sortie  # le diagnostic reste lisible : seul le secret disparaît


def test_la_trace_d_une_exception_masque_aussi_les_formes_usuelles_de_cles(journal_capture):
    journal, tampon = journal_capture
    try:
        raise ValueError(f"en-tête refusé : {JETON_BEARER}")
    except ValueError:
        journal.error("refus", exc_info=True)
    assert JETON_BEARER.split()[1] not in tampon.getvalue()


def test_la_cause_chainee_d_une_exception_est_masquee(journal_capture):
    journal, tampon = journal_capture
    try:
        try:
            raise OSError(f"connexion refusée pour {SECRET_ACTIF}")
        except OSError as cause:
            raise RuntimeError("enveloppe sans secret") from cause
    except RuntimeError:
        journal.exception("chaîne")
    assert SECRET_ACTIF not in tampon.getvalue()


def test_un_message_sans_secret_et_sans_exception_reste_intact(journal_capture):
    journal, tampon = journal_capture
    journal.info("synchronisation terminée : %d messages", 12)
    try:
        raise KeyError("compte_inconnu")
    except KeyError:
        journal.exception("lecture")
    sortie = tampon.getvalue()
    assert "synchronisation terminée : 12 messages" in sortie
    assert "KeyError: 'compte_inconnu'" in sortie


# ======================================================================================= web-02 : redirections
class _Cible:
    """Serveur de la « cible » de la redirection : il note les en-têtes reçus."""

    def __init__(self) -> None:
        self.requetes: list[dict[str, str]] = []
        cible = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def _repondre(self) -> None:
                cible.requetes.append({k.lower(): v for k, v in self.headers.items()})
                corps = b"{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            do_GET = do_POST = _repondre

            def log_message(self, *_: object) -> None:
                return

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self) -> None:
        self.serveur.shutdown()
        self.serveur.server_close()


class _Redirecteur:
    """Serveur « compromis » : toute requête est redirigée (302) vers `vers`."""

    def __init__(self, vers: str) -> None:
        redirecteur = self
        self.vues = 0

        class Gestionnaire(BaseHTTPRequestHandler):
            def _rediriger(self) -> None:
                redirecteur.vues += 1
                self.send_response(302)
                self.send_header("Location", vers)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST = _rediriger

            def log_message(self, *_: object) -> None:
                return

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self) -> None:
        self.serveur.shutdown()
        self.serveur.server_close()


@pytest.fixture
def paire_redirection(monkeypatch):
    for nom in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")
    cible = _Cible()
    redirecteur = _Redirecteur(cible.url + "/vole")
    try:
        yield redirecteur, cible
    finally:
        redirecteur.fermer()
        cible.fermer()


def _cles_recues(cible: _Cible) -> list[str]:
    return [r.get("authorization", "") for r in cible.requetes]


def test_embeddings_ne_suit_pas_une_redirection_et_n_envoie_pas_la_cle(paire_redirection):
    redirecteur, cible = paire_redirection
    client = ClientEmbeddings(base_url=redirecteur.url + "/v1", modele="m", cle="cle-embeddings-fictive-0001")
    with pytest.raises(ErreurEmbeddings):
        client.plonger(["bonjour"])
    assert cible.requetes == [], f"la cible de la redirection a reçu {_cles_recues(cible)}"
    assert redirecteur.vues == 1


def test_embeddings_handshake_local_ne_suit_pas_une_redirection(paire_redirection):
    redirecteur, cible = paire_redirection
    client = ClientEmbeddings(base_url=redirecteur.url + "/v1", modele="m", cle="cle-embeddings-fictive-0002",
                              local=True)
    with pytest.raises(ErreurEmbeddings):
        client.verifier_profil_local()
    assert cible.requetes == [], f"la cible de la redirection a reçu {_cles_recues(cible)}"


def test_passerelle_litellm_ne_suit_pas_une_redirection_et_n_envoie_pas_la_cle_maitre(paire_redirection):
    redirecteur, cible = paire_redirection
    client = passerelle.ClientLiteLLM(redirecteur.url, "cle-maitre-fictive-0003")
    with contextlib.suppress(Exception):  # l'issue importe peu : seul l'envoi de la clé compte
        client.info("cle-virtuelle-fictive-0004-xxxxxxxx")
    assert cible.requetes == [], f"la cible de la redirection a reçu {_cles_recues(cible)}"


def test_repondant_passerelle_ne_suit_pas_une_redirection(paire_redirection):
    redirecteur, cible = paire_redirection
    with pytest.raises(Exception):  # noqa: B017, PT011 — refus typé de l'évaluation
        repondants._transport_urllib(redirecteur.url + "/chat", {"x": 1},
                                     {"Authorization": "Bearer cle-evaluation-fictive-0005",
                                      "Content-Type": "application/json"})
    assert cible.requetes == [], f"la cible de la redirection a reçu {_cles_recues(cible)}"


def test_un_serveur_qui_ne_redirige_pas_reste_joignable():
    """Cas négatif : une réponse directe est toujours lue (la garde ne casse pas l'appel légitime)."""
    cible = _Cible()
    try:
        client = ClientEmbeddings(base_url=cible.url + "/v1", modele="m", cle="cle-embeddings-fictive-0006")
        with pytest.raises(ErreurEmbeddings):  # réponse « {} » : forme inexploitable, mais la requête est bien arrivée
            client.plonger(["bonjour"])
        assert len(cible.requetes) == 1
        assert cible.requetes[0].get("authorization") == "Bearer cle-embeddings-fictive-0006"
    finally:
        cible.fermer()


# ======================================================================================= web-03 : `$` accepte « \n »
def test_empreinte_valide_refuse_un_saut_de_ligne_final():
    bonne = "a" * 64
    assert fichiers.empreinte_valide(bonne) is True
    assert fichiers.empreinte_valide(bonne + "\n") is False
    assert fichiers.empreinte_depuis_reference(fichiers.PREFIXE_REFERENCE + bonne) == bonne
    assert fichiers.empreinte_depuis_reference(fichiers.PREFIXE_REFERENCE + bonne + "\n") is None


# ======================================================================================= web-04 : journal d'accès
def _enregistrement(cible: str) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:50000", "GET", cible, "1.1", 200), None)


@pytest.mark.parametrize("cible", [
    "/console/direction/decision?question=Faut-il+licencier+Marc+Tremblay&reference=2026-10-28T13:00:00Z",
    "/console/memoire?module=M5&task=cl%C3%A9+de+Tremblay+Construction&files=docs%2Fsecret.md",
    "/console/memoire?task=reprendre+le+litige+Gagnon",
    "/console/memoire?files=docs%2Fsecret.md",
])
def test_le_journal_d_acces_ne_porte_pas_un_texte_libre_saisi_par_l_utilisateur(cible):
    enregistrement = _enregistrement(cible)
    assert MasquerRecherche().filter(enregistrement)
    ligne = enregistrement.args[2]
    for fragment in ("Tremblay", "licencier", "Gagnon", "secret.md", "litige"):
        assert fragment not in ligne, ligne


def test_le_journal_d_acces_garde_les_requetes_sans_texte_libre():
    enregistrement = _enregistrement("/console/crm/cedule?debut_semaine=2026-11-02")
    assert MasquerRecherche().filter(enregistrement)
    assert enregistrement.args[2] == "/console/crm/cedule?debut_semaine=2026-11-02"
