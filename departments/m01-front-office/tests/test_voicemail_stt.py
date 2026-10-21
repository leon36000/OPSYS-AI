"""Parcours d'adaptation OpenAI-compatible vers l'import canonique M1 (audio fictif)."""

from __future__ import annotations

import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from m1_front_office import outils as outils_m1
from m1_front_office import voicemail_stt
from sqlalchemy import select

from opsys import stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_SORTANTS

TEXTE_FICTIF = "Bonjour, mes gouttières fuient à Laval."


class _ServeurSTT(BaseHTTPRequestHandler):
    mode = "success"
    modeles_disponibles = True
    requetes = []

    def do_GET(self):
        if not _ServeurSTT.modeles_disponibles:
            self.send_error(404)
            return
        corps = json.dumps({"data": [{"id": "whisper-local"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_POST(self):
        corps = self.rfile.read(int(self.headers["Content-Length"]))
        type_contenu = self.headers.get("Content-Type", "")
        _ServeurSTT.requetes.append((self.path, self.headers.get("Authorization"), type_contenu, corps))
        if self.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "/transcription-non-autorisee")
            self.end_headers()
            return
        if self.mode == "http_error":
            sortie, code = b'{"error":"PII leaked by provider: fake caller text"}', 503
        elif self.mode == "empty":
            sortie, code = b'{"text":"  "}', 200
        else:
            sortie, code = json.dumps({"text": TEXTE_FICTIF}).encode(), 200
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(sortie)))
        self.end_headers()
        self.wfile.write(sortie)

    def log_message(self, *_args):
        return


@pytest.fixture
def serveur_stt():
    _ServeurSTT.mode = "success"
    _ServeurSTT.modeles_disponibles = True
    _ServeurSTT.requetes = []
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), _ServeurSTT)
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    try:
        yield f"http://127.0.0.1:{serveur.server_port}/v1"
    finally:
        serveur.shutdown()
        fil.join(timeout=2)
        serveur.server_close()


@pytest.fixture
def capacites_m1(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm1-voicemail.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    taxonomie.enregistrer_zone_desservie(["Laval"])
    taxonomie.enregistrer_services(["gouttieres"])
    outils_m1.utiliser_stockage_durable()
    deps = charger_departements()
    capacites = Capacites({"m01-front-office": deps["m01-front-office"]}, stockage.transaction, memoire=False)
    try:
        yield capacites
    finally:
        outils_m1.reinitialiser_registre()
        stockage.liberer()


def _wav(path: Path, *, duree_s: int = 1) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * 8000 * duree_s)
    return path


def _args(**overrides):
    return {
        "source": "voicemail_fichier",
        "evenement_id": "event-vocal-fictif-001",
        "appel_id": "appel-vocal-fictif-001",
        "recu_le": "2026-09-30T12:00:00-04:00",
        "telephone": "+15145550142",
        "consentement_enregistrement": "accorde",
        **overrides,
    }


def _client(serveur_stt, **overrides):
    return voicemail_stt.ConfigurationSTT(
        base_url=serveur_stt,
        modele="whisper-local",
        local=True,
        **overrides,
    )


@pytest.mark.parametrize("delai", ["nan", "inf", "-inf", "121"])
def test_delai_configure_invalide_preserve_le_rappel_sans_requete(
    capacites_m1, serveur_stt, tmp_path, monkeypatch, delai
):
    monkeypatch.setenv(voicemail_stt.ENV_URL, serveur_stt)
    monkeypatch.setenv(voicemail_stt.ENV_MODELE, "whisper-local")
    monkeypatch.setenv(voicemail_stt.ENV_LOCAL, "1")
    monkeypatch.setenv(voicemail_stt.ENV_DELAI, delai)
    fichier = _wav(tmp_path / "appel-fictif.wav")
    resultat = voicemail_stt.transcrire_et_importer(
        fichier.read_bytes(), suffixe=".wav", capacites=capacites_m1, **_args()
    )
    assert resultat["statut"] == "refuse" and resultat["code"] == "REJ-STT-CONFIG"
    assert resultat["m1"]["ok"] is True
    assert resultat["m1"]["resultat"]["tache_rappel"]["transfert_id"]
    assert not _ServeurSTT.requetes


def test_redirection_stt_refusee_sans_fausse_transcription(capacites_m1, serveur_stt, tmp_path):
    _ServeurSTT.mode = "redirect"
    fichier = _wav(tmp_path / "appel-fictif.wav")
    resultat = voicemail_stt.transcrire_et_importer(
        fichier.read_bytes(),
        suffixe=".wav",
        capacites=capacites_m1,
        configuration=_client(serveur_stt, cle_api="secret-stt-fictif"),
        **_args(),
    )
    assert resultat["statut"] == "refuse" and resultat["code"] == "REJ-STT-HTTP"
    assert resultat["m1"]["resultat"]["tache_rappel"]["transfert_id"]
    assert len(_ServeurSTT.requetes) == 1


def test_voicemail_stt_reel_local_publie_par_import_m1_canonique_et_rejouable(capacites_m1, serveur_stt, tmp_path):
    fichier = _wav(tmp_path / "appel-prive-fictif.wav")
    configuration = _client(serveur_stt)

    etat_connexion = configuration.verifier_connexion()
    resultat = voicemail_stt.transcrire_et_importer(
        fichier.read_bytes(), suffixe=".wav", capacites=capacites_m1, configuration=configuration, **_args()
    )

    assert etat_connexion == {
        "connecte": None,
        "modele": "whisper-local",
        "statut": "endpoint_rejoignable",
        "stt_verifie": False,
    }
    assert resultat["statut"] == "transcrit"
    assert resultat["transcription"]["caracteres"] == len(TEXTE_FICTIF)
    assert "texte" not in resultat["transcription"]
    assert resultat["m1"]["ok"] is True
    assert resultat["m1"]["resultat"]["transcription_conservee"] is True
    assert resultat["m1"]["resultat"]["traitement"]["decision"] == "TRANSMETTRE_M2"
    assert len(_ServeurSTT.requetes) == 1
    chemin, auth, contenu, corps = _ServeurSTT.requetes[0]
    assert chemin == "/v1/audio/transcriptions"
    assert auth is None
    assert "multipart/form-data" in contenu
    assert b'name="model"' in corps and b"whisper-local" in corps
    assert b'filename="voicemail.wav"' in corps and b"fake caller" not in corps
    with stockage.transaction() as cnx:
        evenements = (
            cnx.execute(select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie"))
            .mappings()
            .all()
        )
    assert len(evenements) == 1

    rejoue = voicemail_stt.transcrire_et_importer(
        fichier.read_bytes(), suffixe=".wav", capacites=capacites_m1, configuration=configuration, **_args()
    )
    assert rejoue["m1"] == resultat["m1"]
    with stockage.transaction() as cnx:
        evenements_apres = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie")
        ).all()
    assert len(evenements_apres) == 1


def test_route_modeles_absente_n_est_pas_un_prerequis_de_transcription(capacites_m1, serveur_stt, tmp_path):
    _ServeurSTT.modeles_disponibles = False
    configuration = _client(serveur_stt)
    etat = configuration.verifier_connexion()
    resultat = voicemail_stt.transcrire_et_importer(
        _wav(tmp_path / "appel-prive-fictif.wav").read_bytes(),
        suffixe=".wav",
        capacites=capacites_m1,
        configuration=configuration,
        **_args(),
    )

    assert etat == {
        "connecte": None,
        "modele": "whisper-local",
        "statut": "diagnostic_indisponible",
        "stt_verifie": False,
    }
    assert resultat["statut"] == "transcrit"
    assert len(_ServeurSTT.requetes) == 1


def test_endpoint_externe_sans_cle_est_signale_sans_envoyer_audio(capacites_m1, tmp_path):
    configuration = voicemail_stt.ConfigurationSTT(
        "https://stt.example.test/v1",
        "modele-configure",
        local=False,
    )
    # Ce diagnostic renvoie l'état de configuration sans tenter de requête réseau.
    etat = configuration.verifier_connexion()
    resultat = voicemail_stt.transcrire_et_importer(
        _wav(tmp_path / "appel-prive-fictif.wav").read_bytes(),
        suffixe=".wav",
        capacites=capacites_m1,
        configuration=configuration,
        consentement_transfert_externe="accorde",
        **_args(),
    )

    assert etat["statut"] == "identifiants_absents" and etat["stt_verifie"] is False
    assert resultat["statut"] == "refuse"
    assert resultat["code"] == "REJ-STT-IDENTIFIANTS"
    assert resultat["m1"]["resultat"]["transcription_conservee"] is False


def test_consentement_manquant_n_envoie_aucun_audio_et_importe_sans_transcription(capacites_m1, serveur_stt, tmp_path):
    resultat = voicemail_stt.transcrire_et_importer(
        b"",
        suffixe=".wav",
        capacites=capacites_m1,
        configuration=_client(serveur_stt),
        **_args(consentement_enregistrement=None),
    )

    assert resultat["statut"] == "refuse"
    assert resultat["code"] == "REJ-CONSENTEMENT-ENREGISTREMENT"
    assert resultat["m1"]["resultat"]["transcription_conservee"] is False
    assert _ServeurSTT.requetes == []


def test_absence_de_configuration_stt_preserve_le_voicemail_et_le_rappel(capacites_m1, monkeypatch):
    for nom in ("OPSYS_M1_STT_URL", "OPSYS_M1_STT_MODELE", "OPSYS_M1_STT_CLE", "OPSYS_M1_STT_LOCAL"):
        monkeypatch.delenv(nom, raising=False)
    resultat = voicemail_stt.transcrire_et_importer(
        b"audio non lu car aucun endpoint n'est configure",
        suffixe=".wav",
        capacites=capacites_m1,
        **_args(),
    )

    assert resultat["statut"] == "refuse"
    assert resultat["code"] == "REJ-STT-NON-CONFIGURE"
    assert resultat["m1"]["resultat"]["transcription_conservee"] is False
    assert resultat["m1"]["resultat"]["tache_rappel"]["statut"] == "ouvert"


def test_endpoint_externe_exige_un_consentement_de_transfert_distinct(capacites_m1, serveur_stt, tmp_path):
    resultat = voicemail_stt.transcrire_et_importer(
        _wav(tmp_path / "appel-prive-fictif.wav").read_bytes(),
        suffixe=".wav",
        capacites=capacites_m1,
        configuration=voicemail_stt.ConfigurationSTT(
            "https://stt.example.test/v1",
            "whisper-local",
            cle_api="secret-fictif",
            local=False,
        ),
        **_args(),
    )

    assert resultat["statut"] == "refuse"
    assert resultat["code"] == "REJ-CONSENTEMENT-TRANSFERT"
    assert resultat["m1"]["resultat"]["transcription_conservee"] is False
    assert _ServeurSTT.requetes == []


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("http_error", "REJ-STT-HTTP"),
        ("empty", "REJ-STT-REPONSE"),
    ],
)
def test_echec_ou_reponse_vide_ne_fabrique_pas_de_transcription_mais_preserve_le_rappel(
    capacites_m1, serveur_stt, tmp_path, mode, code
):
    _ServeurSTT.mode = mode
    resultat = voicemail_stt.transcrire_et_importer(
        _wav(tmp_path / "appel-prive-fictif.wav").read_bytes(),
        suffixe=".wav",
        capacites=capacites_m1,
        configuration=_client(serveur_stt),
        **_args(),
    )

    assert resultat["statut"] == "refuse"
    assert resultat["code"] == code
    assert resultat["m1"]["resultat"]["transcription_conservee"] is False
    assert resultat["m1"]["resultat"]["tache_rappel"]["statut"] == "ouvert"
    assert "fake caller text" not in str(resultat)


def test_duree_maximale_est_verifiee_avant_tout_upload_ni_transcription(capacites_m1, serveur_stt, tmp_path):
    resultat = voicemail_stt.transcrire_et_importer(
        _wav(tmp_path / "appel-trop-long-fictif.wav", duree_s=2).read_bytes(),
        suffixe=".wav",
        capacites=capacites_m1,
        configuration=_client(serveur_stt, duree_max_s=1),
        **_args(),
    )

    assert resultat["statut"] == "refuse"
    assert resultat["code"] == "REJ-DUREE-AUDIO"
    assert resultat["m1"]["resultat"]["transcription_conservee"] is False
    assert _ServeurSTT.requetes == []


def test_limite_octets_refuse_avant_upload_ni_transcription(capacites_m1, serveur_stt, tmp_path):
    resultat = voicemail_stt.transcrire_et_importer(
        _wav(tmp_path / "appel-prive-fictif.wav").read_bytes(),
        suffixe=".wav",
        capacites=capacites_m1,
        configuration=_client(serveur_stt, taille_max_octets=16),
        **_args(),
    )

    assert resultat["statut"] == "refuse"
    assert resultat["code"] == "REJ-TAILLE-AUDIO"
    assert resultat["m1"]["resultat"]["transcription_conservee"] is False
    assert _ServeurSTT.requetes == []


def test_chemin_fichier_n_est_pas_une_entree_de_l_adaptateur(capacites_m1, serveur_stt, tmp_path):
    fichier = _wav(tmp_path / "appel-prive-fictif.wav")
    resultat = voicemail_stt.transcrire_et_importer(
        fichier,
        suffixe=".wav",
        capacites=capacites_m1,
        configuration=_client(serveur_stt),
        **_args(),
    )

    assert resultat["statut"] == "refuse"
    assert resultat["code"] == "REJ-AUDIO-INVALIDE"
    assert resultat["m1"]["resultat"]["transcription_conservee"] is False
    assert _ServeurSTT.requetes == []


def test_transcription_reussie_apres_panne_stt_reprend_le_voicemail_sans_second_rappel(
    capacites_m1, serveur_stt, tmp_path
):
    fichier = _wav(tmp_path / "appel-reprise-fictif.wav")
    audio = fichier.read_bytes()
    configuration = _client(serveur_stt)
    _ServeurSTT.mode = "http_error"

    premiere = voicemail_stt.transcrire_et_importer(
        audio, suffixe=".wav", capacites=capacites_m1, configuration=configuration, **_args()
    )

    assert premiere["statut"] == "refuse" and premiere["code"] == "REJ-STT-HTTP"
    assert premiere["m1"]["ok"] is True
    rappel_initial = premiere["m1"]["resultat"]["tache_rappel"]["transfert_id"]
    assert rappel_initial
    assert len(_ServeurSTT.requetes) == 1

    _ServeurSTT.mode = "success"
    reprise = voicemail_stt.transcrire_et_importer(
        audio, suffixe=".wav", capacites=capacites_m1, configuration=configuration, **_args()
    )

    assert reprise["statut"] == "transcrit", reprise
    assert reprise["m1"]["ok"] is True
    assert reprise["m1"]["resultat"]["transcription_conservee"] is True
    assert reprise["m1"]["resultat"]["tache_rappel"]["transfert_id"] == rappel_initial
    assert len(_ServeurSTT.requetes) == 2
