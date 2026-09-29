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

Ce que ces tests ne prouvent PAS : le navigateur (le script du formulaire est gardé par `test_formulaire_site.py`, sa
forme, et a été vérifié à la main), le récepteur du formulaire (rien ne le reçoit encore : la mise en ligne reste T3),
ni le core. Données fictives (`fictif`), adresses en `.test`.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from harnais_e2e import Moteur, iso
from m1_front_office import outils as m1_outils
from m7_marketing.brand import profil_client
from m7_marketing.social import postiz_adapter
from sqlalchemy import select

from opsys import evenements, stockage, taxonomie
from opsys.capacites import Capacites
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
