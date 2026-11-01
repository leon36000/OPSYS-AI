"""Client d'API OAuth : 401 puis rafraîchissement, 429 + Retry-After, 5xx, liens hors hôte, appels non idempotents,
et aucun secret dans les erreurs. Doubles de réseau ; stockage de jetons en mémoire (le coffre est testé ailleurs)."""

from __future__ import annotations

import logging

import courriel_doubles as dbl
import pytest

from opsys.courriel_connecteurs.client_oauth import ClientApi, GestionnaireJetons
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.courriel_connecteurs.jetons import JeuJetons
from opsys.courriel_connecteurs.oauth import ServiceOAuth, config_gmail
from opsys.courriel_connecteurs.transport import ErreurTransport, ReponseHttp, RequeteHttp
from opsys.secrets_coffre import masquage

FICTIF = True
URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class Montage:
    def __init__(self, *, rotation=False):
        self.horloge = dbl.Horloge()
        self.gmail = dbl.FauxGmail()
        self.oauth = dbl.FauxOAuth("oauth2.googleapis.com", self.horloge, scope_accorde=SCOPE, rotation=rotation)
        self.oauth.cibles = [self.gmail]
        self.transport = dbl.Aiguilleur()
        self.transport.ajouter(self.gmail.HOTE, self.gmail)
        self.transport.ajouter(self.oauth.HOTE, self.oauth)
        service = ServiceOAuth(
            config_gmail(client_id="c", redirect_uri="https://opsys.example.test/cb"),
            self.transport,
            lambda: b"k" * 40,
            horloge=self.horloge,
        )
        self.oauth.refresh_valides.add("refresh-initial-fictif")
        self.gmail.tokens_valides.add("acces-initial-fictif")
        self.stockage = dbl.StockageJetonsMemoire()
        self.stockage.ecrire(
            "n",
            JeuJetons("acces-initial-fictif", "refresh-initial-fictif", int(self.horloge.t) + 3600, frozenset({SCOPE})),
            service="google",
        )
        self.evenements = []
        self.jetons = GestionnaireJetons(
            "n",
            self.stockage,
            service,
            usage="lecture",
            service="google",
            horloge=self.horloge,
            rapport=lambda n, d: self.evenements.append((n, dict(d))),
        )
        self.client = ClientApi(
            self.transport,
            self.jetons,
            hotes=frozenset({self.gmail.HOTE}),
            dormir=self.horloge.dormir,
            horloge=self.horloge,
            rapport=lambda n, d: self.evenements.append((n, dict(d))),
        )


@pytest.fixture
def m():
    return Montage()


def test_requete_ordinaire_porte_le_jeton_sans_le_journaliser(m):
    assert m.client.json("GET", URL)["emailAddress"] == m.gmail.adresse
    envoyee = m.transport.requetes[-1]
    assert envoyee.entetes["Authorization"] == "Bearer acces-initial-fictif"
    assert "acces-initial-fictif" not in repr(envoyee) and "•••" in repr(envoyee)


def test_401_declenche_un_rafraichissement_puis_rejoue(m):
    m.gmail.tokens_valides = set()  # le jeton a été invalidé chez le fournisseur
    m.oauth.cibles = [m.gmail]
    assert m.client.json("GET", URL)["emailAddress"]
    assert m.oauth.emis == 1 and m.stockage.ecritures == ["n", "n"]
    assert m.stockage.lire("n").access_token == m.oauth.dernier_acces


def test_deuxieme_401_apres_rafraichissement_est_un_refus(m):
    m.gmail.scripter(dbl._json(401, {"error": "x"}), dbl._json(401, {"error": "x"}))
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", URL)
    assert (
        exc.value.code == "REJ-COURRIEL-AUTH-REFUSEE" and m.oauth.emis == 1
    )  # un seul rafraîchissement, pas de boucle
    assert ("auth.refusee", {}) in m.evenements


def test_429_retry_after_en_secondes_attend_puis_reussit(m):
    m.gmail.scripter(dbl.reponse_429("3"))
    assert m.client.json("GET", URL)
    assert m.horloge.sommeils == [3.0]


def test_429_retry_after_en_date_http(m):
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    date = format_datetime(datetime.fromtimestamp(m.horloge.t, UTC) + timedelta(seconds=7), usegmt=True)
    m.gmail.scripter(dbl.reponse_429(date))
    m.client.json("GET", URL)
    assert 6.0 <= m.horloge.sommeils[0] <= 8.0


def test_429_sans_retry_after_attente_exponentielle_bornee(m):
    m.gmail.scripter(*[ReponseHttp(429, {}, b"{}")] * 3)
    m.client.json("GET", URL)
    assert m.horloge.sommeils == [2.0, 4.0, 8.0]


def test_429_attente_demandee_trop_longue_est_un_refus_reprenable_qui_dit_quand(m):
    m.gmail.scripter(dbl.reponse_429("600"))
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", URL)
    assert exc.value.code == "REJ-COURRIEL-LIMITE-DEBIT" and exc.value.reprenable and exc.value.reessayer_apres_s == 600
    assert m.horloge.sommeils == []  # on n'attend pas dix minutes dans le fil appelant


def test_429_persistant_epuise_les_tentatives(m):
    m.gmail.scripter(*[dbl.reponse_429("1")] * 10)
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", URL)
    assert exc.value.code == "REJ-COURRIEL-LIMITE-DEBIT" and len(m.horloge.sommeils) == 4


def test_403_limite_de_debit_gmail_traite_comme_un_429(m):
    m.gmail.scripter(dbl.reponse_403_debit())
    assert m.client.json("GET", URL)
    assert len(m.horloge.sommeils) == 1


def test_403_ordinaire_est_un_refus_de_permission(m):
    m.gmail.scripter(dbl._json(403, {"error": {"errors": [{"reason": "forbidden"}]}}))
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", URL)
    assert exc.value.code == "REJ-COURRIEL-PERMISSION-REFUSEE" and "forbidden" in exc.value.detail


def test_5xx_reprises_avec_attente_exponentielle_puis_succes(m):
    m.gmail.scripter(dbl.reponse_5xx(500), dbl.reponse_5xx(502), dbl.reponse_5xx(503))
    assert m.client.json("GET", URL)
    assert m.horloge.sommeils == [2.0, 4.0, 8.0]


def test_5xx_persistant_fournisseur_indisponible_reprenable(m):
    m.gmail.scripter(*[dbl.reponse_5xx(500)] * 10)
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", URL)
    assert exc.value.code == "REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE" and exc.value.reprenable


def test_panne_de_transport_reprise_puis_refus_reseau(m):
    m.gmail.scripter(ErreurTransport("delai"), ErreurTransport("delai"))
    assert m.client.json("GET", URL)
    m.gmail.scripter(*[ErreurTransport("connexion")] * 10)
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", URL)
    assert exc.value.code == "REJ-COURRIEL-RESEAU" and exc.value.reprenable


def test_exception_inattendue_du_transport_ne_fuit_pas_son_message(m):
    secret = "Bearer acces-initial-fictif sur https://exemple.test/?token=SECRET123"
    m.gmail.scripter(RuntimeError(secret))
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", URL)
    assert "SECRET123" not in str(exc.value) and "acces-initial" not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_appel_non_idempotent_pas_de_reprise_sur_5xx_ni_panne(m):
    m.gmail.scripter(dbl.reponse_5xx(500))
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("POST", URL, json_corps={}, idempotente=False)
    assert exc.value.code == "REJ-COURRIEL-FOURNISSEUR-INDISPONIBLE" and not exc.value.reprenable
    assert len(m.gmail.requetes) == 1 and m.horloge.sommeils == []
    m.gmail.scripter(ErreurTransport("delai"))
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("POST", URL, json_corps={}, idempotente=False)
    assert exc.value.code == "REJ-COURRIEL-RESEAU" and not exc.value.reprenable


def test_appel_non_idempotent_429_non_traite_reprenable(m):
    m.gmail.scripter(dbl.reponse_429("30"))
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("POST", URL, json_corps={}, idempotente=False)
    assert exc.value.code == "REJ-COURRIEL-LIMITE-DEBIT" and exc.value.reessayer_apres_s == 30


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.test/gmail/v1/users/me/profile",
        "http://gmail.googleapis.com/gmail/v1/users/me/profile",
        "https://gmail.googleapis.com.evil.example.test/x",
        "https://user:mdp@gmail.googleapis.com/x",
        "https://gmail.googleapis.com:8443/x",
        "https://gmail.googleapis.com@evil.example.test/x",
        "ftp://gmail.googleapis.com/x",
        "//gmail.googleapis.com/x",
    ],
)
def test_url_hors_hote_autorise_refusee_avant_tout_envoi(m, url):
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", url)
    assert exc.value.code == "REJ-COURRIEL-LIEN-NON-AUTORISE" and m.transport.requetes == []


def test_erreur_http_ne_recopie_jamais_le_corps_de_la_reponse(m):
    m.gmail.scripter(ReponseHttp(400, {}, b'{"error":{"message":"Objet: facture de Jean Tremblay 12 500 $"}}'))
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", URL)
    assert "Tremblay" not in str(exc.value) and exc.value.code == "REJ-COURRIEL-REQUETE-INVALIDE"


def test_404_et_reponse_non_json(m):
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", "https://gmail.googleapis.com/gmail/v1/users/me/inconnu")
    assert exc.value.code == "REJ-COURRIEL-INTROUVABLE"
    m.gmail.scripter(ReponseHttp(200, {}, b"<html>pas du json</html>"))
    with pytest.raises(ErreurCourriel) as exc:
        m.client.json("GET", URL)
    assert exc.value.code == "REJ-COURRIEL-REPONSE-INVALIDE"


def test_jetons_masques_dans_les_journaux_pendant_l_appel(m, caplog):
    masquage.installer()

    class Espion:
        def envoyer(self, requete: RequeteHttp):
            logging.getLogger("test").warning("requête avec %s", requete.entetes["Authorization"])
            return m.gmail.traiter(requete)

    m.client._transport = Espion()
    with caplog.at_level(logging.WARNING):
        m.client.json("GET", URL)
    assert "acces-initial-fictif" not in caplog.text and "•••" in caplog.text


def test_rafraichissement_proactif_dans_la_marge_d_expiration(m):
    m.horloge.t += 3600 - 59
    m.client.json("GET", URL)
    assert m.oauth.emis == 1
    assert ("jeton.rafraichi", {"rotation_refresh": False}) in m.evenements


def test_deux_instances_un_seul_rafraichissement_quand_l_autre_a_deja_fait(m):
    """Un autre processus a rafraîchi et écrit dans le coffre : on relit avant d'appeler le fournisseur."""
    m.horloge.t += 4000
    m.stockage.ecrire(
        "n",
        JeuJetons("acces-d-un-autre", "refresh-initial-fictif", int(m.horloge.t) + 3000, frozenset({SCOPE})),
        service="google",
    )
    m.jetons._jeu = JeuJetons(
        "acces-initial-fictif", "refresh-initial-fictif", int(m.horloge.t) - 10, frozenset({SCOPE})
    )
    m.gmail.tokens_valides = {"acces-d-un-autre"}
    m.client.json("GET", URL)
    assert m.oauth.emis == 0
