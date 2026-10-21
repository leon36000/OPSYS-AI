"""Composition voicemail M1 -> M2 : réponse perdue après commit, puis vrai nouveau processus sur la même base.

Le premier processus transcrit par un serveur STT 127.0.0.1 possédé par ce test, importe par le vrai
`Capacites.appeler("m1_importer_appel_manuellement")` et ne perd sa réponse qu'après le retour canonique, une fois le
commit vu par une connexion SQLite indépendante. Un autre processus OS relivre le même voicemail et répartit au vrai
consommateur M2 durable. Les témoins finaux sont relus en lecture seule après la fermeture de tous les écrivains.

Limites : ni plantage du consommateur M2 avant accusé, ni exactly-once du fournisseur STT, ni perte d'alimentation.
Audio, numéro, service et zone sont fictifs.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from m1_front_office import outils as outils_m1
from m2_revenue_crm import outils as outils_m2

from opsys import evenements, stockage, taxonomie
from opsys.stockage import codec

AIDE = Path(__file__).with_name("voicemail_process_fixture.py")
_spec = importlib.util.spec_from_file_location("voicemail_process_fixture", AIDE)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)

TEXTE_FICTIF = "Bonjour, mes gouttières fuient à Laval."
METADONNEES = {
    "source": "boite-vocale-fictive-composition",
    "evenement_id": "evt-vocal-composition-fictif-001",
    "appel_id": "appel-vocal-composition-fictif-001",
    "recu_le": "2026-09-30T12:00:00-04:00",
    "telephone": "+15145550177",
}
MAINTENANT = "2026-09-30T13:00:00-04:00"
REPARTITION_UNIQUE = {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
REPARTITION_VIDE = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}


class _Composition:
    def __init__(self, tmp_path: Path, base: Path, url: str, stt_url: str, audio: Path, requetes: list):
        self.tmp_path, self.base, self.url, self.stt_url = tmp_path, base, url, stt_url
        self.audio, self.requetes = audio, requetes
        self.identites: list[tuple[int, int]] = []

    def lancer(self, role: str, nom: str, **extra) -> tuple[int, dict]:
        """Un vrai processus OS, attendu jusqu'au STOP et à l'EOF de ses deux flux ; jamais relancé."""
        config = {"base": str(self.base), "stt_url": self.stt_url, "audio": str(self.audio),
                  "metadonnees": METADONNEES, "maintenant": MAINTENANT, **extra}
        chemin = self.tmp_path / f"{nom}.json"
        chemin.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        env = {**os.environ, stockage.ENV_URL: self.url, "PYTHONPATH": os.pathsep.join(sys.path),
               "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}
        processus = subprocess.Popen(
            [sys.executable, str(AIDE), role, str(chemin)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env, cwd=self.tmp_path,
        )
        identite_os = aide.identite_processus(processus.pid)
        try:
            sortie, erreurs = processus.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            processus.kill()
            processus.communicate()
            pytest.fail(f"processus {nom} non terminé dans le délai : tué, jamais relancé")
        assert processus.returncode is not None
        lignes = sortie.splitlines()
        assert len(lignes) == 1, (nom, processus.returncode, sortie, erreurs[-4000:])
        rapport = json.loads(lignes[0])
        assert rapport["fin"] is True and rapport["role"] == role
        identite = rapport["identite"]
        assert identite["pid"] == processus.pid and identite["parent"] == os.getpid()
        if identite_os is not None:
            assert identite_os["start_time"] == identite["start_time"]
        cle = (identite["pid"], identite["start_time"])
        assert cle not in self.identites and identite["pid"] != os.getpid()
        self.identites.append(cle)
        assert rapport["metadonnees"] == METADONNEES
        assert rapport["sha256_audio"] == hashlib.sha256(self.audio.read_bytes()).hexdigest()
        return processus.returncode, rapport


def _serveur_stt(requetes: list) -> ThreadingHTTPServer:
    class _STT(BaseHTTPRequestHandler):
        def do_POST(self):
            corps = self.rfile.read(int(self.headers["Content-Length"]))
            requetes.append((self.path, corps))
            sortie = json.dumps({"text": TEXTE_FICTIF}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(sortie)))
            self.end_headers()
            self.wfile.write(sortie)

        def log_message(self, *_args):
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), _STT)


@pytest.fixture
def composition(tmp_path, monkeypatch, declarer_services):
    base = tmp_path / "composition-m1.db"
    url = f"sqlite:///{base}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    stockage.liberer()
    audio = tmp_path / "voicemail-composition-fictif.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\1" * 8000)
    requetes: list = []
    serveur = _serveur_stt(requetes)
    assert serveur.server_address[0] == "127.0.0.1"
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    outils_m1.utiliser_stockage_durable()
    outils_m2.utiliser_stockage_durable()
    try:
        yield _Composition(tmp_path, base, url, f"http://127.0.0.1:{serveur.server_port}/v1", audio, requetes)
    finally:
        serveur.shutdown()
        fil.join(timeout=5)
        serveur.server_close()
        outils_m1.reinitialiser_registre()
        outils_m2.reinitialiser_registre()
        stockage.liberer()


def _json(valeur):
    return json.loads(json.dumps(valeur, ensure_ascii=False))


def _violations(temoins: dict, prefixe_m1: list[str], resultat: dict) -> list[str]:
    """Oracle d'identité et de filiation ; une chaîne valide ou un compte de lignes seul n'y suffit pas."""
    m1 = [codec.decoder(texte) for texte in temoins["registres"][aide.M1]]
    m2 = [codec.decoder(texte) for texte in temoins["registres"][aide.M2]]
    sortants = [{**sortant, "charge": codec.decoder(sortant["charge"])} for sortant in temoins["sortants"]]
    lead = _json(resultat["traitement"]["lead"])
    lead_id = lead["lead_id"]
    signal_id = f"appel-manuel:{METADONNEES['source']}:{METADONNEES['evenement_id']}"
    violations = []
    if temoins["registres"][aide.M1][:len(prefixe_m1)] != prefixe_m1:
        violations.append("prefixe_m1_modifie")
    if len(temoins["registres"][aide.M1]) != len(prefixe_m1):
        violations.append("m1_ajout_apres_commit")
    imports = [ligne for ligne in m1 if ligne.get("type_entree") == "appel_importe"
               and ligne.get("source") == METADONNEES["source"] and ligne.get("appel_id") == METADONNEES["appel_id"]]
    if len(imports) != 1:
        violations.append("appel_importe_non_unique")
    elif (imports[0]["evenement_id"] != METADONNEES["evenement_id"] or imports[0]["statut"] != "voicemail"
          or _json(imports[0]["reponse"]) != _json(resultat)):
        violations.append("appel_importe_identite_divergente")
    leads = [ligne for ligne in m1 if ligne.get("type_entree") == "lead_emis"]
    if len(leads) != 1:
        violations.append("lead_emis_non_unique")
    elif _json(leads[0]["lead"]) != lead or leads[0]["signal_id"] != signal_id:
        violations.append("lead_emis_lignage_divergent")
    outbox = [sortant for sortant in sortants if sortant["type_evenement"] == aide.TYPE_LEAD]
    if len(outbox) != 1:
        violations.append("outbox_lead_non_unique")
    elif (outbox[0]["evenement_id"] != f"m1-lead-qualifie-{lead_id}" or outbox[0]["producteur"] != aide.M1
          or _json(outbox[0]["charge"]["lead"]) != lead or outbox[0]["charge"]["signal_id"] != signal_id):
        violations.append("outbox_lignage_divergent")
    ids_outbox = {sortant["evenement_id"] for sortant in outbox}
    recus = [recu for recu in temoins["recus"] if recu["evenement_id"] in ids_outbox]
    if (len(recus) != 1 or recus[0]["consommateur"] != aide.M2 or recus[0]["statut"] != "traite"
            or recus[0]["tentatives"] != 1 or codec.decoder(recus[0]["resultat"]).get("lead_id") != lead_id):
        violations.append("livraison_m2_non_unique_ou_non_traitee")
    ingeres = [ligne for ligne in m2 if ligne.get("type_entree") == "lead_ingere"]
    if len(ingeres) != 1:
        violations.append("lead_ingere_non_unique")
    elif (ingeres[0]["lead_id"] != lead_id or _json(ingeres[0]["contrat"]) != lead
          or len(outbox) != 1 or ingeres[0]["horodatage"] != outbox[0]["charge"]["horodatage"]):
        violations.append("lead_ingere_lignage_divergent")
    return violations


def _copie_jetable(base: Path, destination: Path) -> str:
    destination.mkdir()
    for suffixe in ("", "-wal"):
        source = Path(f"{base}{suffixe}")
        if source.exists():
            shutil.copy2(source, destination / f"{base.name}{suffixe}")
    return f"sqlite:///{destination / base.name}"


def _chaines_valides(url: str) -> bool:
    with stockage.transaction(url):
        return (outils_m1._obtenir_registre().valider_chaine() == (True, None)
                and outils_m2._obtenir_registre().valider_chaine() is True)


def _muter_copie_sql(url: str, requete: str, parametres: tuple) -> None:
    """Altération brute d'une copie jetable seulement, pour exercer les branches de filiation de l'oracle."""
    cnx = sqlite3.connect(url.removeprefix("sqlite:///"), isolation_level=None)
    try:
        assert cnx.execute(requete, parametres).rowcount == 1
    finally:
        cnx.close()


def _sans_chainage(ligne: dict) -> dict:
    return {cle: valeur for cle, valeur in ligne.items() if cle not in ("ligne_id", "precedent_ligne_id")}


def test_reponse_perdue_apres_commit_nouveau_processus_relivre_sans_doublon_m1_m2(
    composition, record_testsuite_property,
):
    vide = aide.lire_temoins(composition.base)
    assert vide == {"registres": {aide.M1: [], aide.M2: []}, "sortants": [], "recus": []}

    code, ecrivain = composition.lancer("ecrivain", "01-ecrivain")

    # Le commit est constaté AVANT la panne, hors de toute transaction englobante ; sinon le montage est refusé.
    assert code == aide.CODE_PERTE_APRES_COMMIT, ecrivain
    assert ecrivain["transaction_englobante"] is False
    assert ecrivain["faits_committes"] == {"appel_importe": 1, "lead_emis": 1, "outbox": 1}
    assert ecrivain["arguments"] == {**METADONNEES, "statut": "voicemail", "transcription": TEXTE_FICTIF,
                                     "consentement_enregistrement": "accorde"}
    reponse = ecrivain["reponse"]
    assert reponse["ok"] is True
    resultat = reponse["resultat"]
    assert resultat["traitement"]["decision"] == "TRANSMETTRE_M2"
    assert resultat["tache_rappel"] is None and resultat["transcription_conservee"] is True
    assert resultat["evenement_id"] == METADONNEES["evenement_id"]
    commit = ecrivain["temoins"]
    assert commit["registres"][aide.M2] == [] and commit["recus"] == []
    assert not any(codec.decoder(texte).get("type_entree") == "transfert" for texte in commit["registres"][aide.M1])
    prefixe_m1 = commit["registres"][aide.M1]
    assert aide.lire_temoins(composition.base) == commit
    assert len(composition.requetes) == 1

    code, reouverture = composition.lancer("reouverture", "02-reouverture")

    assert code == 0, reouverture
    assert reouverture["resultat"]["statut"] == "transcrit"
    assert reouverture["arguments"] == [ecrivain["arguments"]]
    assert reouverture["resultat"]["m1"] == reponse
    assert reouverture["repartition"] == REPARTITION_UNIQUE
    assert reouverture["chaines"] == {"m1": [True, None], "m2": True}
    apres_reouverture = aide.lire_temoins(composition.base)

    code, repartition = composition.lancer("repartition", "03-repartition")

    assert code == 0, repartition
    assert repartition["repartition"] == REPARTITION_VIDE
    assert repartition["chaines"] == {"m1": [True, None], "m2": True}
    assert len(set(composition.identites)) == 3

    # Tous les écrivains sont fermés : témoins finaux relus en lecture seule.
    final = aide.lire_temoins(composition.base)
    assert final == apres_reouverture
    assert _violations(final, prefixe_m1, resultat) == []
    tentatives_stt = len(composition.requetes)
    record_testsuite_property("r1_tentatives_stt_mesurees", tentatives_stt)
    assert tentatives_stt in (1, 2)
    audio = composition.audio.read_bytes()
    assert all(chemin == "/v1/audio/transcriptions" and audio in corps for chemin, corps in composition.requetes)

    # Sensibilité de l'oracle sur copies jetables, mutées par les API canoniques : la chaîne reste valide.
    url_m2 = _copie_jetable(composition.base, composition.tmp_path / "negatif-m2")
    with stockage.transaction(url_m2):
        registre_m2 = outils_m2._obtenir_registre()
        ingere = next(ligne for ligne in registre_m2.lire() if ligne["type_entree"] == "lead_ingere")
        registre_m2.ajouter(_sans_chainage(ingere))
    assert _chaines_valides(url_m2)
    url_m1 = _copie_jetable(composition.base, composition.tmp_path / "negatif-m1")
    with stockage.transaction(url_m1):
        registre_m1 = outils_m1._obtenir_registre()
        importe = next(ligne for ligne in registre_m1.lire() if ligne["type_entree"] == "appel_importe")
        registre_m1.ajouter(_sans_chainage(importe))
    assert _chaines_valides(url_m1)
    url_bus = _copie_jetable(composition.base, composition.tmp_path / "negatif-bus")
    charge = codec.decoder(next(s["charge"] for s in final["sortants"] if s["type_evenement"] == aide.TYPE_LEAD))
    with stockage.transaction(url_bus):
        evenements.publier(aide.TYPE_LEAD, aide.M1, charge, evenement_id="m1-lead-qualifie-divergent-fictif")
    assert _chaines_valides(url_bus)
    stockage.liberer()
    evenement_id = next(s["evenement_id"] for s in final["sortants"] if s["type_evenement"] == aide.TYPE_LEAD)
    url_lignage = _copie_jetable(composition.base, composition.tmp_path / "negatif-lignage")
    _muter_copie_sql(url_lignage, "UPDATE evenements_sortants SET charge = ? WHERE evenement_id = ?",
                     (codec.encoder({**charge, "signal_id": "appel-manuel:autre-source-fictive:evt-x"}), evenement_id))
    url_livraison = _copie_jetable(composition.base, composition.tmp_path / "negatif-livraison")
    _muter_copie_sql(url_livraison, "UPDATE evenements_recus SET tentatives = 2 WHERE evenement_id = ?",
                     (evenement_id,))

    assert "lead_ingere_non_unique" in _violations(
        aide.lire_temoins(composition.tmp_path / "negatif-m2" / composition.base.name), prefixe_m1, resultat)
    assert "appel_importe_non_unique" in _violations(
        aide.lire_temoins(composition.tmp_path / "negatif-m1" / composition.base.name), prefixe_m1, resultat)
    assert "outbox_lead_non_unique" in _violations(
        aide.lire_temoins(composition.tmp_path / "negatif-bus" / composition.base.name), prefixe_m1, resultat)
    assert _violations(aide.lire_temoins(composition.tmp_path / "negatif-lignage" / composition.base.name),
                       prefixe_m1, resultat) == ["outbox_lignage_divergent"]
    assert _violations(aide.lire_temoins(composition.tmp_path / "negatif-livraison" / composition.base.name),
                       prefixe_m1, resultat) == ["livraison_m2_non_unique_ou_non_traitee"]
    assert aide.lire_temoins(composition.base) == final


def test_consentement_retire_avant_reprise_meme_identite_sans_stt_ni_nouveau_fait(composition):
    code, reception = composition.lancer("reception", "01-reception")

    assert code == 0, reception
    resultat = reception["resultat"]["m1"]["resultat"]
    assert reception["resultat"]["statut"] == "transcrit"
    assert resultat["traitement"]["decision"] == "TRANSMETTRE_M2"
    assert reception["repartition"] == REPARTITION_UNIQUE
    avant = aide.lire_temoins(composition.base)
    assert _violations(avant, avant["registres"][aide.M1], resultat) == []
    assert len(composition.requetes) == 1

    for rang, consentement in enumerate((None, "refuse"), start=2):
        code, retrait = composition.lancer("retrait", f"0{rang}-retrait", consentement=consentement)

        # Contrat existant : aucun STT, aucun succès ni texte rendu ; l'import canonique refuse la contradiction.
        assert code == 0, retrait
        refus = retrait["resultat"]
        assert refus["statut"] == "refuse" and refus["code"] == "REJ-IMPORT-M1"
        assert "transcription" not in refus
        assert refus["m1"]["ok"] is False and "REJ-APPEL-CONTRADICTOIRE" in refus["m1"]["details"]
        assert TEXTE_FICTIF not in json.dumps(refus, ensure_ascii=False)
        assert retrait["repartition"] == REPARTITION_VIDE
        assert retrait["chaines"] == {"m1": [True, None], "m2": True}
        assert len(composition.requetes) == 1
        assert aide.lire_temoins(composition.base) == avant

    assert len(set(composition.identites)) == 3
