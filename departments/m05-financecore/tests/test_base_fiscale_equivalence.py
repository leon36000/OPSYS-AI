"""Équivalence valeur par valeur entre la base de règles (`contracts/regles_fiscales.v1.yaml`) et les constantes que les
calculateurs du dépôt utilisent ENCORE (plan de bascule, `docs/architecture/BASE-FISCALE.md`).

La base est exposée EN PARALLÈLE : aucun calculateur de paie n'a été modifié (leurs fichiers sont épinglés par empreinte
dans `contracts/admission_paie_preparatoire.v1.json`), donc aucun résultat ne peut avoir changé. Ces tests ferment la
porte à la dérive dans les deux sens : une constante modifiée dans le code sans la base, ou une valeur de la base
modifiée sans le code, fait échouer le test ; et toute NOUVELLE feuille numérique d'un snapshot de paramètres doit être
migrée dans la base ou exclue ici avec sa raison. Fictif (AGENTS.md).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import yaml
from m5_financecore import base_fiscale as bf
from m5_financecore import cotisations_rqap_ae_2026 as rqap_ae
from m5_financecore import cotisations_rrq_regulieres as rrq
from m5_financecore import impot_federal_qc_2026 as federal
from m5_financecore import impot_quebec_regulier as impot_qc

FICTIF = True
_CONTRATS = Path(__file__).resolve().parents[1] / "contracts"


def _mapping():
    """identifiant de la base -> valeur lue dans la constante du code (texte, tel que le code la porte)."""
    m = {}
    taux = {
        t["id"]: t for t in yaml.safe_load((_CONTRATS / "taux_fiscaux.v1.yaml").read_text(encoding="utf-8"))["taux"]
    }
    m["fed.tps.taux"] = str(taux["tps_federale"]["taux"])
    m["qc.tvq.taux"] = str(taux["tvq_quebec"]["taux"])
    for cle in (
        "maximum_gains_admissibles",
        "exemption_generale",
        "taux_palier1",
        "taux_premiere_supplementaire",
        "maximum_cotisation_palier1",
        "maximum_supplementaire_gains_admissibles",
        "taux_palier2",
        "maximum_cotisation_palier2",
    ):
        m[f"qc.rrq.{cle}"] = rrq._PARAMETRES[cle]
    for cle in ("revenu_max_assurable", "taux_salarie", "maximum_salarie", "taux_employeur", "maximum_employeur"):
        m[f"qc.rqap.{cle}"] = rqap_ae._PARAMETRES["rqap"][cle]
        m[f"fed.ae_qc.{cle}"] = rqap_ae._PARAMETRES["ae_qc"][cle]
    iq = impot_qc._PARAMETRES
    m["qc.impot.deduction_travailleur.taux"] = iq["deduction_travailleur"]["taux"]
    m["qc.impot.deduction_travailleur.plafond_annuel"] = iq["deduction_travailleur"]["plafond_annuel"]
    for n, tranche in enumerate(iq["tranches"], 1):
        if tranche["maximum_I"] is not None:
            m[f"qc.impot.tranche_{n}.borne_superieure"] = tranche["maximum_I"]
        m[f"qc.impot.tranche_{n}.taux"] = tranche["taux"]
        m[f"qc.impot.tranche_{n}.constante"] = tranche["constante"]
    m["qc.impot.credit_e.taux"] = iq["credits"]["E"]
    m["qc.impot.credit_q.taux"] = iq["credits"]["Q_Q1"]
    m["qc.impot.plafond_fonds_travailleurs"] = iq["plafond_annuel_FTQ_Fondaction"]
    fd = federal._PARAMETRES
    for n, tranche in enumerate(fd["taux_tranches"], 1):
        if tranche["borne_superieure"] is not None:
            m[f"fed.impot.tranche_{n}.borne_superieure"] = tranche["borne_superieure"]
        m[f"fed.impot.tranche_{n}.taux"] = tranche["taux"]
        m[f"fed.impot.tranche_{n}.constante"] = tranche["constante"]
    m["fed.impot.credit_personnel.taux_minimal"] = fd["credit_personnel"]["taux_minimal"]
    for cle, valeur in fd["K2Q"].items():
        m[f"fed.impot.k2q.{cle}"] = valeur
    m["fed.impot.k4.taux_federal"] = fd["K4"]["taux_federal"]
    m["fed.impot.k4.maximum_cea"] = fd["K4"]["maximum_cea"]
    m["fed.impot.abattement_qc"] = fd["abattement_qc"]
    m["fed.impot.lcf_maximum_annuel"] = fd["LCF_maximum_annuel"]
    return m


def _base():
    base, verdict = bf.charger_base(bf.CHEMIN_BASE_PAR_DEFAUT)
    assert verdict is None, verdict
    return base


def test_chaque_valeur_de_la_base_egale_la_constante_du_code_valeur_par_valeur():
    base = _base()
    attendu = _mapping()
    for ident, texte_code in attendu.items():
        versions = base.parametres[ident]
        assert len(versions) == 1, ident
        regle, verdict = bf.resoudre(base, ident, "2026-03-15", mode=bf.MODE_ESSAI)
        assert verdict is None, (ident, verdict)
        assert regle["valeur"] == Decimal(texte_code), (ident, regle["valeur"], texte_code)
    # et inversement : aucune valeur renseignée de la base sans constante de code qui la porte
    renseignes = {i for i, vs in base.parametres.items() if vs[0].valeur is not None}
    assert renseignes == set(attendu), sorted(renseignes ^ set(attendu))


def test_la_valeur_est_la_meme_en_juillet_pour_les_baremes_federaux_qui_ne_changent_pas():
    base = _base()
    for ident in _mapping():
        a = bf.resoudre(base, ident, "2026-01-15", mode="essai")[0]
        b = bf.resoudre(base, ident, "2026-12-31", mode="essai")[0]
        assert a["valeur"] == b["valeur"] and a["empreinte"] == b["empreinte"], ident


def test_la_constante_k2q_federale_est_coherente_avec_les_cotisations_ae_et_rqap_de_la_base():
    base = _base()

    def val(i):
        return bf.resoudre(base, i, "2026-06-01", mode="essai")[0]["valeur"]

    assert val("fed.impot.k2q.maximum_ei_qc") == val("fed.ae_qc.maximum_salarie")
    assert val("fed.impot.k2q.taux_qpip_credit") == val("qc.rqap.taux_salarie")
    assert val("fed.impot.k2q.maximum_qpip") == val("qc.rqap.maximum_salarie")
    assert val("fed.impot.k2q.taux_rrq_total_palier1") == val("qc.rrq.taux_palier1")


def _feuilles_numeriques(objet, chemin=""):
    if isinstance(objet, dict):
        for cle, valeur in objet.items():
            yield from _feuilles_numeriques(valeur, f"{chemin}.{cle}" if chemin else str(cle))
    elif isinstance(objet, list):
        for i, valeur in enumerate(objet):
            yield from _feuilles_numeriques(valeur, f"{chemin}[{i}]")
    elif isinstance(objet, str):
        try:
            Decimal(objet)
        except Exception:
            return
        yield chemin, objet
    elif isinstance(objet, (int, float)) and not isinstance(objet, bool):
        yield chemin, str(objet)


# Feuilles numériques des snapshots qui NE sont PAS des paramètres fiscaux : structure du calcul (nombre de périodes,
# contexte décimal), bornes de validation d'entrée ou identifiants d'édition. Chacune avec sa raison.
_EXCLUES = {
    "periodes_annuelles": "structure : 26 paies bihebdomadaires",
    "mois_par_annee": "structure : 12 mois",
    "pm_requis_atteste": "structure : portée attestée du calcul (PM=12)",
    "periode_couverte": "structure : période annuelle couverte",
    "annee": "structure : millésime du snapshot",
    "montant_max_entree": "borne de validation d'entrée",
    "decimales_max_entree": "borne de validation d'entrée",
    "exposant_max_entree": "borne de validation d'entrée",
    "precision_contexte_decimal": "contexte décimal",
    "emin_contexte_decimal": "contexte décimal",
    "emax_contexte_decimal": "contexte décimal",
    "clamp_contexte_decimal": "contexte décimal",
    "precision_decimal": "contexte décimal",
    "emin_decimal": "contexte décimal",
    "emax_decimal": "contexte décimal",
    "clamp_decimal": "contexte décimal",
    "cent": "unité d'arrondi",
    "option": "option de calcul T4127 (méthode, pas un taux)",
    "limites_montant": "bornes de validation d'entrée",
    "decimal": "contexte décimal",
    "contexte_decimal": "contexte décimal",
    "P": "structure : 26 périodes",
    "B2_regulier_sans_forfait": "hypothèse de périmètre (zéro attesté)",
    "formule": "identifiant d'édition",
    "edition": "identifiant d'édition",
    "version": "identifiant d'édition",
    "edition_formules": "identifiant d'édition",
    "en_vigueur": "date d'édition",
    "CSA_ratio": "dérivé : 0.01 / taux RRQ palier 1, recalculé dans le code",
    "source_pages": "référence documentaire",
    "pages": "référence documentaire",
    "sha256": "empreinte de capture",
    "sha256_tr26": "empreinte de capture",
    "annexe": "référence documentaire",
    "url": "référence documentaire",
    "sections": "référence documentaire",
    "consultation": "date de consultation",
    "schema": "identifiant de schéma",
    "inputs_nuls_obligatoires": "liste de noms de champs",
    "limites": "texte de périmètre",
    "scope": "texte de périmètre",
    "portee": "texte de périmètre",
    "regles_arrondi": "texte de règle d'arrondi",
    "arrondis": "texte de règle d'arrondi",
    "politique_implementation": "texte de politique d'arrondi",
    "pieges_decimal": "contexte décimal",
    "pieges_contexte_decimal": "contexte décimal",
    "arrondi_decimal": "contexte décimal",
    "arrondi_contexte_decimal": "contexte décimal",
    "juridiction": "identifiant",
    "frequence": "identifiant",
    "TC_obligatoire": "texte : le crédit personnel est déclaré (TD1), jamais un défaut",
}


def _est_exclue(chemin):
    morceaux = chemin.replace("[", ".").replace("]", "").split(".")
    return any(morceau in _EXCLUES for morceau in morceaux)


def test_toute_feuille_numerique_des_snapshots_est_migree_ou_exclue_avec_sa_raison():
    """Si quelqu'un ajoute une constante fiscale à un snapshot de paramètres sans l'ajouter à la base, ce test
    échoue."""
    attendu = {Decimal(v) for v in _mapping().values()}
    inconnues = []
    examinees = 0
    for nom, snapshot in (
        ("rrq", rrq._PARAMETRES),
        ("rqap_ae", rqap_ae._PARAMETRES),
        ("impot_qc", impot_qc._PARAMETRES),
        ("federal", federal._PARAMETRES),
    ):
        # le snapshot doit rester sérialisable comme l'empreinte l'exige
        json.dumps(snapshot, sort_keys=True)
        for chemin, texte in _feuilles_numeriques(snapshot):
            if _est_exclue(chemin):
                continue
            examinees += 1
            if Decimal(texte) not in attendu:
                inconnues.append((nom, chemin, texte))
    assert examinees >= 45, "le test ne doit pas être vide : les feuilles examinées ont disparu"
    assert inconnues == [], f"constantes fiscales du code absentes de la base : {inconnues}"


def test_une_valeur_de_la_base_modifiee_et_rescellee_ferait_echouer_l_equivalence():
    """Mutation : la base altérée (valeur ET empreinte cohérentes) charge, mais l'équivalence la voit."""
    contenu = yaml.safe_load(bf.CHEMIN_BASE_PAR_DEFAUT.read_text(encoding="utf-8"))
    cible = next(p for p in contenu["parametres"] if p["id"] == "qc.rrq.taux_palier1")
    cible["valeur"] = "0.0640"
    cible["empreinte"] = bf.empreinte_parametre(cible)
    base, verdict = bf.charger_base(contenu_octets=yaml.safe_dump(contenu, allow_unicode=True).encode("utf-8"))
    assert verdict is None
    regle = bf.resoudre(base, "qc.rrq.taux_palier1", "2026-03-15", mode="essai")[0]
    assert regle["valeur"] != Decimal(_mapping()["qc.rrq.taux_palier1"])


def test_les_resultats_de_paie_existants_n_ont_pas_change_leurs_empreintes_de_parametres():
    """Preuve de non-régression structurelle : les snapshots épinglés du code de paie n'ont pas bougé (leurs hachages
    sont ceux de contracts/admission_paie_preparatoire.v1.json)."""
    contrat = json.loads((_CONTRATS / "admission_paie_preparatoire.v1.json").read_text(encoding="utf-8"))
    pins = {f["parametres_sha256"] for f in contrat["capacite"]["fenetres"]}
    assert "9f94fdcb05c9d919b4f3c3787d9e2585d15bc0bc69bcbd121394547ef17baca6" in pins
    assert federal.HASH_PARAMETRES == "9f94fdcb05c9d919b4f3c3787d9e2585d15bc0bc69bcbd121394547ef17baca6"
