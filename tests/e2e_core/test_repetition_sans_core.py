"""Répétition générale du scénario E2E sans le core : elle prouve le SCRIPT, pas le core (PLAN T1.5-b).

Le core (TypeScript) ne tourne pas dans le bac à sable de développement ; sa CI exécute `scenario.py` contre le
vrai Gateway (`.github/workflows/e2e-core.yml`). Pour que le script n'échoue pas en CI sur une faute de frappe,
ce test en joue tout ce qui est Python, pour de vrai :

- les vraies commandes du socle (`opsys-metier base migrer`, `paliers definir`, `openclaw configurer`,
  `personnes creer`, `appareils appairer`), les vrais fragments de configuration, le vrai chantier semé par les vrais
  outils ;
- le vrai moteur, dans un processus à part, lancé avec la commande que `opsys/metier.json` donne au superviseur ;
- le vrai trajet HTTP de `trajet.jouer`, contre une passerelle factice qui applique la règle de la porte d'appareil
  du core telle que `tests/fixtures/harnais_e2e.py` la refait d'après le fork.

Ce que ce test ne prouve PAS, et que seule la CI du core prouve : le démarrage du Gateway avec cette
configuration, le superviseur, `openclaw qr`, la poignée de main d'appairage, l'approbation par la CLI du core,
le jeton d'appareil, et le comportement réel de `/tools/invoke` et de `GET /opsys/identite`.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.server
import json
import secrets
import struct
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

ICI = Path(__file__).resolve().parent
if str(ICI) not in sys.path:
    sys.path.insert(0, str(ICI))

import journee  # noqa: E402
import scenario  # noqa: E402
import trajet  # noqa: E402
from harnais_e2e import JETON_MCP, Moteur  # noqa: E402

from opsys import fichiers, stockage  # noqa: E402
from opsys.departements import charger_departements  # noqa: E402


class PasserelleFactice:
    """Un Gateway pour la répétition : mêmes routes, mêmes refus que celles que l'app connaît du core.

    `GET /opsys/identite` (`opsys-device-identity-http.ts`) et `POST /tools/invoke` (`tools-invoke-http.ts`,
    `tools-invoke-shared.ts`) ; l'autorisation et l'appel du moteur sont `Moteur.invoquer`, la règle du fork
    refaite en Python par T1.5."""

    def __init__(self, moteur: Moteur, secret_partage: str) -> None:
        self.moteur = moteur
        self.secret_partage = secret_partage
        self.appareils_par_jeton: dict[str, str] = {}  # jeton d'appareil -> deviceId, ajoutés à l'appairage
        passerelle = self

        class Gestionnaire(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                return

            def _repondre(self, statut: int, corps: dict[str, Any]) -> None:
                brut = json.dumps(corps).encode("utf-8")
                self.send_response(statut)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(brut)))
                self.end_headers()
                self.wfile.write(brut)

            def _appelant(self) -> tuple[str | None, str | None]:
                """(nature, appareil) : `appareil` pour un jeton d'appareil, `secret` pour le secret partagé."""
                entete = self.headers.get("authorization", "")
                jeton = entete.removeprefix("Bearer ") if entete.startswith("Bearer ") else None
                if jeton in passerelle.appareils_par_jeton:
                    return "appareil", passerelle.appareils_par_jeton[jeton]
                return ("secret", None) if jeton == passerelle.secret_partage else (None, None)

            def do_GET(self) -> None:
                if self.path != "/opsys/identite":
                    self._repondre(404, {"ok": False})
                    return
                nature, appareil_id = self._appelant()
                if nature is None:
                    self._repondre(401, {"error": {"message": "Unauthorized", "type": "unauthorized"}})
                    return
                refus = None if nature == "appareil" else "device_required"
                appareil = ((moteur._fragment("appareils.json").get("appareils") or {}).get(appareil_id)
                            if appareil_id else None)
                if refus is None and not appareil:
                    refus = "device_unknown"
                if refus is None and appareil["role"] not in (moteur._fragment("roles.json").get("roles") or {}):
                    refus = "role_unknown"
                if refus is not None:
                    self._repondre(403, {"ok": False, "error": {"type": "forbidden", "reason": refus}})
                    return
                self._repondre(200, {"ok": True, "identite": {
                    "appareilId": appareil_id, "personne": appareil["personne"], "role": appareil["role"]}})

            def do_POST(self) -> None:
                if self.path != "/tools/invoke":
                    self._repondre(404, {"ok": False})
                    return
                nature, appareil_id = self._appelant()
                corps = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))) or b"{}")
                if nature != "appareil":
                    self._repondre(401, {"error": {"message": "Unauthorized", "type": "unauthorized"}})
                    return
                if corps.get("deviceId") not in (None, appareil_id):
                    self._repondre(403, {"ok": False, "error": {
                        "type": "tool_call_blocked",
                        "message": "Request body deviceId does not match the authenticated device."}})
                    return
                reponse = moteur.invoquer(appareil_id, corps.get("tool", ""), corps.get("args") or {},
                                          corps.get("idempotencyKey"), corps.get("deviceTimestamp"))
                self._repondre(reponse.statut, reponse.corps)

        self._serveur = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.port = self._serveur.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._fil = threading.Thread(target=self._serveur.serve_forever, daemon=True)

    def __enter__(self) -> PasserelleFactice:
        self._fil.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._serveur.shutdown()
        self._serveur.server_close()
        self._fil.join(timeout=10)


def _instance(tmp_path: Path, *, superviseur: bool) -> scenario.Instance:
    return scenario.creer_instance(tmp_path / "e2e", scenario.RACINE / "core", superviseur=superviseur,
                                   jeton_mcp=JETON_MCP)


def test_le_scenario_joue_de_bout_en_bout_sauf_le_core(tmp_path):
    instance = _instance(tmp_path, superviseur=False)
    with scenario.environnement_du_processus(instance.env), contextlib.ExitStack() as pile:
        scenario.preparer_configuration(instance, pile)
        assert not (instance.dossier_opsys / "metier.json").exists()  # `--moteur direct` : pas de superviseur
        pile.callback(stockage.liberer)
        chantier = scenario.semer_chantier()
        scenario.demarrer_moteur_direct(instance, pile)

        moteur = Moteur(tmp_path, instance.env["OPSYS_BASE_URL"])
        moteur.config_dir = instance.dossier_core
        with PasserelleFactice(moteur, instance.jeton_gateway) as faux:
            instance.port_gateway = faux.port

            def appairer_factice() -> tuple[str, str]:
                """Un appareil « approuvé par le core » : identifiant et jeton viennent de la répétition ; l'attribution
                qui suit (`scenario.attribuer`) est la vraie commande du socle."""
                appareil_id = hashlib.sha256(secrets.token_bytes(16)).hexdigest()
                jeton = f"jeton-appareil-factice-{secrets.token_hex(8)}"
                faux.appareils_par_jeton[jeton] = appareil_id
                return appareil_id, jeton

            mesures = scenario.derouler(instance, chantier, appairer_factice, charger_departements())

    etapes = [m["etape"] for m in mesures]
    assert len(mesures) >= 40 and {m["statut"] for m in mesures} == {200, 401, 403}
    assert all(m["ms"] > 0 for m in mesures)
    assert etapes.count("m4_deposer_fichier") == 3  # la photo en deux blocs, la signature en un
    for attendue in ("m4_completer_intervention", "m6_declarer_materiaux_utilises", "propriétaire : identité",
                     "propriétaire : m9_lister_demandes_approbation", "propriétaire : m9_decider_demande_approbation",
                     "rejeu : m9_decider_demande_approbation", "employé hors portée : m9_decider_demande_approbation"):
        assert attendue in etapes, attendue
    tableau = trajet.resume_latences(mesures)
    assert tableau.count("\n") >= len(mesures) + 2 and "m4_pointer" in tableau
    assert instance.attribues.keys() and {a["personne"] for a in instance.attribues.values()} == {
        scenario.PERSONNE, scenario.PROPRIETAIRE}


def test_le_superviseur_du_core_saurait_lancer_le_moteur(tmp_path):
    """`opsys/metier.json` : la commande, le dossier, le port et l'environnement que le Gateway utilisera. On lance
    ici exactement cette commande, comme le superviseur (T0.10), avec le jeton que le Gateway lui passerait."""
    instance = _instance(tmp_path, superviseur=True)
    with scenario.environnement_du_processus(instance.env), contextlib.ExitStack() as pile:
        scenario.preparer_configuration(instance, pile)
        metier = json.loads((instance.dossier_opsys / "metier.json").read_text(encoding="utf-8"))
        assert metier["actif"] is True and Path(metier["dossier"]).is_dir() and metier["port"] == instance.port_moteur
        assert "OPSYS_MCP_JETON" not in metier["env"]  # le Gateway seul possède le jeton du moteur
        env = {**instance.env, **metier["env"]}
        moteur = scenario.Processus("moteur", metier["commande"], env, Path(metier["dossier"]),
                                    instance.journaux / "moteur.log")
        pile.callback(moteur.arreter)
        pile.callback(stockage.liberer)
        scenario.attendre_http(f"http://127.0.0.1:{metier['port']}/sante", "le moteur répond à /sante", 120, [moteur])
        assert moteur.vivant()


def test_un_processus_qui_s_arrete_fait_echouer_l_attente(tmp_path):
    (tmp_path / "journaux").mkdir()
    court = scenario.Processus("fictif", [sys.executable, "-c", "print('je m arrete')"], {}, tmp_path,
                               tmp_path / "journaux" / "fictif.log")
    with pytest.raises(trajet.EchecE2E, match=r"(?s)fictif s.est arrêté.*je m arrete"):
        scenario.attendre_http("http://127.0.0.1:9/jamais", "un service qui n'existe pas", 30, [court])
    court.arreter()


def test_les_latences_vont_dans_le_journal_le_fichier_et_le_resume_du_job(tmp_path, monkeypatch):
    sommaire = tmp_path / "sommaire.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(sommaire))
    mesures = [{"etape": "identité", "statut": 200, "ms": 3.5}, {"etape": "m4_pointer", "statut": 200, "ms": 90.0}]
    scenario.publier_mesures(tmp_path, mesures)
    assert json.loads((tmp_path / "mesures.json").read_text(encoding="utf-8")) == mesures
    resume = sommaire.read_text(encoding="utf-8")
    assert "| m4_pointer | 200 | 90.0 |" in resume and "2 appels" in resume


def test_un_secret_est_masque_pour_github_et_caviarde_partout_ailleurs(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(scenario, "SECRETS", [])
    scenario.masquer("secret-e2e-fictif-0123")
    assert capsys.readouterr().out == "::add-mask::secret-e2e-fictif-0123\n"
    assert scenario.caviarder("le jeton secret-e2e-fictif-0123 fuit") == "le jeton *** fuit"


def test_le_scenario_range_l_etat_du_core_dans_son_dossier_de_travail_hors_du_profil_opsys(tmp_path):
    """T0.7 lot 3 : `~/.opsys/core` et la migration de Doctor sont ceux du profil `opsys` ; cet E2E n'y passe pas."""
    instance = scenario.creer_instance(tmp_path / "t", scenario.RACINE / "core")

    assert instance.env["OPENCLAW_STATE_DIR"] == str(tmp_path / "t" / "core-etat") == str(instance.dossier_core)
    assert instance.dossier_core.parent == instance.travail  # un dossier de travail, jamais sous le dossier personnel
    assert "OPENCLAW_CONFIG_PATH" not in instance.env  # la configuration est l'openclaw.json de ce dossier
    source = (ICI / "scenario.py").read_text(encoding="utf-8")
    code = "\n".join(ligne for ligne in source.splitlines() if not ligne.lstrip().startswith("#"))
    assert "--profile" not in code and "OPENCLAW_PROFILE" not in code


def test_le_script_refuse_un_core_non_construit(tmp_path, capsys):
    assert scenario.main(["--core", str(tmp_path), "--travail", str(tmp_path / "t")]) == 1
    assert "introuvable" in capsys.readouterr().err
    (tmp_path / "openclaw.mjs").write_text("", encoding="utf-8")
    assert scenario.main(["--core", str(tmp_path), "--travail", str(tmp_path / "t")]) == 1
    assert "pnpm build" in capsys.readouterr().err


def test_un_dossier_de_travail_deja_utilise_est_refuse(tmp_path):
    (tmp_path / "reste-d-une-execution").write_text("x", encoding="utf-8")
    with pytest.raises(trajet.EchecE2E, match="doit être neuf"):
        scenario.creer_instance(tmp_path, scenario.RACINE / "core")


def test_le_fichier_de_l_essai_tient_en_plusieurs_blocs_et_reste_un_png_valide():
    contenu = journee.png_volumineux(fichiers.TAILLE_BLOC_OCTETS + 20_000)
    assert contenu == journee.png_volumineux(fichiers.TAILLE_BLOC_OCTETS + 20_000)  # même graine, mêmes octets
    assert contenu.startswith(b"\x89PNG\r\n\x1a\n") and contenu.endswith(b"IEND\xaeB`\x82")
    assert -(-len(contenu) // fichiers.TAILLE_BLOC_OCTETS) == 2
    assert len(contenu) % fichiers.TAILLE_BLOC_OCTETS != 0  # le dernier bloc est plus court
    ihdr = struct.unpack(">II", contenu[16:24])
    assert ihdr == ((fichiers.TAILLE_BLOC_OCTETS + 20_000) // 3 + 1, 1)  # largeur et hauteur du PNG
