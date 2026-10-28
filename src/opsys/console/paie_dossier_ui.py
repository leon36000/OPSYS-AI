"""Console privée des dossiers de paie préparatoires : propriétaire actif seulement, aucune paie officielle.

Chaque action passe par `metier.executer` et les outils M5 `m5_*_dossier_paie` : le propriétaire est revérifié en base
avant et après l'appel, le CSRF est exigé sur toute écriture, les corps sont bornés et toute valeur
affichée est échappée.
Les écritures ne rendent que des reçus sans montant (l'idempotence partagée les conserve en clair) ; les montants ne
sortent que des lectures, avec `Cache-Control: no-store`.

Le formulaire HTML dépasse la limite générale de 20 champs de `_formulaire` : ce module lit donc lui-même un corps
borné à 64 Kio avec sa propre limite de champs. Rien n'est déduit en silence : une case décochée est une déclaration
négative, un montant laissé vide est INCONNU, et seules les cases « tout nul » écrivent explicitement 0.00.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import Connection

from .. import identite
from . import metier, pages, securite
from .securite import Session

_LIMITE_CORPS = 64 * 1024
_MAX_CHAMPS = 160
_ID32 = frozenset("0123456789abcdef")
_STATUTS = {
    "ACCES-REFUSE": 403,
    "INTROUVABLE": 404,
    "VERSION-PERIMEE": 409,
    "MUTATION-CONFLIT": 409,
    "SOURCE-MODIFIEE": 409,
    "CUMUL-PERIME": 409,
    "DOSSIER-REVU": 409,
    "DOSSIER-DOUBLON": 409,
    "ETAT-INVALIDE": 409,
    "EXPORT-REFUSE": 409,
    "SOURCE-REFUSEE": 409,
    "STOCKAGE-INDISPONIBLE": 503,
    "DONNEES-CORROMPUES": 500,
}
_PIECES = (
    ("td1_federal", "TD1 fédéral (crédits personnels)"),
    ("tp1015_3_qc", "TP-1015.3 (retenues Québec)"),
    ("registre_cumuls", "Registre des cumuls annuels"),
    ("calendrier_paie", "Calendrier de paie 2026"),
    ("attestation_pm", "Attestation PM = 12 (RRQ)"),
    ("attestation_assiettes", "Attestation des assiettes égales au brut"),
    ("attestation_emploi", "Attestation d'emploi annuel continu"),
    ("attestation_residence", "Attestation de résidence au Québec"),
    ("attestation_zeros", "Attestation des déductions et crédits hors périmètre nuls"),
)
_ATTESTATIONS = (
    ("emploi_continu", "Emploi annuel continu"),
    ("resident_qc", "Résident du Québec"),
    ("assujettissement_qc", "Assujetti au régime du Québec (RRQ, RQAP)"),
    ("paiement_regulier_fixe", "Paiement régulier fixe"),
    ("aucune_gratification_ni_retroactif", "Aucune gratification ni paie rétroactive"),
    ("aucun_transfert_province_ou_rpc", "Aucun transfert de province ni de régime de pensions"),
    ("aucune_exemption_ni_exoneration", "Aucune exemption ni exonération"),
    ("taux_ae_normal", "Taux d'assurance-emploi normal (non réduit)"),
    ("salaire_en_argent", "Salaire versé en argent"),
    ("aucune_remuneration_variable", "Aucune rémunération variable"),
    ("assiettes_egales_au_brut", "Assiettes RRQ, RQAP, AE, impôts égales au brut régulier"),
    (
        "aucune_autre_remuneration_ni_avantage",
        "Aucune autre rémunération, surtemps, vacances à part ni avantage imposable",
    ),
    ("pm_12", "PM (mois de cotisation) égal à 12"),
)
_FED_NULS = ("F", "F2", "HD", "F1", "U1", "K3", "LCF", "L")
_QC_MONTANTS = (
    "F",
    "J_annuel",
    "J3",
    "J1_annuel",
    "J2",
    "K1_annuel",
    "K2",
    "E1",
    "E2",
    "Q",
    "Q1",
    "fonds_travailleurs_total_annuel_programme",
    "L",
)
_QC_NULS = tuple(c for c in _QC_MONTANTS if c != "K1_annuel")
_QC_MARQ = ("J_determined_after_period_1", "J1_determined_after_period_1", "K1_determined_after_period_1")
_CUMULS = (
    "salaire_rrq_cumul_avant",
    "rrq_palier1_cumul_avant",
    "rrq_palier2_cumul_avant",
    "rqap_salarie_cumul_avant",
    "rqap_employeur_cumul_avant",
    "ae_salarie_cumul_avant",
    "ae_employeur_cumul_avant",
)
_CHAMPS_FORMULAIRE = frozenset(
    {
        "csrf",
        "action",
        "mutation_id",
        "employee_person_id",
        "employeur_reference",
        "debut",
        "fin",
        "fuseau",
        "date_paie",
        "premiere_date_paie_annee",
        "periode_annuelle",
        "hypothese_arrondi",
        "regime_ccq",
        "fictif",
        "tc",
        "fed_zero",
        "qc_zero",
        "k1_annuel",
        "cumuls_origine",
        "cum_ref_confirmation",
        "sim_dossier_id",
        "sim_numero",
        "sim_hash",
        "autres_retenues_montant",
        "autres_retenues_ref",
        "autres_couts_montant",
        "autres_couts_ref",
        "fss_secteur",
        "fss_masse",
        "fss_base",
        "fss_ref",
        "cnesst_taux",
        "cnesst_base",
        "cnesst_ref",
        "normes_assujetti",
        "normes_ref",
        "fdrcmo_masse",
        "fdrcmo_ref",
        "empreinte_apercu",
        "version_attendue",
        "type_version",
        "motif",
        "entrees_json",
    }
    | {f"att_{c}" for c, _ in _ATTESTATIONS}
    | {f"piece_{s}" for s, _ in _PIECES}
    | {f"sha_{s}" for s, _ in _PIECES}
    | {f"fed_{c}" for c in _FED_NULS}
    | {f"qc_{c}" for c in _QC_NULS}
    | {f"qcm_{c}" for c in _QC_MARQ}
    | {f"cum_{c}" for c in _CUMULS}
)


async def _corps(request: Request) -> bytes:
    annonce = request.headers.get("content-length", "")
    if annonce.isdigit() and int(annonce) > _LIMITE_CORPS:
        raise HTTPException(413, "requête trop volumineuse")
    morceaux, taille = [], 0
    async for morceau in request.stream():
        taille += len(morceau)
        if taille > _LIMITE_CORPS:
            raise HTTPException(413, "requête trop volumineuse")
        morceaux.append(morceau)
    return b"".join(morceaux)


async def _formulaire_large(request: Request) -> dict[str, str]:
    corps = await _corps(request)
    try:
        champs = parse_qs(corps.decode("utf-8"), keep_blank_values=True, max_num_fields=_MAX_CHAMPS)
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(400, "formulaire illisible") from exc
    if any(len(valeurs) != 1 for valeurs in champs.values()):
        raise HTTPException(400, "champ répété refusé")
    return {cle: valeurs[0] for cle, valeurs in champs.items()}


async def _json_borne(request: Request) -> dict[str, Any]:
    corps = await _corps(request)
    try:
        donnees = json.loads(corps) if corps.strip() else {}
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise HTTPException(400, "corps JSON invalide") from exc
    if not isinstance(donnees, dict):
        raise HTTPException(400, "objet JSON attendu")
    return donnees


def _verdict_depuis_details(details: object) -> dict[str, Any] | None:
    """Relit le verdict JSON qu'un refus M5 du dossier de paie a laissé dans `details`."""
    if not isinstance(details, str):
        return None
    try:
        verdict = json.loads(details)
    except ValueError:
        return None
    if (
        isinstance(verdict, dict)
        and set(verdict) == {"code", "detail"}
        and str(verdict["code"]).startswith("REJ-DOSSIER-PAIE-")
    ):
        return verdict
    return None


def _vide_en_none(valeur: str) -> str | None:
    valeur = valeur.strip()
    return valeur or None


def entrees_depuis_formulaire(data: Mapping[str, str]) -> tuple[str, dict[str, Any]]:
    """Traduit le formulaire plat en `entrees` (jamais de défaut silencieux). Lève 400 sur un champ inattendu."""
    inconnus = set(data) - _CHAMPS_FORMULAIRE
    if inconnus:
        raise HTTPException(400, "champ de formulaire inattendu")
    texte = lambda cle: data.get(cle, "").strip()  # noqa: E731
    try:
        periode = int(texte("periode_annuelle"))
    except ValueError as exc:
        raise HTTPException(400, "période annuelle entière requise") from exc
    fed = {"TC": texte("tc")}
    qc = {"K1_annuel": texte("k1_annuel")}
    for c in _FED_NULS:
        fed[c] = "0.00" if data.get("fed_zero") == "on" else texte(f"fed_{c}")
    for c in _QC_NULS:
        qc[c] = "0.00" if data.get("qc_zero") == "on" else texte(f"qc_{c}")
    for c in _QC_MARQ:
        qc[c] = data.get(f"qcm_{c}") == "on"
    origine = texte("cumuls_origine")
    cumuls_valeurs = {c: ("0.00" if origine == "NUL_PERIODE_1" else texte(f"cum_{c}")) for c in _CUMULS}
    simulee = None
    if origine == "SIMULE_VERSION_PRECEDENTE":
        try:
            numero = int(texte("sim_numero"))
        except ValueError as exc:
            raise HTTPException(400, "numéro de version simulée entier requis") from exc
        simulee = {"dossier_id": texte("sim_dossier_id"), "numero_version": numero, "hash_version": texte("sim_hash")}
        cumuls_valeurs = {c: "0.00" for c in _CUMULS}  # placeholders : le service les remplace par la version source
    sha = lambda s: _vide_en_none(data.get(f"sha_{s}", ""))  # noqa: E731
    autres_r, autres_c = texte("autres_retenues_montant"), texte("autres_couts_montant")
    fss = (
        None
        if not (texte("fss_secteur") or texte("fss_masse"))
        else {
            "secteur": texte("fss_secteur"),
            "masse_salariale_estimative_cad": texte("fss_masse"),
            "base_estimation": texte("fss_base"),
            "reference": texte("fss_ref"),
        }
    )
    cnesst = (
        None
        if not texte("cnesst_taux")
        else {
            "taux_versement_pour_100": texte("cnesst_taux"),
            "base_excedent": texte("cnesst_base"),
            "reference": texte("cnesst_ref"),
        }
    )
    normes = None
    if texte("normes_assujetti") in {"oui", "non"}:
        normes = {"assujetti": texte("normes_assujetti") == "oui", "reference": texte("normes_ref")}
    fdrcmo = (
        None
        if not texte("fdrcmo_masse")
        else {
            "masse_salariale_annee_cad": texte("fdrcmo_masse"),
            "reference": texte("fdrcmo_ref"),
        }
    )
    employeur = (
        None
        if all(bloc is None for bloc in (fss, cnesst, normes, fdrcmo))
        else {
            "fss": fss,
            "cnesst": cnesst,
            "normes_travail": normes,
            "fdrcmo": fdrcmo,
        }
    )
    entrees = {
        "schema": "opsys.dossier-paie-entrees/v1",
        "fictif": data.get("fictif") == "on",
        "employeur_reference": texte("employeur_reference"),
        "periode": {
            "annee": 2026,
            "periode_annuelle": periode,
            "debut": texte("debut"),
            "fin": texte("fin"),
            "fuseau": texte("fuseau"),
            "date_paie": texte("date_paie"),
            "premiere_date_paie_annee": texte("premiere_date_paie_annee"),
        },
        "arrondi": {"politique": "centime_demi_superieur", "hypothese": texte("hypothese_arrondi")},
        "classification": {"regime_ccq": texte("regime_ccq")},
        "attestations": {c: data.get(f"att_{c}") == "on" for c, _ in _ATTESTATIONS},
        "pieces": {s: {"reference": texte(f"piece_{s}"), "sha256": sha(s)} for s, _ in _PIECES},
        "credits_federal": fed,
        "credits_qc": qc,
        "cumuls_avant": {
            "origine": origine,
            "valeurs": cumuls_valeurs,
            "source_simulee": simulee,
            "reference_confirmation": _vide_en_none(texte("cum_ref_confirmation"))
            if origine == "CONFIRME_AUTORITE_HUMAINE"
            else None,
        },
        "autres_retenues_employe": None
        if not autres_r
        else {"montant": autres_r, "reference": texte("autres_retenues_ref")},
        "autres_couts_employeur": None
        if not autres_c
        else {"montant": autres_c, "reference": texte("autres_couts_ref")},
        "parametres_employeur": employeur,
    }
    return texte("employee_person_id"), entrees


def valeurs_depuis_entrees(employee_person_id: str, entrees: Mapping[str, Any]) -> dict[str, Any]:
    """Pré-remplissage du formulaire depuis des entrées conservées (correction, période suivante)."""
    p, att = entrees["periode"], entrees["attestations"]
    v: dict[str, Any] = {
        "employee_person_id": employee_person_id,
        "employeur_reference": entrees["employeur_reference"],
        "debut": p["debut"],
        "fin": p["fin"],
        "fuseau": p["fuseau"],
        "date_paie": p["date_paie"],
        "premiere_date_paie_annee": p["premiere_date_paie_annee"],
        "periode_annuelle": p["periode_annuelle"],
        "hypothese_arrondi": entrees["arrondi"]["hypothese"],
        "regime_ccq": entrees["classification"]["regime_ccq"],
        "fictif": entrees["fictif"],
        "tc": entrees["credits_federal"]["TC"],
        "k1_annuel": entrees["credits_qc"]["K1_annuel"],
        "cumuls_origine": entrees["cumuls_avant"]["origine"],
        "cum_ref_confirmation": entrees["cumuls_avant"]["reference_confirmation"] or "",
    }
    for c, _ in _ATTESTATIONS:
        v[f"att_{c}"] = att[c]
    for s, _ in _PIECES:
        v[f"piece_{s}"] = entrees["pieces"][s]["reference"]
        v[f"sha_{s}"] = entrees["pieces"][s]["sha256"] or ""
    fed, qc = entrees["credits_federal"], entrees["credits_qc"]
    v["fed_zero"] = all(fed[c] == "0.00" for c in _FED_NULS)
    v["qc_zero"] = all(qc[c] == "0.00" for c in _QC_NULS)
    for c in _FED_NULS:
        v[f"fed_{c}"] = fed[c]
    for c in _QC_NULS:
        v[f"qc_{c}"] = qc[c]
    for c in _QC_MARQ:
        v[f"qcm_{c}"] = qc[c]
    for c in _CUMULS:
        v[f"cum_{c}"] = entrees["cumuls_avant"]["valeurs"][c]
    simulee = entrees["cumuls_avant"]["source_simulee"]
    if simulee:
        v.update(
            sim_dossier_id=simulee["dossier_id"], sim_numero=simulee["numero_version"], sim_hash=simulee["hash_version"]
        )
    ret, cou, emp = (
        entrees["autres_retenues_employe"],
        entrees["autres_couts_employeur"],
        entrees["parametres_employeur"] or {},
    )
    v.update(
        autres_retenues_montant=ret["montant"] if ret else "",
        autres_retenues_ref=ret["reference"] if ret else "",
        autres_couts_montant=cou["montant"] if cou else "",
        autres_couts_ref=cou["reference"] if cou else "",
    )
    fss, cnesst, normes, fdrcmo = emp.get("fss"), emp.get("cnesst"), emp.get("normes_travail"), emp.get("fdrcmo")
    v.update(
        fss_secteur=fss["secteur"] if fss else "",
        fss_masse=fss["masse_salariale_estimative_cad"] if fss else "",
        fss_base=fss["base_estimation"] if fss else "",
        fss_ref=fss["reference"] if fss else "",
        cnesst_taux=cnesst["taux_versement_pour_100"] if cnesst else "",
        cnesst_base=cnesst["base_excedent"] if cnesst else "",
        cnesst_ref=cnesst["reference"] if cnesst else "",
        normes_assujetti="" if not normes else ("oui" if normes["assujetti"] else "non"),
        normes_ref=normes["reference"] if normes else "",
        fdrcmo_masse=fdrcmo["masse_salariale_annee_cad"] if fdrcmo else "",
        fdrcmo_ref=fdrcmo["reference"] if fdrcmo else "",
    )
    return v


def _valeurs_de_refus(entrees: Mapping[str, Any], employe: str, data: Mapping[str, str]) -> dict[str, Any]:
    """Re-remplit le formulaire refusé avec ce que l'humain a saisi (jamais de valeur inventée)."""
    try:
        return valeurs_depuis_entrees(employe, entrees)
    except (KeyError, TypeError):
        return dict(data)


def _prochaine_periode(valeurs: dict[str, Any]) -> dict[str, Any]:
    """Même employé, 14 jours plus tard, cumuls repris de la version simulée : l'humain relit tout avant l'aperçu."""
    suivante = dict(valeurs)
    for cle in ("debut", "fin", "date_paie"):
        suivante[cle] = (date.fromisoformat(valeurs[cle]) + timedelta(days=14)).isoformat()
    suivante["periode_annuelle"] = int(valeurs["periode_annuelle"]) + 1
    return suivante


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    formulaire: Callable[[Request], Any],
    objet_json: Callable[[Request], Any],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
) -> APIRouter:
    del formulaire, objet_json  # limites générales trop basses pour ce formulaire : lecteurs bornés propres au module
    router = APIRouter(tags=["dossiers de paie préparatoires"])
    base = f"{prefixe}/finance/paie/dossiers"
    e = pages.e

    def proprietaire(cnx: Connection, session: Session) -> identite.Personne:
        personne = identite.personne_active(cnx, session.utilisateur)
        if session.expire <= datetime.now(UTC).timestamp() or personne is None or "nathan_owner" not in personne.roles:
            raise HTTPException(403, "dossiers de paie réservés au propriétaire actif")
        return personne

    def verdict_http(verdict: Mapping[str, Any]) -> int:
        code = str(verdict.get("code", ""))
        court = code.removeprefix("REJ-DOSSIER-PAIE-")
        return _STATUTS.get(court, 400)

    def appeler(
        session: Session, nom: str, arguments: dict[str, Any], mutation_id: str | None = None
    ) -> tuple[Any, dict[str, Any] | None]:
        """(résultat, None) ou (None, verdict) ; propriétaire revérifié avant ET après l'appel."""
        with cnx_factory() as cnx:
            proprietaire(cnx, session)
            try:
                reponse = metier.executer(cnx, deps, session, nom, arguments, mutation_id=mutation_id)
            except PermissionError as exc:
                raise HTTPException(403, "accès refusé") from exc
            except KeyError as exc:
                raise HTTPException(404, "action indisponible") from exc
            except ValueError as exc:
                raise HTTPException(409 if "conflit" in str(exc).lower() else 400, "demande refusée") from exc
            proprietaire(cnx, session)
        if reponse.get("ok") is True:
            corps = reponse.get("resultat")
            if isinstance(corps, Mapping) and corps.get("accepte") is True:
                return corps["resultat"], None
            verdict = corps.get("verdict") if isinstance(corps, Mapping) else None
            return None, dict(verdict) if isinstance(verdict, Mapping) else {
                "code": "REJ-DOSSIER-PAIE-REFUSE",
                "detail": "refus",
            }
        verdict = _verdict_depuis_details(reponse.get("details"))
        if verdict is None:
            erreur = str(reponse.get("erreur", "refus"))
            return None, {"code": "REJ-DOSSIER-PAIE-REFUSE", "detail": erreur}
        return None, verdict

    def reponse_html(session: Session, titre: str, contenu: str, statut: int = 200) -> HTMLResponse:
        return HTMLResponse(
            pages.gabarit(titre, contenu, prefixe=prefixe, session=session, actif="finance"),
            status_code=statut,
            headers={"Cache-Control": "no-store"},
        )

    def message_refus(verdict: Mapping[str, Any]) -> str:
        return (
            f'<p class="message message-erreur" role="alert">Refus : <code>{e(verdict.get("code"))}</code> — '
            f"{e(verdict.get('detail'))}</p>"
        )

    # ------------------------------------------------------------------ rendu
    def champ(
        nom: str,
        libelle: str,
        valeurs: Mapping[str, Any],
        *,
        type_: str = "text",
        requis: bool = True,
        aide: str = "",
        extra: str = "",
    ) -> str:
        valeur = valeurs.get(nom, "")
        return (
            f'<label for="{e(nom)}">{e(libelle)}</label>'
            f'<input id="{e(nom)}" name="{e(nom)}" type="{type_}" value="{e(valeur)}"{" required" if requis else ""}'
            f' maxlength="300" autocomplete="off"{extra}>' + (f"<small>{e(aide)}</small>" if aide else "")
        )

    def case(nom: str, libelle: str, valeurs: Mapping[str, Any]) -> str:
        coche = " checked" if valeurs.get(nom) else ""
        return f'<label class="case"><input type="checkbox" name="{e(nom)}" value="on"{coche}> {e(libelle)}</label>'

    def choix(
        nom: str, libelle: str, options: list[tuple[str, str]], valeurs: Mapping[str, Any], *, requis: bool = True
    ) -> str:
        courant = str(valeurs.get(nom, ""))
        opts = f'<option value=""{" selected" if courant == "" else ""}>— à choisir —</option>' + "".join(
            f'<option value="{e(v)}"{" selected" if courant == v else ""}>{e(t)}</option>' for v, t in options
        )
        attribut = " required" if requis else ""
        return (
            f'<label for="{e(nom)}">{e(libelle)}</label><select id="{e(nom)}" name="{e(nom)}"{attribut}>{opts}</select>'
        )

    def formulaire_html(
        session: Session,
        employes: list[identite.Personne],
        valeurs: Mapping[str, Any],
        *,
        action: str,
        extra_hidden: str = "",
    ) -> str:
        options_employes = '<option value="">— à choisir —</option>' + "".join(
            f'<option value="{e(p.identifiant)}"'
            f"{' selected' if valeurs.get('employee_person_id') == p.identifiant else ''}>"
            f"{e(p.nom)}</option>"
            for p in employes
        )
        simulee = valeurs.get("cumuls_origine") == "SIMULE_VERSION_PRECEDENTE"
        sim_hidden = ""
        if simulee:
            sim_hidden = "".join(
                f'<input type="hidden" name="{n}" value="{e(valeurs.get(n, ""))}">'
                for n in ("sim_dossier_id", "sim_numero", "sim_hash")
            )
        parties = [
            f'<form method="post" action="{e(action)}" class="carte pile" autocomplete="off">',
            f'<input type="hidden" name="csrf" value="{e(session.csrf)}">'
            f'<input type="hidden" name="mutation_id" value="{secrets.token_hex(16)}">' + sim_hidden + extra_hidden,
            "<h2>Période et employé</h2>",
            f'<label for="employee_person_id">Salarié actif</label><select '
            f'id="employee_person_id" name="employee_person_id" required>{options_employes}</select>',
            champ("employeur_reference", "Référence de l'employeur (étiquette, sans donnée personnelle)", valeurs),
            champ("debut", "Premier jour travaillé inclus (14 jours)", valeurs, type_="date"),
            champ("fin", "Dernier jour travaillé inclus", valeurs, type_="date"),
            champ("fuseau", "Fuseau horaire IANA", valeurs, aide="Exemple : America/Montreal"),
            champ("date_paie", "Date de paie", valeurs, type_="date"),
            champ(
                "premiere_date_paie_annee",
                "Date de la première paie de 2026",
                valeurs,
                type_="date",
                aide="Sert à vérifier le numéro de période; 27 paies dans l'année = hors couverture.",
            ),
            champ(
                "periode_annuelle",
                "Numéro de période annuelle (1 à 26)",
                valeurs,
                type_="number",
                extra=' min="1" max="26"',
            ),
            champ(
                "hypothese_arrondi",
                "Hypothèse ou référence d'arrondi du brut (politique : centime, demi supérieur)",
                valeurs,
            ),
            case("fictif", "Dossier fictif (données de test)", valeurs),
            "<h2>Classification</h2>",
            choix(
                "regime_ccq",
                "Régime CCQ (jamais déduit du métier)",
                [("NON_CCQ_DECLARE", "Non CCQ — déclaré"), ("CCQ", "CCQ"), ("INCONNU", "Inconnu")],
                valeurs,
            ),
            "<h2>Attestations humaines (case décochée = non attesté)</h2>",
            *[case(f"att_{c}", libelle, valeurs) for c, libelle in _ATTESTATIONS],
            "<h2>Pièces justificatives (références; empreinte SHA-256 facultative)</h2>",
        ]
        for slot, libelle in _PIECES:
            parties.append(champ(f"piece_{slot}", libelle, valeurs, aide="Lettres, chiffres, . _ : - (128 max)"))
            parties.append(
                champ(
                    f"sha_{slot}",
                    f"SHA-256 de la pièce — {libelle} (facultatif)",
                    valeurs,
                    requis=False,
                    extra=' pattern="[0-9a-f]{64}"',
                )
            )
        parties += [
            "<h2>Crédits fédéraux (TD1) et Québec (TP-1015.3)</h2>",
            champ(
                "tc",
                "TC : total des crédits TD1 fédéral (CAD)",
                valeurs,
                extra=' inputmode="decimal" pattern="(0|[1-9][0-9]{0,8})\\.[0-9]{2}"',
            ),
            champ(
                "k1_annuel",
                "K1 annuel Québec (CAD)",
                valeurs,
                extra=' inputmode="decimal" pattern="(0|[1-9][0-9]{0,8})\\.[0-9]{2}"',
            ),
            case("fed_zero", "Déclarer nuls (0.00) F, F2, HD, F1, U1, K3, LCF, L fédéraux", valeurs),
            case("qc_zero", "Déclarer nuls (0.00) les autres montants du formulaire Québec", valeurs),
            "<details><summary>Saisir ces montants un à un (si non déclarés nuls)</summary>",
            *[champ(f"fed_{c}", f"Fédéral {c}", valeurs, requis=False) for c in _FED_NULS],
            *[champ(f"qc_{c}", f"Québec {c}", valeurs, requis=False) for c in _QC_NULS],
            *[case(f"qcm_{c}", f"Québec : {c}", valeurs) for c in _QC_MARQ],
            "</details>",
            "<h2>Cumuls avant la période</h2>",
            choix(
                "cumuls_origine",
                "Origine des cumuls",
                [
                    ("NUL_PERIODE_1", "Période 1 : tous nuls"),
                    ("DECLARE_HISTORIQUE", "Historique déclaré"),
                    ("CONFIRME_AUTORITE_HUMAINE", "Confirmé par une autorité humaine (pièce citée)"),
                    ("SIMULE_VERSION_PRECEDENTE", "Simulé depuis la version courante de la période précédente"),
                ],
                valeurs,
            ),
            "<small>Un cumul simulé ou déclaré n'est jamais une preuve de versement.</small>",
            *[champ(f"cum_{c}", f"Cumul {c}", valeurs, requis=False) for c in _CUMULS],
            champ("cum_ref_confirmation", "Référence de la pièce de confirmation (si confirmé)", valeurs, requis=False),
            "<h2>Autres retenues et coûts (vide = inconnu)</h2>",
            champ(
                "autres_retenues_montant",
                "Autres retenues de l'employé, total (CAD, 0.00 si aucune)",
                valeurs,
                requis=False,
            ),
            champ("autres_retenues_ref", "Référence de la pièce", valeurs, requis=False),
            champ(
                "autres_couts_montant",
                "Autres coûts employeur de la période (CAD, 0.00 si aucun)",
                valeurs,
                requis=False,
            ),
            champ("autres_couts_ref", "Référence de la pièce", valeurs, requis=False),
            "<h2>Paramètres employeur (vide = inconnu; aucun taux par défaut)</h2>",
            choix(
                "fss_secteur",
                "FSS : secteur de l'employeur",
                [
                    ("AUTRES", "Autres secteurs"),
                    ("PRIMAIRE_MANUFACTURIER", "Primaire ou manufacturier"),
                    ("SECTEUR_PUBLIC", "Secteur public"),
                ],
                valeurs,
                requis=False,
            ),
            champ("fss_masse", "FSS : masse salariale totale estimative (CAD)", valeurs, requis=False),
            choix(
                "fss_base",
                "FSS : base de l'estimation",
                [
                    ("ANNEE_PRECEDENTE", "Année précédente"),
                    ("CUMUL_NOUVEL_EMPLOYEUR", "Cumul de l'année (nouvel employeur)"),
                ],
                valeurs,
                requis=False,
            ),
            champ("fss_ref", "FSS : référence de la déclaration", valeurs, requis=False),
            champ(
                "cnesst_taux",
                "CNESST : taux de versement pour 100 $ (Décision de classification)",
                valeurs,
                requis=False,
            ),
            choix(
                "cnesst_base",
                "CNESST : base de l'excédent du maximum",
                [("ANNUELLE", "Annuelle"), ("HEBDOMADAIRE", "Hebdomadaire (non transcrite)")],
                valeurs,
                requis=False,
            ),
            champ("cnesst_ref", "CNESST : référence de la décision", valeurs, requis=False),
            choix(
                "normes_assujetti",
                "Normes du travail : assujetti à la cotisation",
                [("oui", "Oui"), ("non", "Non (pièce citée)")],
                valeurs,
                requis=False,
            ),
            champ("normes_ref", "Normes du travail : référence", valeurs, requis=False),
            champ("fdrcmo_masse", "FDRCMO : masse salariale de l'année (CAD)", valeurs, requis=False),
            champ("fdrcmo_ref", "FDRCMO : référence", valeurs, requis=False),
            '<button type="submit" name="action" value="apercu">Calculer '
            "l'aperçu (rien n'est conservé)</button></form>",
        ]
        return "".join(parties)

    def aplatir_entrees(valeur: Any, prefixe: str = "") -> list[tuple[str, Any]]:
        if isinstance(valeur, Mapping):
            lignes: list[tuple[str, Any]] = []
            for cle in sorted(valeur):
                lignes += aplatir_entrees(valeur[cle], f"{prefixe}.{cle}" if prefixe else str(cle))
            return lignes
        return [(prefixe, valeur)]

    def rendre_entrees(entrees: Mapping[str, Any]) -> str:
        lignes = "".join(
            f"<tr><td>{e(chemin)}</td><td>{e(valeur)}</td></tr>" for chemin, valeur in aplatir_entrees(entrees)
        )
        return (
            "<details><summary>Entrées déclarées figées dans cette version</summary>"
            "<table><thead><tr><th>Champ</th><th>Valeur déclarée</th></tr></thead>"
            f"<tbody>{lignes}</tbody></table></details>"
        )

    def rendre_version(v: Mapping[str, Any]) -> str:
        calcul, adm = v["calcul"], v["admission"]
        lignes = "".join(
            f"<tr><td>{e(p['libelle'])}</td><td>{e(p['autorite'])}</td><td>{e(p['etat'])}</td>"
            f"<td class='num'>{e(p['montant']) + ' $' if p['montant'] is not None else '—'}</td>"
            f"<td>{e('; '.join(p['manque']))}</td></tr>"
            for p in calcul["matrice"]
        )
        totaux = "".join(
            f"<tr><td>{e(t['libelle'])}</td><td>{e(t['etat'])}</td>"
            f"<td class='num'>{e(t['montant']) + ' $' if t['montant'] is not None else 'INCONNU'}</td>"
            f"<td>{e('; '.join(t['manques']))}</td></tr>"
            for t in calcul["totaux"].values()
        )
        src = v["sources"]
        heures = src["heures_m4"] or {}
        contrat = src["contrat_m5"] or {}
        brut = src["brut"] or {}
        sources_html = (
            (
                "<ul>"
                f"<li>Heures M4 : ligne {e(heures.get('ligne_id'))}, révision {e(heures.get('revision'))}, "
                f"empreinte {e(heures.get('empreinte_sources'))}, "
                f"{e(heures.get('minutes_regulieres'))} min régulières.</li>"
                f"<li>Contrat M5 : {e(contrat.get('contrat_id'))}, ligne "
                f"{e(contrat.get('ligne_id'))}, révision {e(contrat.get('revision'))}.</li>"
                f"<li>Brut régulier : {e(brut.get('brut_brouillon'))} CAD "
                f"(arrondi {e(brut.get('politique_arrondi'))}).</li></ul>"
            )
            if brut
            else "<p>Aucune source M4/M5 lue : voir le refus ci-dessus.</p>"
        )
        motifs = "".join(f"<li>{e(m)}</li>" for m in adm["motifs"])
        hors = "".join(f"<li>{e(m['detail'])}</li>" for m in calcul["motifs_hors_couverture"])
        apres = v["cumuls_apres_hypothetiques"]
        cumuls_apres = (
            "<table><tbody>"
            + "".join(f"<tr><td>{e(k)}</td><td class='num'>{e(x)} $</td></tr>" for k, x in apres.items())
            + "</tbody></table>"
            if apres
            else "<p>Non disponibles (composition incomplète).</p>"
        )
        refus = calcul.get("refus")
        return (
            '<section class="carte pile" aria-labelledby="entete-version">'
            f'<h2 id="entete-version">Calcul préparatoire — état : {e(calcul["etat"])}</h2>'
            '<p class="message message-alerte" role="note"><strong>PREPARATOIRE '
            "— NON_QUALIFIEE_POUR_PAIE.</strong> Aucun salaire versé, "
            "aucune remise, aucun document fiscal officiel, aucune "
            "écriture financière. Validation Nathan/CPA requise.</p>"
            + (message_refus(refus) if refus else "")
            + ("<h3>Hors du domaine couvert</h3><ul>" + hors + "</ul>" if hors else "")
            + f"<h3>Admission documentaire : {'satisfaite' if adm['admissible'] else 'non satisfaite'}</h3>"
            + f"<ul>{motifs}</ul>"
            + "<h3>Sources</h3>"
            + sources_html
            + rendre_entrees(v["entrees"])
            + "<h3>Postes</h3><table><thead><tr><th>Poste</th><th>Autorité</th><th>État</th>"
            + "<th>Montant</th><th>Manque</th></tr></thead>"
            f"<tbody>{lignes}</tbody></table>"
            "<h3>Totaux (affichés seulement si tous leurs postes sont "
            "couverts)</h3><table><thead><tr><th>Total</th><th>État</th>"
            f"<th>Montant</th><th>Manques</th></tr></thead><tbody>{totaux}</tbody></table>"
            f"<h3>Cumuls après la période — hypothétiques, jamais un versement</h3>{cumuls_apres}"
            "<p>Les cumuls simulés ne deviennent jamais un salaire payé ni une preuve de versement.</p></section>"
        )

    def employes_actifs(cnx: Connection) -> list[identite.Personne]:
        return [p for p in identite.lister(cnx) if p.actif and "employee" in p.roles]

    def liste_employes(session: Session) -> list[identite.Personne]:
        with cnx_factory() as cnx:
            proprietaire(cnx, session)
            return employes_actifs(cnx)

    # ------------------------------------------------------------------ pages
    @router.get("/finance/paie/dossiers", response_class=HTMLResponse)
    def liste(request: Request) -> HTMLResponse:
        session = session_page(request, administrateur=False)
        if request.query_params:
            raise HTTPException(400, "aucun paramètre accepté")
        resultat, verdict = appeler(
            session, "m5_lire_dossier_paie", {"dossier_id": None, "numero": None, "comparer_a": None}
        )
        if verdict is not None:
            return reponse_html(
                session, "Dossiers de paie préparatoires", message_refus(verdict), verdict_http(verdict)
            )
        lignes = "".join(
            f'<tr><td><a href="{e(base)}/{e(d["dossier_id"])}">{e(d["date_paie"])}</a>'
            f"</td><td>{e(d['employee_person_id'])}</td>"
            f"<td>{e(d['periode_annuelle'])}</td><td>{e(d['etat'])}</td><td>{e(d['etat_calcul'])}</td>"
            f"<td>v{e(d['numero_courant'])}</td><td "
            f'class="num">{e(d["net_preparatoire"]) + " $" if d["net_preparatoire"] else "INCONNU"}</td></tr>'
            for d in resultat["dossiers"]
        )
        contenu = (
            "<p>Dossiers de paie préparatoires : aucun salaire n'est versé et aucun document officiel n'est émis.</p>"
            f'<p><a class="bouton" href="{e(base)}/nouveau">Préparer un nouveau dossier</a> '
            f'<a href="{e(prefixe)}/finance/paie">Brut régulier</a></p>'
            "<table><thead><tr><th>Date de paie</th><th>Salarié</th>"
            "<th>Période</th><th>État</th><th>Calcul</th><th>Version</th>"
            f"<th>Net préparatoire</th></tr></thead><tbody>{lignes}</tbody></table>"
        )
        return reponse_html(session, "Dossiers de paie préparatoires", contenu)

    @router.get("/finance/paie/dossiers/nouveau", response_class=HTMLResponse)
    def nouveau(request: Request) -> HTMLResponse:
        session = session_page(request, administrateur=False)
        parametres = dict(request.query_params)
        if set(parametres) - {"depuis", "numero", "mode"}:
            raise HTTPException(400, "paramètre inattendu")
        valeurs: dict[str, Any] = {"fuseau": "America/Montreal", "employeur_reference": ""}
        extra = ""
        titre = "Nouveau dossier de paie préparatoire"
        if "depuis" in parametres:
            mode = parametres.get("mode")
            if (
                mode not in {"correction", "suivante"}
                or set(parametres["depuis"]) - _ID32
                or len(parametres["depuis"]) != 32
            ):
                raise HTTPException(400, "paramètres invalides")
            numero = parametres.get("numero")
            if numero is not None and (not numero.isdecimal() or len(numero) > 4):
                raise HTTPException(400, "numéro invalide")
            resultat, verdict = appeler(
                session,
                "m5_lire_dossier_paie",
                {"dossier_id": parametres["depuis"], "numero": int(numero) if numero else None, "comparer_a": None},
            )
            if verdict is not None:
                return reponse_html(session, titre, message_refus(verdict), verdict_http(verdict))
            version = resultat["version"]
            valeurs = valeurs_depuis_entrees(version["identite"]["employee_person_id"], version["entrees"])
            if mode == "suivante":
                valeurs = _prochaine_periode(valeurs)
                valeurs.update(
                    cumuls_origine="SIMULE_VERSION_PRECEDENTE",
                    sim_dossier_id=version["dossier_id"],
                    sim_numero=version["numero"],
                    sim_hash=version["hash_version"],
                )
                titre = "Période suivante (cumuls simulés)"
            else:
                titre = "Correction : nouvelle version"
                extra = (
                    f'<input type="hidden" name="version_attendue" '
                    f'value="{e(resultat["dossier"]["versions"][-1]["numero"])}">'
                    '<input type="hidden" name="type_version" value="CORRECTION">'
                )
        contenu = (
            "<p>Chaque champ est une déclaration humaine : rien n'est présumé, rien n'est conservé avant l'aperçu.</p>"
            + formulaire_html(session, liste_employes(session), valeurs, action=f"{base}/apercu", extra_hidden=extra)
        )
        return reponse_html(session, titre, contenu)

    @router.post("/finance/paie/dossiers/apercu", response_class=HTMLResponse)
    async def apercu_formulaire(request: Request) -> Response:
        session = session_page(request, administrateur=False)
        with cnx_factory() as cnx:
            proprietaire(cnx, session)
        data = await _formulaire_large(request)
        if not securite.csrf_valide(data.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        if data.get("action") != "apercu":
            raise HTTPException(400, "action invalide")
        employe, entrees = entrees_depuis_formulaire(data)
        resultat, verdict = appeler(
            session, "m5_apercu_dossier_paie", {"employee_person_id": employe, "entrees": entrees}
        )
        if verdict is not None:
            contenu = message_refus(verdict) + formulaire_html(
                session, liste_employes(session), _valeurs_de_refus(entrees, employe, data), action=f"{base}/apercu"
            )
            return reponse_html(session, "Aperçu refusé", contenu, verdict_http(verdict))
        attendue_texte = data.get("version_attendue") or "0"
        if not attendue_texte.isdecimal() or len(attendue_texte) > 4:
            raise HTTPException(400, "version attendue invalide")
        version_attendue = int(attendue_texte)
        type_version = data.get("type_version") or "CREATION"
        conserver = ""
        if resultat["conservable"]:
            conserver = (
                f'<form method="post" action="{e(base)}/conserver" class="carte pile">'
                f'<input type="hidden" name="csrf" value="{e(session.csrf)}">'
                f'<input type="hidden" name="mutation_id" value="{secrets.token_hex(16)}">'
                f'<input type="hidden" name="employee_person_id" value="{e(employe)}">'
                f'<input type="hidden" name="empreinte_apercu" value="{e(resultat["empreinte_apercu"])}">'
                f'<input type="hidden" name="version_attendue" value="{version_attendue}">'
                f'<input type="hidden" name="type_version" value="{e(type_version)}">'
                f'<input type="hidden" name="entrees_json" '
                f'value="{e(json.dumps(entrees, ensure_ascii=False, separators=(",", ":")))}">'
                '<label for="motif">Motif de la version (facultatif)</label>'
                '<input id="motif" name="motif" maxlength="1000" autocomplete="off">'
                "<p>Conserver fige les entrées, les références de sources et ce calcul, chiffrés, sans rien verser.</p>"
                '<button type="submit">Conserver cette version</button></form>'
            )
        else:
            conserver = (
                '<p class="message message-alerte">Aucune version conservable tant que la source M4/M5 '
                "ou la période est refusée.</p>"
            )
        retenus = (
            f'<input type="hidden" name="version_attendue" value="{version_attendue}">'
            f'<input type="hidden" name="type_version" value="{e(type_version)}">'
        )
        modifier = formulaire_html(
            session,
            liste_employes(session),
            valeurs_depuis_entrees(employe, resultat["version"]["entrees"]),
            action=f"{base}/apercu",
            extra_hidden=retenus,
        )
        contenu = (
            rendre_version(resultat["version"])
            + conserver
            + f"<details><summary>Modifier les déclarations</summary>{modifier}</details>"
        )
        return reponse_html(session, "Aperçu du dossier de paie", contenu)

    @router.post("/finance/paie/dossiers/conserver", response_class=HTMLResponse)
    async def conserver_formulaire(request: Request) -> Response:
        session = session_page(request, administrateur=False)
        with cnx_factory() as cnx:
            proprietaire(cnx, session)
        data = await _formulaire_large(request)
        if not securite.csrf_valide(data.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        try:
            entrees = json.loads(data.get("entrees_json", ""))
            version_attendue = int(data["version_attendue"])
        except (ValueError, KeyError, RecursionError) as exc:
            raise HTTPException(400, "formulaire de conservation invalide") from exc
        arguments = {
            "employee_person_id": data.get("employee_person_id", ""),
            "entrees": entrees,
            "empreinte_apercu": data.get("empreinte_apercu", ""),
            "version_attendue": version_attendue,
            "type_version": data.get("type_version", ""),
            "motif": data.get("motif", ""),
            "mutation_id": data.get("mutation_id", ""),
        }
        recu, verdict = appeler(
            session, "m5_conserver_version_dossier_paie", arguments, mutation_id=arguments["mutation_id"]
        )
        if verdict is not None:
            return reponse_html(session, "Version non conservée", message_refus(verdict), verdict_http(verdict))
        return Response(
            status_code=303, headers={"Location": f"{base}/{recu['dossier_id']}", "Cache-Control": "no-store"}
        )

    def numero_requete(request: Request, nom: str) -> int | None:
        brut = request.query_params.get(nom)
        if brut is None:
            return None
        if not brut.isdecimal() or len(brut) > 4 or int(brut) < 1:
            raise HTTPException(400, f"{nom} invalide")
        return int(brut)

    def id_dossier(valeur: str) -> str:
        if len(valeur) != 32 or set(valeur) - _ID32:
            raise HTTPException(404, "dossier introuvable")
        return valeur

    @router.get("/finance/paie/dossiers/{dossier_id}", response_class=HTMLResponse)
    def dossier_page(dossier_id: str, request: Request) -> HTMLResponse:
        session = session_page(request, administrateur=False)
        if set(request.query_params) - {"v", "comparer"}:
            raise HTTPException(400, "paramètre inattendu")
        dossier_id = id_dossier(dossier_id)
        resultat, verdict = appeler(
            session,
            "m5_lire_dossier_paie",
            {
                "dossier_id": dossier_id,
                "numero": numero_requete(request, "v"),
                "comparer_a": numero_requete(request, "comparer"),
            },
        )
        if verdict is not None:
            return reponse_html(session, "Dossier de paie", message_refus(verdict), verdict_http(verdict))
        d, version = resultat["dossier"], resultat["version"]
        courant = d["versions"][-1]

        def ligne_historique(v: Mapping[str, Any]) -> str:
            numero = v["numero"]
            comparer = (
                ""
                if numero == 1
                else f'<a href="{e(base)}/{e(dossier_id)}?v={numero}&amp;comparer={numero - 1}">'
                f"comparer à v{numero - 1}</a>"
            )
            return (
                f'<tr><td><a href="{e(base)}/{e(dossier_id)}?v={numero}">v{numero}</a>'
                f"</td><td>{e(v['type_version'])}</td>"
                f"<td>{e(v['horodatage'])}</td><td>{e(v['etat_calcul'])}</td><td>{e(v['motif'])}</td>"
                f"<td><code>{e(v['hash_version'])[:16]}…</code></td><td>{comparer}</td></tr>"
            )

        historique = "".join(ligne_historique(v) for v in d["versions"])
        revues = (
            "".join(
                f"<li>v{e(r['numero'])} — {e(r['decision'])} — {e(r['note'])} ({e(r['horodatage'])})</li>"
                for r in d["revues"]
            )
            or "<li>Aucune revue.</li>"
        )
        exports = (
            "".join(
                f"<li>v{e(x['numero'])} {e(x['format'])} {e(x['horodatage'])} "
                f"<code>{e(x['empreinte_export'])[:16]}…</code></li>"
                for x in d["exports"]
            )
            or "<li>Aucun export.</li>"
        )
        comparaison = ""
        if resultat["comparaison"]:
            comp = resultat["comparaison"]
            diffs = (
                "".join(
                    f"<tr><td>{e(sect)}</td><td>{e(c['champ'])}</td>"
                    f"<td>{e(c['avant'])}</td><td>{e(c['apres'])}</td></tr>"
                    for sect in ("entrees", "sources", "admission", "postes", "totaux")
                    for c in comp[sect]
                )
                or "<tr><td colspan='4'>Aucune différence.</td></tr>"
            )
            comparaison = (
                f'<section class="carte pile"><h2>Comparaison v{e(comp["de"])} → v{e(comp["vers"])}</h2>'
                f"<table><thead><tr><th>Section</th><th>Champ</th><th>Avant</th>"
                f"<th>Après</th></tr></thead><tbody>{diffs}</tbody></table></section>"
            )
        actions = ""
        csrf = f'<input type="hidden" name="csrf" value="{e(session.csrf)}">'
        hidden_version = (
            f'<input type="hidden" name="numero" value="{courant["numero"]}">'
            f'<input type="hidden" name="hash_version" value="{e(courant["hash_version"])}">'
        )
        if d["etat"] in {"EN_PREPARATION", "A_CORRIGER"}:
            actions += (
                f'<form method="post" action="{e(base)}/{e(dossier_id)}/revue" class="carte '
                f'pile"><h3>Revue interne de la version courante</h3>{csrf}{hidden_version}'
                f'<input type="hidden" name="mutation_id" value="{secrets.token_hex(16)}">'
                '<label for="decision">Décision</label><select id="decision" name="decision" required>'
                '<option value="REVUE_COMPLETEE">Revue complétée</option>'
                '<option value="A_CORRIGER">À corriger</option></select>'
                '<label for="note">Note (revue interne, non fiscale)</label>'
                '<textarea id="note" name="note" maxlength="1000"></textarea>'
                '<button type="submit">Enregistrer la revue</button></form>'
            )
        if d["etat"] in {"REVUE_COMPLETEE", "A_CORRIGER"}:
            actions += (
                f'<form method="post" action="{e(base)}/{e(dossier_id)}/rouvrir" '
                f'class="carte pile"><h3>Rouvrir le dossier</h3>{csrf}{hidden_version}'
                f'<input type="hidden" name="mutation_id" value="{secrets.token_hex(16)}">'
                '<label for="motif_r">Motif</label><input id="motif_r" name="motif" required maxlength="1000">'
                '<button type="submit">Rouvrir</button></form>'
            )
        if d["etat"] == "REVUE_COMPLETEE":
            for fmt, libelle in (("json", "JSON structuré"), ("html", "Page lisible")):
                actions += (
                    f'<form method="post" action="{e(base)}/{e(dossier_id)}/export" '
                    f'class="carte pile">{csrf}{hidden_version}'
                    f'<input type="hidden" name="mutation_id" value="{secrets.token_hex(16)}">'
                    f'<input type="hidden" name="format_export" value="{fmt}">'
                    f'<button type="submit">Exporter pour le professionnel — {libelle}</button></form>'
                )
        liens = (
            f'<a href="{e(base)}/nouveau?depuis={e(dossier_id)}&amp;mode=correction">Corriger (nouvelle version)</a> · '
            f'<a href="{e(base)}/nouveau?depuis={e(dossier_id)}&amp;mode=suivante">Période '
            f"suivante (cumuls simulés)</a> · "
            f'<a href="{e(base)}/{e(dossier_id)}/verifier">Vérifier les sources et la reproductibilité</a> · '
            f'<a href="{e(base)}">Tous les dossiers</a>'
        )
        contenu = (
            f"<p>Dossier <code>{e(dossier_id)}</code> — état : "
            f"<strong>{e(d['etat'])}</strong>. Version affichée : v{e(version['numero'])} "
            f"(<code>{e(version['hash_version'])}</code>). Employé "
            f": {e(version['identite']['employee_person_id'])}.</p>"
            f"<p>{liens}</p>"
            + rendre_version(version)
            + comparaison
            + "<section class='carte pile'><h2>Historique des versions</h2><table><thead><tr><th>Version</th>"
            + "<th>Type</th><th>Date</th><th>Calcul</th>"
            f"<th>Motif</th><th>Empreinte</th><th></th></tr></thead><tbody>{historique}</tbody></table>"
            f"<h3>Revues internes</h3><ul>{revues}</ul><h3>Exports audités</h3><ul>{exports}</ul></section>" + actions
        )
        return reponse_html(session, "Dossier de paie préparatoire", contenu)

    @router.get("/finance/paie/dossiers/{dossier_id}/verifier", response_class=HTMLResponse)
    def verifier_page(dossier_id: str, request: Request) -> HTMLResponse:
        session = session_page(request, administrateur=False)
        if set(request.query_params) - {"v"}:
            raise HTTPException(400, "paramètre inattendu")
        resultat, verdict = appeler(
            session,
            "m5_verifier_dossier_paie",
            {"dossier_id": id_dossier(dossier_id), "numero": numero_requete(request, "v")},
        )
        if verdict is not None:
            return reponse_html(session, "Vérification", message_refus(verdict), verdict_http(verdict))
        diffs = (
            "".join(f"<li><code>{e(x['code'])}</code> — {e(x['detail'])}</li>" for x in resultat["differences"])
            or "<li>Aucune différence.</li>"
        )
        contenu = (
            f"<p>Version v{e(resultat['numero'])} — calcul reproductible : "
            f"<strong>{'oui' if resultat['reproductible'] else 'non'}</strong>; "
            f"sources inchangées : <strong>{'oui' if resultat['sources_inchangees'] else 'non'}</strong>.</p>"
            f"<ul>{diffs}</ul>"
            "<p>L'ancienne version n'est jamais modifiée : une différence "
            "mène à une nouvelle version explicite (rebase).</p>"
            f'<p><a href="{e(base)}/{e(dossier_id)}">Retour au dossier</a></p>'
        )
        return reponse_html(session, "Vérification du dossier", contenu)

    async def action_dossier(request: Request, dossier_id: str, outil: str, champs: tuple[str, ...]) -> Response:
        session = session_page(request, administrateur=False)
        with cnx_factory() as cnx:
            proprietaire(cnx, session)
        data = await _formulaire_large(request)
        if not securite.csrf_valide(data.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        if set(data) != {"csrf", *champs}:
            raise HTTPException(400, "champs du formulaire invalides")
        try:
            numero = int(data["numero"])
        except ValueError as exc:
            raise HTTPException(400, "numéro invalide") from exc
        arguments: dict[str, Any] = {"dossier_id": id_dossier(dossier_id), "numero": numero}
        arguments.update({c: data[c] for c in champs if c != "numero"})
        recu, verdict = appeler(session, outil, arguments, mutation_id=data["mutation_id"])
        if verdict is not None:
            return reponse_html(session, "Action refusée", message_refus(verdict), verdict_http(verdict))
        del recu
        return Response(status_code=303, headers={"Location": f"{base}/{dossier_id}", "Cache-Control": "no-store"})

    @router.post("/finance/paie/dossiers/{dossier_id}/revue", response_class=HTMLResponse)
    async def revue_formulaire(dossier_id: str, request: Request) -> Response:
        return await action_dossier(
            request, dossier_id, "m5_revue_dossier_paie", ("numero", "hash_version", "decision", "note", "mutation_id")
        )

    @router.post("/finance/paie/dossiers/{dossier_id}/rouvrir", response_class=HTMLResponse)
    async def rouvrir_formulaire(dossier_id: str, request: Request) -> Response:
        return await action_dossier(
            request, dossier_id, "m5_rouvrir_dossier_paie", ("numero", "hash_version", "motif", "mutation_id")
        )

    def telecharger(
        session: Session, dossier_id: str, numero: int, hash_version: str, fmt: str, mutation_id: str
    ) -> tuple[Response | None, dict[str, Any] | None]:
        """Audite l'export puis le rend : (réponse, None) ou (None, verdict). Rien n'est rendu sans export audité."""
        recu, verdict = appeler(
            session,
            "m5_exporter_dossier_paie",
            {
                "dossier_id": dossier_id,
                "numero": numero,
                "hash_version": hash_version,
                "format_export": fmt,
                "mutation_id": mutation_id,
            },
            mutation_id=mutation_id,
        )
        if verdict is not None:
            return None, verdict
        contenu, verdict = appeler(
            session,
            "m5_lire_export_dossier_paie",
            {"dossier_id": dossier_id, "numero": numero, "hash_version": hash_version, "format_export": fmt},
        )
        if verdict is not None:
            return None, verdict
        if contenu["empreinte_sha256"] != recu["empreinte_export"]:
            return None, {"code": "REJ-DOSSIER-PAIE-EXPORT-REFUSE", "detail": "empreinte de l'export différente"}
        extension = "json" if fmt == "json" else "html"
        return Response(
            content=contenu["contenu"].encode("utf-8"),
            media_type=contenu["type_mime"],
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Export-Sha256": contenu["empreinte_sha256"],
                "Content-Disposition": f'attachment; filename="dossier-paie-preparatoire-v{numero}.{extension}"',
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            },
        ), None

    @router.post("/finance/paie/dossiers/{dossier_id}/export")
    async def export_formulaire(dossier_id: str, request: Request) -> Response:
        session = session_page(request, administrateur=False)
        with cnx_factory() as cnx:
            proprietaire(cnx, session)
        data = await _formulaire_large(request)
        if not securite.csrf_valide(data.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        if set(data) != {"csrf", "numero", "hash_version", "format_export", "mutation_id"}:
            raise HTTPException(400, "champs du formulaire invalides")
        try:
            numero = int(data["numero"])
        except ValueError as exc:
            raise HTTPException(400, "numéro invalide") from exc
        reponse, verdict = telecharger(
            session, id_dossier(dossier_id), numero, data["hash_version"], data["format_export"], data["mutation_id"]
        )
        if verdict is not None or reponse is None:
            verdict = verdict or {"code": "REJ-DOSSIER-PAIE-EXPORT-REFUSE", "detail": "export indisponible"}
            return reponse_html(session, "Export refusé", message_refus(verdict), verdict_http(verdict))
        return reponse

    # ------------------------------------------------------------------ API JSON
    def exiger_csrf(request: Request, session: Session) -> None:
        if not securite.csrf_valide(request.headers.get("x-csrf-token"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")

    def json_ou_erreur(resultat: Any, verdict: dict[str, Any] | None) -> JSONResponse:
        if verdict is not None:
            return JSONResponse(
                {"accepte": False, "verdict": verdict},
                status_code=verdict_http(verdict),
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse({"accepte": True, "resultat": resultat}, headers={"Cache-Control": "no-store"})

    @router.post("/api/finance/paie/dossiers/apercu")
    async def api_apercu(request: Request) -> JSONResponse:
        session = session_api(request, administrateur=False)
        with cnx_factory() as cnx:
            proprietaire(cnx, session)
        exiger_csrf(request, session)
        corps = await _json_borne(request)
        if set(corps) != {"employee_person_id", "entrees"}:
            raise HTTPException(400, "champs invalides")
        return json_ou_erreur(*appeler(session, "m5_apercu_dossier_paie", corps))

    @router.post("/api/finance/paie/dossiers/conserver")
    async def api_conserver(request: Request) -> JSONResponse:
        session = session_api(request, administrateur=False)
        with cnx_factory() as cnx:
            proprietaire(cnx, session)
        exiger_csrf(request, session)
        corps = await _json_borne(request)
        if set(corps) != {
            "employee_person_id",
            "entrees",
            "empreinte_apercu",
            "version_attendue",
            "type_version",
            "motif",
            "mutation_id",
        }:
            raise HTTPException(400, "champs invalides")
        return json_ou_erreur(
            *appeler(session, "m5_conserver_version_dossier_paie", corps, mutation_id=corps["mutation_id"])
        )

    @router.get("/api/finance/paie/dossiers")
    def api_liste(request: Request) -> JSONResponse:
        session = session_api(request, administrateur=False)
        if request.query_params:
            raise HTTPException(400, "aucun paramètre accepté")
        return json_ou_erreur(
            *appeler(session, "m5_lire_dossier_paie", {"dossier_id": None, "numero": None, "comparer_a": None})
        )

    @router.get("/api/finance/paie/dossiers/{dossier_id}")
    def api_dossier(dossier_id: str, request: Request) -> JSONResponse:
        session = session_api(request, administrateur=False)
        if set(request.query_params) - {"numero", "comparer_a"}:
            raise HTTPException(400, "paramètre inattendu")
        return json_ou_erreur(
            *appeler(
                session,
                "m5_lire_dossier_paie",
                {
                    "dossier_id": id_dossier(dossier_id),
                    "numero": numero_requete(request, "numero"),
                    "comparer_a": numero_requete(request, "comparer_a"),
                },
            )
        )

    @router.get("/api/finance/paie/dossiers/{dossier_id}/verifier")
    def api_verifier(dossier_id: str, request: Request) -> JSONResponse:
        session = session_api(request, administrateur=False)
        if set(request.query_params) - {"numero"}:
            raise HTTPException(400, "paramètre inattendu")
        return json_ou_erreur(
            *appeler(
                session,
                "m5_verifier_dossier_paie",
                {"dossier_id": id_dossier(dossier_id), "numero": numero_requete(request, "numero")},
            )
        )

    async def api_action(request: Request, dossier_id: str, outil: str, champs: set[str]) -> JSONResponse:
        session = session_api(request, administrateur=False)
        with cnx_factory() as cnx:
            proprietaire(cnx, session)
        exiger_csrf(request, session)
        corps = await _json_borne(request)
        if set(corps) != champs:
            raise HTTPException(400, "champs invalides")
        return json_ou_erreur(
            *appeler(session, outil, {"dossier_id": id_dossier(dossier_id), **corps}, mutation_id=corps["mutation_id"])
        )

    @router.post("/api/finance/paie/dossiers/{dossier_id}/revue")
    async def api_revue(dossier_id: str, request: Request) -> JSONResponse:
        return await api_action(
            request, dossier_id, "m5_revue_dossier_paie", {"numero", "hash_version", "decision", "note", "mutation_id"}
        )

    @router.post("/api/finance/paie/dossiers/{dossier_id}/rouvrir")
    async def api_rouvrir(dossier_id: str, request: Request) -> JSONResponse:
        return await api_action(
            request, dossier_id, "m5_rouvrir_dossier_paie", {"numero", "hash_version", "motif", "mutation_id"}
        )

    @router.post("/api/finance/paie/dossiers/{dossier_id}/export")
    async def api_export(dossier_id: str, request: Request) -> Response:
        session = session_api(request, administrateur=False)
        with cnx_factory() as cnx:
            proprietaire(cnx, session)
        exiger_csrf(request, session)
        corps = await _json_borne(request)
        if set(corps) != {"numero", "hash_version", "format_export", "mutation_id"} or type(corps["numero"]) is not int:
            raise HTTPException(400, "champs invalides")
        reponse, verdict = telecharger(
            session,
            id_dossier(dossier_id),
            corps["numero"],
            corps["hash_version"],
            corps["format_export"],
            corps["mutation_id"],
        )
        if verdict is not None or reponse is None:
            return json_ou_erreur(None, verdict or {"code": "REJ-DOSSIER-PAIE-EXPORT-REFUSE", "detail": "indisponible"})
        return reponse

    return router
