"""Adaptateur OSRM du port FournisseurMatrice (PLAN T4.1-b, R15 §2 palier 1).

Contre un FAUX serveur HTTP local (``http.server`` dans un fil) : aucun vrai OSRM, aucun accès hors de
127.0.0.1. Les points sont fictifs (fictif: true). Les matrices de réponse viennent de l'exemple de la
documentation d'OSRM (service `table`, https://project-osrm.org/docs/v5.24.0/api/#table-service).
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from m4_field_ops import distances, distances_osrm, verdicts

PARAMS = {"facteur_detour_milliemes": 1300, "vitesse_moyenne_kmh": 50, "marge_par_trajet_secondes": 600}

# fictif: true
POINTS = [
    {"id": "b-repentigny", "latitude_microdeg": 45742000, "longitude_microdeg": -73450000},
    {"id": "a-joliette", "latitude_microdeg": 46020000, "longitude_microdeg": -73440000},
    {"id": "c-terrebonne", "latitude_microdeg": 45700000, "longitude_microdeg": -73640000},
]

# Exemple de la documentation OSRM (3×3, décimaux, matrice asymétrique).
DUREES_DOC = [[0, 192.6, 382.8], [199, 0, 283.9], [344.7, 222.3, 0]]
DISTANCES_DOC = [[0, 1886.89, 3791.3], [1824, 0, 2838.09], [3275.36, 2361.73, 0]]
# Arrondis attendus : secondes au plafond, mètres au plus proche.
SECONDES_BRUTES = [[0, 193, 383], [199, 0, 284], [345, 223, 0]]
METRES_BRUTS = [[0, 1887, 3791], [1824, 0, 2838], [3275, 2362, 0]]


def _corps(durees=DUREES_DOC, distances_=DISTANCES_DOC, code="Ok", **supplement):
    corps = {"code": code, "durations": durees, "distances": distances_,
             "sources": [{"name": "rue secrète", "hint": "abc", "location": [0.0, 0.0]}]}
    corps.update(supplement)
    return json.dumps(corps).encode("utf-8")


class ServeurFactice:
    """Faux sidecar OSRM : consigne les chemins reçus, répond selon ``reponse`` (statut, corps, entêtes)."""

    def __init__(self):
        self.requetes = []
        self.reponse = (200, _corps(), {"Content-Type": "application/json"})
        self.bloque = threading.Event()
        self.attendre = False
        fabrique = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def do_GET(self):
                fabrique.requetes.append(self.path)
                if fabrique.attendre:
                    fabrique.bloque.wait(15)
                statut, corps, entetes = fabrique.reponse
                self.send_response(statut)
                for cle, valeur in entetes.items():
                    self.send_header(cle, valeur)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *args):
                return None

        class Serveur(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                return None  # un client qui a rompu (délai dépassé) n'est pas une erreur du test

        self.serveur = Serveur(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"
        self.fil = threading.Thread(target=self.serveur.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.fil.start()

    def arreter(self):
        self.bloque.set()
        self.serveur.shutdown()
        self.serveur.server_close()
        self.fil.join(5)


@pytest.fixture
def serveur():
    faux = ServeurFactice()
    yield faux
    faux.arreter()


@pytest.fixture
def autre_serveur():
    """Deuxième faux serveur : cible d'une redirection, qui ne doit JAMAIS être joint."""
    faux = ServeurFactice()
    yield faux
    faux.arreter()


def _fournisseur(url, **kwargs):
    fournisseur, verdict = distances_osrm.creer_fournisseur_osrm(url, "quebec-fictif-1", **kwargs)
    assert verdict is None
    return fournisseur


def _port_ferme():
    """Un port de boucle locale où personne n'écoute."""
    with socket.socket() as sonde:
        sonde.bind(("127.0.0.1", 0))
        return sonde.getsockname()[1]


# ---------------------------------------------------------------------------
# Configuration : sidecar LOCAL seulement
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "http://127.0.0.1:5000",
    "http://127.0.0.1:5000/",
    "http://localhost:5000",
    "http://[::1]:5000",
    "http://10.1.2.3:5000",
    "http://172.16.0.9:5000",
    "http://192.168.1.20:5000",
    "http://osrm:5000",
    "https://osrm-routage:5000",
])
def test_urls_de_sidecar_local_acceptees(url):
    fournisseur, verdict = distances_osrm.creer_fournisseur_osrm(url, "quebec-260927")
    assert verdict is None
    assert isinstance(fournisseur, distances.FournisseurMatrice)


@pytest.mark.parametrize("url", [
    "http://router.project-osrm.org",
    "https://example.com",
    "http://8.8.8.8:5000",
    "http://osrm.exemple.ca:5000",
    "http://169.254.169.254",
    "http://0.0.0.0:5000",
    "http://[2606:4700:4700::1111]:5000",
    "http://[::ffff:8.8.8.8]:5000",
    "http://user:secret@127.0.0.1:5000",
    "ftp://127.0.0.1:5000",
    "http://127.0.0.1:5000/table/v1",
    "http://127.0.0.1:5000?x=1",
    "http://127.0.0.1:99999",
    "127.0.0.1:5000",
    "",
    None,
    5000,
])
def test_urls_non_locales_ou_mal_formees_refusees_a_la_configuration(url):
    fournisseur, verdict = distances_osrm.creer_fournisseur_osrm(url, "quebec-260927")
    assert fournisseur is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert verdicts.est_verdict(verdict["code"])
    assert "url_base" in verdict["detail"]
    assert "secret" not in verdict["detail"]


@pytest.mark.parametrize(("nom", "valeur"), [
    ("version_donnees", ""),
    ("version_donnees", None),
    ("version_donnees", "avec espace"),
    ("version_donnees", "x" * 65),
    ("profil", "Driving"),
    ("profil", "../etc"),
    ("profil", ""),
    ("delai_secondes", 0),
    ("delai_secondes", 31),
    ("delai_secondes", 2.5),
    ("delai_secondes", True),
])
def test_configuration_invalide_est_refusee_par_un_verdict(nom, valeur):
    arguments = {"url_base": "http://127.0.0.1:5000", "version_donnees": "quebec-260927",
                 "profil": "driving", "delai_secondes": 5}
    arguments[nom] = valeur
    fournisseur, verdict = distances_osrm.creer_fournisseur_osrm(**arguments)
    assert fournisseur is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert nom in verdict["detail"]


def test_la_version_des_donnees_routieres_est_obligatoire_pas_de_valeur_par_defaut():
    with pytest.raises(TypeError):
        distances_osrm.creer_fournisseur_osrm("http://127.0.0.1:5000")


def test_le_constructeur_direct_valide_aussi():
    with pytest.raises(ValueError, match="url_base"):
        distances_osrm.FournisseurOsrm("http://example.com", "quebec-260927")
    assert distances_osrm.FournisseurOsrm("http://127.0.0.1:5000", "quebec-260927").descripteur() == {
        "mode_distance": "osrm_table", "fournisseur": "osrm", "api": "table/v1",
        "profil": "driving", "version_donnees": "quebec-260927",
    }


def test_la_creation_n_ouvre_aucune_connexion(monkeypatch):
    def interdit(*args, **kwargs):
        raise AssertionError("connexion à la création")

    monkeypatch.setattr(socket.socket, "connect", interdit)
    fournisseur, verdict = distances_osrm.creer_fournisseur_osrm("http://127.0.0.1:5000", "quebec-260927")
    assert verdict is None
    assert fournisseur.descripteur()["mode_distance"] == "osrm_table"


# ---------------------------------------------------------------------------
# Requête émise et lecture de la réponse
# ---------------------------------------------------------------------------
def test_requete_get_table_avec_coordonnees_lon_lat_triees_par_identifiant(serveur):
    fournisseur = _fournisseur(serveur.url, profil="driving")
    trajets, verdict = fournisseur.trajets(POINTS)  # entrée désordonnée : l'adaptateur trie
    assert verdict is None
    assert serveur.requetes == [
        "/table/v1/driving/-73.440000,46.020000;-73.450000,45.742000;-73.640000,45.700000"
        "?annotations=duration,distance"
    ]
    assert "fallback_speed" not in serveur.requetes[0]  # jamais : OSRM inventerait une ligne droite
    assert trajets == {"metres": METRES_BRUTS, "secondes": SECONDES_BRUTES}


def test_formatage_exact_des_coordonnees_sans_flottant(serveur):
    points = [
        {"id": "a", "latitude_microdeg": -500_000, "longitude_microdeg": 5},
        {"id": "b", "latitude_microdeg": 1, "longitude_microdeg": -1_000_000},
        {"id": "c", "latitude_microdeg": 89_999_999, "longitude_microdeg": -179_999_999},
    ]
    _fournisseur(serveur.url, profil="bike").trajets(points)
    assert serveur.requetes[0].startswith(
        "/table/v1/bike/0.000005,-0.500000;-1.000000,0.000001;-179.999999,89.999999?"
    )


def test_arrondis_secondes_au_plafond_metres_au_plus_proche_demi_vers_le_haut(serveur):
    serveur.reponse = (200, _corps(
        durees=[[0, 0.1], [10.0, 0]], distances_=[[0, 0.5], [1.49, 0]],
    ), {})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS[:2])
    assert verdict is None
    assert trajets == {"metres": [[0, 1], [1, 0]], "secondes": [[0, 1], [10, 0]]}
    assert all(type(v) is int for ligne in trajets["metres"] + trajets["secondes"] for v in ligne)


def test_les_champs_inconnus_et_les_waypoints_sont_ignores(serveur):
    serveur.reponse = (200, _corps(data_version="2026-09-27T00:00:00Z", extra={"a": 1}), {})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS)
    assert verdict is None
    assert trajets["metres"] == METRES_BRUTS


def test_les_entiers_json_sont_acceptes_comme_les_decimaux(serveur):
    serveur.reponse = (200, _corps(durees=[[0, 5], [7, 0]], distances_=[[0, 100], [120, 0]]), {})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS[:2])
    assert verdict is None
    assert trajets == {"metres": [[0, 100], [120, 0]], "secondes": [[0, 5], [7, 0]]}


def test_points_invalides_refuses_avant_toute_requete(serveur):
    trajets, verdict = _fournisseur(serveur.url).trajets([])
    assert trajets is None
    assert verdict["code"] == "REJ-CHAMP-VIDE"
    assert serveur.requetes == []


# ---------------------------------------------------------------------------
# Toute erreur devient un verdict
# ---------------------------------------------------------------------------
def test_connexion_refusee_est_un_verdict_fournisseur_indisponible():
    fournisseur = _fournisseur(f"http://127.0.0.1:{_port_ferme()}")
    trajets, verdict = fournisseur.trajets(POINTS)
    assert trajets is None
    assert verdict["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert "injoignable" in verdict["detail"]
    assert "ConnectionRefusedError" in verdict["detail"]


def test_delai_depasse_est_un_verdict_borne_dans_le_temps(serveur):
    serveur.attendre = True
    fournisseur = _fournisseur(serveur.url, delai_secondes=1)
    trajets, verdict = fournisseur.trajets(POINTS)
    serveur.bloque.set()
    assert trajets is None
    assert verdict["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert "délai dépassé" in verdict["detail"]
    assert "1 s" in verdict["detail"]


@pytest.mark.parametrize("statut", [500, 502, 503, 404, 302])
def test_statut_http_non_200_est_un_verdict_fournisseur_indisponible(serveur, statut):
    serveur.reponse = (statut, b"erreur du sidecar", {"Location": "http://127.0.0.1:1/ailleurs"})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS)
    assert trajets is None
    assert verdict["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert f"HTTP {statut}" in verdict["detail"]


@pytest.mark.parametrize("code_osrm", ["TooBig", "InvalidQuery", "InvalidValue", "NoTable", "NotImplemented"])
def test_erreur_osrm_http_400_est_un_verdict_avec_le_code_osrm(serveur, code_osrm):
    serveur.reponse = (400, json.dumps({"code": code_osrm, "message": "coordonnée 45.7,-73.4 refusée"}).encode(), {})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS)
    assert trajets is None
    assert verdict["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert f"code {code_osrm}" in verdict["detail"]
    assert "coordonnée" not in verdict["detail"]  # le message libre d'OSRM n'est jamais recopié


def test_code_osrm_autre_que_ok_avec_statut_200_est_un_refus(serveur):
    serveur.reponse = (200, json.dumps({"code": "TooBig", "message": "trop"}).encode(), {})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS)
    assert trajets is None
    assert verdict["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert "TooBig" in verdict["detail"]


@pytest.mark.parametrize("corps", [
    {"code": 42},
    {"code": "Ok\nInjection"},
    {},
])
def test_code_osrm_illisible_est_inconnu_pas_recopie(serveur, corps):
    serveur.reponse = (400, json.dumps(corps).encode(), {})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS)
    assert trajets is None
    assert "code inconnu" in verdict["detail"]


def test_no_segment_est_un_verdict_trajet_introuvable_pas_une_panne(serveur):
    for reponse in ((400, json.dumps({"code": "NoSegment", "message": "point 2"}).encode(), {}),
                    (200, json.dumps({"code": "NoSegment"}).encode(), {})):
        serveur.reponse = reponse
        trajets, verdict = _fournisseur(serveur.url).trajets(POINTS)
        assert trajets is None
        assert verdict["code"] == distances.CODE_TRAJET_INTROUVABLE
        assert "NoSegment" in verdict["detail"]


@pytest.mark.parametrize("corps", [
    b"",
    b"pas du json",
    b"\xff\xfe\x00",
    b"[1, 2, 3]",
    b'"Ok"',
    b'{"code": "Ok", "durations": [[0, NaN], [1, 0]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, Infinity], [1, 0]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": "vide", "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, 1]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, 1], [1]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, 1, 2], [1, 0, 3]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, "1"], [1, 0]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, true], [1, 0]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, [1]], [1, 0]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, -1], [1, 0]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, 1], [1, 0]], "distances": [[0, -0.5], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, 1e30], [1, 0]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[3, 1], [1, 0]], "distances": [[0, 1], [1, 0]]}',
    b'{"code": "Ok", "durations": [[0, 1], [1, 0]], "distances": [[0, 1], [1, 2.5]]}',
])
def test_reponses_malformees_sont_un_verdict_reponse_invalide(serveur, corps):
    serveur.reponse = (200, corps, {})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS[:2])
    assert trajets is None
    assert verdict["code"] == distances.CODE_REPONSE_INVALIDE
    assert verdict["detail"] != ""


def test_cellule_null_est_un_trajet_introuvable_avec_les_identifiants(serveur):
    serveur.reponse = (200, _corps(
        durees=[[0, None, 5], [3, 0, 4], [None, 2, 0]], distances_=[[0, None, 5], [3, 0, 4], [None, 2, 0]],
    ), {})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS)
    assert trajets is None
    assert verdict["code"] == distances.CODE_TRAJET_INTROUVABLE
    assert "a-joliette->b-repentigny" in verdict["detail"]
    assert "c-terrebonne->a-joliette" in verdict["detail"]
    assert "2 trajet(s)" in verdict["detail"]


def test_trop_de_cellules_null_sont_resumees(serveur):
    n = 4
    grille = [[0 if i == j else None for j in range(n)] for i in range(n)]
    serveur.reponse = (200, _corps(durees=grille, distances_=grille), {})
    points = [{"id": f"p{i}", "latitude_microdeg": 45_000_000 + i, "longitude_microdeg": -73_000_000} for i in range(n)]
    trajets, verdict = _fournisseur(serveur.url).trajets(points)
    assert trajets is None
    assert "12 trajet(s)" in verdict["detail"]
    assert verdict["detail"].count("->") == 5
    assert "..." in verdict["detail"]


def test_reponse_trop_volumineuse_est_refusee_sans_tout_lire(serveur, monkeypatch):
    monkeypatch.setattr(distances_osrm, "TAILLE_MAX_REPONSE", 200)
    serveur.reponse = (200, _corps() + b" " * 500, {})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS)
    assert trajets is None
    assert verdict["code"] == distances.CODE_REPONSE_INVALIDE
    assert "200 octets" in verdict["detail"]


def test_une_redirection_n_est_jamais_suivie(serveur, autre_serveur):
    """Suivre la redirection enverrait les coordonnées d'un client ailleurs : on rend un verdict."""
    serveur.reponse = (302, b"", {"Location": autre_serveur.url + "/table/v1/driving/x"})
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS)
    assert trajets is None
    assert verdict["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert "HTTP 302" in verdict["detail"]
    assert autre_serveur.requetes == []


def test_les_mandataires_de_l_environnement_sont_ignores(serveur, monkeypatch):
    """Un http_proxy inutilisable n'empêche pas le sidecar local, et n'y voit pas passer les coordonnées."""
    port_mort = _port_ferme()
    for nom in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(nom, f"http://127.0.0.1:{port_mort}")
    for nom in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(nom, raising=False)
    trajets, verdict = _fournisseur(serveur.url).trajets(POINTS)
    assert verdict is None
    assert trajets["metres"] == METRES_BRUTS
    assert len(serveur.requetes) == 1


def _serveur_brut(comportement):
    """Serveur TCP brut, une connexion : ``comportement(connexion)`` décide quoi envoyer avant de fermer."""
    ecoute = socket.socket()
    ecoute.bind(("127.0.0.1", 0))
    ecoute.listen(1)

    def servir():
        connexion, _ = ecoute.accept()
        with connexion:
            connexion.recv(65536)
            comportement(connexion)
        ecoute.close()

    fil = threading.Thread(target=servir, daemon=True)
    fil.start()
    return f"http://127.0.0.1:{ecoute.getsockname()[1]}", fil


def test_connexion_coupee_sans_reponse_est_un_verdict():
    url, fil = _serveur_brut(lambda connexion: None)
    trajets, verdict = _fournisseur(url).trajets(POINTS)
    fil.join(5)
    assert trajets is None
    assert verdict["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert "échec de la requête OSRM" in verdict["detail"]


def test_corps_tronque_est_un_verdict():
    """Content-Length promet plus d'octets que le serveur n'en envoie : JSON coupé, donc réponse invalide."""
    def tronque(connexion):
        connexion.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5000\r\nContent-Type: application/json\r\n\r\n{\"code\"")

    url, fil = _serveur_brut(tronque)
    trajets, verdict = _fournisseur(url).trajets(POINTS)
    fil.join(5)
    assert trajets is None
    assert verdict["code"] == distances.CODE_REPONSE_INVALIDE
    assert "JSON invalide" in verdict["detail"]


def test_ligne_de_statut_invalide_est_un_verdict():
    url, fil = _serveur_brut(lambda connexion: connexion.sendall(b"ceci n'est pas du HTTP\r\n\r\n"))
    trajets, verdict = _fournisseur(url).trajets(POINTS)
    fil.join(5)
    assert trajets is None
    assert verdict["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE


def test_delai_de_connexion_enveloppe_par_urllib_est_aussi_un_delai_depasse(monkeypatch):
    class Ouvreur:
        def open(self, requete, timeout):
            raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(distances_osrm, "_OUVREUR", Ouvreur())
    trajets, verdict = _fournisseur("http://127.0.0.1:5000", delai_secondes=2).trajets(POINTS)
    assert trajets is None
    assert verdict["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert verdict["detail"] == "sidecar OSRM sans réponse en 2 s (délai dépassé)"


def test_resolution_de_nom_impossible_est_un_verdict():
    fournisseur = _fournisseur("http://service-osrm-inexistant:5000")
    trajets, verdict = fournisseur.trajets(POINTS)
    assert trajets is None
    assert verdict["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE


# ---------------------------------------------------------------------------
# Intégration avec obtenir_matrice : matrice routière, repli explicite, pas de repli sur donnée à corriger
# ---------------------------------------------------------------------------
def test_matrice_routiere_osrm_complete_avec_marge_et_empreinte(serveur):
    fournisseur = _fournisseur(serveur.url)
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, fournisseur)
    assert verdict is None
    assert matrice["mode_distance"] == "osrm_table"
    assert matrice["mode_bride"] is False
    assert matrice["repli"] is None
    assert matrice["ids"] == ["a-joliette", "b-repentigny", "c-terrebonne"]
    assert matrice["metres"] == METRES_BRUTS  # asymétrique : gardée telle quelle
    assert matrice["secondes"] == [
        [0, 193 + 600, 383 + 600], [199 + 600, 0, 284 + 600], [345 + 600, 223 + 600, 0],
    ]
    assert matrice["parametres"] == {
        "marge_par_trajet_secondes": 600,
        "fournisseur": {"fournisseur": "osrm", "api": "table/v1", "profil": "driving",
                        "version_donnees": "quebec-fictif-1"},
    }
    assert distances.verifier_matrice(matrice) == (True, "")
    assert len(serveur.requetes) == 1
    # l'URL du sidecar est de la configuration locale : elle n'entre ni dans la matrice ni dans l'empreinte
    assert serveur.url not in json.dumps(matrice)


def test_meme_reponse_meme_empreinte_et_les_donnees_routieres_font_changer_l_empreinte(serveur):
    premiere, _ = distances.obtenir_matrice(POINTS, PARAMS, _fournisseur(serveur.url))
    seconde, _ = distances.obtenir_matrice(list(reversed(POINTS)), PARAMS, _fournisseur(serveur.url))
    assert premiere["empreinte"] == seconde["empreinte"]
    autres_donnees, _ = distances.obtenir_matrice(
        POINTS, PARAMS, distances_osrm.FournisseurOsrm(serveur.url, "quebec-fictif-2"),
    )
    assert autres_donnees["empreinte"] != premiere["empreinte"]
    assert autres_donnees["metres"] == premiere["metres"]


def test_sidecar_indisponible_replie_sur_le_palier_0_avec_badge_et_marque():
    fournisseur = _fournisseur(f"http://127.0.0.1:{_port_ferme()}")
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, fournisseur)
    assert verdict is None
    assert matrice["mode_distance"] == "haversine_detour"
    assert matrice["mode_bride"] is True
    assert matrice["repli"]["depuis"] == "osrm_table"
    assert matrice["repli"]["code"] == distances.CODE_FOURNISSEUR_INDISPONIBLE
    assert "injoignable" in matrice["repli"]["detail"]
    sans_repli, _ = distances.matrice_palier0(POINTS, PARAMS)
    assert matrice["metres"] == sans_repli["metres"]
    assert matrice["secondes"] == sans_repli["secondes"]
    assert matrice["empreinte"] != sans_repli["empreinte"]
    assert distances.verifier_matrice(matrice) == (True, "")


def test_la_marque_de_repli_est_reproductible_donc_l_empreinte_aussi():
    """Aucun message d'exception dans le détail : deux pannes identiques donnent la même empreinte."""
    fournisseur = _fournisseur(f"http://127.0.0.1:{_port_ferme()}")
    premiere, _ = distances.obtenir_matrice(POINTS, PARAMS, fournisseur)
    seconde, _ = distances.obtenir_matrice(POINTS, PARAMS, fournisseur)
    assert premiere["repli"] == seconde["repli"]
    assert premiere["empreinte"] == seconde["empreinte"]


@pytest.mark.parametrize("reponse", [
    (500, b"boum", {}),
    (200, b"pas du json", {}),
    (200, b'{"code": "Ok", "durations": [[0]], "distances": [[0]]}', {}),
    (400, b'{"code": "TooBig"}', {}),
])
def test_reponse_inutilisable_replie_sur_le_palier_0_explicitement(serveur, reponse):
    serveur.reponse = reponse
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, _fournisseur(serveur.url))
    assert verdict is None
    assert matrice["mode_bride"] is True
    assert matrice["repli"]["depuis"] == "osrm_table"
    assert matrice["repli"]["code"] in {distances.CODE_FOURNISSEUR_INDISPONIBLE, distances.CODE_REPONSE_INVALIDE}
    assert matrice["metres"] == distances.matrice_palier0(POINTS, PARAMS)[0]["metres"]


def test_delai_depasse_replie_sur_le_palier_0(serveur):
    serveur.attendre = True
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, _fournisseur(serveur.url, delai_secondes=1))
    serveur.bloque.set()
    assert verdict is None
    assert matrice["mode_bride"] is True
    assert "délai dépassé" in matrice["repli"]["detail"]


def test_trajet_introuvable_n_est_pas_un_repli_c_est_une_donnee_a_corriger(serveur):
    serveur.reponse = (200, _corps(
        durees=[[0, None, 5], [3, 0, 4], [6, 2, 0]], distances_=[[0, None, 5], [3, 0, 4], [6, 2, 0]],
    ), {})
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, _fournisseur(serveur.url))
    assert matrice is None
    assert verdict["code"] == distances.CODE_TRAJET_INTROUVABLE
    serveur.reponse = (400, json.dumps({"code": "NoSegment"}).encode(), {})
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS, _fournisseur(serveur.url))
    assert matrice is None
    assert verdict["code"] == distances.CODE_TRAJET_INTROUVABLE


def test_parametres_absents_avec_osrm_refusent_avant_toute_requete(serveur):
    matrice, verdict = distances.obtenir_matrice(POINTS, {"vitesse_moyenne_kmh": 50}, _fournisseur(serveur.url))
    assert matrice is None
    assert verdict["code"] == "REJ-CHAMP-MANQUANT"
    assert serveur.requetes == []


def test_le_palier_0_par_defaut_n_appelle_jamais_le_serveur(serveur):
    matrice, verdict = distances.obtenir_matrice(POINTS, PARAMS)
    assert verdict is None
    assert matrice["mode_bride"] is True
    assert serveur.requetes == []
