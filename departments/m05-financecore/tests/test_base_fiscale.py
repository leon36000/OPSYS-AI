"""Base de règles fiscales versionnée (`docs/architecture/BASE-FISCALE.md`) : chargeur strict, résolution à une
date, deux modes.

Tout est fictif (AGENTS.md) : les réviseurs « marie.fictive » et « jean.fictif » n'existent pas ; les valeurs des bases
construites ici sont arbitraires. La base RÉELLE du dépôt (`contracts/regles_fiscales.v1.yaml`) n'a aucun réviseur :
elle
est entièrement `brouillon`, et les tests le disent.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from m5_financecore import base_fiscale as bf
from m5_financecore import taux_fiscaux, taxes

FICTIF = True
_CHEMIN_REEL = Path(__file__).resolve().parents[1] / "contracts" / "regles_fiscales.v1.yaml"
_CHEMIN_TAUX = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"
SRC_OK = {
    "organisme": "Organisme fictif",
    "titre": "Document fictif 2026",
    "url": "https://exemple.test/doc",
    "consulte_le": "2026-10-01",
}


def _param(
    identifiant="qc.test.taux",
    valeur="0.05",
    debut="2026-01-01",
    fin="2026-12-31",
    unite="ratio",
    revueurs=("marie.fictive", "jean.fictif"),
    source=None,
    saisie_par="saisie.fictive",
    **extra,
):
    p = {
        "id": identifiant,
        "juridiction": "QC",
        "libelle": "Paramètre fictif",
        "valeur": valeur,
        "unite": unite,
        "effet": {"debut": debut, "fin": fin},
        "sources": [dict(source or SRC_OK)],
        "saisie": {"par": saisie_par, "le": "2026-10-02"},
        "revues": [],
        "statut": "brouillon",
        "empreinte": "x",
    }
    p.update(extra)
    p["empreinte"] = bf.empreinte_parametre(p)
    p["revues"] = [
        {"reviewer": r, "le": "2026-10-03", "decision": "approuve", "empreinte": p["empreinte"]} for r in revueurs
    ]
    p["statut"] = {0: "brouillon", 1: "revu_1"}.get(len(revueurs), "approuve")
    return p


def _base(*params):
    return {"schema": bf.SCHEMA, "parametres": list(params)}


def _charger(contenu):
    return bf.charger_base(contenu_octets=yaml.safe_dump(contenu, allow_unicode=True).encode("utf-8"))


def _refus(contenu, code):
    base, verdict = _charger(contenu)
    assert base is None and verdict is not None, "le chargeur aurait dû refuser"
    assert verdict["code"] == code, verdict
    return verdict


def _ok(contenu):
    base, verdict = _charger(contenu)
    assert verdict is None, verdict
    return base


# ------------------------------------------------------------------------ la base réelle du dépôt
def test_la_base_reelle_se_charge_et_aucune_valeur_n_est_approuvee():
    base, verdict = bf.charger_base(_CHEMIN_REEL)
    assert verdict is None, verdict
    resume = bf.resume_base(base)
    assert resume["parametres_renseignes"] > 50
    assert resume["par_statut"]["approuve"] == 0 and resume["par_statut"]["revu_1"] == 0
    assert resume["non_renseignes"], "les paramètres que le dépôt ne porte pas doivent être listés"
    assert all(ligne["source_officielle_requise"] for ligne in resume["non_renseignes"])


def test_la_base_reelle_refuse_tout_en_mode_officiel_et_sert_en_mode_essai_marque():
    base, _ = bf.charger_base(_CHEMIN_REEL)
    regle, verdict = bf.resoudre(base, "fed.tps.taux", "2026-06-15", mode=bf.MODE_OFFICIEL)
    assert regle is None and verdict["code"] == "REJ-BASEFISC-NON-APPROUVE"
    regle, verdict = bf.resoudre(base, "fed.tps.taux", "2026-06-15", mode=bf.MODE_ESSAI)
    assert verdict is None and regle["valeur"] == Decimal("0.05")
    assert regle["essai"] is True and regle["mode"] == "essai" and "ESSAI" in regle["avertissement"]


def test_un_parametre_non_renseigne_est_refuse_dans_les_deux_modes_jamais_une_valeur_par_defaut():
    base, _ = bf.charger_base(_CHEMIN_REEL)
    ligne = bf.resume_base(base)["non_renseignes"][0]
    for mode in (bf.MODE_OFFICIEL, bf.MODE_ESSAI):
        regle, verdict = bf.resoudre(base, ligne["identifiant"], "2026-06-15", mode=mode)
        assert regle is None and verdict["code"] == "REJ-BASEFISC-NON-RENSEIGNE"


def test_modifier_une_valeur_de_la_base_reelle_sans_sceller_est_detecte():
    texte = _CHEMIN_REEL.read_text(encoding="utf-8")
    assert "valeur: '0.09975'" in texte
    base, verdict = bf.charger_base(
        contenu_octets=texte.replace("valeur: '0.09975'", "valeur: '0.10975'", 1).encode("utf-8")
    )
    assert base is None and verdict["code"] == "REJ-BASEFISC-EMPREINTE-DIVERGENTE"
    assert "qc.tvq.taux" in verdict["detail"]


# --------------------------------------------------------------------------- résolution à la date D
def _deux_versions():
    return _base(
        _param(valeur="0.05", debut="2026-01-01", fin="2026-06-30"),
        _param(valeur="0.06", debut="2026-07-01", fin="2026-12-31"),
    )


def test_resolution_a_la_date_inclut_les_bornes_et_choisit_la_bonne_version():
    base = _ok(_deux_versions())
    for jour, attendu in [
        ("2026-01-01", "0.05"),
        ("2026-06-30", "0.05"),
        ("2026-07-01", "0.06"),
        ("2026-12-31", "0.06"),
    ]:
        regle, verdict = bf.resoudre(base, "qc.test.taux", jour, mode=bf.MODE_OFFICIEL)
        assert verdict is None and regle["valeur"] == Decimal(attendu), (jour, verdict)
        assert regle["essai"] is False and regle["mode"] == "officiel" and regle["statut_revue"] == "approuve"


def test_hors_couverture_est_un_refus_pas_la_derniere_valeur_connue():
    base = _ok(_deux_versions())
    for jour in ("2025-12-31", "2027-01-01"):
        regle, verdict = bf.resoudre(base, "qc.test.taux", jour, mode=bf.MODE_ESSAI)
        assert regle is None and verdict["code"] == "REJ-BASEFISC-HORS-COUVERTURE"


def test_parametre_inconnu_date_invalide_et_mode_invalide_sont_refuses():
    base = _ok(_deux_versions())
    assert (
        bf.resoudre(base, "qc.inconnu.taux", "2026-06-15", mode="essai")[1]["code"] == "REJ-BASEFISC-PARAMETRE-INCONNU"
    )
    for jour in ("2026-02-30", "2026-6-1", "", None, 20260615, "2026-06-15T00:00:00"):
        assert bf.resoudre(base, "qc.test.taux", jour, mode="essai")[1]["code"] == "REJ-BASEFISC-DATE-INVALIDE", jour
    for mode in (None, "", "Officiel", "OFFICIEL", "test", True):
        assert bf.resoudre(base, "qc.test.taux", "2026-06-15", mode=mode)[1]["code"] == "REJ-BASEFISC-MODE-INVALIDE"


def test_version_ouverte_sans_fin_vaut_jusqu_a_nouvel_ordre_mais_pas_avant_son_debut():
    base = _ok(_base(_param(fin=None)))
    assert bf.resoudre(base, "qc.test.taux", "2040-05-05", mode="officiel")[1] is None
    assert bf.resoudre(base, "qc.test.taux", "2025-12-31", mode="officiel")[1]["code"] == "REJ-BASEFISC-HORS-COUVERTURE"


# ------------------------------------------------------------------------------- les deux modes
@pytest.mark.parametrize(("reviseurs", "statut"), [((), "brouillon"), (("marie.fictive",), "revu_1")])
def test_mode_officiel_refuse_brouillon_et_revu_1_mode_essai_les_sert_en_les_marquant(reviseurs, statut):
    base = _ok(_base(_param(revueurs=reviseurs)))
    regle, verdict = bf.resoudre(base, "qc.test.taux", "2026-03-01", mode=bf.MODE_OFFICIEL)
    assert regle is None and verdict["code"] == "REJ-BASEFISC-NON-APPROUVE"
    regle, verdict = bf.resoudre(base, "qc.test.taux", "2026-03-01", mode=bf.MODE_ESSAI)
    assert verdict is None and regle["statut_revue"] == statut and regle["essai"] is True


def test_deux_reviseurs_distincts_donnent_approuve_et_le_mode_officiel_sert():
    base = _ok(_base(_param()))
    regle, verdict = bf.resoudre(base, "qc.test.taux", "2026-03-01", mode=bf.MODE_OFFICIEL)
    assert verdict is None and regle["essai"] is False and "avertissement" not in regle


def test_le_recu_porte_le_mode_les_empreintes_et_la_mention():
    base = _ok(_base(_param()))
    regle, _ = bf.resoudre(base, "qc.test.taux", "2026-03-01", mode="essai")
    marque = bf.marquage_recu([regle], "essai")
    assert marque["mode"] == "essai" and marque["essai"] is True and "ESSAI" in marque["avertissement"]
    assert marque["parametres"][0]["empreinte"] == regle["empreinte"]
    recu = bf.recu_regle(regle)
    assert recu["valeur"] == "0.05" and isinstance(recu["valeur"], str)
    assert recu["mention_comptable"].startswith("À valider auprès d'un comptable (CPA)")


# ------------------------------------------------------------------ le chargeur refuse (strict)
def test_trou_de_dates_est_refuse():
    _refus(
        _base(_param(debut="2026-01-01", fin="2026-06-30"), _param(debut="2026-07-02", fin="2026-12-31")),
        "REJ-BASEFISC-TROU-DE-DATES",
    )


def test_chevauchement_est_refuse_meme_d_un_seul_jour():
    _refus(
        _base(_param(debut="2026-01-01", fin="2026-07-01"), _param(debut="2026-07-01", fin="2026-12-31")),
        "REJ-BASEFISC-CHEVAUCHEMENT",
    )


def test_version_apres_une_version_ouverte_est_un_chevauchement():
    _refus(
        _base(_param(debut="2026-01-01", fin=None), _param(debut="2027-01-01", fin="2027-12-31")),
        "REJ-BASEFISC-CHEVAUCHEMENT",
    )


def test_deux_versions_identiques_sont_un_chevauchement_pas_un_doublon_silencieux():
    _refus(_base(_param(), _param(valeur="0.07")), "REJ-BASEFISC-CHEVAUCHEMENT")


def test_parametre_sans_source_est_refuse():
    p = _param()
    p["sources"] = []
    p["empreinte"] = bf.empreinte_parametre(p)
    _refus(_base(p), "REJ-BASEFISC-SOURCE-ABSENTE")


@pytest.mark.parametrize(
    "source",
    [
        {"organisme": "", "titre": "t", "url": None, "consulte_le": None},
        {"organisme": "o", "titre": "  ", "url": None, "consulte_le": None},
        {"organisme": "o", "titre": "t"},
    ],
)
def test_source_sans_organisme_ou_titre_ou_cles_explicites_est_refusee(source):
    p = _param(revueurs=(), source=source)
    code = "REJ-BASEFISC-SOURCE-INCOMPLETE" if "url" in source else "REJ-BASEFISC-SCHEMA-INVALIDE"
    _refus(_base(p), code)


def test_un_brouillon_peut_avoir_une_source_sans_url_mais_pas_une_valeur_revue():
    brouillon = _param(revueurs=(), source={"organisme": "o", "titre": "t", "url": None, "consulte_le": None})
    assert _ok(_base(brouillon)) is not None
    revu = _param(
        revueurs=("marie.fictive",), source={"organisme": "o", "titre": "t", "url": None, "consulte_le": None}
    )
    _refus(_base(revu), "REJ-BASEFISC-SOURCE-INCOMPLETE")
    http = _param(revueurs=("marie.fictive",), source={**SRC_OK, "url": "http://exemple.test/doc"})
    _refus(_base(http), "REJ-BASEFISC-SOURCE-INCOMPLETE")


@pytest.mark.parametrize(
    "valeur", ["0,05", " 0.05", "0.05 ", "1e-2", "NaN", "Infinity", "", "+0.05", ".05", "5.", "0x1"]
)
def test_valeur_non_canonique_est_refusee(valeur):
    _refus(_base(_param(valeur=valeur, revueurs=())), "REJ-BASEFISC-VALEUR-INVALIDE")


@pytest.mark.parametrize("valeur", [0.05, 5, True, ["0.05"]])
def test_valeur_non_texte_est_refusee(valeur):
    p = _param(revueurs=())
    p["valeur"] = valeur
    p["empreinte"] = "x"
    code = _charger(_base(p))[1]["code"]
    assert code in {"REJ-BASEFISC-VALEUR-INVALIDE", "REJ-BASEFISC-SCHEMA-INVALIDE"}


def test_ratio_hors_de_zero_un_et_unite_inconnue_sont_refuses():
    _refus(_base(_param(valeur="1.5", revueurs=())), "REJ-BASEFISC-VALEUR-INVALIDE")
    _refus(_base(_param(valeur="-0.1", revueurs=())), "REJ-BASEFISC-VALEUR-INVALIDE")
    _refus(_base(_param(unite="dollars", revueurs=())), "REJ-BASEFISC-SCHEMA-INVALIDE")
    _refus(_base(_param(unite="CAD", valeur="-5.00", revueurs=())), "REJ-BASEFISC-VALEUR-INVALIDE")


@pytest.mark.parametrize(
    ("debut", "fin"),
    [("2026-02-30", "2026-12-31"), ("2026-1-1", "2026-12-31"), ("2026-12-31", "2026-01-01"), ("2026-01-01", "demain")],
)
def test_dates_invalides_ou_inversees_sont_refusees(debut, fin):
    _refus(_base(_param(debut=debut, fin=fin, revueurs=())), "REJ-BASEFISC-DATE-INVALIDE")


def test_cle_inconnue_schema_inconnu_et_juridiction_inconnue_sont_refuses():
    p = _param(revueurs=())
    p["secret"] = "x"
    _refus(_base(p), "REJ-BASEFISC-SCHEMA-INVALIDE")
    _refus({"schema": "autre/v9", "parametres": []}, "REJ-BASEFISC-SCHEMA-INVALIDE")
    q = _param(revueurs=())
    q["juridiction"] = "ON"
    q["empreinte"] = bf.empreinte_parametre(q)
    _refus(_base(q), "REJ-BASEFISC-SCHEMA-INVALIDE")
    _refus({"schema": bf.SCHEMA, "parametres": [], "extra": 1}, "REJ-BASEFISC-SCHEMA-INVALIDE")


def test_yaml_avec_cle_dupliquee_est_refuse_pas_la_derniere_gagne():
    texte = "schema: opsys.regles-fiscales/v1\nparametres: []\nparametres: []\n"
    _, verdict = bf.charger_base(contenu_octets=texte.encode("utf-8"))
    assert verdict["code"] == "REJ-BASEFISC-FORMAT-INVALIDE"


def test_octets_non_utf8_et_fichier_trop_gros_et_yaml_casse_sont_refuses():
    for octets in (b"\xff\xfe\x00", b"a: [", b"- 1\n- 2\n", b"x" * (3 * 1024 * 1024)):
        _, verdict = bf.charger_base(contenu_octets=octets)
        assert verdict["code"] in {"REJ-BASEFISC-FORMAT-INVALIDE", "REJ-BASEFISC-SCHEMA-INVALIDE"}, octets[:8]
    assert bf.charger_base(Path("/chemin/inexistant/regles.yaml"))[1]["code"] == "REJ-BASEFISC-FORMAT-INVALIDE"


# ------------------------------------------------------------- modification silencieuse, revues
def test_valeur_modifiee_sans_nouvelle_empreinte_est_detectee():
    p = _param()
    p["valeur"] = "0.99"
    _refus(_base(p), "REJ-BASEFISC-EMPREINTE-DIVERGENTE")


def test_source_modifiee_ou_dates_modifiees_sans_nouvelle_empreinte_sont_detectees():
    p = _param()
    p["sources"][0]["url"] = "https://pirate.test/"
    _refus(_base(p), "REJ-BASEFISC-EMPREINTE-DIVERGENTE")
    q = _param()
    q["effet"]["fin"] = "2027-12-31"
    _refus(_base(q), "REJ-BASEFISC-EMPREINTE-DIVERGENTE")


def test_valeur_modifiee_ET_rescellee_ne_garde_pas_les_revues_donc_ne_reste_pas_approuvee():
    p = _param()
    ancien = p["empreinte"]
    p["valeur"] = "0.99"
    p["empreinte"] = bf.empreinte_parametre(p)
    assert p["empreinte"] != ancien
    # le statut « approuve » déclaré n'est plus prouvé : les revues portent l'ancienne empreinte
    _refus(_base(p), "REJ-BASEFISC-STATUT-INCOHERENT")
    # redescendu honnêtement en brouillon, la base se charge mais le mode officiel refuse
    p["statut"] = "brouillon"
    base = _ok(_base(p))
    assert bf.resoudre(base, "qc.test.taux", "2026-03-01", mode="officiel")[1]["code"] == "REJ-BASEFISC-NON-APPROUVE"


def test_approuve_exige_deux_reviseurs_DISTINCTS_meme_nom_en_casse_differente():
    p = _param(revueurs=("marie.fictive", "Marie.Fictive"))
    p["statut"] = "approuve"
    _refus(_base(p), "REJ-BASEFISC-STATUT-INCOHERENT")
    p["statut"] = "revu_1"
    assert _ok(_base(p)) is not None


def test_l_auteur_de_la_saisie_ne_compte_pas_comme_reviseur():
    p = _param(revueurs=("saisie.fictive", "marie.fictive"))
    p["statut"] = "approuve"
    _refus(_base(p), "REJ-BASEFISC-STATUT-INCOHERENT")
    p["statut"] = "revu_1"
    base = _ok(_base(p))
    assert bf.resoudre(base, "qc.test.taux", "2026-03-01", mode="officiel")[1]["code"] == "REJ-BASEFISC-NON-APPROUVE"


def test_statut_declare_trop_bas_est_aussi_incoherent_le_statut_est_prouve_pas_declare():
    p = _param()
    p["statut"] = "brouillon"
    _refus(_base(p), "REJ-BASEFISC-STATUT-INCOHERENT")


def test_revue_mal_formee_ou_datee_avant_la_saisie_est_refusee():
    p = _param()
    p["revues"][0]["le"] = "2026-09-01"
    _refus(_base(p), "REJ-BASEFISC-REVUE-INVALIDE")
    q = _param()
    q["revues"][0]["decision"] = "peut-etre"
    _refus(_base(q), "REJ-BASEFISC-REVUE-INVALIDE")
    r = _param()
    r["revues"][0]["extra"] = 1
    _refus(_base(r), "REJ-BASEFISC-REVUE-INVALIDE")


def test_revue_sur_un_ancien_empreinte_ne_compte_pas():
    p = _param(revueurs=("marie.fictive",))
    p["revues"][0]["empreinte"] = "0" * 64
    p["statut"] = "brouillon"
    base = _ok(_base(p))
    assert bf.resume_base(base)["par_statut"]["brouillon"] == 1


def test_non_renseigne_n_a_ni_valeur_ni_revue_et_se_refuse_a_la_resolution():
    p = {
        "id": "qc.test.inconnu",
        "juridiction": "QC",
        "libelle": "À fournir",
        "valeur": None,
        "unite": "CAD",
        "effet": {"debut": "2026-01-01", "fin": "2026-12-31"},
        "sources": [],
        "saisie": {"par": "saisie.fictive", "le": "2026-10-02"},
        "revues": [],
        "statut": "brouillon",
        "non_renseigne": {"raison": "absent du dépôt", "source_requise": "organisme X"},
        "empreinte": "x",
    }
    p["empreinte"] = bf.empreinte_parametre(p)
    base = _ok(_base(p))
    verdict = bf.resoudre(base, "qc.test.inconnu", "2026-05-05", mode="essai")[1]
    assert verdict["code"] == "REJ-BASEFISC-NON-RENSEIGNE" and "source officielle requise" in verdict["detail"]
    avec_valeur = copy.deepcopy(p)
    avec_valeur["valeur"] = "10.00"
    avec_valeur["empreinte"] = bf.empreinte_parametre(avec_valeur)
    _refus(_base(avec_valeur), "REJ-BASEFISC-SCHEMA-INVALIDE")
    sans_marque = copy.deepcopy(p)
    del sans_marque["non_renseigne"]
    sans_marque["empreinte"] = bf.empreinte_parametre(sans_marque)
    _refus(_base(sans_marque), "REJ-BASEFISC-SCHEMA-INVALIDE")


def test_empreinte_de_base_change_quand_une_valeur_change():
    a = _ok(_base(_param(valeur="0.05")))
    b = _ok(_base(_param(valeur="0.06")))
    assert a.empreinte != b.empreinte and len(a.empreinte) == 64


# ------------------------------------------------------- le pont TPS/TVQ : mêmes résultats, au cent
def _base_taxes(reviseurs=("marie.fictive", "jean.fictif")):
    dispo = {"fed.tps.taux": "0.05", "qc.tvq.taux": "0.09975"}
    return _ok(_base(*[_param(identifiant=i, valeur=v, revueurs=reviseurs) for i, v in dispo.items()]))


def test_calcul_des_taxes_selon_la_base_egale_le_calcul_historique_au_cent():
    legacy, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX)
    assert erreurs == []
    base = _base_taxes()
    for centimes in list(range(0, 400)) + [12345, 99999, 100000, 123457, 98765432, 999999999]:
        montant = Decimal(centimes) / Decimal(100)
        attendu, v1 = taxes.calculer_taxes(montant, legacy)
        obtenu, v2 = bf.calculer_taxes_selon_base(montant, base, "2026-05-05", mode=bf.MODE_OFFICIEL)
        assert v1 is None and v2 is None
        assert obtenu["taxes"] == [
            {**t, "version": o["version"], "nom": o["nom"]}
            for t, o in zip(attendu["taxes"], obtenu["taxes"], strict=True)
        ]
        assert obtenu["total_taxes"] == attendu["total_taxes"]
        assert obtenu["montant_apres_taxes"] == attendu["montant_apres_taxes"]
        assert obtenu["base_fiscale"]["mode"] == "officiel" and obtenu["base_fiscale"]["essai"] is False


def test_calcul_selon_la_base_en_mode_essai_est_marque_et_en_mode_officiel_refuse_sans_approbation():
    base, _ = bf.charger_base(_CHEMIN_REEL)
    obtenu, verdict = bf.calculer_taxes_selon_base(Decimal("100.00"), base, "2026-05-05", mode="essai")
    assert verdict is None and obtenu["base_fiscale"]["essai"] is True
    assert obtenu["total_taxes"] == Decimal("14.98")  # 5.00 + 9.975 arrondi au cent supérieur, comme taxes.py
    obtenu, verdict = bf.calculer_taxes_selon_base(Decimal("100.00"), base, "2026-05-05", mode="officiel")
    assert obtenu is None and verdict["code"] == "REJ-BASEFISC-NON-APPROUVE"
    obtenu, verdict = bf.calculer_taxes_selon_base(Decimal("100.00"), base, "2027-05-05", mode="essai")
    assert obtenu is None and verdict["code"] == "REJ-BASEFISC-HORS-COUVERTURE"


def test_un_seul_taux_non_approuve_suffit_a_refuser_le_calcul_officiel():
    base = _ok(
        _base(
            _param(identifiant="fed.tps.taux", valeur="0.05"),
            _param(identifiant="qc.tvq.taux", valeur="0.09975", revueurs=("marie.fictive",)),
        )
    )
    obtenu, verdict = bf.calculer_taxes_selon_base(Decimal("10.00"), base, "2026-05-05", mode="officiel")
    assert obtenu is None and verdict["code"] == "REJ-BASEFISC-NON-APPROUVE"


def test_diagnostic_liste_toutes_les_erreurs_pas_seulement_la_premiere():
    a, b = _param(identifiant="qc.a.taux", revueurs=()), _param(identifiant="qc.b.taux", revueurs=())
    a["valeur"], b["valeur"] = "0.09", "0.08"
    codes = [v["code"] for v in bf.diagnostiquer(yaml.safe_dump(_base(a, b)).encode("utf-8"))]
    assert codes.count("REJ-BASEFISC-EMPREINTE-DIVERGENTE") == 2


# ---------------------------------------------------------------------------------------------------- CLI
def test_cli_verifier_dit_zero_approuve_et_empreintes_redonne_celles_du_fichier(capsys):
    assert bf.main(["verifier"]) == 0
    assert "0/62 valeurs approuvées" in capsys.readouterr().out
    assert bf.main(["empreintes"]) == 0
    lignes = capsys.readouterr().out.strip().split("\n")
    contenu = yaml.safe_load(_CHEMIN_REEL.read_text(encoding="utf-8"))["parametres"]
    assert lignes == [f"{p['id']} {p['effet']['debut']} {p['empreinte']}" for p in contenu]


def test_cli_verifier_echoue_sur_un_fichier_modifie_et_commande_inconnue_donne_2(tmp_path, capsys):
    texte = _CHEMIN_REEL.read_text(encoding="utf-8").replace("valeur: '0.05'", "valeur: '0.06'", 1)
    fichier = tmp_path / "regles.yaml"
    fichier.write_text(texte, encoding="utf-8")
    assert bf.main(["verifier", str(fichier)]) == 1
    assert "REJ-BASEFISC-EMPREINTE-DIVERGENTE" in capsys.readouterr().out
    assert bf.main(["autre"]) == 2
