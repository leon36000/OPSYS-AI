"""PLAN T1.4-n (constats 1 et 2, profil employé) — « chantiers du jour » de l'employé lit SES interventions par la vraie
porte d'appareil (E2E moteur).

DEFINITION-PRODUIT §9.6 : l'employé voit son chantier du jour. `mobile/app/(employee)/today.tsx` appelle
`m4_lister_interventions` ; `job/[id]/index.tsx` appelle `m4_statut_intervention`. `m4_lister_interventions` n'a AUCUNE
pagination, et le socle (`Capacites._tronquer`) COUPE toute réponse de plus de 6 000 caractères : `{ok, tronque: true,
apercu}`, sans `resultat`. L'app lisait cette forme comme une liste vide et écrivait le cache vide par-dessus la vraie
liste (le constat 2 de T4.20). Elle lit maintenant un statut à la fois (les quatre états actifs) et dit « incomplète »
quand le socle a coupé un groupe.

Le scénario, sur le vrai moteur (des dates et des identifiants fictifs) : Étienne (employé) a 27 chantiers de lead v1 ;
26 sont `planifiee`, le dernier est `en_route` (consentement GPS donné, départ). Un autre employé, Luc, est désactivé.

Ce que ces tests prouvent :
- la liste des 26 chantiers planifiés de l'employé est COUPÉE par le socle : la réponse a exactement la forme
  `{ok, tronque, apercu}` et n'a pas de `resultat` ; la même requête sans statut (l'ancien appel de l'app) l'est aussi ;
- chaque autre groupe (`en_route`, `sur_site`, `en_revue`) tient sous la borne : un appel par statut donne à l'app des
  listes entières, dont la seule vraie (le chantier en route) ;
- un employé désactivé reçoit un REFUS de la porte, pas une panne : `refus_metier` avec le verdict d'identité, pour
  les deux outils de l'écran ; c'est ce que l'app lit comme un refus, jamais remplacé par le cache ;
- la FORME de chaque réponse est celle de `mobile/src/today/fixtures/reponses-moteur.json`, que les tests Jest font
  passer par l'orchestrateur de l'app (un appel par statut, le cache, les cinq issues) ;
- l'app et le serveur parlent la même langue : les statuts d'intervention que l'app connaît sont ceux de M4
  (`etats.ETATS`, `a_planifier` compris), et les deux outils de l'écran sont dans la portée `employee`.
Ce que ces tests ne prouvent PAS : les écrans (Jest, `mobile/`) ni le core.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from harnais_e2e import Moteur, PorteAppareil, Reponse
from harnais_e2e_chantier import AppEmploye, Chantier, debut_de_journee, preparer_chantier
from m4_field_ops import etats as etats_m4

from opsys import cli, openclaw
from opsys.departements import charger_departements

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
RACINE = Path(__file__).resolve().parents[2]
MOBILE_SRC = RACINE / "mobile" / "src"
FIXTURE_APP = MOBILE_SRC / "today" / "fixtures" / "reponses-moteur.json"
ENV_REGENERER = "OPSYS_REGENERER_FIXTURES_MOBILE"
_CHEMIN_DE_TEST = re.compile(r"/tmp/pytest-of-[^/]+/pytest-\d+/[^/]+/opsys-home")
NOMBRE_PLANIFIES = 26  # 26 interventions de lead v1 pèsent plus de 6 000 caractères dans `m4_lister_interventions`


# -- ce que l'app lit dans son propre code ---------------------------------------------------------------------------
def _source(relatif: str) -> str:
    return (MOBILE_SRC / relatif).read_text(encoding="utf-8")


def _liste_ts(source: str, nom: str) -> list[str]:
    """Les chaînes d'une constante `export const NOM: readonly <Type>[] = [...]` de l'app."""
    trouve = re.search(rf"export const {nom}: readonly \w+\[\] = \[(.*?)\];", source, re.DOTALL)
    assert trouve is not None, f"{nom} n'est plus dans l'app"
    return re.findall(r'"([^"]+)"', trouve.group(1))


def _normaliser(valeur: Any) -> Any:
    """Le chemin d'un fichier du serveur de test change à chaque exécution : la fixture garde un chemin stable."""
    if isinstance(valeur, dict):
        return {cle: _normaliser(v) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_normaliser(v) for v in valeur]
    if isinstance(valeur, str):
        return _CHEMIN_DE_TEST.sub("/srv/opsys", valeur)
    return valeur


def _forme(valeur: Any) -> Any:
    """La FORME d'une réponse : ses clés et le type de chaque valeur, jamais les valeurs elles-mêmes."""
    if isinstance(valeur, dict):
        return {cle: _forme(v) for cle, v in sorted(valeur.items())}
    if isinstance(valeur, list):
        return [_forme(valeur[0])] if valeur else []
    if valeur is None:
        return "null"
    return type(valeur).__name__


# -- l'enregistreur : ce que l'app envoie et ce que le moteur répond ---------------------------------------------------
class Enregistreur:
    """Chaque lecture de l'écran : l'appel (outil et arguments exacts) et l'enveloppe que l'app reçoit (`corps.result`),
    c'est-à-dire ce que `reponses-moteur.json` garde et que les tests Jest lisent."""

    def __init__(self, moteur: Moteur) -> None:
        self.moteur = moteur
        self.appels: dict[str, dict[str, Any]] = {}
        self.reponses: dict[str, Any] = {}

    def lire(self, nom: str, porte: PorteAppareil, outil: str, args: dict[str, Any]) -> Reponse:
        """Une lecture : HTTP 200, et RIEN d'écrit dans le moteur. La troncature est constatée, jamais supposée."""
        avant = self.moteur.empreinte_etat()
        reponse = porte.appeler(outil, dict(args))
        assert reponse.statut == 200, (nom, reponse.corps)
        assert self.moteur.empreinte_etat() == avant, f"{nom} : lire n'écrit rien"
        assert nom not in self.reponses, nom
        self.appels[nom] = {"outil": outil, "args": dict(args)}
        self.reponses[nom] = _normaliser(reponse.enveloppe)
        return reponse


def _planifier(moteur: Moteur) -> list[Chantier]:
    """27 chantiers de lead v1 pour Étienne, un par jour (l'un après l'autre, comme le fait le bureau)."""
    return [
        preparer_chantier(moteur.departements, suffixe=f"EMP-{numero:02d}", technicien="etienne",
                          debut=debut_de_journee(numero), version_lead=1)
        for numero in range(1, NOMBRE_PLANIFIES + 2)
    ]


def _enregistrer_la_liste_de_l_employe(moteur: Moteur, equipe: dict[str, Any], monkeypatch: Any) -> Enregistreur:
    employe = equipe["employe"]
    enr = Enregistreur(moteur)
    chantiers = _planifier(moteur)

    # Le dernier chantier part en route : consentement GPS, puis départ (les gestes de l'app, par la porte).
    en_route = chantiers[-1]
    moteur.horloge.maintenant = en_route.debut
    app = AppEmploye(moteur, employe, en_route)
    app.attendre(minutes=1)
    assert app.donner_consentement_gps().metier["accepte"] is True
    app.attendre(minutes=29)
    assert app.en_route().metier["accepte"] is True

    # ---- 1. ce que l'app demande : un appel par statut actif ------------------------------------------------------
    planifiees = enr.lire("interventions_planifiee_tronquee", employe, "m4_lister_interventions",
                          {"statut": "planifiee"})
    assert planifiees.mesure.tronque is True, "26 chantiers planifiés dépassent la borne de sortie du socle"
    enveloppe = planifiees.enveloppe
    assert set(enveloppe) == {"ok", "tronque", "apercu"}, "la forme d'une sortie coupée par le socle"
    assert enveloppe["ok"] is True and enveloppe["tronque"] is True
    assert "resultat" not in enveloppe, "une liste coupée n'a pas de `resultat` : jamais « aucune intervention »"
    assert enveloppe["apercu"].startswith('{"ok": true, "resultat": [{"intervention_id": "')
    assert "caractères omis" in enveloppe["apercu"]

    en_cours = enr.lire("interventions_en_route", employe, "m4_lister_interventions", {"statut": "en_route"})
    assert en_cours.mesure.tronque is False
    assert [i["intervention_id"] for i in en_cours.resultat] == [en_route.intervention_id]
    assert en_cours.resultat[0]["statut"] == "en_route" and en_cours.resultat[0]["technicien_assigne"] == "etienne"
    for statut in ("sur_site", "en_revue"):
        vide = enr.lire(f"interventions_{statut}", employe, "m4_lister_interventions", {"statut": statut})
        assert vide.mesure.tronque is False and vide.resultat == [], statut

    # ---- 2. l'ancien appel de l'app : sans statut, tout l'historique d'un coup ---------------------------------------
    sans_filtre = enr.lire("interventions_sans_filtre_tronquee", employe, "m4_lister_interventions", {})
    assert sans_filtre.mesure.tronque is True
    assert set(sans_filtre.enveloppe) == {"ok", "tronque", "apercu"}

    # ---- 3. le statut d'UN chantier (l'écran du chantier) ------------------------------------------------------------
    statut = enr.lire("statut_intervention", employe, "m4_statut_intervention",
                      {"intervention_id": en_route.intervention_id})
    assert statut.resultat == {"intervention_id": en_route.intervention_id, "statut": "en_route"}

    # ---- 4. un employé désactivé : un REFUS de la porte, pas une panne -----------------------------------------------
    moteur.creer_personne("luc", "Luc Tremblay (fictif)", ["employee"], monkeypatch)
    luc = moteur.appairer("luc", "employee")
    assert cli.main(["personnes", "desactiver", "luc"]) == 0
    for nom, outil, args in (
        ("refus_identite_interventions", "m4_lister_interventions", {"statut": "planifiee"}),
        ("refus_identite_statut", "m4_statut_intervention", {"intervention_id": chantiers[0].intervention_id}),
    ):
        refus = enr.lire(nom, luc, outil, args)
        assert refus.enveloppe["ok"] is False and refus.enveloppe["erreur"] == "refus_metier", (nom, refus.enveloppe)
        assert refus.enveloppe["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE"), (nom, refus.enveloppe)
    return enr


@SQLITE_SEULEMENT
def test_la_liste_de_l_employe_est_coupee_par_le_socle_et_la_fixture_est_la_forme_du_moteur(
        moteur, equipe, monkeypatch):
    """Le pont entre les deux langages : `mobile/src/today/fixtures/reponses-moteur.json` (lue par les tests Jest, qui
    la font passer par l'orchestrateur de l'app) est la forme EXACTE de ce que le moteur rend aujourd'hui. Si le socle
    change la forme d'une sortie coupée ou d'un refus, ce test échoue ; on relit alors les lecteurs de l'app, puis on
    régénère la fixture
    (`OPSYS_REGENERER_FIXTURES_MOBILE=1 pytest tests/e2e/test_liste_employe_appareil.py -k fixture`)."""
    enr = _enregistrer_la_liste_de_l_employe(moteur, equipe, monkeypatch)
    if os.environ.get(ENV_REGENERER) == "1":
        FIXTURE_APP.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_APP.write_text(json.dumps(
            {"fictif": True, "appels": enr.appels, "reponses": enr.reponses}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    fixture = json.loads(FIXTURE_APP.read_text(encoding="utf-8"))
    assert fixture["fictif"] is True
    assert set(fixture["reponses"]) == set(enr.reponses) and set(fixture["appels"]) == set(enr.appels)
    for nom, vivante in enr.reponses.items():
        assert _forme(vivante) == _forme(fixture["reponses"][nom]), f"{nom} : la forme du moteur a changé"
        assert enr.appels[nom] == fixture["appels"][nom], nom


# ---------------------------------------------------------------------------------------------------------
# L'app et le serveur parlent la même langue
# ---------------------------------------------------------------------------------------------------------
def test_les_statuts_d_intervention_de_l_app_sont_ceux_de_m4():
    interventions = _source("m4/interventions.ts")
    assert _liste_ts(interventions, "ETATS_INTERVENTION_M4") == list(etats_m4.ETATS), (
        "l'app connaît les statuts de M4, dans son ordre, `a_planifier` compris")
    assert _liste_ts(interventions, "ETATS_TERMINAUX_M4") == list(etats_m4.ETATS_TERMINAUX)
    actifs = _liste_ts(_source("today/selection.ts"), "ETATS_ACTIFS_AUJOURDHUI")
    assert actifs == ["en_route", "sur_site", "en_revue", "planifiee"]
    assert set(actifs) <= set(etats_m4.ETATS) - set(etats_m4.ETATS_TERMINAUX), "un statut actif n'est pas terminal"


def test_les_deux_outils_de_l_ecran_sont_dans_la_portee_de_l_employe():
    orchestrateur = _source("today/orchestrateur.ts")
    statut = _source("today/statut.ts")
    outils = {
        re.search(r'tool: "([a-z0-9_]+)"', orchestrateur).group(1),  # type: ignore[union-attr]
        re.search(r'tool: "([a-z0-9_]+)"', statut).group(1),  # type: ignore[union-attr]
    }
    assert outils == {"m4_lister_interventions", "m4_statut_intervention"}
    portee_employe = set(openclaw.roles_outils(charger_departements())["employee"])
    assert outils <= portee_employe, "l'app appelle un outil hors de la portée de l'employé"
    # Ni l'un ni l'autre n'écrit : le nom dit ce qu'il fait, et aucun ne décide.
    assert not any(mot in outil for outil in outils for mot in ("decider", "appliquer", "creer", "resoudre"))
