"""PLAN T4.8 — le profil vendeur de l'app lit SES leads, sa fiche, ses devis, et note, par la vraie porte d'appareil
(E2E moteur).

DEFINITION-PRODUIT §9.4 : « M2 : ses leads, prochaine meilleure action, Client 360, notes, soumissions ; M3 :
soumissions ; ne voit pas : finances globales, coûts internes au-delà de sa soumission ». Les écrans `leads`,
`lead/[id]` et `quotes` de `mobile/app/(seller)/` appellent six outils ; ce test les appelle comme l'app, sous le nom
nu, avec le rôle `seller`, par la même règle que le core (`PorteAppareil`, relue dans le fork, appliquée au vrai
moteur HTTP MCP sur une base temporaire).

Le scénario : deux vendeurs (A, B) et l'admin (Nathan) ; un même CLIENT qui a une opportunité chez A (`lead-a-1`,
`lead-a-2` converti par le devis `devis-a-2`) et une chez B (`lead-b-1`, avec une note « secrète ») ; un client de B
seulement (`lead-b-2`) ; un lead `nouveau` sans propriétaire ; un devis par lead.

Ce que ces tests prouvent :
- le vendeur A ne voit que SES leads (liste, total, corps brut), sa fiche et son Client 360 ne portent que SES
  opportunités et SES notes ; le lead d'un autre et un lead inconnu donnent le MÊME refus ; l'employé est refusé ;
- 403 sur tous les outils de l'admin (et sur le nom préfixé d'un outil permis : la règle est le nom NU) ;
- une note se rejoue sans double effet (même clé : `rejoue`, un seul maillon, aucun changement d'état ; même clé et
  autre contenu : conflit) ; `auteur` est la personne authentifiée, jamais celle qu'on nomme ;
- les devis : le vendeur lit les siens, le devis d'un autre donne le refus d'un devis inconnu ;
- ce que le serveur rend au vendeur pour un devis (la vue « interne » : avec coût et marge — le serveur n'a pas de vue
  « prix sans coût ») et donc pourquoi l'app la réduit à sa liste blanche ;
- l'app et le serveur parlent la même langue : les catalogues de statuts, de segments et de statuts de devis, les six
  noms d'outils, les clés que l'app lit dans chaque réponse, et la borne des notes (dix notes au maximum, dans la
  réponse du Client 360, sous la limite de sortie du socle), lus dans le code de l'app (`mobile/src/`).
Ce que ces tests ne prouvent PAS : les écrans (Jest, `mobile/`) ni le core.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from harnais_e2e import Moteur, PorteAppareil, Reponse, iso
from m2_revenue_crm import segments as segments_m2
from m2_revenue_crm import statuts as statuts_m2
from m2_revenue_crm import verdicts as verdicts_m2
from m3_estimation import devis_durable

from opsys import cli, idempotence, openclaw
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
RACINE = Path(__file__).resolve().parents[2]
MOBILE_SRC = RACINE / "mobile" / "src"
FIXTURE_APP = MOBILE_SRC / "vendeur" / "fixtures" / "reponses-moteur.json"
ENV_REGENERER = "OPSYS_REGENERER_FIXTURES_MOBILE"
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT`
HORODATAGE = "2026-09-29T12:00:00-04:00"
ACTION = {"description": "Appeler le client (fictif)", "echeance": "2026-09-05T09:00:00-04:00"}
CONTACT_PARTAGE = {"nom": "Cliente Partagée (fictif)", "courriel": "partagee@exemple-fictif.test"}
CONTACT_B = {"nom": "Client B (fictif)", "courriel": "client-b@exemple-fictif.test"}
NOTE_SECRETE = "SECRET-DU-VENDEUR-B note privée (fictif)"
NOTE_A1 = "Premier appel : le client veut voir le devis (fictif)"


# -- ce que l'app lit dans son propre code ---------------------------------------------------------------------------
def _source(relatif: str) -> str:
    return (MOBILE_SRC / relatif).read_text(encoding="utf-8")


def _liste_ts(source: str, nom: str) -> list[str]:
    trouve = re.search(rf"export const {nom}: readonly string\[\] = \[(.*?)\];", source, re.DOTALL)
    assert trouve is not None, f"{nom} n'est plus dans l'app"
    return re.findall(r'"([^"]+)"', trouve.group(1))


def _outils_de_l_app() -> dict[str, str]:
    """Les sept outils que l'app appelle : `OUTIL_*` des contrats du vendeur, lus dans leur source."""
    outils: dict[str, str] = {}
    for relatif in ("m2/listeLeads.ts", "m2/client360.ts", "m2/interaction.ts", "m2/readiness.ts", "m3/devis.ts"):
        outils.update(re.findall(r'export const (OUTIL_[A-Z_0-9]+) = "([^"]+)"', _source(relatif)))
    return outils


# -- le scénario -----------------------------------------------------------------------------------------------------
def _m2(moteur: Moteur) -> dict[str, Any]:
    return {o.nom: o for o in moteur.departements["m02-revenue-crm"].charger_outils()}


def _m3(moteur: Moteur) -> dict[str, Any]:
    return {o.nom: o for o in moteur.departements["m03-estimation"].charger_outils()}


def _ok(reponse: dict[str, Any]) -> dict[str, Any]:
    """La donnée d'une écriture acceptée. `m2_ingerer_lead` rend son accusé à plat, les autres sous `resultat`."""
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"].get("resultat", reponse["resultat"])


def _ingerer(m2: dict[str, Any], lead_id: str, contact: dict[str, Any], ville: str = "Repentigny",
             urgence: bool = False) -> None:
    """Chaque lead a sa ville : deux leads de même ville et de mêmes travaux seraient signalés comme doublons
    probables (M2.12), ce que seuls `lead-a-1`, `lead-a-2` et `lead-b-1` (même client) doivent être ici."""
    contrat = {"lead_id": lead_id, "conversation_id": f"conv-{lead_id}", "contact": contact,
               "type_travaux": "renovation_totale", "ville": ville, "urgence_declaree": urgence,
               "canal": "telephone"}
    _ok(executer_atomique(m2["m2_ingerer_lead"], {"contrat": contrat, "horodatage": "2026-09-01T09:00:00-04:00"}))


def _qualifier(m2: dict[str, Any], lead_id: str, owner: str) -> None:
    _ok(executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": "2026-09-02T09:00:00-04:00", "owner": owner,
        "prochaine_action": ACTION}))


def _noter(m2: dict[str, Any], lead_id: str, auteur: str, resume: str, heure: str) -> None:
    _ok(executer_atomique(m2["m2_enregistrer_interaction"], {
        "lead_id": lead_id, "auteur": auteur, "resume": resume, "horodatage": heure}))


def _devis(m3: dict[str, Any], devis_id: str, lead_id: str) -> None:
    _ok(executer_atomique(m3["m3_creer_devis"], {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{"description": "Gouttière alu 5 po (fictif)", "quantite": "30", "unite": "pi_lin",
                    "cout_unitaire": "10.00", "reference_besoin_materiau": "besoin-goutt-001"}],
        "taux_marge": "0.20", "horodatage": "2026-09-01T09:05:00-04:00"}))


@pytest.fixture
def vente(moteur, equipe, monkeypatch):
    """Deux vendeurs appairés `seller`, leurs leads, les notes et les devis, préparés par la voie des agents (en
    production, M1 ingère par le bus et l'admin qualifie depuis son téléphone) ; l'admin et l'employé de `equipe`."""
    moteur.creer_personne("vendeur.a", "Vendeur A (fictif)", ["seller"], monkeypatch)
    moteur.creer_personne("vendeur.b", "Vendeur B (fictif)", ["seller"], monkeypatch)
    m2, m3 = _m2(moteur), _m3(moteur)
    _ingerer(m2, "lead-a-1", CONTACT_PARTAGE, urgence=True)
    _ingerer(m2, "lead-a-2", CONTACT_PARTAGE)
    _ingerer(m2, "lead-a-3", {"nom": "Client A3 (fictif)", "courriel": "a3@exemple-fictif.test"}, ville="Joliette")
    _ingerer(m2, "lead-a-4", {"nom": "Client A4 (fictif)", "courriel": "a4@exemple-fictif.test"}, ville="Terrebonne")
    _ingerer(m2, "lead-b-1", CONTACT_PARTAGE)
    _ingerer(m2, "lead-b-2", CONTACT_B, ville="Mascouche")
    _ingerer(m2, "lead-nouveau", {"nom": "Client N (fictif)", "courriel": "n@exemple-fictif.test"}, ville="Blainville")
    for lead_id, owner in (("lead-a-1", "vendeur.a"), ("lead-a-2", "vendeur.a"), ("lead-a-3", "vendeur.a"),
                           ("lead-a-4", "vendeur.a"), ("lead-b-1", "vendeur.b"), ("lead-b-2", "vendeur.b")):
        _qualifier(m2, lead_id, owner)
    _noter(m2, "lead-a-1", "vendeur.a", NOTE_A1, "2026-09-03T10:00:00-04:00")
    _noter(m2, "lead-a-4", "vendeur.a", "Visite faite, le client veut une soumission (fictif)",
           "2026-09-03T10:30:00-04:00")
    _noter(m2, "lead-b-1", "vendeur.b", NOTE_SECRETE, "2026-09-03T11:00:00-04:00")
    for lead_id, devis_id in (("lead-a-1", "devis-a-1"), ("lead-a-2", "devis-a-2"), ("lead-b-1", "devis-b-1")):
        _devis(m3, devis_id, lead_id)
    _ok(executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": "lead-a-2", "statut_cible": "converti", "horodatage": "2026-09-04T09:00:00-04:00",
        "reference_devis_m3": "devis-a-2"}))
    return {**equipe, "a": moteur.appairer("vendeur.a", "seller"), "b": moteur.appairer("vendeur.b", "seller")}


def _lire(porte: PorteAppareil, outil: str, args: dict[str, Any] | None = None) -> Reponse:
    """Un appel de lecture de l'écran : HTTP 200, jamais tronqué par le socle."""
    reponse = porte.appeler(outil, args or {})
    assert reponse.statut == 200, reponse.corps
    assert reponse.mesure.tronque is False and reponse.mesure.octets_texte < LIMITE_TRONCATURE, reponse.mesure
    return reponse


def _verdict(reponse: Reponse) -> dict[str, Any]:
    assert reponse.statut == 200 and reponse.metier["accepte"] is False, reponse.corps
    return reponse.metier["verdict"]


def _pages_de_leads(porte: PorteAppareil, **args: Any) -> list[dict[str, Any]]:
    """Comme l'écran : la page 0, puis `suivant` tant qu'il n'est pas nul."""
    pages = [_lire(porte, "m2_lister_leads", {"horodatage": HORODATAGE, **args}).resultat]
    while pages[-1]["suivant"] is not None:
        pages.append(_lire(porte, "m2_lister_leads",
                           {"horodatage": HORODATAGE, "decalage": pages[-1]["suivant"], **args}).resultat)
        assert len(pages) < 30, "la lecture ne progresse pas"
    return pages


def _ids(pages: list[dict[str, Any]]) -> list[str]:
    return [lead["lead_id"] for page in pages for lead in page["leads"]]


# ---------------------------------------------------------------------------------------------------------
# Ses leads seulement
# ---------------------------------------------------------------------------------------------------------
@SQLITE_SEULEMENT
def test_le_vendeur_a_ne_lit_que_ses_leads_et_b_que_les_siens(moteur, vente):
    a, b, admin = vente["a"], vente["b"], vente["admin"]

    pages_a = _pages_de_leads(a)
    assert _ids(pages_a) == ["lead-a-1", "lead-a-2", "lead-a-3", "lead-a-4"]
    assert {p["total"] for p in pages_a} == {4}  # jamais le total de l'entreprise
    assert _ids(_pages_de_leads(b)) == ["lead-b-1", "lead-b-2"]
    tous = _ids(_pages_de_leads(admin))
    assert sorted(tous) == ["lead-a-1", "lead-a-2", "lead-a-3", "lead-a-4", "lead-b-1", "lead-b-2", "lead-nouveau"]

    # Le corps brut de chaque réponse, pas seulement la liste : rien d'un autre vendeur, rien du lead sans propriétaire.
    brut = json.dumps([p for p in pages_a], ensure_ascii=False)
    for interdit in ("lead-b-1", "lead-b-2", "lead-nouveau", "vendeur.b", NOTE_SECRETE):
        assert interdit not in brut


@SQLITE_SEULEMENT
def test_le_filtre_par_segment_cite_le_devis_du_lead_converti_et_les_segments_sans_donnee_sont_dits_non_calculables(
        moteur, vente):
    a = vente["a"]
    pages = _pages_de_leads(a, segment="won_pending_schedule")
    assert _ids(pages) == ["lead-a-2"]
    segment = pages[0]["leads"][0]["segments"][0]
    assert segment["segment"] == "won_pending_schedule" and segment["regle"] == "soumission_acceptee_a_planifier"
    assert segment["donnee"]["reference_devis_m3"] == "devis-a-2"  # la seule source de numéro de devis de l'app
    assert "soumission est acceptée" in pages[0]["regles"]["soumission_acceptee_a_planifier"]
    assert _ids(_pages_de_leads(a, segment="hot_lead")) == ["lead-a-1"]

    # Un segment que M2 ne peut pas calculer : un refus avec ce qui manque, jamais une liste vide.
    for segment_refuse, mot in (("quote_stale", "seuil à configurer"), ("quote_sent", "m3.devis_envoye"),
                                ("needs_photos", "photos")):
        verdict = _verdict(a.appeler("m2_lister_leads", {"horodatage": HORODATAGE, "segment": segment_refuse}))
        assert verdict["code"] == "REJ-SEGMENT-NON-CALCULABLE"
        assert "non calculable, manque" in verdict["detail"] and mot in verdict["detail"]
    page = _pages_de_leads(a)[0]
    assert {n["segment"] for n in page["segments_non_calculables"]} >= {"needs_photos", "quote_sent", "quote_stale"}


@SQLITE_SEULEMENT
def test_l_employe_n_a_pas_la_portee_de_la_liste_des_leads(moteur, vente):
    refus = vente["employe"].appeler("m2_lister_leads", {"horodatage": HORODATAGE})
    assert refus.statut == 403 and "tool_out_of_scope" in refus.corps["error"]["message"]


# ---------------------------------------------------------------------------------------------------------
# La fiche du lead : suggestion citée, Client 360, historique
# ---------------------------------------------------------------------------------------------------------
@SQLITE_SEULEMENT
def test_la_fiche_du_lead_porte_la_regle_citee_le_client_360_de_ses_opportunites_et_ses_notes_seulement(moteur, vente):
    a = vente["a"]

    def suggerer(lead_id: str) -> dict[str, Any]:
        return _lire(a, "m2_suggerer_prochaine_action", {"lead_id": lead_id, "horodatage": HORODATAGE}).resultat

    prete = suggerer("lead-a-4")
    assert prete["lead_id"] == "lead-a-4" and prete["statut"] == "qualifie"
    assert prete["regle"] == "transmettre_m3"  # readiness satisfaite : une note a suivi la qualification
    assert prete["suggestion"] == "Transmettre le dossier à M3 pour estimation." and prete["motif"]
    assert suggerer("lead-a-3")["regle"] == "completer_readiness"  # la règle change avec les faits, citée à chaque fois
    # Le même contact chez deux vendeurs : un doublon probable est en attente d'arbitrage (geste de l'admin). La règle
    # est citée, et le texte ne nomme aucun lead de l'autre vendeur.
    doublon = suggerer("lead-a-1")
    assert doublon["regle"] == "doublon_en_attente" and doublon["suggestion"].startswith("Arbitrer le doublon")
    assert "lead-b" not in json.dumps(doublon) and "vendeur.b" not in json.dumps(doublon)

    lien = _lire(a, "m2_trouver_client_de_lead", {"lead_id": "lead-a-1"}).resultat
    assert lien["lead_id"] == "lead-a-1" and isinstance(lien["client_id"], str) and lien["client_id"]
    vue = _lire(a, "m2_obtenir_client_360", {"client_id": lien["client_id"]}).resultat

    assert vue["client_id"] == lien["client_id"] and vue["contact"] == CONTACT_PARTAGE
    assert [o["lead_id"] for o in vue["opportunites"]] == ["lead-a-1", "lead-a-2"]  # pas lead-b-1, du même client
    assert {i["lead_id"] for i in vue["interactions_recentes"]} == {"lead-a-1"}
    assert [(i["auteur"], i["resume"]) for i in vue["interactions_recentes"]] == [
        ("vendeur.a", NOTE_A1)]
    brut = json.dumps(vue, ensure_ascii=False)
    for interdit in ("lead-b-1", "vendeur.b", NOTE_SECRETE):
        assert interdit not in brut

    # L'admin, lui, voit les deux vendeurs du même client : la restriction vient bien de la portée du vendeur.
    vue_admin = _lire(vente["admin"], "m2_obtenir_client_360", {"client_id": lien["client_id"]}).resultat
    assert [o["lead_id"] for o in vue_admin["opportunites"]] == ["lead-a-1", "lead-a-2", "lead-b-1"]
    assert NOTE_SECRETE in json.dumps(vue_admin, ensure_ascii=False)


@SQLITE_SEULEMENT
def test_le_lead_d_un_autre_et_un_lead_inconnu_donnent_le_meme_refus_sans_rien_ecrire(moteur, vente):
    a = vente["a"]
    avant = moteur.empreinte_etat()
    client_de_b = _lire(vente["b"], "m2_trouver_client_de_lead", {"lead_id": "lead-b-2"}).resultat["client_id"]

    def refus(outil: str, args: dict[str, Any], lead: str) -> dict[str, Any]:
        verdict = _verdict(a.appeler(outil, args))
        assert verdict["code"] == "REJ-LEAD-NON-ASSIGNE", (outil, verdict)
        return {**verdict, "detail": verdict["detail"].replace(lead, "?")}

    for outil, extra in (("m2_suggerer_prochaine_action", {"horodatage": HORODATAGE}),
                         ("m2_trouver_client_de_lead", {})):
        d_un_autre = refus(outil, {"lead_id": "lead-b-1", **extra}, "lead-b-1")
        sans_proprietaire = refus(outil, {"lead_id": "lead-nouveau", **extra}, "lead-nouveau")
        inconnu = refus(outil, {"lead_id": "lead-fantome", **extra}, "lead-fantome")
        assert d_un_autre == sans_proprietaire == inconnu, outil

    # Le Client 360 d'un client dont AUCUNE opportunité n'est à A : le refus d'un client inconnu.
    sans_lead_a = _verdict(a.appeler("m2_obtenir_client_360", {"client_id": client_de_b}))
    inconnu = _verdict(a.appeler("m2_obtenir_client_360", {"client_id": "m2-client-v1:inconnu"}))
    assert sans_lead_a["code"] == inconnu["code"] == "REJ-LEAD-NON-ASSIGNE"
    assert sans_lead_a["detail"] == inconnu["detail"]
    assert moteur.empreinte_etat() == avant, "un refus de lecture n'écrit rien"


# ---------------------------------------------------------------------------------------------------------
# 403 sur les outils de l'admin ; le nom nu
# ---------------------------------------------------------------------------------------------------------
ADMIN_SEUL = (
    ("m2_produire_digest", {"date_jour": "2026-09-29", "horodatage": HORODATAGE}),
    ("m2_detecter_doublons", {"lead_id": "lead-a-1"}),
    ("m2_arbitrer_doublon", {"signalement_id": "s", "decision": "distincts", "horodatage": HORODATAGE}),
    ("m9_lister_demandes_approbation", {}),
    ("m9_decider_demande_approbation", {"demande_id": "d", "decision": "approuver"}),
    ("m5_etat_tresorerie", {}),
    ("m5_lire_rentabilite_chantier", {"chantier_id": "c"}),
    ("m4_lister_pending_review", {}),
    ("m6_approuver_po", {"po_id": "p"}),
    ("m3_creer_devis", {}),
    ("m3_marquer_devis_accepte", {"devis_id": "devis-a-1", "approbateur": "vendeur.a", "horodatage": HORODATAGE}),
    ("m3_lire_ecarts_estime_reel", {}),
    ("opsys_memoire_chercher", {}),
    ("outil_qui_n_existe_pas", {}),
)


@SQLITE_SEULEMENT
def test_403_sur_les_outils_de_l_admin_et_sur_tout_nom_qui_n_est_pas_nu(moteur, vente):
    a = vente["a"]
    avant = moteur.empreinte_etat()
    for outil, args in ADMIN_SEUL:
        refus = a.appeler(outil, args)
        assert refus.statut == 403, outil
        assert refus.corps["ok"] is False and refus.corps["error"]["type"] == "tool_call_blocked", outil
        message = refus.corps["error"]["message"]
        assert "tool_out_of_scope" in message or "server_unknown" in message
    # La règle est le nom NU (`opsys/roles.json`) : un outil permis, nommé avec son serveur, est refusé.
    for prefixe in ("m02-revenue-crm.", "m02-revenue-crm__", "mcp__m02-revenue-crm__", "M2_LISTER_LEADS"):
        refus = a.appeler(f"{prefixe}m2_lister_leads" if prefixe != "M2_LISTER_LEADS" else prefixe,
                          {"horodatage": HORODATAGE})
        assert refus.statut == 403, prefixe
    assert moteur.empreinte_etat() == avant, "un refus de la porte n'écrit rien"
    # L'admin, lui, passe la porte pour ses outils.
    assert vente["admin"].appeler("m9_lister_demandes_approbation", {}).statut == 200


# ---------------------------------------------------------------------------------------------------------
# La note : rejeu sans double effet
# ---------------------------------------------------------------------------------------------------------
def _note(moteur: Moteur, porte: PorteAppareil, lead_id: str, resume: str, cle: str, **en_plus: Any) -> Reponse:
    return porte.appeler(
        "m2_enregistrer_interaction", {"lead_id": lead_id, "resume": resume, "horodatage": HORODATAGE, **en_plus},
        cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant))


def _interactions(porte: PorteAppareil, lead_id: str) -> list[dict[str, Any]]:
    client = _lire(porte, "m2_trouver_client_de_lead", {"lead_id": lead_id}).resultat["client_id"]
    vue = _lire(porte, "m2_obtenir_client_360", {"client_id": client}).resultat
    return [i for i in vue["interactions_recentes"] if i["lead_id"] == lead_id]


@SQLITE_SEULEMENT
def test_une_note_rejouee_avec_sa_cle_n_est_ecrite_qu_une_fois(moteur, vente):
    a = vente["a"]
    resume = "Rappel fait : visite prévue jeudi (fictif)"

    premiere = _note(moteur, a, "lead-a-3", resume, "e2e-note-a3-1")
    assert premiere.enveloppe["rejoue"] is False and premiere.resultat["lead_id"] == "lead-a-3"
    apres_la_premiere = moteur.empreinte_etat()
    assert [(i["auteur"], i["resume"]) for i in _interactions(a, "lead-a-3")] == [("vendeur.a", resume)]

    # La réponse s'est perdue en chemin : l'app renvoie la MÊME clé avec le MÊME payload.
    rejeu = _note(moteur, a, "lead-a-3", resume, "e2e-note-a3-1")
    assert rejeu.enveloppe["rejoue"] is True and rejeu.mesure.rejoue is True
    assert rejeu.resultat == premiere.resultat  # l'accusé enregistré, tel quel
    assert moteur.empreinte_etat() == apres_la_premiere  # ni maillon, ni événement, ni approbation, ni journal en plus
    assert len(_interactions(a, "lead-a-3")) == 1

    # Même clé, autre contenu : un conflit, rien n'est écrit ni modifié.
    conflit = _note(moteur, a, "lead-a-3", "Autre contenu", "e2e-note-a3-1")
    assert conflit.enveloppe["ok"] is False and conflit.enveloppe["erreur"] == "mutation_conflit"
    assert moteur.empreinte_etat() == apres_la_premiere

    # Une autre clé est une autre note.
    seconde = _note(moteur, a, "lead-a-3", "Deuxième note (fictif)", "e2e-note-a3-2")
    assert seconde.enveloppe["rejoue"] is False
    assert [i["resume"] for i in _interactions(a, "lead-a-3")] == [resume, "Deuxième note (fictif)"]


@SQLITE_SEULEMENT
def test_la_note_est_toujours_sous_le_nom_du_vendeur_et_seulement_sur_ses_leads(moteur, vente):
    a = vente["a"]
    avant = moteur.empreinte_etat()

    autre_auteur = _note(moteur, a, "lead-a-1", "Note au nom d'un autre", "e2e-note-auteur", auteur="vendeur.b")
    assert _verdict(autre_auteur)["code"] == "REJ-IDENTITE-FOURNIE-DIFFERENTE"
    sur_le_lead_d_un_autre = _note(moteur, a, "lead-b-1", "Note chez un autre vendeur", "e2e-note-lead-b")
    assert _verdict(sur_le_lead_d_un_autre)["code"] == "REJ-LEAD-NON-ASSIGNE"
    sur_un_lead_inconnu = _note(moteur, a, "lead-fantome", "Note nulle part", "e2e-note-fantome")
    assert _verdict(sur_un_lead_inconnu)["code"] == "REJ-LEAD-NON-ASSIGNE"
    assert moteur.empreinte_etat().get("registres") == avant.get("registres"), "aucun de ces refus n'écrit un maillon"

    # L'app n'envoie pas `auteur` : le serveur y met la personne authentifiée.
    accepte = _note(moteur, a, "lead-a-1", "Note sous mon nom (fictif)", "e2e-note-nom")
    assert accepte.resultat["lead_id"] == "lead-a-1"
    assert _interactions(a, "lead-a-1")[-1] == {
        "lead_id": "lead-a-1", "auteur": "vendeur.a", "resume": "Note sous mon nom (fictif)", "horodatage": HORODATAGE}
    assert NOTE_SECRETE not in json.dumps(_interactions(a, "lead-a-1"), ensure_ascii=False)


@SQLITE_SEULEMENT
def test_la_borne_des_notes_de_l_app_tient_dix_notes_dans_la_reponse_du_client_360(moteur, vente):
    """`RESUME_LONGUEUR_MAX` est lue dans l'app. Le Client 360 rend les dix dernières interactions dans UNE réponse
    que le socle tronque au-delà de 6 000 caractères : dix notes de la longueur maximale doivent passer."""
    a = vente["a"]
    trouve = re.search(r"export const RESUME_LONGUEUR_MAX = (\d+);", _source("m2/interaction.ts"))
    assert trouve is not None, "la borne n'est plus dans l'app"
    borne = int(trouve.group(1))
    assert _m2(moteur)["m2_enregistrer_interaction"].parametres["properties"]["resume"]["maxLength"] == borne
    for i in range(12):
        texte = f"{i:02d}" + "é" * (borne - 2)  # la longueur maximale, en caractères accentués
        assert len(texte) == borne
        assert _note(moteur, a, "lead-a-1", texte, f"e2e-note-longue-{i:02d}").statut == 200
    client = _lire(a, "m2_trouver_client_de_lead", {"lead_id": "lead-a-1"}).resultat["client_id"]
    reponse = a.appeler("m2_obtenir_client_360", {"client_id": client})
    assert reponse.statut == 200 and reponse.mesure.tronque is False, reponse.mesure
    assert reponse.mesure.octets_texte < LIMITE_TRONCATURE
    assert len(reponse.resultat["interactions_recentes"]) == 10
    print("MESURE-CLIENT-360 " + json.dumps({"borne": borne, "notes": 10, "octets": reponse.mesure.octets_texte}))


@SQLITE_SEULEMENT
def test_borne_note_serveur_refus_puis_rejeu_et_conflit_sans_effet_supplementaire(moteur, vente):
    a = vente["a"]
    avant = moteur.empreinte_etat()
    refusee = _note(moteur, a, "lead-a-3", "é" * 301, "e2e-note-hors-borne")
    assert refusee.enveloppe["ok"] is True and refusee.metier["accepte"] is False
    assert refusee.metier["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
    apres_refus = moteur.empreinte_etat()
    assert apres_refus == {**avant, "journal": avant["journal"] + 1,
        "mutations": avant["mutations"] + 1, "approbations": avant["approbations"] + 1}
    assert _interactions(a, "lead-a-3") == []
    rejeu_refus = _note(moteur, a, "lead-a-3", "é" * 301, "e2e-note-hors-borne")
    assert rejeu_refus.enveloppe["rejoue"] is True and rejeu_refus.metier == refusee.metier
    assert moteur.empreinte_etat() == apres_refus

    # Une intention admise reste immuable, y compris quand le métier la refuse.
    texte = "é" * 300
    changement = _note(moteur, a, "lead-a-3", texte, "e2e-note-hors-borne")
    assert changement.enveloppe["erreur"] == "mutation_conflit"
    assert moteur.empreinte_etat() == apres_refus
    premiere = _note(moteur, a, "lead-a-3", texte, "e2e-note-corrigee")
    assert premiere.statut == 200 and premiere.enveloppe["rejoue"] is False
    apres = moteur.empreinte_etat()
    rejeu = _note(moteur, a, "lead-a-3", texte, "e2e-note-corrigee")
    assert rejeu.enveloppe["rejoue"] is True and rejeu.resultat == premiere.resultat
    assert moteur.empreinte_etat() == apres
    conflit = _note(moteur, a, "lead-a-3", "autre contenu", "e2e-note-corrigee")
    assert conflit.enveloppe["erreur"] == "mutation_conflit"
    assert moteur.empreinte_etat() == apres
    assert [i["resume"] for i in _interactions(a, "lead-a-3")] == [texte]


# ---------------------------------------------------------------------------------------------------------
# Les devis
# ---------------------------------------------------------------------------------------------------------
@SQLITE_SEULEMENT
def test_le_vendeur_lit_le_devis_de_son_lead_et_celui_d_un_autre_donne_le_refus_d_un_devis_inconnu(moteur, vente):
    a = vente["a"]
    avant = moteur.empreinte_etat()

    devis = _lire(a, "m3_lire_devis", {"devis_id": "devis-a-2"}).resultat
    assert devis["devis_id"] == "devis-a-2" and devis["lead_id"] == "lead-a-2"
    assert devis["statut"] == "brouillon" and devis["prix_total"] == "360.00"
    assert devis["lignes"][0]["prix_ligne"] == "360.00" and devis["lignes"][0]["prix_unitaire"] == "12.00"

    d_un_autre = _verdict(a.appeler("m3_lire_devis", {"devis_id": "devis-b-1"}))
    inconnu = _verdict(a.appeler("m3_lire_devis", {"devis_id": "devis-fantome"}))
    assert d_un_autre["code"] == inconnu["code"] == "REJ-DEVIS-INTROUVABLE"
    assert d_un_autre["detail"].replace("devis-b-1", "?") == inconnu["detail"].replace("devis-fantome", "?")
    assert moteur.empreinte_etat() == avant, "lire un devis n'écrit rien"
    assert _lire(vente["admin"], "m3_lire_devis", {"devis_id": "devis-b-1"}).resultat["lead_id"] == "lead-b-1"


@SQLITE_SEULEMENT
def test_le_serveur_rend_au_vendeur_la_vue_interne_avec_cout_et_marge_donc_l_app_la_reduit_a_sa_liste_blanche(
        moteur, vente):
    """CARACTÉRISATION, pas un souhait : M3 n'a que deux vues (`interne`, `employe`) et rend `interne` à un appareil
    `seller` (`_VUE_PAR_ROLE_APPAREIL`). La vue « employe » retire aussi le PRIX, que le vendeur doit voir. L'app
    (`mobile/src/m3/devis.ts`) ne garde donc que statut, prix et lignes décrites. Si M3 livre un jour une vue
    « prix sans coût ni marge » (GATE NATHAN), ce test change — et l'app peut la demander."""
    a = vente["a"]
    interne = _lire(a, "m3_lire_devis", {"devis_id": "devis-a-1"}).resultat
    assert interne["cout_total"] == "300.00" and interne["taux_marge"] == "0.20"
    assert interne["lignes"][0]["cout_unitaire"] == "10.00" and interne["lignes"][0]["cout_ligne"] == "300.00"

    employe = _lire(a, "m3_lire_devis", {"devis_id": "devis-a-1", "role": "employe"}).resultat
    assert "prix_total" not in employe and "cout_total" not in employe and "taux_marge" not in employe
    assert set(employe["lignes"][0]) == {
        "reference_ligne", "description", "quantite", "unite", "reference_besoin_materiau"}

    # L'app ne demande ni `role` ni rien d'autre que `devis_id` : ce que ses contrats lisent est dans la vue interne.
    source = _source("m3/devis.ts")
    assert "construireArgumentsLireDevis" in source and "{ devis_id: devisId }" in source
    lu_par_l_app = {"devis_id", "lead_id", "chantier_id", "statut", "horodatage", "lignes", "prix_total"}
    assert lu_par_l_app <= set(interne)
    assert {"reference_ligne", "description", "quantite", "unite", "prix_unitaire", "prix_ligne"} <= set(
        interne["lignes"][0])
    for nom in re.findall(r"(?<![\w.])(?:brut|valeur)\.(\w+)", source):
        assert nom in set(interne) | set(interne["lignes"][0]), f"l'app lit `{nom}`, que le serveur ne rend pas"
    page = _lire(a, "m3_lister_devis", {"limite": 10}).resultat
    assert set(page) == {"devis", "curseur_suivant"}
    assert page["devis"] and len(page["devis"]) <= 10
    assert all(devis["lead_id"].startswith("lead-a-") for devis in page["devis"])


# ---------------------------------------------------------------------------------------------------------
# L'app et le serveur parlent la même langue
# ---------------------------------------------------------------------------------------------------------
def test_les_catalogues_et_les_noms_d_outils_de_l_app_sont_ceux_du_serveur():
    assert _liste_ts(_source("m2/listeLeads.ts"), "STATUTS_LEAD") == list(statuts_m2.STATUTS)
    assert _liste_ts(_source("m2/listeLeads.ts"), "SEGMENTS_LEAD") == list(segments_m2.SEGMENTS)
    assert _liste_ts(_source("m3/devis.ts"), "STATUTS_DEVIS") == list(devis_durable.STATUTS_DEVIS)

    outils = _outils_de_l_app()
    assert set(outils.values()) == {
        "m2_lister_leads", "m2_obtenir_client_360", "m2_trouver_client_de_lead", "m2_suggerer_prochaine_action",
        "m2_enregistrer_interaction", "m2_evaluer_readiness", "m3_lire_devis", "m3_lister_devis"}
    portee_vendeur = set(openclaw.roles_outils(charger_departements())["seller"])
    assert set(outils.values()) <= portee_vendeur, "l'app appelle un outil hors de la portée du vendeur"
    assert not any(outil.startswith(("mcp", "m0", "m1")) or "." in outil for outil in outils.values())

    descripteurs = _source("outbox/descripteurs.ts")
    assert '["lead_note", { tool: "m2_enregistrer_interaction"' in descripteurs

    # Le refus d'un segment non calculable est reconnu par son code : celui du serveur.
    assert 'CODE_SEGMENT_NON_CALCULABLE = "REJ-SEGMENT-NON-CALCULABLE"' in _source("m2/listeLeads.ts")
    assert segments_m2.CHEMIN_SEUILS == "configuration.segments"

    # PLAN T1.4-n : le verdict d'identité (personne désactivée, rôle retiré) est reconnu par son code, celui des
    # départements, et les pannes passagères du socle (jamais un refus) sont celles du serveur.
    assert 'CODE_IDENTITE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"' in _source("protocole/enveloppeOutil.ts")
    assert "REJ-IDENTITE-APPAREIL-INVALIDE" in verdicts_m2.CODES_M2
    passageres = set(_liste_ts(_source("protocole/enveloppeOutil.ts"), "ERREURS_PASSAGERES"))
    assert passageres == set(idempotence.ERREURS_PASSAGERES)


def _forme(valeur: Any) -> Any:
    """La FORME d'une réponse : ses clés et le type de chaque valeur, jamais les valeurs elles-mêmes (une liste est
    décrite par son premier élément). C'est ce que les lecteurs de l'app exigent, et ce qui change quand le serveur
    change de contrat."""
    if isinstance(valeur, dict):
        return {cle: _forme(v) for cle, v in sorted(valeur.items())}
    if isinstance(valeur, list):
        return [_forme(valeur[0])] if valeur else []
    if valeur is None:
        return "null"
    return type(valeur).__name__


def _reponses_du_scenario(moteur: Moteur, vente: dict[str, PorteAppareil]) -> dict[str, Any]:
    """Les enveloppes que l'app reçoit (`corps.result`) pour chaque geste des trois écrans, y compris les refus : ce
    que `mobile/src/vendeur/fixtures/reponses-moteur.json` garde et que les tests Jest lisent."""
    a = vente["a"]
    reponses: dict[str, Any] = {}

    def garder(nom: str, reponse: Reponse) -> Reponse:
        assert reponse.statut == 200, (nom, reponse.corps)
        reponses[nom] = reponse.enveloppe
        return reponse

    garder("page_des_leads", a.appeler("m2_lister_leads", {"horodatage": HORODATAGE}))
    garder("page_du_segment_converti",
           a.appeler("m2_lister_leads", {"horodatage": HORODATAGE, "segment": "won_pending_schedule"}))
    garder("refus_segment_non_calculable",
           a.appeler("m2_lister_leads", {"horodatage": HORODATAGE, "segment": "quote_sent"}))
    garder("arguments_invalides",
           a.appeler("m2_lister_leads", {"horodatage": HORODATAGE, "owner": "vendeur.b"}))
    garder("suggestion_doublon",
           a.appeler("m2_suggerer_prochaine_action", {"lead_id": "lead-a-1", "horodatage": HORODATAGE}))
    garder("suggestion_prete",
           a.appeler("m2_suggerer_prochaine_action", {"lead_id": "lead-a-4", "horodatage": HORODATAGE}))
    garder("refus_lead_d_un_autre",
           a.appeler("m2_suggerer_prochaine_action", {"lead_id": "lead-b-1", "horodatage": HORODATAGE}))
    lien = garder("client_du_lead", a.appeler("m2_trouver_client_de_lead", {"lead_id": "lead-a-1"}))
    garder("client_360", a.appeler("m2_obtenir_client_360", {"client_id": lien.resultat["client_id"]}))
    garder("devis_interne", a.appeler("m3_lire_devis", {"devis_id": "devis-a-2"}))
    garder("refus_devis_d_un_autre", a.appeler("m3_lire_devis", {"devis_id": "devis-b-1"}))
    garder("note_enregistree", _note(moteur, a, "lead-a-3", "Rappel fait (fictif)", "e2e-fixture-note"))
    garder("note_rejouee", _note(moteur, a, "lead-a-3", "Rappel fait (fictif)", "e2e-fixture-note"))
    garder("note_conflit", _note(moteur, a, "lead-a-3", "Autre contenu", "e2e-fixture-note"))
    garder("note_refusee", _note(moteur, a, "lead-b-1", "Note chez un autre vendeur", "e2e-fixture-refus"))

    # PLAN T1.4-n : l'admin désactive le vendeur A. Son jeton reste valide pour la porte du core (`appareils.json`),
    # mais chaque outil revérifie l'identité en base : la personne est refusée. C'est ce que l'app doit lire comme un
    # REFUS (jamais un cache), sur les cinq lectures des écrans.
    assert cli.main(["personnes", "desactiver", "vendeur.a"]) == 0
    garder("refus_identite_page_des_leads", a.appeler("m2_lister_leads", {"horodatage": HORODATAGE}))
    garder("refus_identite_suggestion",
           a.appeler("m2_suggerer_prochaine_action", {"lead_id": "lead-a-1", "horodatage": HORODATAGE}))
    garder("refus_identite_client_du_lead", a.appeler("m2_trouver_client_de_lead", {"lead_id": "lead-a-1"}))
    garder("refus_identite_client_360", a.appeler("m2_obtenir_client_360", {"client_id": lien.resultat["client_id"]}))
    garder("refus_identite_devis", a.appeler("m3_lire_devis", {"devis_id": "devis-a-2"}))
    return reponses


@SQLITE_SEULEMENT
def test_les_reponses_du_moteur_ont_la_forme_de_la_fixture_que_l_app_lit(moteur, vente):
    """Le pont entre les deux langages : `mobile/src/vendeur/fixtures/reponses-moteur.json` (lue par les tests Jest, qui
    la font passer par les lecteurs de l'app) est la forme EXACTE de ce que le moteur rend aujourd'hui. Si le serveur
    change une clé ou un type, ce test échoue ; on relit alors les lecteurs de l'app, puis on régénère la fixture
    (`OPSYS_REGENERER_FIXTURES_MOBILE=1 pytest tests/e2e/test_vendeur_appareil.py -k fixture`)."""
    reponses = _reponses_du_scenario(moteur, vente)
    if os.environ.get(ENV_REGENERER) == "1":
        FIXTURE_APP.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_APP.write_text(
            json.dumps({"fictif": True, "reponses": reponses}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    fixture = json.loads(FIXTURE_APP.read_text(encoding="utf-8"))
    assert fixture["fictif"] is True
    assert set(fixture["reponses"]) == set(reponses)
    for nom, vivante in reponses.items():
        assert _forme(vivante) == _forme(fixture["reponses"][nom]), f"{nom} : la forme du moteur a changé"
    assert len(reponses) == 20


@SQLITE_SEULEMENT
def test_les_cles_que_l_app_lit_sont_celles_que_le_serveur_rend(moteur, vente):
    """Miroir de `mobile/src/m2/listeLeads.ts`, `client360.ts`, `interaction.ts` et `m3/devis.ts` : chaque clé que
    leurs lecteurs exigent est dans la vraie réponse du moteur, avec son type."""
    a = vente["a"]
    page = _pages_de_leads(a, segment="won_pending_schedule")[0]
    assert {"total", "decalage", "affichees", "reste", "suivant", "indetermines", "filtre", "leads", "regles",
            "segments_non_calculables"} <= set(page)
    assert page["filtre"] == {"statut": None, "segment": "won_pending_schedule"}
    assert isinstance(page["total"], int) and isinstance(page["regles"], dict)
    lead = page["leads"][0]
    assert set(lead) <= {"lead_id", "statut", "proprietaire", "travaux", "ville", "urgence_declaree", "ingere_le",
                         "derniere_activite", "prochaine_action", "segments", "non_calculables"}
    assert {"lead_id", "ingere_le", "segments", "prochaine_action", "urgence_declaree"} <= set(lead)
    assert set(lead["prochaine_action"]) == {"description", "echeance"}
    assert set(lead["segments"][0]) == {"segment", "regle", "donnee"}
    assert all(set(n) == {"segment", "manque"} for n in page["segments_non_calculables"])

    suggestion = _lire(a, "m2_suggerer_prochaine_action", {"lead_id": "lead-a-1", "horodatage": HORODATAGE}).resultat
    assert set(suggestion) == {"lead_id", "statut", "regle", "suggestion", "motif"}
    lien = _lire(a, "m2_trouver_client_de_lead", {"lead_id": "lead-a-1"}).resultat
    assert set(lien) == {"lead_id", "client_id"}
    vue = _lire(a, "m2_obtenir_client_360", {"client_id": lien["client_id"]}).resultat
    assert set(vue) == {"client_id", "contact", "opportunites", "interactions_recentes"}
    assert {"lead_id", "statut", "ville", "type_travaux", "service", "canal", "source", "campagne",
            "prochaine_action"} <= set(vue["opportunites"][0])
    assert set(vue["interactions_recentes"][0]) == {"lead_id", "auteur", "resume", "horodatage"}

    accuse = _note(moteur, a, "lead-a-1", "Accusé (fictif)", "e2e-cles-accuse").resultat
    assert {"lead_id", "ligne_id", "horodatage"} <= set(accuse)
    devis = _lire(a, "m3_lire_devis", {"devis_id": "devis-a-1"}).resultat
    assert isinstance(devis["prix_total"], str) and isinstance(devis["lignes"][0]["quantite"], str)  # décimaux en texte
