"""Export privé pour le professionnel (CPA) d'une version revue : JSON canonique + HTML lisible, reproductibles.

Fonction pure de la version figée et de sa revue : aucune heure courante, aucun hasard, aucune lecture externe. Deux
appels sur les mêmes entrées donnent les mêmes octets, donc la même empreinte (celle que l'événement EXPORT conserve).
Ce n'est ni un bulletin de paie, ni un T4/RL-1/RE, ni un avis fiscal : il porte PREPARATOIRE et NON_QUALIFIEE_POUR_PAIE.
Contenu minimal : référence OPSYS de l'employé (ni NAS, ni adresse, ni compte bancaire), jamais de taux horaire.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence
from typing import Any

from . import cotisations_employeur_2026
from . import dossier_paie_preparatoire as dossier

SCHEMA_EXPORT = "opsys.export-cpa-paie-preparatoire/v1"
_FORMATS = ("json", "html")
TYPES_MIME = {"json": "application/json", "html": "text/html; charset=utf-8"}

_LIMITES = (
    "Document préparatoire : aucun salaire versé, aucune remise faite, aucun document fiscal officiel émis.",
    "Qualification des règles : NON_QUALIFIEE_POUR_PAIE. La revue du propriétaire est interne, liée à une version "
    "et à son empreinte ; elle ne vaut ni validation fiscale, ni attestation professionnelle, ni conformité légale.",
    "Les attestations, crédits, cumuls, taux employeur et pièces sont des déclarations humaines non authentifiées.",
    "Cumuls après période : hypothétiques, issus d'une préparation, jamais un salaire versé ni une preuve.",
    "Domaine couvert : QC, paie bihebdomadaire à 26 périodes de 2026, salaire régulier, assiettes égales au brut, "
    "sans avantage imposable, gratification, rétroactif, surtemps, vacances/fériés payés à part, ni régime CCQ.",
    "Les sources réglementaires employeur (FSS, CNESST, normes du travail, FDRCMO) ont été lues en texte officiel sans "
    "re-hachage des octets des PDF : statut de source non qualifié.",
)


def est_format(valeur: object) -> bool:
    return isinstance(valeur, str) and valeur in _FORMATS


def _sources_reglementaires(figee: Mapping[str, Any]) -> list[dict[str, Any]]:
    from . import cotisations_rrq_regulieres as rrq
    from . import impot_federal_qc_2026 as federal

    empreintes = figee["admission"].get("empreintes_sources") or {}
    sources: list[dict[str, Any]] = [
        {
            "id": "rq_tp1015f_2026_01",
            "autorite": "Revenu Québec",
            "document": "TP-1015.F",
            "edition": "2026-01",
            "usage": "RRQ, impôt du Québec, RQAP",
            "url": rrq.SOURCE_URL_F,
            "sha256_pdf_epingle": rrq.SOURCE_SHA256_F,
            "pages": "7, 12-16, 29, 37-42, 46-49, 51-52",
            "empreinte_verifiee_par_admission": empreintes.get("rq_f2026"),
        },
        {
            "id": "rq_tp1015tr26_2026_01",
            "autorite": "Revenu Québec",
            "document": "TP-1015.TR.26",
            "edition": "2026-01",
            "usage": "RRQ — annexe D, tables A et C",
            "url": rrq.SOURCE_URL_TR26,
            "sha256_pdf_epingle": rrq.SOURCE_SHA256_TR26,
            "empreinte_verifiee_par_admission": empreintes.get("rq_tr26_2026"),
        },
        {
            "id": "arc_t4127_122e_2026_01",
            "autorite": "Agence du revenu du Canada",
            "document": "T4127",
            "edition": "122e, janvier 2026",
            "usage": "impôt fédéral (option 1), AE",
            "sha256_pdf_epingle": federal.SOURCE_T4127_SHA256,
            "pages": "3, 14-17, 31, 32, 34",
            "empreinte_verifiee_par_admission": empreintes.get("arc_jan2026"),
        },
        {
            "id": "arc_t4127_123e_2026_07",
            "autorite": "Agence du revenu du Canada",
            "document": "T4127",
            "edition": "123e, juillet 2026",
            "usage": "impôt fédéral dès le 2026-07-01",
            "sha256_pdf_epingle": "69d86d952cb14c786fdcc0321ec293f66db1529276ef310217b3ade47db25671",
            "empreinte_verifiee_par_admission": empreintes.get("arc_jul2026"),
        },
    ]
    for source in cotisations_employeur_2026.PARAMETRES["sources"]:
        sources.append(
            {**source, "usage": "postes employeur", "statut_capture": cotisations_employeur_2026.STATUT_SOURCE}
        )
    return sources


def construire_json(
    d: Mapping[str, Any],
    numero: int,
    liens_officiels: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    version = d["versions"][numero - 1]
    figee = version["version"]
    revue = next(
        (r for r in reversed(d["revues"]) if r["numero"] == numero and r["hash_version"] == version["hash_version"]),
        None,
    )
    calcul = figee["calcul"]
    entrees = figee["entrees"]
    brut = figee["sources"]["brut"]
    heures = figee["sources"]["heures_m4"]
    minutes = heures["minutes_regulieres"]
    return {
        "schema": SCHEMA_EXPORT,
        "mode": dossier.MODE,
        "qualification_regles": dossier.QUALIFICATION,
        "aucun_versement": True,
        "documents_officiels_emis": [],
        "limites": list(_LIMITES),
        "dossier": {
            "dossier_id": d["dossier_id"],
            "numero_version": version["numero"],
            "hash_version": version["hash_version"],
            "type_version": version["type_version"],
            "motif": version["motif"],
            "horodatage_version": version["horodatage"],
            "fictif": entrees["fictif"],
            "revue_interne": None
            if revue is None
            else {
                "decision": revue["decision"],
                "note": revue["note"],
                "horodatage": revue["horodatage"],
                "portee": "REVUE_INTERNE_PROPRIETAIRE_NON_FISCALE",
            },
        },
        "employe": {"reference_opsys": figee["identite"]["employee_person_id"]},
        "employeur": {"reference": figee["identite"]["employeur_reference"]},
        "periode": {
            **{
                k: entrees["periode"][k]
                for k in (
                    "annee",
                    "periode_annuelle",
                    "debut",
                    "fin",
                    "fuseau",
                    "date_paie",
                    "premiere_date_paie_annee",
                )
            },
            "frequence": "bihebdomadaire",
            "periodes_annuelles": dossier.PERIODES_ANNUELLES,
        },
        "heures_et_brut": {
            "minutes_regulieres": minutes,
            "heures_regulieres": f"{minutes // 60}:{minutes % 60:02d}",
            "brut_regulier": brut["brut_brouillon"],
            "brut_exact_fraction": brut["brut_exact_fraction"],
            "politique_arrondi": brut["politique_arrondi"],
            "hypothese_arrondi": brut["hypothese_arrondi"],
            "source_heures": {k: heures.get(k) for k in ("ligne_id", "revision", "empreinte_sources")},
            "source_contrat": {
                k: (figee["sources"]["contrat_m5"] or {}).get(k) for k in ("contrat_id", "revision", "ligne_id")
            },
        },
        "assiettes": {
            "mode": "EGALES_AU_BRUT_DECLAREES",
            "rrq": brut["brut_brouillon"],
            "rqap": brut["brut_brouillon"],
            "ae": brut["brut_brouillon"],
            "impot_quebec": brut["brut_brouillon"],
            "impot_federal": brut["brut_brouillon"],
        },
        "credits_et_declarations": {
            "credits_federal_td1": entrees["credits_federal"],
            "credits_quebec_tp1015_3": entrees["credits_qc"],
            "attestations": entrees["attestations"],
            "classification": entrees["classification"],
            "pieces_declarees": calcul["provenance_pieces"],
            "autres_retenues_employe": entrees["autres_retenues_employe"],
            "autres_couts_employeur": entrees["autres_couts_employeur"],
            "parametres_employeur_declares": entrees["parametres_employeur"],
        },
        "cumuls_avant": {
            "origine": entrees["cumuls_avant"]["origine"],
            "valeurs": entrees["cumuls_avant"]["valeurs"],
            "source_simulee": entrees["cumuls_avant"]["source_simulee"],
            "avertissement": "cumul simulé ou déclaré : ce n'est pas une preuve de versement"
            if entrees["cumuls_avant"]["origine"] != "CONFIRME_AUTORITE_HUMAINE"
            else "cumul confirmé par une autorité humaine sur la pièce citée; non authentifié par OPSYS",
        },
        "postes": calcul["matrice"],
        "totaux": calcul["totaux"],
        "cumuls_apres_hypothetiques": figee["cumuls_apres_hypothetiques"],
        "moteurs": calcul["moteurs"],
        "sources_reglementaires": _sources_reglementaires(figee),
        "admission_documentaire": figee["admission"],
        "parametres": figee["parametres"],
        "pour_verification_webras": {
            "usage": "Saisie et comparaison humaines dans WebRAS/PDOC; aucun appel automatisé n'est fait par OPSYS.",
            "revenu_brut_periode": brut["brut_brouillon"],
            "date_paie": entrees["periode"]["date_paie"],
            "periodes_annuelles": dossier.PERIODES_ANNUELLES,
            "liens_officiels": [dict(lien) for lien in liens_officiels],
        },
        "empreintes": {"hash_version": version["hash_version"], "empreinte_calcul": figee["empreinte_calcul"]},
    }


def serialiser_json(contenu: Mapping[str, Any]) -> bytes:
    return (json.dumps(contenu, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _e(valeur: Any) -> str:
    return html.escape("" if valeur is None else str(valeur), quote=True)


def _argent(valeur: Any) -> str:
    return "—" if valeur is None else f"{_e(valeur)} $"


def serialiser_html(contenu: Mapping[str, Any]) -> bytes:
    dos, per, hb = contenu["dossier"], contenu["periode"], contenu["heures_et_brut"]
    revue = dos["revue_interne"]
    lignes_postes = "".join(
        f"<tr><td>{_e(p['libelle'])}</td><td>{_e(p['autorite'])}</td><td>{_e(p['etat'])}</td>"
        f"<td class='num'>{_argent(p['montant'])}</td><td>{_e('; '.join(p['manque']))}</td></tr>"
        for p in contenu["postes"]
    )
    lignes_totaux = "".join(
        f"<tr><td>{_e(t['libelle'])}</td><td>{_e(t['etat'])}</td><td class='num'>{_argent(t['montant'])}</td>"
        f"<td>{_e('; '.join(t['manques']))}</td></tr>"
        for t in contenu["totaux"].values()
    )
    lignes_sources = "".join(
        f"<tr><td>{_e(s.get('autorite'))}</td><td>{_e(s.get('document'))} — {_e(s.get('edition'))}</td>"
        f"<td>{_e(s.get('pages') or s.get('sections'))}</td>"
        f"<td>{_e(s.get('sha256_pdf_epingle') or s.get('statut_capture') or '')}</td></tr>"
        for s in contenu["sources_reglementaires"]
    )
    cumuls = "".join(
        f"<tr><td>{_e(cle)}</td><td class='num'>{_argent(val)}</td></tr>"
        for cle, val in contenu["cumuls_avant"]["valeurs"].items()
    )
    apres = contenu["cumuls_apres_hypothetiques"]
    cumuls_apres = (
        "".join(f"<tr><td>{_e(cle)}</td><td class='num'>{_argent(val)}</td></tr>" for cle, val in apres.items())
        if apres
        else "<tr><td colspan='2'>Non disponibles (composition incomplète)</td></tr>"
    )
    limites = "".join(f"<li>{_e(texte)}</li>" for texte in contenu["limites"])
    revue_html = (
        f"<p>Revue interne du propriétaire : {_e(revue['decision'])} — {_e(revue['note'])} ({_e(revue['portee'])})</p>"
        if revue
        else "<p>Aucune revue interne liée à cette version.</p>"
    )
    page = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Dossier de paie préparatoire — {_e(per["date_paie"])}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:60rem;margin:1rem auto;padding:0 1rem;line-height:1.4}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}}
th,td{{border:1px solid #888;padding:.3rem .5rem;text-align:left;vertical-align:top}}
td.num{{text-align:right;white-space:nowrap}}
.alerte{{border:2px solid #b00;padding:.6rem;margin:1rem 0}}</style></head><body>
<h1>Dossier de paie préparatoire — remise au professionnel</h1>
<p class="alerte"><strong>PRÉPARATOIRE — NON_QUALIFIEE_POUR_PAIE.</strong>
Aucun salaire versé, aucune remise, aucun document fiscal officiel.</p>
<h2>Identification</h2>
<table><tr><th>Dossier</th><td>{_e(dos["dossier_id"])}</td></tr>
<tr><th>Version / empreinte</th><td>{_e(dos["numero_version"])} — {_e(dos["hash_version"])}</td></tr>
<tr><th>Employé (référence OPSYS)</th><td>{_e(contenu["employe"]["reference_opsys"])}</td></tr>
<tr><th>Employeur</th><td>{_e(contenu["employeur"]["reference"])}</td></tr>
<tr><th>Période de travail</th><td>{_e(per["debut"])} au {_e(per["fin"])} ({_e(per["fuseau"])})</td></tr>
<tr><th>Date de paie / période</th><td>{_e(per["date_paie"])} —
période {_e(per["periode_annuelle"])} sur {_e(per["periodes_annuelles"])}</td></tr>
<tr><th>Heures régulières M4</th><td>{_e(hb["heures_regulieres"])} ({_e(hb["minutes_regulieres"])} min)</td></tr>
<tr><th>Brut régulier</th><td>{_argent(hb["brut_regulier"])} (arrondi : {_e(hb["politique_arrondi"])})</td></tr></table>
{revue_html}
<h2>Postes</h2>
<table><thead><tr><th>Poste</th><th>Autorité</th><th>État</th><th>Montant</th><th>Manque</th></tr></thead><tbody>{lignes_postes}</tbody></table>
<h2>Totaux (affichés seulement si tous leurs postes sont couverts)</h2>
<table><thead><tr><th>Total</th><th>État</th><th>Montant</th><th>Manques</th></tr></thead><tbody>{lignes_totaux}</tbody></table>
<h2>Cumuls avant la période ({_e(contenu["cumuls_avant"]["origine"])})</h2>
<p>{_e(contenu["cumuls_avant"]["avertissement"])}</p><table><tbody>{cumuls}</tbody></table>
<h2>Cumuls après la période — hypothétiques, non versés</h2><table><tbody>{cumuls_apres}</tbody></table>
<h2>Sources réglementaires</h2>
<table><thead><tr><th>Autorité</th><th>Document</th><th>Pages / sections</th>
<th>Empreinte PDF épinglée / statut</th></tr></thead><tbody>{lignes_sources}</tbody></table>
<h2>Limites</h2><ul>{limites}</ul>
<p>Empreinte du calcul : {_e(contenu["empreintes"]["empreinte_calcul"])}</p>
</body></html>
"""
    return page.encode("utf-8")


def produire(
    d: Mapping[str, Any],
    numero: int,
    format_export: str,
    liens_officiels: Sequence[Mapping[str, Any]],
) -> tuple[bytes, str]:
    """(octets, empreinte SHA-256) de l'export; refuse un format inconnu."""
    import hashlib

    if format_export not in _FORMATS:
        raise ValueError("format d'export inconnu")
    contenu = construire_json(d, numero, liens_officiels)
    octets = serialiser_json(contenu) if format_export == "json" else serialiser_html(contenu)
    return octets, hashlib.sha256(octets).hexdigest()
