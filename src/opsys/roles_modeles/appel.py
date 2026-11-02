"""Appel routé par la politique d'économie, avec plafonds, replis et escalade encadrée ; test de connexion borné.

Chemin d'un appel : classe de tâche → rôle (`economie`) → affectation du rôle (sinon refus, aucun aiguillage par défaut)
→ cibles ordonnées [principal, *replis] → pour chacune : fournisseur actif ET conforme à la politique de licence,
plafonds (jetons par jour, budget du mois) du principal, puis l'appel. Un repli n'est tenté que sur panne retentable
(délai, 429, 5xx, hôte injoignable), plafond atteint ou fournisseur devenu inutilisable ; une erreur de requête ou
d'authentification (4xx) arrête tout : un autre fournisseur ne la corrigerait pas. Chaque tentative est rendue.

**Raisonnement (Opus).** Joignable par la seule classe `escalade_raisonnement`, avec (1) le réglage `raisonnement`
activé
par un geste N3 du propriétaire, (2) une `Escalade` signée par une personne active admin/propriétaire et motivée,
(3) aucune dérogation : pas de repli, jamais la cible d'un autre rôle. Chaque appel est journalisé.

L'appel ne tient aucune transaction pendant le réseau (le coffre l'interdit et un verrou d'écriture serait gardé).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from .. import etat, identite
from ..fournisseurs import registre
from ..fournisseurs.modele import Fournisseur
from ..fournisseurs.politique import evaluer
from ..secrets_coffre import coffre, masquage
from ..stockage.schema import FOURNISSEURS_CONFIGURATIONS
from . import acces, codes, economie, service
from . import roles as lex
from .client import JETONS_TEST_MAX, ClientOpenAI, ErreurAppel
from .codes import ModelesErreur

PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
OPERATION_DU_ROLE: dict[str, str] = {
    "llm_rapide": "completion",
    "llm_fort": "completion",
    "llm_raisonnement": "completion",
    "vl": "completion",
    "embeddings": "embeddings",
    "reranker": "rerank",
}


@dataclasses.dataclass(frozen=True)
class Escalade:
    """Demande explicite de raisonnement : une personne admin/propriétaire et son motif."""

    par: str
    motif: str


def _ceil_micro(valeur: Decimal) -> int:
    return int(math.ceil(valeur))


def _charger_cibles(cnx: Connection, role: str, ligne: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Pour chaque cible : fournisseur, état actif, verdict de politique — relus à CHAQUE appel."""
    profil = registre.lire_profil(cnx)
    cibles = []
    for rang, (fid, modele) in enumerate(
        [(ligne["fournisseur_id"], ligne["modele_appel"]), *((r["fournisseur"], r["modele"]) for r in ligne["replis"])]
    ):
        config = (
            cnx.execute(FOURNISSEURS_CONFIGURATIONS.select().where(FOURNISSEURS_CONFIGURATIONS.c.identifiant == fid))
            .mappings()
            .first()
        )
        cible: dict[str, Any] = {
            "rang": rang,
            "fournisseur_id": fid,
            "modele": modele,
            "fournisseur": None,
            "raison": None,
        }
        if config is None:
            cible["raison"] = "FOURNISSEUR_INCONNU"
        else:
            fournisseur = Fournisseur.depuis_json(json.loads(config["definition"]))
            cible["fournisseur"] = fournisseur
            decision = evaluer(fournisseur, profil)
            if not config["actif"]:
                cible["raison"] = "FOURNISSEUR_INACTIF"
            elif not decision.conforme:
                cible["raison"] = "REFUS_POLITIQUE:" + ",".join(decision.codes)
            elif fournisseur.capacite != lex.CAPACITE_DU_ROLE[role]:
                cible["raison"] = "CAPACITE_INCOMPATIBLE"
        cibles.append(cible)
    return cibles


def _autoriser_escalade(cnx: Connection, escalade: Escalade | None) -> Escalade:
    if not service.raisonnement_actif(cnx):
        raise ModelesErreur(
            codes.RAISONNEMENT_INACTIF, "le raisonnement n'est pas activé (geste N3 du propriétaire)", 403
        )
    if not isinstance(escalade, Escalade) or not isinstance(escalade.par, str) or not isinstance(escalade.motif, str):
        raise ModelesErreur(codes.ESCALADE_REFUSEE, "escalade explicite requise : personne et motif", 403)
    personne = identite.personne_active(cnx, escalade.par)
    if personne is None or not personne.roles.intersection(coffre.ROLES_ADMIN):
        raise ModelesErreur(
            codes.ESCALADE_REFUSEE, "l'escalade doit être demandée par une personne admin ou propriétaire active", 403
        )
    if not service._MOTIF.fullmatch(escalade.motif):  # noqa: SLF001
        raise ModelesErreur(codes.ESCALADE_REFUSEE, "motif de l'escalade requis (10 à 300 caractères)", 422)
    return escalade


def _estimer_entree(charge: Any) -> int:
    """Estimation prudente des jetons d'entrée quand l'amont n'en rapporte pas (3 caractères par jeton)."""
    return len(json.dumps(charge, ensure_ascii=False)) // 3 + 1


def _micro_usd(ligne: Mapping[str, Any], entree: int, sortie: int) -> int | None:
    cin, cout = ligne.get("cout_entree_par_million"), ligne.get("cout_sortie_par_million")
    if cin is None or cout is None:
        return None
    return _ceil_micro(Decimal(entree) * Decimal(cin) + Decimal(sortie) * Decimal(cout))


def _verifier_plafonds(
    cnx: Connection, role: str, ligne: Mapping[str, Any], entree_est: int, sortie_max: int
) -> str | None:
    """Raison d'un plafond atteint pour le fournisseur PRINCIPAL, ou `None` (les replis n'en ont pas)."""
    plafond = ligne["plafond_jetons_jour"]
    if plafond is not None:
        jour = service.usage(cnx, role)
        if jour["jetons_entree"] + jour["jetons_sortie"] + entree_est + sortie_max > plafond:
            return "PLAFOND_JETONS_JOUR"
    budget = ligne["budget_usd_mois"]
    if budget is not None:
        projete = _micro_usd(ligne, entree_est, sortie_max)
        if projete is None:
            return "BUDGET_NON_VERIFIABLE_COUT_INCONNU"
        if service.usage_mois(cnx, role)["cout_micro_usd"] + projete > _ceil_micro(Decimal(budget) * 1_000_000):
            return "PLAFOND_BUDGET_MOIS"
    return None


def _acheminer(
    fabrique: acces.FabriqueConnexion,
    *,
    classe: str,
    operation: str,
    charge: Any,
    sortie_max: int,
    executer: Callable[[ClientOpenAI, str], tuple[dict[str, Any], dict[str, int | None]]],
    escalade: Escalade | None,
    ouvrir=None,
    delai_s: float = 8.0,
    dans_transaction: bool = False,
) -> dict[str, Any]:
    try:
        regle = economie.regle(classe)
    except economie.ClasseInconnue as exc:
        raise ModelesErreur(codes.CLASSE_INCONNUE, str(exc), 422) from None
    role = regle["role"]
    if OPERATION_DU_ROLE.get(role) != operation:
        raise ModelesErreur(
            codes.CLASSE_INCONNUE, f"la classe {classe} (rôle {role}) n'est pas servie par l'opération {operation}", 422
        )
    with fabrique() as cnx:
        ligne = service.ligne_role(cnx, role)
        if ligne is None:
            raise ModelesErreur(
                codes.ROLE_NON_CONFIGURE, f"le rôle {role} n'est pas configuré : aucun appel (fail-closed)", 409
            )
        if regle["approbation"]:
            autorisation = _autoriser_escalade(cnx, escalade)
            etat.journaliser(
                cnx,
                autorisation.par,
                "modeles.escalade.appel",
                f"role:{role}",
                {"classe": classe, "motif": masquage.masquer_texte(autorisation.motif)[:300]},
            )
        cibles = _charger_cibles(cnx, role, ligne)
        entree_est = _estimer_entree(charge)
        plafond = _verifier_plafonds(cnx, role, ligne, entree_est, sortie_max)
    tentatives: list[dict[str, Any]] = []
    for cible in cibles:
        trace = {"fournisseur": cible["fournisseur_id"], "modele": cible["modele"], "repli": cible["rang"] > 0}
        if cible["raison"] is not None:
            tentatives.append({**trace, "statut": "ignoree", "code": cible["raison"]})
            continue
        if cible["rang"] == 0 and plafond is not None:
            tentatives.append({**trace, "statut": "ignoree", "code": plafond})
            continue
        try:
            with acces.client_du_fournisseur(
                fabrique, cible["fournisseur"], ouvrir=ouvrir, delai_s=delai_s, dans_transaction=dans_transaction
            ) as client:
                resultat, usage = executer(client, cible["modele"])
        except ErreurAppel as exc:
            tentatives.append({**trace, "statut": "echec", "code": exc.code, "detail": exc.detail[:160]})
            if not exc.retentable:
                raise ModelesErreur(
                    codes.APPEL_REFUSE,
                    f"{exc.detail[:160]} (aucun repli : la requête ou la configuration est en cause)",
                    502,
                    tuple(t["code"] for t in tentatives),
                ) from None
            continue
        except ModelesErreur as exc:
            tentatives.append({**trace, "statut": "ignoree", "code": exc.code})
            continue
        entree = usage.get("entree")
        sortie = usage.get("sortie")
        estime = entree is None or sortie is None
        entree = _estimer_entree(charge) if entree is None else entree
        sortie = sortie_max if sortie is None else sortie  # borne haute : jamais sous-compter un plafond
        cout = _micro_usd(ligne, entree, sortie) if cible["rang"] == 0 else 0
        with fabrique() as cnx:
            service.ajouter_usage(
                cnx, role, entree=entree, sortie=sortie, cout_micro_usd=cout or 0, repli=cible["rang"] > 0
            )
            if cible["rang"] > 0:
                etat.journaliser(
                    cnx,
                    acces.ACTEUR_SYSTEME,
                    "modeles.repli",
                    f"role:{role}",
                    {"vers": cible["fournisseur_id"], "raisons": [t["code"] for t in tentatives]},
                )
        tentatives.append({**trace, "statut": "succes"})
        return {
            "role": role,
            "classe": classe,
            "fournisseur": cible["fournisseur_id"],
            "modele": cible["modele"],
            "repli_utilise": cible["rang"] > 0,
            "tentatives": tentatives,
            "approbation_requise": regle["approbation"],
            "usage": {"entree": entree, "sortie": sortie, "estime": estime, "cout_micro_usd": cout},
            **resultat,
        }
    codes_vus = [t["code"] for t in tentatives]
    if any(
        c in ("PLAFOND_JETONS_JOUR", "PLAFOND_BUDGET_MOIS", "BUDGET_NON_VERIFIABLE_COUT_INCONNU") for c in codes_vus
    ):
        raise ModelesErreur(
            codes.PLAFOND_ATTEINT, f"plafond du rôle {role} atteint et aucun repli utilisable", 429, tuple(codes_vus)
        )
    if any(t["statut"] == "echec" for t in tentatives):
        raise ModelesErreur(codes.APPEL_ECHEC, f"aucun fournisseur du rôle {role} n'a répondu", 502, tuple(codes_vus))
    raise ModelesErreur(
        codes.FOURNISSEUR_REFUSE, f"aucun fournisseur utilisable pour le rôle {role}", 409, tuple(codes_vus)
    )


def completer(
    fabrique: acces.FabriqueConnexion,
    *,
    classe: str,
    messages: Sequence[Mapping[str, Any]],
    max_tokens: int = 256,
    escalade: Escalade | None = None,
    ouvrir=None,
    delai_s: float = 8.0,
) -> dict[str, Any]:
    if type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
        raise ModelesErreur(codes.DECLARATION_INVALIDE, "max_tokens : entier de 1 à 8192", 422)
    if not isinstance(messages, Sequence) or isinstance(messages, str) or not 1 <= len(messages) <= 64:
        raise ModelesErreur(codes.DECLARATION_INVALIDE, "messages : liste de 1 à 64 messages", 422)

    def executer(client: ClientOpenAI, modele: str):
        reponse = client.chat(modele, messages, max_tokens)
        return {"contenu": reponse["contenu"], "arret": reponse["arret"], "latence_ms": reponse["latence_ms"]}, reponse[
            "usage"
        ]

    return _acheminer(
        fabrique,
        classe=classe,
        operation="completion",
        charge=list(messages),
        sortie_max=max_tokens,
        executer=executer,
        escalade=escalade,
        ouvrir=ouvrir,
        delai_s=delai_s,
    )


def plonger(
    fabrique: acces.FabriqueConnexion,
    *,
    textes: Sequence[str],
    ouvrir=None,
    delai_s: float = 8.0,
    dans_transaction: bool = False,
) -> dict[str, Any]:
    if (
        not isinstance(textes, Sequence)
        or isinstance(textes, str)
        or not 1 <= len(textes) <= 256
        or not all(isinstance(t, str) for t in textes)
    ):
        raise ModelesErreur(codes.DECLARATION_INVALIDE, "textes : liste de 1 à 256 chaînes", 422)

    def executer(client: ClientOpenAI, modele: str):
        reponse = client.embeddings(modele, textes)
        return {"vecteurs": reponse["vecteurs"], "latence_ms": reponse["latence_ms"]}, {
            "entree": reponse["usage"]["entree"],
            "sortie": 0,
        }

    return _acheminer(
        fabrique,
        classe="plongement",
        operation="embeddings",
        charge=list(textes),
        sortie_max=0,
        executer=executer,
        escalade=None,
        ouvrir=ouvrir,
        delai_s=delai_s,
        dans_transaction=dans_transaction,
    )


def reclasser(
    fabrique: acces.FabriqueConnexion,
    *,
    requete: str,
    passages: Sequence[str],
    ouvrir=None,
    delai_s: float = 8.0,
    dans_transaction: bool = False,
) -> dict[str, Any]:
    if (
        not isinstance(requete, str)
        or not isinstance(passages, Sequence)
        or isinstance(passages, str)
        or not (1 <= len(passages) <= 128)
        or not all(isinstance(p, str) for p in passages)
    ):
        raise ModelesErreur(codes.DECLARATION_INVALIDE, "requete et 1 à 128 passages (chaînes) attendus", 422)

    def executer(client: ClientOpenAI, modele: str):
        reponse = client.rerank(modele, requete, passages)
        return {"notes": reponse["notes"], "latence_ms": reponse["latence_ms"]}, {
            "entree": reponse["usage"]["entree"],
            "sortie": 0,
        }

    return _acheminer(
        fabrique,
        classe="reclassement",
        operation="rerank",
        charge=[requete, *passages],
        sortie_max=0,
        executer=executer,
        escalade=None,
        ouvrir=ouvrir,
        delai_s=delai_s,
        dans_transaction=dans_transaction,
    )


# -- test de connexion d'un rôle ---------------------------------------------------------------------------------
def tester_role(
    fabrique: acces.FabriqueConnexion,
    *,
    acteur: str,
    role: str,
    ouvrir=None,
    delai_s: float = 8.0,
    interdire_raisonnement: bool = False,
    verifier_admin: bool = True,
    dans_transaction: bool = False,
    delai_min_s: int = 0,
) -> dict[str, Any]:
    """UN appel minuscule au fournisseur PRINCIPAL du rôle (≤ 8 jetons de sortie ; un texte pour les embeddings),
    jamais de repli. Le résultat (statut, latence, dimension mesurée) est conservé sur le rôle et jamais un secret."""
    role = lex.verifier_role(role)
    if interdire_raisonnement and role == lex.ROLE_RAISONNEMENT:
        raise ModelesErreur(
            codes.ESCALADE_REFUSEE, "le test du rôle de raisonnement est réservé à la console du propriétaire", 403
        )
    with fabrique() as cnx:
        if verifier_admin:
            service.exiger_admin(cnx, acteur)
        ligne = service.ligne_role(cnx, role)
        if ligne is None:
            raise ModelesErreur(codes.ROLE_NON_CONFIGURE, f"le rôle {role} n'est pas configuré", 409)
        dernier = (ligne["mesures"] or {}).get("date")
        if (
            delai_min_s
            and dernier
            and (dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(dernier)).total_seconds() < delai_min_s
        ):
            raise ModelesErreur(
                codes.APPEL_REFUSE,
                f"un test du rôle a eu lieu il y a moins de {delai_min_s} s : attendre (économie de jetons)",
                429,
            )
        if role == lex.ROLE_RAISONNEMENT and not service.raisonnement_actif(cnx):
            raise ModelesErreur(codes.RAISONNEMENT_INACTIF, "activer le raisonnement (N3) avant de le tester", 403)
        cible = _charger_cibles(cnx, role, ligne)[0]
    mesure: dict[str, Any]
    if cible["raison"] is not None:
        mesure = {"statut": "refuse_politique", "detail": "aucun appel : " + cible["raison"], "latence_ms": None}
    elif role not in OPERATION_DU_ROLE:
        mesure = _tester_presence(fabrique, cible, ouvrir, delai_s)
    else:
        mesure = _tester_appel(fabrique, role, cible, ouvrir, delai_s, dans_transaction)
    mesure = masquage.masquer({**mesure, "date": service.instant()})
    with fabrique() as cnx:
        if verifier_admin:
            service.exiger_admin(cnx, acteur)
        service.enregistrer_mesure(cnx, role, mesure)
        etat.journaliser(cnx, acteur, "modeles.tester", f"role:{role}", {"statut": mesure["statut"]})
    return mesure


def _tester_appel(
    fabrique, role: str, cible: dict[str, Any], ouvrir, delai_s: float, dans_transaction: bool
) -> dict[str, Any]:
    modele = cible["modele"]
    try:
        with acces.client_du_fournisseur(
            fabrique, cible["fournisseur"], ouvrir=ouvrir, delai_s=delai_s, dans_transaction=dans_transaction
        ) as client:
            if role == "embeddings":
                r = client.embeddings(modele, ["bonjour"])
                dimension = len(r["vecteurs"][0])
                usage = {"entree": r["usage"]["entree"] or 2, "sortie": 0}
                mesure = {
                    "statut": "succes",
                    "latence_ms": r["latence_ms"],
                    "dimension": dimension,
                    "detail": f"{dimension} dimensions",
                }
            elif role == "reranker":
                r = client.rerank(modele, "bonjour", ["bonjour", "table"])
                usage = {"entree": r["usage"]["entree"] or 4, "sortie": 0}
                mesure = {"statut": "succes", "latence_ms": r["latence_ms"], "detail": "2 notes"}
            else:
                contenu: Any = "Réponds par le seul mot : OK"
                if role == "vl":
                    contenu = [
                        {"type": "text", "text": "Réponds par le seul mot : OK"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG_1X1}"}},
                    ]
                r = client.chat(modele, [{"role": "user", "content": contenu}], JETONS_TEST_MAX // 2)
                usage = {"entree": r["usage"]["entree"] or 16, "sortie": r["usage"]["sortie"] or JETONS_TEST_MAX // 2}
                mesure = {
                    "statut": "succes",
                    "latence_ms": r["latence_ms"],
                    "detail": f"réponse de {len(r['contenu'])} caractères",
                }
    except ErreurAppel as exc:
        return {"statut": "echec", "detail": f"{exc.code} : {exc.detail}"[:200], "latence_ms": None}
    except ModelesErreur as exc:
        return {"statut": "echec", "detail": f"{exc.code} : {exc.detail}"[:200], "latence_ms": None}
    with fabrique() as cnx:
        service.ajouter_usage(
            cnx, role, entree=int(usage["entree"]), sortie=int(usage["sortie"]), cout_micro_usd=0, repli=False
        )
    return mesure


def _tester_presence(fabrique, cible: dict[str, Any], ouvrir, delai_s: float) -> dict[str, Any]:
    """OCR, voix, image : pas d'appel générique ; on vérifie seulement la présence de l'alias au catalogue."""
    if not (cible["fournisseur"].point_acces or "").startswith("passerelle:"):
        return {
            "statut": "non_verifiable",
            "detail": "pas d'appel générique pour ce rôle : voir le moteur dédié",
            "latence_ms": None,
        }
    try:
        with acces.client_passerelle(fabrique, ouvrir=ouvrir, delai_s=delai_s) as (client, _):
            noms, latence = client.modeles()
    except (ErreurAppel, ModelesErreur) as exc:
        return {"statut": "echec", "detail": f"{exc.code} : {exc.detail}"[:200], "latence_ms": None}
    present = cible["modele"] in noms
    return {
        "statut": "succes" if present else "echec",
        "latence_ms": latence,
        "detail": "alias présent au catalogue" if present else "alias absent du catalogue de la passerelle",
    }
