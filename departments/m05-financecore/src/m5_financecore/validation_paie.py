"""Harnais de validation de la paie : format `cas_paie.v1`, rejeu contre le moteur actuel, écart au cent par ligne,
campagne qualifiée seulement à ≥ 300 cas OFFICIELS à provenance vérifiée (`docs/architecture/BASE-FISCALE.md`).

Ce que le harnais est : un EXÉCUTEUR. Il prend des cas (entrées + retenues attendues d'un calculateur officiel,
WebRAS ou
PDOC), les rejoue contre les moteurs préparatoires de M5 et rapporte, ligne par ligne, l'écart en cents. Le seuil
d'acceptation est 0,00 $ : un seul cent d'écart sur une seule ligne d'un seul cas ferme la qualification.

Ce que le harnais n'est PAS : une source de cas. AUCUN cas officiel n'est fabriqué ici. Les cas livrés avec le dépôt
sont
marqués `fictif_pour_tests_du_harnais` (valeurs arbitraires, produites par le moteur lui-même : ils prouvent que le
harnais rejoue et détecte un écart, jamais que le moteur est juste) ; le mode de qualification les REFUSE. Tant que
`validation_paie/cas_officiels/` est vide, le statut honnête est « campagne officielle : 0/300 ».

« Provenance vérifiée » veut dire : source nommée (outil, version, date d'exécution, URL d'un hôte officiel), capture
dont
l'empreinte SHA-256 est celle du fichier du dépôt, auteur de la saisie et réviseur DISTINCTS, revue postérieure à la
saisie.
Cela ne prouve pas l'AUTHENTICITÉ de la capture (voir `docs/architecture/BASE-FISCALE.md`, « Limites »).

Module pur : aucune horloge, aucun réseau. Les captures se lisent sous une racine confinée.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from . import cotisations_rqap_ae_2026 as rqap_ae
from . import impot_federal_qc_2026 as federal
from . import impot_quebec_regulier as impot_qc
from . import verdicts_fiscal
from .base_fiscale import _ChargeurStrict

__all__ = [
    "NATURE_FICTIF",
    "NATURE_OFFICIEL",
    "SEUIL_CAS_OFFICIELS",
    "SEUIL_ECART",
    "Cas",
    "charger_cas",
    "charger_dossier",
    "construire_demandes",
    "executer_campagne",
    "qualifier_campagne",
    "rejouer_cas",
    "statut_campagne",
    "verifier_provenance",
]

SCHEMA = "cas_paie.v1"
NATURE_OFFICIEL = "officiel"
NATURE_FICTIF = "fictif_pour_tests_du_harnais"
SEUIL_CAS_OFFICIELS = 300
SEUIL_ECART = Decimal("0.00")
_LIGNES = (
    "rrq_palier1",
    "rrq_palier2",
    "rqap_salarie",
    "rqap_employeur",
    "ae_salarie",
    "ae_employeur",
    "impot_federal",
    "impot_quebec",
)
_OUTILS_OFFICIELS = frozenset({"WebRAS", "PDOC"})
_HOTES_OFFICIELS = ("revenuquebec.ca", "canada.ca")
_EXEMPTIONS = ("gratif_ou_retroactif", "exemption_speciale", "transfert_province", "taux_ae_reduit", "exonere")
_CUMULS = ("salaire_rrq", "rrq_palier1", "rrq_palier2", "rqap_salarie", "rqap_employeur", "ae_salarie", "ae_employeur")
_ENTREES = frozenset(
    {
        "annee",
        "date_paie",
        "province",
        "frequence",
        "periode_annuelle",
        "salaire_brut_periode",
        "credit_personnel_federal_td1",
        "exemptions",
        "cumuls_avant",
    }
)
_MONTANT = re.compile(r"^(?:0|[1-9][0-9]{0,11})\.[0-9]{2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PERSONNE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}$")
_ID_CAS = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TAILLE_MAX = 8 * 1024 * 1024
_TAILLE_CAPTURE_MAX = 16 * 1024 * 1024


def _v(code: str, detail: str) -> dict[str, str]:
    return verdicts_fiscal.construire_verdict(code, detail)


def _date_iso(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur):
        return None
    try:
        jour = date.fromisoformat(valeur)
    except ValueError:
        return None
    return jour if jour.isoformat() == valeur else None


def _texte(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


@dataclass(frozen=True)
class Cas:
    identifiant: str
    nature: str
    entrees: Mapping[str, Any]
    lignes: Mapping[str, Mapping[str, str]]
    source: Mapping[str, Any]
    saisie: Mapping[str, str]
    revue: Mapping[str, str] | None
    empreinte_entrees: str


# ---------------------------------------------------------------------------------------- chargement
def _valider_entrees(ident: str, e: Any) -> dict[str, str] | None:
    if not isinstance(e, dict) or set(e) != _ENTREES:
        return _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : entrées {sorted(_ENTREES)} exigées, rien d'autre")
    if type(e["annee"]) is not int or _date_iso(e["date_paie"]) is None or type(e["periode_annuelle"]) is not int:
        return _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : année, date de paie ou période annuelle mal typée")
    for cle in ("province", "frequence"):
        if not _texte(e[cle]):
            return _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : {cle} requis")
    for cle in ("salaire_brut_periode", "credit_personnel_federal_td1"):
        if not isinstance(e[cle], str) or _MONTANT.fullmatch(e[cle]) is None:
            return _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : {cle} doit être un montant texte à deux décimales")
    ex = e["exemptions"]
    if not isinstance(ex, dict) or set(ex) != set(_EXEMPTIONS) or any(type(ex[c]) is not bool for c in _EXEMPTIONS):
        return _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : `exemptions` doit déclarer EXPLICITEMENT {list(_EXEMPTIONS)}")
    cu = e["cumuls_avant"]
    if (
        not isinstance(cu, dict)
        or set(cu) != set(_CUMULS)
        or any(not isinstance(cu[c], str) or _MONTANT.fullmatch(cu[c]) is None for c in _CUMULS)
    ):
        return _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : `cumuls_avant` doit donner {list(_CUMULS)} en montants texte")
    return None


def _valider_lignes(ident: str, attendu: Any) -> dict[str, str] | None:
    lignes = attendu.get("lignes") if isinstance(attendu, dict) and set(attendu) == {"lignes"} else None
    if not isinstance(lignes, dict) or not lignes:
        return _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : `attendu.lignes` non vide exigé")
    for nom, ligne in lignes.items():
        if nom not in _LIGNES:
            return _v(
                "REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : ligne de retenue inconnue {nom!r} (connues : {list(_LIGNES)})"
            )
        if (
            not isinstance(ligne, dict)
            or set(ligne) != {"montant", "outil"}
            or not isinstance(ligne["montant"], str)
            or _MONTANT.fullmatch(ligne["montant"]) is None
            or not _texte(ligne["outil"])
        ):
            return _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : ligne {nom} = {{montant: texte à deux décimales, outil}}")
    return None


def _valider_cas(brut: Any) -> tuple[Cas | None, dict[str, str] | None]:
    if not isinstance(brut, dict):
        return None, _v("REJ-PAIEVAL-CAS-INVALIDE", "un cas doit être un objet")
    ident = brut.get("id", "?")
    if set(brut) != {"id", "nature", "entrees", "attendu", "source", "saisie", "revue"}:
        return None, _v(
            "REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : clés id, nature, entrees, attendu, source, saisie, revue exigées"
        )
    if not isinstance(ident, str) or _ID_CAS.fullmatch(ident) is None:
        return None, _v("REJ-PAIEVAL-CAS-INVALIDE", f"identifiant de cas illisible : {ident!r}")
    if brut["nature"] not in {NATURE_OFFICIEL, NATURE_FICTIF}:
        return None, _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : nature {NATURE_OFFICIEL!r} ou {NATURE_FICTIF!r}")
    for verifie in (_valider_entrees(ident, brut["entrees"]), _valider_lignes(ident, brut["attendu"])):
        if verifie is not None:
            return None, verifie
    source, saisie, revue = brut["source"], brut["saisie"], brut["revue"]
    if (
        not isinstance(source, dict)
        or set(source) != {"type", "executions"}
        or not isinstance(source["executions"], list)
    ):
        return None, _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : source {{type, executions}} mal formée")
    if source["type"] != ("calculateur_officiel" if brut["nature"] == NATURE_OFFICIEL else NATURE_FICTIF):
        return None, _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : le type de source contredit la nature du cas")
    if (
        not isinstance(saisie, dict)
        or set(saisie) != {"auteur", "le"}
        or not isinstance(saisie["auteur"], str)
        or _PERSONNE.fullmatch(saisie["auteur"]) is None
        or _date_iso(saisie["le"]) is None
    ):
        return None, _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : saisie {{auteur, le}} mal formée")
    if revue is not None and (
        not isinstance(revue, dict)
        or set(revue) != {"reviewer", "le"}
        or not isinstance(revue["reviewer"], str)
        or _PERSONNE.fullmatch(revue["reviewer"]) is None
        or _date_iso(revue["le"]) is None
    ):
        return None, _v("REJ-PAIEVAL-CAS-INVALIDE", f"{ident} : revue {{reviewer, le}} mal formée")
    canon = json.dumps(brut["entrees"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return Cas(
        identifiant=ident,
        nature=brut["nature"],
        entrees=json.loads(canon),
        lignes=json.loads(json.dumps(brut["attendu"]["lignes"])),
        source=json.loads(json.dumps(source)),
        saisie=dict(saisie),
        revue=dict(revue) if revue else None,
        empreinte_entrees=hashlib.sha256(canon.encode("utf-8")).hexdigest(),
    ), None


def charger_cas(
    chemin: Path | str | None = None, *, contenu_octets: bytes | None = None
) -> tuple[list[Cas] | None, dict[str, str] | None]:
    """Un fichier `cas_paie.v1` (clés `schema` et `cas`). `(cas, None)` ou `(None, premier refus)`. Identifiants de cas
    uniques dans le fichier ; entrées canoniques uniques aussi (un cas copié ne compte pas deux fois)."""
    try:
        if contenu_octets is None:
            if chemin is None:
                return None, _v("REJ-PAIEVAL-FORMAT-INVALIDE", "chemin ou octets requis")
            cible = Path(chemin)
            if cible.stat().st_size > _TAILLE_MAX:
                return None, _v("REJ-PAIEVAL-FORMAT-INVALIDE", "fichier de cas démesuré")
            contenu_octets = cible.read_bytes()
        if len(contenu_octets) > _TAILLE_MAX:
            return None, _v("REJ-PAIEVAL-FORMAT-INVALIDE", "fichier de cas démesuré")
        contenu = yaml.load(contenu_octets.decode("utf-8", errors="strict"), Loader=_ChargeurStrict)
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError, RecursionError) as erreur:
        return None, _v("REJ-PAIEVAL-FORMAT-INVALIDE", f"fichier de cas illisible ({type(erreur).__name__})")
    if (
        not isinstance(contenu, dict)
        or set(contenu) != {"schema", "cas"}
        or contenu["schema"] != SCHEMA
        or not isinstance(contenu["cas"], list)
    ):
        return None, _v("REJ-PAIEVAL-FORMAT-INVALIDE", f"schéma {SCHEMA} attendu, clés schema et cas seulement")
    cas: list[Cas] = []
    for brut in contenu["cas"]:
        unique, refus = _valider_cas(brut)
        if refus is not None:
            return None, refus
        assert unique is not None
        cas.append(unique)
    return _sans_doublon(cas)


def _sans_doublon(cas: list[Cas]) -> tuple[list[Cas] | None, dict[str, str] | None]:
    ids: set[str] = set()
    entrees: set[str] = set()
    for c in cas:
        if c.identifiant in ids:
            return None, _v("REJ-PAIEVAL-DOUBLON", f"identifiant de cas en double : {c.identifiant}")
        if c.empreinte_entrees in entrees:
            return None, _v(
                "REJ-PAIEVAL-DOUBLON", f"{c.identifiant} : mêmes entrées qu'un autre cas (compte une seule fois)"
            )
        ids.add(c.identifiant)
        entrees.add(c.empreinte_entrees)
    return cas, None


def charger_dossier(dossier: Path | str) -> tuple[list[Cas] | None, dict[str, str] | None]:
    """Tous les `*.yaml` d'un dossier, triés par nom. Un dossier absent ou vide donne une liste vide (honnête : zéro
    cas),
    jamais un cas inventé. Doublons refusés d'un fichier à l'autre."""
    racine = Path(dossier)
    if not racine.is_dir():
        return [], None
    tous: list[Cas] = []
    for fichier in sorted(racine.glob("*.yaml")):
        cas, refus = charger_cas(fichier)
        if refus is not None:
            return None, {**refus, "detail": f"{fichier.name} : {refus['detail']}"}
        assert cas is not None
        tous.extend(cas)
    return _sans_doublon(tous)


# ------------------------------------------------------------------------------------------ provenance
def _capture_verifiee(execution: Mapping[str, Any], racine: Path | None) -> str | None:
    capture = execution.get("capture")
    if racine is None or not isinstance(capture, dict) or set(capture) != {"chemin", "sha256"}:
        return "capture (chemin, sha256) absente ou racine des captures non fournie"
    chemin, attendu = capture["chemin"], capture["sha256"]
    if not isinstance(chemin, str) or not isinstance(attendu, str) or _SHA256.fullmatch(attendu) is None:
        return "capture mal formée"
    posix = PurePosixPath(chemin)
    if not chemin or posix.is_absolute() or ".." in posix.parts or "\\" in chemin:
        return "chemin de capture invalide"
    try:
        base = racine.resolve(strict=True)
        cible = (base / Path(*posix.parts)).resolve(strict=True)
        cible.relative_to(base)
        if not cible.is_file() or cible.stat().st_size > _TAILLE_CAPTURE_MAX:
            return "capture absente ou démesurée"
        empreinte = hashlib.sha256()
        with cible.open("rb") as fichier:
            for bloc in iter(lambda: fichier.read(64 * 1024), b""):
                empreinte.update(bloc)
    except (OSError, ValueError):
        return "capture absente, illisible ou hors de la racine"
    if empreinte.hexdigest() != attendu:
        return "empreinte de la capture divergente"
    return None


def verifier_provenance(cas: Cas, racine_captures: Path | str | None) -> dict[str, str] | None:
    """`None` si la provenance d'un cas OFFICIEL est vérifiée ; sinon le refus, qui dit quoi manque."""
    if cas.nature != NATURE_OFFICIEL:
        return _v("REJ-PAIEVAL-FICTIF-REFUSE", f"{cas.identifiant} : cas fictif, aucune provenance officielle")

    def manque(raison: str) -> dict[str, str]:
        return _v("REJ-PAIEVAL-PROVENANCE-NON-VERIFIEE", f"{cas.identifiant} : {raison}")

    saisie_le = _date_iso(cas.saisie["le"])
    executions = cas.source["executions"]
    if not executions:
        return manque("aucune exécution de calculateur officiel citée")
    racine = Path(racine_captures) if racine_captures is not None else None
    outils: set[str] = set()
    for execution in executions:
        if not isinstance(execution, dict) or set(execution) != {
            "outil",
            "version",
            "date_execution",
            "url",
            "capture",
        }:
            return manque("exécution {outil, version, date_execution, url, capture} mal formée")
        if execution["outil"] not in _OUTILS_OFFICIELS:
            return manque(f"outil {execution['outil']!r} hors de {sorted(_OUTILS_OFFICIELS)}")
        if not _texte(execution["version"]):
            return manque("version du calculateur absente")
        jour = _date_iso(execution["date_execution"])
        if jour is None or saisie_le is None or jour > saisie_le:
            return manque("date d'exécution invalide ou postérieure à la saisie")
        url = execution["url"]
        # hôte lu à la main (pas d'urllib dans M5) ; un identifiant « utilisateur@ » dans l'URL est refusé
        trouve = (
            re.match(r"^https://([A-Za-z0-9.-]+)(?::[0-9]{1,5})?(?:[/?#]|$)", url) if isinstance(url, str) else None
        )
        hote = trouve.group(1).lower() if trouve else ""
        if not hote or not any(hote == h or hote.endswith("." + h) for h in _HOTES_OFFICIELS):
            return manque("URL https d'un hôte officiel (revenuquebec.ca, canada.ca) requise")
        refus_capture = _capture_verifiee(execution, racine)
        if refus_capture is not None:
            return manque(refus_capture)
        outils.add(execution["outil"])
    if any(ligne["outil"] not in outils for ligne in cas.lignes.values()):
        return manque("une ligne attendue cite un outil sans exécution documentée")
    if cas.revue is None:
        return manque("aucun réviseur")
    if cas.revue["reviewer"].casefold() == cas.saisie["auteur"].casefold():
        return manque("l'auteur de la saisie ne peut pas être le réviseur")
    revue_le = _date_iso(cas.revue["le"])
    if revue_le is None or saisie_le is None or revue_le < saisie_le:
        return manque("revue antérieure à la saisie")
    return None


# --------------------------------------------------------------------------------------------- rejeu
def construire_demandes(entrees: Mapping[str, Any]) -> dict[str, Any]:
    """Les quatre demandes déclaratives des moteurs, depuis les entrées neutres d'un cas. Les preuves jointes sont
    marquées `fictif: true` : le moteur les exige, le harnais n'en fabrique aucune d'authentique."""
    salaire = entrees["salaire_brut_periode"]
    cumuls = entrees["cumuls_avant"]
    ex = entrees["exemptions"]
    contexte = {
        "annee": entrees["annee"],
        "date_paie": entrees["date_paie"],
        "juridiction": entrees["province"],
        "frequence": entrees["frequence"],
        "periode_annuelle": entrees["periode_annuelle"],
    }

    def preuve(nom: str) -> dict[str, Any]:
        return {"id": f"harnais-{nom}", "sha256": "0" * 64, "fictif": True}

    zero = "0.00"
    rrq = {
        **contexte,
        "emploi_continu": True,
        "paiement_regulier_fixe": True,
        "gratif_ou_retroactif": ex["gratif_ou_retroactif"],
        "transfert_rpc_vers_rrq": ex["transfert_province"],
        "exemption_speciale": ex["exemption_speciale"],
        "assujettissement_qc": True,
        "pm": 12,
        "preuve_pm": preuve("pm"),
        "salaire_rrq_periode": salaire,
        "salaire_rrq_cumul_avant": cumuls["salaire_rrq"],
        "rrq_palier1_cumul_avant": cumuls["rrq_palier1"],
        "rrq_palier2_cumul_avant": cumuls["rrq_palier2"],
        "preuve_assiette": preuve("assiette-rrq"),
        "preuve_cumuls": preuve("cumuls-rrq"),
        "preuve_calendrier": preuve("calendrier"),
    }
    cotisations = {
        **contexte,
        "paiement_regulier_fixe": True,
        "gratif_ou_retroactif": ex["gratif_ou_retroactif"],
        "transfert_province": ex["transfert_province"],
        "taux_ae_reduit": ex["taux_ae_reduit"],
        "exemption_speciale": ex["exemption_speciale"],
        "assujettissement_qc": True,
        "salaire_en_argent_confirme": True,
        "assiette_rqap_periode": salaire,
        "rqap_salarie_cumul_avant": cumuls["rqap_salarie"],
        "rqap_employeur_cumul_avant": cumuls["rqap_employeur"],
        "assiette_ae_periode": salaire,
        "ae_salarie_cumul_avant": cumuls["ae_salarie"],
        "ae_employeur_cumul_avant": cumuls["ae_employeur"],
        "preuve_assiette_rqap": preuve("assiette-rqap"),
        "preuve_cumul_rqap_salarie": preuve("rqap-salarie"),
        "preuve_cumul_rqap_employeur": preuve("rqap-employeur"),
        "preuve_assiette_ae": preuve("assiette-ae"),
        "preuve_cumul_ae_salarie": preuve("ae-salarie"),
        "preuve_cumul_ae_employeur": preuve("ae-employeur"),
    }
    impot = {
        **contexte,
        "paiement_regulier_fixe": True,
        "gratif_ou_retroactif": ex["gratif_ou_retroactif"],
        "remuneration_variable": False,
        "exonere": ex["exonere"],
        "transfert_province": ex["transfert_province"],
        "resident": True,
        "G": salaire,
        "F": zero,
        "D": salaire,
        "CSA": zero,
        "J_annuel": zero,
        "J3": zero,
        "J_determined_after_period_1": False,
        "J1_annuel": zero,
        "J2": zero,
        "J1_determined_after_period_1": False,
        "K1_annuel": zero,
        "K2": zero,
        "K1_determined_after_period_1": False,
        "E1": zero,
        "E2": zero,
        "Q": zero,
        "Q1": zero,
        "fonds_travailleurs_total_annuel_programme": zero,
        "L": zero,
    }
    fed = {
        **contexte,
        "pm": 12,
        "emploi_annuel_continu": True,
        "resident": True,
        "revenu_brut_emploi": salaire,
        "TC": entrees["credit_personnel_federal_td1"],
        "F": zero,
        "F2": zero,
        "HD": zero,
        "F1": zero,
        "U1": zero,
        "K3": zero,
        "LCF": zero,
        "L": zero,
        "preuves": {
            nom: preuve(nom)
            for nom in ("td1", "emploi_annuel_continu", "assiettes_egales", "residence", "zeros_hors_scope")
        },
    }
    return {"entree_rrq": rrq, "entree_impot_qc": impot, "entree_rqap_ae": cotisations, "demande_federale": fed}


def _lignes_du_moteur(rapport: Mapping[str, Any]) -> dict[str, str]:
    postes = rapport["postes_composants"]
    return {
        "rrq_palier1": postes["rrq"]["cotisation_palier1"],
        "rrq_palier2": postes["rrq"]["cotisation_palier2"],
        "rqap_salarie": postes["rqap_ae"]["rqap_salarie"],
        "rqap_employeur": postes["rqap_ae"]["rqap_employeur"],
        "ae_salarie": postes["rqap_ae"]["ae_salarie"],
        "ae_employeur": postes["rqap_ae"]["ae_employeur"],
        "impot_federal": rapport["retenue_impot_federal"],
        "impot_quebec": postes["impot_qc"]["retenue_qc_preparatoire"],
    }


def rejouer_cas(cas: Cas) -> dict[str, Any]:
    """Rejoue UN cas contre le moteur actuel. Statut : `OK` (écart 0,00 $ sur toutes les lignes attendues), `ECART`
    (au moins une ligne s'écarte), `MOTEUR_REFUSE` (le moteur refuse l'entrée : hors périmètre ou invalide)."""
    base = {"id": cas.identifiant, "nature": cas.nature, "empreinte_entrees": cas.empreinte_entrees}
    try:
        rapport, refus = federal.calculer_retenue_federale_qc_preparatoire(**construire_demandes(cas.entrees))
    except (KeyError, TypeError, ValueError) as erreur:
        return {
            **base,
            "statut": "MOTEUR_REFUSE",
            "refus": _v("REJ-PAIEVAL-MOTEUR-REFUSE", type(erreur).__name__),
            "lignes": {},
        }
    if refus is not None or rapport is None:
        return {
            **base,
            "statut": "MOTEUR_REFUSE",
            "lignes": {},
            "refus": _v("REJ-PAIEVAL-MOTEUR-REFUSE", f"{(refus or {}).get('code')} : {(refus or {}).get('detail')}"),
        }
    obtenu = _lignes_du_moteur(rapport)
    lignes: dict[str, Any] = {}
    tout_ok = True
    for nom in _LIGNES:
        if nom not in cas.lignes:
            continue
        attendu = Decimal(cas.lignes[nom]["montant"])
        reel = Decimal(obtenu[nom])
        ecart = reel - attendu
        ok = abs(ecart) <= SEUIL_ECART
        tout_ok = tout_ok and ok
        lignes[nom] = {
            "attendu": cas.lignes[nom]["montant"],
            "obtenu": obtenu[nom],
            "ecart": format(ecart, ".2f"),
            "ecart_cents": int(ecart * 100),
            "ok": ok,
        }
    return {**base, "statut": "OK" if tout_ok else "ECART", "lignes": lignes}


# ------------------------------------------------------------------------------------------- campagne
def executer_campagne(cas: Iterable[Cas], *, racine_captures: Path | str | None = None) -> dict[str, Any]:
    """Rejoue tous les cas et rapporte. N'exclut rien (un cas fictif est rejoué et marqué fictif) ; la qualification est
    une autre décision (`qualifier_campagne`)."""
    liste = list(cas)
    resultats = []
    for c in liste:
        resultat = rejouer_cas(c)
        if c.nature == NATURE_OFFICIEL:
            refus = verifier_provenance(c, racine_captures)
            resultat["provenance_verifiee"] = refus is None
            if refus is not None:
                resultat["provenance_refus"] = refus
        else:
            resultat["provenance_verifiee"] = False
        resultats.append(resultat)
    officiels = [r for r in resultats if r["nature"] == NATURE_OFFICIEL]
    qualifiants = [r for r in officiels if r["statut"] == "OK" and r["provenance_verifiee"]]
    nb_lignes = sum(len(r["lignes"]) for r in resultats)
    nb_ecarts = sum(1 for r in resultats for ligne in r["lignes"].values() if not ligne["ok"])
    return {
        "schema": "m5-campagne-paie/1",
        "moteur": {
            "federal": federal.HASH_PARAMETRES,
            "rqap_ae": rqap_ae.HASH_PARAMETRES,
            "impot_qc": impot_qc.HASH_SNAPSHOT_PARAMETRES,
            "qualification_regles": "NON_QUALIFIEE_POUR_PAIE",
        },
        "seuil_ecart": format(SEUIL_ECART, ".2f"),
        "cas": resultats,
        "totaux": {
            "cas": len(resultats),
            "officiels": len(officiels),
            "fictifs": len(resultats) - len(officiels),
            "officiels_qualifiants": len(qualifiants),
            "lignes_comparees": nb_lignes,
            "lignes_en_ecart": nb_ecarts,
            "moteur_refuse": sum(1 for r in resultats if r["statut"] == "MOTEUR_REFUSE"),
        },
        "statut_campagne": f"campagne officielle : {len(qualifiants)}/{SEUIL_CAS_OFFICIELS}",
    }


def qualifier_campagne(
    cas: Iterable[Cas], *, racine_captures: Path | str | None
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """MODE DE QUALIFICATION. Refuse tout cas fictif (un seul suffit), exige ≥ 300 cas officiels, TOUS à provenance
    vérifiée et à écart 0,00 $ sur chaque ligne. Rend le rapport complet si la campagne est qualifiée ; sinon le
    premier refus. La qualification d'une campagne ne qualifie pas les règles pour la paie (le moteur reste
    `NON_QUALIFIEE_POUR_PAIE` jusqu'à la revue du CPA)."""
    liste = list(cas)
    for c in liste:
        if c.nature != NATURE_OFFICIEL:
            return None, _v(
                "REJ-PAIEVAL-FICTIF-REFUSE", f"{c.identifiant} : le mode de qualification refuse les cas fictifs"
            )
    rapport = executer_campagne(liste, racine_captures=racine_captures)
    for r in rapport["cas"]:
        if not r["provenance_verifiee"]:
            return None, r["provenance_refus"]
        if r["statut"] == "MOTEUR_REFUSE":
            return None, r["refus"]
        if r["statut"] == "ECART":
            ecarts = {n: ligne["ecart"] for n, ligne in r["lignes"].items() if not ligne["ok"]}
            return None, _v("REJ-PAIEVAL-ECART", f"{r['id']} : écart non nul {ecarts}")
    n = rapport["totaux"]["officiels_qualifiants"]
    if n < SEUIL_CAS_OFFICIELS:
        return None, _v(
            "REJ-PAIEVAL-CAMPAGNE-INSUFFISANTE",
            f"campagne officielle : {n}/{SEUIL_CAS_OFFICIELS} — au moins {SEUIL_CAS_OFFICIELS} cas officiels requis",
        )
    return {**rapport, "qualifiee": True}, None


def statut_campagne(cas_officiels: Iterable[Cas], *, racine_captures: Path | str | None) -> dict[str, Any]:
    """Le statut HONNÊTE d'un dossier de cas officiels : jamais « qualifiée » sans les 300 cas, la provenance
    vérifiée et
    l'écart nul sur chaque ligne. `refus` dit pourquoi elle ne l'est pas."""
    liste = list(cas_officiels)
    rapport = executer_campagne(liste, racine_captures=racine_captures)
    totaux = rapport["totaux"]
    qualifiee, refus = qualifier_campagne(liste, racine_captures=racine_captures)
    return {
        "statut": rapport["statut_campagne"],
        "qualifiee": qualifiee is not None,
        "cas_officiels": totaux["officiels"],
        "cas_officiels_qualifiants": totaux["officiels_qualifiants"],
        "cas_fictifs": totaux["fictifs"],
        "lignes_en_ecart": totaux["lignes_en_ecart"],
        "seuil_cas": SEUIL_CAS_OFFICIELS,
        "seuil_ecart": rapport["seuil_ecart"],
        "moteur": rapport["moteur"],
        "refus": refus,
    }
