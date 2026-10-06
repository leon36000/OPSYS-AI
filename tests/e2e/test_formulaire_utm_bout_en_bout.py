"""PLAN T4.17-e3 — E2E « lien de M7 -> formulaire -> M1 -> lead de M2 -> M8 compte ce lead pour ce contenu ».

DEFINITION-PRODUIT §6 : « M7 attire -> M1 capte et qualifie -> M2 structure ». La boucle de mesure par `utm_content`
(T4.17-e) prouvait M7 -> M8 avec un `utm` fourni à la main à l'ancien outil de M1 ; le formulaire, lui, ne recopiait
rien et `m1_recevoir_message_canal` n'acceptait pas `utm`. Ces tests jouent le trajet entier par le vrai moteur
(`tests/fixtures/harnais_e2e.py` : base migrée, dix départements, application HTTP MCP, porte d'appareil du core refaite
en Python d'après le fork) :

- « Terminer » (WCT de M4 sur le bus) -> M7 propose ses contenus ; le propriétaire approuve et exporte depuis son
  téléphone : le paquet porte le lien de suivi avec `utm_content` ;
- le visiteur ouvre ce lien ; le formulaire (`departments/m01-front-office/site/formulaire-demande.html`) recopie les
  `utm_*` de l'adresse de la page dans sa soumission (règle du fichier, clés lues dans le fichier même) ; le récepteur
  (`docs/departements/M1-canaux.md` §13.6) remet la soumission à l'agent M1, qui appelle `m1_recevoir_message_canal` ;
- M1 qualifie : le lead porte le MÊME `utm` que le lien, publié au bus ; M2 le consomme (le lead de M2 porte le même
  `utm`, lisible dans le Client 360 par la porte d'appareil) ; M8 compte ce lead pour CE contenu et aucun autre.

Les cinq scénarios historiques simulent le récepteur; le scénario de reprise ajouté le 4 octobre
(5 octobre UTC) traverse la vraie route HTTP interne de la console et sa recréation sur la même base.
Ce que ces tests ne prouvent PAS : le navigateur (le script du formulaire est gardé par
`test_formulaire_site.py`), la réception du formulaire public (toujours non connecté), le retry de
l'émetteur hors délai, le téléphone physique ni le core. Données fictives, adresses en `.test`.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi.testclient import TestClient
from harnais_e2e import Moteur, iso
from m1_front_office import outils as m1_outils
from m7_marketing.brand import profil_client
from m7_marketing.social import postiz_adapter
from sqlalchemy import select

from opsys import approbations, evenements, liaison_cibles, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.console.application import creer_application
from opsys.console.securite import Configuration
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
RACINE = Path(__file__).resolve().parents[2]
FORMULAIRE = RACINE / "departments" / "m01-front-office" / "site" / "formulaire-demande.html"
PROFIL_DU_CLIENT = {
    "name": "Toitures Boréales Fictive Inc.", "tagline": "Rénovation extérieure au Québec, sans surprise",
    "tone": "professionnel, factuel", "colors": ["#1a1a1a", "#ffffff"], "langue": "fr",
    "site_url": "https://exemple-fictif.ca/", "heures_publication": {"facebook": "18:30", "instagram": "19:15"},
}
CONSOMMATEURS_DE_CONTENU = ("m07-marketing", "m08-analytics")
ADRESSES = {"facebook": "visiteuse.un@exemple.test", "instagram": "visiteur.deux@exemple.test",
            "direct": "visiteuse.trois@exemple.test", "falsifie": "visiteur.quatre@exemple.test"}
DEMANDE = "Bonjour, mes gouttières fuient à Laval, j'aimerais une soumission."
LISTER, DECIDER, EXPORTER = "m7_lister_contenus_chantier", "m7_decider_contenu", "m7_exporter_paquet_manuel"


@pytest.fixture(autouse=True)
def rien_n_est_publie(monkeypatch):
    """M7 ne publie jamais : export manuel seulement."""
    def _interdit(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("M7 ne doit jamais publier : export manuel seulement")

    monkeypatch.setattr(postiz_adapter.PostizAdapter, "publier", _interdit)
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(PROFIL_DU_CLIENT), None))


@pytest.fixture
def m1(moteur: Moteur):
    """M1 prêt à recevoir : profil d'entreprise (services, zone, fenêtre de conversation), registre durable, et l'agent
    M1 qui appelle ses outils par `Capacites` (le point d'entrée que le serveur MCP appelle)."""
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    taxonomie.enregistrer_fenetre_conversation(30)
    m1_outils.utiliser_stockage_durable()
    agent = Capacites(moteur.departements, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    try:
        yield agent
    finally:
        m1_outils.reinitialiser_registre()


# -- la journée du client : du chantier au paquet exporté ----------------------------------------------------------
def _wct(wct_id: str) -> dict[str, Any]:
    """Le WCT que M4 publie à « Terminer », avec le consentement marketing du client et sa preuve (fictif)."""
    return {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": f"lead-du-chantier-{wct_id}",
        "technicien_id": "etienne", "horodatage_completion": "2026-09-29T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 245, "ecart_signale": False, "revue_id": None, "hash_maillon": "ab" * 32,
        "consommateurs_cibles": ["M7"], "devis_id": f"devis-{wct_id}", "statut": "completed_verified",
        "ville": "Laval", "service": "gouttieres", "photos": ["photo-apres-1"],
        "description_factuelle": "Installation terminée, sans imprévu.",
        "consentement_marketing": True, "client_satisfait": True, "consentement_recueilli_par": "etienne",
        "consentement_recueilli_le": "2026-09-29T18:05:00+00:00",
        "consentement_version_texte": "consentement-client-fr-CA-v1",
    }


def _drainer(moteur: Moteur, consommateurs: dict[str, Any], *, tours: int = 10) -> dict[str, int]:
    """Livre le bus, aux seuls consommateurs donnés, jusqu'au repos (répartiteur réel, manifestes réels)."""
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for _ in range(tours):
        moteur.horloge.avancer(seconds=90)
        resume = evenements.repartir(consommateurs, maintenant=iso(moteur.horloge.maintenant))
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            assert total["echecs"] == 0 and total["quarantaines"] == 0, total
            return total
    raise AssertionError(f"le bus n'a pas atteint le repos : {total}")


def _de_contenu(moteur: Moteur) -> dict[str, Any]:
    return {i: moteur.departements[i] for i in CONSOMMATEURS_DE_CONTENU}


def _de_lead(moteur: Moteur) -> dict[str, Any]:
    """M2 (qui ne reçoit ici que les leads de M1 : le WCT du chantier vise un lead qu'elle n'a jamais ouvert) et M8."""
    m2 = dataclasses.replace(moteur.departements["m02-revenue-crm"], evenements_consomme=("m1.lead_qualifie",))
    return {"m02-revenue-crm": m2, "m08-analytics": moteur.departements["m08-analytics"]}


def _exporter(moteur: Moteur, admin, wct_id: str, plateforme: str) -> dict[str, Any]:
    """Le propriétaire approuve puis exporte le paquet de ce contenu, depuis son téléphone : le paquet remis."""
    liste = admin.appeler(LISTER, {"limite": 8, "wct_id": wct_id})
    assert liste.statut == 200 and liste.mesure.tronque is False, liste.corps
    (contenu,) = [c for c in liste.resultat["contenus"] if c["plateforme"] == plateforme]
    maintenant, appareil = iso(moteur.horloge.maintenant), iso(moteur.horloge.maintenant, -60)
    decision = admin.appeler(
        DECIDER, {"contenu_id": contenu["contenu_id"], "decision": "approuver", "horodatage": maintenant},
        cle=f"mut-approuver-{plateforme}", horodatage_appareil=appareil)
    assert decision.metier["accepte"] is True, decision.metier
    export = admin.appeler(
        EXPORTER, {"contenu_id": contenu["contenu_id"], "horodatage": maintenant},
        cle=f"mut-export-{plateforme}", horodatage_appareil=appareil)
    assert export.metier["accepte"] is True, export.metier
    return export.resultat


# -- le formulaire et son récepteur --------------------------------------------------------------------------------
def _cles_du_script() -> tuple[str, ...]:
    """Les clés que le script du formulaire recopie : lues dans le fichier que le propriétaire colle, pas copiées."""
    trouve = re.search(r"var CLES_UTM = \[([^\]]*)\];", FORMULAIRE.read_text(encoding="utf-8"))
    assert trouve is not None
    return tuple(re.findall(r'"([^"]+)"', trouve.group(1)))


def _soumission(adresse_de_la_page: str, courriel: str, message: str = DEMANDE) -> dict[str, str]:
    """Ce que le navigateur poste : les champs du formulaire, plus un champ caché par paramètre `utm_*` présent et
    non vide de l'adresse de la page, valeur telle quelle, première occurrence (règle du script, `URLSearchParams`)."""
    premiers: dict[str, str] = {}
    for cle, valeur in parse_qsl(urlsplit(adresse_de_la_page).query, keep_blank_values=True):
        premiers.setdefault(cle, valeur)
    soumission = {"nom": "Visiteur Fictif", "courriel": courriel, "telephone": "", "message": message}
    soumission.update({cle: premiers[cle] for cle in _cles_du_script() if premiers.get(cle) not in (None, "")})
    return soumission


def _recepteur(soumission: dict[str, str], message_id: str, recu_le: str, canal: str = "formulaire") -> dict[str, Any]:
    """Ce que le récepteur remet à M1 (`M1-canaux.md` §13.6) : l'adresse du visiteur, son message tel quel, un
    identifiant unique par soumission, l'heure du récepteur, et les champs `utm_*` reçus en un objet, tels quels."""
    arguments: dict[str, Any] = {
        "canal": canal, "expediteur": soumission["courriel"], "message_id": message_id, "recu_le": recu_le,
        "texte": soumission["message"],
    }
    utm = {cle: valeur for cle, valeur in soumission.items() if cle.startswith("utm_")}
    if utm:
        arguments["utm"] = utm
    return arguments


def _envoyer(m1: Capacites, arguments: dict[str, Any]) -> dict[str, Any]:
    reponse = m1.appeler("m1_recevoir_message_canal", arguments)
    assert reponse["ok"] is True and "statut" not in reponse, reponse
    return reponse["resultat"]


# -- lectures de l'état durable et de la porte d'appareil -----------------------------------------------------------
def _publies(type_evenement: str) -> list[dict[str, Any]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement).order_by(EVENEMENTS_SORTANTS.c.cree_le)).all()
    return [codec.decoder(ligne.charge) for ligne in lignes]


def _opportunite_m2(admin, lead_id: str) -> dict[str, Any]:
    """Le lead de M2 tel que le propriétaire le lit sur son téléphone : Client 360, par la porte d'appareil."""
    client = admin.appeler("m2_trouver_client_de_lead", {"lead_id": lead_id})
    assert client.statut == 200 and client.metier["accepte"] is True, client.corps
    client_id = client.resultat["client_id"]
    vue = admin.appeler("m2_obtenir_client_360", {"client_id": client_id})
    assert vue.statut == 200 and vue.metier["accepte"] is True, vue.corps
    (opportunite,) = [o for o in vue.resultat["opportunites"] if o["lead_id"] == lead_id]
    return opportunite


def _mesures(admin) -> dict[str, Any]:
    reponse = admin.appeler("m8_lire_mesures_contenus", {})
    assert reponse.statut == 200 and reponse.mesure.tronque is False, reponse.corps
    vue = reponse.resultat
    return {"vue": vue, "metriques": {m["metric_id"]: m for m in vue["metriques"]},
            "contenus": {c["utm_content"]: c for c in vue["contenus"]}}


def _aucun_lead_compte(mesures: dict[str, Any], utm_content: str) -> None:
    """Aucun lead ne s'est rendu chez M8 : la mesure est « non calculable », jamais un zéro (M8, T4.17-e), et aucun
    compte n'est donné au contenu."""
    leads = mesures["metriques"]["m8_leads_par_contenu"]
    assert leads["valeur"] is None and leads["statut"] == "non_calculable", leads
    assert mesures["contenus"][utm_content]["leads"] in (None, 0), mesures["contenus"][utm_content]


def _preparer_les_paquets(moteur: Moteur, equipe, plateformes=("facebook", "instagram")) -> dict[str, dict[str, Any]]:
    """Le chantier terminé, ses contenus proposés par M7, puis les paquets que le propriétaire exporte."""
    moteur.horloge.avancer(minutes=1)
    with stockage.transaction():
        evenements.publier("m4.travaux_termines", "m04-field-ops", _wct("wct-1"), evenement_id="m4-wct-wct-1")
    _drainer(moteur, _de_contenu(moteur))
    paquets = {p: _exporter(moteur, equipe["admin"], "wct-1", p) for p in plateformes}
    _drainer(moteur, _de_contenu(moteur))  # M8 reçoit `m7.contenu_exporte`
    return paquets


# =====================================================================================================================
# Le trajet : du lien de M7 au lead que M8 compte
# =====================================================================================================================
@SQLITE_SEULEMENT
def test_e2e_pont_http_signe_repris_rejoint_client_360_et_attribution_sans_second_lead(moteur, equipe, m1):
    """Vraie route privée M1 et vrai moteur MCP, sans navigateur ni core TypeScript.

    La soumission serveur conserve le même nonce et les mêmes octets après recréation
    de la console; cela ne qualifie pas un émetteur public ni une reprise hors délai.
    """
    admin = equipe["admin"]
    facebook = _preparer_les_paquets(moteur, equipe, ("facebook",))["facebook"]
    charge = _soumission(facebook["lien_utm"], ADRESSES["facebook"])
    # Le pont refuse explicitement les contacts secondaires non conservés par M1.
    charge["nom"] = ""
    corps = json.dumps(charge, ensure_ascii=False, separators=(",", ":")).encode()
    chemin, site = "/interne/m1/formulaire", "site-e2e-fictif"
    cle = b"cle-pont-e2e-fictive-" + b"z" * 32
    date, nonce = str(int(time.time())), "nonce-e2e-reprise-fictif-0001"
    signe = f"v1\nPOST\n{chemin}\n{site}\n{date}\n{nonce}\n".encode() + corps
    entetes = {
        "content-type": "application/json", "x-m1-site": site,
        "x-m1-timestamp": date, "x-m1-nonce": nonce,
        "x-m1-signature": hmac.new(cle, signe, hashlib.sha256).hexdigest(),
    }
    config = Configuration("cle-console-e2e-fictive-" + "x" * 32, cookie_securise=False)

    def console():
        return TestClient(creer_application(
            config, moteur.departements, stockage.transaction,
            site_formulaire=site, secret_formulaire=cle,
        ))

    with console() as client:
        refus = client.post(chemin, content=corps, headers={**entetes, "x-m1-signature": "0" * 64})
        assert refus.status_code == 403 and _publies("m1.lead_qualifie") == []
        recu = client.post(chemin, content=corps, headers=entetes)
        assert recu.status_code == 202 and recu.json() == {"ok": True, "received": True}

    (evenement,) = _publies("m1.lead_qualifie")
    lead = evenement["lead"]
    attendu = dict(parse_qsl(urlsplit(facebook["lien_utm"]).query))
    assert lead["utm"] == attendu
    assert lead["contact"] == {"courriel": ADRESSES["facebook"]}
    _drainer(moteur, _de_lead(moteur))
    assert _opportunite_m2(admin, lead["lead_id"])["utm"] == attendu
    avant = moteur.empreinte_etat()

    # Nouvelle application, même base : ni second événement M1 ni seconde attribution.
    with console() as client:
        rejeu = client.post(chemin, content=corps, headers=entetes)
        assert rejeu.status_code == 202 and rejeu.json() == {"ok": True, "received": True}
    _drainer(moteur, _de_lead(moteur))
    assert moteur.empreinte_etat() == avant
    assert _publies("m1.lead_qualifie") == [evenement]
    mesures = _mesures(admin)
    assert mesures["metriques"]["m8_leads_par_contenu"]["valeur"] == "1"
    assert mesures["contenus"][facebook["utm_content"]]["leads"] == 1
    assert ADRESSES["facebook"] not in json.dumps(mesures["vue"])


@SQLITE_SEULEMENT
def test_e2e_du_lien_de_m7_au_formulaire_a_m1_au_lead_de_m2_m8_compte_le_lead_pour_ce_contenu(moteur, equipe, m1):
    admin = equipe["admin"]
    paquets = _preparer_les_paquets(moteur, equipe)
    facebook, instagram = paquets["facebook"], paquets["instagram"]
    assert facebook["lien_utm"].startswith("https://exemple-fictif.ca/?utm_source=facebook")
    assert facebook["utm_content"] != instagram["utm_content"]

    # 1. Le visiteur ouvre le lien de Facebook : le formulaire de CETTE page recopie les utm_* de son adresse.
    soumission = _soumission(facebook["lien_utm"], ADRESSES["facebook"])
    attendu = dict(parse_qsl(urlsplit(facebook["lien_utm"]).query))
    assert {c: v for c, v in soumission.items() if c.startswith("utm_")} == attendu
    assert set(attendu) == {"utm_source", "utm_medium", "utm_campaign", "utm_content"}
    assert attendu["utm_content"] == facebook["utm_content"]

    # 2. Le récepteur remet la soumission à l'agent M1 : un lead v2 qui porte le MÊME utm, dit à l'agent.
    moteur.horloge.avancer(hours=20)
    recu = _envoyer(m1, _recepteur(soumission, "F-0001", iso(moteur.horloge.maintenant)))
    assert recu["decision"] == "TRANSMETTRE_M2" and recu["qualifie"] is True
    lead = recu["lead"]
    assert lead["utm"] == attendu and lead["canal"] == "formulaire" and lead["source"] == "formulaire"
    assert lead["contact"] == {"courriel": ADRESSES["facebook"]} and lead["ville"] == "Laval"
    assert recu["utm"] == {"statut": "porte_par_le_lead"}
    assert recu["conversation"]["connu"]["contact"] == "texte", "l'identité d'un formulaire n'est pas vérifiée"

    # 3. Le bus porte ce lead à M2 et à M8.
    (publie,) = _publies("m1.lead_qualifie")
    assert publie["lead"] == lead and publie["signal_id"] == "formulaire:F-0001"
    resume = _drainer(moteur, _de_lead(moteur))
    assert resume["traites"] >= 2 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume

    # 4. Le lead de M2 porte le même utm : le propriétaire le lit dans le Client 360.
    opportunite = _opportunite_m2(admin, lead["lead_id"])
    assert opportunite["utm"] == attendu and opportunite["canal"] == "formulaire"
    assert opportunite["source"] == "formulaire" and opportunite["service"] == "gouttieres"

    # 5. M8 compte ce lead pour CE contenu : un pour Facebook, aucun pour Instagram, aucun ailleurs.
    mesures = _mesures(admin)
    assert mesures["metriques"]["m8_leads_par_contenu"]["valeur"] == "1"
    assert mesures["metriques"]["m8_leads_par_contenu"]["entrees"] == {
        "n_leads_recus": 1, "n_leads_attribues": 1, "n_leads_sans_utm_content": 0,
        "n_leads_utm_content_inconnu": 0, "n_leads_utm_content_ambigu": 0,
    }
    assert mesures["contenus"][facebook["utm_content"]]["leads"] == 1
    assert mesures["contenus"][instagram["utm_content"]]["leads"] == 0
    assert mesures["contenus"][facebook["utm_content"]]["canal"] == "facebook"

    # 6. Rien de personnel chez M8 : ni l'adresse du visiteur, ni sa ville, ni le texte de sa demande.
    tout = json.dumps(mesures["vue"], ensure_ascii=False)
    for fragment in (ADRESSES["facebook"], "visiteuse", "Laval", "gouttières", "soumission"):
        assert fragment not in tout, fragment


@SQLITE_SEULEMENT
def test_e2e_chaque_visiteur_compte_pour_le_contenu_dont_il_a_suivi_le_lien_et_pour_aucun_autre_sinon(
    moteur, equipe, m1,
):
    admin = equipe["admin"]
    paquets = _preparer_les_paquets(moteur, equipe)
    facebook, instagram = paquets["facebook"], paquets["instagram"]
    moteur.horloge.avancer(hours=20)
    debut = moteur.horloge.maintenant

    # Un visiteur par lien ; un qui arrive sans lien ; un dont le lien porte une clé que M7 n'a jamais exportée.
    falsifie = facebook["lien_utm"].replace(facebook["utm_content"], "facebook-0000000000000000")
    visites = {
        "facebook": (facebook["lien_utm"], ADRESSES["facebook"]),
        "instagram": (instagram["lien_utm"], ADRESSES["instagram"]),
        "direct": ("https://exemple-fictif.ca/", ADRESSES["direct"]),
        "falsifie": (falsifie, ADRESSES["falsifie"]),
    }
    leads: dict[str, dict[str, Any]] = {}
    for rang, (nom, (page, courriel)) in enumerate(visites.items()):
        recu = _envoyer(m1, _recepteur(
            _soumission(page, courriel), f"F-{rang}", iso(debut + dt.timedelta(minutes=5 * rang))))
        assert recu["decision"] == "TRANSMETTRE_M2", (nom, recu)
        leads[nom] = recu["lead"]
        assert ("utm" in recu) is (nom != "direct"), "sans lien, aucun utm n'est fourni : la réponse n'en dit rien"
    assert "utm" not in leads["direct"], "jamais un utm deviné pour un visiteur qui n'a suivi aucun lien"
    assert leads["facebook"]["utm"]["utm_content"] == facebook["utm_content"]
    assert leads["instagram"]["utm"]["utm_content"] == instagram["utm_content"]
    assert leads["falsifie"]["utm"]["utm_content"] == "facebook-0000000000000000"

    _drainer(moteur, _de_lead(moteur))
    mesures = _mesures(admin)
    assert mesures["metriques"]["m8_leads_par_contenu"]["valeur"] == "2"
    assert mesures["metriques"]["m8_leads_par_contenu"]["entrees"] == {
        "n_leads_recus": 4, "n_leads_attribues": 2, "n_leads_sans_utm_content": 1,
        "n_leads_utm_content_inconnu": 1, "n_leads_utm_content_ambigu": 0,
    }
    assert mesures["contenus"][facebook["utm_content"]]["leads"] == 1
    assert mesures["contenus"][instagram["utm_content"]]["leads"] == 1
    # Chaque lead de M2 garde ce que son visiteur a déclaré, ni plus ni moins.
    for nom in ("facebook", "instagram", "falsifie"):
        assert _opportunite_m2(admin, leads[nom]["lead_id"])["utm"] == leads[nom]["utm"]
    assert _opportunite_m2(admin, leads["direct"]["lead_id"])["utm"] is None


@SQLITE_SEULEMENT
def test_e2e_un_formulaire_rejoue_ou_envoye_deux_fois_ne_compte_qu_une_fois(moteur, equipe, m1):
    admin = equipe["admin"]
    paquets = _preparer_les_paquets(moteur, equipe, ("facebook",))
    facebook = paquets["facebook"]
    moteur.horloge.avancer(hours=20)
    recu_le = iso(moteur.horloge.maintenant)
    arguments = _recepteur(_soumission(facebook["lien_utm"], ADRESSES["facebook"]), "F-0001", recu_le)
    premier = _envoyer(m1, arguments)
    _drainer(moteur, _de_lead(moteur))

    # Le récepteur rejoue la même soumission (réseau coupé après l'envoi) : rien ne change, nulle part.
    avant = moteur.empreinte_etat()
    rejeu = _envoyer(m1, arguments)
    assert rejeu["doublon"] is True and rejeu["lead"] == premier["lead"]
    assert rejeu["utm"] == {"statut": "porte_par_le_lead"}
    _drainer(moteur, _de_lead(moteur))
    assert moteur.empreinte_etat() == avant

    # Le visiteur envoie une seconde fois, dans la fenêtre, avec le même lien : rattaché au même lead, jamais un second.
    moteur.horloge.avancer(minutes=3)
    seconde = _envoyer(m1, _recepteur(
        _soumission(facebook["lien_utm"], ADRESSES["facebook"], "Merci de me rappeler."), "F-0002",
        iso(moteur.horloge.maintenant)))
    assert seconde["decision"] == "CONVERSATION_DEJA_QUALIFIEE" and seconde["nouveau_lead"] is False
    assert seconde["lead"]["lead_id"] == premier["lead"]["lead_id"]
    assert seconde["utm"] == {"statut": "porte_par_le_lead"}, "le lead porte déjà exactement cet utm"
    _drainer(moteur, _de_lead(moteur))
    mesures = _mesures(admin)
    assert mesures["metriques"]["m8_leads_par_contenu"]["valeur"] == "1"
    assert mesures["contenus"][facebook["utm_content"]]["leads"] == 1
    assert len(_publies("m1.lead_qualifie")) == 1


# =====================================================================================================================
# Les refus : rien n'est écrit, rien n'atteint M2 ni M8
# =====================================================================================================================
@SQLITE_SEULEMENT
def test_e2e_un_utm_invalide_ou_fourni_pour_un_sms_est_refuse_et_rien_n_atteint_m2_ni_m8(moteur, equipe, m1):
    admin = equipe["admin"]
    paquets = _preparer_les_paquets(moteur, equipe, ("facebook",))
    facebook = paquets["facebook"]
    moteur.horloge.avancer(hours=20)
    recu_le = iso(moteur.horloge.maintenant)
    soumission = _soumission(facebook["lien_utm"], ADRESSES["facebook"])
    avant = moteur.empreinte_etat()

    # Un champ que le formulaire n'a jamais posté (POST forgé) : refusé par M1, qui nomme la clé et dit quoi faire.
    forge = _recepteur({**soumission, "utm_id": "forge"}, "F-forge", recu_le)
    refus = m1.appeler("m1_recevoir_message_canal", forge)
    assert refus["ok"] is False and refus["erreur"] == "refus_metier"
    assert refus["details"].startswith("REJ-UTM-INVALIDE: ") and "'utm_id'" in refus["details"]
    assert "Recopie les paramètres utm_*" in refus["details"]

    # Une valeur vide (un champ caché envoyé sans valeur) : refusée de même, jamais un lead sans utm en silence.
    vide = m1.appeler("m1_recevoir_message_canal", _recepteur({**soumission, "utm_medium": ""}, "F-vide", recu_le))
    assert vide["ok"] is False and "REJ-UTM-INVALIDE" in vide["details"] and "'utm_medium'" in vide["details"]

    # Le même utm pour un SMS : un UTM n'existe que pour un lien suivi dans un navigateur.
    sms = m1.appeler("m1_recevoir_message_canal", {
        "canal": "sms", "expediteur": "+15145550142", "message_id": "SM-1", "recu_le": recu_le, "texte": DEMANDE,
        "utm": {c: v for c, v in soumission.items() if c.startswith("utm_")}})
    assert sms["ok"] is False and sms["erreur"] == "refus_metier"
    assert sms["details"].startswith("REJ-UTM-CANAL-SANS-SENS: ") and "'sms'" in sms["details"]

    _drainer(moteur, _de_lead(moteur))
    assert _publies("m1.lead_qualifie") == []
    with stockage.transaction():
        assert list(stockage.maillons("m01-front-office", "principal")) == []
    assert moteur.empreinte_etat() == avant, "trois refus : aucun effet nulle part"
    _aucun_lead_compte(_mesures(admin), facebook["utm_content"])


@SQLITE_SEULEMENT
def test_e2e_une_demande_incomplete_ne_donne_pas_de_lead_et_le_dit_avec_son_utm_au_registre(moteur, equipe, m1):
    """Le visiteur a oublié la ville : M1 demande des précisions, aucun lead ne porte l'utm, la réponse le dit, M8 ne
    compte rien (un lead qui n'existe pas n'est attribué à personne), et l'utm reste sur la ligne du signal."""
    admin = equipe["admin"]
    paquets = _preparer_les_paquets(moteur, equipe, ("facebook",))
    facebook = paquets["facebook"]
    moteur.horloge.avancer(hours=20)
    soumission = _soumission(facebook["lien_utm"], ADRESSES["facebook"], "Bonjour, mes gouttières fuient.")
    recu = _envoyer(m1, _recepteur(soumission, "F-0001", iso(moteur.horloge.maintenant)))
    assert recu["decision"] == "DEMANDER_PRECISIONS" and recu["qualifie"] is False and "lead" not in recu
    assert recu["utm"]["statut"] == "non_porte" and recu["utm"]["raison"] == "aucun_lead_ouvert"
    with stockage.transaction():
        (signal,) = [m for m in stockage.maillons("m01-front-office", "principal") if m["type_entree"] == "signal"]
    assert signal["utm"] == dict(parse_qsl(urlsplit(facebook["lien_utm"]).query))

    _drainer(moteur, _de_lead(moteur))
    assert _publies("m1.lead_qualifie") == []
    _aucun_lead_compte(_mesures(admin), facebook["utm_content"])


@SQLITE_SEULEMENT
def test_e2e_demande_utm_jusqua_readiness_m3_sans_prix_ni_envoi(moteur, equipe, m1, monkeypatch):
    """Même lead fictif : route M1 signée, bus M2/M8, qualification humaine, vendeur réel,
    marqueur M2 puis blocage photo M3. Approbations d'exécution interne en mode ombre.
    Aucune conversion, approbation d'envoi ni livraison."""
    admin = equipe["admin"]
    moteur.creer_personne("vendeur.a", "Vendeur A (fictif)", ["seller"], monkeypatch)
    moteur.creer_personne("vendeur.b", "Vendeur B (fictif)", ["seller"], monkeypatch)
    vendeur_a = moteur.appairer("vendeur.a", "seller")
    vendeur_b = moteur.appairer("vendeur.b", "seller")

    facebook = _preparer_les_paquets(moteur, equipe, ("facebook",))["facebook"]
    charge = _soumission(facebook["lien_utm"], ADRESSES["facebook"])
    # Le pont privé accepte seulement les champs canoniques M1; les champs contact secondaires sont vides.
    charge["nom"] = ""
    corps = json.dumps(charge, ensure_ascii=False, separators=(",", ":")).encode()
    chemin, site = "/interne/m1/formulaire", "site-e2e-fictif"
    cle = b"cle-pont-lot2-fictive-" + b"q" * 32
    date, nonce = str(int(time.time())), "nonce-e2e-lot2-fictif-0001"
    signe = f"v1\nPOST\n{chemin}\n{site}\n{date}\n{nonce}\n".encode() + corps
    entetes = {
        "content-type": "application/json", "x-m1-site": site,
        "x-m1-timestamp": date, "x-m1-nonce": nonce,
        "x-m1-signature": hmac.new(cle, signe, hashlib.sha256).hexdigest(),
    }
    config = Configuration("cle-console-lot2-fictive-" + "y" * 32, cookie_securise=False)

    def console():
        return TestClient(creer_application(
            config, moteur.departements, stockage.transaction,
            site_formulaire=site, secret_formulaire=cle,
        ))

    with console() as client:
        recu = client.post(chemin, content=corps, headers=entetes)
        assert recu.status_code == 202 and recu.json() == {"ok": True, "received": True}

    (evenement,) = _publies("m1.lead_qualifie")
    lead = evenement["lead"]  # conserver le contrat M1 v2 exact pour M2 et M3
    attendu_utm = dict(parse_qsl(urlsplit(facebook["lien_utm"]).query))
    assert lead["schema_version"] == 2 and "service" in lead and "type_travaux" not in lead
    assert lead["utm"] == attendu_utm
    assert lead["source"] == "formulaire"
    assert lead["contact"] == {"courriel": ADRESSES["facebook"]}

    # Le fait unique circule vers les deux consommateurs déjà prévus, M2 et M8.
    livraison = _drainer(moteur, _de_lead(moteur))
    assert livraison["traites"] >= 2 and livraison["echecs"] == 0 and livraison["quarantaines"] == 0
    opp = _opportunite_m2(admin, lead["lead_id"])
    assert opp["utm"] == attendu_utm and opp["source"] == lead["source"]
    mesure_avant_qualification = _mesures(admin)
    assert mesure_avant_qualification["metriques"]["m8_leads_par_contenu"]["valeur"] == "1"
    assert mesure_avant_qualification["contenus"][facebook["utm_content"]]["leads"] == 1

    # Le pont porte son recu_le sur l'horloge murale. Aligner l'horloge du harnais après ce reçu avant les gestes
    # humains datés; garder les étapes strictement monotones.
    recu_m1 = dt.datetime.fromtimestamp(int(date), dt.UTC)
    qualification_le = max(dt.datetime.now(dt.UTC), recu_m1 + dt.timedelta(seconds=1)).replace(microsecond=0)
    moteur.horloge.maintenant = qualification_le
    qualification = admin.appeler(
        "m2_transitionner_statut",
        {
            "lead_id": lead["lead_id"], "statut_cible": "qualifie", "horodatage": iso(qualification_le),
            "owner": "vendeur.a",
            "prochaine_action": {
                "description": "Demander les photos de façade au client (fictif)",
                "echeance": iso(qualification_le + dt.timedelta(days=1)),
            },
        },
        cle="lot2-qualification-admin-fictive-0001", horodatage_appareil=iso(qualification_le),
    )
    assert qualification.statut == 200 and qualification.metier["accepte"] is True, qualification.corps
    assert qualification.resultat["statut"] == "qualifie"

    # La qualification vient de publier m2.lead_assigne. Livrer ce fait avant de prendre le
    # témoin du rejeu : son éventuel traitement M8 est un effet légitime de la qualification,
    # pas un effet du rejeu HTTP qui suit.
    assignation_livree = _drainer(moteur, _de_lead(moteur))
    assert assignation_livree["echecs"] == 0 and assignation_livree["quarantaines"] == 0

    # Même nonce, même signature et mêmes octets, cette fois après la qualification humaine : l'état complet
    # reste identique, le bus ne crée ni lead ni attribution supplémentaire.
    avant_rejeu = moteur.empreinte_etat()
    with console() as client:
        rejeu = client.post(chemin, content=corps, headers=entetes)
        assert rejeu.status_code == 202 and rejeu.json() == {"ok": True, "received": True}
    _drainer(moteur, _de_lead(moteur))
    assert moteur.empreinte_etat() == avant_rejeu
    assert _publies("m1.lead_qualifie") == [evenement]
    assert _opportunite_m2(admin, lead["lead_id"])["statut"] == "qualifie"

    # Lecture, readiness et interaction sont bornées au vendeur propriétaire; lead inconnu est le contrôle négatif.
    def refus(porte, outil: str, arguments: dict[str, Any], *, cle: str | None = None) -> dict[str, Any]:
        # Toute interaction T1 doit passer la validation idempotence de la vraie porte HTTP,
        # même quand l'autorisation métier la refusera. Les essais ont chacun leur propre clé.
        options = {"cle": cle, "horodatage_appareil": iso(qualification_le)} if cle else {}
        reponse = porte.appeler(outil, arguments, **options)
        assert reponse.statut == 200 and reponse.metier["accepte"] is False, reponse.corps
        return reponse.metier["verdict"]

    def meme_refus(outil: str, reel: dict[str, Any], inconnu: dict[str, Any], token_reel: str,
                   token_inconnu: str, *, interaction: bool = False) -> None:
        verdict_reel = refus(vendeur_b, outil, reel, cle=f"lot2-refus-b-{outil}-reel" if interaction else None)
        verdict_inconnu = refus(vendeur_b, outil, inconnu,
                               cle=f"lot2-refus-b-{outil}-inconnu" if interaction else None)
        assert verdict_reel["code"] == verdict_inconnu["code"] == "REJ-LEAD-NON-ASSIGNE", outil
        assert verdict_reel["detail"].replace(token_reel, "<id>") == verdict_inconnu["detail"].replace(
            token_inconnu, "<id>"
        ), outil

    client_id = admin.appeler("m2_trouver_client_de_lead", {"lead_id": lead["lead_id"]}).resultat["client_id"]
    avant_refus = moteur.empreinte_etat()
    id_inconnu = "lead-fantome-lot2"
    meme_refus("m2_trouver_client_de_lead",
               {"lead_id": lead["lead_id"]}, {"lead_id": id_inconnu}, lead["lead_id"], id_inconnu)
    client_inconnu = "m2-client-v1:fantome-lot2"
    meme_refus("m2_obtenir_client_360",
               {"client_id": client_id}, {"client_id": client_inconnu}, client_id, client_inconnu)
    meme_refus("m2_evaluer_readiness",
               {"lead_id": lead["lead_id"], "horodatage": iso(qualification_le)},
               {"lead_id": id_inconnu, "horodatage": iso(qualification_le)}, lead["lead_id"], id_inconnu)
    meme_refus("m2_enregistrer_interaction",
               {"lead_id": lead["lead_id"], "resume": "Appel fictif non autorisé",
                "horodatage": iso(qualification_le + dt.timedelta(seconds=1))},
               {"lead_id": id_inconnu, "resume": "Appel fictif non autorisé",
                "horodatage": iso(qualification_le + dt.timedelta(seconds=1))}, lead["lead_id"], id_inconnu,
               interaction=True)
    apres_refus = moteur.empreinte_etat()
    # La porte peut journaliser des tentatives T1 refusées; aucun registre métier ni attribution ne change.
    assert apres_refus["registres"] == avant_refus["registres"]
    assert _publies("m1.lead_qualifie") == [evenement]
    assert len(_publies("m2.lead_assigne")) == 1
    assert _mesures(admin)["metriques"]["m8_leads_par_contenu"]["valeur"] == "1"

    interaction_le = qualification_le + dt.timedelta(seconds=2)
    moteur.horloge.maintenant = interaction_le
    note_args = {
        "lead_id": lead["lead_id"], "resume": "Appel de suivi effectué; photos demandées (fictif)",
        "horodatage": iso(interaction_le),
    }
    note = vendeur_a.appeler(
        "m2_enregistrer_interaction", note_args, cle="lot2-note-vendeur-a-fictive-0001",
        horodatage_appareil=iso(interaction_le),
    )
    assert note.statut == 200 and note.metier["accepte"] is True, note.corps
    assert note.resultat["lead_id"] == lead["lead_id"]
    apres_note = moteur.empreinte_etat()
    rejeu_note = vendeur_a.appeler(
        "m2_enregistrer_interaction", note_args, cle="lot2-note-vendeur-a-fictive-0001",
        horodatage_appareil=iso(interaction_le),
    )
    assert rejeu_note.enveloppe["rejoue"] is True and rejeu_note.resultat == note.resultat
    assert moteur.empreinte_etat() == apres_note
    client_id = admin.appeler("m2_trouver_client_de_lead", {"lead_id": lead["lead_id"]}).resultat["client_id"]
    vue_client = admin.appeler("m2_obtenir_client_360", {"client_id": client_id}).resultat
    notes = [i for i in vue_client["interactions_recentes"] if i["lead_id"] == lead["lead_id"]]
    assert len(notes) == 1 and notes[0]["auteur"] == "vendeur.a"

    readiness_le = interaction_le + dt.timedelta(seconds=1)
    moteur.horloge.maintenant = readiness_le
    avant_gate = moteur.empreinte_etat()
    gate = vendeur_a.appeler(
        "m2_evaluer_readiness", {"lead_id": lead["lead_id"], "horodatage": iso(readiness_le)}
    )
    assert moteur.empreinte_etat() == avant_gate, "le marqueur readiness est une lecture pure"
    assert gate.statut == 200 and gate.metier["accepte"] is True, gate.corps
    marqueur = gate.resultat
    assert marqueur["readiness_ok"] is True and marqueur["lead_id"] == lead["lead_id"]

    # Fixture purement fictive, jamais un barème commercial : bornes 10..12 tirées de
    # departments/m03-estimation/tests/test_scenarios.py (poste gouttieres), unité pi_lin et quantité 30
    # tirées de test_outils_agent.py (_LIGNE_DEVIS_VALIDE). Le contrat v2 reste service=gouttieres.
    bareme_fictif_gouttieres = {
        "version": "fictif-test-2026.1", "unite": "pi_lin",
        "postes": {"gouttieres": {"cout_unitaire_min": 10.0, "cout_unitaire_max": 12.0}},
    }
    estimateur = Capacites(
        moteur.departements, stockage.transaction, filtre={"m03-estimation"},
        appelant="m03-estimation", memoire=False,
    )
    def approuver_execution_interne(nom_outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # Le manifeste M3 reste en mode ombre. La porte agent prépare une demande, pas un résultat;
        # le propriétaire fictif décide via le vrai moteur d'approbations, sans modifier ce mode.
        avant_demande = moteur.empreinte_etat()["registres"]
        ticket_meta = None
        if nom_outil == "m3_creer_devis":
            from m10_memoire import liaison as liaison_m10
            from m10_memoire import registre as registre_m10

            cle_session = "agent:m03-estimation:webchat:direct:lot2-fictif"
            # Liaison autorisée par le propriétaire fictif via le vrai registre M10;
            # le ticket est émis par la plateforme, jamais fourni comme argument métier.
            with stockage.transaction() as cnx:
                reg = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
                lien, refus = liaison_m10.lier_session_affaire(
                    cle_session, lead["lead_id"], "nathan", "admin", "appareil",
                    "Liaison du dossier fictif pour le test intégré", iso(readiness_le), reg,
                )
                assert refus is None and lien is not None
                ticket = liaison_cibles.emettre_ticket(
                    cnx, departement="m03-estimation", agent_id="m03-estimation",
                    cle_session=cle_session, affaire_id=lead["lead_id"], origine_affaire="session",
                    outil=nom_outil, arguments=arguments,
                )
            ticket_meta = liaison_cibles.TicketMeta(ticket["ticket"])
            avant_demande = moteur.empreinte_etat()["registres"]
        demande = estimateur.appeler(nom_outil, arguments, ticket_cible=ticket_meta)
        assert demande.get("ok") is True and demande.get("statut") == "en_attente_approbation", demande
        assert "resultat" not in demande
        assert moteur.empreinte_etat()["registres"] == avant_demande
        with stockage.transaction() as cnx:
            decision = approbations.decider(
                cnx, demande["demande_id"], True, "nathan",
                outils_executables(moteur.departements, stockage.transaction), moteur.departements,
            )
        assert decision["statut"] == "executee", decision
        assert decision["reponse"]["ok"] is True, decision
        return decision["reponse"]

    estimation_initiale = approuver_execution_interne("m3_estimer_projet", {
        "contrat": lead,
        "marqueur": marqueur,
        "photos": [],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": bareme_fictif_gouttieres,
        "quantite": 30,
        "plancher_rentable": 0,
    })
    assert estimation_initiale["ok"] is True, estimation_initiale
    sortie_m3 = estimation_initiale["resultat"]
    assert sortie_m3["accepte"] is True and sortie_m3["etape"] == "complet", sortie_m3
    assert sortie_m3["estimation"]["lead_id"] == lead["lead_id"]
    assert sortie_m3["estimation"]["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    assert sortie_m3["estimation"]["prix_bloque"] is True
    assert sortie_m3["estimation"]["intervalle_confiance"] == {
        "borne_basse": None, "borne_haute": None, "niveau": 0.9,
    }
    assert sortie_m3["elements_manquants"] == ["aucune entrée visuelle n'a été fournie"]
    assert sortie_m3["signal_relance_m2"] == {
        "type": "DEMANDE_ENTREES_VISUELLES", "lead_id": lead["lead_id"],
        "devis_id": sortie_m3["estimation"]["devis_id"],
        "elements_manquants": ["aucune entrée visuelle n'a été fournie"], "emission_count": 1,
    }

    # Correction test-only sur le même dossier, avec une photo de qualité issue du helper de
    # test_estimation.py (3000x2000, éclairage 7, porte à dimensions connues). Ce n'est pas une image réelle.
    photos_corrigees_fictives = [{
        "photo_id": "photo-gouttieres-lot2-fictive-001",
        "resolution_largeur": 3000,
        "resolution_hauteur": 2000,
        "eclairage": 7,
        "angle": "face",
        "reference_echelle": {"type": "porte", "dimensions_connues": True},
    }]
    estimation_corrigee = approuver_execution_interne("m3_estimer_projet", {
        "contrat": lead,
        "marqueur": marqueur,
        "photos": photos_corrigees_fictives,
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": bareme_fictif_gouttieres,
        "quantite": 30,
        "plancher_rentable": 0,
    })
    assert estimation_corrigee["ok"] is True, estimation_corrigee
    sortie_corrigee = estimation_corrigee["resultat"]
    assert sortie_corrigee["accepte"] is True and sortie_corrigee["etape"] == "complet", sortie_corrigee
    assert sortie_corrigee["estimation"]["lead_id"] == lead["lead_id"]
    assert sortie_corrigee["estimation"]["devis_id"] == sortie_m3["estimation"]["devis_id"]
    assert sortie_corrigee["estimation"]["prix_bloque"] is False
    intervalle_corrige = sortie_corrigee["estimation"]["intervalle_confiance"]
    assert 0 < intervalle_corrige["borne_basse"] <= intervalle_corrige["borne_haute"]

    # Création interne du devis puis rendu HTML T0; les fixtures de devis durable fournissent
    # explicitement la ligne (30 pi_lin, coût unitaire 10.00) et le taux fictif 0.20. Aucun prix
    # n'est fourni au code : M3 le recalcule. Les outils décrivent ces opérations comme brouillon,
    # sans envoi; aucune capacité ni approbation d'envoi n'est appelée.
    horodatage_brouillon = iso(readiness_le + dt.timedelta(seconds=1))
    devis = approuver_execution_interne("m3_creer_devis", {
        "devis_id": sortie_corrigee["estimation"]["devis_id"],
        "estimation_source_hash": sortie_corrigee["estimation"]["hash_maillon"],
        "lead_id": lead["lead_id"],
        "chantier_id": None,
        "lignes": [{
            "description": "Gouttière alu 5 po (fictif)",
            "quantite": "30",
            "unite": "pi_lin",
            "cout_unitaire": "10.00",
            "reference_besoin_materiau": None,
        }],
        "taux_marge": "0.20",
        "horodatage": horodatage_brouillon,
    })
    assert devis["ok"] is True and devis["resultat"]["accepte"] is True, devis
    assert devis["resultat"]["resultat"]["statut"] == "brouillon"
    soumission = estimateur.appeler("m3_generer_soumission_brouillon", {
        "devis_id": sortie_corrigee["estimation"]["devis_id"], "format": "html",
    })
    assert soumission["ok"] is True and soumission["resultat"]["accepte"] is True, soumission
    html_brouillon = soumission["resultat"]["resultat"]
    assert "BROUILLON — non envoyé, sujet à approbation." in html_brouillon
    assert "Gouttière alu 5 po (fictif)" in html_brouillon and "360.00" in html_brouillon
    assert "cout_unitaire" not in html_brouillon and "taux_marge" not in html_brouillon

    # Le rendu reste un brouillon interne : aucun envoi/acceptation, conversion, ni attribution nouvelle.
    assert _opportunite_m2(admin, lead["lead_id"])["statut"] == "qualifie"
    assert len(_publies("m1.lead_qualifie")) == 1
    assert len(_publies("m2.lead_assigne")) == 1
    assert _publies("m3.devis_envoye") == []
    assert _publies("m3.devis_accepte") == []
    mesures_finales = _mesures(admin)
    assert mesures_finales["metriques"]["m8_leads_par_contenu"]["valeur"] == "1"
    assert mesures_finales["contenus"][facebook["utm_content"]]["leads"] == 1
