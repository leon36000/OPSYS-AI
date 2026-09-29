"""`m8_lire_vue_executive` (PLAN T4.19, M8.6) : la vue exécutive du propriétaire.

Ce que ce fichier prouve :
- l'outil est T0, réservé à l'`admin`, et n'a qu'un paramètre facultatif (`aujourd_hui`, pour l'âge du constat du cash
  libre) ; tout autre rôle d'appareil est refusé DANS LE CODE, avant toute lecture (le socle n'applique pas
  `roles_appareil` à un outil de lecture hors du core) ;
- lecture pure : rien n'est écrit, rien n'est publié ;
- M8 lit, il ne recalcule pas : la marge réelle de M5 est reprise telle quelle (aucune somme, aucun arrondi, un
  garde statique le verrouille), le stock à commander est ce que M6 met à la file du propriétaire (M6 seul est
  appelé), le cash libre est « manque » tant que M5 n'a rien constaté (T4.19-b : le dernier constat, tel quel, avec son
  âge, est dans `test_vue_executive_cash_libre.py`) ;
- une donnée absente est un manque nommé, dit une fois, jamais un zéro ;
- la réponse est bornée sous la limite du socle : ce qui n'y tient pas est compté (`reste`), jamais coupé.

Les faits sont injectés en mémoire quand la base n'est pas nécessaire ; les tests d'identité et de lecture de M6
montent une base SQLite migrée avec de vraies personnes (fictives) et posent l'identité d'un appareil comme le fait
OPSYS-CORE (`opsys.contexte.appele_par_appareil`). M6 est doublé par un département de test : le vrai M6 se lit dans
`tests/test_cascade_mesure_m8_m9.py`.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml
from m8_analytics import entonnoir, mesures_chantier, vue_executive
from m8_analytics import outils as m8_outils
from m8_analytics.outils import outils
from m8_analytics.registre import RegistreSnapshots
from sqlalchemy import func, select

from opsys import contexte, identite, jetons, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer, executer_atomique
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True  # aucun client réel : des identifiants, des personnes et des montants de test

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_SRC_M8 = Path(__file__).resolve().parents[1] / "src" / "m8_analytics"
_M6 = "m06-material-control"
_ADMIN = IdentiteAppelante("admin.fictif", "admin")
ACTION_M6 = "Décider de commander : M6 n'en crée jamais seul (fictif)"


# ---------------------------------------------------------------------------
# Faits, construits par les vrais constructeurs
# ---------------------------------------------------------------------------
def _lead(lead_id, arrivee="2026-09-29T09:15:00-04:00"):
    return entonnoir.fait_lead_recu({"lead_id": lead_id, "client_id": "a" * 64, "horodatage_association": arrivee})


def _envoye(devis_id, lead_id="lead-1-fictif", quand="2026-09-29T15:00:00-04:00"):
    return entonnoir.fait_devis_envoye(
        {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_envoi": quand}
    )


def _accepte(devis_id, lead_id="lead-1-fictif", prix="600.00", quand="2026-09-30T10:00:00-04:00"):
    return entonnoir.fait_devis_accepte({
        "devis_id": devis_id, "lead_id": lead_id, "prix_total": prix, "horodatage_acceptation": quand,
    })


def _sans_reponse(devis_id, statut="envoye", depuis="2026-09-29T15:30:00-04:00"):
    return entonnoir.fait_devis_sans_reponse({
        "devis_id": devis_id, "lead_id": "lead-1-fictif", "statut": statut, "horodatage_devis": depuis,
        "horodatage_reference": "2026-10-08T08:00:00-04:00", "delai_relance_jours": 7,
    })


def _wct(wct_id, devis_id, quand="2026-10-05T14:00:00-04:00"):
    return mesures_chantier.fait_wct({
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "devis_id": devis_id, "technicien_id": "tech-fictif",
        "horodatage_completion": quand, "duree_reelle_minutes": 100, "statut": "completed_verified",
    })


def _marge(wct_id, devis_id, sequence, marge, manque=(), verdict=None):
    """Le fait de M5 tel que `mesures_chantier.fait_rentabilite` le range : la marge en texte, ou `None` avec les
    codes de ce que M5 n'a pas pu chiffrer."""
    calculee = marge is not None
    return mesures_chantier.fait_rentabilite({
        "wct_id": wct_id, "devis_id": devis_id, "sequence": sequence, "marge_reelle_cad": marge,
        "verdict": verdict or ("CALCULEE" if calculee else "PARTIELLE"), "cout_reel_complet": calculee,
        "manque": list(manque),
    })


def _par_nom(faits_entonnoir=None, faits_chantier=None, faits_cash_libre=None):
    return {
        o.nom: o
        for o in outils(
            RegistreSnapshots(), [], faits_chantier if faits_chantier is not None else [],
            faits_entonnoir if faits_entonnoir is not None else [],
            faits_cash_libre_cible=faits_cash_libre if faits_cash_libre is not None else [],
        )
    }


def _lire(par_nom, appelante=None, atomique=False):
    """L'appel de l'outil : `executer` (aucune base), ou `executer_atomique` (dans la transaction d'un outil)."""
    lancer = executer_atomique if atomique else executer
    if appelante is None:
        return lancer(par_nom["m8_lire_vue_executive"], {})
    with contexte.appele_par_appareil(appelante):
        return lancer(par_nom["m8_lire_vue_executive"], {})


def _vue(par_nom, appelante=None, atomique=False):
    reponse = _lire(par_nom, appelante, atomique)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


class _FauxDepartement:
    """Un département de test : il ne sait que dire son identifiant et donner sa fonction `attentes()`. Compte ses
    appels : la vue ne doit appeler QUE M6."""

    def __init__(self, identifiant, attentes=(), echec=None):
        self.id = identifiant
        self._attentes = list(attentes)
        self._echec = echec
        self.appels = 0

    def charger_attentes(self):
        def attentes():
            self.appels += 1
            if self._echec is not None:
                raise self._echec
            return list(self._attentes)

        return attentes

    def charger_outils(self):
        raise AssertionError(f"{self.id} : la vue exécutive n'appelle l'outil d'aucun département")


def _attente(type_attente, identifiant, resume, depuis="2026-10-04T12:00:00+00:00", niveau="N2"):
    return {
        "type": type_attente, "id": identifiant, "resume": resume, "niveau": niveau, "depuis": depuis,
        "action_proposee": ACTION_M6,
    }


def _besoin(materiau, depuis="2026-10-04T12:00:00+00:00", resume=None):
    return _attente(
        "besoin_commande", f"besoin_commande:{materiau}",
        resume or f"Stock bas : {materiau} — 10 pi en main, sous le seuil de 150 pi (fictif)", depuis,
    )


@pytest.fixture
def m6_de_test(monkeypatch):
    """Remplace les départements que la vue charge : M6 de test (et un M5 qui ne doit jamais être appelé)."""
    def poser(**arguments):
        m6 = _FauxDepartement(_M6, **arguments)
        m5 = _FauxDepartement("m05-financecore")
        monkeypatch.setattr(m8_outils, "charger_departements", lambda: {_M6: m6, "m05-financecore": m5})
        return m6, m5

    return poser


@pytest.fixture
def base_avec_personnes(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-1234", ["admin"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
        identite.creer_personne(cnx, "ancien.fictif", "Ancien Admin Fictif", "mot-de-passe-ancien-1234", ["admin"],
                                actif=False)
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-1234", ["seller"])
    yield url
    stockage.liberer()


@pytest.fixture
def configurer(tmp_path, monkeypatch):
    """Pose `department.yaml/configuration` du test ; sans appel, M8 lit le vrai manifeste (aucun seuil)."""
    def poser(seuils_entonnoir):
        manifeste = tmp_path / "department.yaml"
        contenu = {"configuration": {"seuils_entonnoir": seuils_entonnoir}}
        manifeste.write_text(yaml.safe_dump(contenu), encoding="utf-8")
        monkeypatch.setattr(m8_outils, "_MANIFESTE", manifeste)

    return poser


# ---------------------------------------------------------------------------
# La déclaration : T0, sans paramètre, admin seulement
# ---------------------------------------------------------------------------
def test_l_outil_est_t0_reserve_au_role_admin_avec_un_seul_parametre_facultatif_la_date_de_l_appelant():
    outil = _par_nom()["m8_lire_vue_executive"]

    assert outil.autonomie == Autonomie.T0 and not outil.frontiere_humaine
    assert outil.roles_appareil == frozenset({"admin"})  # ni employee, ni seller
    assert set(outil.parametres["properties"]) == {"aujourd_hui"} and "required" not in outil.parametres
    assert outil.parametres["properties"]["aujourd_hui"]["type"] == ["string", "null"]
    assert outil.parametres["additionalProperties"] is False and outil.parametres["type"] == "object"
    assert "Réservé à l'admin" in outil.description and len(outil.description) <= 1024
    assert "aujourd_hui" in outil.description and "M8 n'a pas d'horloge" in outil.description


def test_aucun_argument_n_est_accepte_ni_role_ni_montant_ni_periode_seule_la_date_de_l_appelant_l_est():
    outil = _par_nom()["m8_lire_vue_executive"]

    for argument in ({"role": "admin"}, {"autorise_couts": True}, {"cash_libre": "1000.00"}, {"limite": 50},
                     {"aujourd_hui": "2026-10-02", "role": "admin"}, {"aujourd_hui": 20261002},
                     {"aujourd_hui": ["2026-10-02"]}):
        reponse = executer(outil, argument)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", argument
    for argument in ({}, {"aujourd_hui": None}, {"aujourd_hui": "2026-10-02"}):
        assert executer(outil, argument)["ok"] is True, argument


# ---------------------------------------------------------------------------
# Qui peut lire : l'admin authentifié ; tout autre rôle d'appareil est refusé dans le code, avant toute lecture
# ---------------------------------------------------------------------------
def test_l_admin_authentifie_lit_la_vue(base_avec_personnes, m6_de_test):
    m6_de_test()

    vue = _vue(_par_nom([_lead("lead-1-fictif")]), _ADMIN, atomique=True)

    assert vue["vue"] == "executive"
    assert set(vue) == {"vue", "portee", "entonnoir", "marge_reelle", "stock_a_commander", "cash_libre", "manques"}


def test_sans_identite_d_appareil_la_voie_des_agents_reste_ouverte(base_avec_personnes, m6_de_test):
    m6_de_test()

    assert _vue(_par_nom([_lead("lead-1-fictif")]), None, atomique=True)["vue"] == "executive"


class _RegistreQuiNeSeLitPas:
    """Un registre qui échoue s'il est lu : prouve qu'un refus arrive AVANT toute lecture."""

    def __iter__(self):
        raise AssertionError("un registre a été lu avant le refus du rôle")


@pytest.mark.parametrize("appelante", [
    IdentiteAppelante("employe.fictif", "employee"),   # rôle non admin
    IdentiteAppelante("vendeur.fictif", "seller"),
    IdentiteAppelante("employe.fictif", "admin"),      # jeton qui prétend un rôle que la personne n'a pas
    IdentiteAppelante("ancien.fictif", "admin"),       # personne désactivée depuis l'émission du jeton
    IdentiteAppelante("inconnu.fictif", "admin"),      # personne inconnue
    IdentiteAppelante("admin.fictif", "employee"),     # un admin qui se présente avec un rôle de moindre portée
])
def test_tout_autre_role_d_appareil_est_refuse_dans_le_code_avant_toute_lecture(base_avec_personnes, appelante):
    par_nom = _par_nom(_RegistreQuiNeSeLitPas(), _RegistreQuiNeSeLitPas())

    reponse = _lire(par_nom, appelante, atomique=True)

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE")
    assert "réservée à l'admin" in reponse["details"]


def test_une_identite_d_admin_hors_transaction_est_refusee_faute_de_pouvoir_la_verifier(base_avec_personnes):
    """Aucune base jointe : rien n'est vérifiable, donc rien n'est cru sur parole (fail-closed)."""
    par_nom = _par_nom(_RegistreQuiNeSeLitPas(), _RegistreQuiNeSeLitPas())

    reponse = _lire(par_nom, _ADMIN, atomique=False)

    assert reponse["ok"] is False and reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE")


def test_par_capacites_un_employe_est_refuse_et_un_admin_lit(base_avec_personnes, m6_de_test):
    """Le chemin réel d'un appel d'outil (`Capacites`) : le socle n'applique pas `roles_appareil` à un outil de
    lecture hors du core, c'est donc l'outil qui refuse."""
    m6_de_test()
    capacites = Capacites(
        charger_departements(_RACINE_DEPARTEMENTS), stockage.transaction, filtre={"m08-analytics"}, memoire=False,
    )

    with contexte.appele_par_appareil(IdentiteAppelante("employe.fictif", "employee")):
        refus = capacites.appeler("m8_lire_vue_executive", {})
    with contexte.appele_par_appareil(_ADMIN):
        accepte = capacites.appeler("m8_lire_vue_executive", {})

    assert refus["ok"] is False and "REJ-IDENTITE-APPAREIL-INVALIDE" in json.dumps(refus, ensure_ascii=False)
    assert "resultat" not in refus and not {"entonnoir", "marge_reelle", "stock_a_commander"} & set(
        json.dumps(refus).replace('"', " ").replace(":", " ").split()
    )
    assert accepte["ok"] is True and accepte["resultat"]["vue"] == "executive"


# ---------------------------------------------------------------------------
# Lecture pure
# ---------------------------------------------------------------------------
def _etat_des_ecritures():
    with stockage.transaction() as cnx:
        return {
            "registres": cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one(),
            "sortants": cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one(),
            "recus": cnx.execute(select(func.count()).select_from(EVENEMENTS_RECUS)).scalar_one(),
        }


def test_la_lecture_n_ecrit_rien_et_ne_publie_rien(base_avec_personnes, m6_de_test):
    m6_de_test(attentes=[_besoin("gouttiere-fictif")])
    with stockage.transaction():
        faits = stockage.maillons("m08-analytics", "faits_chantier")
        entonnoir_registre = stockage.maillons("m08-analytics", "faits_entonnoir")
        for fait in (_wct("w1", "D1"), _marge("w1", "D1", 1, "52.00")):
            faits.append(fait)
        for fait in (_lead("L1"), _envoye("D1"), _accepte("D1")):
            entonnoir_registre.append(fait)
    avant = _etat_des_ecritures()
    par_nom = {o.nom: o for o in outils()}  # les registres durables, comme en production

    premiere = _vue(par_nom, _ADMIN, atomique=True)
    seconde = _vue(par_nom, _ADMIN, atomique=True)

    assert _etat_des_ecritures() == avant
    assert premiere == seconde  # même état, même vue
    assert premiere["marge_reelle"]["chantiers"][0]["marge_reelle_cad"] == "52.00"


# ---------------------------------------------------------------------------
# L'entonnoir dans la vue
# ---------------------------------------------------------------------------
def _trajet():
    return [
        _lead("lead-1-fictif"), _envoye("D1"), _envoye("D2", quand="2026-09-29T15:30:00-04:00"), _accepte("D1"),
        _sans_reponse("D2"), _sans_reponse("D3", statut="brouillon", depuis="2026-09-30T09:00:00-04:00"),
    ]


def test_la_vue_montre_l_entonnoir_mesure_avec_version_proprietaire_et_sources(m6_de_test):
    m6_de_test()

    entonnoir_vue = _vue(_par_nom(_trajet()))["entonnoir"]

    lignes = {m["metric_id"]: m for m in entonnoir_vue["mesures"]}
    assert {m: (x["valeur"], x["statut"]) for m, x in lignes.items()} == {
        "m8_leads_recus": ("1", "calculee"), "m8_leads_qualifies": ("0", "calculee"),
        "m8_devis_envoyes": ("2", "calculee"), "m8_devis_acceptes": ("1", "calculee"),
        "m8_devis_sans_reponse": ("1", "calculee"), "m8_taux_acceptation_pct": ("50.00", "calculee"),
        "m8_delai_lead_acceptation_jours": ("1.03", "calculee"), "m8_carnet_signe_cad": ("600.00", "calculee"),
    }
    for ligne in lignes.values():
        assert len(ligne["version_definition"]) == 64 and ligne["proprietaire"].startswith(("m02-", "m03-"))
        assert ligne["nom"] and ligne["unite"] and "manque" not in ligne
    assert lignes["m8_taux_acceptation_pct"]["entrees"]["n_envoyes"] == 2
    assert [(s["evenement"], s["n"]) for s in entonnoir_vue["sources"]] == [
        ("m2.client_associe", 1), ("m2.lead_assigne", 0), ("m3.devis_envoye", 2), ("m3.devis_accepte", 1),
        ("m3.devis_sans_reponse", 2),
    ]
    assert entonnoir_vue["devis_en_attente"] == {
        "sans_reponse": {"n": 1, "devis": ["D2"], "reste": 0},
        "brouillons_en_retard": {"n": 1, "devis": ["D3"], "reste": 0},
    }


def test_sans_aucun_fait_la_vue_dit_non_calculable_et_nomme_ce_qui_manque_une_seule_fois(m6_de_test):
    m6_de_test()

    vue = _vue(_par_nom())

    lignes = vue["entonnoir"]["mesures"]
    assert len(lignes) == 8 and all(m["statut"] == "non_calculable" and m["valeur"] is None for m in lignes)
    assert all(m["manque"] for m in lignes) and all("entrees" not in m for m in lignes)
    champs = [m["champ"] for m in vue["manques"]]
    assert champs[:5] == [
        "m2.client_associe", "m2.lead_assigne", "m3.devis_envoye", "m3.devis_accepte", "m3.devis_sans_reponse",
    ]  # « aucun devis accepté reçu » vaut pour quatre métriques : dit une fois
    assert len(champs) == len(set(champs))
    assert [s["n"] for s in vue["entonnoir"]["sources"]] == [0, 0, 0, 0, 0]


def test_les_seuils_vides_du_vrai_manifeste_disent_seuil_a_configurer_et_ou(m6_de_test):
    m6_de_test()
    assert m8_outils._seuils_entonnoir() == {}  # le vrai `department.yaml` de M8, tel que livré

    seuils = _vue(_par_nom(_trajet()))["entonnoir"]["seuils"]

    assert seuils == {
        "a_configurer": [
            "m8_devis_sans_reponse", "m8_taux_acceptation_pct", "m8_delai_lead_acceptation_jours",
            "m8_carnet_signe_cad",
        ],
        "invalides": [], "ignores": [], "evalues": [],
        "configuration": "department.yaml de m08-analytics, configuration.seuils_entonnoir",
    }


def test_un_seuil_configure_est_evalue_dans_la_vue_sans_alerte_ni_decision(m6_de_test, configurer):
    m6_de_test()
    configurer({
        "m8_taux_acceptation_pct": {"sens": "au_dessous", "valeur": 60},  # 50,00 : franchi
        "m8_carnet_signe_cad": {"sens": "au_dessous", "valeur": 100},  # 600,00 : non franchi
        "m8_devis_sans_reponse": {"sens": "au_dessus"},  # invalide : pas de valeur
    })

    seuils = _vue(_par_nom(_trajet()))["entonnoir"]["seuils"]

    assert seuils["a_configurer"] == ["m8_delai_lead_acceptation_jours"]
    assert seuils["invalides"] == ["m8_devis_sans_reponse"]
    assert seuils["evalues"] == [
        {"metric_id": "m8_taux_acceptation_pct", "statut": "franchi", "valeur": "50.00", "unite": "pourcentage",
         "sens": "au_dessous", "seuil": "60.00"},
        {"metric_id": "m8_carnet_signe_cad", "statut": "non_franchi", "valeur": "600.00", "unite": "CAD",
         "sens": "au_dessous", "seuil": "100.00"},
    ]
    assert "configuration" in seuils  # il reste des seuils à définir ou à corriger


def test_quand_tous_les_seuils_sont_valides_la_vue_n_a_plus_rien_a_faire_configurer(m6_de_test, configurer):
    m6_de_test()
    configurer({
        "m8_taux_acceptation_pct": {"sens": "au_dessous", "valeur": 30},
        "m8_carnet_signe_cad": {"sens": "au_dessous", "valeur": 100},
        "m8_devis_sans_reponse": {"sens": "au_dessus", "valeur": 5},
        "m8_delai_lead_acceptation_jours": {"sens": "au_dessus", "valeur": 14},
    })

    seuils = _vue(_par_nom(_trajet()))["entonnoir"]["seuils"]

    assert seuils["a_configurer"] == [] and seuils["invalides"] == [] and seuils["ignores"] == []
    assert "configuration" not in seuils
    assert {e["statut"] for e in seuils["evalues"]} == {"non_franchi"}


def test_une_cle_de_seuil_qui_ne_surveille_rien_est_dite_dans_la_vue_avec_l_endroit_ou_la_corriger(
        m6_de_test, configurer):
    m6_de_test()
    configurer({
        "m8_taux_acceptation_pct": {"sens": "au_dessous", "valeur": 30},
        "m8_carnet_signe_cad": {"sens": "au_dessous", "valeur": 100},
        "m8_devis_sans_reponse": {"sens": "au_dessus", "valeur": 5},
        "m8_delai_lead_acceptation_jours": {"sens": "au_dessus", "valeur": 14},
        "m8_leads_recus": {"sens": "au_dessous", "valeur": 10},  # un comptage cumulé : rien à surveiller
        "m8_taux_acceptaton_pct": {"sens": "au_dessous", "valeur": 30},  # faute de frappe
    })

    seuils = _vue(_par_nom(_trajet()))["entonnoir"]["seuils"]

    assert seuils["ignores"] == ["m8_leads_recus", "m8_taux_acceptaton_pct"]
    assert seuils["a_configurer"] == [] and seuils["invalides"] == [] and len(seuils["evalues"]) == 4
    assert seuils["configuration"] == "department.yaml de m08-analytics, configuration.seuils_entonnoir"


def test_les_devis_en_attente_sont_plafonnes_du_plus_ancien_au_plus_recent_et_le_reste_est_compte(m6_de_test):
    m6_de_test()
    faits = [_sans_reponse(f"D{numero}", depuis=f"2026-09-{numero:02d}T08:00:00-04:00") for numero in (7, 3, 9, 1, 5)]

    attente = _vue(_par_nom(faits))["entonnoir"]["devis_en_attente"]["sans_reponse"]

    assert attente == {"n": 5, "devis": ["D1", "D3", "D5"], "reste": 2}


# ---------------------------------------------------------------------------
# La marge réelle : celle de M5, reprise sans un seul calcul
# ---------------------------------------------------------------------------
def test_la_marge_reelle_est_celle_de_m5_en_texte_sans_somme_ni_arrondi_ni_ecart(m6_de_test):
    m6_de_test()
    chantiers = [
        _wct("w-recent", "D3", "2026-10-07T14:00:00-04:00"), _marge("w-recent", "D3", 1, "52.00"),
        _wct("w-perte", "D2", "2026-10-06T14:00:00-04:00"), _marge("w-perte", "D2", 1, "-1234.50"),
        _wct("w-ancien", "D1", "2026-10-01T14:00:00-04:00"),
        _marge("w-ancien", "D1", 1, None, ("REJ-COUT-PRIX-ABSENT",)),
    ]

    marge = _vue(_par_nom(faits_chantier=chantiers))["marge_reelle"]

    assert marge["source"].startswith("M5 (m5.rentabilite_chantier)") and "aucun calcul" in marge["source"]
    assert (marge["n_chantiers"], marge["n_marge_connue"], marge["n_non_calculable"]) == (3, 2, 1)
    assert [c["wct_id"] for c in marge["chantiers"]] == ["w-recent", "w-perte", "w-ancien"]  # le plus récent d'abord
    assert [c["marge_reelle_cad"] for c in marge["chantiers"]] == ["52.00", "-1234.50", None]  # verbatim
    assert marge["chantiers"][0] == {
        "wct_id": "w-recent", "devis_id": "D3", "horodatage_completion": "2026-10-07T14:00:00-04:00",
        "statut": "calculee", "marge_reelle_cad": "52.00",
    }
    texte = json.dumps(marge)
    for chiffre_calcule in ("-1182.50", "1182.50", "-591.25", "17.33", "-1234.5 ", "1286.50"):
        assert chiffre_calcule not in texte, chiffre_calcule  # ni somme, ni moyenne, ni écart


def test_une_marge_que_m5_n_a_pas_chiffree_dit_pourquoi_avec_les_codes_de_m5(m6_de_test):
    m6_de_test()
    chantiers = [
        _wct("w-codes", "D1", "2026-10-03T14:00:00-04:00"),
        _marge("w-codes", "D1", 1, None, ("REJ-COUT-PRIX-ABSENT", "REJ-RENTABILITE-FACTURE-ABSENTE")),
        _wct("w-sans-code", "D2", "2026-10-02T14:00:00-04:00"), _marge("w-sans-code", "D2", 1, None),
        _wct("w-rien", "D3", "2026-10-01T14:00:00-04:00"),  # M5 n'a encore rien publié pour ce chantier
    ]

    lignes = {c["wct_id"]: c for c in _vue(_par_nom(faits_chantier=chantiers))["marge_reelle"]["chantiers"]}

    assert lignes["w-codes"]["raison"] == (
        "M5 n'a pas chiffré la marge réelle : REJ-COUT-PRIX-ABSENT, REJ-RENTABILITE-FACTURE-ABSENTE"
    )
    assert lignes["w-sans-code"]["raison"] == "M5 n'a pas chiffré la marge réelle (verdict PARTIELLE)"
    assert lignes["w-rien"]["raison"] == "M5 n'a rien publié pour ce chantier (m5.rentabilite_chantier)"
    for ligne in lignes.values():
        assert ligne["statut"] == "non_calculable" and ligne["marge_reelle_cad"] is None


def test_le_plus_grand_rang_de_m5_fait_foi_quel_que_soit_l_ordre_de_livraison(m6_de_test):
    m6_de_test()
    ancien, recent = _marge("w1", "D1", 1, None, ("REJ-COUT-PRIX-ABSENT",)), _marge("w1", "D1", 2, "52.00")

    for ordre in ([ancien, recent], [recent, ancien]):
        marge = _vue(_par_nom(faits_chantier=[_wct("w1", "D1"), *ordre]))["marge_reelle"]

        assert marge["chantiers"][0]["marge_reelle_cad"] == "52.00" and marge["n_marge_connue"] == 1


def test_un_chantier_connu_une_fois_seulement_et_les_autres_faits_du_registre_ne_sont_pas_des_chantiers(m6_de_test):
    m6_de_test()
    faits = [
        _wct("w1", "D1"), _wct("w1", "D1"),  # relivré : un seul chantier
        _marge("w-orphelin", "D9", 1, "999.00"),  # M5 a publié pour un WCT que M8 n'a pas reçu : pas listé
        {"type_entree": "devis", "devis_id": "D1", "prix_total": "600.00", "cout_total": "480.00"},
        {"type_entree": "variance", "wct_id": "w1", "statut_variance": "evaluee"},
    ]

    marge = _vue(_par_nom(faits_chantier=faits))["marge_reelle"]

    assert marge["n_chantiers"] == 1 and [c["wct_id"] for c in marge["chantiers"]] == ["w1"]
    assert "999.00" not in json.dumps(marge)


def test_la_liste_des_chantiers_est_plafonnee_et_le_reste_est_compte(m6_de_test):
    m6_de_test()
    faits = []
    for numero in range(1, 8):
        faits += [_wct(f"w{numero}", f"D{numero}", f"2026-10-{numero:02d}T14:00:00-04:00"),
                  _marge(f"w{numero}", f"D{numero}", 1, f"{numero}0.00")]

    marge = _vue(_par_nom(faits_chantier=faits))["marge_reelle"]

    assert marge["n_chantiers"] == 7 and marge["reste"] == 4
    assert [c["wct_id"] for c in marge["chantiers"]] == ["w7", "w6", "w5"]


def test_la_vue_ne_fait_aucune_arithmetique_sur_les_montants_de_m5():
    """Garde statique : `vue_executive.py` ne calcule rien avec un montant. Ni `Decimal`, ni `float`, ni `round`, ni
    `sum`, ni `nombres` (lecture et écriture de nombres) : la marge de M5 passe d'un fait à la réponse par `.get()`."""
    arbre = ast.parse((_SRC_M8 / "vue_executive.py").read_text(encoding="utf-8"))

    noms = {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    importes = {a.name.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.Import) for a in n.names}
    importes |= {n.module.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module}
    importes |= {a.name for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.module is None for a in n.names}

    assert not {"Decimal", "float", "round", "sum", "nombres", "decimal"} & (noms | importes)
    source = (_SRC_M8 / "vue_executive.py").read_text(encoding="utf-8")
    assert "marge_reelle_cad" in source  # le garde ne passe pas à vide : la marge y passe bien


# ---------------------------------------------------------------------------
# Le stock à commander : ce que M6 publie, et M6 seul
# ---------------------------------------------------------------------------
def test_le_stock_a_commander_est_ce_que_m6_met_a_la_file_du_proprietaire(base_avec_personnes, m6_de_test):
    m6, m5 = m6_de_test(attentes=[
        _besoin("gouttiere-alu-5po-fictif", depuis="2026-10-04T12:00:00+00:00"),
        _besoin("vis-inox-fictif", depuis="2026-10-05T12:00:00+00:00", resume="Stock bas : vis-inox-fictif (fictif)"),
    ])

    stock = _vue(_par_nom(), _ADMIN, atomique=True)["stock_a_commander"]

    assert stock["statut"] == "lu" and stock["n_articles"] == 2 and stock["reste"] == 0
    assert stock["seuils_a_configurer"] is False and "manque" not in stock
    assert stock["articles"] == [
        {"id": "besoin_commande:gouttiere-alu-5po-fictif",
         "resume": "Stock bas : gouttiere-alu-5po-fictif — 10 pi en main, sous le seuil de 150 pi (fictif)",
         "depuis": "2026-10-04T12:00:00+00:00", "action_proposee": ACTION_M6},
        {"id": "besoin_commande:vis-inox-fictif", "resume": "Stock bas : vis-inox-fictif (fictif)",
         "depuis": "2026-10-05T12:00:00+00:00", "action_proposee": ACTION_M6},
    ]
    assert m6.appels == 1 and m5.appels == 0  # M6 seul : jamais M5, ni aucun autre département


def test_les_seuils_de_reapprovisionnement_a_configurer_de_m6_sont_un_manque_dit_avec_le_texte_de_m6(
        base_avec_personnes, m6_de_test):
    resume = "Seuil de réapprovisionnement non configuré : vis-inox-fictif. Le stock bas n'est pas évalué."
    m6_de_test(attentes=[
        _besoin("gouttiere-fictif"),
        _attente("seuil_a_configurer", "seuils-reapprovisionnement", resume),
        _attente("chantier_a_reviser", "autre-chose", "un autre type d'attente : pas du stock"),
    ])

    vue = _vue(_par_nom(), _ADMIN, atomique=True)

    assert vue["stock_a_commander"]["n_articles"] == 1  # le besoin seul : ni le seuil, ni l'autre attente
    assert vue["stock_a_commander"]["seuils_a_configurer"] is True
    assert {
        "champ": "seuil_reapprovisionnement", "source": "M6 (configuration.reapprovisionnement)", "raison": resume,
    } in vue["manques"]
    assert "un autre type d'attente" not in json.dumps(vue)


def test_un_stock_que_m6_ne_signale_pas_est_zero_article_lu_pas_un_manque(base_avec_personnes, m6_de_test):
    m6_de_test(attentes=[])

    vue = _vue(_par_nom(), _ADMIN, atomique=True)

    assert vue["stock_a_commander"] == {
        "source": "M6 (attentes du propriétaire, type besoin_commande)", "statut": "lu", "n_articles": 0,
        "articles": [], "reste": 0, "seuils_a_configurer": False,
    }
    assert "stock_a_commander" not in [m["champ"] for m in vue["manques"]]


def test_la_liste_des_articles_est_plafonnee_et_le_reste_est_compte(base_avec_personnes, m6_de_test):
    m6_de_test(attentes=[_besoin(f"article-{numero}-fictif") for numero in range(1, 8)])

    stock = _vue(_par_nom(), _ADMIN, atomique=True)["stock_a_commander"]

    assert stock["n_articles"] == 7 and len(stock["articles"]) == 3 and stock["reste"] == 4


def test_m6_absent_illisible_ou_hors_transaction_est_un_manque_nomme_jamais_rien_a_commander(
        base_avec_personnes, monkeypatch, m6_de_test):
    # 1. M6 n'est pas installé sur l'instance.
    monkeypatch.setattr(m8_outils, "charger_departements", lambda: {})
    absent = _vue(_par_nom(), _ADMIN, atomique=True)
    # 2. La fonction `attentes()` de M6 échoue : le socle la saute et la dit illisible.
    m6_de_test(echec=RuntimeError("panne de M6 (fictive)"))
    illisible = _vue(_par_nom(), _ADMIN, atomique=True)
    # 3. Aucune base jointe : rien à lire.
    hors_transaction = _vue(_par_nom())

    raisons = []
    for vue in (absent, illisible, hors_transaction):
        assert vue["stock_a_commander"] == {
            "source": "M6 (attentes du propriétaire, type besoin_commande)", "statut": "manque",
            "manque": ["stock_a_commander"],
        }
        (manque,) = [m for m in vue["manques"] if m["champ"] == "stock_a_commander"]
        raisons.append(manque["raison"])
    assert raisons == [
        "m06-material-control n'est pas installé sur cette instance",
        "les attentes de m06-material-control n'ont pas pu être lues (voir le journal du moteur)",
        "aucune base jointe : les attentes de M6 ne se lisent que dans la transaction d'un outil",
    ]


# ---------------------------------------------------------------------------
# Le cash libre sans constat : la vue dit « manque » et où le lire (avec un constat : test_vue_executive_cash_libre.py)
# ---------------------------------------------------------------------------
def test_sans_constat_de_m5_le_cash_libre_est_un_manque_explicite_qui_renvoie_aux_outils_de_m5_sans_les_appeler(
        base_avec_personnes, m6_de_test):
    m6, m5 = m6_de_test()

    vue = _vue(_par_nom([_lead("L1")]), _ADMIN, atomique=True)

    assert vue["cash_libre"] == {
        "source": "M5 (m5.cash_libre_constate)", "statut": "manque", "manque": ["cash_libre"],
        "a_lire": "m5_etat_tresorerie (admin), avec la décomposition du cash libre ; "
                  "m5_constater_cash_libre (admin) le publie à M8",
    }
    (manque,) = [m for m in vue["manques"] if m["champ"] == "cash_libre"]
    assert manque["source"] == "M5 (m5.cash_libre_constate)"
    assert "M5 n'a publié aucun constat du cash libre" in manque["raison"]
    assert "ne peut ni le lire ni le recalculer" in manque["raison"]
    assert "m5_constater_cash_libre" in manque["raison"]
    assert m5.appels == 0  # M5 n'est ni lu ni appelé : `charger_outils()` de M5 lèverait


def test_sans_constat_aucun_montant_de_cash_libre_n_existe_dans_la_vue():
    vue = _vue(_par_nom(_trajet()))

    assert set(vue["cash_libre"]) == {"source", "statut", "manque", "a_lire"}
    assert "solde" not in json.dumps(vue) and "argent_disponible" not in json.dumps(vue)
    assert "cash_libre_cad" not in json.dumps(vue)


def test_sans_constat_la_date_de_l_appelant_ne_change_rien_a_la_section():
    sans_date = _vue(_par_nom(_trajet()))["cash_libre"]

    reponse = executer(_par_nom(_trajet())["m8_lire_vue_executive"], {"aujourd_hui": "2026-10-02"})

    assert reponse["ok"] is True and reponse["resultat"]["cash_libre"] == sans_date


# ---------------------------------------------------------------------------
# La borne : sous la limite du socle, ce qui ne tient pas est compté
# ---------------------------------------------------------------------------
def _remplir_gros_registres():
    """60 chantiers avec leur marge, 40 devis sans réponse : bien plus que la vue n'en peut montrer."""
    with stockage.transaction():
        chantier = stockage.maillons("m08-analytics", "faits_chantier")
        registre = stockage.maillons("m08-analytics", "faits_entonnoir")
        for numero in range(60):
            chantier.append(_wct(f"w-{numero:02d}", f"D-{numero:02d}", f"2026-08-{1 + numero % 28:02d}T14:00:00-04:00"))
            chantier.append(_marge(f"w-{numero:02d}", f"D-{numero:02d}", 1, f"{numero * 37}.25"))
        registre.append(_lead("lead-1-fictif"))
        for numero in range(40):
            depuis = f"2026-09-{1 + numero % 28:02d}T08:00:00-04:00"
            registre.append(_sans_reponse(f"DEVIS-EN-ATTENTE-{numero:02d}", depuis=depuis))
            registre.append(_envoye(f"DEVIS-EN-ATTENTE-{numero:02d}"))
        registre.append(_accepte("DEVIS-EN-ATTENTE-99"))


def test_la_vue_d_une_grosse_entreprise_tient_sous_la_limite_du_socle_et_compte_ce_qui_ne_tient_pas(
        base_avec_personnes, m6_de_test):
    longs = [
        _besoin(f"article-numero-{numero:02d}-fictif", resume="Stock bas : " + "x" * 300 + f" ({numero})")
        for numero in range(40)
    ]
    m6_de_test(attentes=longs)
    _remplir_gros_registres()
    capacites = Capacites(
        charger_departements(_RACINE_DEPARTEMENTS), stockage.transaction, filtre={"m08-analytics"}, memoire=False,
    )

    with contexte.appele_par_appareil(_ADMIN):
        reponse = capacites.appeler("m8_lire_vue_executive", {})

    assert reponse["ok"] is True and "tronque" not in reponse, reponse  # jamais coupée au milieu
    assert len(json.dumps(reponse, ensure_ascii=False)) <= jetons.LIMITE_SORTIE_DEFAUT
    vue = reponse["resultat"]
    marge, stock = vue["marge_reelle"], vue["stock_a_commander"]
    attente = vue["entonnoir"]["devis_en_attente"]["sans_reponse"]
    assert marge["n_chantiers"] == 60 and stock["n_articles"] == 40 and attente["n"] == 40  # les totaux, jamais réduits
    assert len(marge["chantiers"]) + marge["reste"] == 60
    assert len(stock["articles"]) + stock["reste"] == 40
    assert len(attente["devis"]) + attente["reste"] == 40
    assert marge["reste"] + stock["reste"] + attente["reste"] > 0  # la borne a joué : quelque chose ne tenait pas
    assert vue["entonnoir"]["mesures"] and vue["cash_libre"]["statut"] == "manque"  # l'essentiel reste en entier


def _listes(vue):
    """Le nombre d'éléments de chaque liste bornable : chantiers, articles, devis sans réponse, brouillons."""
    attente = vue["entonnoir"]["devis_en_attente"]
    return [
        len(vue["marge_reelle"]["chantiers"]), len(vue["stock_a_commander"]["articles"]),
        len(attente["sans_reponse"]["devis"]), len(attente["brouillons_en_retard"]["devis"]),
    ]


def _restes(vue):
    attente = vue["entonnoir"]["devis_en_attente"]
    return [
        vue["marge_reelle"]["reste"], vue["stock_a_commander"]["reste"], attente["sans_reponse"]["reste"],
        attente["brouillons_en_retard"]["reste"],
    ]


def test_la_borne_retire_de_la_plus_longue_liste_et_compte_chaque_retrait():
    situation = entonnoir.situation(
        [_sans_reponse(f"D{numero}") for numero in range(9)], [], entonnoir.charger_definitions(), {}
    )
    chantiers = []
    for numero in range(9):
        chantiers += [_wct(f"w{numero}", f"X{numero}"), _marge(f"w{numero}", f"X{numero}", 1, "10.00")]
    attentes = [_besoin(f"a-{numero}") for numero in range(9)]

    complete = vue_executive.assembler(situation, chantiers, attentes, None)
    assert _listes(complete) == [3, 3, 3, 0] and _restes(complete) == [6, 6, 6, 0]  # le plafond ordinaire : trois

    # Un caractère de trop : un seul élément part, le premier de la plus longue liste (à égalité, dans l'ordre).
    borne = len(json.dumps(complete, ensure_ascii=False)) - 1
    une_de_moins = vue_executive.assembler(situation, chantiers, attentes, None, budget_caracteres=borne)
    assert len(json.dumps(une_de_moins, ensure_ascii=False)) <= borne
    assert _listes(une_de_moins) == [2, 3, 3, 0] and _restes(une_de_moins) == [7, 6, 6, 0]

    # Encore un : la plus longue est maintenant celle des articles (3, contre 2 chantiers).
    borne = len(json.dumps(une_de_moins, ensure_ascii=False)) - 1
    deux_de_moins = vue_executive.assembler(situation, chantiers, attentes, None, budget_caracteres=borne)
    assert len(json.dumps(deux_de_moins, ensure_ascii=False)) <= borne
    assert _listes(deux_de_moins) == [2, 2, 3, 0] and _restes(deux_de_moins) == [7, 7, 6, 0]
    for vue in (une_de_moins, deux_de_moins):  # les totaux ne bougent jamais : seul l'affichage se réduit
        assert vue["marge_reelle"]["n_chantiers"] == 9 and vue["stock_a_commander"]["n_articles"] == 9
        assert vue["entonnoir"]["devis_en_attente"]["sans_reponse"]["n"] == 9


def test_une_vue_qui_ne_tient_pas_meme_sans_aucune_liste_est_un_refus_jamais_une_reponse_coupee():
    situation = entonnoir.situation([], [], entonnoir.charger_definitions(), {})

    with pytest.raises(ValueError, match="dépasse à elle seule la borne de 100 caractères"):
        vue_executive.assembler(situation, [], [], None, budget_caracteres=100)


def test_la_vue_du_cas_ordinaire_tient_avec_de_la_marge_sous_la_borne(base_avec_personnes, m6_de_test):
    """Un entonnoir plein, trois chantiers, trois articles : la vue tient sans rien retirer (aucun `reste`)."""
    m6_de_test(attentes=[_besoin(f"article-{numero}-fictif") for numero in range(3)])
    chantiers = []
    for numero in range(3):
        chantiers += [_wct(f"w{numero}", f"D{numero}"), _marge(f"w{numero}", f"D{numero}", 1, f"{numero}00.00")]
    faits = [*_trajet(), _lead("lead-2-fictif")]

    vue = _vue(_par_nom(faits, chantiers), _ADMIN, atomique=True)

    assert len(json.dumps(vue, ensure_ascii=False)) < m8_outils.BUDGET_SORTIE
    assert vue["marge_reelle"]["reste"] == 0 and vue["stock_a_commander"]["reste"] == 0
