"""PLAN T4.17 (M7) — « gouttières à Repentigny -> 5 contenus -> approbation -> export -> retrait » (E2E moteur).

DEFINITION-PRODUIT §7 M7, preuve de complétion : « chantier de gouttières terminé à Repentigny -> 5 contenus ->
approbation -> publication ou export -> mesure ». L'audit M7 (§2.8) constatait que ce scénario ne pouvait pas
s'exécuter : un seul brouillon, aucun paquet manuel, aucun registre de retrait du consentement. Ces tests le
jouent par la vraie porte d'appareil (mêmes gestes, même harnais que `test_demande_d_avis_appareil.py`) :

- A. « Terminer » avec le consentement du client à l'usage de son chantier : M7 propose les cinq contenus
  (Facebook, Instagram, fiche Google, script de vidéo courte, demande de témoignage), tous `PROPOSE`, chacun avec
  son lien de suivi et la preuve du consentement ; le propriétaire les voit dans « À voir » (une attente N3 chacun)
  et les lit en entier ; l'employé, lui, n'a pas ces outils (403).
- B. Un texte que le modèle rédige avec un prix est refusé en nommant la règle ; corrigé, il est proposé.
- C. Le propriétaire approuve depuis son téléphone (N3, validation au départ, tracée par le socle) ; un
  gestionnaire `admin` qui n'est pas le propriétaire ne le peut pas ; le paquet manuel est remis (texte,
  mots-clics, lien, médias « à flouter à la main », heure du profil) ; RIEN n'est publié, jamais.
- D. Sans consentement à l'usage du chantier (aucun, celui d'un avis seulement, refusé, ou client insatisfait) : rien.
- E. Le client retire son consentement : tout est bloqué, un paquet approuvé et déjà exporté compris.

La version du texte de consentement est celle que l'app envoie : lue dans `mobile/src/m4/consentementClient.ts`.
Ce que ces tests ne prouvent PAS : l'écran (Jest, `mobile/`) ni le core.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import pytest
from harnais_e2e import Moteur, Reponse, iso
from harnais_e2e_chantier import (
    AppEmploye,
    Chantier,
    debut_de_journee,
    preparer_chantier,
    receptionner_materiel_args,
)
from m7_marketing import outils as m7_outils
from m7_marketing.brand import profil_client
from m7_marketing.social import postiz_adapter
from sqlalchemy import select

from opsys import approbations, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
RACINE = Path(__file__).resolve().parents[2]
CONSOMMATEURS_WCT = {"m02-revenue-crm", "m03-estimation", "m05-financecore", "m06-material-control",
                     "m07-marketing", "m08-analytics", "m10-memoire"}
PLATEFORMES = ["facebook", "instagram", "fiche_google", "video_courte", "demande_temoignage"]
LISTER, DECIDER, EXPORTER, RETIRER = (
    "m7_lister_contenus_chantier", "m7_decider_contenu", "m7_exporter_paquet_manuel",
    "m7_enregistrer_retrait_consentement_marketing",
)
A_VOIR = "m9_lister_demandes_approbation"
PROFIL_DU_CLIENT = {
    "name": "Gouttières et Revêtements Synergy (fictif)",
    "tagline": "Rénovation extérieure au Québec, sans surprise",
    "tone": "professionnel, chaleureux",
    "colors": ["#1a1a1a", "#ffffff"],
    "langue": "fr",
    "site_url": "https://synergy-fictif.example/",
    "heures_publication": {"facebook": "18:30", "instagram": "19:15", "fiche_google": "10:00"},
}


@pytest.fixture(scope="module")
def version_du_texte() -> str:
    source = (RACINE / "mobile/src/m4/consentementClient.ts").read_text(encoding="utf-8")
    trouve = re.search(r'VERSION_TEXTE_CONSENTEMENT_CLIENT\s*=\s*"([^"]+)"', source)
    assert trouve is not None, "la constante de version n'est plus dans l'app"
    return trouve.group(1)


@pytest.fixture
def marque_configuree(monkeypatch):
    """Le profil de marque du client, configuré (jamais un argument d'outil) ; sans lui M7 refuse (fail-closed)."""
    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(PROFIL_DU_CLIENT), None))


@pytest.fixture(autouse=True)
def rien_n_est_publie(monkeypatch):
    """M7 ne publie jamais : si un chemin de ces scénarios atteignait l'adaptateur de publication, le test échoue."""
    def _interdit(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("M7 ne doit jamais publier : export manuel seulement")

    monkeypatch.setattr(postiz_adapter.PostizAdapter, "publier", _interdit)


class AppEmployeAvecClient(AppEmploye):
    """L'app de l'employé dont « Terminer » joint ce que l'employé a recueilli auprès du client (`champs_client`) et
    la photo déposée comme photo du chantier (`photos`, références seulement)."""

    def __init__(self, *args: Any, champs_client: dict[str, Any] | None = None, **options: Any) -> None:
        super().__init__(*args, **options)
        self.champs_client = champs_client or {}

    def terminer(self, photo: str, signature: str) -> Reponse:
        return self._envoyer("m4_completer_intervention", {
            "intervention_id": self.chantier.intervention_id, "horodatage": self.heure_appareil(),
            "preuves_completion": {"checklist_complete": True, "photos_apres": [photo],
                                   "notes": "Installation terminée, aucun imprévu (fictif).",
                                   "signature": signature},
            "signature_requise": True, "photos": [photo], **self.champs_client})


# -- lectures de l'état durable -----------------------------------------------------------------------------
def _registre_m7(nom: str) -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def _evenements(type_evenement: str) -> list[dict[str, Any]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement).order_by(EVENEMENTS_SORTANTS.c.cree_le)).all()
    return [{"evenement_id": ligne.evenement_id, **codec.decoder(ligne.charge)} for ligne in lignes]


def _recus(evenement_id: str) -> dict[str, str]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_RECUS.c.consommateur, EVENEMENTS_RECUS.c.statut).where(
            EVENEMENTS_RECUS.c.evenement_id == evenement_id)).all()
    return {ligne.consommateur: ligne.statut for ligne in lignes}


def _appel_agent(nom: str, **arguments: Any) -> dict[str, Any]:
    """Un appel d'AGENT (Hermes, sans jeton d'appareil), par le vrai outil du vrai manifeste."""
    outil = next(o for o in m7_outils.outils() if o.nom == nom)
    reponse = executer_atomique(outil, arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _lire_les_contenus(admin, **filtres: Any) -> dict[str, Any]:
    """Comme l'app : page 0, puis `suivant` tant qu'il n'est pas nul. Chaque page tient sous la troncature de
    `Capacites` (6 000 caractères) ; l'union des pages est la liste entière, sans doublon."""
    page = admin.appeler(LISTER, {"limite": 8, **filtres})
    lues: list[dict[str, Any]] = []
    total = page.resultat["total"]
    while True:
        assert page.statut == 200 and page.mesure.tronque is False and page.mesure.octets_texte < 6000
        assert page.resultat["total"] == total
        lues.extend(page.resultat["contenus"])
        if page.resultat["suivant"] is None:
            break
        assert page.resultat["reste"] > 0 and len(lues) < 40, "la lecture ne progresse pas"
        page = admin.appeler(LISTER, {"limite": 8, "decalage": page.resultat["suivant"], **filtres})
    assert len({c["contenu_id"] for c in lues}) == len(lues) == total
    return {"total": total, "contenus": lues}


def _attentes_de_m7(admin) -> list[dict[str, Any]]:
    """Comme l'app : page 0, puis `attentes_suivant` tant qu'il n'est pas nul ; ne garde que les contenus de M7."""
    page = admin.appeler(A_VOIR, {}).resultat
    lues = list(page["attentes"])
    while page["attentes_suivant"] is not None:
        page = admin.appeler(A_VOIR, {"decalage_attentes": page["attentes_suivant"]}).resultat
        lues.extend(page["attentes"])
    return [a for a in lues if a["type"] == "contenu_a_approuver"]


# -- la journée --------------------------------------------------------------------------------------------
def _chantier_termine(
    moteur: Moteur, equipe: dict[str, Any], suffixe: str, jour: int, champs_client: dict[str, Any],
) -> tuple[Chantier, AppEmployeAvecClient, Reponse]:
    """Chantier préparé, matériel reçu, journée de l'employé jusqu'à « Terminer » (avec `champs_client`), le bus
    livre la complétion, l'employé déclare ses matériaux, le bus livre la variance."""
    chantier = preparer_chantier(moteur.departements, suffixe=suffixe, technicien="etienne",
                                 debut=debut_de_journee(jour))
    moteur.horloge.maintenant = chantier.debut
    moteur.drainer_bus(moteur.horloge.maintenant)
    reception = equipe["admin"].appeler(
        "m6_receptionner_commande", receptionner_materiel_args(chantier), cle=f"mut-reception-{suffixe}",
        horodatage_appareil=iso(chantier.debut))
    assert reception.metier["accepte"] is True, reception.metier
    app = AppEmployeAvecClient(moteur, equipe["employe"], chantier, champs_client=champs_client)
    completion = app.journee_jusqu_a_la_completion()
    assert completion.metier["accepte"] is True, completion.metier
    moteur.drainer_bus(moteur.horloge.maintenant)
    app.attendre(minutes=5)
    assert app.declarer_materiaux(completion.resultat["wct_id"], 42.0).metier["accepte"] is True
    moteur.drainer_bus(moteur.horloge.maintenant)
    return chantier, app, completion


def _champs_marketing(version: str, **plus: Any) -> dict[str, Any]:
    return {"consentement_marketing": True, "consentement_version_texte": version, "client_satisfait": True, **plus}


@pytest.fixture
def gestionnaire(moteur, monkeypatch):
    """Une gestionnaire `admin` qui n'est PAS le propriétaire (elle voit, mais ne décide pas à sa place)."""
    moteur.creer_personne("gestionnaire", "Gestionnaire (fictive)", ["admin"], monkeypatch)
    return moteur.appairer("gestionnaire", "admin")


def _decider(admin, contenu_id: str, decision: str, moteur: Moteur, cle: str, motif: str | None = None) -> Reponse:
    args = {"contenu_id": contenu_id, "decision": decision, "horodatage": iso(moteur.horloge.maintenant)}
    if motif:
        args["motif"] = motif
    return admin.appeler(DECIDER, args, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant, -60))


# =============================================================================================================
# A. « Terminer » avec le consentement : cinq contenus en attente, dans « À voir »
# =============================================================================================================
@SQLITE_SEULEMENT
def test_terminer_avec_consentement_donne_cinq_contenus_en_attente_que_le_proprietaire_lit(
    moteur, equipe, version_du_texte, marque_configuree,
):
    chantier, app, completion = _chantier_termine(moteur, equipe, "USINE-A", 15, _champs_marketing(version_du_texte))
    wct_id = completion.resultat["wct_id"]

    # -- le WCT publié porte le consentement à l'usage du chantier ET sa preuve, posée par le serveur -----------
    (publie,) = _evenements("m4.travaux_termines")
    assert publie["consentement_marketing"] is True and publie["client_satisfait"] is True
    assert publie["consentement_recueilli_par"] == "etienne"
    assert publie["consentement_version_texte"] == version_du_texte
    assert "consentement_demande_avis" not in publie  # l'autre consentement (un avis) n'a pas été donné
    assert _recus(wct_id) == dict.fromkeys(CONSOMMATEURS_WCT, "traite")

    # -- M7 : cinq contenus PROPOSE, un par plateforme, jamais approuvés ni publiés ----------------------------
    propositions = _registre_m7("contenus_chantier")
    assert [p["plateforme"] for p in propositions] == PLATEFORMES
    assert {p["approval_status"] for p in propositions} == {"PROPOSE"} and {p["revision"] for p in propositions} == {1}
    assert {p["origine"] for p in propositions} == {"bus:m4.travaux_termines"}
    assert {p["wct_id"] for p in propositions} == {wct_id} and {p["photos"][0] for p in propositions} == {
        publie["photos"][0]}
    for proposition in propositions:
        assert proposition["preuve_consentement"]["recueilli_par"] == "etienne"
        assert proposition["preuve_consentement"]["recueilli_le"] == publie["consentement_recueilli_le"]
        assert chantier.lead_id not in proposition["texte"] and wct_id not in proposition["texte"]
    assert [p["lien_utm"] is not None for p in propositions] == [True, True, True, True, False]
    assert _registre_m7("decisions_contenu") == [] and _registre_m7("exports_paquet") == []
    with stockage.transaction() as cnx:
        assert approbations.lister(cnx, "en_attente") == []  # rien n'attend une approbation formelle du socle

    # -- l'admin lit les cinq textes en entier, avec la preuve du consentement -----------------------------------
    premiere_page = equipe["admin"].appeler(LISTER, {"limite": 8})
    assert premiere_page.statut == 200 and premiere_page.mesure.tronque is False
    contenus = _lire_les_contenus(equipe["admin"])
    assert contenus["total"] == 5
    par_plateforme = {c["plateforme"]: c for c in contenus["contenus"]}
    assert set(par_plateforme) == set(PLATEFORMES)
    assert {c["approval_status"] for c in contenus["contenus"]} == {"PROPOSE"}
    facebook = par_plateforme["facebook"]
    # Le WCT n'a pas de ville (M4 ne la publie pas) : aucune n'est inventée.
    assert facebook["texte"].startswith("Chantier terminé : renovation totale.")
    assert "Gouttières et Revêtements Synergy (fictif)" in facebook["texte"]
    assert any("ville absente du WCT" in a for a in facebook["avertissements"])
    assert facebook["consentement"]["recueilli_par"] == "etienne"
    assert facebook["lien_utm"].startswith("https://synergy-fictif.example/?utm_source=facebook&utm_medium=social")
    assert par_plateforme["demande_temoignage"]["lien_utm"] is None

    # -- « À voir » : une attente N3 par contenu, que le propriétaire décidera ---------------------------------
    attentes = _attentes_de_m7(equipe["admin"])
    assert len(attentes) == 5 and {a["id"] for a in attentes} == {c["contenu_id"] for c in contenus["contenus"]}
    assert {a["niveau"] for a in attentes} == {"N3"}
    assert all("m7_decider_contenu" in a["action_proposee"] for a in attentes)

    # -- l'employé recueille le consentement, il ne voit ni ne décide rien de ce contenu ---------------------
    for outil in (LISTER, DECIDER, EXPORTER, RETIRER):
        refus = equipe["employe"].appeler(outil, {})
        assert refus.statut == 403 and "tool_out_of_scope" in refus.corps["error"]["message"], outil

    # -- rejeu de « Terminer » (réseau coupé après l'envoi) : aucun double contenu -----------------------------
    terminer = next(a for a in app.appels if a.outil == "m4_completer_intervention")
    avant = moteur.empreinte_etat()
    assert app.rejouer(terminer).enveloppe["rejoue"] is True
    moteur.drainer_bus(moteur.horloge.maintenant)
    assert moteur.empreinte_etat() == avant and len(_registre_m7("contenus_chantier")) == 5


# =============================================================================================================
# B. Un texte rédigé par le modèle avec un prix est refusé, nommé ; corrigé, il est proposé
# =============================================================================================================
@SQLITE_SEULEMENT
def test_un_texte_du_modele_avec_un_prix_est_refuse_en_nommant_la_regle_puis_corrige(
    moteur, equipe, version_du_texte, monkeypatch,
):
    # Le profil de marque n'est pas encore configuré (décision de Nathan) : « Terminer » passe, M7 ne compose rien.
    chantier, _, completion = _chantier_termine(moteur, equipe, "USINE-B", 16, _champs_marketing(version_du_texte))
    wct_id = completion.resultat["wct_id"]
    assert _registre_m7("contenus_chantier") == [] and [w["wct_id"] for w in _registre_m7("wct_recus")] == [wct_id]
    assert _appel_agent("m7_lire_matiere_chantier", wct_id=wct_id)["statut"] == "profil_marque_non_configure"

    monkeypatch.setattr(profil_client, "charger_profil_client", lambda: (dict(PROFIL_DU_CLIENT), None))
    matiere = _appel_agent("m7_lire_matiere_chantier", wct_id=wct_id)
    assert matiere["statut"] == "ok" and matiere["matiere"]["nature"] == "renovation totale"
    assert "REJ-PRIX" in matiere["regles"] and matiere["matiere"]["note_du_chantier"] is None

    avec_prix = "Rénovation totale terminée, à partir de 18 500 $ : demandez votre soumission."
    resultat = _appel_agent("m7_proposer_contenus_chantier", wct_id=wct_id, textes={"facebook": avec_prix})
    assert resultat["statut"] == "partiel"
    facebook = next(i for i in resultat["contenus"] if i["plateforme"] == "facebook")
    assert facebook["statut"] == "refuse" and [r["regle"] for r in facebook["regles"]] == ["REJ-PRIX"]
    assert {p["plateforme"] for p in _registre_m7("contenus_chantier")} == set(PLATEFORMES) - {"facebook"}
    assert "18 500" not in str(_registre_m7("contenus_chantier"))  # le texte refusé n'existe nulle part

    propre = "Une rénovation totale terminée avec soin par notre équipe. Demandez votre soumission."
    corrige = _appel_agent("m7_proposer_contenus_chantier", wct_id=wct_id, textes={"facebook": propre})
    assert corrige["statut"] == "propose"
    lecture = _lire_les_contenus(equipe["admin"], wct_id=wct_id)
    assert lecture["total"] == 5
    assert next(c for c in lecture["contenus"] if c["plateforme"] == "facebook")["origine_texte"] == "modele"
    assert {c["origine_texte"] for c in lecture["contenus"] if c["plateforme"] != "facebook"} == {"gabarit"}
    assert chantier.chantier_id  # le chantier de la démonstration existe bien


# =============================================================================================================
# C. Approbation du propriétaire, paquet manuel exporté, rien de publié
# =============================================================================================================
@SQLITE_SEULEMENT
def test_le_proprietaire_approuve_puis_prend_le_paquet_a_publier_lui_meme(
    moteur, equipe, gestionnaire, version_du_texte, marque_configuree,
):
    _, _, completion = _chantier_termine(moteur, equipe, "USINE-C", 17, _champs_marketing(version_du_texte))
    wct_id = completion.resultat["wct_id"]
    admin = equipe["admin"]
    contenus = {c["plateforme"]: c for c in _lire_les_contenus(admin)["contenus"]}
    facebook, instagram = contenus["facebook"]["contenu_id"], contenus["instagram"]["contenu_id"]

    # -- avant l'approbation, rien ne s'exporte -------------------------------------------------------------------
    non_approuve = admin.appeler(EXPORTER, {"contenu_id": facebook, "horodatage": iso(moteur.horloge.maintenant)},
                                 cle="mut-export-avant", horodatage_appareil=iso(moteur.horloge.maintenant))
    assert non_approuve.metier["accepte"] is False
    assert non_approuve.metier["verdict"]["code"] == "REJ-CONTENU-NON-APPROUVE"
    assert _registre_m7("exports_paquet") == []

    # -- la gestionnaire (admin, pas propriétaire) ne décide pas à la place de Nathan ------------------------
    refus = _decider(gestionnaire, facebook, "approuver", moteur, "mut-gestionnaire")
    assert refus.metier["accepte"] is False and refus.metier["verdict"]["code"] == "REJ-HUMAIN-ROLE-INSUFFISANT"
    assert _registre_m7("decisions_contenu") == []

    # -- Nathan approuve depuis son téléphone : N3, validation au départ, tracée par le socle ----------------
    approbation = _decider(admin, facebook, "approuver", moteur, "mut-approuver-facebook")
    assert approbation.statut == 200 and approbation.metier["accepte"] is True
    decision = approbation.resultat
    assert (decision["approval_status"], decision["par"], decision["source"]) == ("APPROVED", "nathan", "appareil")
    (maillon,) = _registre_m7("decisions_contenu")
    assert maillon["contenu_id"] == facebook and maillon["role"] == "nathan_owner"
    # L'heure de RÉCEPTION du serveur (le même instant, en UTC), pas celle du téléphone (en retard de cinq minutes).
    assert dt.datetime.fromisoformat(maillon["horodatage"]) == moteur.horloge.maintenant
    with stockage.transaction() as cnx:
        traces = {d["decide_par"]: d for d in approbations.lister(cnx, "executee") if d["outil"] == DECIDER}
    # Le socle trace le geste de chacun : celui du propriétaire (accepté) et la tentative de la gestionnaire (refusée).
    assert set(traces) == {"nathan", "gestionnaire"}
    assert (traces["nathan"]["niveau"], traces["nathan"]["departement"]) == ("N3", "m07-marketing")
    assert traces["nathan"]["resultat"]["accepte"] is True and traces["gestionnaire"]["resultat"]["accepte"] is False

    # -- le rejeu de la même décision ne change rien ---------------------------------------------------------------
    avant = moteur.empreinte_etat()
    rejeu = _decider(admin, facebook, "approuver", moteur, "mut-approuver-facebook")
    assert rejeu.enveloppe["rejoue"] is True and moteur.empreinte_etat() == avant

    # -- Instagram : rejeté avec son motif, puis remplacé par un nouveau texte (révision 2) ------------------
    sans_motif = _decider(admin, instagram, "rejeter", moteur, "mut-rejet-sans-motif")
    assert sans_motif.metier["verdict"]["code"] == "REJ-MOTIF-REQUIS"
    rejet = _decider(admin, instagram, "rejeter", moteur, "mut-rejet-instagram", "trop vendeur pour notre voix")
    assert rejet.metier["accepte"] is True and rejet.resultat["approval_status"] == "REJECTED"
    nouvelle = _appel_agent("m7_proposer_contenus_chantier", wct_id=wct_id, textes={
        "instagram": "Une rénovation terminée avec soin. Notre équipe est fière du résultat."})
    assert next(i for i in nouvelle["contenus"] if i["plateforme"] == "instagram")["revision"] == 2

    # -- « À voir » : il reste 4 attentes (Facebook est décidé, Instagram en révision 2 attend) --------------
    attentes = _attentes_de_m7(admin)
    assert len(attentes) == 4 and facebook not in {a["id"] for a in attentes}
    assert instagram not in {a["id"] for a in attentes}  # la révision 1 est rejetée, la 2 a un autre identifiant

    # -- le paquet manuel : ce que le propriétaire copie et publie lui-même ----------------------------------
    export = admin.appeler(EXPORTER, {"contenu_id": facebook, "horodatage": iso(moteur.horloge.maintenant)},
                           cle="mut-export-facebook", horodatage_appareil=iso(moteur.horloge.maintenant, -60))
    assert export.statut == 200 and export.metier["accepte"] is True
    paquet = export.resultat
    assert paquet["plateforme"] == "facebook" and paquet["public"] is True and paquet["deja_exporte"] is False
    assert paquet["texte"] == contenus["facebook"]["texte"] and paquet["approuve_par"] == "nathan"
    assert paquet["lien_utm"].startswith("https://synergy-fictif.example/?utm_source=facebook")
    assert paquet["texte_a_copier"].startswith(paquet["texte"]) and paquet["lien_utm"] in paquet["texte_a_copier"]
    assert paquet["heure_suggeree"] == {"heure_locale": "18:30", "source": "profil de marque (heures_publication)"}
    assert paquet["publication"].startswith("manuelle")
    (media,) = paquet["medias"]
    assert media["statut"] == "a_flouter_a_la_main" and media["reference"].startswith("fichier:sha256:")
    assert "flouter à la main" in media["instruction"] and "sûr" not in media["instruction"]
    assert any("visage" in etape for etape in paquet["instructions"])
    (trace,) = _registre_m7("exports_paquet")
    assert trace["contenu_id"] == facebook and trace["exporte_par"] == "nathan"
    assert _lire_les_contenus(admin, statut="APPROVED")["contenus"][0]["exporte"] is True

    # -- la demande de témoignage : le client n'a pas consenti à être contacté, le paquet le dit -------------
    temoignage = contenus["demande_temoignage"]["contenu_id"]
    assert _decider(admin, temoignage, "approuver", moteur, "mut-approuver-temoignage").metier["accepte"] is True
    paquet_temoignage = admin.appeler(
        EXPORTER, {"contenu_id": temoignage, "horodatage": iso(moteur.horloge.maintenant)},
        cle="mut-export-temoignage", horodatage_appareil=iso(moteur.horloge.maintenant, -60)).resultat
    assert paquet_temoignage["public"] is False and paquet_temoignage["contact_client"]["autorise"] is False
    assert paquet_temoignage["medias"] == [] and paquet_temoignage["lien_utm"] is None


@SQLITE_SEULEMENT
def test_un_agent_ne_peut_pas_approuver_a_la_place_du_proprietaire(moteur, equipe, version_du_texte, marque_configuree):
    _chantier_termine(moteur, equipe, "USINE-C2", 18, _champs_marketing(version_du_texte))
    contenu = equipe["admin"].appeler(LISTER, {"limite": 1}).resultat["contenus"][0]
    with stockage.transaction():
        outil = next(o for o in m7_outils.outils() if o.nom == DECIDER)
    reponse = executer_atomique(outil, {"contenu_id": contenu["contenu_id"], "decision": "approuver",
                                        "horodatage": iso(moteur.horloge.maintenant)})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _registre_m7("decisions_contenu") == []


# =============================================================================================================
# D. Sans consentement à l'usage du chantier : rien
# =============================================================================================================
CAS_SANS_CONTENU = {
    "aucun_choix": {},
    "avis_seulement": {"consentement_demande_avis": True},
    "refus_explicite": {"consentement_marketing": False},
    "client_insatisfait": {"consentement_marketing": True, "client_satisfait": False},
}


@pytest.mark.parametrize("cas", list(CAS_SANS_CONTENU))
@SQLITE_SEULEMENT
def test_terminer_sans_consentement_a_l_usage_du_chantier_ne_propose_aucun_contenu(
    moteur, equipe, version_du_texte, marque_configuree, cas,
):
    champs = dict(CAS_SANS_CONTENU[cas])
    if champs:
        champs["consentement_version_texte"] = version_du_texte
    jour = 19 + list(CAS_SANS_CONTENU).index(cas)
    _, app, completion = _chantier_termine(moteur, equipe, f"USINE-D-{cas}", jour, champs)
    wct_id = completion.resultat["wct_id"]

    # « Terminer » réussit quand même : refuser son consentement ne bloque jamais le chantier.
    assert app.statut().resultat["statut"] == "completed_verified"
    assert _recus(wct_id) == dict.fromkeys(CONSOMMATEURS_WCT, "traite")
    assert [w["wct_id"] for w in _registre_m7("wct_recus")] == [wct_id]  # le fait reçu reste enregistré

    # M7 n'a composé RIEN : ni contenu, ni décision, ni export, ni attente.
    assert _registre_m7("contenus_chantier") == []
    lecture = equipe["admin"].appeler(LISTER, {}).resultat
    assert (lecture["total"], lecture["contenus"]) == (0, [])
    assert _attentes_de_m7(equipe["admin"]) == []
    assert _appel_agent("m7_proposer_contenus_chantier", wct_id=wct_id)["contenus"] == []
    assert _registre_m7("contenus_chantier") == []


# =============================================================================================================
# E. Le client retire son consentement : tout est bloqué, un paquet déjà approuvé et exporté compris
# =============================================================================================================
@SQLITE_SEULEMENT
def test_le_retrait_du_consentement_bloque_tout_y_compris_un_paquet_approuve_et_exporte(
    moteur, equipe, version_du_texte, marque_configuree,
):
    chantier, _, completion = _chantier_termine(moteur, equipe, "USINE-E", 23, _champs_marketing(version_du_texte))
    wct_id = completion.resultat["wct_id"]
    admin = equipe["admin"]
    contenus = {c["plateforme"]: c for c in _lire_les_contenus(admin)["contenus"]}
    facebook, instagram = contenus["facebook"]["contenu_id"], contenus["instagram"]["contenu_id"]
    assert _decider(admin, facebook, "approuver", moteur, "mut-e-approuver").metier["accepte"] is True
    assert admin.appeler(EXPORTER, {"contenu_id": facebook, "horodatage": iso(moteur.horloge.maintenant)},
                         cle="mut-e-export", horodatage_appareil=iso(moteur.horloge.maintenant, -60)
                         ).metier["accepte"] is True
    assert len(_attentes_de_m7(admin)) == 4

    # -- l'employé ne peut pas enregistrer un retrait (le propriétaire ou son gestionnaire, oui) -------------
    assert equipe["employe"].appeler(RETIRER, {}).statut == 403

    # -- le client retire son consentement : le retrait est un fait durable, sans texte libre ----------------
    args_retrait = {"wct_id": wct_id, "canal": "telephone", "horodatage": iso(moteur.horloge.maintenant)}
    retrait = admin.appeler(RETIRER, args_retrait, cle="mut-e-retrait",
                            horodatage_appareil=iso(moteur.horloge.maintenant, -60))
    assert retrait.statut == 200 and retrait.metier["accepte"] is True
    resultat = retrait.resultat
    assert resultat["wct_connu"] is True and resultat["lead_id"] == chantier.lead_id
    assert len(resultat["contenus_bloques"]) == 5 and resultat["contenus_deja_exportes"] == [facebook]
    assert any("retirer à la main" in etape for etape in resultat["a_faire"])
    (maillon,) = _registre_m7("retraits_consentement_marketing")
    assert (maillon["wct_id"], maillon["canal"], maillon["enregistre_par"], maillon["source"]) == (
        wct_id, "telephone", "nathan", "appareil")
    assert set(maillon) == {"retrait_id", "wct_id", "lead_id", "canal", "enregistre_par", "source", "horodatage"}

    # -- tout est bloqué : la liste, « À voir », la décision, l'export, la nouvelle proposition --------------
    bloque = _lire_les_contenus(admin)
    assert {c["approval_status"] for c in bloque["contenus"]} == {"CONSENTEMENT_RETIRE"}
    assert _attentes_de_m7(admin) == []
    decision = _decider(admin, instagram, "approuver", moteur, "mut-e-approuver-apres")
    assert decision.metier["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"
    export = admin.appeler(EXPORTER, {"contenu_id": facebook, "horodatage": iso(moteur.horloge.maintenant)},
                           cle="mut-e-export-apres", horodatage_appareil=iso(moteur.horloge.maintenant, -60))
    assert export.metier["verdict"]["code"] == "REJ-CONSENTEMENT-RETIRE"  # même approuvé, même déjà exporté une fois
    assert _appel_agent("m7_proposer_contenus_chantier", wct_id=wct_id)["statut"] == "consentement_retire"
    assert _appel_agent("m7_lire_matiere_chantier", wct_id=wct_id)["statut"] == "consentement_retire"
    assert len(_registre_m7("decisions_contenu")) == 1 and len(_registre_m7("exports_paquet")) == 1
    assert len(_registre_m7("contenus_chantier")) == 5  # l'audit ne se réécrit pas : rien de perdu, tout bloqué

    # -- le rejeu ne change rien, et le retrait ne se lève pas -----------------------------------------------
    avant = moteur.empreinte_etat()
    rejeu = admin.appeler(RETIRER, args_retrait, cle="mut-e-retrait",
                          horodatage_appareil=iso(moteur.horloge.maintenant, -60))
    assert rejeu.enveloppe["rejoue"] is True and moteur.empreinte_etat() == avant
    autre_cle = admin.appeler(RETIRER, {"wct_id": wct_id, "canal": "sms", "horodatage": iso(moteur.horloge.maintenant)},
                              cle="mut-e-retrait-bis", horodatage_appareil=iso(moteur.horloge.maintenant, -60))
    assert autre_cle.resultat["deja_enregistre"] is True and len(_registre_m7("retraits_consentement_marketing")) == 1

    # -- la demande d'avis, elle, est un autre consentement : le retrait de l'usage du chantier ne la touche pas ---
    assert _registre_m7("demandes_avis") == []  # le client n'avait consenti qu'à l'usage du chantier, pas à un avis
