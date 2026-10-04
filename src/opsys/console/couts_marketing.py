"""Console privée de répartition AP→M7 par SDK réel, sans paiement ni ROI.

Le port M7 est construit par le serveur depuis les départements installés. Ni
le JSON, ni la session déclarative, ni le nom d'un rôle ne constituent l'autorité.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import approbations, contexte, idempotence, identite, stockage
from ..etat import journaliser
from ..outils import Autonomie, Niveau, executer_atomique, valider_arguments
from . import pages, securite

LECTURE = "m5_lire_couts_marketing_affectes"
ECRITURES = frozenset({"m5_affecter_cout_marketing", "m5_revoquer_affectation_cout_marketing"})
ACTIONS = ECRITURES | {LECTURE}
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_MAX_SORTIE = 32 * 1024


def autoriser(cnx, session, *, ecriture=False):
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None or not personne.roles.intersection({"admin", "nathan_owner"}):
        raise PermissionError("accès coûts retiré")
    if ecriture and "nathan_owner" not in personne.roles:
        raise PermissionError("propriétaire requis")
    return personne


def _outil_prive(cnx, deps, session, nom):
    m5, m7 = deps.get("m05-financecore"), deps.get("m07-marketing")
    if m5 is None or m7 is None or m7.module_outils != "m7_marketing.outils":
        raise ValueError("SOURCE-DEPARTEMENT-ABSENTE")
    catalogue = [o for o in m7.charger_outils() if o.nom == "m7_lire_campagne_locale"]
    if (len(catalogue) != 1 or catalogue[0].autonomie is not Autonomie.T0
            or catalogue[0].niveau_effectif is not Niveau.N0):
        raise ValueError("SOURCE-CONTRAT-INVALIDE")

    def lire(campagne_id):
        if stockage.connexion_courante() is not cnx:
            raise PermissionError("contexte de lecture changé")
        personne = autoriser(cnx, session, ecriture=nom in ECRITURES)
        role = "nathan_owner" if "nathan_owner" in personne.roles else "admin"
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne.identifiant, role, "console")), \
                contexte.appeler_en_tant_que(m7.id, origine=m5.id):
            reponse = executer_atomique(catalogue[0], {"campagne_id": campagne_id})
        autoriser(cnx, session, ecriture=nom in ECRITURES)
        return reponse

    outils = [o for o in m5.charger_outils(ports_prives={"lecteur_campagne_m7": lire}) if o.nom == nom]
    if len(outils) != 1 or outils[0].roles_appareil:
        raise ValueError("SOURCE-CONTRAT-INVALIDE")
    niveau = Niveau.N4 if nom in ECRITURES else Niveau.N0
    if outils[0].niveau_effectif is not niveau:
        raise ValueError("SOURCE-CONTRAT-INVALIDE")
    return outils[0]


def executer_action(cnx, deps, session, nom, arguments, mutation_id=None):
    """Même reçu canonique et vraie approbation N4 ; rollback du parcours entier sur refus."""
    if nom not in ACTIONS:
        raise KeyError("action coûts inconnue")
    ecriture = nom in ECRITURES
    personne = autoriser(cnx, session, ecriture=ecriture)
    if cnx.dialect.name != "sqlite":
        raise ValueError("REJ-COUT-MARKETING-BACKEND-NON-PRIS-EN-CHARGE")
    if stockage.connexion_courante() is not cnx:
        raise ValueError("REJ-COUT-MARKETING-TRANSACTION-REQUISE")
    if ecriture != (mutation_id is not None):
        raise ValueError("mutation_id requis seulement pour une écriture")
    outil = _outil_prive(cnx, deps, session, nom)
    if not isinstance(arguments, Mapping) or valider_arguments(outil.parametres, arguments):
        raise ValueError("ARGUMENTS-INVALIDES")
    if len(json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode("utf-8")) > _MAX_SORTIE:
        raise ValueError("ARGUMENTS-INVALIDES")
    meta = None
    if ecriture:
        if not isinstance(mutation_id, str) or not mutation_id.strip() or len(mutation_id) > 200:
            raise ValueError("ARGUMENTS-INVALIDES")
        maintenant = datetime.now(UTC)
        meta = idempotence.Meta(mutation_id, f"console:{personne.identifiant}", maintenant.isoformat())
        try:
            reclamation = idempotence.reclamer(cnx, meta, nom, arguments, maintenant)
        except idempotence.MutationConflit:
            raise ValueError("CONFLIT-COMMANDE") from None
        if reclamation.rejouee:
            autoriser(cnx, session, ecriture=True)
            return {**reclamation.reponse, "rejoue": True, "nature_recu": "HISTORIQUE"}
        ident = approbations.creer_demande(cnx, "m05-financecore", nom, arguments, niveau=Niveau.N4)
        with contexte.appele_par_appareil(None):
            decision = approbations.decider(cnx, ident, True, personne.identifiant, {nom: outil}, deps,
                                           motif="Répartition interne demandée par le propriétaire dans la console")
        reponse = {**decision["reponse"], "approbation_id": ident}
    else:
        role = "admin" if "admin" in personne.roles else "nathan_owner"
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne.identifiant, role, "console")), \
                contexte.appeler_en_tant_que("m05-financecore", origine="console"):
            reponse = executer_atomique(outil, arguments)
    if not approbations.execution_reussie(reponse):
        if any(code in str(reponse.get("details", "")) for code in ("ACCES-REFUSE", "OWNER-N4-REQUIS")):
            raise PermissionError("accès coûts retiré")
        raise ValueError("SOURCE-COUTS-REFUSEE")
    autoriser(cnx, session, ecriture=ecriture)
    if meta is not None:
        idempotence.finaliser(cnx, meta, reponse)
        journaliser(cnx, personne.identifiant, "console.action_interne", nom,
                    {"departement": "m05-financecore", "mutation_id": mutation_id, "ok": True})
    return reponse


def _charge(reponse):
    charge = reponse["resultat"]
    if (not isinstance(charge, Mapping) or charge.get("accepte") is not True
            or not isinstance(charge.get("resultat"), dict)):
        raise ValueError("SOURCE-COUTS-REFUSEE")
    return charge["resultat"]


def _query(request):
    permis = {"campagne_id", "debut", "fin", "offset_affectations", "offset_pieces", "snapshot_attendu"}
    valeurs = {}
    for cle, valeur in request.query_params.multi_items():
        if cle not in permis or cle in valeurs or len(valeur.encode("utf-8")) > 2048:
            raise ValueError("ARGUMENTS-INVALIDES")
        valeurs[cle] = valeur
    if not {"campagne_id", "debut", "fin"} <= set(valeurs):
        raise ValueError("ARGUMENTS-INVALIDES")
    for cle in ("offset_affectations", "offset_pieces"):
        if cle in valeurs:
            if not re.fullmatch(r"[0-9]{1,6}", valeurs[cle]):
                raise ValueError("ARGUMENTS-INVALIDES")
            valeurs[cle] = int(valeurs[cle])
    if "snapshot_attendu" in valeurs:
        valeurs["snapshot_attendu"] = json.loads(valeurs["snapshot_attendu"])
    return valeurs


def creer_router(*, session_page, session_api, ecriture_api, formulaire, objet_json, cnx_factory, deps, prefixe):
    router = APIRouter(tags=["coûts marketing privés M5→M7"])

    def erreur(exc):
        status = 403 if isinstance(exc, PermissionError) else 400 if str(exc) == "ARGUMENTS-INVALIDES" else 409
        return HTTPException(status, "accès refusé" if status == 403 else "commande ou source coûts refusée",
                             headers=_NO_STORE)

    def appeler(session, nom, arguments, mutation_id=None):
        try:
            with cnx_factory() as cnx:
                reponse = executer_action(cnx, deps, session, nom, arguments, mutation_id)
            return reponse
        except (PermissionError, KeyError, TypeError, ValueError, RecursionError) as exc:
            raise erreur(exc) from None

    def confirmer(session, ecriture=False):
        try:
            with cnx_factory() as cnx:
                autoriser(cnx, session, ecriture=ecriture)
        except PermissionError as exc:
            raise erreur(exc) from None

    def lire(session, request):
        confirmer(session)
        try:
            arguments = _query(request)
        except (TypeError, ValueError, RecursionError):
            raise HTTPException(400, "filtres invalides", headers=_NO_STORE) from None
        resultat = _charge(appeler(session, LECTURE, arguments))
        confirmer(session)
        return resultat

    @router.get("/api/marketing/cmo/couts")
    def api_lire(request: Request):
        session = session_api(request)
        resultat = lire(session, request)
        reponse = JSONResponse({"ok": True, "resultat": resultat}, headers=_NO_STORE)
        if len(reponse.body) > _MAX_SORTIE:
            raise HTTPException(409, "projection trop grande", headers=_NO_STORE)
        confirmer(session)
        return reponse

    @router.get("/marketing/cmo/couts", response_class=HTMLResponse)
    def page(request: Request):
        session = session_page(request)
        confirmer(session)
        contenu = _formulaire_recherche(prefixe)
        if request.query_params:
            resultat = lire(session, request)
            with cnx_factory() as cnx:
                personne = autoriser(cnx, session)
            contenu += _html(resultat, prefixe, session, "nathan_owner" in personne.roles)
        html = pages.gabarit("Coûts de campagne", contenu, prefixe=prefixe, session=session, actif="marketing")
        if len(html.encode("utf-8")) > 64 * 1024:
            raise HTTPException(409, "rendu trop grand, consulter la page JSON privée", headers=_NO_STORE)
        confirmer(session)
        return HTMLResponse(html, headers=_NO_STORE)

    async def commande(request, nom):
        session = ecriture_api(request)
        confirmer(session, True)
        if request.query_params:
            raise HTTPException(400, "paramètres non attendus", headers=_NO_STORE)
        corps = await objet_json(request)
        if not isinstance(corps, dict) or set(corps) != {"arguments", "mutation_id"}:
            raise HTTPException(400, "commande invalide", headers=_NO_STORE)
        reponse = appeler(session, nom, corps["arguments"], corps["mutation_id"])
        resultat = JSONResponse({"ok": True, "resultat": _charge(reponse), "approbation_id": reponse["approbation_id"],
                                  "rejoue": reponse.get("rejoue", False),
                                  "nature_recu": "HISTORIQUE" if reponse.get("rejoue") else "NOUVELLE_VERSION"},
                                 headers=_NO_STORE)
        confirmer(session, True)
        return resultat

    @router.post("/api/marketing/cmo/couts/affectations")
    async def api_affecter(request: Request):
        return await commande(request, "m5_affecter_cout_marketing")

    @router.post("/api/marketing/cmo/couts/retraits")
    async def api_retirer(request: Request):
        return await commande(request, "m5_revoquer_affectation_cout_marketing")

    @router.post("/marketing/cmo/couts/affectations")
    async def formulaire_affecter(request: Request):
        session = session_page(request)
        confirmer(session, True)
        champs = await formulaire(request)
        if not securite.csrf_valide(champs.get("csrf"), session):
            raise HTTPException(403, "CSRF invalide", headers=_NO_STORE)
        try:
            requis = {"csrf", "mutation_id", "action", "campagne_id", "debut", "fin", "motif"}
            if champs.get("action") == "retirer":
                if set(champs) != requis | {"affectation_id", "version_attendue", "snapshot_attendu"}:
                    raise ValueError
                args = {"affectation_id": champs["affectation_id"],
                        "version_attendue": int(champs["version_attendue"]),
                        "snapshot_attendu": json.loads(champs["snapshot_attendu"]), "motif": champs["motif"]}
                nom = "m5_revoquer_affectation_cout_marketing"
            else:
                permis = requis | {
                    "facture_fournisseur_id", "devise", "base", "montant_alloue_cad", "sources_attendues",
                }
                if champs.get("action") != "affecter" or set(champs) not in (permis, permis | {"affectation_id"}):
                    raise ValueError
                args = {k: v for k, v in champs.items() if k not in {"csrf", "mutation_id", "action"}}
                args["sources_attendues"] = json.loads(args["sources_attendues"])
                nom = "m5_affecter_cout_marketing"
        except (KeyError, TypeError, ValueError, RecursionError):
            raise HTTPException(400, "formulaire invalide", headers=_NO_STORE) from None
        appeler(session, nom, args, champs["mutation_id"])
        confirmer(session, True)
        return RedirectResponse(f"{prefixe}/marketing/cmo/couts?" + urlencode({k: champs[k] for k in (
            "campagne_id", "debut", "fin",
        )}), status_code=303, headers=_NO_STORE)

    return router


def _formulaire_recherche(prefixe):
    return (f'<p><a href="{pages.e(prefixe)}/marketing/cmo">Retour au CMO</a></p>'
            f'<form method="get" action="{pages.e(prefixe)}/marketing/cmo/couts" class="formulaire">'
            '<label>ID de campagne locale<input name="campagne_id" maxlength="128" required></label>'
            '<label>Début de prestation<input type="date" name="debut" required></label>'
            '<label>Fin de prestation<input type="date" name="fin" required></label>'
            '<button type="submit">Lire les coûts affectés</button></form>')


def _html(resultat, prefixe, session, owner):
    def hidden(cle, valeur):
        if isinstance(valeur, (dict, list)):
            valeur = json.dumps(valeur, ensure_ascii=False, separators=(",", ":"))
        return f'<input type="hidden" name="{pages.e(cle)}" value="{pages.e(valeur)}">'

    def form(piece, part=None):
        champs = {"csrf": session.csrf, "mutation_id": uuid.uuid4().hex, "action": "affecter",
                  "campagne_id": resultat["campagne"]["campagne_id"],
                  "facture_fournisseur_id": piece["facture_fournisseur_id"],
                  "sources_attendues": part["sources_courantes"] if part else piece["sources_attendues"]}
        if part:
            champs["affectation_id"] = part["affectation_id"]
        p = part["periode"] if part else resultat["periode"]
        base = part["base"] if part else piece.get("base_reservee") or "HT"
        return (f'<form method="post" action="{pages.e(prefixe)}/marketing/cmo/couts/affectations" '
                'class="formulaire">'
                + "".join(hidden(k, v) for k, v in champs.items())
                + '<label>Début de prestation<input type="date" name="debut" '
                + f'value="{pages.e(p["debut"])}" required></label>'
                + '<label>Fin de prestation<input type="date" name="fin" '
                + f'value="{pages.e(p["fin"])}" required></label>'
                + '<label>Devise déclarée<select name="devise"><option>CAD</option></select></label>'
                + '<p>La pièce AP ne porte pas de devise : confirmez CAD. Aucune conversion.</p>'
                + '<label>Base analytique<select name="base">'
                + "".join(f'<option value="{b}"{" selected" if b == base else ""}>{b}</option>' for b in ("HT", "TTC"))
                + '</select></label><label>Part affectée CAD<input name="montant_alloue_cad" '
                + f'inputmode="decimal" maxlength="15" value="{pages.e(part["montant_alloue_cad"] if part else "")}" '
                + 'required></label>'
                + f'<label>Motif<input name="motif" maxlength="300" value="{pages.e(part["motif"] if part else "")}" '
                + 'required></label>'
                + '<button type="submit">Valider cette version</button></form>')

    morceaux = [f'<h2>{pages.e(resultat["campagne"]["nom"])}</h2>',
                 '<p>Répartition humaine sur pièces déclarées. Couverture partielle ou inconnue ; '
                 'paiement, récupération des taxes, coût économique et ROI inconnus. HT et TTC restent séparés.</p>',
                 f'<p>Couverture : {pages.e(resultat["couverture"])}. '
                 f'HT : {pages.e(resultat["totaux_par_base"]["HT"] or "Inconnu")} ; '
                 f'TTC : {pages.e(resultat["totaux_par_base"]["TTC"] or "Inconnu")}. CAD déclaré.</p>',
                 '<h3>Affectations</h3>']
    for part in resultat["affectations"]:
        morceaux.append(f'<article><p>{pages.e(part["affectation_id"])} · version {part["version"]} · '
                        f'{pages.e(part["montant_alloue_cad"])} CAD {pages.e(part["base"])} · '
                        f'{pages.e(part["statut"])}. '
                        f'Exclusion : {pages.e(part["exclusion"] or "aucune")}</p>')
        if owner and part["statut"] != "RETIREE":
            if part["piece_statut"] != "ANNULEE":
                morceaux.append(form(part, part))
            champs = {"csrf": session.csrf, "mutation_id": uuid.uuid4().hex, "action": "retirer",
                      "campagne_id": resultat["campagne"]["campagne_id"], **resultat["periode"],
                      "affectation_id": part["affectation_id"], "version_attendue": part["version"],
                      "snapshot_attendu": resultat["observation_source"]["affectations"]}
            morceaux.append(f'<form method="post" action="{pages.e(prefixe)}/marketing/cmo/couts/affectations">'
                            + "".join(hidden(k, v) for k, v in champs.items())
                            + '<label>Motif du retrait<input name="motif" maxlength="300" required></label>'
                            + '<button type="submit">Retirer la répartition</button></form>')
        morceaux.append('</article>')
    morceaux.append('<h3>Pièces AP sans PO disponibles</h3>')
    for piece in resultat["pieces_eligibles"]:
        morceaux.append(f'<article><p>Pièce {pages.e(piece["facture_fournisseur_id"])} · '
                        f'{pages.e(piece["categorie_depense"])} · HT {pages.e(piece["montant_avant_taxes"])} / '
                        f'TTC {pages.e(piece["montant_apres_taxes"])} · réserve {pages.e(piece["reserve_cad"])} '
                        f'{pages.e(piece["base_reservee"] or "sans base affectée")}</p>')
        if owner:
            morceaux.append(form(piece))
        morceaux.append('</article>')
    for cle, page in (
        ("offset_affectations", resultat["pagination"]), ("offset_pieces", resultat["pagination_pieces"]),
    ):
        morceaux.append(f'<p>{page["affichees"]} lignes affichées sur {page["total"]} ; {page["reste"]} restantes.</p>')
        if page["suivant"] is not None:
            params = {"campagne_id": resultat["campagne"]["campagne_id"], **resultat["periode"],
                      "offset_affectations": resultat["pagination"]["offset"],
                      "offset_pieces": resultat["pagination_pieces"]["offset"], cle: page["suivant"],
                      "snapshot_attendu": json.dumps(resultat["observation_source"], separators=(",", ":"))}
            url = pages.e(prefixe + "/marketing/cmo/couts?" + urlencode(params))
            morceaux.append(f'<a href="{url}">Page suivante</a>')
    return "".join(morceaux)
