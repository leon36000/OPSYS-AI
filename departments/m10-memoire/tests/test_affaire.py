"""PLAN T4.18-b : la forme d'une affaire, commune au core et à M10.

Une affaire s'identifie par le `lead_id` de son lead, ou, pour le chantier suivant d'un client déjà connu, par
l'opportunité que M2 ouvre : `<lead d'origine>~opp~<wct_id>`. La forme est bornée (64 + 5 + 128 caractères) et ne
porte que des lettres, des chiffres et `._:-` : ni espace, ni retour à la ligne, ni caractère de contrôle.

La liste de cas est celle du core (`core/src/context-engine/opsys-contexte.affaires.json`), que le test du core
(`opsys-contexte-affaire.test.ts`, vitest) lit aussi : les deux côtés testent les MÊMES cas. Ici, chaque cas passe
par TOUTES les entrées de M10 qui prennent une affaire (lien de session, dépôt POSTFLIGHT, paquet, faits de l'amont),
pour qu'aucune ne garde sa propre forme. Données fictives (`fictif: true`).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from m10_memoire import affaire, etapes, faits_candidats, liaison, paquets, registre

FICTIF = True
HORODATAGE = "2026-09-16T08:00:00-04:00"
CAS = json.loads(
    (Path(__file__).resolve().parents[3] / "core" / "src" / "context-engine" / "opsys-contexte.affaires.json")
    .read_text(encoding="utf-8")
)
ACCEPTEES = CAS["acceptees"]
REFUSEES = CAS["refusees"]
FORME_ATTENDUE = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}(?:~opp~[A-Za-z0-9][A-Za-z0-9._:-]{0,127})?$"


def _titre(cas):
    return cas["note"][:60]


def _fait_depose():
    return [{"cle": "cle-t418b-1", "outil": "m3_estimer_projet", "resultat": "ok", "code": None}]


def _charge_client_associe(lead_id):
    return {"lead_id": lead_id, "client_id": "client-fictif-1", "horodatage_association": HORODATAGE}


def _charge_lead_qualifie(lead_id):
    return {
        "lead": {"lead_id": lead_id, "service": "gouttieres", "canal": "texte", "urgence_declaree": False},
        "horodatage": HORODATAGE,
    }


# -- La liste partagée ----------------------------------------------------------------------------


def test_la_liste_de_cas_est_fictive_et_couvre_les_bornes_des_deux_formes():
    assert CAS["fictif"] is True and FICTIF is True
    identifiants = [cas["id"] for cas in ACCEPTEES + REFUSEES]
    assert len(identifiants) == len(set(identifiants)), "un cas en double dit deux fois la même chose"
    assert {cas["genre"] for cas in ACCEPTEES} == {affaire.GENRE_LEAD, affaire.GENRE_OPPORTUNITE}
    assert len(ACCEPTEES) >= 10 and len(REFUSEES) >= 50
    longueurs_acceptees = {len(cas["id"]) for cas in ACCEPTEES}
    assert {1, affaire.LONGUEUR_LEAD_MAX, affaire.LONGUEUR_AFFAIRE_MAX} <= longueurs_acceptees
    lead_trop_long = "a" * (affaire.LONGUEUR_LEAD_MAX + 1)
    wct_trop_long = "b" * (affaire.LONGUEUR_WCT_MAX + 1)
    refuses = {cas["id"] for cas in REFUSEES}
    assert lead_trop_long in refuses
    assert any(identifiant.endswith(wct_trop_long) for identifiant in refuses)
    assert any(identifiant.startswith(lead_trop_long + affaire.SEPARATEUR_OPPORTUNITE) for identifiant in refuses)


def test_les_limites_de_la_liste_sont_celles_du_code():
    assert CAS["limites"] == {
        "lead": affaire.LONGUEUR_LEAD_MAX,
        "wct": affaire.LONGUEUR_WCT_MAX,
        "separateur": len(affaire.SEPARATEUR_OPPORTUNITE),
        "affaire": affaire.LONGUEUR_AFFAIRE_MAX,
    }
    assert affaire.LONGUEUR_AFFAIRE_MAX == 197  # 64 + 5 + 128


def test_la_forme_est_celle_que_le_core_recopie_mot_pour_mot():
    """Changer la forme est un choix des DEUX côtés : ce test, `AFFAIRE_ID` et `AFFAIRE_LINE` du core, la liste."""
    assert affaire.FORME_AFFAIRE.pattern == FORME_ATTENDUE
    assert affaire.FORME_LEAD.pattern == r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
    assert affaire.SEPARATEUR_OPPORTUNITE == "~opp~"


# -- Chaque cas, par chaque entrée de M10 -------------------------------------------------------------


@pytest.mark.parametrize("cas", ACCEPTEES, ids=_titre)
def test_une_affaire_admise_l_est_partout_dans_m10(cas):
    identifiant = cas["id"]

    assert affaire.valide(identifiant) is True
    assert affaire.genre(identifiant) == cas["genre"]
    assert affaire.est_opportunite(identifiant) is (cas["genre"] == affaire.GENRE_OPPORTUNITE)
    assert liaison.affaire_valide(identifiant) is True
    depot, verdict = faits_candidats.deposer_faits_candidats(
        identifiant, "m03-estimation", _fait_depose(), HORODATAGE, registre.Registre()
    )
    assert verdict is None and depot["ecrits"] == 1
    paquet = paquets.assembler_paquet_contexte(identifiant, HORODATAGE, registre.Registre(), registre.Registre())
    assert paquet["affaire_id"] == identifiant
    fait = etapes.etape(etapes.TYPE_CLIENT_ASSOCIE).extraire(_charge_client_associe(identifiant))
    assert fait["lead_id"] == identifiant


@pytest.mark.parametrize("cas", [c for c in ACCEPTEES if c["genre"] == affaire.GENRE_LEAD], ids=_titre)
def test_m1_publie_un_lead_jamais_une_opportunite_et_la_forme_du_lead_est_admise(cas):
    assert affaire.est_lead(cas["id"]) is True
    assert etapes.etape(etapes.TYPE_LEAD_QUALIFIE).extraire(_charge_lead_qualifie(cas["id"]))["lead_id"] == cas["id"]


@pytest.mark.parametrize("cas", [c for c in ACCEPTEES if c["genre"] == affaire.GENRE_OPPORTUNITE], ids=_titre)
def test_une_opportunite_n_est_pas_un_lead_de_m1(cas):
    assert affaire.est_lead(cas["id"]) is False
    with pytest.raises(etapes.ChampRefuse) as refus:
        etapes.etape(etapes.TYPE_LEAD_QUALIFIE).extraire(_charge_lead_qualifie(cas["id"]))
    assert refus.value.code == etapes.REJ_AMONT_CHAMP_INVALIDE and refus.value.detail == "lead/lead_id"


@pytest.mark.parametrize("cas", REFUSEES, ids=_titre)
def test_une_affaire_refusee_l_est_partout_dans_m10_sans_rien_ecrire(cas):
    identifiant = cas["id"]

    assert affaire.valide(identifiant) is False
    assert affaire.genre(identifiant) is None
    assert affaire.est_opportunite(identifiant) is False
    assert affaire.est_lead(identifiant) is False
    assert liaison.affaire_valide(identifiant) is False
    ecrits = registre.Registre()
    depot, verdict = faits_candidats.deposer_faits_candidats(
        identifiant, "m03-estimation", _fait_depose(), HORODATAGE, ecrits
    )
    assert depot is None and verdict == faits_candidats.REJ_CANDIDAT_AFFAIRE_INVALIDE
    assert ecrits.lire() == []
    with pytest.raises(ValueError, match="affaire_id"):
        paquets.assembler_paquet_contexte(identifiant, HORODATAGE, registre.Registre(), registre.Registre())
    with pytest.raises(etapes.ChampRefuse) as refus:
        etapes.etape(etapes.TYPE_CLIENT_ASSOCIE).extraire(_charge_client_associe(identifiant))
    assert refus.value.code == etapes.REJ_AMONT_CHAMP_INVALIDE
    assert refus.value.detail == "lead_id"  # le CHAMP, jamais la valeur (qui pourrait être une donnée personnelle)


@pytest.mark.parametrize("valeur", [None, 12, 1.5, True, b"LEAD-1", ["LEAD-1"], {"lead_id": "LEAD-1"}])
def test_ce_qui_n_est_pas_un_texte_n_est_jamais_une_affaire(valeur):
    assert affaire.valide(valeur) is False
    assert affaire.est_lead(valeur) is False
    assert affaire.est_opportunite(valeur) is False
    assert affaire.genre(valeur) is None
    assert liaison.affaire_valide(valeur) is False


def test_les_bornes_exactes_de_chaque_morceau():
    lead, wct = "a" * affaire.LONGUEUR_LEAD_MAX, "b" * affaire.LONGUEUR_WCT_MAX
    sep = affaire.SEPARATEUR_OPPORTUNITE

    assert affaire.valide(lead) and affaire.valide(lead + sep + wct)
    assert len(lead + sep + wct) == affaire.LONGUEUR_AFFAIRE_MAX
    assert not affaire.valide(lead + "a") and not affaire.valide(lead + "a" + sep + wct)
    assert not affaire.valide(lead + sep + wct + "b")
    assert affaire.valide("a" + sep + "b") and not affaire.valide("a" + sep)


def test_un_retour_a_la_ligne_final_ne_passe_pas_meme_si_le_motif_seul_l_accepterait():
    """`$` accepte un retour à la ligne final avec `match` : c'est `fullmatch` qui ferme cette porte."""
    assert affaire.FORME_AFFAIRE.match("LEAD-1\n") is not None
    assert affaire.valide("LEAD-1\n") is False
    assert affaire.FORME_LEAD.match("LEAD-1\n") is not None
    assert affaire.est_lead("LEAD-1\n") is False


def test_le_genre_se_lit_de_la_forme_seule():
    assert affaire.genre("LEAD-1") == affaire.GENRE_LEAD
    assert affaire.genre("LEAD-1~opp~wct-9") == affaire.GENRE_OPPORTUNITE
    assert affaire.genre("LEAD-1~opp~") is None


def test_le_module_reste_pur_aucun_import_d_opsys():
    """DA-M10-08 : seul `outils.py` touche `opsys`."""
    arbre = ast.parse(Path(affaire.__file__).read_text(encoding="utf-8"))
    importes = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes += [alias.name for alias in noeud.names]
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0:
            importes.append(noeud.module or "")
    assert set(importes) <= {"__future__", "re", "typing"}
