"""PLAN T4.17-e — la boucle de mesure par `utm_content`, par le VRAI bus : du contenu exporté au lead que M8 compte.

Trajet, sans réseau ni core (le core ne s'exécute pas ici) :

    « Terminer » de M4 -> `m4.travaux_termines` avec le consentement du client
      -> `evenements.repartir` (vrai répartiteur) -> M7 (vrai consommateur) : cinq contenus PROPOSE
    le propriétaire approuve et exporte des paquets (vrais outils de M7, porte d'appareil)
      -> `m7_exporter_paquet_manuel` annonce `m7.contenu_exporte` (clé utm_content, chantier, canal), même transaction
    des clients suivent le lien du paquet : M1 qualifie leur lead avec les `utm_*` du lien
      (`m1_traiter_demande_entrante`)
      -> `m1.lead_qualifie` porte `lead.utm.utm_content`
    -> M8 (vrai consommateur des deux événements) compte les leads par contenu ; `m8_lire_mesures_contenus` les lit
    -> (chaîne) M2 reprend le lead de M1, M3 publie le devis envoyé et accepté : M8 les rattache au contenu

Ce que ce fichier prouve : la clé qui sort dans le lien est celle que M1 rapporte et que M8 compte ; un lead sans
`utm_content` n'est attribué à aucun contenu (ni un lead à clé inconnue) ; impressions et clics restent « non
calculable » ; rien de personnel ne traverse ni ne reste chez M8 ; le rejeu n'ajoute rien ; seul l'admin lit.
Données fictives (numéros en 555, personnes de test). Ce que ce fichier ne prouve PAS : le core, ni qu'un site ou un
formulaire recopie les `utm_*` vers M1 (aucun formulaire n'existe encore), ni les impressions ni les clics (aucune
source).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import m2_revenue_crm.outils as m2_outils
import m3_estimation.outils as m3_outils
import pytest
from m1_front_office import outils as m1
from m7_marketing import outils as m7
from m7_marketing.brand import profil_client
from m7_marketing.social import postiz_adapter
from m8_analytics import outils as m8
from sqlalchemy import select

from opsys import approbations_appareil, contexte, evenements, idempotence, identite, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True
DEBUT = dt.datetime(2026, 9, 29, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
ZONE = ["Laval", "Québec"]
PROPRIETAIRE = ("nathan", "admin")
ADMIN = IdentiteAppelante(*PROPRIETAIRE)
VENDEUR = IdentiteAppelante("vendeur.un", "seller")
EMPLOYE = IdentiteAppelante("employe.un", "employee")
MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"
PROFIL_DU_CLIENT = {
    "name": "Toitures Boréales Fictive Inc.", "tagline": "Rénovation extérieure au Québec, sans surprise",
    "tone": "professionnel, factuel", "colors": ["#1a1a1a", "#ffffff"], "langue": "fr",
    "site_url": "https://exemple-fictif.ca/", "heures_publication": {"facebook": "18:30", "instagram": "19:15"},
}
# Ce que le lead porte et que M8 ne doit jamais garder : son nom (absent du texte), son téléphone, sa ville.
CONFIDENCES = ("450-555-0101", "450-555-0102", "450-555-0103", "450-555-0104", "450-555-0105", "Repentigny")
CONSOMMATEURS = {"m07-marketing", "m08-analytics"}


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    """Base migrée, profil d'entreprise, marque configurée, M1 et M2 durables, les personnes ; le vrai manifeste."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(ZONE)
    m1.utiliser_stockage_durable()
    m2_outils.utiliser_stockage_durable()
    profil = dict(PROFIL_DU_CLIENT)
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(profil), None))

    def _interdit(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("M7 ne doit jamais publier : export manuel seulement")

    monkeypatch.setattr(postiz_adapter.PostizAdapter, "publier", _interdit)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", MOT_DE_PASSE, ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un (fictif)", MOT_DE_PASSE, ["seller"])
        identite.creer_personne(cnx, "employe.un", "Employé Un (fictif)", MOT_DE_PASSE, ["employee"])
    yield SimpleNamespace(departements=charger_departements(), profil=profil)
    m1.reinitialiser_registre()
    m2_outils.reinitialiser_registre()
    stockage.liberer()


# ---------------------------------------------------------------------------------------------------------------------
# Petits outils : le bus, M7, M1, M8
# ---------------------------------------------------------------------------------------------------------------------
def _drainer(departements, consommateurs=CONSOMMATEURS, *, max_tours: int = 10) -> dict[str, int]:
    """Livre le bus jusqu'à quiescence, aux consommateurs donnés (le vrai répartiteur, ses vrais manifestes)."""
    sous_ensemble = {i: d for i, d in departements.items() if i in consommateurs}
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(max_tours):
        maintenant = (DEBUT + dt.timedelta(hours=3, seconds=90 * tour)).isoformat()
        resume = evenements.repartir(sous_ensemble, maintenant=maintenant)
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            assert total["echecs"] == 0 and total["quarantaines"] == 0, total
            return total
    raise AssertionError(f"le bus n'a pas atteint la quiescence : {total}")


def _wct(wct_id: str, **surcharges) -> dict[str, Any]:
    """Le WCT que M4 publie à « Terminer », avec le consentement marketing du client et sa preuve."""
    charge = {
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
    charge.update(surcharges)
    return charge


def _terminer(departements, charge: dict[str, Any]) -> None:
    with stockage.transaction():
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=f"m4-wct-{charge['wct_id']}")
    _drainer(departements)


def _outil(module, nom):
    return next(o for o in module.outils() if o.nom == nom)


def _appeler(module, nom, *, appareil=None, **arguments):
    if appareil is None:
        reponse = executer_atomique(_outil(module, nom), arguments)
    else:
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(*appareil)):
            reponse = executer_atomique(_outil(module, nom), arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _contenu(wct_id: str, plateforme: str) -> str:
    contenus = _appeler(m7, "m7_lister_contenus_chantier", wct_id=wct_id, limite=8)["contenus"]
    (contenu,) = [c for c in contenus if c["plateforme"] == plateforme]
    return contenu["contenu_id"]


def _exporter(wct_id: str, plateforme: str) -> dict[str, Any]:
    """Le propriétaire approuve puis exporte le paquet de ce contenu, depuis son appareil : le paquet remis."""
    contenu_id = _contenu(wct_id, plateforme)
    horodatage = "2026-09-29T20:00:00-04:00"
    decision = _appeler(m7, "m7_decider_contenu", appareil=PROPRIETAIRE, contenu_id=contenu_id, decision="approuver",
                        horodatage=horodatage)
    assert decision["accepte"] is True, decision
    paquet = _appeler(m7, "m7_exporter_paquet_manuel", appareil=PROPRIETAIRE, contenu_id=contenu_id,
                      horodatage=horodatage)
    assert paquet["accepte"] is True, paquet
    return paquet["resultat"]


def _utm_du_lien(lien: str) -> dict[str, str]:
    """Ce que M1 recevrait : les paramètres `utm_*` du lien de suivi, tels que le paquet les a remis."""
    return {cle: valeur for cle, valeur in parse_qsl(urlsplit(lien).query) if cle.startswith("utm_")}


def _lead_de_m1(
    conversation: str, telephone: str, utm: dict[str, str] | None = None, minutes: int = 0,
) -> dict[str, Any]:
    """M1 qualifie la demande d'un client (vrai outil, vrai registre durable) et PUBLIE `m1.lead_qualifie` dans sa
    transaction. `utm` : ce que le formulaire a recopié du lien, ou rien."""
    arguments: dict[str, Any] = {
        "contenu_brut": f"Gouttières à Laval, téléphone {telephone}.", "canal": "formulaire",
        "conversation_id": conversation, "signal_id": f"formulaire:{conversation}",
        "horodatage": (DEBUT + dt.timedelta(days=1, minutes=minutes)).isoformat(), "zone_desservie": ZONE,
    }
    if utm is not None:
        arguments["utm"] = utm
    resultat = _appeler(m1, "m1_traiter_demande_entrante", **arguments)
    assert resultat["qualifie"] is True and resultat["decision"] == "TRANSMETTRE_M2", resultat
    return resultat["lead"]


def _publies(type_evenement: str) -> list[tuple[str, dict[str, Any]]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement
        ).order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)).all()
    return [(ligne.evenement_id, codec.decoder(ligne.charge)) for ligne in lignes]


def _vue(appelante: IdentiteAppelante = ADMIN, **arguments) -> dict[str, Any]:
    with contexte.appele_par_appareil(appelante):
        reponse = executer_atomique(_outil(m8, "m8_lire_mesures_contenus"), arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _mesures(vue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {ligne["metric_id"]: ligne for ligne in vue["metriques"]}


def _ligne(vue: dict[str, Any], utm_content: str) -> dict[str, Any]:
    (ligne,) = [ligne for ligne in vue["contenus"] if ligne["utm_content"] == utm_content]
    return ligne


def _ecritures_du_bus() -> tuple[int, int]:
    with stockage.transaction() as cnx:
        return (len(cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id)).all()),
                len(cnx.execute(select(EVENEMENTS_RECUS.c.evenement_id)).all()))


# =====================================================================================================================
# Le scénario : du contenu exporté au lead compté
# =====================================================================================================================
def test_du_paquet_exporte_au_lead_de_m1_m8_compte_un_lead_pour_ce_contenu(instance):
    departements = instance.departements
    _terminer(departements, _wct("wct-1"))
    paquets = {p: _exporter("wct-1", p) for p in ("facebook", "instagram", "demande_temoignage")}

    # -- 1. M7 annonce chaque contenu exporté : la clé du paquet, son lien, son chantier, son canal -----------------
    annonces = _publies("m7.contenu_exporte")
    assert len(annonces) == 3
    for evenement_id, fait in annonces:
        paquet = paquets[fait["canal"]]
        assert evenement_id == f"m7-contenu-exporte-{fait['contenu_id']}"
        assert fait["utm_content"] == paquet["utm_content"] and fait["wct_id"] == "wct-1"
        assert set(fait) == {"contenu_id", "wct_id", "canal", "utm_content", "lien_de_suivi", "exporte_le"}
        assert fait["lien_de_suivi"] is (paquet["lien_utm"] is not None)
    cles = {p: paquets[p]["utm_content"] for p in paquets}
    assert len(set(cles.values())) == 3 and all(cles[p].startswith(f"{p}-") for p in cles)
    assert paquets["demande_temoignage"]["lien_utm"] is None  # un message privé : une clé, aucun lien pour la porter
    assert _utm_du_lien(paquets["facebook"]["lien_utm"]) == {
        "utm_source": "facebook", "utm_medium": "social", "utm_campaign": "contenu-gouttieres-et-descentes-2026",
        "utm_content": cles["facebook"],
    }

    # -- 2. des clients arrivent : la clé du lien revient dans le lead que M1 qualifie ------------------------------
    depuis_facebook = _lead_de_m1("conv-fb", "450-555-0101", _utm_du_lien(paquets["facebook"]["lien_utm"]))
    depuis_instagram = _lead_de_m1("conv-ig", "450-555-0102", _utm_du_lien(paquets["instagram"]["lien_utm"]), 5)
    sans_utm = _lead_de_m1("conv-sans", "450-555-0103", None, 10)
    sans_utm_content = _lead_de_m1("conv-google", "450-555-0104", {"utm_source": "google", "utm_medium": "cpc"}, 15)
    cle_inconnue = _lead_de_m1(
        "conv-inconnue", "450-555-0105",
        {"utm_source": "facebook", "utm_medium": "social", "utm_campaign": "contenu-x-2026",
         "utm_content": "facebook-0000000000000000"}, 20,
    )
    assert depuis_facebook["utm"]["utm_content"] == cles["facebook"]
    assert depuis_instagram["utm"]["utm_content"] == cles["instagram"]
    assert "utm" not in sans_utm and "utm_content" not in sans_utm_content["utm"]
    porte_par_le_bus = {c["lead"]["lead_id"]: c["lead"].get("utm", {}).get("utm_content") for _, c in
                        _publies("m1.lead_qualifie")}
    assert porte_par_le_bus == {
        depuis_facebook["lead_id"]: cles["facebook"], depuis_instagram["lead_id"]: cles["instagram"],
        sans_utm["lead_id"]: None, sans_utm_content["lead_id"]: None,
        cle_inconnue["lead_id"]: "facebook-0000000000000000",
    }

    # -- 3. le bus livre à M8, qui compte : un lead pour Facebook, un pour Instagram, aucun pour les trois autres ---
    resume = _drainer(departements)
    assert resume["traites"] >= 8 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    vue = _vue()

    mesures = _mesures(vue)
    assert {m: ligne["valeur"] for m, ligne in mesures.items()} == {
        "m8_contenus_exportes": "3", "m8_leads_par_contenu": "2", "m8_devis_envoyes_par_contenu": None,
        "m8_devis_acceptes_par_contenu": None, "m8_impressions_par_contenu": None, "m8_clics_par_contenu": None,
    }
    assert mesures["m8_leads_par_contenu"]["entrees"] == {
        "n_leads_recus": 5, "n_leads_attribues": 2, "n_leads_sans_utm_content": 2,
        "n_leads_utm_content_inconnu": 1, "n_leads_utm_content_ambigu": 0,
    }
    assert _ligne(vue, cles["facebook"])["leads"] == 1 and _ligne(vue, cles["instagram"])["leads"] == 1
    ligne_privee = _ligne(vue, cles["demande_temoignage"])
    assert ligne_privee["suivi"] == "sans_lien" and ligne_privee["leads"] is None  # « non mesurable », jamais 0
    assert sum(ligne["leads"] or 0 for ligne in vue["contenus"]) == 2  # ni les leads sans clé, ni la clé inconnue
    assert (_ligne(vue, cles["facebook"])["canal"], _ligne(vue, cles["facebook"])["wct_id"]) == ("facebook", "wct-1")

    # -- 4. sans aucune source, les devis, les impressions et les clics sont « non calculable », jamais un zéro ---
    for metric_id in ("m8_devis_envoyes_par_contenu", "m8_devis_acceptes_par_contenu"):
        assert mesures[metric_id]["statut"] == "non_calculable"  # aucun fait de l'entonnoir : le dit, ne suppose rien
    for metric_id in ("m8_impressions_par_contenu", "m8_clics_par_contenu"):
        assert mesures[metric_id]["statut"] == "non_calculable" and mesures[metric_id]["valeur"] is None
        assert mesures[metric_id]["manque"] == ["source des impressions et des clics"]
    assert any(m["champ"] == "source des impressions et des clics" for m in vue["manques"])
    sources = [(s["evenement"], s["n"]) for s in vue["sources"]]
    assert sources[:2] == [("m7.contenu_exporte", 3), ("m1.lead_qualifie", 5)]


def test_un_lead_sans_utm_content_n_est_attribue_a_aucun_contenu(instance):
    """Le cas nommé de la mission : un seul contenu exporté, un seul lead, et ce lead ne porte aucune clé."""
    _terminer(instance.departements, _wct("wct-1"))
    paquet = _exporter("wct-1", "facebook")
    _lead_de_m1("conv-sans", "450-555-0101", None)
    _drainer(instance.departements)

    vue = _vue()

    mesures = _mesures(vue)
    assert mesures["m8_leads_par_contenu"]["valeur"] == "0"
    assert mesures["m8_leads_par_contenu"]["entrees"]["n_leads_recus"] == 1
    assert mesures["m8_leads_par_contenu"]["entrees"]["n_leads_sans_utm_content"] == 1
    assert _ligne(vue, paquet["utm_content"])["leads"] == 0


def test_le_lead_d_un_autre_contenu_ne_compte_pas_pour_celui_ci(instance):
    _terminer(instance.departements, _wct("wct-1"))
    facebook, instagram = _exporter("wct-1", "facebook"), _exporter("wct-1", "instagram")
    for i in range(3):
        _lead_de_m1(f"conv-{i}", f"450-555-010{i}", _utm_du_lien(instagram["lien_utm"]), i)
    _drainer(instance.departements)

    vue = _vue()

    assert _ligne(vue, instagram["utm_content"])["leads"] == 3
    assert _ligne(vue, facebook["utm_content"])["leads"] == 0
    assert _mesures(vue)["m8_leads_par_contenu"]["valeur"] == "3"


def test_sans_site_dans_le_profil_le_contenu_est_exporte_sans_lien_et_m8_dit_non_mesurable(instance):
    del instance.profil["site_url"]
    _terminer(instance.departements, _wct("wct-1"))
    paquet = _exporter("wct-1", "facebook")
    assert paquet["lien_utm"] is None and paquet["utm_content"].startswith("facebook-")
    ((_, fait),) = _publies("m7.contenu_exporte")
    assert fait["lien_de_suivi"] is False
    _lead_de_m1("conv-1", "450-555-0101", {"utm_source": "facebook", "utm_content": paquet["utm_content"]})
    _drainer(instance.departements)

    vue = _vue()

    assert _ligne(vue, paquet["utm_content"])["suivi"] == "sans_lien"
    assert _ligne(vue, paquet["utm_content"])["leads"] is None
    # Aucun lien n'a porté cette clé : un lead qui la porte quand même ne lui est pas attribué (compté à part).
    assert _mesures(vue)["m8_leads_par_contenu"]["entrees"]["n_leads_utm_content_inconnu"] == 1
    assert _mesures(vue)["m8_leads_par_contenu"]["valeur"] == "0"


# =====================================================================================================================
# La chaîne : M1 -> M2 -> M3 -> M8, par le même lead_id
# =====================================================================================================================
def _m3_creer_devis(devis_id: str, lead_id: str) -> None:
    lignes = [
        {"description": "Gouttières 5po aluminium (fictif)", "quantite": "40", "unite": "pi", "cout_unitaire": "8.00",
         "reference_besoin_materiau": None},
        {"description": "Main d'oeuvre installation (fictif)", "quantite": "1", "unite": "forfait",
         "cout_unitaire": "160.00", "reference_besoin_materiau": None},
    ]
    reponse = executer_atomique(_outil(m3_outils, "m3_creer_devis"), {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "lignes": lignes, "taux_marge": "0.25",
        "horodatage": "2026-09-30T09:00:00-04:00", "prix_total": "600.00",
    })
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def _m3_envoyer_devis(deps, devis_id: str, cle: str) -> None:
    """Le vendeur DEMANDE l'envoi (N4) de son appareil ; le propriétaire l'approuve du sien : c'est à cette décision
    que M3 passe le devis à `envoye` et publie `m3.devis_envoye`."""
    m3 = {"m03-estimation": deps["m03-estimation"]}
    capacites = Capacites(m3, stockage.transaction, memoire=False)
    meta = idempotence.Meta(cle=cle, appareil="tel-vendeur-fictif", horodatage_appareil="2026-10-01T06:30:00-04:00")
    with contexte.appele_par_appareil(VENDEUR):
        demande = capacites.appeler("m3_demander_envoi_devis", {"devis_id": devis_id, "contexte_revue": None}, meta)
    assert demande["ok"] is True and demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        decision, verdict = approbations_appareil.decider_demande(
            cnx, m3, ADMIN, demande["demande_id"], "approuver", "", appareil="tel-proprio-fictif")
    assert verdict is None and decision["issue"] == {"ok": True, "accepte": True}, (decision, verdict)


def _m3_accepter_devis(devis_id: str) -> None:
    reponse = executer_atomique(_outil(m3_outils, "m3_marquer_devis_accepte"), {
        "devis_id": devis_id, "approbateur": "Nathan Proprietaire (fictif, T3)",
        "horodatage": "2026-10-02T09:00:00-04:00",
    })
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def test_de_m1_a_m3_le_meme_lead_id_relie_le_contenu_au_devis_envoye_puis_accepte(instance):
    departements = instance.departements
    _terminer(departements, _wct("wct-1"))
    paquet = _exporter("wct-1", "facebook")
    lead = _lead_de_m1("conv-fb", "450-555-0101", _utm_du_lien(paquet["lien_utm"]))
    autre = _lead_de_m1("conv-sans", "450-555-0102", None, 5)

    # M2 reprend le lead de M1 tel quel : le lead_id qu'elle publie est celui de M1. Elle ne reçoit ici que les leads
    # de M1 (le WCT de ce chantier concerne un lead qu'elle n'a jamais ouvert : un autre sujet).
    m2 = dataclasses.replace(departements["m02-revenue-crm"], evenements_consomme=("m1.lead_qualifie",))
    resume_m2 = evenements.repartir({"m02-revenue-crm": m2}, maintenant=(DEBUT + dt.timedelta(hours=3)).isoformat())
    assert resume_m2["traites"] == 2 and resume_m2["echecs"] == 0 and resume_m2["quarantaines"] == 0, resume_m2
    associes = {charge["lead_id"] for _, charge in _publies("m2.client_associe")}
    assert associes == {lead["lead_id"], autre["lead_id"]}

    # M3 publie les devis de ce lead_id (vrais outils, approbation du propriétaire pour l'envoi).
    _m3_creer_devis("devis-a", lead["lead_id"])
    _m3_creer_devis("devis-b", autre["lead_id"])
    for devis_id in ("devis-a", "devis-b"):
        _m3_envoyer_devis(departements, devis_id, f"cle-{devis_id}")
    _m3_accepter_devis("devis-a")
    assert {c["lead_id"] for _, c in _publies("m3.devis_envoye")} == {lead["lead_id"], autre["lead_id"]}
    assert [c["lead_id"] for _, c in _publies("m3.devis_accepte")] == [lead["lead_id"]]

    # M8 (avec M7 seuls) : le devis du lead venu du contenu compte pour ce contenu, celui du lead sans clé pour aucun.
    _drainer(departements)
    vue = _vue()

    mesures = _mesures(vue)
    assert {m: mesures[m]["valeur"] for m in (
        "m8_contenus_exportes", "m8_leads_par_contenu", "m8_devis_envoyes_par_contenu", "m8_devis_acceptes_par_contenu",
    )} == {"m8_contenus_exportes": "1", "m8_leads_par_contenu": "1", "m8_devis_envoyes_par_contenu": "1",
           "m8_devis_acceptes_par_contenu": "1"}
    assert mesures["m8_devis_envoyes_par_contenu"]["entrees"] == {
        "n_devis_recus": 2, "n_devis_attribues": 1, "n_sans_lead_de_m1": 0, "n_lead_sans_contenu": 1,
    }
    ligne = _ligne(vue, paquet["utm_content"])
    assert (ligne["leads"], ligne["devis_envoyes"], ligne["devis_acceptes"]) == (1, 1, 1)


# =====================================================================================================================
# Loi 25, rejeu, accès
# =====================================================================================================================
def test_rien_de_personnel_ne_traverse_le_bus_pour_le_contenu_ni_ne_reste_chez_m8(instance):
    departements = instance.departements
    _terminer(departements, _wct("wct-1"))
    paquet = _exporter("wct-1", "facebook")
    lead = _lead_de_m1("conv-fb", "450-555-0101", _utm_du_lien(paquet["lien_utm"]))
    _drainer(departements)
    vue = _vue()

    # Le fait annoncé par M7 : six clés, aucune valeur qui identifie un client.
    ((_, fait),) = [(i, c) for i, c in _publies("m7.contenu_exporte")]
    lu_par_le_bus = json.dumps(fait, ensure_ascii=False)
    for secret in ("lead-du-chantier-wct-1", "Laval", "Repentigny", "etienne", "Toitures", "int-wct-1", "devis-wct-1"):
        assert secret not in lu_par_le_bus, secret
    # Ce que M8 garde et rend : des identifiants, des instants, la clé ; ni le téléphone, ni la ville, ni le service.
    with stockage.transaction() as cnx:
        registres = [ligne.maillon for ligne in cnx.execute(
            select(REGISTRES.c.maillon).where(REGISTRES.c.departement == "m08-analytics")).all()]
        recus = [ligne.resultat for ligne in cnx.execute(
            select(EVENEMENTS_RECUS.c.resultat).where(EVENEMENTS_RECUS.c.consommateur == "m08-analytics")).all()]
    lu_par_m8 = json.dumps(registres, ensure_ascii=False) + json.dumps(recus, ensure_ascii=False)
    lu_par_m8 += json.dumps(vue, ensure_ascii=False)
    for secret in (*CONFIDENCES, "conv-fb", "gouttieres", "formulaire", lead["conversation_id"]):
        assert secret not in lu_par_m8, secret
    assert lead["lead_id"] not in json.dumps(vue, ensure_ascii=False)  # des comptes, jamais un lead


def test_le_rejeu_du_bus_et_de_l_export_n_ajoute_rien_et_la_lecture_ne_change_pas(instance):
    departements = instance.departements
    _terminer(departements, _wct("wct-1"))
    paquet = _exporter("wct-1", "facebook")
    lead = _lead_de_m1("conv-fb", "450-555-0101", _utm_du_lien(paquet["lien_utm"]))
    _drainer(departements)
    avant = (_vue(), _ecritures_du_bus())

    assert _drainer(departements)["livres"] == 0  # rien à livrer de nouveau
    encore = _appeler(m7, "m7_exporter_paquet_manuel", appareil=PROPRIETAIRE, contenu_id=_contenu("wct-1", "facebook"),
                      horodatage="2026-09-30T09:00:00-04:00")
    assert encore["resultat"]["deja_exporte"] is True and encore["resultat"]["mesure"]["statut"] == "deja_annonce"
    rejoue = _lead_de_m1("conv-fb", "450-555-0101", _utm_du_lien(paquet["lien_utm"]))  # même signal : même lead
    assert rejoue["lead_id"] == lead["lead_id"]
    assert _drainer(departements)["livres"] == 0
    assert (_vue(), _ecritures_du_bus()) == avant
    assert len(_publies("m7.contenu_exporte")) == 1 and len(_publies("m1.lead_qualifie")) == 1
    assert evenements.etat()["quarantaine"] == []


def test_seul_l_admin_authentifie_lit_la_mesure_par_contenu(instance):
    _terminer(instance.departements, _wct("wct-1"))
    paquet = _exporter("wct-1", "facebook")
    _lead_de_m1("conv-fb", "450-555-0101", _utm_du_lien(paquet["lien_utm"]))
    _drainer(instance.departements)

    for appelante in (EMPLOYE, VENDEUR, IdentiteAppelante("employe.un", "admin")):
        with contexte.appele_par_appareil(appelante):
            refus = executer_atomique(_outil(m8, "m8_lire_mesures_contenus"), {})
        assert refus["ok"] is False and refus["erreur"] == "refus_metier", appelante
        assert refus["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE") and "resultat" not in refus
        assert paquet["utm_content"] not in json.dumps(refus, ensure_ascii=False)
    assert _mesures(_vue())["m8_leads_par_contenu"]["valeur"] == "1"


def test_le_type_est_au_catalogue_m7_le_publie_m8_le_consomme_et_les_declarations_sont_coherentes(instance):
    departements = instance.departements
    assert "m7.contenu_exporte" in evenements.types_connus()
    assert "m7.contenu_exporte" in departements["m07-marketing"].evenements_publie
    assert {"m7.contenu_exporte", "m1.lead_qualifie"} <= set(departements["m08-analytics"].evenements_consomme)
    assert "m01-front-office" in departements["m08-analytics"].dependances
    assert evenements.verifier_coherence(departements) == []
