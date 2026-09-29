"""PLAN T4.17-c — le STOP d'un client à M1 retire son consentement marketing chez M7, par le vrai bus.

Trajet, sans réseau ni core (le core ne s'exécute pas ici) :

    SMS du client -> `Capacites.appeler("m1_recevoir_message_canal")`  (vrai manifeste de M1, registre durable)
      -> lead `m1.lead_qualifie`                             (le `lead_id` : ce que M1, M2, M4 et M7 partagent)
    « Terminer » de M4 -> `m4.travaux_termines` avec ce `lead_id` et le consentement du client
      -> `evenements.repartir` (vrai répartiteur) -> M7 (vrai consommateur) : cinq contenus PROPOSE
    le propriétaire approuve un contenu et exporte son paquet
    SMS « STOP » -> M1 inscrit le retrait, PUBLIE `m1.retrait_consentement` (mêmes transactions)
      -> `evenements.repartir` -> M7 inscrit le retrait au registre `retraits_consentement_marketing`
      -> tout contenu du client est bloqué, un paquet déjà exporté compris

Le lien entre le correspondant du STOP et le chantier est le `lead_id` : aucun numéro ni courriel ne traverse le bus
pour ce retrait, et M7 n'en écrit aucun. Données fictives (numéros en 555, personnes de test). Ce que ce fichier ne
prouve PAS : le core ni l'envoi réel d'un SMS.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest
from m1_front_office import outils as m1
from m7_marketing import outils as m7
from m7_marketing.brand import profil_client
from m7_marketing.social import postiz_adapter
from sqlalchemy import select

from opsys import contexte, evenements, identite, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

FICTIF = True
DEBUT = dt.datetime(2026, 9, 29, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
NUMERO = "+15145550142"
AUTRE_NUMERO = "+15145550177"
GOUTTIERES = "Bonjour, mes gouttières fuient à Laval, c'est urgent."
REVETEMENT = "Bonjour, je veux refaire mon revêtement extérieur à Laval."
PROPRIETAIRE = ("nathan", "admin")
PROFIL_DU_CLIENT = {
    "name": "Toitures Boréales Fictive Inc.", "tagline": "Rénovation extérieure au Québec, sans surprise",
    "tone": "professionnel, factuel", "colors": ["#1a1a1a", "#ffffff"], "langue": "fr",
    "site_url": "https://exemple-fictif.ca/", "heures_publication": {"facebook": "18:30", "instagram": "19:15"},
}
CONSOMMATEURS_DU_TEST = {"m01-front-office", "m07-marketing"}


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    """Base migrée, profil d'entreprise, marque configurée, M1 durable, le propriétaire ; M1 et M7 sur le vrai bus."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    m1.utiliser_stockage_durable()
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(PROFIL_DU_CLIENT), None))

    def _interdit(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("M7 ne doit jamais publier : export manuel seulement")

    monkeypatch.setattr(postiz_adapter.PostizAdapter, "publier", _interdit)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner", "admin"])
    departements = charger_departements()
    yield departements, Capacites(departements, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    m1.reinitialiser_registre()
    stockage.liberer()


def _drainer(departements, *, max_tours: int = 10) -> dict[str, int]:
    """Livre le bus jusqu'à quiescence, à M1 et à M7 seulement (le vrai répartiteur, ses vrais manifestes)."""
    sous_ensemble = {i: d for i, d in departements.items() if i in CONSOMMATEURS_DU_TEST}
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(max_tours):
        resume = evenements.repartir(
            sous_ensemble, maintenant=(DEBUT + dt.timedelta(hours=3, seconds=90 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
    raise AssertionError(f"le bus n'a pas atteint la quiescence : {total}")


def _sms(texte, message_id, minutes=0, *, expediteur=NUMERO):
    return {"canal": "sms", "expediteur": expediteur, "message_id": message_id,
            "recu_le": (DEBUT + dt.timedelta(minutes=minutes)).isoformat(), "texte": texte}


def _client_ecrit(capacites, texte, message_id, minutes=0, *, expediteur=NUMERO) -> dict[str, Any]:
    reponse = capacites.appeler("m1_recevoir_message_canal", _sms(texte, message_id, minutes, expediteur=expediteur))
    assert reponse["ok"] is True and "statut" not in reponse, reponse
    return reponse["resultat"]


def _wct(lead_id: str, wct_id: str, **surcharges) -> dict[str, Any]:
    """Le WCT que M4 publie à « Terminer » : le `lead_id` est celui que M1 a créé, le consentement est prouvé."""
    charge = {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": lead_id, "technicien_id": "etienne",
        "horodatage_completion": "2026-09-29T14:00:00-04:00",
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
    resume = _drainer(departements)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume


def _outil_m7(nom, *, appareil=None, **arguments):
    outil = next(o for o in m7.outils() if o.nom == nom)
    if appareil is None:
        reponse = executer_atomique(outil, arguments)
    else:
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(*appareil)):
            reponse = executer_atomique(outil, arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _contenus(wct_id):
    return _outil_m7("m7_lister_contenus_chantier", wct_id=wct_id, limite=8)["contenus"]


def _contenu(wct_id, plateforme):
    (contenu,) = [c for c in _contenus(wct_id) if c["plateforme"] == plateforme]
    return contenu["contenu_id"]


def _registre_m7(nom):
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def _evenements_retrait():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m1.retrait_consentement"
        ).order_by(EVENEMENTS_SORTANTS.c.cree_le, EVENEMENTS_SORTANTS.c.evenement_id)).all()
    return [(ligne.evenement_id, codec.decoder(ligne.charge)) for ligne in lignes]


def _recu_par_m7(evenement_id):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == "m07-marketing")
        )).mappings().first()
    return None if ligne is None else dict(ligne)


def _statuts(wct_id):
    return {c["approval_status"] for c in _contenus(wct_id)}


def _approuver_et_exporter(contenu_id) -> dict[str, Any]:
    horodatage = "2026-09-29T20:00:00-04:00"
    decision = _outil_m7("m7_decider_contenu", appareil=PROPRIETAIRE, contenu_id=contenu_id, decision="approuver",
                         horodatage=horodatage)
    assert decision["accepte"] is True, decision
    paquet = _outil_m7("m7_exporter_paquet_manuel", appareil=PROPRIETAIRE, contenu_id=contenu_id, horodatage=horodatage)
    assert paquet["accepte"] is True and paquet["resultat"]["deja_exporte"] is False, paquet
    return paquet["resultat"]


# =====================================================================================================================
# Le scénario : STOP, puis tout contenu du client est bloqué, y compris un paquet déjà exporté
# =====================================================================================================================
def test_stop_puis_tout_contenu_du_client_est_bloque_y_compris_un_paquet_deja_exporte(instance):
    departements, capacites = instance
    lead = _client_ecrit(capacites, GOUTTIERES, "SM-1")["lead"]
    _drainer(departements)
    _terminer(departements, _wct(lead["lead_id"], "wct-1"))

    # Avant le STOP : cinq contenus PROPOSE, un approuvé et exporté. Le test n'est pas vide : tout marche.
    assert _statuts("wct-1") == {"PROPOSE"} and len(_contenus("wct-1")) == 5
    facebook, instagram = _contenu("wct-1", "facebook"), _contenu("wct-1", "instagram")
    paquet = _approuver_et_exporter(facebook)
    assert paquet["publication"].startswith("manuelle")
    with stockage.transaction():
        assert len(m7.attentes()) == 4
    assert _registre_m7("retraits_consentement_marketing") == []

    # Le STOP : M1 inscrit le retrait ET publie le fait (mêmes transactions).
    stop = _client_ecrit(capacites, "STOP", "SM-STOP", 600)
    assert stop["decision"] == "RETRAIT_CONSENTEMENT"
    ((evenement_id, charge),) = _evenements_retrait()
    assert stop["retrait_publie"] == {"leads": 1, "evenement_id": evenement_id}
    assert charge == {"lead_ids": [lead["lead_id"]], "canal": "sms", "signal_id": "sms:SM-STOP",
                      "horodatage": (DEBUT + dt.timedelta(minutes=600)).isoformat()}

    # M7 le reçoit par le vrai répartiteur et inscrit le retrait au registre.
    resume = _drainer(departements)
    assert resume["traites"] == 1 and resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    recu = _recu_par_m7(evenement_id)
    assert recu["statut"] == "traite"
    bilan = codec.decoder(recu["resultat"])
    assert bilan["retraits_ecrits"] == 1 and len(bilan["contenus_bloques"]) == 5
    assert bilan["contenus_deja_exportes"] == [facebook]
    (retrait,) = _registre_m7("retraits_consentement_marketing")
    assert (retrait["lead_id"], retrait["wct_id"], retrait["canal"], retrait["source"]) == (
        lead["lead_id"], None, "sms", "bus:m1.retrait_consentement")

    # Tout est bloqué : la liste, « À voir », la décision, l'export (même approuvé, même déjà exporté), la proposition.
    assert _statuts("wct-1") == {"CONSENTEMENT_RETIRE"}
    with stockage.transaction():
        assert m7.attentes() == []
    decision = _outil_m7("m7_decider_contenu", appareil=PROPRIETAIRE, contenu_id=instagram, decision="approuver",
                         horodatage="2026-09-30T09:00:00-04:00")
    assert decision["accepte"] is False and decision["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"
    export = _outil_m7("m7_exporter_paquet_manuel", appareil=PROPRIETAIRE, contenu_id=facebook,
                       horodatage="2026-09-30T09:00:00-04:00")
    assert export["accepte"] is False and export["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"
    reproposition = _outil_m7("m7_proposer_contenus_chantier", wct_id="wct-1")
    assert reproposition["statut"] == "consentement_retire"
    assert _outil_m7("m7_lire_matiere_chantier", wct_id="wct-1")["statut"] == "consentement_retire"
    assert len(_registre_m7("contenus_chantier")) == 5, "aucun contenu de plus n'a été écrit"


def test_un_chantier_du_meme_client_qui_arrive_apres_le_stop_est_bloque_a_sa_reception(instance):
    departements, capacites = instance
    lead = _client_ecrit(capacites, GOUTTIERES, "SM-1")["lead"]
    _client_ecrit(capacites, "STOP", "SM-STOP", 5)
    _drainer(departements)

    _terminer(departements, _wct(lead["lead_id"], "wct-apres"))
    assert _registre_m7("contenus_chantier") == []
    assert _outil_m7("m7_proposer_contenus_chantier", wct_id="wct-apres")["statut"] == "consentement_retire"


def test_un_client_qui_ecrit_a_nouveau_apres_son_stop_reste_retire_pour_ses_nouveaux_leads(instance):
    departements, capacites = instance
    avant = _client_ecrit(capacites, GOUTTIERES, "SM-1")["lead"]
    _client_ecrit(capacites, "STOP", "SM-STOP", 5)
    nouveau = _client_ecrit(capacites, REVETEMENT, "SM-2", 60 * 24 * 10)["lead"]
    assert nouveau["lead_id"] != avant["lead_id"]

    assert [c["lead_ids"] for _, c in _evenements_retrait()] == [[avant["lead_id"]], [nouveau["lead_id"]]]
    assert _drainer(departements)["echecs"] == 0
    assert {r["lead_id"] for r in _registre_m7("retraits_consentement_marketing")} == {
        avant["lead_id"], nouveau["lead_id"]}
    _terminer(departements, _wct(nouveau["lead_id"], "wct-nouveau", service="revetement"))
    assert _registre_m7("contenus_chantier") == [], "le retrait ne se lève pas : un nouveau lead ne le défait pas"


def test_le_stop_d_un_client_ne_touche_pas_le_contenu_d_un_autre_client(instance):
    departements, capacites = instance
    a = _client_ecrit(capacites, GOUTTIERES, "SM-A")["lead"]
    b = _client_ecrit(capacites, GOUTTIERES, "SM-B", expediteur=AUTRE_NUMERO)["lead"]
    assert a["lead_id"] != b["lead_id"]
    _terminer(departements, _wct(a["lead_id"], "wct-a"))
    _terminer(departements, _wct(b["lead_id"], "wct-b"))

    _client_ecrit(capacites, "STOP", "SM-STOP", 5)  # le STOP est celui du numéro de A
    _drainer(departements)
    assert _statuts("wct-a") == {"CONSENTEMENT_RETIRE"}
    assert _statuts("wct-b") == {"PROPOSE"} and len(_contenus("wct-b")) == 5
    with stockage.transaction():
        assert len(m7.attentes()) == 5  # « À voir » ne garde que les cinq contenus de B


def test_le_rejeu_du_stop_et_du_bus_n_ecrit_rien_de_plus(instance):
    departements, capacites = instance
    lead = _client_ecrit(capacites, GOUTTIERES, "SM-1")["lead"]
    _terminer(departements, _wct(lead["lead_id"], "wct-1"))
    _client_ecrit(capacites, "STOP", "SM-STOP", 5)
    _drainer(departements)
    avant = (_registre_m7("retraits_consentement_marketing"), _evenements_retrait())

    rejoue = _client_ecrit(capacites, "STOP", "SM-STOP", 5)
    assert rejoue["doublon"] is True
    assert _drainer(departements)["livres"] == 0
    assert (_registre_m7("retraits_consentement_marketing"), _evenements_retrait()) == avant
    assert len(avant[0]) == 1 and len(avant[1]) == 1
    assert evenements.etat()["quarantaine"] == []


def test_un_stop_a_un_correspondant_sans_lead_ne_publie_rien_et_m7_n_ecrit_rien(instance):
    departements, capacites = instance
    stop = _client_ecrit(capacites, "STOP", "SM-STOP")
    assert stop["retrait_publie"] == {"leads": 0, "evenement_id": None}
    assert _evenements_retrait() == [] and _drainer(departements)["livres"] == 0
    assert _registre_m7("retraits_consentement_marketing") == []


def test_aucun_numero_ni_courriel_ne_traverse_le_bus_pour_le_retrait_et_m7_n_en_ecrit_aucun(instance):
    departements, capacites = instance
    lead = _client_ecrit(capacites, GOUTTIERES, "SM-1")["lead"]
    _terminer(departements, _wct(lead["lead_id"], "wct-1"))
    _client_ecrit(capacites, "STOP", "SM-STOP", 5)
    _drainer(departements)

    conversation = lead["conversation_id"]
    ecrit_par_le_retrait = json.dumps(
        [charge for _, charge in _evenements_retrait()] + _registre_m7("retraits_consentement_marketing"))
    for secret in (NUMERO, NUMERO.removeprefix("+1"), "5145550142", conversation, conversation.split("-")[1]):
        assert secret not in ecrit_par_le_retrait, secret
    # M7 non plus, nulle part : ses registres ne portent jamais le numéro du client.
    with stockage.transaction():
        tout_m7 = json.dumps({nom: list(stockage.maillons("m07-marketing", nom)) for nom in (
            "wct_recus", "contenus_chantier", "retraits_consentement_marketing", "decisions_contenu",
            "exports_paquet")})
    assert NUMERO not in tout_m7 and "5145550142" not in tout_m7


def test_le_stop_est_un_type_du_catalogue_que_m1_publie_et_que_m7_consomme(instance):
    departements, _ = instance
    assert "m1.retrait_consentement" in evenements.types_connus()
    assert "m1.retrait_consentement" in departements["m01-front-office"].evenements_publie
    assert "m1.retrait_consentement" in departements["m07-marketing"].evenements_consomme
    assert evenements.verifier_coherence(departements) == []
