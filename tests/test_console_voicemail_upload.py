"""Parcours de dépôt admin d’un voicemail M1, sans téléphonie réelle."""

import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import identite, stockage, taxonomie
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.stockage.schema import EVENEMENTS_SORTANTS

SECRET = "secret-voicemail-console-fictif-" + "x" * 32
PREFIXE = "/opsys"


@pytest.fixture
def client_voicemail(session):
    from m1_front_office import outils as outils_m1

    outils_m1.utiliser_stockage_durable()
    taxonomie.enregistrer_zone_desservie(["Laval"])
    taxonomie.enregistrer_services(["gouttieres"])
    with session() as cnx:
        identite.creer_personne(cnx, "admin_voicemail", "Admin FICTIF", "mot-de-passe-admin-fictif", ["admin"])
        identite.creer_personne(
            cnx, "employe_voicemail", "Employé FICTIF", "mot-de-passe-employe-fictif", ["employee"]
        )
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE), None, session
    )
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client


def connecter_admin(client):
    connexion = client.post(
        "/connexion",
        data={"identifiant": "admin_voicemail", "mot_de_passe": "mot-de-passe-admin-fictif"},
        follow_redirects=False,
    )
    assert connexion.status_code == 303
    return client.get("/api/session").json()["csrf"]


def connecter_employe(client):
    connexion = client.post(
        "/connexion",
        data={"identifiant": "employe_voicemail", "mot_de_passe": "mot-de-passe-employe-fictif"},
        follow_redirects=False,
    )
    assert connexion.status_code == 303
    return client.get("/api/session").json()["csrf"]


class _ServeurSTT(BaseHTTPRequestHandler):
    lors_transcription = None
    requetes = 0
    transcription = "Bonjour, mes gouttières fuient à Laval."
    statut_http = 200

    def do_POST(self):
        _ServeurSTT.requetes += 1
        self.rfile.read(int(self.headers["Content-Length"]))
        if _ServeurSTT.lors_transcription is not None:
            _ServeurSTT.lors_transcription()
        corps = json.dumps({"text": _ServeurSTT.transcription}).encode()
        self.send_response(_ServeurSTT.statut_http)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *_args):
        return


@pytest.fixture
def serveur_stt():
    _ServeurSTT.lors_transcription = None
    _ServeurSTT.requetes = 0
    _ServeurSTT.transcription = "Bonjour, mes gouttières fuient à Laval."
    _ServeurSTT.statut_http = 200
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), _ServeurSTT)
    thread = threading.Thread(target=serveur.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{serveur.server_port}/v1"
    finally:
        serveur.shutdown()
        thread.join(timeout=2)
        serveur.server_close()


def _wav(duree_s=1):
    fichier = BytesIO()
    with wave.open(fichier, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * 8000 * duree_s)
    return fichier.getvalue()


def _champs(csrf, **overrides):
    return {
        "source": "Téléphone consulté FICTIF",
        "evenement_id": "event-voicemail-fictif-001",
        "appel_id": "appel-voicemail-fictif-001",
        "recu_le": "2026-09-30T12:00:00-04:00",
        "telephone": "+15145550142",
        "mutation_id": "mutation-voicemail-fictif-001",
        "csrf": csrf,
        "consentement_enregistrement": "accorde",
        **overrides,
    }


def _upload(client, champs, audio=None, nom="message.wav", headers=None):
    parties = [(cle, (None, valeur)) for cle, valeur in champs.items()]
    if audio is not None:
        parties.append(("audio", (nom, audio, "audio/wav")))
    return client.post("/reception/voicemail", files=parties, headers=headers or {})


def test_console_admin_dispose_d_un_ecran_pour_importer_un_voicemail(client_voicemail):
    connecter_admin(client_voicemail)
    reception = client_voicemail.get("/reception")
    assert reception.status_code == 200
    assert f'href="{PREFIXE}/reception/voicemail"' in reception.text
    reponse = client_voicemail.get("/reception/voicemail")
    assert reponse.status_code == 200
    assert "Importer un message vocal" in reponse.text


def test_upload_transcrit_et_importe_par_le_chemin_m1_m2_reel(client_voicemail, serveur_stt, monkeypatch):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)

    reponse = _upload(client_voicemail, _champs(csrf), _wav())

    assert reponse.status_code == 200, reponse.text
    assert "Message vocal importé" in reponse.text
    assert "Bonjour, mes gouttières fuient" not in reponse.text
    assert _ServeurSTT.requetes == 1
    lignes = list(stockage.maillons("m01-front-office", "principal"))
    appels = [ligne for ligne in lignes if ligne.get("type_entree") == "appel_importe"]
    assert len(appels) == 1
    assert appels[0]["statut"] == "voicemail"
    assert appels[0]["reponse"]["transcription_conservee"] is True
    with stockage.transaction() as cnx:
        evenements = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie")
        ).mappings().all()
    assert len(evenements) == 1


@pytest.mark.parametrize("mode", ["sans_consentement", "sans_configuration"])
def test_upload_sans_autorisation_stt_conserve_le_rappel_sans_requete(
    client_voicemail, serveur_stt, monkeypatch, mode
):
    champs = _champs(connecter_admin(client_voicemail))
    if mode == "sans_consentement":
        champs.pop("consentement_enregistrement")
        monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
        monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
        monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    else:
        for variable in ("OPSYS_M1_STT_URL", "OPSYS_M1_STT_MODELE", "OPSYS_M1_STT_CLE", "OPSYS_M1_STT_LOCAL"):
            monkeypatch.delenv(variable, raising=False)

    reponse = _upload(client_voicemail, champs, _wav())

    assert reponse.status_code == 200, reponse.text
    assert "Message vocal importé" in reponse.text
    assert _ServeurSTT.requetes == 0
    appels = [ligne for ligne in stockage.maillons("m01-front-office", "principal")
              if ligne.get("type_entree") == "appel_importe"]
    assert len(appels) == 1
    resultat = appels[0]["reponse"]
    assert resultat["transcription_conservee"] is False
    assert resultat["tache_rappel"]["statut"] == "ouvert"


def test_role_retire_pendant_stt_refuse_import_final(client_voicemail, serveur_stt, session, monkeypatch):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)

    def retirer_role():
        with session() as cnx:
            identite.retirer_role(cnx, "admin_voicemail", "admin")

    _ServeurSTT.lors_transcription = retirer_role
    reponse = _upload(client_voicemail, _champs(csrf), _wav())

    assert reponse.status_code == 403, reponse.text
    assert not [ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]


def test_role_retire_apres_parsing_refuse_avant_transfert_stt(
    client_voicemail, serveur_stt, session, monkeypatch
):
    from opsys.console import voicemail_ui

    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    parser_reel = voicemail_ui._multipart_borne

    async def parser_puis_retirer_role(request):
        formulaire = await parser_reel(request)
        with session() as cnx:
            identite.retirer_role(cnx, "admin_voicemail", "admin")
        return formulaire

    monkeypatch.setattr(voicemail_ui, "_multipart_borne", parser_puis_retirer_role)

    reponse = _upload(client_voicemail, _champs(csrf), _wav())

    assert reponse.status_code == 403
    assert _ServeurSTT.requetes == 0
    assert not [ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]


def test_upload_refuse_csrf_absent_extension_invalide_et_wav_invalide(
    client_voicemail, serveur_stt, monkeypatch
):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)

    csrf_absent = _upload(client_voicemail, _champs("jeton-csrf-incorrect"), _wav())
    extension_invalide = _upload(client_voicemail, _champs(csrf, mutation_id="mut-2"), _wav(), "message.mp3")
    wav_invalide = _upload(client_voicemail, _champs(csrf, mutation_id="mut-3"), b"pas un wav")

    assert csrf_absent.status_code == 403
    assert extension_invalide.status_code == 400
    assert wav_invalide.status_code == 400
    assert _ServeurSTT.requetes == 0
    assert not [ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]


def test_upload_temporary_spool_ferme_apres_traitement(client_voicemail, monkeypatch):
    import starlette.formparsers

    temporaires = []
    vrai_temporaire = starlette.formparsers.SpooledTemporaryFile

    def temporaire_suivi(*args, **kwargs):
        fichier = vrai_temporaire(*args, **kwargs)
        temporaires.append(fichier)
        return fichier

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", temporaire_suivi)
    csrf = connecter_admin(client_voicemail)

    reponse = _upload(client_voicemail, _champs(csrf), _wav())

    assert reponse.status_code == 200, reponse.text
    assert len(temporaires) == 1 and temporaires[0].closed


def test_upload_temporary_spool_ferme_apres_refus_de_format(client_voicemail, monkeypatch):
    import starlette.formparsers

    temporaires = []
    vrai_temporaire = starlette.formparsers.SpooledTemporaryFile

    def temporaire_suivi(*args, **kwargs):
        fichier = vrai_temporaire(*args, **kwargs)
        temporaires.append(fichier)
        return fichier

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", temporaire_suivi)
    csrf = connecter_admin(client_voicemail)

    reponse = _upload(client_voicemail, _champs(csrf), _wav(), "fichier.mp3")

    assert reponse.status_code == 400
    assert len(temporaires) == 1 and temporaires[0].closed


def test_upload_ferme_le_spool_si_le_parseur_refuse_un_second_fichier(client_voicemail, monkeypatch):
    import starlette.formparsers

    temporaires = []
    vrai_temporaire = starlette.formparsers.SpooledTemporaryFile

    def temporaire_suivi(*args, **kwargs):
        fichier = vrai_temporaire(*args, **kwargs)
        temporaires.append(fichier)
        return fichier

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", temporaire_suivi)
    champs = _champs(connecter_admin(client_voicemail))
    parties = [(cle, (None, valeur)) for cle, valeur in champs.items()]
    parties.extend([
        ("audio", ("message.wav", _wav(), "audio/wav")),
        ("audio", ("deuxieme.wav", _wav(), "audio/wav")),
    ])

    reponse = client_voicemail.post("/reception/voicemail", files=parties)

    assert reponse.status_code == 400
    assert len(temporaires) == 1 and temporaires[0].closed


def test_upload_ne_reflete_pas_texte_fourni_dans_le_formulaire(client_voicemail, monkeypatch):
    for variable in ("OPSYS_M1_STT_URL", "OPSYS_M1_STT_MODELE", "OPSYS_M1_STT_CLE", "OPSYS_M1_STT_LOCAL"):
        monkeypatch.delenv(variable, raising=False)
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf, source="<script>alert('xss')</script>")
    champs.pop("consentement_enregistrement")

    reponse = _upload(client_voicemail, champs, _wav())

    assert reponse.status_code == 200
    assert "<script>" not in reponse.text
    assert "alert('xss')" not in reponse.text


def test_upload_exige_session_et_csrf(client_voicemail):
    sans_session = client_voicemail.get("/reception/voicemail", follow_redirects=False)
    assert sans_session.status_code == 303
    assert sans_session.headers["location"] == f"{PREFIXE}/connexion"
    connecter_admin(client_voicemail)

    sans_csrf = _upload(client_voicemail, _champs(""), _wav())

    assert sans_csrf.status_code == 403
    assert not [ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]


def test_upload_refuse_employe_avant_lecture_audio_ou_stt(client_voicemail, serveur_stt, monkeypatch):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_employe(client_voicemail)

    reponse = _upload(client_voicemail, _champs(csrf), _wav())

    assert reponse.status_code == 403
    assert _ServeurSTT.requetes == 0
    assert not [ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]


def test_upload_refuse_champs_dupliques_sans_effet(client_voicemail):
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    parties = [(cle, (None, valeur)) for cle, valeur in champs.items()]
    parties.extend([("source", (None, "autre source")), ("audio", ("message.wav", _wav(), "audio/wav"))])

    reponse = client_voicemail.post("/reception/voicemail", files=parties)

    assert reponse.status_code == 400
    assert not [ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]


def test_upload_refuse_champ_inconnu_ou_transport_non_multipart(client_voicemail):
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    parties = [(cle, (None, valeur)) for cle, valeur in champs.items()]
    parties.extend([
        ("action_libre", (None, "exécuter une commande")),
        ("audio", ("message.wav", _wav(), "audio/wav")),
    ])

    champ_inconnu = client_voicemail.post("/reception/voicemail", files=parties)
    sans_multipart = client_voicemail.post("/reception/voicemail", data=champs)

    assert champ_inconnu.status_code == 400
    assert sans_multipart.status_code == 400
    assert not [ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]


def test_upload_refuse_endpoint_externe_sans_consentement_de_transfert(
    client_voicemail, serveur_stt, monkeypatch
):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "0")
    monkeypatch.setenv("OPSYS_M1_STT_CLE", "secret-fictif-ne-pas-afficher")
    csrf = connecter_admin(client_voicemail)

    reponse = _upload(client_voicemail, _champs(csrf), _wav())

    assert reponse.status_code == 200, reponse.text
    assert "sans transcription" in reponse.text
    assert _ServeurSTT.requetes == 0
    assert "secret-fictif-ne-pas-afficher" not in reponse.text
    appels = [ligne for ligne in stockage.maillons("m01-front-office", "principal")
              if ligne.get("type_entree") == "appel_importe"]
    assert len(appels) == 1 and appels[0]["reponse"]["transcription_conservee"] is False


def test_upload_rejoue_ne_cree_pas_deux_entrees_metier(client_voicemail, serveur_stt, monkeypatch):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)

    premier = _upload(client_voicemail, champs, _wav())
    rejoue = _upload(client_voicemail, champs, _wav())

    assert premier.status_code == rejoue.status_code == 200
    assert _ServeurSTT.requetes == 1
    assert len([ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]) == 1
    with stockage.transaction() as cnx:
        evenements = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie")
        ).all()
    assert len(evenements) == 1


def test_upload_rejeu_contradictoire_ne_remplace_pas_la_premiere_entree(
    client_voicemail, serveur_stt, monkeypatch
):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    premier = _upload(client_voicemail, champs, _wav())
    _ServeurSTT.transcription = "Plainte fictive sur une facture."

    conflit = _upload(client_voicemail, champs, _wav(duree_s=2))

    assert premier.status_code == 200
    assert conflit.status_code == 409
    assert _ServeurSTT.requetes == 2
    assert len([ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]) == 1


def test_rejeu_audio_identique_reutilise_stt_termine(client_voicemail, serveur_stt, monkeypatch):
    from m1_front_office import outils as outils_m1

    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    chercher = outils_m1.rechercher_rejeu_voicemail_stt
    marquer = outils_m1.enregistrer_rejeu_voicemail_stt

    def chercher_dans_instance(*args):
        assert stockage.connexion_courante() is not None
        return chercher(*args)

    def marquer_dans_instance(*args):
        assert stockage.connexion_courante() is not None
        return marquer(*args)

    monkeypatch.setattr(outils_m1, "rechercher_rejeu_voicemail_stt", chercher_dans_instance)
    monkeypatch.setattr(outils_m1, "enregistrer_rejeu_voicemail_stt", marquer_dans_instance)

    premier = _upload(client_voicemail, champs, _wav())
    rejoue = _upload(client_voicemail, champs, _wav())

    assert premier.status_code == rejoue.status_code == 200
    assert _ServeurSTT.requetes == 1
    appels = [ligne for ligne in stockage.maillons("m01-front-office", "principal")
              if ligne.get("type_entree") == "appel_importe"]
    assert len(appels) == 1


def test_role_retire_apres_lookup_cache_refuse_avant_reponse(
    client_voicemail, serveur_stt, session, monkeypatch
):
    from m1_front_office import outils as outils_m1

    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    assert _upload(client_voicemail, champs, _wav()).status_code == 200
    recherche_reelle = outils_m1.rechercher_rejeu_voicemail_stt

    def rechercher_puis_retirer(*args):
        resultat = recherche_reelle(*args)
        with session() as cnx:
            identite.retirer_role(cnx, "admin_voicemail", "admin")
        return resultat

    monkeypatch.setattr(outils_m1, "rechercher_rejeu_voicemail_stt", rechercher_puis_retirer)
    refuse = _upload(client_voicemail, champs, _wav())

    assert refuse.status_code == 403
    assert _ServeurSTT.requetes == 1


def test_rejeu_metadata_change_ne_reutilise_pas_stt_et_conflit_sans_ecraser(
    client_voicemail, serveur_stt, monkeypatch
):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    premier = _upload(client_voicemail, champs, _wav())
    modifie = _upload(client_voicemail, _champs(csrf, telephone="+15145550143"), _wav())

    assert premier.status_code == 200
    assert modifie.status_code == 409
    assert _ServeurSTT.requetes == 2
    appels = [ligne for ligne in stockage.maillons("m01-front-office", "principal")
              if ligne.get("type_entree") == "appel_importe"]
    assert len(appels) == 1 and appels[0]["reponse"]["source"] == "Téléphone consulté FICTIF"


def test_configuration_stt_differente_invalide_la_reutilisation(
    client_voicemail, serveur_stt, monkeypatch
):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    assert _upload(client_voicemail, champs, _wav()).status_code == 200

    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-autre-fictif")
    assert _upload(client_voicemail, champs, _wav()).status_code == 200
    assert _ServeurSTT.requetes == 2


def test_role_retire_avant_rejeu_refuse_avant_stt(client_voicemail, serveur_stt, session, monkeypatch):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    assert _upload(client_voicemail, champs, _wav()).status_code == 200
    with session() as cnx:
        identite.retirer_role(cnx, "admin_voicemail", "admin")

    refuse = _upload(client_voicemail, champs, _wav())

    assert refuse.status_code == 403
    assert _ServeurSTT.requetes == 1


def test_consentement_courant_absent_ne_reutilise_pas_la_preuve_stt(client_voicemail, serveur_stt, monkeypatch):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    assert _upload(client_voicemail, champs, _wav()).status_code == 200
    avant = len([ligne for ligne in stockage.maillons("m01-front-office", "principal")
                 if ligne.get("type_entree") == "voicemail_stt_termine"])
    sans_consentement = _champs(csrf)
    sans_consentement.pop("consentement_enregistrement")

    refuse = _upload(client_voicemail, sans_consentement, _wav())

    apres = len([ligne for ligne in stockage.maillons("m01-front-office", "principal")
                 if ligne.get("type_entree") == "voicemail_stt_termine"])
    assert refuse.status_code == 409
    assert _ServeurSTT.requetes == 1 and avant == apres == 1


def test_import_manuel_sans_empreinte_ne_sert_pas_de_cache_stt(client_voicemail, serveur_stt, monkeypatch):
    from m1_front_office import outils as outils_m1

    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    outils_m1.importer_appel_manuellement(
        source=champs["source"], evenement_id=champs["evenement_id"], appel_id=champs["appel_id"],
        recu_le=champs["recu_le"], telephone=champs["telephone"], statut="voicemail",
        transcription=_ServeurSTT.transcription, consentement_enregistrement="accorde",
    )

    reprise = _upload(client_voicemail, champs, _wav())

    assert reprise.status_code == 200
    assert _ServeurSTT.requetes == 1


def test_echec_stt_n_est_pas_marque_comme_transcription_reutilisable(client_voicemail, serveur_stt, monkeypatch):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    champs = _champs(csrf)
    _ServeurSTT.statut_http = 503
    premier = _upload(client_voicemail, champs, _wav())
    preuves = [ligne for ligne in stockage.maillons("m01-front-office", "principal")
               if ligne.get("type_entree") == "voicemail_stt_termine"]
    _ServeurSTT.statut_http = 200

    reprise = _upload(client_voicemail, champs, _wav())

    assert premier.status_code == 200 and reprise.status_code == 409
    assert _ServeurSTT.requetes == 2 and preuves == []


def test_upload_duree_wav_verifiee_meme_sans_stt_configure(client_voicemail, monkeypatch):
    for variable in ("OPSYS_M1_STT_URL", "OPSYS_M1_STT_MODELE", "OPSYS_M1_STT_CLE", "OPSYS_M1_STT_LOCAL"):
        monkeypatch.delenv(variable, raising=False)
    csrf = connecter_admin(client_voicemail)

    reponse = _upload(client_voicemail, _champs(csrf), _wav(duree_s=301))

    assert reponse.status_code == 400
    assert "REJ-DUREE-AUDIO" in reponse.text
    assert not [ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]


def test_upload_trop_grand_refuse_avant_stt(client_voicemail, serveur_stt, monkeypatch):
    from m1_front_office.voicemail_stt import MAX_AUDIO_OCTETS

    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)

    reponse = _upload(client_voicemail, _champs(csrf), b"x" * (MAX_AUDIO_OCTETS + 1))

    assert reponse.status_code == 413
    assert _ServeurSTT.requetes == 0
    assert not [ligne for ligne in stockage.maillons("m01-front-office", "principal")
                if ligne.get("type_entree") == "appel_importe"]


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("source", " Téléphone consulté FICTIF "),
        ("evenement_id", " event-voicemail-fictif-001 "),
        ("appel_id", " appel-voicemail-fictif-001 "),
    ],
)
def test_rejeu_identifiant_avec_espaces_externes_reutilise_stt(
    client_voicemail, serveur_stt, monkeypatch, champ, valeur
):
    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    champs = _champs(connecter_admin(client_voicemail), **{champ: valeur})

    premier = _upload(client_voicemail, champs, _wav())
    rejoue = _upload(client_voicemail, champs, _wav())

    assert premier.status_code == rejoue.status_code == 200
    assert _ServeurSTT.requetes == 1
    lignes = stockage.maillons("m01-front-office", "principal")
    imports = [ligne for ligne in lignes if ligne.get("type_entree") == "appel_importe"]
    marqueurs = [ligne for ligne in lignes if ligne.get("type_entree") == "voicemail_stt_termine"]
    assert len(imports) == len(marqueurs) == 1
    assert imports[0][champ] == valeur.strip()


def test_echec_stt_puis_reprise_consentie_garde_le_meme_handoff_et_rejeu_routeur(
    client_voicemail, serveur_stt, monkeypatch
):
    from m1_front_office import transferts

    monkeypatch.setenv("OPSYS_M1_STT_URL", serveur_stt)
    monkeypatch.setenv("OPSYS_M1_STT_MODELE", "whisper-test-fictif")
    monkeypatch.setenv("OPSYS_M1_STT_LOCAL", "1")
    csrf = connecter_admin(client_voicemail)
    _ServeurSTT.statut_http = 503

    panne = _upload(client_voicemail, _champs(csrf), _wav())

    assert panne.status_code == 200, panne.text
    assert "sans transcription" in panne.text
    assert _ServeurSTT.requetes == 1
    lignes_initiales = list(stockage.maillons("m01-front-office", "principal"))
    appels = [ligne for ligne in lignes_initiales if ligne.get("type_entree") == "appel_importe"]
    assert len(appels) == 1
    assert appels[0]["reponse"]["transcription_conservee"] is False
    transfert_id = appels[0]["reponse"]["tache_rappel"]["transfert_id"]
    assert "Bonjour, mes gouttières fuient à Laval." not in str(lignes_initiales)

    _ServeurSTT.statut_http = 200
    reprise = _upload(
        client_voicemail, _champs(csrf, mutation_id="mutation-voicemail-retry-fictif-002"), _wav()
    )

    assert reprise.status_code == 200, reprise.text
    assert "transcription reçue" in reprise.text
    assert _ServeurSTT.requetes == 2
    lignes = list(stockage.maillons("m01-front-office", "principal"))
    imports = [ligne for ligne in lignes if ligne.get("type_entree") == "appel_importe"]
    enrichis = [ligne for ligne in lignes if ligne.get("type_entree") == "appel_voicemail_enrichi"]
    assert len(imports) == 1 and len(enrichis) == 1
    assert enrichis[0]["consentement_enregistrement"] == "accorde"
    assert enrichis[0]["transfert_id"] == transfert_id
    assert enrichis[0]["reponse"]["traitement"]["decision"] == "TRANSFERT_EN_COURS"
    assert enrichis[0]["reponse"]["traitement"]["qualification_en_attente"] == "transfert_humain_ouvert"
    etats = transferts.lire(lignes)
    assert len(etats) == 1 and etats[0].identifiant == transfert_id and etats[0].ouvert
    vue = transferts.vue(etats[0], lignes)
    assert len(vue["messages_suivants"]) == 1
    assert "Bonjour, mes gouttières fuient à Laval." in vue["messages_suivants"][0]["texte"]
    assert all("audio" not in cle for ligne in enrichis for cle in ligne)
    with stockage.transaction() as cnx:
        publies = cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == "m1.lead_qualifie")
        ).all()
    assert publies == [], "un transfert humain ouvert ne force pas un lead vers M2/M10"

    replay = _upload(
        client_voicemail, _champs(csrf, mutation_id="mutation-voicemail-replay-fictif-003"), _wav()
    )
    assert replay.status_code == 200, replay.text
    assert "transcription reçue" in replay.text
    assert _ServeurSTT.requetes == 2, "le reçu STT opaque évite un troisième appel au mock local"
    lignes_rejouees = list(stockage.maillons("m01-front-office", "principal"))
    assert len([ligne for ligne in lignes_rejouees if ligne.get("type_entree") == "appel_voicemail_enrichi"]) == 1
    assert len([e for e in transferts.lire(lignes_rejouees) if e.identifiant == transfert_id]) == 1
