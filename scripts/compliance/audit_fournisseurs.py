#!/usr/bin/env python3
"""Audit du catalogue de fournisseurs (`opsys.fournisseurs.catalogue`) : complétude des champs de licence et niveau de
vérification À LA SOURCE de chaque ligne.

Ce que le script établit (sans réseau) :
- chaque ligne porte licence du code ET des poids (ou une justification écrite que les poids ne s'appliquent pas), usage
  commercial, seuil de revenu, territoires exclus, droit de service à des tiers, source et date ;
- une ligne n'est « lue en recherche » que si sa source porte une marque de preuve primaire `[V` (recherches R1-R6 du
  2026-10-31, lues avec accès réseau par leurs auteurs) ; toute autre ligne est `non_verifiee_a_la_source`. AUCUNE ligne n'a
  été revérifiée dans cette session (aucun accès réseau).
- l'empreinte du bloc licence de chaque ligne est consignée : modifier une licence du catalogue sans repasser par l'audit
  fait échouer `tests/test_registre_fournisseurs_licences.py`.

  PYTHONPATH=src python scripts/compliance/audit_fournisseurs.py --ecrire | --verifier
"""

# ruff: noqa: E501  (assertions et chaînes de documentation longues, lisibles telles quelles)

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "src"))

from opsys.fournisseurs import catalogue  # noqa: E402
from opsys.fournisseurs.modele import Fournisseur  # noqa: E402

FICHIER_DONNEES = RACINE / "docs" / "compliance" / "donnees" / "fournisseurs-verification.json"
FICHIER_REGISTRE = RACINE / "docs" / "compliance" / "REGISTRE-FOURNISSEURS-LICENCES.md"
DATE_RECHERCHE = "2026-10-31"
LUE = "lue_en_recherche_niveau_V"
NON_VERIFIEE = "non_verifiee_a_la_source"
# Capacités qui livrent des POIDS de modèle : la licence des poids doit être déclarée pour une ligne locale.
CAPACITES_A_POIDS = {"llm", "embeddings", "reranker", "ocr", "stt", "tts", "avatar", "image", "video", "vision"}

# Lignes locales dont `poids` est vide : justification écrite, revue à la main (jamais déduite).
POIDS_NON_APPLICABLES = {
    "ocr.tesseract-5.5.local": "binaire seul dans le catalogue ; les données de langue (traineddata « fra ») ont leur propre "
                               "licence, NON relevée : à vérifier avant de les distribuer",
    "avatar.talkinghead": "bibliothèque de rendu sans modèle appris ; les avatars GLB sont fournis par OPSYS ou le client "
                          "(les exemples du dépôt amont, non commerciaux, sont exclus : voir la note de la ligne)",
    "courriel.imap.generique": "protocole standard (bibliothèque Python) : aucun poids",
    "courriel.mbox.local": "format de fichier standard (bibliothèque Python) : aucun poids",
    "ocr.pymupdf": "bibliothèque sans modèle appris (écartée : AGPL)",
    "ocr.ghostscript": "logiciel sans modèle appris (écarté : AGPL)",
    "video.remotion": "bibliothèque de composition sans modèle appris (écartée : licence maison)",
}

# Lacunes réelles du catalogue, connues et non corrigées ici (le texte de licence manque : on ne le complète pas de mémoire).
LACUNES_CONNUES = {
    "image.flux3-image-klein.local": ["licence du code absente"],
}


def empreinte_licence(f: Fournisseur) -> str:
    texte = json.dumps(f.licence.vers_json(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def statut_source(f: Fournisseur) -> tuple[str, str]:
    lic = f.licence
    if lic.verification == "a_lire":
        return NON_VERIFIEE, "texte intégral non lu (le catalogue déclare verification=a_lire)"
    if "hors-recherche" in lic.source:
        return NON_VERIFIEE, "licence tirée de la connaissance de l'agent, hors des recherches R1-R6"
    if "[V" in lic.source:
        return LUE, "marque de preuve primaire [V] dans la source citée"
    return NON_VERIFIEE, "source citée sans marque de preuve primaire [V] (connu, supposé ou non précisé)"


def lacunes(f: Fournisseur) -> list[str]:
    """Problèmes de `f` qui ne sont PAS des lacunes consignées dans LACUNES_CONNUES."""
    return [x for x in problemes(f) if x not in LACUNES_CONNUES.get(f.identifiant, [])]


def problemes(f: Fournisseur) -> list[str]:
    """Champs manquants ou incohérents pour UNE ligne (liste vide = complète)."""
    lic, p = f.licence, []
    if f.mode == "local" and f.capacite in CAPACITES_A_POIDS and lic.poids is None and f.identifiant not in POIDS_NON_APPLICABLES:
        p.append("licence des poids absente sans justification")
    if f.mode == "local" and lic.code is None and f.statut_catalogue != "ecarte":
        p.append("licence du code absente")
    if not lic.source.strip():
        p.append("source absente")
    if lic.usage_commercial == "sous_seuil" and not lic.seuil_revenu_usd:
        p.append("seuil de revenu absent")
    if lic.service_tiers not in ("autorise", "interdit", "incertain"):
        p.append("droit de service à des tiers non déclaré")
    return p


def construire() -> dict[str, Any]:
    lignes = {}
    for f in catalogue.CATALOGUE:
        statut, raison = statut_source(f)
        lignes[f.identifiant] = {
            "empreinte_licence": empreinte_licence(f), "statut_source": statut, "raison_statut": raison,
            "date_source": DATE_RECHERCHE if statut == LUE else None,
            "date_reverification_locale": None,
        }
        if f.identifiant in POIDS_NON_APPLICABLES:
            lignes[f.identifiant]["poids_non_applicable"] = POIDS_NON_APPLICABLES[f.identifiant]
        if f.identifiant in LACUNES_CONNUES:
            lignes[f.identifiant]["lacunes_connues"] = LACUNES_CONNUES[f.identifiant]
    return {"schema": "opsys.conformite.fournisseurs/v1", "date_recherche_sources": DATE_RECHERCHE,
            "avertissement": "Aucune ligne n'a été revérifiée à la source dans la session du 2026-11-01 (aucun accès réseau). "
                             "« lue_en_recherche_niveau_V » = lue par les auteurs des recherches R1-R6 le 2026-10-31, à revérifier "
                             "avant tout engagement. Ce n'est pas un avis juridique.",
            "lignes": lignes}


def incoherences_catalogue() -> list[str]:
    """Lignes que le catalogue déclare `verifiee` alors que leur source ne porte pas de preuve primaire [V]."""
    return sorted(f.identifiant for f in catalogue.CATALOGUE
                  if f.licence.verification == "verifiee" and statut_source(f)[0] == NON_VERIFIEE)


def _t(valeur: Any) -> str:
    return "—" if valeur in (None, "", ()) else str(valeur).replace("|", "/")


def registre_markdown(donnees: dict[str, Any]) -> str:
    sortie = [
        "# Registre des licences des fournisseurs (généré)", "",
        "> Généré par `scripts/compliance/audit_fournisseurs.py --ecrire` depuis `src/opsys/fournisseurs/catalogue.py` ; "
        "ne pas modifier à la main (un test compare). **Aucune ligne n'a été revérifiée à la source** dans la session du "
        "2026-11-01 (aucun accès réseau) : la colonne « Source » dit seulement si la recherche R1-R6 du "
        f"{DATE_RECHERCHE} l'avait lue (niveau V). Pas un avis juridique ; questions ouvertes : "
        "[QUESTIONS-AVOCAT](QUESTIONS-AVOCAT.md).", "",
        "| Identifiant | Cap. | Statut | Licence du code | Licence des poids | Usage commercial | Seuil (USD de revenu) | "
        "Territoires exclus | Service à des tiers | Référence de la source | Source | Date |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in catalogue.CATALOGUE:
        d = donnees["lignes"][f.identifiant]
        lic = f.licence
        seuil = f"{lic.seuil_revenu_usd:,}".replace(",", " ") if lic.seuil_revenu_usd else None
        poids = lic.poids or ("sans objet : " + d["poids_non_applicable"] if "poids_non_applicable" in d else
                              ("sans poids (API)" if f.mode == "api" else None))
        source = "lue (V)" if d["statut_source"] == LUE else "**non vérifiée à la source**"
        if "lacunes_connues" in d:
            source += " ; **lacune : " + ", ".join(d["lacunes_connues"]) + "**"
        sortie.append(
            f"| `{f.identifiant}` | {f.capacite} | {f.statut_catalogue} | {_t(lic.code)} | {_t(poids)} | {lic.usage_commercial} | "
            f"{_t(seuil)} | {_t(', '.join(lic.territoires_exclus))} | {lic.service_tiers} | {_t(lic.source)} | {source} | "
            f"{_t(d['date_source'])} |")
    n = sum(1 for d in donnees["lignes"].values() if d["statut_source"] == NON_VERIFIEE)
    sortie += ["", f"Total : {len(donnees['lignes'])} lignes, dont **{n} non vérifiées à la source** et "
               f"{len(donnees['lignes']) - n} lues en recherche (niveau V, {DATE_RECHERCHE}, non revérifiées).", ""]
    return "\n".join(sortie)


def main(argv: list[str] | None = None) -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--ecrire", action="store_true")
    g.add_argument("--verifier", action="store_true")
    args = a.parse_args(argv)
    donnees = construire()
    donnees_txt = json.dumps(donnees, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    md = registre_markdown(donnees)
    if args.ecrire:
        FICHIER_DONNEES.write_text(donnees_txt, encoding="utf-8")
        FICHIER_REGISTRE.write_text(md, encoding="utf-8")
        print("écrit :", FICHIER_DONNEES.name, FICHIER_REGISTRE.name)
        return 0
    ok = (FICHIER_DONNEES.read_text(encoding="utf-8") == donnees_txt and FICHIER_REGISTRE.read_text(encoding="utf-8") == md)
    print("à jour" if ok else "périmé : relancer --ecrire")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
