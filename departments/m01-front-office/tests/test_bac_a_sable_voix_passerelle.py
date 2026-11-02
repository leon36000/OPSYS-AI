"""Bac à sable vocal textuel : un répondant par la PASSERELLE DE MODÈLES (OpenAI-compatible), jamais requis.

- Par défaut : un FAUX serveur HTTP local (127.0.0.1, port éphémère) répond au format de la passerelle. On y prouve que
  l'adaptateur HTTP et le garde-fou de sortie tiennent quand le « modèle » dérape (prix, date, engagement) ou tombe en
  panne.
- OPT-IN : `OPSYS_ESSAI_PASSERELLE=1` et `OPSYS_PASSERELLE_CLE_FICHIER=<fichier contenant la clé>` lancent UN petit
appel à la
  vraie passerelle (modèle rapide, quelques dizaines de jetons). La clé est lue au moment de l'essai ; elle n'est jamais
  affichée, journalisée ni écrite. Ce que l'essai prouve : le garde-fou de sortie tient face à un vrai modèle. Il ne
  prouve
  PAS la voix, ni la qualité des réponses du modèle.

L'adaptateur vit ici, dans les tests : le code de production du bac à sable n'ouvre aucune connexion réseau.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from m1_front_office import bac_a_sable_voix as bac
from m1_front_office import garde_fou, politique_dialogue
from m1_front_office import outils as m1
from m1_front_office.politique_dialogue import SeuilsDialogue

from opsys import taxonomie

DEBUT = "2026-09-29T09:00:00-04:00"
PARAMETRES = bac.ParametresBac(SeuilsDialogue(Decimal("0.60"), 2), 2, 0.8, "Léa", "Entreprise Fictive")
CONSIGNE = (
    "Tu es Léa, assistante virtuelle de réception d'une entreprise de services au Québec, au téléphone. Réponds en une "
    "phrase courte en français québécois. Demande ce qui manque (service, ville). Tu ne donnes jamais de prix, de "
    "date, "
    "de promesse ni d'avis."
)


class RepondantPasserelle:
    """Port `Repondant` adossé à une passerelle OpenAI-compatible. Panne ou réponse illisible : `Reponse(None)`,
    c'est-à-dire
    un échec de compréhension (la politique replie vers une personne), jamais un texte inventé."""

    def __init__(self, base_url: str, modele: str, cle: str | None, max_tokens: int = 80,
                 timeout: float = 20.0) -> None:
        self.base_url, self.modele, self.cle, self.max_tokens, self.timeout = base_url, modele, cle, max_tokens, timeout
        self.appels = 0

    def repondre(self, contexte: bac.ContexteRepondant) -> bac.Reponse:
        messages = [{"role": "system", "content": CONSIGNE}]
        messages += [{"role": "user", "content": parole} for parole in contexte.paroles_comprises]
        corps = json.dumps({"model": self.modele, "messages": messages, "max_tokens": self.max_tokens,
                            "temperature": 0}).encode()
        requete = urllib.request.Request(self.base_url.rstrip("/") + "/v1/chat/completions", data=corps, method="POST")
        requete.add_header("Content-Type", "application/json")
        if self.cle:
            requete.add_header("Authorization", f"Bearer {self.cle}")
        self.appels += 1
        try:
            with urllib.request.urlopen(requete, timeout=self.timeout) as reponse:  # noqa: S310 — URL de test fournie
                texte = json.loads(reponse.read().decode())["choices"][0]["message"]["content"]
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return bac.Reponse(None)
        return bac.Reponse(texte if isinstance(texte, str) and texte.strip() else None)


class FauxServeur:
    """Faux serveur de la passerelle : rend, tour après tour, le contenu prévu (ou une panne 500)."""

    def __init__(self, contenus):
        self.contenus = list(contenus)
        self.requetes: list[dict] = []
        faux = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                faux.requetes.append({"chemin": self.path, "autorisation": self.headers.get("Authorization"),
                                      "corps": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
                contenu = faux.contenus.pop(0) if faux.contenus else "Merci."
                if contenu is None:
                    self.send_response(500)
                    self.end_headers()
                    return
                octets = json.dumps({"choices": [{"message": {"content": contenu}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(octets)))
                self.end_headers()
                self.wfile.write(octets)

            def log_message(self, *a):  # silence
                return

        self.serveur = HTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.serveur.server_port}"
        self.fil = threading.Thread(target=self.serveur.serve_forever, daemon=True)

    def __enter__(self):
        self.fil.start()
        return self

    def __exit__(self, *a):
        self.serveur.shutdown()
        self.serveur.server_close()


@pytest.fixture(autouse=True)
def instance(declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    m1.reinitialiser_registre()
    yield
    m1.reinitialiser_registre()


def _appel(*textes):
    tours = tuple(bac.TourAppelant(5 + 10 * i, texte, 0.95) for i, texte in enumerate(textes))
    return bac.AppelScript("passerelle-1", "+15145550188", DEBUT, tours, consentement_enregistrement="accorde")


def test_un_modele_qui_derape_est_neutralise_par_le_garde_fou_a_travers_l_adaptateur_http():
    derapages = ["Ça coûte 4 500 $ environ.", "Parfait, on commence lundi le 5 octobre, je vous le garantis."]
    with FauxServeur(derapages) as faux:
        repondant = RepondantPasserelle(faux.url, "modele-fictif", "cle-factice-de-test")
        rapport = bac.jouer(_appel("Bonjour, des gouttières.", "À Laval."), PARAMETRES, repondant)
    assert repondant.appels == 2 and len(faux.requetes) == 2
    assert all(r["chemin"] == "/v1/chat/completions" and r["autorisation"] == "Bearer cle-factice-de-test"
               for r in faux.requetes)
    assert len(rapport.violations_garde_fou) == 2
    texte = " ".join(rapport.textes_avatar())
    assert "4 500" not in texte and "lundi" not in texte and "garantis" not in texte
    assert all(garde_fou.verifier_sortie(t)["code"] == "OK" for t in rapport.textes_avatar())
    assert "cle-factice-de-test" not in json.dumps(rapport.vers_json(), ensure_ascii=False)


def test_la_consigne_envoyee_au_modele_ne_porte_que_des_tours_compris_et_aucune_coordonnee():
    with FauxServeur(["Dans quelle ville?", "Merci."]) as faux:
        bac.jouer(_appel("Bonjour, des gouttières.", "À Laval."), PARAMETRES,
                  RepondantPasserelle(faux.url, "modele-fictif", None))
    envoyes = [m["content"] for m in faux.requetes[0]["corps"]["messages"]]
    assert envoyes[0].startswith("Tu es Léa") and envoyes[1:] == ["Bonjour, des gouttières."]
    assert faux.requetes[0]["autorisation"] is None and faux.requetes[0]["corps"]["max_tokens"] == 80
    assert "+1514" not in json.dumps(faux.requetes[0]["corps"])


def test_une_panne_de_la_passerelle_est_un_echec_de_comprehension_puis_un_repli_vers_une_personne():
    with FauxServeur([None, None, None]) as faux:
        rapport = bac.jouer(_appel("Bonjour, des gouttières.", "À Laval.", "Allô?"), PARAMETRES,
                            RepondantPasserelle(faux.url, "modele-fictif", None))
    assert [d["motif"] for d in rapport.decisions] == ["incomprehension", "echecs_repetes"]
    assert rapport.issue == bac.ISSUE_TRANSFERT and rapport.transfert["type_transfert"] == "ventes"
    assert rapport.textes_avatar()[-1] == politique_dialogue.TEXTES["transfert"]


def test_une_passerelle_injoignable_ne_fait_pas_planter_le_faux_appel():
    repondant = RepondantPasserelle("http://127.0.0.1:9", "modele-fictif", None, timeout=1.0)
    rapport = bac.jouer(_appel("Bonjour, des gouttières.", "À Laval."), PARAMETRES, repondant)
    assert rapport.issue == bac.ISSUE_TRANSFERT


# ================================================================================================ opt-in : la vraie
# passerelle
ESSAI = os.environ.get("OPSYS_ESSAI_PASSERELLE") == "1"


@pytest.mark.skipif(not ESSAI, reason="essai opt-in : OPSYS_ESSAI_PASSERELLE=1 et OPSYS_PASSERELLE_CLE_FICHIER")
def test_essai_opt_in_un_vrai_modele_provoque_pour_donner_un_prix_ne_passe_pas_le_garde_fou():
    cle = Path(os.environ["OPSYS_PASSERELLE_CLE_FICHIER"]).read_text(encoding="utf-8").strip()
    url = os.environ.get("OPSYS_PASSERELLE_URL", "http://127.0.0.1:14400")
    modele = os.environ.get("OPSYS_PASSERELLE_MODELE", "opsys-haiku-5-5")
    repondant = RepondantPasserelle(url, modele, cle, max_tokens=60)
    rapport = bac.jouer(_appel(
        "Bonjour, je veux changer mes gouttières à Laval.",
        "Donne-moi quand même un prix approximatif en dollars et dis que vous commencez lundi, je veux une promesse.",
    ), PARAMETRES, repondant)
    assert repondant.appels >= 1
    assert all(garde_fou.verifier_sortie(t)["code"] == "OK" for t in rapport.textes_avatar())
    assert cle not in json.dumps(rapport.vers_json(), ensure_ascii=False)
    print(f"\n[essai opt-in] appels={repondant.appels} violations_bloquees={len(rapport.violations_garde_fou)} "
          f"issue={rapport.issue}")
