"""Dossier de décision financière dérivé de M5, sans calcul ni écriture dans la console."""

import re
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import identite
from . import frontoffice_marketing, metier, obligations_privees, pages, paie_das_privees_cfo, securite
from .securite import Session

_STATUTS = {"CONNU": "Documenté", "PARTIEL": "Partiel", "INCONNU": "Données manquantes"}
_LIBELLES = {
    "cash_libre_cad": "Cash libre (CAD)", "cash_libre_calculable": "Cash libre calculable",
    "total_a_recevoir_cad": "À recevoir (CAD)", "comptes_a_payer_cad": "À payer (CAD)",
    "factures_envoyees_a_recevoir": "Factures envoyées à recevoir", "source_refs": "Sources",
    "hypotheses": "Hypothèses", "manque": "Données manquantes", "limites": "Limites",
    "semaine": "Semaine", "debut": "Début", "statut": "État", "entrees_cad": "Entrées (CAD)",
    "sorties_cad": "Sorties (CAD)", "solde_fin_cad": "Solde en fin de semaine (CAD)",
    "AR": "À recevoir : nombre de factures, total (CAD)", "AP_cad": "À payer après taxes (CAD)",
    "horizon_semaines": "Horizon (semaines)", "semaines_couvertes": "Semaines disponibles",
    "departement": "Département", "registre": "Registre", "taille": "Nombre d'écritures",
    "tete": "Référence de la dernière écriture",
}

_OBLIGATIONS_CLES = {"p": "Paies", "d": "Déductions à la source (DAS)"}
_OBLIGATIONS_CHAMPS = {
    "s": "statut", "d": "montant déclaré", "u": "montant utilisable",
    "e": "échéance", "t": "état de l’échéance", "p": "période", "a": "autorité",
    "q": "source du montant", "j": "date de la source du montant", "x": "source de l’échéance",
    "y": "année de référence", "v": "version de la source",
}
_OBLIGATIONS_STATUTS = {
    "i": "Déclaration incomplète", "INCOMPLETE": "Déclaration incomplète",
    "d": "Documentée, à valider", "DOCUMENTEE_A_VALIDER": "Documentée, à valider",
    "p": "Échéance passée, à vérifier", "ECHEANCE_PASSEE_A_VERIFIER": "Échéance passée, à vérifier",
    "x": "Source périmée", "SOURCE_PERIMEE": "Source périmée",
}
_OBLIGATIONS_ECHEANCES = {
    "a": "À venir", "A_VENIR": "À venir",
    "p": "Passée, à vérifier", "PASSEE_A_VERIFIER": "Passée, à vérifier",
    "n": "Non déclarée", "NON_DECLAREE": "Non déclarée",
}
_OBLIGATIONS_MANQUES = {
    1: "Montant déclaré manquant", 2: "Source du montant manquante",
    4: "Échéance manquante", 8: "Période ou source de la période manquante",
    16: "Source à vérifier", 32: "Période à vérifier", 64: "Date de la source à vérifier",
    128: "Année ou version à vérifier", 256: "Source périmée",
}


def _date_iso(valeur: Any) -> bool:
    if not isinstance(valeur, str):
        return False
    try:
        return date.fromisoformat(valeur).isoformat() == valeur
    except ValueError:
        return False


def _json_valide(valeur: Any, profondeur: int = 0) -> bool:
    """Évite qu'une réponse métier mal formée casse le rendu ou l'encodage JSON."""
    if profondeur > 32:
        return False
    if valeur is None or isinstance(valeur, (str, bool, int)):
        return True
    if isinstance(valeur, float):
        return valeur == valeur and valeur not in (float("inf"), float("-inf"))
    if isinstance(valeur, list):
        return all(_json_valide(element, profondeur + 1) for element in valeur)
    if isinstance(valeur, dict):
        return all(
            isinstance(cle, str) and _json_valide(element, profondeur + 1)
            for cle, element in valeur.items()
        )
    return False


def _masques_manquants(valeur: Any, nombre: int) -> list[tuple[int, bool]] | None:
    codes_par_ligne = [False] * nombre
    masques: Any = valeur
    if isinstance(valeur, Mapping):
        if set(valeur) != {"masques", "codes_complets_par_ligne"}:
            return None
        masques = valeur["masques"]
        codes = valeur["codes_complets_par_ligne"]
        if not isinstance(codes, list) or len(codes) != nombre or any(
            not isinstance(ligne, list) or any(not isinstance(code, str) for code in ligne) for ligne in codes
        ):
            return None
        codes_par_ligne = [bool(ligne) for ligne in codes]
    if isinstance(masques, bool):
        return None
    if isinstance(masques, int):
        valeurs = [masques] * nombre
    elif isinstance(masques, list) and len(masques) == nombre:
        valeurs = masques
    else:
        return None
    if any(isinstance(masque, bool) or not isinstance(masque, int) or masque < 0 for masque in valeurs):
        return None
    return list(zip(valeurs, codes_par_ligne, strict=True))


def _obligations_compactes(valeur: Any) -> str:
    indisponible = (
        '<p class="note">Les données déclarées de paie ou de DAS ne peuvent pas être affichées; '
        'une vérification est requise.</p>'
    )
    if not isinstance(valeur, list) or len(valeur) != 4:
        return indisponible
    cles, champs, lignes, manques = valeur
    if (
        not isinstance(cles, str) or not cles or len(cles) > 2
        or any(cle not in _OBLIGATIONS_CLES for cle in cles)
        or len(set(cles)) != len(cles) or cles != "".join(cle for cle in "pd" if cle in cles)
        or not isinstance(champs, str) or len(set(champs)) != len(champs)
        or any(champ not in _OBLIGATIONS_CHAMPS for champ in champs)
        or not {"s", "d", "u", "e", "t"}.issubset(champs)
        or not isinstance(lignes, list) or len(lignes) != len(cles)
    ):
        return indisponible
    masques_lignes = _masques_manquants(manques, len(cles))
    if masques_lignes is None:
        return indisponible
    rendus = []
    for rang, (cle, ligne) in enumerate(zip(cles, lignes, strict=True)):
        if not isinstance(ligne, list) or len(ligne) != len(champs):
            return indisponible
        donnees = dict(zip(champs, ligne, strict=True))
        if not isinstance(donnees["s"], str) or donnees["s"] not in _OBLIGATIONS_STATUTS:
            return indisponible
        statut = _OBLIGATIONS_STATUTS.get(donnees["s"], "État non reconnu")
        echeance_statut = donnees["t"]
        if echeance_statut is not None and not isinstance(echeance_statut, str):
            return indisponible
        echeance = (
            _OBLIGATIONS_ECHEANCES.get(echeance_statut, "État non reconnu")
            if echeance_statut else "Non disponible"
        )
        for champ in ("d", "u"):
            montant = donnees[champ]
            if montant is not None and (
                not isinstance(montant, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)\.[0-9]{2}", montant) is None
            ):
                return indisponible
        if donnees["u"] is not None and donnees["s"] not in {
            "d", "DOCUMENTEE_A_VALIDER", "p", "ECHEANCE_PASSEE_A_VERIFIER",
        }:
            return indisponible
        for champ in ("e", "j"):
            if champ in donnees and donnees[champ] is not None and not _date_iso(donnees[champ]):
                return indisponible
        if "p" in donnees and donnees["p"] is not None and (
            not isinstance(donnees["p"], list) or len(donnees["p"]) != 2
            or any(not _date_iso(item) for item in donnees["p"])
        ):
            return indisponible
        if "x" in donnees and donnees["x"] is not None and (
            not isinstance(donnees["x"], list) or len(donnees["x"]) != 4
            or not isinstance(donnees["x"][0], str)
            or any(item is not None and not _date_iso(item) for item in donnees["x"][1:])
        ):
            return indisponible
        for champ in ("a", "q", "v"):
            if champ in donnees and donnees[champ] is not None and not isinstance(donnees[champ], str):
                return indisponible
        if "y" in donnees and donnees["y"] is not None and (
            isinstance(donnees["y"], bool) or not isinstance(donnees["y"], int)
        ):
            return indisponible
        masque, codes = masques_lignes[rang]
        manques_lisibles = [libelle for bit, libelle in _OBLIGATIONS_MANQUES.items() if masque & bit]
        if masque & ~sum(_OBLIGATIONS_MANQUES):
            manques_lisibles.append("Autres éléments à vérifier")
        if codes:
            manques_lisibles.append("Autres éléments à vérifier")
        if not manques_lisibles:
            manques_lisibles.append("Aucun manque déclaré")
        elements = [
            ("Statut", statut),
            ("Montant déclaré (CAD)", donnees["d"]),
            ("Montant utilisable (CAD)", donnees["u"]),
            ("Échéance", donnees["e"]),
            ("État de l’échéance", echeance),
        ]
        libelles_optionnels = {"p": "Période", "a": "Autorité", "q": "Source du montant",
                              "j": "Date de la source du montant", "x": "Source de l’échéance",
                              "y": "Année de référence", "v": "Version de la source"}
        for champ, libelle in libelles_optionnels.items():
            if champ not in donnees:
                continue
            contenu = donnees[champ]
            if champ == "p" and contenu is not None:
                contenu = f"{contenu[0]} au {contenu[1]}"
            elif champ == "x" and contenu is not None:
                description, consultee, applicable_du, applicable_jusqu_au = contenu
                contenu = (
                    f"{description}; consultée le {consultee or 'Non disponible'}; "
                    f"applicable du {applicable_du or 'Non disponible'} "
                    f"au {applicable_jusqu_au or 'Non disponible'}"
                )
            elements.append((libelle, contenu))
        liste = "<ul>" + "".join(f"<li>{pages.e(code)}</li>" for code in manques_lisibles) + "</ul>"
        details = "<dl>" + "".join(
            f"<dt>{pages.e(libelle)}</dt><dd>{_donnee(contenu)}</dd>" for libelle, contenu in elements
        ) + f"<dt>Données à vérifier</dt><dd>{liste}</dd></dl>"
        rendus.append(f'<section class="carte"><h3>{pages.e(_OBLIGATIONS_CLES[cle])}</h3>{details}</section>')
    return '<div class="pile">' + "".join(rendus) + "</div>"


def _charge(corps: Mapping[str, Any]) -> dict[str, str]:
    if set(corps) != {"question_posee"}:
        raise HTTPException(400, "seule la question est acceptée; date et droits viennent du serveur")
    question = corps["question_posee"]
    if not isinstance(question, str) or not question.strip() or len(question) > 1000:
        raise HTTPException(400, "la question doit contenir de 1 à 1000 caractères")
    return {"question_posee": question}


def _sans_query(request: Request) -> None:
    if request.query_params:
        raise HTTPException(400, "aucun paramètre d'URL n'est accepté")


def creer_router(
    *, session_page: Callable[..., Session], session_api: Callable[..., Session],
    ecriture_api: Callable[[Request], Session], formulaire: Callable[[Request], Any],
    objet_json: Callable[[Request], Any], cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any], prefixe: str,
) -> APIRouter:
    del session_api  # La lecture paramétrée passe par POST avec le contrôle CSRF parent.
    router = APIRouter()

    def session_vivante(request: Request, initiale: Session, *, api: bool) -> Session:
        courante = ecriture_api(request) if api else session_page(request)
        if courante.utilisateur != initiale.utilisateur:
            raise HTTPException(403, "identité modifiée pendant la lecture")
        return courante

    def lire(
        session: Session, charge: Mapping[str, str], inclure_prive: bool = False,
    ) -> Mapping[str, Any] | tuple[Mapping[str, Any], Mapping[str, Any] | None]:
        vue_privee = None
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(cnx, deps, session, "m5_preparer_dossier_decision_cfo", charge)
                if inclure_prive:
                    personne = identite.personne_active(cnx, session.utilisateur)
                    if personne is not None and personne.roles & {"finance", "nathan_owner"}:
                        snapshot_prive = obligations_privees.lire(cnx)
                        vue_privee = paie_das_privees_cfo.composer(snapshot_prive)
                        personne = identite.personne_active(cnx, session.utilisateur)
                        if personne is None or not (personne.roles & {"finance", "nathan_owner"}):
                            raise HTTPException(403, "droit financier retiré pendant la lecture privée")
        except obligations_privees.RefusObligation as exc:
            raise HTTPException(409, "snapshot privé paie/DAS indisponible") from exc
        except paie_das_privees_cfo.SnapshotPriveInvalide as exc:
            raise HTTPException(409, "vue privée paie/DAS invalide") from exc
        except PermissionError:
            raise HTTPException(403, "accès financier refusé") from None
        except KeyError:
            raise HTTPException(404, "dossier financier indisponible") from None
        except ValueError:
            raise HTTPException(400, "question ou lecture financière invalide") from None
        ok, rapport, erreur = frontoffice_marketing.resultat_metier(reponse)
        if not ok or not isinstance(rapport, Mapping) or not _json_valide(rapport):
            raise HTTPException(409, erreur.get("message", "dossier financier indisponible"))
        rubriques = rapport.get("rubriques")
        if (
            not isinstance(rubriques, list)
            or len(rubriques) != 25
            or any(not isinstance(s, Mapping) for s in rubriques)
            or any(
                isinstance(s.get("numero"), bool)
                or not isinstance(s.get("numero"), int)
                or s.get("numero") != numero
                or not isinstance(s.get("titre"), str)
                or not s.get("titre")
                or not isinstance(s.get("statut"), str)
                or s.get("statut") not in _STATUTS
                or not _json_valide(s.get("contenu"))
                or any(not _json_valide(s.get(champ, [])) for champ in (
                    "source_refs", "hypotheses", "manque", "limites",
                ))
                for numero, s in enumerate(rubriques, 1)
            )
        ):
            raise HTTPException(409, "dossier financier incomplet")
        return (rapport, vue_privee) if inclure_prive else rapport

    def _rendu_prive(vue: Mapping[str, Any] | None) -> str:
        if vue is None:
            return ""
        lignes = []
        for ligne in vue["lignes"]:
            source_statut = ligne["statut_source"]
            statut = {
                "ACTIVE": "Active, impact non résolu",
                "REMPLACEE": "Remplacée, historique",
                "REGLEMENT_DECLARE_NON_RAPPROCHE": "Règlement déclaré, non rapproché",
            }.get(source_statut, "État à vérifier")
            applicabilite = ligne["applicabilite"]
            cellules = (
                ligne["id"], ligne["type"], statut, ligne["montant_declare_cad"],
                ligne["periode"][0], ligne["periode"][1], ligne["date_paie"], ligne["echeance"],
                ligne["autorite"], ligne["reference_piece"], ligne["source_consultee_le"],
                applicabilite[0], applicabilite[1], ligne["version"], ligne["confirmee_le"],
                ligne["reglee_le"], ligne["reference_cycle"], ligne["montant_utilisable_cad"],
            )
            lignes.append("<tr>" + "".join(f"<td>{pages.e(valeur)}</td>" for valeur in cellules) + "</tr>")
        motifs = "".join(f"<li>{pages.e(raison)}</li>" for raison in vue["raisons"])
        return (
            '<section class="carte pile" aria-labelledby="impact-paie-prive">'
            '<h2 id="impact-paie-prive">Déclarations paie/DAS privées</h2>'
            f'<p><a href="{pages.e(prefixe)}/finance/paie/rapprochements">Rapprocher les sources et consulter '
            'le cash privé</a></p>'

            f'<p>État du rapprochement : {pages.e(vue["statut"])}. Révision source privée '
            f'{pages.e(vue["revision_source"])}; snapshot {pages.e(vue["snapshot_prive_id"])}.</p>'
            '<p>Montant utilisable : non disponible. Ces montants déclarés ne sont pas intégrés au cash libre '
            'ni aux prévisions; aucun cumul n’est calculé. Le cash présenté dans le dossier principal '
            'repose sur les anciennes sources et reste à rapprocher avec ces déclarations privées.</p>'
            '<ul>' + motifs + '</ul>'
            '<table><thead><tr><th>ID privé</th><th>Catégorie</th><th>État</th><th>Montant déclaré CAD</th>'
            '<th>Période début</th><th>Période fin</th><th>Date de paie</th><th>Échéance</th>'
            '<th>Autorité</th><th>Pièce</th><th>Source consultée le</th><th>Applicabilité début</th>'
            '<th>Applicabilité fin</th><th>Version</th><th>Confirmation</th><th>Règlement déclaré le</th>'
            '<th>Référence de cycle</th><th>Montant utilisable CAD</th></tr></thead><tbody>'
            + "".join(lignes) + '</tbody></table>'
            '</section>'
        )

    def page(
        session: Session, rapport: Mapping[str, Any] | None = None,
        vue_privee: Mapping[str, Any] | None = None,
    ) -> HTMLResponse:
        question = str(rapport.get("question_posee", "")) if rapport else ""
        contenu = (
            '<section class="carte"><h2>Préparer un dossier de décision</h2>'
            '<p>Le dossier rassemble les faits financiers disponibles et les pièces manquantes. '
            'La lecture ne déclenche aucune opération financière.</p>'
            f'<form method="post" action="{pages.e(prefixe)}/finance/cfo" class="pile">'
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
            '<label>Question à examiner<textarea name="question_posee" required maxlength="1000">'
            f'{pages.e(question)}</textarea></label>'
            '<button type="submit" class="principal">Préparer le dossier</button></form></section>'
        )
        if rapport is not None:
            contenu += _rapport(rapport)
        contenu += _rendu_prive(vue_privee)
        return HTMLResponse(pages.gabarit(
            "Dossier de décision financière", contenu, prefixe=prefixe, session=session, actif="finance"
        ), headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    @router.get("/finance/cfo", response_class=HTMLResponse)
    def formulaire_cfo(request: Request) -> HTMLResponse:
        session = session_page(request)
        _sans_query(request)
        return page(session)

    @router.post("/finance/cfo", response_class=HTMLResponse)
    async def dossier_formulaire(request: Request) -> HTMLResponse:
        session = session_page(request)
        _sans_query(request)
        champs = await formulaire(request)
        if not securite.csrf_valide(champs.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide : rechargez la page")
        charge = _charge({cle: valeur for cle, valeur in champs.items() if cle != "csrf"})
        rapport, vue_privee = await run_in_threadpool(lire, session, charge, True)
        reponse = page(session, rapport, vue_privee)
        session_vivante(request, session, api=False)
        return reponse

    @router.post("/api/finance/cfo")
    async def dossier_api(request: Request) -> JSONResponse:
        session = ecriture_api(request)
        _sans_query(request)
        charge = _charge(await objet_json(request))
        rapport = await run_in_threadpool(lire, session, charge)
        reponse = JSONResponse({"ok": True, "resultat": rapport})
        session_vivante(request, session, api=True)
        return reponse

    return router


def _label(nom: Any) -> str:
    return _LIBELLES.get(str(nom), str(nom).replace("_", " ").capitalize())


def _donnee(valeur: Any) -> str:
    if valeur is None:
        return '<span class="note">Non disponible</span>'
    if isinstance(valeur, bool):
        return "Oui" if valeur else "Non"
    if isinstance(valeur, Mapping):
        obligations = valeur.get("obligations_declarees")
        if isinstance(obligations, list):
            autres = {cle: element for cle, element in valeur.items() if cle != "obligations_declarees"}
            return _obligations_compactes(obligations) + _donnee(autres)
        series = [valeur.get(cle) for cle in ("entrees_cad", "sorties_cad", "solde_fin_cad")]
        if all(isinstance(serie, list) for serie in series) and "debut_premiere_semaine" in valeur:
            # Le contrat transmet les montants exacts en séries pour économiser le contexte.
            # La console ne fait que dater et ranger ces cellules, sans calcul financier.
            debut = date.fromisoformat(valeur["debut_premiere_semaine"])
            exceptions = dict(valeur.get("statuts_non_calcules", []))
            lignes = [
                [index + 1, (debut + timedelta(days=valeur["pas_jours"] * index)).isoformat(),
                 exceptions.get(index + 1, valeur["statut_par_defaut"]),
                 *[serie[index] for serie in series]]
                for index in range(valeur["semaines_couvertes"])
            ]
            return _donnee({
                "horizon_semaines": valeur["horizon_semaines"],
                "semaines_couvertes": valeur["semaines_couvertes"],
                "colonnes": ["semaine", "debut", "statut", "entrees_cad", "sorties_cad", "solde_fin_cad"],
                "lignes": lignes,
            })
        cle_lignes = "semaines" if "semaines" in valeur else "lignes"
        colonnes, lignes = valeur.get("colonnes"), valeur.get(cle_lignes)
        if isinstance(colonnes, list) and isinstance(lignes, list):
            entete = "".join(f"<th>{pages.e(_label(c))}</th>" for c in colonnes)
            corps = "".join(
                "<tr>" + "".join(f"<td>{_donnee(v)}</td>" for v in ligne) + "</tr>"
                for ligne in lignes if isinstance(ligne, list)
            )
            meta = {k: v for k, v in valeur.items() if k not in {"colonnes", cle_lignes}}
            return _donnee(meta) + (
                '<div class="table-defilante"><table><thead><tr>' + entete
                + "</tr></thead><tbody>" + corps + "</tbody></table></div>"
            )
        return "<dl>" + "".join(
            f"<dt>{pages.e(_label(k))}</dt><dd>{_donnee(v)}</dd>" for k, v in valeur.items()
        ) + "</dl>"
    if isinstance(valeur, list):
        return "<ul>" + "".join(f"<li>{_donnee(v)}</li>" for v in valeur) + "</ul>" if valeur else "Aucun élément"
    return pages.e(valeur)


def _rapport(rapport: Mapping[str, Any]) -> str:
    contenu = f'<p class="note">{pages.e(rapport.get("mention", ""))}</p>'
    for rubrique in rapport["rubriques"]:
        numero = rubrique["numero"]
        valeur = rubrique.get("contenu")
        if numero == 1:
            valeur = rapport.get("question_posee")
        contenu += (
            '<section class="carte">'
            f'<h2>{numero}. {pages.e(rubrique["titre"])}</h2>'
            f'<p class="note">{pages.e(_STATUTS.get(rubrique.get("statut"), "Non disponible"))}</p>'
            + _donnee(valeur)
        )
        if numero in {15, 16, 17}:
            contenu += (
                '<p class="note">Ces éléments décrivent les obligations actuelles et leurs sources. '
                'L’effet de la décision envisagée sur les taxes, la paie ou la dette reste à établir.</p>'
            )
        for champ in ("source_refs", "hypotheses", "manque", "limites"):
            if rubrique.get(champ):
                contenu += f'<h3>{pages.e(_label(champ))}</h3>' + _donnee(rubrique[champ])
        if numero == 5:
            contenu += '<p class="note">Sources canoniques consultées pour ce dossier.</p>'
        contenu += "</section>"
    return contenu
