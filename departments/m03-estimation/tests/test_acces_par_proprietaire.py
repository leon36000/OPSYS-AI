"""PLAN T1.4-k2 : un vendeur ne lit que les devis des leads dont il est le PROPRIÉTAIRE.

`m3_lire_devis` et `m3_generer_soumission_brouillon` sont ouverts au vendeur (`roles_appareil`). Jusqu'ici
un vendeur authentifié lisait le devis de n'importe quel lead. Le propriétaire d'un lead est une donnée de
M2 (`owner` de sa qualification) : M3 la relit à la source du bus (`m2.lead_assigne`, publié par M2 dans la
transaction de la qualification), jamais depuis les arguments de l'appelant, et sans importer M2 (#109). Ici
le fait est publié à la main, comme M2 le publierait ; la CHAÎNE réelle (M2 qualifie, M3 relit) est prouvée
par `tests/test_acces_par_proprietaire.py` du socle.

Même patron que `test_projection_identite_appareil.py` : base SQLite temporaire migrée, outils RÉELS appelés
comme le fait `Capacites.appeler` (`executer_atomique`), vraies personnes. Chaque refus est prouvé SANS
écriture (toutes les tables de la base comparées avant et après). Données fictives (AGENTS.md).
"""

from __future__ import annotations

import base64
import contextlib
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import devis_durable  # noqa: E402
from m3_estimation.outils import outils, registre_devis_production  # noqa: E402
from sqlalchemy import select  # noqa: E402

from opsys import contexte, evenements, identite, stockage  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402
from opsys.stockage.schema import META  # noqa: E402

FICTIF = True
_HORODATAGE = "2026-09-29T14:00:00-04:00"
_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"

VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
ADMIN = contexte.IdentiteAppelante(personne="admin.un", role="admin")
EMPLOYE = contexte.IdentiteAppelante(personne="employe.un", role="employee")
INACTIF = contexte.IdentiteAppelante(personne="inactif.un", role="seller")

CODE_INTROUVABLE = "REJ-DEVIS-INTROUVABLE"
CODE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"

# devis -> lead : le devis d'un lead de vendeur.un, celui d'un lead de vendeur.deux, celui d'un lead que M2
# n'a jamais qualifié (aucun fait de propriété), celui d'un lead dont le fait est absent (qualifié avant).
DEVIS_UN = "M3-DEVIS-prop-001"
DEVIS_DEUX = "M3-DEVIS-prop-002"
DEVIS_SANS_PROPRIETAIRE = "M3-DEVIS-prop-003"
DEVIS_INCONNU = "M3-DEVIS-prop-fantome"


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(_outil(nom), arguments)


def _lead_assigne(lead_id, proprietaire, *, evenement_lead_id=None):
    """M2 a qualifié `lead_id` avec ce propriétaire : le fait que M3 relit à la source du bus."""
    with stockage.transaction():
        evenements.publier(
            "m2.lead_assigne", "m02-revenue-crm",
            {"lead_id": lead_id, "proprietaire": proprietaire, "horodatage_assignation": _HORODATAGE},
            evenement_id=f"m2-lead-assigne-{evenement_lead_id or lead_id}",
        )


def _creer_devis(devis_id, lead_id):
    reponse = _appeler("m3_creer_devis", {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{
            "description": "Gouttière alu 5 po", "quantite": "30", "unite": "pi_lin",
            "cout_unitaire": "10.00", "reference_besoin_materiau": "besoin-goutt-001",
        }],
        "taux_marge": "0.20", "horodatage": _HORODATAGE,
    })
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys-m3-proprietaire.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def scenario(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", _MOT_DE_PASSE, roles=["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", _MOT_DE_PASSE, roles=["seller"])
        identite.creer_personne(cnx, "admin.un", "Admin Un", _MOT_DE_PASSE, roles=["admin"])
        identite.creer_personne(cnx, "employe.un", "Employé Un", _MOT_DE_PASSE, roles=["employee"])
        identite.creer_personne(cnx, "inactif.un", "Inactif Un", _MOT_DE_PASSE, roles=["seller"], actif=False)
    _creer_devis(DEVIS_UN, "lead-un")
    _creer_devis(DEVIS_DEUX, "lead-deux")
    _creer_devis(DEVIS_SANS_PROPRIETAIRE, "lead-nouveau")
    _lead_assigne("lead-un", "vendeur.un")
    _lead_assigne("lead-deux", "vendeur.deux")


def _instantane_base():
    """Le contenu de TOUTES les tables : un refus ne doit rien écrire (registre, événement, trace...)."""
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


def _verdict(reponse):
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


_LECTURES = {
    "m3_lire_devis": lambda devis_id: {"devis_id": devis_id},
    "m3_generer_soumission_brouillon": lambda devis_id: {"devis_id": devis_id},
}


# =========================================================================================
# 1. Le vendeur lit les devis de SES leads, et seulement ceux-là
# =========================================================================================
def test_un_vendeur_lit_le_devis_de_son_lead_avec_marge_et_prix(scenario):
    devis = _accepte(_appeler("m3_lire_devis", {"devis_id": DEVIS_UN}, VENDEUR_UN))

    assert devis["devis_id"] == DEVIS_UN
    assert devis["cout_total"] == "300.00" and devis["prix_total"] == "360.00"  # §9.4 : marge de SA soumission


def test_un_vendeur_peut_toujours_se_restreindre_a_la_vue_employe_sur_son_lead(scenario):
    devis = _accepte(_appeler("m3_lire_devis", {"devis_id": DEVIS_UN, "role": "employe"}, VENDEUR_UN))

    assert "prix_total" not in devis and "cout_total" not in devis and "taux_marge" not in devis


def test_un_vendeur_obtient_le_brouillon_de_soumission_de_son_lead(scenario):
    brouillon = _accepte(_appeler("m3_generer_soumission_brouillon", {"devis_id": DEVIS_UN}, VENDEUR_UN))

    assert DEVIS_UN in str(brouillon)
    assert "cout_total" not in str(brouillon) and "taux_marge" not in str(brouillon)  # jamais coût ni marge


@pytest.mark.parametrize("nom_outil", sorted(_LECTURES))
def test_devis_d_un_autre_sans_proprietaire_ou_inconnu_donnent_le_meme_refus(scenario, nom_outil):
    """Le devis d'un lead d'un AUTRE vendeur, celui d'un lead que M2 n'a jamais qualifié (aucun propriétaire)
    et un devis INCONNU : le même code, le même détail (au devis_id près), aucune écriture. Un vendeur ne peut
    pas sonder quels devis existent."""
    verdicts = []
    for devis_id in (DEVIS_DEUX, DEVIS_SANS_PROPRIETAIRE, DEVIS_INCONNU):
        avant = _instantane_base()
        verdicts.append(_verdict(_appeler(nom_outil, _LECTURES[nom_outil](devis_id), VENDEUR_UN)))
        assert _instantane_base() == avant, f"{nom_outil} sur {devis_id} a écrit malgré le refus"

    assert {v["code"] for v in verdicts} == {CODE_INTROUVABLE}
    gabarit = verdicts[2]["detail"].replace(repr(DEVIS_INCONNU), "{}")
    assert verdicts[0]["detail"].replace(repr(DEVIS_DEUX), "{}") == gabarit
    assert verdicts[1]["detail"].replace(repr(DEVIS_SANS_PROPRIETAIRE), "{}") == gabarit
    assert "vendeur.deux" not in str(verdicts) and "lead-deux" not in str(verdicts)


def test_le_proprietaire_vient_de_m2_pas_des_arguments(scenario):
    """`m3_lire_devis` n'a aucun argument de propriété : le schéma refuse d'en accepter un, et l'identité
    vient du jeton."""
    reponse = _appeler("m3_lire_devis", {"devis_id": DEVIS_DEUX, "proprietaire": "vendeur.un"}, VENDEUR_UN)

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", reponse


def test_un_lead_qualifie_avant_le_fait_de_propriete_n_est_a_personne_fail_closed(scenario):
    """Aucun fait `m2.lead_assigne` pour ce lead (qualifié avant T1.4-k2) : M3 ne devine pas un propriétaire,
    ni depuis le `lead_id`, ni depuis un autre lead. Seul l'admin le lit (voir ROLES.md)."""
    assert _verdict(_appeler("m3_lire_devis", {"devis_id": DEVIS_SANS_PROPRIETAIRE}, VENDEUR_UN))[
        "code"] == CODE_INTROUVABLE
    assert _accepte(_appeler("m3_lire_devis", {"devis_id": DEVIS_SANS_PROPRIETAIRE}, ADMIN))["prix_total"]


def test_un_fait_de_propriete_d_un_autre_lead_ne_donne_rien(scenario):
    """Le fait relu doit nommer le lead demandé : un événement publié sous l'identifiant de `lead-nouveau`
    mais qui porte un autre `lead_id` ne fait de personne le propriétaire de `lead-nouveau`."""
    _lead_assigne("lead-ailleurs", "vendeur.un", evenement_lead_id="lead-nouveau")

    assert _verdict(_appeler("m3_lire_devis", {"devis_id": DEVIS_SANS_PROPRIETAIRE}, VENDEUR_UN))[
        "code"] == CODE_INTROUVABLE


# =========================================================================================
# 2. Admin, employé et agent : inchangés
# =========================================================================================
@pytest.mark.parametrize("devis_id", [DEVIS_UN, DEVIS_DEUX, DEVIS_SANS_PROPRIETAIRE])
def test_l_admin_lit_tous_les_devis_et_tous_les_brouillons(scenario, devis_id):
    assert _accepte(_appeler("m3_lire_devis", {"devis_id": devis_id}, ADMIN))["cout_total"] == "300.00"
    assert devis_id in str(_accepte(_appeler("m3_generer_soumission_brouillon", {"devis_id": devis_id}, ADMIN)))


def test_l_employe_reste_sans_cout_ni_marge_ni_prix_et_sans_filtre_par_proprietaire(scenario):
    """T2.3-d : la vue employé ne porte ni coût, ni marge, ni prix. Ce n'est pas un rôle à propriétaire :
    aucun filtre, mais jamais rien d'interne, ni même en le demandant."""
    devis = _accepte(_appeler("m3_lire_devis", {"devis_id": DEVIS_DEUX}, EMPLOYE))
    assert "cout_total" not in devis and "prix_total" not in devis and "taux_marge" not in devis
    elargi = _appeler("m3_lire_devis", {"devis_id": DEVIS_DEUX, "role": "interne"}, EMPLOYE)
    assert _verdict(elargi)["code"] == "REJ-ROLE-ELARGI"


def test_l_employe_n_obtient_pas_le_brouillon_qui_porte_les_prix(scenario):
    avant = _instantane_base()

    reponse = _appeler("m3_generer_soumission_brouillon", {"devis_id": DEVIS_UN}, EMPLOYE)

    assert _verdict(reponse)["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


@pytest.mark.parametrize("devis_id", [DEVIS_UN, DEVIS_DEUX, DEVIS_SANS_PROPRIETAIRE])
def test_la_voie_des_agents_reste_sans_filtre(scenario, devis_id):
    assert _accepte(_appeler("m3_lire_devis", {"devis_id": devis_id}))["prix_total"] == "360.00"
    assert devis_id in str(_accepte(_appeler("m3_generer_soumission_brouillon", {"devis_id": devis_id})))


# =========================================================================================
# 3. Identité non confirmée : refus avant toute lecture
# =========================================================================================
@pytest.mark.parametrize("nom_outil", sorted(_LECTURES))
@pytest.mark.parametrize("appelante", [
    contexte.IdentiteAppelante(personne="inactif.un", role="seller"),
    contexte.IdentiteAppelante(personne="fantome.un", role="seller"),
    contexte.IdentiteAppelante(personne="vendeur.un", role="admin"),
], ids=["personne-desactivee", "personne-inconnue", "role-jamais-porte"])
def test_une_identite_non_confirmee_est_refusee_avant_de_lire_le_devis(scenario, nom_outil, appelante):
    """Même pour un `devis_id` inconnu : l'identité est vérifiée d'abord, le refus ne dit rien du registre."""
    avant = _instantane_base()

    for devis_id in (DEVIS_UN, DEVIS_INCONNU):
        assert _verdict(_appeler(nom_outil, _LECTURES[nom_outil](devis_id), appelante))["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


@pytest.mark.parametrize("nom_outil", sorted(_LECTURES))
def test_un_role_retire_depuis_l_appairage_est_refuse_avec_le_meme_jeton(scenario, nom_outil):
    arguments = _LECTURES[nom_outil](DEVIS_UN)
    assert _appeler(nom_outil, arguments, VENDEUR_UN)["resultat"]["accepte"] is True
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "vendeur.un", "seller")
        identite.ajouter_role(cnx, "vendeur.un", "employee")

    assert _verdict(_appeler(nom_outil, arguments, VENDEUR_UN))["code"] == CODE_INVALIDE


@pytest.mark.parametrize("nom_outil", sorted(_LECTURES))
def test_hors_transaction_le_vendeur_n_est_pas_verifiable_donc_refuse(scenario, nom_outil):
    """Appel direct de la fonction, sans la transaction de `executer_atomique` : aucune base jointe, donc
    aucune identité crue sur parole."""
    with contexte.appele_par_appareil(VENDEUR_UN):
        reponse = _outil(nom_outil).fonction(**_LECTURES[nom_outil](DEVIS_UN))

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == CODE_INVALIDE


def test_le_fait_de_propriete_n_est_pas_lisible_hors_transaction():
    """Sans base jointe, M3 ne suppose aucun propriétaire (jamais une valeur par défaut)."""
    from m3_estimation import outils as module_outils

    assert module_outils._proprietaire_du_lead("lead-un") is None
    assert module_outils._proprietaire_du_lead("") is None
    assert module_outils._proprietaire_du_lead(None) is None

# =========================================================================================
# 3. Inventaire vendeur M3 : lecture seule, pagination stable, sans divulgation inter-vendeurs
# =========================================================================================
def test_m3_lister_devis_est_un_outil_t0_pagine_sans_argument_de_proprietaire():
    outil = _outil("m3_lister_devis")
    assert outil.autonomie.value == "T0"
    assert outil.roles_appareil == frozenset({"seller"})
    assert set(outil.parametres["properties"]) == {"limite", "curseur"}
    assert "required" not in outil.parametres or outil.parametres["required"] == []
    assert "proprietaire" not in outil.parametres["properties"]
    assert outil.parametres["additionalProperties"] is False


def test_m3_lister_devis_refuse_absence_appareil_et_roles_non_vendeur(scenario):
    for appareil in (None, EMPLOYE, ADMIN, INACTIF):
        verdict = _verdict(_appeler("m3_lister_devis", {}, appareil))
        assert verdict["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_m3_lister_devis_ne_rend_que_le_proprietaire_et_est_rejouable_sans_ecriture(scenario):
    avant = _instantane_base()
    premiere = _accepte(_appeler("m3_lister_devis", {}, VENDEUR_UN))
    rejouee = _accepte(_appeler("m3_lister_devis", {}, VENDEUR_UN))

    assert premiere == rejouee
    assert [devis["devis_id"] for devis in premiere["devis"]] == [DEVIS_UN]
    assert premiere["devis"][0]["statut"] == "brouillon"
    assert premiere["curseur_suivant"] is None
    assert "total" not in premiere and "nombre_total" not in premiere
    assert _instantane_base() == avant


def test_m3_lister_devis_pagine_dans_un_ordre_stable_et_lie_au_vendeur(scenario):
    for devis_id, lead_id in (
        ("M3-DEVIS-prop-000", "lead-un-0"),
        ("M3-DEVIS-prop-004", "lead-un-4"),
    ):
        _creer_devis(devis_id, lead_id)
        _lead_assigne(lead_id, "vendeur.un")
    with stockage.transaction():
        registre = registre_devis_production()
        _, rejet = devis_durable.marquer_devis_envoye(
            "M3-DEVIS-prop-000", _HORODATAGE, registre
        )
        assert rejet is None
        _, rejet = devis_durable.marquer_devis_envoye(
            "M3-DEVIS-prop-004", _HORODATAGE, registre
        )
        assert rejet is None
        _, rejet = devis_durable.marquer_devis_accepte(
            "M3-DEVIS-prop-004", "humain ayant constaté l'acceptation", _HORODATAGE, registre
        )
        assert rejet is None
    avant = _instantane_base()

    page1 = _accepte(_appeler("m3_lister_devis", {"limite": 1}, VENDEUR_UN))
    page2 = _accepte(_appeler("m3_lister_devis", {"limite": 1, "curseur": page1["curseur_suivant"]}, VENDEUR_UN))
    page3 = _accepte(_appeler("m3_lister_devis", {"limite": 1, "curseur": page2["curseur_suivant"]}, VENDEUR_UN))

    assert [
        page1["devis"][0]["devis_id"],
        page2["devis"][0]["devis_id"],
        page3["devis"][0]["devis_id"],
    ] == ["M3-DEVIS-prop-000", DEVIS_UN, "M3-DEVIS-prop-004"]
    assert [page1["devis"][0]["statut"], page2["devis"][0]["statut"], page3["devis"][0]["statut"]] == [
        "envoye", "brouillon", "accepte",
    ]
    assert page1["curseur_suivant"] and page2["curseur_suivant"]
    assert page3["curseur_suivant"] is None
    assert all("devis_id" not in page for page in (page1, page2, page3))
    assert _instantane_base() == avant

    croise = _verdict(_appeler(
        "m3_lister_devis", {"limite": 1, "curseur": page1["curseur_suivant"]}, VENDEUR_DEUX
    ))
    assert croise["code"] == "REJ-CONTRAT-INVALIDE"

    for identifiant_inconnu_ou_autre in (DEVIS_DEUX, DEVIS_INCONNU):
        charge = json.dumps(
            {"version": 1, "personne": "vendeur.un", "devis_id": identifiant_inconnu_ou_autre},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        curseur_forge = base64.urlsafe_b64encode(charge).decode("ascii").rstrip("=")
        verdict = _verdict(_appeler(
            "m3_lister_devis", {"limite": 1, "curseur": curseur_forge}, VENDEUR_UN
        ))
        assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
        assert verdict["detail"] == "curseur invalide"


@pytest.mark.parametrize("arguments", [
    {"limite": 0}, {"limite": 51}, {"limite": True}, {"limite": "1"}, {"curseur": "%%"},
])
def test_m3_lister_devis_refuse_limites_et_curseurs_invalides_sans_ecriture(scenario, arguments):
    avant = _instantane_base()
    reponse = _appeler("m3_lister_devis", arguments, VENDEUR_UN)
    assert reponse["ok"] is False or reponse["resultat"]["accepte"] is False
    if reponse["ok"]:
        assert reponse["resultat"]["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
    assert _instantane_base() == avant


def test_m3_lister_devis_refuse_un_role_vendeur_retire(scenario):
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "vendeur.un", "seller")
    avant = _instantane_base()
    verdict = _verdict(_appeler("m3_lister_devis", {}, VENDEUR_UN))
    assert verdict["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _instantane_base() == avant


def test_m3_lister_devis_invalide_le_curseur_si_le_lead_repere_est_reassigne(scenario):
    _creer_devis("M3-DEVIS-prop-000", "lead-un-0")
    _lead_assigne("lead-un-0", "vendeur.un")
    _creer_devis("M3-DEVIS-prop-004", "lead-un-4")
    _lead_assigne("lead-un-4", "vendeur.un")
    page = _accepte(_appeler("m3_lister_devis", {"limite": 1}, VENDEUR_UN))
    assert page["devis"][0]["devis_id"] == "M3-DEVIS-prop-000"

    with stockage.transaction():
        evenements.publier(
            "m2.lead_assigne",
            "m02-revenue-crm",
            {
                "lead_id": "lead-un-0",
                "proprietaire": "vendeur.deux",
                "horodatage_assignation": "2026-09-29T15:00:00-04:00",
                "rang": 2,
                "proprietaire_precedent": "vendeur.un",
            },
            evenement_id="m2-lead-reassigne-2-lead-un-0",
        )
    verdict = _verdict(_appeler(
        "m3_lister_devis",
        {"limite": 1, "curseur": page["curseur_suivant"]},
        VENDEUR_UN,
    ))
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert verdict["detail"] == "curseur invalide"
