"""Harnais de validation de la paie (`cas_paie.v1`) : rejeu, écart au cent par ligne, qualification à ≥ 300 cas
officiels.

HONNÊTETÉ : les « cas officiels » construits dans ce fichier sont des COUPLES FICTIFS fabriqués pour exercer la
mécanique de qualification (captures écrites dans un dossier temporaire, valeurs produites par le moteur lui-même). Ils
ne prouvent rien sur l'exactitude du moteur et n'existent que le temps du test. Le dépôt, lui, ne contient AUCUN cas
officiel : le test `test_le_depot_ne_contient_aucun_cas_officiel` le garde. Fictif (AGENTS.md).
"""

from __future__ import annotations

import copy
import hashlib
import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from m5_financecore import validation_paie as vp

FICTIF = True
_RACINE = Path(__file__).resolve().parents[1] / "validation_paie"
_DEMO = _RACINE / "cas_demonstration"
_OFFICIELS = _RACINE / "cas_officiels"


def _entrees(periode=1, salaire="1002.00", jour="2026-01-15", cumuls=None, td1="16452.00"):
    return {
        "annee": 2026,
        "date_paie": jour,
        "province": "QC",
        "frequence": "bihebdomadaire",
        "periode_annuelle": periode,
        "salaire_brut_periode": salaire,
        "credit_personnel_federal_td1": td1,
        "exemptions": {k: False for k in vp._EXEMPTIONS},
        "cumuls_avant": cumuls or {k: "0.00" for k in vp._CUMULS},
    }


def _attendu_moteur(entrees):
    from m5_financecore import impot_federal_qc_2026 as federal

    rapport, refus = federal.calculer_retenue_federale_qc_preparatoire(**vp.construire_demandes(entrees))
    assert refus is None, refus
    return vp._lignes_du_moteur(rapport)


def _cas_fictif(ident="demo-1", entrees=None, lignes=None):
    entrees = entrees or _entrees()
    lignes = lignes or _attendu_moteur(entrees)
    return {
        "id": ident,
        "nature": vp.NATURE_FICTIF,
        "entrees": entrees,
        "attendu": {"lignes": {k: {"montant": v, "outil": "aucun"} for k, v in lignes.items()}},
        "source": {"type": vp.NATURE_FICTIF, "executions": []},
        "saisie": {"auteur": "auteur.fictif", "le": "2026-11-01"},
        "revue": None,
    }


def _cas_officiel(racine, ident, entrees, lignes=None, **remplacements):
    """Un cas « officiel » FICTIF DE TEST : capture écrite sous `racine`, valeurs du moteur."""
    lignes = lignes or _attendu_moteur(entrees)
    contenu = f"capture fictive {ident}".encode()
    (racine / f"{ident}.png").write_bytes(contenu)
    cas = {
        "id": ident,
        "nature": vp.NATURE_OFFICIEL,
        "entrees": entrees,
        "attendu": {"lignes": {k: {"montant": v, "outil": "WebRAS"} for k, v in lignes.items()}},
        "source": {
            "type": "calculateur_officiel",
            "executions": [
                {
                    "outil": "WebRAS",
                    "version": "version-fictive-1",
                    "date_execution": "2026-10-30",
                    "url": "https://www.revenuquebec.ca/outil-fictif",
                    "capture": {"chemin": f"{ident}.png", "sha256": hashlib.sha256(contenu).hexdigest()},
                }
            ],
        },
        "saisie": {"auteur": "auteur.fictif", "le": "2026-11-01"},
        "revue": {"reviewer": "revue.fictive", "le": "2026-11-02"},
    }
    for cle, valeur in remplacements.items():
        cas[cle] = valeur
    return cas


def _charger(cas):
    return vp.charger_cas(contenu_octets=yaml.safe_dump({"schema": vp.SCHEMA, "cas": cas}).encode("utf-8"))


def _charger_ok(cas):
    liste, refus = _charger(cas)
    assert refus is None, refus
    return liste


def _refuse(cas, code):
    liste, refus = _charger(cas)
    assert liste is None and refus["code"] == code, (liste, refus)


def _trois_cents_entrees():
    """300 jeux d'entrées DISTINCTS (salaire et période variables)."""
    sorties = []
    for i in range(300):
        periode = 1
        salaire = f"{700 + i * 9}.{(i * 7) % 100:02d}"
        jour = (date(2026, 1, 2) + timedelta(days=i % 150)).isoformat()
        sorties.append(_entrees(periode=periode, salaire=salaire, jour=jour))
    return sorties


# --------------------------------------------------------------------------------- les cas de démonstration
def test_les_cas_de_demonstration_sont_tous_fictifs_et_se_rejouent_a_zero_ecart():
    cas = vp.charger_dossier(_DEMO)[0]
    assert len(cas) >= 15
    assert {c.nature for c in cas} == {vp.NATURE_FICTIF}
    assert all(c.source["type"] == vp.NATURE_FICTIF and c.source["executions"] == [] for c in cas)
    rapport = vp.executer_campagne(cas)
    assert rapport["totaux"]["lignes_en_ecart"] == 0 and rapport["totaux"]["moteur_refuse"] == 0
    assert all(r["statut"] == "OK" for r in rapport["cas"])
    assert rapport["totaux"]["officiels"] == 0 and rapport["statut_campagne"] == "campagne officielle : 0/300"
    # les cas couvrent des plafonds (RRQ palier 2 > 0) et la période de juillet : pas seulement le cas facile
    assert any(c.lignes["rrq_palier2"]["montant"] != "0.00" for c in cas)
    assert any(c.entrees["date_paie"] >= "2026-07-01" for c in cas)


def test_le_mode_de_qualification_refuse_les_cas_de_demonstration():
    cas = vp.charger_dossier(_DEMO)[0]
    rapport, refus = vp.qualifier_campagne(cas, racine_captures=None)
    assert rapport is None and refus["code"] == "REJ-PAIEVAL-FICTIF-REFUSE"


def test_un_seul_cas_fictif_glisse_parmi_trois_cents_officiels_fait_refuser_la_qualification(tmp_path):
    cas = _charger_ok(
        [_cas_officiel(tmp_path, f"off-{i:03d}", e) for i, e in enumerate(_trois_cents_entrees())]
        + [_cas_fictif("intrus", _entrees(salaire="777.77"))]
    )
    rapport, refus = vp.qualifier_campagne(cas, racine_captures=tmp_path)
    assert rapport is None and refus["code"] == "REJ-PAIEVAL-FICTIF-REFUSE" and "intrus" in refus["detail"]


def test_le_depot_ne_contient_aucun_cas_officiel_et_le_statut_est_zero_sur_trois_cents():
    assert [p.name for p in _OFFICIELS.iterdir() if p.suffix == ".yaml"] == []
    cas, refus = vp.charger_dossier(_OFFICIELS)
    assert refus is None and cas == []
    statut = vp.statut_campagne(cas, racine_captures=_RACINE / "captures")
    assert statut["statut"] == "campagne officielle : 0/300" and statut["qualifiee"] is False
    assert statut["refus"]["code"] == "REJ-PAIEVAL-CAMPAGNE-INSUFFISANTE"
    # aucun cas du dépôt, où qu'il soit, ne se dit officiel
    for fichier in _RACINE.rglob("*.yaml"):
        assert "nature: officiel" not in fichier.read_text(encoding="utf-8"), fichier


def test_seuils_du_harnais():
    assert vp.SEUIL_CAS_OFFICIELS == 300 and str(vp.SEUIL_ECART) == "0.00"


# ----------------------------------------------------------------------------------------- écart au cent
@pytest.mark.parametrize("delta", ["0.01", "-0.01", "5.00"])
def test_un_ecart_d_un_cent_sur_une_ligne_est_rapporte_ligne_par_ligne(delta):
    lignes = _attendu_moteur(_entrees())
    modifie = dict(lignes)
    modifie["ae_salarie"] = format(Decimal(lignes["ae_salarie"]) + Decimal(delta), ".2f")
    resultat = vp.rejouer_cas(_charger_ok([_cas_fictif("c1", lignes=modifie)])[0])
    assert resultat["statut"] == "ECART"
    ligne = resultat["lignes"]["ae_salarie"]
    assert ligne["ok"] is False and ligne["ecart_cents"] == -int(Decimal(delta) * 100)
    assert ligne["attendu"] == modifie["ae_salarie"] and ligne["obtenu"] == lignes["ae_salarie"]
    assert all(v["ok"] for k, v in resultat["lignes"].items() if k != "ae_salarie")


def test_seules_les_lignes_attendues_sont_comparees():
    lignes = {"impot_quebec": _attendu_moteur(_entrees())["impot_quebec"]}
    resultat = vp.rejouer_cas(_charger_ok([_cas_fictif("c1", lignes=lignes)])[0])
    assert resultat["statut"] == "OK" and set(resultat["lignes"]) == {"impot_quebec"}


def test_le_moteur_qui_refuse_n_est_pas_un_succes():
    e = _entrees()
    e["exemptions"]["gratif_ou_retroactif"] = True
    lignes = _attendu_moteur(_entrees())
    resultat = vp.rejouer_cas(_charger_ok([_cas_fictif("c1", entrees=e, lignes=lignes)])[0])
    assert resultat["statut"] == "MOTEUR_REFUSE" and resultat["refus"]["code"] == "REJ-PAIEVAL-MOTEUR-REFUSE"


def test_periode_hors_perimetre_du_moteur_est_un_refus_moteur_pas_une_valeur():
    e = _entrees(periode=1, jour="2026-09-01")  # P1 au-delà du 30 juin : hors périmètre du moteur
    resultat = vp.rejouer_cas(_charger_ok([_cas_fictif("c1", entrees=e, lignes={"impot_quebec": "1.00"})])[0])
    assert resultat["statut"] == "MOTEUR_REFUSE" and resultat["lignes"] == {}


# ----------------------------------------------------------------------------- le format est strict
def test_le_chargeur_refuse_ce_qui_est_mal_forme():
    base = _cas_fictif()
    mauvais = {
        "cle_inconnue": lambda c: c.update(extra=1),
        "nature_inconnue": lambda c: c.update(nature="presque_officiel"),
        "type_contredit": lambda c: c["source"].update(type="calculateur_officiel"),
        "ligne_inconnue": lambda c: c["attendu"]["lignes"].update(csa={"montant": "1.00", "outil": "aucun"}),
        "montant_sans_decimales": lambda c: c["attendu"]["lignes"]["rrq_palier1"].update(montant="54.6"),
        "montant_virgule": lambda c: c["attendu"]["lignes"]["rrq_palier1"].update(montant="54,65"),
        "lignes_vides": lambda c: c["attendu"].update(lignes={}),
        "exemption_manquante": lambda c: c["entrees"]["exemptions"].pop("exonere"),
        "exemption_non_booleenne": lambda c: c["entrees"]["exemptions"].update(exonere="non"),
        "cumul_manquant": lambda c: c["entrees"]["cumuls_avant"].pop("ae_salarie"),
        "salaire_float": lambda c: c["entrees"].update(salaire_brut_periode=1002.0),
        "id_invalide": lambda c: c.update(id="Majuscule Espace"),
        "auteur_vide": lambda c: c["saisie"].update(auteur=""),
    }
    for nom, mutation in mauvais.items():
        cas = copy.deepcopy(base)
        mutation(cas)
        liste, refus = _charger([cas])
        assert liste is None and refus["code"] == "REJ-PAIEVAL-CAS-INVALIDE", nom


def test_doublons_d_identifiant_et_d_entrees_sont_refuses_pour_ne_pas_gonfler_le_compte():
    a = _cas_fictif("a")
    _refuse([a, copy.deepcopy(a)], "REJ-PAIEVAL-DOUBLON")
    b = _cas_fictif("b")  # mêmes entrées, autre identifiant
    _refuse([a, b], "REJ-PAIEVAL-DOUBLON")


def test_fichier_illisible_schema_inconnu_et_cle_yaml_dupliquee_sont_refuses():
    for octets in (b"\xff\xfe", b"cas: [", b"schema: autre\ncas: []\n", b"schema: cas_paie.v1\ncas: []\ncas: []\n"):
        assert vp.charger_cas(contenu_octets=octets)[1]["code"] == "REJ-PAIEVAL-FORMAT-INVALIDE"
    assert vp.charger_cas(Path("/inexistant/cas.yaml"))[1]["code"] == "REJ-PAIEVAL-FORMAT-INVALIDE"
    assert vp.charger_cas()[1]["code"] == "REJ-PAIEVAL-FORMAT-INVALIDE"


# ----------------------------------------------------------------------------- la qualification
@pytest.fixture(scope="module")
def trois_cents(tmp_path_factory):
    racine = tmp_path_factory.mktemp("captures")
    cas = [_cas_officiel(racine, f"off-{i:03d}", e) for i, e in enumerate(_trois_cents_entrees())]
    return racine, cas


def test_trois_cents_cas_officiels_verifies_a_zero_ecart_qualifient_la_campagne(trois_cents):
    racine, cas = trois_cents
    rapport, refus = vp.qualifier_campagne(_charger_ok(cas), racine_captures=racine)
    assert refus is None and rapport["qualifiee"] is True
    assert rapport["statut_campagne"] == "campagne officielle : 300/300"
    # même qualifiée, la campagne ne qualifie PAS les règles pour la paie
    assert rapport["moteur"]["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"


def test_deux_cent_quatre_vingt_dix_neuf_cas_ne_qualifient_pas(trois_cents):
    racine, cas = trois_cents
    rapport, refus = vp.qualifier_campagne(_charger_ok(cas[:-1]), racine_captures=racine)
    assert rapport is None and refus["code"] == "REJ-PAIEVAL-CAMPAGNE-INSUFFISANTE" and "299/300" in refus["detail"]


def test_un_seul_cent_d_ecart_dans_trois_cents_cas_refuse_la_campagne(trois_cents):
    racine, cas = trois_cents
    cas = copy.deepcopy(cas)
    ligne = cas[150]["attendu"]["lignes"]["impot_federal"]
    ligne["montant"] = format(Decimal(ligne["montant"]) + Decimal("0.01"), ".2f")
    rapport, refus = vp.qualifier_campagne(_charger_ok(cas), racine_captures=racine)
    assert rapport is None and refus["code"] == "REJ-PAIEVAL-ECART" and "off-150" in refus["detail"]


def _qualifie_un_cas_modifie(trois_cents, mutation, racine_captures=None):
    racine, cas = trois_cents
    cas = copy.deepcopy(cas)
    mutation(cas[10], racine)
    return vp.qualifier_campagne(
        _charger_ok(cas), racine_captures=racine if racine_captures is None else racine_captures
    )


@pytest.mark.parametrize(
    ("nom", "mutation"),
    [
        ("sans_execution", lambda c, r: c["source"].update(executions=[])),
        ("outil_inconnu", lambda c, r: c["source"]["executions"][0].update(outil="Excel-de-Marc")),
        ("version_vide", lambda c, r: c["source"]["executions"][0].update(version=" ")),
        ("date_apres_saisie", lambda c, r: c["source"]["executions"][0].update(date_execution="2026-12-31")),
        ("date_invalide", lambda c, r: c["source"]["executions"][0].update(date_execution="2026-02-30")),
        ("http", lambda c, r: c["source"]["executions"][0].update(url="http://www.revenuquebec.ca/x")),
        ("hote_pirate", lambda c, r: c["source"]["executions"][0].update(url="https://pirate.test/revenuquebec.ca")),
        ("hote_sosie", lambda c, r: c["source"]["executions"][0].update(url="https://revenuquebec.ca.pirate.test/x")),
        ("hote_suffixe_colle", lambda c, r: c["source"]["executions"][0].update(url="https://faux-revenuquebec.ca/x")),
        ("sha_divergent", lambda c, r: c["source"]["executions"][0]["capture"].update(sha256="0" * 64)),
        ("sha_mal_forme", lambda c, r: c["source"]["executions"][0]["capture"].update(sha256="ABC")),
        ("capture_absente", lambda c, r: c["source"]["executions"][0]["capture"].update(chemin="n-existe-pas.png")),
        ("chemin_parent", lambda c, r: c["source"]["executions"][0]["capture"].update(chemin="../etc/passwd")),
        ("chemin_absolu", lambda c, r: c["source"]["executions"][0]["capture"].update(chemin="/etc/passwd")),
        ("chemin_antislash", lambda c, r: c["source"]["executions"][0]["capture"].update(chemin="a\\b.png")),
        ("sans_reviseur", lambda c, r: c.update(revue=None)),
        ("auteur_est_reviseur", lambda c, r: c["revue"].update(reviewer="Auteur.Fictif")),
        ("revue_avant_saisie", lambda c, r: c["revue"].update(le="2026-10-01")),
        ("ligne_d_un_autre_outil", lambda c, r: c["attendu"]["lignes"]["impot_federal"].update(outil="PDOC")),
    ],
)
def test_une_provenance_non_verifiee_refuse_la_qualification(trois_cents, nom, mutation):
    rapport, refus = _qualifie_un_cas_modifie(trois_cents, mutation)
    assert rapport is None and refus["code"] == "REJ-PAIEVAL-PROVENANCE-NON-VERIFIEE", (nom, refus)
    assert "off-010" in refus["detail"]


def test_capture_hors_racine_via_lien_symbolique_est_refusee(trois_cents, tmp_path):
    racine, cas = trois_cents
    exterieur = tmp_path / "exterieur.png"
    exterieur.write_bytes(b"hors racine")
    dossier = tmp_path / "captures"
    dossier.mkdir()
    for c in cas:
        (dossier / f"{c['id']}.png").write_bytes((racine / f"{c['id']}.png").read_bytes())
    os.remove(dossier / "off-010.png")
    os.symlink(exterieur, dossier / "off-010.png")
    cas = copy.deepcopy(cas)
    cas[10]["source"]["executions"][0]["capture"]["sha256"] = hashlib.sha256(b"hors racine").hexdigest()
    _, refus = vp.qualifier_campagne(_charger_ok(cas), racine_captures=dossier)
    assert refus["code"] == "REJ-PAIEVAL-PROVENANCE-NON-VERIFIEE" and "racine" in refus["detail"]


def test_sans_racine_de_captures_aucune_provenance_n_est_verifiee(trois_cents):
    racine, cas = trois_cents
    _, refus = vp.qualifier_campagne(_charger_ok(cas), racine_captures=None)
    assert refus["code"] == "REJ-PAIEVAL-PROVENANCE-NON-VERIFIEE"


def test_un_cas_officiel_que_le_moteur_refuse_ferme_la_qualification(trois_cents):
    racine, cas = trois_cents
    cas = copy.deepcopy(cas)
    cas[3]["entrees"]["exemptions"]["exemption_speciale"] = True
    _, refus = vp.qualifier_campagne(_charger_ok(cas), racine_captures=racine)
    assert refus["code"] == "REJ-PAIEVAL-MOTEUR-REFUSE"


def test_le_statut_d_un_dossier_de_cent_cas_officiels_verifies_dit_cent_sur_trois_cents(trois_cents):
    racine, cas = trois_cents
    statut = vp.statut_campagne(_charger_ok(cas[:100]), racine_captures=racine)
    assert statut["statut"] == "campagne officielle : 100/300" and statut["qualifiee"] is False
    assert statut["cas_officiels_qualifiants"] == 100


def test_un_cas_officiel_sans_provenance_ne_compte_pas_dans_le_statut(trois_cents):
    racine, cas = trois_cents
    cas = copy.deepcopy(cas[:5])
    cas[0]["revue"] = None
    statut = vp.statut_campagne(_charger_ok(cas), racine_captures=racine)
    assert statut["statut"] == "campagne officielle : 4/300" and statut["cas_officiels"] == 5


def test_dossier_de_cas_charge_plusieurs_fichiers_et_refuse_un_doublon_inter_fichiers(tmp_path):
    (tmp_path / "a.yaml").write_text(
        yaml.safe_dump({"schema": vp.SCHEMA, "cas": [_cas_fictif("x1")]}), encoding="utf-8"
    )
    (tmp_path / "b.yaml").write_text(
        yaml.safe_dump({"schema": vp.SCHEMA, "cas": [_cas_fictif("x1", _entrees(salaire="900.00"))]}), encoding="utf-8"
    )
    cas, refus = vp.charger_dossier(tmp_path)
    assert cas is None and refus["code"] == "REJ-PAIEVAL-DOUBLON"
    (tmp_path / "b.yaml").write_text(
        yaml.safe_dump({"schema": vp.SCHEMA, "cas": [_cas_fictif("x2", _entrees(salaire="900.00"))]}), encoding="utf-8"
    )
    assert len(vp.charger_dossier(tmp_path)[0]) == 2
