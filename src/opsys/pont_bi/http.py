"""Routes HTTP du pont BI : GET seulement, jeton de lecture dédié, aucune session, aucun cookie.

Deux surfaces, mêmes jeux, mêmes gardes :

* ``/pont-bi/v1/jeux`` (liste) et ``/pont-bi/v1/jeux/{jeu}.csv`` ou ``.jsonl`` : exports à plat pour un tableur,
Metabase,
  Superset ou Grafana (source CSV/JSON) ;
* ``/pont-bi/odata/`` (document de service), ``$metadata`` et ``/pont-bi/odata/{Entité}`` : OData v4 MINIMAL.

Gardes, dans l'ordre : (1) méthode — tout autre verbe que GET est refusé 405 (et journalisé si le jeton est valide) ;
(2) jeton dans l'en-tête ``Authorization`` seulement, jamais dans l'URL (un paramètre ``access_token`` ou ``token``
est un
refus 400) ; (3) jeton connu, non révoqué, non expiré, secret comparé au coffre ; (4) jeu permis par le jeton ; (5)
quota de
requêtes ; (6) lecture seule ; (7) quota de lignes ; (8) minimisation PII ; (9) journal. Chaque refus est journalisé
avec son
code, jamais avec un secret. ``Cache-Control: no-store`` partout.

Tout est en lecture : le routeur n'importe aucune fonction d'écriture de l'entrepôt.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..observabilite.pii import MasqueurPII
from ..secrets_coffre.cle_maitresse import CleMaitresse
from . import formats, service
from .jeux import JEUX, PAR_ENTITE, Jeu

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}
_PARAMETRES_JETON = frozenset({"access_token", "token", "jeton", "bearer", "api_key", "apikey", "key"})
_EXPORT_FORMATS = {"csv": "text/csv; charset=utf-8", "jsonl": "application/x-ndjson; charset=utf-8"}
_LIMITE_DEFAUT = 1000


def creer_router(
    *,
    cnx_factory: Callable[[], Any],
    masqueur: Callable[[], MasqueurPII] | None = None,
    cle: Callable[[], CleMaitresse | None] | None = None,
    horloge: Callable[[], float] = time.time,
) -> APIRouter:
    """``masqueur`` fabrique le masqueur PII au premier besoin (clé locale d'observabilité) ; ``cle`` fournit la clé
    maîtresse
    du coffre (``None`` : celle de l'instance). Les deux sont des ports : les tests y mettent des doubles."""
    router = APIRouter(tags=["pont-bi"])

    def refus(
        statut: int, code: str, message: str, odata: bool = False, extra: dict[str, str] | None = None
    ) -> Response:
        corps: dict[str, Any] = (
            formats.corps_erreur(formats.ErreurFormat(statut, code, message))
            if odata
            else {"ok": False, "erreur": code, "message": message}
        )
        return JSONResponse(corps, status_code=statut, headers={**ENTETES, **(extra or {})})

    def refuser_jeton_dans_url(request: Request) -> None:
        if any(cle_param.lower() in _PARAMETRES_JETON for cle_param in request.query_params):
            raise service.RefusPontBI(
                400, "jeton_dans_l_url", "le jeton ne se met jamais dans l'URL : en-tête Authorization"
            )

    def authentifier(request: Request, maintenant: float) -> dict[str, Any]:
        refuser_jeton_dans_url(request)
        jeton_id, secret = service.lire_jeton(request.headers.get("authorization"))
        with cnx_factory() as cnx:
            jeton = service.charger_jeton(cnx, jeton_id, maintenant)
        service.verifier_secret(cnx_factory, jeton, secret, cle=cle() if cle else None, maintenant=maintenant)
        return jeton

    def tracer_refus(maintenant: float, jeton_id: str | None, jeu: str | None, format: str | None, code: str) -> None:
        try:
            with cnx_factory() as cnx:
                service.journaliser(
                    cnx,
                    maintenant=maintenant,
                    jeton_id=jeton_id,
                    jeu=jeu,
                    format=format,
                    phase="debut",
                    statut="refuse",
                    code=code,
                )
        except Exception:  # un journal indisponible ne transforme pas un refus en succès  # noqa: BLE001
            pass

    def servir(
        request: Request,
        jeu: Jeu,
        format: str,
        *,
        odata: bool,
        options: dict[str, Any] | None = None,
        limite: int = _LIMITE_DEFAUT,
        depart: int = 0,
        selection: list[str] | None = None,
    ) -> Response:
        maintenant = horloge()
        jeton_id: str | None = None
        try:
            jeton = authentifier(request, maintenant)
            jeton_id = jeton["jeton_id"]
            if jeu.nom not in jeton["jeux"]:
                raise service.RefusPontBI(403, "jeu_non_permis", "ce jeton ne couvre pas ce jeu")
            with cnx_factory() as cnx:
                service.controler_quota_requetes(cnx, jeton, maintenant)
                service.journaliser(
                    cnx,
                    maintenant=maintenant,
                    jeton_id=jeton_id,
                    jeu=jeu.nom,
                    format=format,
                    phase="debut",
                    statut="accepte",
                )
            with cnx_factory() as cnx, service.lecture_seule(cnx):
                colonnes, lignes, total = service.lire_jeu(
                    cnx, jeu, financier=jeton["financier"], limite=limite, depart=depart, selection=selection
                )
                construction = service.etat_entrepot(cnx)
            with cnx_factory() as cnx:
                service.controler_quota_lignes(cnx, jeton, maintenant, len(lignes))
            propres, masquees = formats.minimiser(jeu, colonnes, lignes, masqueur() if masqueur else None)
        except service.RefusPontBI as erreur:
            tracer_refus(maintenant, jeton_id, jeu.nom, format, erreur.code)
            return refus(
                erreur.statut,
                erreur.code,
                erreur.message,
                odata,
                {"Retry-After": "3600"} if erreur.statut == 429 else None,
            )
        except formats.ErreurFormat as erreur:
            tracer_refus(maintenant, jeton_id, jeu.nom, format, erreur.code)
            return refus(erreur.statut, erreur.code, erreur.message, odata)
        with cnx_factory() as cnx:
            service.journaliser(
                cnx,
                maintenant=maintenant,
                jeton_id=jeton_id,
                jeu=jeu.nom,
                format=format,
                phase="fin",
                statut="termine",
                lignes=len(propres),
            )
        entetes = {
            **ENTETES,
            "X-OPSYS-Lecture-Seule": "oui",
            "X-OPSYS-Total-Lignes": str(total),
            "X-OPSYS-Cellules-Masquees": str(masquees),
            "X-OPSYS-Entrepot-Construit-Le": construction["construit_le"] if construction else "aucune",
            "X-OPSYS-Entrepot-Construction": construction["construction_id"] if construction else "aucune",
        }
        if odata:
            base = str(request.base_url).rstrip("/") + "/pont-bi/odata"
            assert options is not None

            def suite(position: int) -> str:
                return f"{base}/{jeu.entite}?$top={options['top']}&$skip={position}"

            corps = formats.collection_odata(
                base, jeu, colonnes, propres, total=total, options=options, url_suite=suite
            )
            return JSONResponse(corps, headers={**entetes, "OData-Version": "4.0"})
        contenu = formats.vers_csv(colonnes, propres) if format == "csv" else formats.vers_jsonl(colonnes, propres)
        return Response(contenu, media_type=_EXPORT_FORMATS[format], headers=entetes)

    def entier(request: Request, nom: str, defaut: int, minimum: int, maximum: int) -> int:
        valeurs = request.query_params.getlist(nom)
        if len(valeurs) > 1:
            raise service.RefusPontBI(400, "parametre_repete", f"paramètre répété : {nom}")
        brut = valeurs[0] if valeurs else None
        if brut is None:
            return defaut
        if not brut.isdigit() or not minimum <= int(brut) <= maximum:
            raise service.RefusPontBI(400, "pagination_invalide", f"{nom} : entier de {minimum} à {maximum}")
        return int(brut)

    @router.get("/pont-bi/v1/jeux")
    def liste(request: Request) -> Response:
        maintenant = horloge()
        try:
            jeton = authentifier(request, maintenant)
        except service.RefusPontBI as erreur:
            tracer_refus(maintenant, None, None, None, erreur.code)
            return refus(erreur.statut, erreur.code, erreur.message)
        visibles = []
        for nom in jeton["jeux"]:
            jeu = JEUX[nom]
            visibles.append(
                {
                    "jeu": nom,
                    "entite_odata": jeu.entite,
                    "description": jeu.description,
                    "colonnes": [{"nom": c.nom, "type": c.edm} for c in jeu.colonnes_visibles(jeton["financier"])],
                    "formats": sorted(_EXPORT_FORMATS),
                    "url_csv": f"/pont-bi/v1/jeux/{nom}.csv",
                    "url_jsonl": f"/pont-bi/v1/jeux/{nom}.jsonl",
                }
            )
        with cnx_factory() as cnx:
            service.journaliser(
                cnx,
                maintenant=maintenant,
                jeton_id=jeton["jeton_id"],
                jeu=None,
                format="json",
                phase="debut",
                statut="accepte",
            )
            service.journaliser(
                cnx,
                maintenant=maintenant,
                jeton_id=jeton["jeton_id"],
                jeu=None,
                format="json",
                phase="fin",
                statut="termine",
                lignes=0,
            )
        return JSONResponse({"ok": True, "lecture_seule": True, "jeux": visibles}, headers=ENTETES)

    @router.get("/pont-bi/v1/jeux/{nom_format}")
    def exporter(nom_format: str, request: Request) -> Response:
        nom, _, format = nom_format.rpartition(".")
        jeu = JEUX.get(nom)
        if jeu is None or format not in _EXPORT_FORMATS:
            return refus(404, "jeu_inconnu", "jeu ou format inconnu")
        try:
            refuser_jeton_dans_url(request)
            inconnus = [k for k in request.query_params if k not in ("limite", "depart")]
            if inconnus:
                raise service.RefusPontBI(400, "parametre_inconnu", f"paramètre inconnu : {inconnus[0]}")
            limite = entier(request, "limite", _LIMITE_DEFAUT, 1, service.LIGNES_PAR_REQUETE_MAX)
            depart = entier(request, "depart", 0, 0, 10**9)
        except service.RefusPontBI as erreur:
            return refus(erreur.statut, erreur.code, erreur.message)
        return servir(request, jeu, format, odata=False, limite=limite, depart=depart)

    @router.get("/pont-bi/odata")
    @router.get("/pont-bi/odata/")
    def odata_service(request: Request) -> Response:
        maintenant = horloge()
        try:
            jeton = authentifier(request, maintenant)
        except service.RefusPontBI as erreur:
            tracer_refus(maintenant, None, None, None, erreur.code)
            return refus(erreur.statut, erreur.code, erreur.message, odata=True)
        base = str(request.base_url).rstrip("/") + "/pont-bi/odata"
        jeux = [JEUX[n] for n in jeton["jeux"]]
        return JSONResponse(formats.document_de_service(base, jeux), headers={**ENTETES, "OData-Version": "4.0"})

    @router.get("/pont-bi/odata/$metadata")
    def odata_metadata(request: Request) -> Response:
        maintenant = horloge()
        try:
            jeton = authentifier(request, maintenant)
        except service.RefusPontBI as erreur:
            tracer_refus(maintenant, None, None, None, erreur.code)
            return refus(erreur.statut, erreur.code, erreur.message, odata=True)
        xml = formats.metadata_edmx([JEUX[n] for n in jeton["jeux"]], jeton["financier"])
        return Response(xml, media_type="application/xml", headers={**ENTETES, "OData-Version": "4.0"})

    @router.get("/pont-bi/odata/{entite}")
    def odata_collection(entite: str, request: Request) -> Response:
        jeu = PAR_ENTITE.get(entite)
        if jeu is None:
            return refus(404, "entite_inconnue", "entité inconnue", odata=True)
        try:
            options = formats.lire_options(request.query_params.multi_items(), [c.nom for c in jeu.colonnes])
        except formats.ErreurFormat as erreur:
            return refus(erreur.statut, erreur.code, erreur.message, odata=True)
        return servir(
            request,
            jeu,
            "odata",
            odata=True,
            options=options,
            limite=options["top"],
            depart=options["skip"],
            selection=options["select"],
        )

    @router.get("/pont-bi/{chemin:path}")
    def inconnu(chemin: str) -> Response:
        return refus(404, "route_inconnue", "route inconnue")

    @router.api_route("/pont-bi/{chemin:path}", methods=["POST", "PUT", "PATCH", "DELETE"])
    def lecture_seule_uniquement(chemin: str, request: Request) -> Response:
        """Le pont est en LECTURE : tout verbe d'écriture est refusé 405, avec ou sans jeton ; avec un jeton valide, le
        refus est journalisé."""
        maintenant = horloge()
        jeton_id = None
        try:
            jeton_id = authentifier(request, maintenant)["jeton_id"]
        except service.RefusPontBI:
            jeton_id = None
        tracer_refus(maintenant, jeton_id, None, None, "lecture_seule")
        return refus(405, "lecture_seule", "le pont BI est en lecture seule : GET uniquement", extra={"Allow": "GET"})

    return router
