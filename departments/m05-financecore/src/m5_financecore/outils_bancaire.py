"""Outils M5 du RAPPROCHEMENT BANCAIRE (M5.1, M5.3) : un relevé CSV ou OFX déposé par un humain, rapproché des lignes du
compte Banque du grand livre par des règles explicables (`rapprochement_bancaire.py`), jusqu'à un état de rapprochement
PRÉPARÉ, rejouable, que seule une PERSONNE confirme (N4).

Aucun réseau, aucune API bancaire (ni Plaid, ni Stripe, ni QuickBooks en ligne : non fournis) : le relevé est un fichier
déposé dans `<OPSYS_HOME>/imports/releves/` et lu par son NOM. Ce module ne nomme jamais le registre des mouvements ;
payer ou encaisser est hors d'OPSYS. Portée d'appareil FERMÉE.

Rejeu. Chaque rapprochement enregistre les têtes des registres qu'il a lus (grand livre, factures clientes, comptes à
payer, opérations) et les paramètres de lecture du fichier ; les registres étant en ajout seulement, `lire` avec
`rejouer` recalcule le rapprochement sur LE PRÉFIXE de chaque registre arrêté à ces têtes et compare le reçu.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from opsys.outils import Autonomie, Niveau, Outil

from . import (
    comptes_a_payer,
    facturation,
    grand_livre,
    operations_registre,
    rapprochement_bancaire,
    recu_calcul,
    releve_bancaire,
    verdicts_operations,
)
from . import outils as _o
from .outils_operations import (
    _HORODATAGE,
    _recu_ecriture,
    accepte,
    contexte_operations,
    humain_requis,
    lire_fichier_confine,
    refuse,
)

__all__ = ["outils_bancaire"]

_OCTETS_RELEVE_MAX = releve_bancaire.OCTETS_MAX
_LIGNES_VUE = 6
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_operations.construire_verdict(code, detail=detail)


class _Lecture:
    """Un préfixe de registre, en lecture seule (`lire`) : assez pour les fonctions pures qui relisent un registre."""

    def __init__(self, maillons: Sequence[Mapping[str, Any]]) -> None:
        self._maillons = list(maillons)

    def lire(self) -> list[Mapping[str, Any]]:
        return list(self._maillons)


def _prefixe(maillons: Sequence[Mapping[str, Any]], tete: str | None) -> list[Mapping[str, Any]] | None:
    """Les maillons jusqu'à la tête `tete` incluse (`[]` pour une tête nulle) ; `None` si cette tête n'est pas dans la
    chaîne (elle a été réécrite : le rejeu ne peut pas se faire)."""
    if tete is None:
        return []
    for index, maillon in enumerate(maillons):
        if maillon["ligne_id"] == tete:
            return list(maillons[: index + 1])
    return None


def _livre_banque(
    etat_gl: Mapping[str, Any], plan: Mapping[str, Any], fin: str
) -> tuple[list[dict[str, Any]], Decimal]:
    """Les lignes du compte Banque du livre (brouillons ET définitives, chacune avec son statut) datées au plus tard
    `fin`, et le solde du compte à cette date (débit moins crédit)."""
    compte = plan["roles"]["banque"]
    lignes: list[dict[str, Any]] = []
    solde = Decimal("0.00")
    for ident in etat_gl["ordre"]:
        e = etat_gl["ecritures"][ident]
        if e["date_effet"] > fin:
            continue
        for index, ligne in enumerate(e["lignes"]):
            if ligne["compte"] != compte:
                continue
            montant = ligne["debit"] - ligne["credit"]
            solde += montant
            lignes.append(
                {
                    "cle": f"{ident}:{index}",
                    "ecriture_id": ident,
                    "date": e["date_effet"],
                    "montant": montant,
                    "libelle": e["libelle"],
                    "piece": f"{e['piece']['type']}:{e['piece']['reference']}",
                    "statut": e["statut"],
                }
            )
    return lignes, solde


def _configuration_rapprochement() -> dict[str, Any]:
    brut = _o._configuration_manifeste().get("operations")
    config = brut.get("rapprochement") if isinstance(brut, dict) else None
    return config if isinstance(config, dict) else {}


def _ouverts(registre_factures: Any, registre_ap: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    clients = [
        {"facture_id": f["facture_id"], "montant": str(f["montant_apres_taxes"])}
        for f in facturation.factures_par_statut(registre_factures, "ENVOYEE")
    ]
    fournisseurs = [
        {"facture_fournisseur_id": f["facture_fournisseur_id"], "montant": str(f["montant_apres_taxes"])}
        for f in comptes_a_payer.factures_saisies(registre_ap)
    ]
    return clients, fournisseurs


def _cles_deja_rapprochees(etat_ops: Mapping[str, Any], avant_le: str) -> list[str]:
    """Les lignes du livre déjà constatées par un relevé ANTÉRIEUR (dont la dernière date précède `avant_le`) :
    elles ne sont plus « en circulation ». Un relevé de la même période, ou postérieur, n'en retire rien : relancer
    le même relevé redonne
    le même rapprochement."""
    cles: set[str] = set()
    for r in etat_ops["par_type"]["op_rapprochement_prepare"].values():
        if r["periode_fin"] < avant_le:
            cles.update(r["cles_livre_rapprochees"])
    return sorted(cles)


def _lire_releve(octets: bytes, nom: str, lecture: Mapping[str, Any]) -> tuple[dict | None, dict | None]:
    return releve_bancaire.lire_releve(
        octets,
        nom=nom,
        mapping=lecture.get("mapping"),
        separateur=lecture.get("separateur"),
        format_dates=lecture.get("format_dates", "auto"),
        convention_signe=lecture.get("convention_signe", "depot_positif"),
        solde_fin_declare=lecture.get("solde_fin_declare"),
    )


def _vue_etat(etat: Mapping[str, Any]) -> dict[str, Any]:
    """L'état de rapprochement tel qu'une réponse le montre : totaux complets, listes tronquées à quelques lignes."""

    def court(bloc: Mapping[str, Any]) -> dict[str, Any]:
        lignes = bloc["lignes"]
        return {
            **{k: v for k, v in bloc.items() if k not in ("lignes", "reste")},
            "lignes": lignes[:_LIGNES_VUE],
            "lignes_non_montrees": max(0, len(lignes) - _LIGNES_VUE) + bloc.get("reste", 0),
        }

    return {
        "periode": etat["periode"],
        "compte": etat["compte_masque"],
        "releve": etat["releve"],
        "etat": etat["etat"],
        "explication": etat["explication_etat"],
        "solde_releve": etat["solde_releve"],
        "solde_livre": etat["solde_livre"],
        "depots_en_transit": court(etat["depots_en_transit"]),
        "cheques_en_circulation": court(etat["cheques_en_circulation"]),
        "non_comptabilise_a_la_banque": court(etat["non_comptabilise_a_la_banque"]),
        "frais_suggeres": {
            "nombre": etat["frais_suggeres"]["nombre"],
            "net": etat["frais_suggeres"]["net"],
            "lignes": etat["frais_suggeres"]["lignes"][:_LIGNES_VUE],
        },
        "releve_ajuste": etat["releve_ajuste"],
        "livre_ajuste": etat["livre_ajuste"],
        "ecart": etat["ecart"],
        "appariements": etat["appariements"],
        "ambigus": etat["ambigus"][:3],
        "parametres": etat["parametres"],
    }


def preparer_rapprochement_bancaire(
    fichier: str,
    fenetre_jours: int,
    anciennete_max_jours: int,
    horodatage: str,
    solde_fin_declare: str | None = None,
    format_dates: str = "auto",
    convention_signe: str = "depot_positif",
    separateur: str | None = None,
    mapping: dict[str, str] | None = None,
    proposer_brouillons_frais: bool = False,
) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    octets, refus = lire_fichier_confine("releves", fichier, _OCTETS_RELEVE_MAX, "fichier")
    if refus is not None:
        return refuse(refus)
    lecture = {
        "mapping": mapping,
        "separateur": separateur,
        "format_dates": format_dates,
        "convention_signe": convention_signe,
        "solde_fin_declare": solde_fin_declare,
    }
    releve, refus = _lire_releve(octets, fichier, lecture)
    if refus is not None:
        return refuse(refus)
    config = _configuration_rapprochement()
    livre, solde_livre = _livre_banque(ctx["etat_gl"], ctx["plan"], releve["date_fin"])
    registre_factures, registre_ap = _o._registre_factures(None), _o._registre_comptes_a_payer()
    maillons_ops = ctx["ops"].lire()
    tetes = {
        "grand_livre": ctx["gl"].tete(),
        "factures": registre_factures.tete(),
        "comptes_a_payer": registre_ap.tete(),
        "operations": maillons_ops[-1]["ligne_id"] if maillons_ops else None,
    }  # AVANT tout brouillon de frais
    clients, fournisseurs = _ouverts(registre_factures, registre_ap)
    resultat, refus = rapprochement_bancaire.rapprocher(
        releve,
        livre,
        solde_livre=solde_livre,
        fenetre_jours=fenetre_jours,
        anciennete_max_jours=anciennete_max_jours,
        motifs_frais=config.get("motifs_frais", []),
        compte_frais=config.get("compte_frais_bancaires"),
        ouverts_clients=clients,
        ouverts_fournisseurs=fournisseurs,
        cles_deja_rapprochees=_cles_deja_rapprochees(ctx["etat_ops"], releve["date_debut"]),
    )
    if refus is not None:
        return refuse(refus)
    etat, recu = resultat["etat"], resultat["recu"]
    brouillons_frais: list[str] = []
    if proposer_brouillons_frais:
        roles = ctx["plan"]["roles"]
        for ligne in etat["frais_suggeres"]["lignes"]:
            montant = format(-Decimal(ligne["montant"]), "f")
            propose, refus = grand_livre.proposer_ecriture(
                ctx["gl"],
                ctx["plan"],
                cle_piece=f"auto:releve_bancaire:{releve['sha256'][:16]}:{ligne['ligne']}",
                piece={"type": "releve_bancaire", "reference": f"{releve['sha256'][:16]}:{ligne['ligne']}"},
                nature="frais_bancaires",
                date_effet=ligne["date"],
                libelle=f"Frais bancaires (relevé {fichier}, ligne {ligne['ligne']})"[:200],
                lignes_brutes=[
                    {"compte": ligne["compte_charge"], "debit": montant, "credit": None},
                    {"compte": roles["banque"], "debit": None, "credit": montant},
                ],
                horodatage=horodatage,
                origine="rapprochement_bancaire",
            )
            if refus is not None:
                return refuse(refus)
            brouillons_frais.append(propose["ecriture"]["ecriture_id"])
    corps = {
        "periode_debut": etat["periode"]["debut"],
        "periode_fin": etat["periode"]["fin"],
        "etat": etat["etat"],
        "ecart": etat["ecart"],
        "solde_releve": etat["solde_releve"],
        "solde_livre": etat["solde_livre"],
        "releve": etat["releve"],
        "depots_en_transit": etat["depots_en_transit"]["total"],
        "cheques_en_circulation": etat["cheques_en_circulation"]["total"],
        "non_comptabilise": etat["non_comptabilise_a_la_banque"]["net"],
        "appariements": etat["appariements"]["nombre"],
        "recu_empreinte": recu["empreinte"],
        "recu": recu,
        "cles_livre_rapprochees": etat["cles_livre_rapprochees"],
        "lecture": lecture,
        "parametres": etat["parametres"],
        "tetes": tetes,
        "brouillons_frais": brouillons_frais,
    }
    enregistre, refus = operations_registre.ajouter_operation(
        ctx["ops"],
        ctx["etat_ops"],
        "op_rapprochement_prepare",
        f"rapprochement:{releve['sha256']}:{recu['empreinte_entrees']}",
        corps,
        horodatage,
        hors_identite=("tetes", "brouillons_frais"),
    )
    if refus is not None:
        return refuse(refus)
    operation = enregistre["operation"]
    return accepte(
        {
            "rapprochement_id": operation["rapprochement_id"],
            "statut": "deja_prepare" if enregistre["statut"] == "deja" else "prepare",
            "etat_de_rapprochement": _vue_etat(etat),
            "appariements_apercu": [
                {k: a[k] for k in ("ligne_banque", "regle", "confiance", "montant", "explication")}
                for a in resultat["appariements"][:_LIGNES_VUE]
            ],
            "brouillons_frais_proposes": len(brouillons_frais),
            "recu": {
                "empreinte": recu["empreinte"],
                "empreinte_entrees": recu["empreinte_entrees"],
                "moteur": recu["moteur"],
                **_recu_ecriture(ctx["ops"]),
            },
            "avertissements": recu["avertissements"],
            "a_faire": "relire l'état, expliquer chaque écart, puis le faire CONFIRMER par une personne "
            "(m5_confirmer_rapprochement_bancaire, N4) ; rien n'est comptabilisé par ce rapprochement",
        }
    )


def _rejouer(ctx: Mapping[str, Any], maillon: Mapping[str, Any]) -> tuple[dict | None, dict | None]:
    """Recalcule un rapprochement sur le préfixe des registres arrêté à ses têtes ; compare les reçus."""
    tetes = maillon["tetes"]
    prefixes = {
        "gl": _prefixe(ctx["gl"].lire(), tetes["grand_livre"]),
        "factures": _prefixe(_o._registre_factures(None).lire(), tetes["factures"]),
        "ap": _prefixe(_o._registre_comptes_a_payer().lire(), tetes["comptes_a_payer"]),
        "ops": _prefixe(ctx["ops"].lire(), tetes["operations"]),
    }
    if any(p is None for p in prefixes.values()):
        return None, _verdict(
            "REJ-BANQUE-REJEU-DIVERGENT", "une tête de registre enregistrée n'est plus dans sa chaîne"
        )
    octets, refus = lire_fichier_confine("releves", maillon["releve"]["nom"], _OCTETS_RELEVE_MAX, "fichier")
    if refus is not None:
        return None, refus
    releve, refus = _lire_releve(octets, maillon["releve"]["nom"], maillon["lecture"])
    if refus is not None:
        return None, refus
    if releve["sha256"] != maillon["releve"]["sha256"]:
        return None, _verdict("REJ-BANQUE-REJEU-DIVERGENT", "le fichier déposé n'est plus celui de ce rapprochement")
    etat_gl = grand_livre.etat_grand_livre(prefixes["gl"])
    livre, solde_livre = _livre_banque(etat_gl, ctx["plan"], releve["date_fin"])
    clients, fournisseurs = _ouverts(_Lecture(prefixes["factures"]), _Lecture(prefixes["ap"]))
    etat_ops = operations_registre.etat_operations(prefixes["ops"])
    parametres = maillon["parametres"]
    resultat, refus = rapprochement_bancaire.rapprocher(
        releve,
        livre,
        solde_livre=solde_livre,
        fenetre_jours=parametres["fenetre_jours"],
        anciennete_max_jours=parametres["anciennete_max_jours"],
        motifs_frais=parametres["motifs_frais"],
        compte_frais=parametres["compte_frais"],
        ouverts_clients=clients,
        ouverts_fournisseurs=fournisseurs,
        cles_deja_rapprochees=_cles_deja_rapprochees(etat_ops, releve["date_debut"]),
    )
    return (resultat, refus)


def lire_rapprochement_bancaire(
    rapprochement_id: str | None = None, rejouer: bool = False, depart: int = 0, limite: int = 8
) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    prepares = ctx["etat_ops"]["par_type"]["op_rapprochement_prepare"]
    confirmes = {c["rapprochement_vise"]: c for c in ctx["etat_ops"]["par_type"]["op_rapprochement_confirme"].values()}
    if type(limite) is not int or not 1 <= limite <= 15 or type(depart) is not int or depart < 0:
        return refuse(_verdict("REJ-OPS-LIMITE-INVALIDE", "limite de 1 à 15, depart entier positif ou nul"))

    def resume(m: Mapping[str, Any]) -> dict[str, Any]:
        c = confirmes.get(m["rapprochement_id"])
        return {
            "rapprochement_id": m["rapprochement_id"],
            "periode": [m["periode_debut"], m["periode_fin"]],
            "etat": m["etat"],
            "ecart": m["ecart"],
            "fichier": m["releve"]["nom"],
            "appariements": m["appariements"],
            "confirme_par": None if c is None else c["par"],
            "recu_empreinte": m["recu_empreinte"],
        }

    if rapprochement_id is None:
        tous = [prepares[i] for i in ctx["etat_ops"]["ordre"]["op_rapprochement_prepare"]]
        page = tous[depart : depart + limite]
        return accepte(
            {
                "rapprochements": [resume(m) for m in page],
                "total": len(tous),
                "prochain_depart": depart + limite if depart + limite < len(tous) else None,
            }
        )
    maillon = prepares.get(rapprochement_id)
    if maillon is None:
        return refuse(_verdict("REJ-BANQUE-RAPPROCHEMENT-INTROUVABLE", f"rapprochement {rapprochement_id!r} inconnu"))
    sortie: dict[str, Any] = {
        **resume(maillon),
        "solde_releve": maillon["solde_releve"],
        "solde_livre": maillon["solde_livre"],
        "depots_en_transit": maillon["depots_en_transit"],
        "cheques_en_circulation": maillon["cheques_en_circulation"],
        "non_comptabilise": maillon["non_comptabilise"],
        "brouillons_frais": maillon["brouillons_frais"],
        "parametres": maillon["parametres"],
    }
    if rejouer:
        resultat, refus = _rejouer(ctx, maillon)
        if refus is not None:
            return refuse(refus)
        identique = resultat["recu"]["empreinte"] == maillon["recu_empreinte"]
        if not identique:
            return refuse(
                _verdict(
                    "REJ-BANQUE-REJEU-DIVERGENT",
                    "le rejeu ne redonne pas le reçu enregistré : "
                    f"{resultat['recu']['empreinte'][:16]} ≠ {maillon['recu_empreinte'][:16]}",
                )
            )
        sortie["rejeu"] = {
            "identique": True,
            "recu_verifie": recu_calcul.verifier(resultat["recu"])[0],
            "empreinte": resultat["recu"]["empreinte"],
            "detail": _vue_etat(resultat["etat"]),
        }
    return accepte(sortie)


def confirmer_rapprochement_bancaire(
    rapprochement_id: str, recu_empreinte: str, motif_ecart: str | None, horodatage: str
) -> dict[str, Any]:
    ctx, refus = contexte_operations()
    if refus is not None:
        return refuse(refus)
    humain, refus = humain_requis("m5_confirmer_rapprochement_bancaire", "confirmer un rapprochement bancaire")
    if refus is not None:
        return refuse(refus)
    maillon = ctx["etat_ops"]["par_type"]["op_rapprochement_prepare"].get(rapprochement_id)
    if maillon is None:
        return refuse(_verdict("REJ-BANQUE-RAPPROCHEMENT-INTROUVABLE", f"rapprochement {rapprochement_id!r} inconnu"))
    if (
        not isinstance(recu_empreinte, str)
        or not _SHA.match(recu_empreinte)
        or recu_empreinte != maillon["recu_empreinte"]
    ):
        return refuse(
            _verdict(
                "REJ-BANQUE-REJEU-DIVERGENT",
                "recu_empreinte ne correspond pas au reçu de ce rapprochement : relire l'état avant de confirmer",
            )
        )
    if any(
        c["rapprochement_vise"] == rapprochement_id
        for c in ctx["etat_ops"]["par_type"]["op_rapprochement_confirme"].values()
    ):
        return refuse(_verdict("REJ-BANQUE-DEJA-CONFIRME", "ce rapprochement est déjà confirmé"))
    motif = motif_ecart.strip() if isinstance(motif_ecart, str) else None
    if maillon["etat"] != "EQUILIBRE" and (motif is None or len(motif) < 10 or "\n" in motif or len(motif) > 300):
        return refuse(
            _verdict(
                "REJ-BANQUE-ECART-NON-NUL",
                f"l'état est « {maillon['etat']} » (écart {maillon['ecart']}) : un motif d'une ligne "
                "(10 à 300 caractères) est exigé pour confirmer",
            )
        )
    corps = {
        "rapprochement_vise": rapprochement_id,
        "par": humain["par"],
        "role": humain["role"],
        "voie": humain["voie"],
        "etat_confirme": maillon["etat"],
        "ecart": maillon["ecart"],
        "motif_ecart": motif,
    }
    enregistre, refus = operations_registre.ajouter_operation(
        ctx["ops"], ctx["etat_ops"], "op_rapprochement_confirme", f"confirme:{rapprochement_id}", corps, horodatage
    )
    if refus is not None:
        return refuse(refus)
    return accepte(
        {
            "confirmation_id": enregistre["operation"]["confirmation_id"],
            "rapprochement_id": rapprochement_id,
            "confirme_par": humain["par"],
            "etat": maillon["etat"],
            "ecart": maillon["ecart"],
            "motif_ecart": motif,
            "recu": _recu_ecriture(ctx["ops"]),
            "nature": "relu et confirmé par une personne ; ne comptabilise rien et ne clôt aucune période",
        }
    )


def outils_bancaire() -> tuple[Outil, ...]:
    mention = " Sortie comptable : porte la mention « À valider auprès d'un comptable (CPA) / professionnel qualifié »."
    objet = {"type": "object", "additionalProperties": False}
    return (
        Outil(
            nom="m5_preparer_rapprochement_bancaire",
            description=(
                "Rapproche un relevé bancaire CSV ou OFX (déposé par un humain dans imports/releves/, lu par son "
                "NOM) des "
                "lignes du compte Banque du grand livre, par cinq règles EXPLICABLES (montant+date+référence ; montant+"
                "référence ; montant+date proche ; somme de lignes ; élément antérieur en circulation) : état de "
                "rapprochement "
                "(dépôts en transit, chèques en circulation, opérations de la banque non comptabilisées avec "
                "pistes vers "
                "les factures ouvertes, écart résiduel) et reçu rejouable. Montant ou date ambigus, solde "
                "incohérent, colonne "
                "introuvable : refus nommé, jamais deviné. Les frais bancaires ne sont classés que si le "
                "propriétaire a "
                "déclaré leurs motifs et leur compte. PRÉPARÉ seulement : il devient fiable après confirmation "
                "d'une personne "
                "(N4). Aucun réseau." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "fichier": {"type": "string", "description": "NOM du fichier déposé dans imports/releves/."},
                    "fenetre_jours": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": rapprochement_bancaire.FENETRE_MAX,
                        "description": "Écart de dates toléré entre la banque et le livre (jamais deviné).",
                    },
                    "anciennete_max_jours": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 365,
                        "description": "Ancienneté maximale d'un élément en circulation.",
                    },
                    "horodatage": _HORODATAGE,
                    "solde_fin_declare": {
                        "type": ["string", "null"],
                        "description": "Solde de fin lu sur le relevé papier.",
                    },
                    "format_dates": {"type": "string", "enum": ["auto", "AAAA-MM-JJ", "JJ/MM/AAAA", "MM/JJ/AAAA"]},
                    "convention_signe": {"type": "string", "enum": ["depot_positif", "retrait_positif"]},
                    "separateur": {"type": ["string", "null"], "enum": [",", ";", "\t", None]},
                    "mapping": {
                        "type": ["object", "null"],
                        "description": "{date, montant | debit+credit, description, "
                        "reference, solde} → noms de colonnes.",
                    },
                    "proposer_brouillons_frais": {
                        "type": "boolean",
                        "description": "Proposer en BROUILLON les écritures des frais bancaires reconnus.",
                    },
                },
                "required": ["fichier", "fenetre_jours", "anciennete_max_jours", "horodatage"],
            },
            fonction=preparer_rapprochement_bancaire,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m5_lire_rapprochement_bancaire",
            description=(
                "Liste les rapprochements bancaires préparés (état, écart, confirmation) ou en lit un ; avec "
                "rejouer=vrai, "
                "recalcule le rapprochement sur les registres tels qu'ils étaient (têtes enregistrées) et compare "
                "le reçu : "
                "REJ-BANQUE-REJEU-DIVERGENT si le fichier ou un registre a changé. Lecture pure." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "rapprochement_id": {"type": ["string", "null"]},
                    "rejouer": {"type": "boolean"},
                    "depart": {"type": "integer", "minimum": 0},
                    "limite": {"type": "integer", "minimum": 1, "maximum": 15},
                },
                "required": [],
            },
            fonction=lire_rapprochement_bancaire,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_confirmer_rapprochement_bancaire",
            description=(
                "CONFIRME un rapprochement bancaire préparé (N4) : une personne a relu l'état et son reçu "
                "(recu_empreinte). L'appel attend dans la file du propriétaire ou de la finance ; un agent seul "
                "est refusé "
                "(REJ-OPS-HUMAIN-REQUIS). Un état avec écart exige un motif d'une ligne. Ne comptabilise rien, ne clôt "
                "aucune période." + mention
            ),
            parametres={
                **objet,
                "properties": {
                    "rapprochement_id": {"type": "string"},
                    "recu_empreinte": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "motif_ecart": {"type": ["string", "null"], "description": "Exigé si l'état n'est pas EQUILIBRE."},
                    "horodatage": _HORODATAGE,
                },
                "required": ["rapprochement_id", "recu_empreinte", "motif_ecart", "horodatage"],
            },
            fonction=confirmer_rapprochement_bancaire,
            autonomie=Autonomie.T2,
            niveau=Niveau.N4,
        ),
    )
