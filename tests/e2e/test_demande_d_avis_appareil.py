"""PLAN T1.5-d (M7) — la demande d'avis naît d'un « Terminer » de l'app, avec le consentement du client (E2E moteur).

DEFINITION-PRODUIT §6, cascade « travaux terminés », ligne M7 : « propose une demande d'avis et, avec
consentement, du contenu avant/après ». Constat de T1.5 : aucune demande d'avis ne naissait d'un « Terminer »
depuis l'app, qui n'envoyait aucun des champs du client. L'écran « Terminer » recueille désormais, auprès du
client, son consentement à être contacté pour un avis (`mobile/src/m4/consentementClient.ts`) ; M4 le porte
dans le WCT avec la personne authentifiée et l'heure du serveur ; M7 le lit dans le WCT reçu par le bus et
PROPOSE un brouillon, jamais envoyé.

Ces tests jouent la journée de l'employé par la vraie porte d'appareil (mêmes gestes, même harnais que
`test_travaux_termines_appareil.py`), avec pour seule différence les champs du client que « Terminer » envoie :

- avec le consentement à la demande d'avis : un brouillon chez M7, que l'admin lit sur son téléphone
  (`m7_lister_demandes_avis`) avec la preuve du consentement ; l'employé, lui, n'a pas cet outil (403) ;
- sans consentement, avec le seul consentement aux photos (un autre consentement, Loi 25),
  ou avec un refus explicite : rien ; la satisfaction n'exclut aucun client consentant ;
- l'appareil ne peut pas écrire lui-même « recueilli par » ni l'heure : le serveur les pose ;
- pour un lead v2, le brouillon dit le libellé du service déclaré par l'entreprise, pas son code (T0.13-b).

La version du texte de consentement est celle que l'app envoie : lue dans `mobile/src/m4/consentementClient.ts`,
jamais recopiée ici. Ce que ces tests ne prouvent PAS : l'écran (Jest, `mobile/`) ni le core.
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
from sqlalchemy import select

from opsys import approbations, stockage
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
LISTER_DEMANDES_AVIS = "m7_lister_demandes_avis"
RACINE = Path(__file__).resolve().parents[2]
CONSOMMATEURS_WCT = {"m02-revenue-crm", "m03-estimation", "m05-financecore", "m06-material-control",
                     "m07-marketing", "m08-analytics", "m10-memoire"}


@pytest.fixture(scope="module")
def version_du_texte() -> str:
    """La version du texte de consentement que l'app envoie, lue dans son code : si l'app la change, ce test
    suit ; si elle n'a plus le format que M4 exige, il échoue."""
    source = (RACINE / "mobile/src/m4/consentementClient.ts").read_text(encoding="utf-8")
    trouve = re.search(r'VERSION_TEXTE_CONSENTEMENT_CLIENT\s*=\s*"([^"]+)"', source)
    assert trouve is not None, "la constante de version n'est plus dans l'app"
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", trouve.group(1))
    return trouve.group(1)


class AppEmployeAvecClient(AppEmploye):
    """L'app de l'employé dont « Terminer » joint ce que l'employé a recueilli auprès du client (`champs_client`,
    comme `construireChampsClient` de l'app : une clé par consentement donné, jamais `false` pour une case
    décochée). Tout le reste est celui de `AppEmploye`."""

    def __init__(self, *args: Any, champs_client: dict[str, Any] | None = None, **options: Any) -> None:
        super().__init__(*args, **options)
        self.champs_client = champs_client or {}

    def terminer(self, photo: str, signature: str) -> Reponse:
        return self._envoyer("m4_completer_intervention", {
            "intervention_id": self.chantier.intervention_id, "horodatage": self.heure_appareil(),
            "preuves_completion": {"checklist_complete": True, "photos_apres": [photo],
                                   "notes": "Installation terminée, aucun imprévu (fictif).",
                                   "signature": signature},
            "signature_requise": True, **self.champs_client})


# -- lectures de l'état durable -----------------------------------------------------------------------------
def _demandes_avis_de_m7() -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", "demandes_avis"))


def _wct_recus_de_m7() -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", "wct_recus"))


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


def _recu_le_par_le_serveur(app: AppEmploye) -> str:
    """L'heure de réception du dernier « Terminer » : celle du serveur (UTC), pas celle du téléphone, qui
    retarde de `derive_appareil_s`."""
    terminer = [a for a in app.appels if a.outil == "m4_completer_intervention"][-1]
    return (dt.datetime.fromisoformat(terminer.horodatage_appareil)
            - dt.timedelta(seconds=app.derive_appareil_s)).astimezone(dt.UTC).isoformat()


# -- la journée -------------------------------------------------------------------------------------------
def _chantier_termine(
    moteur: Moteur, equipe: dict[str, Any], suffixe: str, jour: int, champs_client: dict[str, Any], *,
    version_lead: int = 1,
) -> tuple[Chantier, AppEmployeAvecClient, Reponse]:
    """Chantier préparé, matériel reçu, journée de l'employé jusqu'à « Terminer » (avec `champs_client`), le bus
    livre la complétion, l'employé déclare 42 pi de matériaux (prévu 40 : +5 %), le bus livre la variance."""
    chantier = preparer_chantier(moteur.departements, suffixe=suffixe, technicien="etienne",
                                 debut=debut_de_journee(jour), version_lead=version_lead)
    moteur.horloge.maintenant = chantier.debut
    moteur.drainer_bus(moteur.horloge.maintenant)  # le devis accepté est livré à M6 (prévu de matériaux)
    reception = equipe["admin"].appeler(
        "m6_receptionner_commande", receptionner_materiel_args(chantier), cle=f"mut-reception-{suffixe}",
        horodatage_appareil=iso(chantier.debut))
    assert reception.metier["accepte"] is True, reception.metier
    app = AppEmployeAvecClient(moteur, equipe["employe"], chantier, champs_client=champs_client)
    completion = app.journee_jusqu_a_la_completion()
    moteur.drainer_bus(moteur.horloge.maintenant)
    app.attendre(minutes=5)
    declaration = app.declarer_materiaux(completion.resultat["wct_id"], 42.0)
    assert declaration.metier["accepte"] is True, declaration.metier
    moteur.drainer_bus(moteur.horloge.maintenant)
    return chantier, app, completion


# =============================================================================================
# A. Le client consent à la demande d'avis : M7 propose un brouillon, l'admin le lit, rien n'est envoyé.
# =============================================================================================
@SQLITE_SEULEMENT
@pytest.mark.parametrize("satisfaction", [True, False, None], ids=["satisfait", "insatisfait", "non_evalue"])
def test_terminer_avec_le_consentement_du_client_propose_une_demande_d_avis_a_l_admin(
    moteur, equipe, version_du_texte, satisfaction,
):
    champs = {"consentement_demande_avis": True, "consentement_version_texte": version_du_texte}
    if satisfaction is not None:
        champs["client_satisfait"] = satisfaction
    chantier, app, completion = _chantier_termine(moteur, equipe, "AVIS-OUI", 15, champs)
    wct_id = completion.resultat["wct_id"]

    # -- tous les gestes de l'employé sont acceptés, « Terminer » compris ---------------------------------
    assert [a.reponse.statut for a in app.appels] == [200] * len(app.appels)
    for appel in app.appels:
        assert appel.reponse.enveloppe["rejoue"] is False, appel.outil
        assert appel.reponse.metier["accepte"] is True, (appel.outil, appel.reponse.metier)
    terminer = next(a for a in app.appels if a.outil == "m4_completer_intervention")
    assert {cle for cle in terminer.args if cle.startswith("consentement")} == {
        cle for cle in champs if cle.startswith("consentement")
    }

    # -- le WCT publié porte le consentement ET sa preuve, posée par le serveur -------------------------
    (publie,) = _evenements("m4.travaux_termines")
    assert publie["evenement_id"] == wct_id
    assert publie["consentement_demande_avis"] is True
    assert publie["consentement_version_texte"] == version_du_texte
    assert publie["consentement_recueilli_par"] == "etienne"  # la personne du jeton, jamais un argument
    assert publie["consentement_recueilli_le"] == _recu_le_par_le_serveur(app)  # l'heure du serveur
    assert publie["consentement_recueilli_le"] != terminer.horodatage_appareil  # pas celle du téléphone
    assert "consentement_marketing" not in publie  # l'autre consentement (photos) n'a pas été donné

    # -- le bus : tous les consommateurs traitent ce WCT, M6 comprise (elle refuse toute clé inconnue) ---
    assert _recus(wct_id) == dict.fromkeys(CONSOMMATEURS_WCT, "traite")
    assert app.statut().resultat["statut"] == "completed_verified"  # la déclaration de matériaux est passée

    # -- M7 : exactement un brouillon, proposé, jamais envoyé -------------------------------------------
    (brouillon,) = _demandes_avis_de_m7()
    assert brouillon["wct_id"] == wct_id and brouillon["intervention_id"] == chantier.intervention_id
    assert brouillon["approval_status"] == "PROPOSE"
    assert (brouillon["type_travaux"], brouillon["service"]) == ("renovation_totale", None)  # lead v1
    assert "(renovation totale)" in brouillon["texte"]
    assert "avis honnête" in brouillon["texte"]
    assert brouillon["preuve_consentement"] == {
        "consentement_demande_avis": True, "recueilli_par": "etienne",
        "recueilli_le": publie["consentement_recueilli_le"], "version_texte": version_du_texte,
        "source": "wct_m4_travaux_termines", "wct_id": wct_id}
    assert [w["wct_id"] for w in _wct_recus_de_m7()] == [wct_id]

    # -- l'admin le lit sur son téléphone, avec la preuve du consentement ---------------------------------
    lecture = equipe["admin"].appeler(LISTER_DEMANDES_AVIS, {})
    assert lecture.statut == 200
    (vue,) = lecture.resultat["demandes"]
    assert (lecture.resultat["total"], lecture.resultat["reste"]) == (1, 0)
    assert vue["wct_id"] == wct_id and vue["approval_status"] == "PROPOSE"
    assert vue["texte"] == brouillon["texte"]
    assert vue["consentement"] == {"recueilli_par": "etienne", "recueilli_le": publie["consentement_recueilli_le"],
                                   "version_texte": version_du_texte}
    assert lecture.mesure.tronque is False

    # -- l'employé, qui recueille le consentement, n'a pas l'outil qui lit la suite qu'on en donne ---------
    refus = equipe["employe"].appeler(LISTER_DEMANDES_AVIS, {})
    assert refus.statut == 403 and "tool_out_of_scope" in refus.corps["error"]["message"]

    # -- proposée seulement : le brouillon attend une décision humaine, aucune approbation n'est en cours --------
    with stockage.transaction() as cnx:
        assert approbations.lister(cnx, "en_attente") == []

    # -- rejeu de « Terminer » (réseau coupé après l'envoi) : même réponse, aucun double effet --------------
    avant = moteur.empreinte_etat()
    rejeu = app.rejouer(terminer)
    assert rejeu.enveloppe["rejoue"] is True and rejeu.resultat["wct_id"] == wct_id
    moteur.drainer_bus(moteur.horloge.maintenant)
    assert moteur.empreinte_etat() == avant
    assert len(_demandes_avis_de_m7()) == 1


# =============================================================================================
# B. Sans consentement à la demande d'avis : rien. Loi 25 : jamais inventé, jamais déduit d'un autre.
# =============================================================================================
CAS_SANS_DEMANDE = {
    "aucun_choix": ({}, "aucun consentement recueilli : « Terminer » part comme avant"),
    "photos_seulement": ({"consentement_marketing": True},
                         "le consentement aux photos n'est pas celui d'être contacté pour un avis"),
    "refus_explicite": ({"consentement_demande_avis": False},
                        "le client a refusé : un fait, porté tel quel, qui ne produit rien"),
}


@pytest.mark.parametrize("cas", list(CAS_SANS_DEMANDE))
@SQLITE_SEULEMENT
def test_terminer_sans_consentement_a_la_demande_d_avis_ne_propose_rien(moteur, equipe, version_du_texte, cas):
    champs, _pourquoi = CAS_SANS_DEMANDE[cas]
    if "consentement_demande_avis" in champs or "consentement_marketing" in champs:
        champs = {**champs, "consentement_version_texte": version_du_texte}
    chantier, app, completion = _chantier_termine(moteur, equipe, f"AVIS-NON-{cas}", 16, champs)
    wct_id = completion.resultat["wct_id"]

    # « Terminer » réussit quand même : ne pas donner son consentement ne bloque jamais le chantier.
    assert completion.metier["accepte"] is True
    assert app.statut().resultat["statut"] == "completed_verified"
    (publie,) = _evenements("m4.travaux_termines")
    assert _recus(wct_id) == dict.fromkeys(CONSOMMATEURS_WCT, "traite")
    if champs:  # ce que le client a dit est porté tel quel, avec sa preuve
        assert publie["consentement_recueilli_par"] == "etienne"
    else:  # rien n'a été dit : ni consentement, ni preuve, ni personne inventés
        assert not any(cle.startswith("consentement") for cle in publie)

    # M7 a reçu le fait, et n'en fait aucune demande d'avis.
    assert [w["wct_id"] for w in _wct_recus_de_m7()] == [wct_id]
    assert _demandes_avis_de_m7() == []
    lecture = equipe["admin"].appeler(LISTER_DEMANDES_AVIS, {})
    assert lecture.resultat == {"total": 0, "demandes": [], "reste": 0}


# =============================================================================================
# C. L'appareil ne peut pas écrire lui-même qui a recueilli le consentement, ni quand.
# =============================================================================================
@SQLITE_SEULEMENT
def test_l_appareil_ne_peut_pas_ecrire_la_preuve_du_consentement_le_serveur_la_pose(
    moteur, equipe, version_du_texte,
):
    faux = {"consentement_demande_avis": True, "consentement_version_texte": version_du_texte,
            "consentement_recueilli_par": "nathan", "consentement_recueilli_le": "2026-09-01T08:00:00-04:00"}
    chantier = preparer_chantier(moteur.departements, suffixe="AVIS-FAUX", technicien="etienne",
                                 debut=debut_de_journee(17))
    moteur.horloge.maintenant = chantier.debut
    moteur.drainer_bus(moteur.horloge.maintenant)
    app = AppEmployeAvecClient(moteur, equipe["employe"], chantier, champs_client=faux)

    tentative = app.journee_jusqu_a_la_completion()

    # Refusé par le schéma de l'outil (`additionalProperties: false`), avant tout : rien d'écrit ni de publié.
    assert tentative.enveloppe["ok"] is False and tentative.enveloppe["erreur"] == "arguments_invalides"
    assert _evenements("m4.travaux_termines") == []
    assert app.statut().resultat["statut"] == "sur_site"

    # Le même « Terminer » sans la preuve forgée passe, et c'est le serveur qui la pose.
    app.champs_client = {cle: valeur for cle, valeur in faux.items() if not cle.startswith("consentement_recueilli")}
    photo, signature = (a.reponse.resultat["reference"] for a in app.appels if a.outil == "m4_deposer_fichier")
    corrige = app.terminer(photo, signature)
    assert corrige.metier["accepte"] is True
    (publie,) = _evenements("m4.travaux_termines")
    assert publie["consentement_recueilli_par"] == "etienne" != "nathan"
    assert publie["consentement_recueilli_le"] == _recu_le_par_le_serveur(app)


# =============================================================================================
# D. Lead v2 : le brouillon dit le libellé du service déclaré par l'entreprise (PLAN T0.13-b).
# =============================================================================================
@SQLITE_SEULEMENT
def test_lead_v2_la_demande_d_avis_dit_le_libelle_du_service_pas_son_code(
    moteur, equipe, version_du_texte, declarer_services,
):
    declarer_services()  # les services du catalogue de référence : « gouttieres », etc.
    champs = {"consentement_demande_avis": True, "consentement_version_texte": version_du_texte}
    _, _, completion = _chantier_termine(moteur, equipe, "AVIS-V2", 18, champs, version_lead=2)

    (publie,) = _evenements("m4.travaux_termines")
    assert (publie["service"], "type_travaux" in publie) == ("gouttieres", False)  # lead v2 : `service` seulement
    (brouillon,) = _demandes_avis_de_m7()
    assert brouillon["wct_id"] == completion.resultat["wct_id"]
    assert (brouillon["service"], brouillon["type_travaux"]) == ("gouttieres", None)
    assert brouillon["nature_travaux"] == "Gouttières et descentes"
    assert "(Gouttières et descentes)" in brouillon["texte"] and "gouttieres" not in brouillon["texte"]
    assert brouillon["avertissements"] == []
    (vue,) = equipe["admin"].appeler(LISTER_DEMANDES_AVIS, {}).resultat["demandes"]
    assert vue["nature_travaux"] == "Gouttières et descentes"
