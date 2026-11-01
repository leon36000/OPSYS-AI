"""Service de l'ingestion d'onboarding : dépôt -> tâches -> brouillons, sans jamais écrire une donnée définitive.

Parcours (docs/architecture/INGESTION-ONBOARDING.md) :

1. `deposer` : lit le fichier déposé par NOM (`depot`), le déplie (archive ZIP gardée), dédoublonne EXACTEMENT par
   SHA-256 (une copie déjà connue, dans ce lot ou un autre, devient un document `DOUBLON` qui pointe vers l'original,
   sans contenu), chiffre chaque original et planifie ses sept tâches. Idempotent par (acteur, clé de mutation) : la
   même clé et le même fichier rejouent le lot ; la même clé et un autre fichier sont refusés.
2. `avancer` : exécute les tâches du lot une à une, chacune en trois temps — réserver (bail) dans une transaction,
   travailler HORS transaction (extraction isolée, fournisseur), puis écrire le résultat et ses effets par CAS dans une
   seconde transaction. Un arrêt à n'importe quel moment laisse soit la tâche en bail (reprise à l'échéance), soit rien
   (transaction annulée) : jamais un brouillon en double.
3. Les BROUILLONS (comptes à payer M5, fiches clients M2) attendent un humain : `decider_brouillon` est appelé par les
   outils de validation de M5 et de M2, dans la transaction même où ils écrivent la donnée définitive.

Aucune donnée financière définitive n'est écrite ici : ni facture fournisseur, ni écriture de grand livre, ni client.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, select, update

from .. import etat
from ..stockage.schema import INGESTION_BROUILLONS, INGESTION_DOCUMENTS, INGESTION_JOURNAL
from . import classement, depot, extraction_texte, port_extraction, scellement
from .codes import EchecEtape, IngestionErreur
from .taches import ETAPES, QUOTAS, RANG, TachesSQLite, instant_texte, nouvel_identifiant

FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]
Horloge = Callable[[], int]
_MUTATION = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_IDENTIFIANT = re.compile(r"[0-9a-f]{32}")
_PAGE_MAX = 50
CLE_PROFIL_IDENTITE = "identite_fiscale"


def _horloge() -> int:
    return int(time.time())


def _sha(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


def _acteur(acteur: Any) -> str:
    if not isinstance(acteur, str) or not acteur.strip() or len(acteur) > 200 or not acteur.isprintable():
        raise IngestionErreur("REJ-ING-ACTEUR-INVALIDE", "acteur : identifiant imprimable de 200 caractères au plus",
                              422)
    return acteur


def _identifiant(valeur: Any, nom: str) -> str:
    if not isinstance(valeur, str) or _IDENTIFIANT.fullmatch(valeur) is None:
        raise IngestionErreur("REJ-ING-ARGUMENT-INVALIDE", f"{nom} : identifiant de 32 caractères hexadécimaux", 422)
    return valeur


# ============================================================================================== vues
def _vue_lot(port: TachesSQLite, lot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lot_id": lot["lot_id"], "nom_source": lot["nom_source"], "source_sha256": lot["source_sha256"],
        "type_source": lot["type_source"], "statut": lot["statut"], "nb_documents": lot["nb_documents"],
        "octets": lot["octets"], "acteur": lot["acteur"], "cree_le": lot["cree_le"], "modifie_le": lot["modifie_le"],
        "compteurs": port.compter(lot["lot_id"]),
    }


def _vue_document(ligne: Mapping[str, Any]) -> dict[str, Any]:
    return {cle: ligne[cle] for cle in ("document_id", "rang", "nom", "type_detecte", "classe", "statut", "code",
                                        "doublon_de")}


def _vue_brouillon(ligne: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "brouillon_id": ligne["brouillon_id"], "lot_id": ligne["lot_id"], "document_id": ligne["document_id"],
        "genre": ligne["genre"], "statut": ligne["statut"], "raisons": json.loads(ligne["raisons"]),
        "revision": ligne["revision"], "reference_definitive": ligne["reference_definitive"],
        "decision": json.loads(ligne["decision"]) if ligne["decision"] else None,
    }


# ============================================================================================== dépôt
def deposer(cnx: Connection, acteur: str, *, nom: str, mutation_id: str, horloge: Horloge | None = None,
            dossier: Any = None) -> dict[str, Any]:
    """Crée (ou rejoue) le lot d'un fichier déposé. Refus typés (`IngestionErreur`) avant toute écriture."""
    acteur = _acteur(acteur)
    if not isinstance(mutation_id, str) or _MUTATION.fullmatch(mutation_id) is None:
        raise IngestionErreur("REJ-ING-MUTATION-INVALIDE", "mutation_id : 1 à 64 caractères [A-Za-z0-9_.:-]", 422)
    octets = depot.lire_depose(nom, dossier=dossier)
    source_sha = _sha(octets)
    port = TachesSQLite(cnx, maintenant=horloge or _horloge)
    existant = port.lot_par_mutation(acteur, mutation_id)
    if existant is not None:
        if existant["source_sha256"] != source_sha or existant["nom_source"] != nom:
            raise IngestionErreur("REJ-ING-MUTATION-CONFLIT", "cette clé de mutation a déjà servi pour un autre "
                                  "fichier : utiliser une nouvelle clé")
        return {**_vue_lot(port, existant), "rejeu": True}
    if port.lots_en_cours() >= QUOTAS["lots_en_cours"]:
        raise IngestionErreur("REJ-ING-QUOTA-LOTS", f"{QUOTAS['lots_en_cours']} lots déjà en cours : les avancer "
                              "jusqu'au bout avant d'en déposer un autre", 429)
    membres, resume = depot.deplier(nom, octets)
    if not membres:
        raise IngestionErreur("REJ-ING-LOT-VIDE", "aucun document dans le dépôt", 422)
    if len(membres) > QUOTAS["documents_par_lot"]:
        raise IngestionErreur("REJ-ING-QUOTA-DOCUMENTS", f"plus de {QUOTAS['documents_par_lot']} documents dans le "
                              "lot", 413)
    acceptes = [m for m in membres if m.refus is None]
    octets_lot = sum(m.taille for m in acceptes)
    if octets_lot > QUOTAS["octets_par_lot"]:
        raise IngestionErreur("REJ-ING-QUOTA-OCTETS", f"plus de {QUOTAS['octets_par_lot']} octets de documents dans "
                              "le lot", 413)
    nombre_total, octets_total = port.totaux_stockes()
    if nombre_total + len(acceptes) > QUOTAS["documents_total"] or octets_total + octets_lot > QUOTAS["octets_total"]:
        raise IngestionErreur("REJ-ING-QUOTA-OCTETS", "quota total de l'ingestion atteint (documents ou octets "
                              "conservés)", 507)
    reference = scellement.reference_cle()
    quand = instant_texte()
    lot_id = nouvel_identifiant()
    port.creer_lot({
        "lot_id": lot_id, "acteur": acteur, "mutation_id": mutation_id, "nom_source": nom,
        "source_sha256": source_sha, "type_source": "zip" if resume["type_source"] == "zip" else "fichier",
        "statut": "EN_COURS", "nb_documents": len(membres), "octets": octets_lot, "cle_reference": reference,
        "version_format": scellement.VERSION_FORMAT, "cree_le": quand, "modifie_le": quand,
    })
    port.journaliser(lot_id, acteur, "lot.depose", details={"documents": len(membres), "acceptes": len(acceptes),
                                                             "ignores": resume["ignores"]})
    vus_dans_le_lot: dict[str, str] = {}
    for rang, membre in enumerate(membres, 1):
        document_id = nouvel_identifiant()
        ligne = {"document_id": document_id, "lot_id": lot_id, "rang": rang, "nom": membre.nom[:255],
                 "taille": membre.taille, "sha256": membre.sha256, "type_detecte": membre.type_detecte,
                 "classe": None, "statut": "EN_ATTENTE", "code": None, "doublon_de": None, "nonce": None,
                 "chiffre": None, "cree_le": quand, "modifie_le": quand}
        if membre.refus is not None:
            port.ajouter_document({**ligne, "statut": "REFUSE", "code": membre.refus["code"]})
            port.journaliser(lot_id, acteur, "document.refuse", document_id=document_id, code=membre.refus["code"])
            continue
        original = vus_dans_le_lot.get(membre.sha256)
        if original is None:
            connu = port.original(membre.sha256)
            original = connu["document_id"] if connu is not None else None
        if original is not None:
            port.ajouter_document({**ligne, "statut": "DOUBLON", "code": None, "doublon_de": original})
            port.journaliser(lot_id, acteur, "document.doublon_exact", document_id=document_id,
                             details={"original": original})
            continue
        assert membre.octets is not None
        nonce, chiffre = scellement.sceller(reference, "original", document_id, membre.sha256, membre.octets)
        port.ajouter_document({**ligne, "nonce": nonce, "chiffre": chiffre})
        port.planifier(lot_id, document_id)
        vus_dans_le_lot[membre.sha256] = document_id
    port.rafraichir_lot(lot_id)
    lot = port.lot(lot_id)
    assert lot is not None
    return {**_vue_lot(port, lot), "rejeu": False}


# ============================================================================================== étapes
def _resultat_etape(port: TachesSQLite, lot: Mapping[str, Any], document_id: str, etape: str) -> Any:
    tache = port.resultat(document_id, etape)
    if tache is None or tache["statut"] != "TERMINEE" or tache["chiffre"] is None:
        raise IngestionErreur("REJ-ING-CONTENU-CORROMPU", f"résultat de l'étape {etape} absent", 409)
    valeur = scellement.ouvrir_json(lot["cle_reference"], f"etape:{etape}", tache["tache_id"], document_id,
                                    tache["nonce"], tache["chiffre"])
    if _sha(scellement.json_canonique(valeur)) != tache["empreinte_resultat"]:
        raise IngestionErreur("REJ-ING-CONTENU-CORROMPU", f"empreinte du résultat de {etape} différente", 409)
    return valeur


def _identite_fiscale() -> dict[str, str] | None:
    from .. import taxonomie

    try:
        brut = taxonomie._valeur_du_profil(CLE_PROFIL_IDENTITE, taxonomie.fichier_profil())
    except taxonomie.ProfilInvalide:
        raise EchecEtape("REJ-ING-PROFIL-INVALIDE", "entreprise.yaml illisible") from None
    if brut is None:
        return None
    if not isinstance(brut, Mapping) or set(brut) - {"nom_legal", "tps", "tvq"} or not all(
            isinstance(v, str) and v.strip() and len(v) <= 200 for v in brut.values()) or not brut:
        raise EchecEtape("REJ-ING-PROFIL-INVALIDE", "entreprise.yaml, identite_fiscale : {nom_legal, tps, tvq} en "
                         "texte (au moins un)")
    return {cle: str(brut[cle]) for cle in brut}


def _taux_fiscaux() -> dict[str, Any]:
    from m5_financecore import outils as m5_outils
    from m5_financecore import taux_fiscaux

    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    if erreurs:
        raise EchecEtape("REJ-ING-PROFIL-INVALIDE", "taux fiscaux versionnés de M5 illisibles")
    return dictionnaire


def _preparer(port: TachesSQLite, lot: Mapping[str, Any], document: Mapping[str, Any],
              tache: Mapping[str, Any]) -> dict[str, Any]:
    """Les entrées de l'étape, lues dans la transaction de réservation (déchiffrées en mémoire seulement)."""
    etape = tache["etape"]
    entrees: dict[str, Any] = {"etape": etape, "document": dict(document), "lot": dict(lot)}
    if etape in ("empreinte", "type", "texte"):
        entrees["octets"] = scellement.ouvrir(lot["cle_reference"], "original", document["document_id"],
                                              document["sha256"], document["nonce"], document["chiffre"])
    if etape == "classement":
        entrees["texte"] = _resultat_etape(port, lot, document["document_id"], "texte")
    if etape == "extraction":
        entrees["texte"] = _resultat_etape(port, lot, document["document_id"], "texte")
        entrees["classe"] = _resultat_etape(port, lot, document["document_id"], "classement")["classe"]
        if entrees["classe"] == "facture":
            entrees["extracteur"] = port_extraction.resoudre(port.cnx)
    if etape == "validation":
        entrees["classe"] = _resultat_etape(port, lot, document["document_id"], "classement")["classe"]
        entrees["extraction"] = _resultat_etape(port, lot, document["document_id"], "extraction")
        if entrees["classe"] == "facture":
            entrees["identite"] = _identite_fiscale()
            entrees["taux"] = _taux_fiscaux()
    if etape == "proposition":
        entrees["classe"] = _resultat_etape(port, lot, document["document_id"], "classement")["classe"]
        entrees["validation"] = _resultat_etape(port, lot, document["document_id"], "validation")
        entrees["extraction"] = _resultat_etape(port, lot, document["document_id"], "extraction")
        entrees["texte_source"] = _resultat_etape(port, lot, document["document_id"], "texte").get("source")
    return entrees


def _executer_etape(entrees: Mapping[str, Any], *, extracteur_pdf: Any = None, extracteur_ocr: Any = None
                    ) -> tuple[dict[str, Any], str | None]:
    """`(résultat, code)` de l'étape, HORS transaction. `code` non nul : l'étape a abouti à un verdict qui arrête le
    document (sans être une panne). Lève `EchecEtape` pour une panne ou un refus du contenu."""
    etape, document = entrees["etape"], entrees["document"]
    if etape == "empreinte":
        empreinte = _sha(entrees["octets"])
        if empreinte != document["sha256"]:
            raise EchecEtape("REJ-ING-CONTENU-CORROMPU", "l'original déchiffré n'a plus son empreinte")
        return {"sha256": empreinte, "taille": len(entrees["octets"])}, None
    if etape == "type":
        type_detecte, refus = depot.detecter_type(document["nom"], entrees["octets"])
        if refus is not None:
            raise EchecEtape(refus["code"], refus["detail"])
        return {"type": type_detecte}, None
    if etape == "texte":
        return extraction_texte.extraire(document["type_detecte"], entrees["octets"],
                                         document_id=document["document_id"], extracteur_pdf=extracteur_pdf,
                                         extracteur_ocr=extracteur_ocr), None
    if etape == "classement":
        resultat = classement.classer(entrees["texte"])
        if resultat["classe"] == "inconnu":
            return resultat, "REJ-ING-CLASSE-INCONNUE"
        if resultat["classe"] in ("soumission", "contrat"):
            return resultat, "REJ-ING-CLASSE-NON-PEUPLEE"
        return resultat, None
    if etape == "extraction":
        if entrees["classe"] == "facture":
            extracteur = entrees["extracteur"]
            return {"provenance": extracteur.provenance(),
                    "facture": port_extraction.extraire(extracteur, entrees["texte"]["pages"])}, None
        from m2_revenue_crm import clients_importes

        lecture, raison = clients_importes.lire_lignes(entrees["texte"]["candidats"])
        if raison is not None:
            raise EchecEtape("REJ-ING-TABLEAU-ILLISIBLE", f"liste de clients : {raison['code']}")
        return {"clients": lecture}, None
    if etape == "validation":
        if entrees["classe"] == "facture":
            from m5_financecore import validation_facture_onboarding

            jour = datetime.fromisoformat(entrees["lot"]["cree_le"]).date()
            verdict = validation_facture_onboarding.valider(
                entrees["extraction"]["facture"], dictionnaire_taux=entrees["taux"], identite=entrees["identite"],
                jour_depot=jour)
            if verdict["direction"] == "client":
                return verdict, "REJ-ING-CLASSE-NON-PEUPLEE"
            return verdict, None
        from m2_revenue_crm import clients_importes

        lecture = entrees["extraction"]["clients"]
        return {"fiches": clients_importes.proposer_fiches(lecture["lignes"]),
                "lignes_refusees": lecture["refusees"]}, None
    if etape == "proposition":
        return {"classe": entrees["classe"]}, None
    raise EchecEtape("REJ-ING-ARGUMENT-INVALIDE", f"étape inconnue {etape!r}")


def _nom_compare(nom: str) -> str:
    from m5_financecore import validation_facture_onboarding

    return validation_facture_onboarding._nom_compare(nom)


def _inserer_brouillon(port: TachesSQLite, lot: Mapping[str, Any], document_id: str, *, genre: str,
                       cle_metier: str, statut: str, raisons: list[str], cles: list[str],
                       charge: Mapping[str, Any]) -> str:
    brouillon_id = nouvel_identifiant()
    nonce, chiffre = scellement.sceller_json(lot["cle_reference"], f"brouillon:{genre}", brouillon_id, cle_metier,
                                             charge)
    quand = instant_texte()
    port.cnx.execute(INGESTION_BROUILLONS.insert().values(
        brouillon_id=brouillon_id, lot_id=lot["lot_id"], document_id=document_id, genre=genre, cle_metier=cle_metier,
        statut=statut, raisons=json.dumps(sorted(set(raisons))), cles=json.dumps(cles), nonce=nonce, chiffre=chiffre,
        revision=1, decision=None, reference_definitive=None, cree_le=quand, modifie_le=quand))
    return brouillon_id


def _brouillon_par_cle(port: TachesSQLite, genre: str, cle_metier: str) -> dict[str, Any] | None:
    ligne = port.cnx.execute(select(INGESTION_BROUILLONS).where(
        (INGESTION_BROUILLONS.c.genre == genre) & (INGESTION_BROUILLONS.c.cle_metier == cle_metier))).mappings().first()
    return dict(ligne) if ligne is not None else None


def _proposer_facture(port: TachesSQLite, lot: Mapping[str, Any], document: Mapping[str, Any],
                      entrees: Mapping[str, Any]) -> dict[str, Any]:
    verdict = entrees["validation"]
    facture = verdict["facture"]
    if facture and facture["fournisseur"] and facture["numero"]:
        cle_metier = _sha(("ap|" + _nom_compare(facture["fournisseur"]) + "|"
                           + re.sub(r"\s+", "", facture["numero"]).casefold()).encode("utf-8"))
    else:
        cle_metier = _sha(("ap-document|" + document["sha256"]).encode("ascii"))
    existant = _brouillon_par_cle(port, "ap_facture_fournisseur", cle_metier)
    if existant is not None:
        return {"brouillons": [], "rattaches": [{"brouillon_id": existant["brouillon_id"],
                                                 "regle": "meme_fournisseur_et_numero"}], "statut": "TERMINE"}
    charge = {"validation": verdict, "extraction": entrees["extraction"]["facture"],
              "provenance": entrees["extraction"]["provenance"],
              "document": {"nom": document["nom"], "sha256": document["sha256"]},
              "texte_source": entrees["texte_source"],
              "avertissements": ["texte issu d'OCR : relire les montants contre l'original"]
              if entrees["texte_source"] == "ocr" else []}
    brouillon_id = _inserer_brouillon(
        port, lot, document["document_id"], genre="ap_facture_fournisseur", cle_metier=cle_metier,
        statut=verdict["statut"], raisons=[r["code"] for r in verdict["raisons"]], cles=[cle_metier], charge=charge)
    return {"brouillons": [brouillon_id], "rattaches": [],
            "statut": "TERMINE" if verdict["statut"] == "PRET" else "A_VERIFIER"}


def _cles_connues_crm(port: TachesSQLite) -> tuple[dict[str, str], dict[str, str]]:
    """Les clés fortes des brouillons clients et des clients DÉJÀ importés (M2) : clé -> brouillon_id ou client_id."""
    from m2_revenue_crm import clients_importes

    from .. import stockage

    brouillons: dict[str, str] = {}
    for brouillon_id, cles in port.cnx.execute(select(INGESTION_BROUILLONS.c.brouillon_id, INGESTION_BROUILLONS.c.cles)
                                               .where(INGESTION_BROUILLONS.c.genre == "crm_client")):
        for cle in json.loads(cles):
            brouillons.setdefault(cle, brouillon_id)
    definitifs: dict[str, str] = {}
    for maillon in clients_importes.clients_importes(stockage.maillons("m02-revenue-crm", "clients_importes")):
        for cle in clients_importes.empreintes_du_client(maillon):
            definitifs.setdefault(cle, maillon["client_id"])
    return brouillons, definitifs


def _proposer_clients(port: TachesSQLite, lot: Mapping[str, Any], document: Mapping[str, Any],
                      entrees: Mapping[str, Any]) -> dict[str, Any]:
    brouillons, definitifs = _cles_connues_crm(port)
    crees, rattaches = [], []
    a_verifier = False
    for fiche in entrees["validation"]["fiches"]:
        client = next((definitifs[c] for c in fiche["cles"] if c in definitifs), None)
        if client is not None:
            rattaches.append({"lignes": fiche["lignes"], "client_id": client, "regle": "cle_forte_d_un_client_importe"})
            continue
        brouillon = next((brouillons[c] for c in fiche["cles"] if c in brouillons), None)
        if brouillon is not None:
            rattaches.append({"lignes": fiche["lignes"], "brouillon_id": brouillon,
                              "regle": "cle_forte_d_un_brouillon_existant"})
            continue
        charge = {"fiche": fiche, "document": {"nom": document["nom"], "sha256": document["sha256"]}}
        cle_metier = fiche["cle_metier"] if fiche["cles"] else _sha(
            f"crm-sans-cle-forte|{document['sha256']}|{fiche['lignes']}|{fiche['cle_metier']}".encode())
        brouillon_id = _inserer_brouillon(
            port, lot, document["document_id"], genre="crm_client", cle_metier=cle_metier,
            statut=fiche["statut"], raisons=[r["code"] for r in fiche["raisons"]], cles=fiche["cles"], charge=charge)
        for cle in fiche["cles"]:
            brouillons.setdefault(cle, brouillon_id)
        crees.append(brouillon_id)
        a_verifier = a_verifier or fiche["statut"] != "PRET"
    if entrees["validation"]["lignes_refusees"]:
        a_verifier = True
    return {"brouillons": crees, "rattaches": rattaches, "lignes_refusees": entrees["validation"]["lignes_refusees"],
            "statut": "A_VERIFIER" if a_verifier else "TERMINE"}


_STATUT_DU_CODE = {
    "REJ-ING-TYPE-NON-ACCEPTE": "REFUSE", "REJ-ING-TYPE-INCOHERENT": "REFUSE", "REJ-ING-CONTENU-CORROMPU": "REFUSE",
    "REJ-ING-PDF-REFUSE": "REFUSE", "REJ-ING-TEXTE-ILLISIBLE": "REFUSE", "REJ-ING-TABLEAU-ILLISIBLE": "REFUSE",
}


def _conclure(port: TachesSQLite, lot: Mapping[str, Any], tache: Mapping[str, Any], porteur: str,
              resultat: dict[str, Any] | None, code: str | None, *, refus: EchecEtape | None = None) -> bool:
    """Écrit l'issue de l'étape et ses effets, dans la transaction courante ; `False` si le bail a été perdu (rien
    n'est alors écrit : l'appelant annule la transaction)."""
    document_id = tache["document_id"]
    if refus is not None and refus.reprenable:
        return port.echouer(tache, porteur, refus.code, reprenable=True) is not None
    if refus is not None:
        resultat, code = {"refus": refus.code, "detail": refus.detail}, refus.code
    assert resultat is not None
    empreinte = _sha(scellement.json_canonique(resultat))
    nonce, chiffre = scellement.sceller_json(lot["cle_reference"], f"etape:{tache['etape']}", tache["tache_id"],
                                             document_id, resultat)
    if not port.terminer(tache, porteur, nonce=nonce, chiffre=chiffre, empreinte=empreinte, code=code):
        return False
    if tache["etape"] == "type" and code is None:
        port.maj_document(document_id, type_detecte=resultat["type"])
    if tache["etape"] == "classement":
        port.maj_document(document_id, classe=resultat["classe"])
    if tache["etape"] == "validation" and code == "REJ-ING-CLASSE-NON-PEUPLEE":
        port.maj_document(document_id, classe="facture_client")
    if code is not None:
        port.sauter_suivantes(document_id, tache["rang_etape"], code)
        port.maj_document(document_id, statut=_STATUT_DU_CODE.get(code, "NON_TRAITE"), code=code)
    return True


_CODES_CONFIGURATION = frozenset({"REJ-ING-CLE-INDISPONIBLE", "REJ-ING-CHIFFREMENT-INDISPONIBLE"})


class _BailPerdu(Exception):
    pass


def avancer(fabrique: FabriqueConnexion, acteur: str, lot_id: str, *, budget: int = 64, porteur: str | None = None,
            horloge: Horloge | None = None, extracteur_pdf: Any = None, extracteur_ocr: Any = None) -> dict[str, Any]:
    """Exécute au plus `budget` tâches du lot. Chaque tâche : réserver (transaction 1), travailler hors transaction,
    conclure par CAS (transaction 2). Rend le lot, ses compteurs et ce que cet appel a fait."""
    acteur = _acteur(acteur)
    lot_id = _identifiant(lot_id, "lot_id")
    if type(budget) is not int or not 1 <= budget <= 500:
        raise IngestionErreur("REJ-ING-ARGUMENT-INVALIDE", "budget : entier de 1 à 500", 422)
    porteur = porteur or f"{acteur[:40]}:{nouvel_identifiant()[:12]}"
    maintenant = horloge or _horloge
    executees: dict[str, int] = {}
    pertes = 0
    for _ in range(budget):
        with fabrique() as cnx:
            port = TachesSQLite(cnx, maintenant=maintenant)
            lot = port.lot(lot_id)
            if lot is None:
                raise IngestionErreur("REJ-ING-LOT-INCONNU", "lot inconnu", 404)
            tache = port.reserver(lot_id, porteur)
            if tache is None:
                port.rafraichir_lot(lot_id)
                break
            document = port.document(tache["document_id"])
            assert document is not None
            try:
                entrees, refus = _preparer(port, lot, document, tache), None
            except EchecEtape as exc:
                entrees, refus = None, exc
            except IngestionErreur as exc:
                entrees, refus = None, EchecEtape(exc.code, exc.detail, reprenable=exc.code in _CODES_CONFIGURATION)
        resultat, code = None, None
        if refus is None:
            try:
                resultat, code = _executer_etape(entrees, extracteur_pdf=extracteur_pdf, extracteur_ocr=extracteur_ocr)
            except EchecEtape as exc:
                refus = exc
        try:
            with fabrique() as cnx:
                port = TachesSQLite(cnx, maintenant=maintenant)
                if refus is None and tache["etape"] == "proposition":
                    resultat = _proposer(port, lot, document, entrees)
                if not _conclure(port, lot, tache, porteur, resultat, code, refus=refus):
                    raise _BailPerdu
                if tache["etape"] == "proposition" and refus is None:
                    port.maj_document(document["document_id"], statut=resultat["statut"])
                port.rafraichir_lot(lot_id)
        except _BailPerdu:
            pertes += 1
            continue
        issue = f"{tache['etape']}:{refus.code if refus is not None else (code or 'ok')}"
        executees[issue] = executees.get(issue, 0) + 1
    with fabrique() as cnx:
        port = TachesSQLite(cnx, maintenant=maintenant)
        lot = port.lot(lot_id)
        assert lot is not None
        return {**_vue_lot(port, lot), "taches_executees": sum(executees.values()),
                "issues": dict(sorted(executees.items())), "baux_perdus": pertes}


def _proposer(port: TachesSQLite, lot: Mapping[str, Any], document: Mapping[str, Any],
              entrees: Mapping[str, Any]) -> dict[str, Any]:
    if entrees["classe"] == "facture":
        return {"classe": "facture", **_proposer_facture(port, lot, document, entrees)}
    return {"classe": "liste_clients", **_proposer_clients(port, lot, document, entrees)}


# ============================================================================================== lecture
VUES_LOT = ("resume", "documents", "brouillons")


def lire_lot(cnx: Connection, lot_id: str, *, vue: str = "resume", depart: int = 0, limite: int = 10
             ) -> dict[str, Any]:
    """Le lot et ses compteurs ; `vue` « documents » ou « brouillons » ajoute une PAGE de métadonnées (jamais un
    contenu), avec `suivant` (décalage de la page suivante, `None` à la fin)."""
    lot_id = _identifiant(lot_id, "lot_id")
    if (vue not in VUES_LOT or type(depart) is not int or depart < 0 or type(limite) is not int
            or not 1 <= limite <= _PAGE_MAX):
        raise IngestionErreur("REJ-ING-ARGUMENT-INVALIDE", f"vue parmi {VUES_LOT}, depart ≥ 0, limite de 1 à "
                              f"{_PAGE_MAX}", 422)
    port = TachesSQLite(cnx, maintenant=_horloge)
    lot = port.lot(lot_id)
    if lot is None:
        raise IngestionErreur("REJ-ING-LOT-INCONNU", "lot inconnu", 404)
    resultat: dict[str, Any] = {**_vue_lot(port, lot), "vue": vue}
    if vue == "resume":
        return resultat
    if vue == "documents":
        requete = select(INGESTION_DOCUMENTS).where(INGESTION_DOCUMENTS.c.lot_id == lot_id).order_by(
            INGESTION_DOCUMENTS.c.rang)
        vues = [_vue_document(d) for d in cnx.execute(requete.offset(depart).limit(limite + 1)).mappings()]
    else:
        requete = select(INGESTION_BROUILLONS).where(INGESTION_BROUILLONS.c.lot_id == lot_id).order_by(
            INGESTION_BROUILLONS.c.cree_le, INGESTION_BROUILLONS.c.brouillon_id)
        vues = [_vue_brouillon(b) for b in cnx.execute(requete.offset(depart).limit(limite + 1)).mappings()]
    return {**resultat, vue: vues[:limite], "depart": depart,
            "suivant": depart + limite if len(vues) > limite else None}


def journal(cnx: Connection, lot_id: str, *, limite: int = 200) -> list[dict[str, Any]]:
    lot_id = _identifiant(lot_id, "lot_id")
    lignes = cnx.execute(select(INGESTION_JOURNAL).where(INGESTION_JOURNAL.c.lot_id == lot_id)
                         .order_by(INGESTION_JOURNAL.c.id).limit(limite)).mappings()
    return [{**dict(ligne), "details": json.loads(ligne["details"])} for ligne in lignes]


def lire_brouillon(cnx: Connection, brouillon_id: str) -> dict[str, Any]:
    """Le brouillon ET son contenu déchiffré (pour la revue humaine et pour l'outil de validation)."""
    brouillon_id = _identifiant(brouillon_id, "brouillon_id")
    ligne = cnx.execute(select(INGESTION_BROUILLONS).where(
        INGESTION_BROUILLONS.c.brouillon_id == brouillon_id)).mappings().first()
    if ligne is None:
        raise IngestionErreur("REJ-ING-BROUILLON-INCONNU", "brouillon inconnu", 404)
    lot = TachesSQLite(cnx, maintenant=_horloge).lot(ligne["lot_id"])
    assert lot is not None
    contenu = scellement.ouvrir_json(lot["cle_reference"], f"brouillon:{ligne['genre']}", brouillon_id,
                                     ligne["cle_metier"], ligne["nonce"], ligne["chiffre"])
    return {**_vue_brouillon(ligne), "contenu": contenu}


def decider_brouillon(cnx: Connection, brouillon_id: str, *, genre: str, revision_attendue: Any, statut: str,
                      decision: Mapping[str, Any], reference: str | None) -> dict[str, Any]:
    """CAS : le brouillon passe VALIDE (avec la référence de la donnée définitive écrite dans la MÊME transaction) ou
    ECARTE. Appelé par les outils de validation de M5 et M2 seulement, après qu'ils ont établi l'humain."""
    brouillon = lire_brouillon(cnx, brouillon_id)
    controler_decidable(brouillon, genre=genre, revision_attendue=revision_attendue)
    if statut not in ("VALIDE", "ECARTE") or (statut == "VALIDE") != (reference is not None):
        raise IngestionErreur("REJ-ING-DECISION-INVALIDE", "VALIDE avec une référence, ou ECARTE sans", 422)
    resultat = cnx.execute(update(INGESTION_BROUILLONS).where(
        (INGESTION_BROUILLONS.c.brouillon_id == brouillon_id)
        & (INGESTION_BROUILLONS.c.revision == revision_attendue)
        & INGESTION_BROUILLONS.c.statut.in_(("PRET", "A_VERIFIER"))
    ).values(statut=statut, decision=json.dumps(dict(decision), ensure_ascii=False, sort_keys=True),
             reference_definitive=reference, revision=revision_attendue + 1, modifie_le=instant_texte()))
    if resultat.rowcount != 1:
        raise IngestionErreur("REJ-ING-BROUILLON-REVISION", "brouillon modifié entre-temps : relire")
    port = TachesSQLite(cnx, maintenant=_horloge)
    port.journaliser(brouillon["lot_id"], str(decision.get("par", "?")), f"brouillon.{statut.lower()}",
                     document_id=brouillon["document_id"], details={"brouillon_id": brouillon_id, "genre": genre,
                                                                    "voie": decision.get("voie"),
                                                                    "reference": reference})
    etat.journaliser(cnx, str(decision.get("par", "?")), f"ingestion.brouillon.{statut.lower()}", brouillon_id,
                     {"genre": genre, "voie": decision.get("voie"), "reference": reference})
    return lire_brouillon(cnx, brouillon_id)


def controler_decidable(brouillon: Mapping[str, Any], *, genre: str, revision_attendue: Any) -> None:
    if brouillon["genre"] != genre:
        raise IngestionErreur("REJ-ING-BROUILLON-GENRE", f"ce brouillon est un {brouillon['genre']}, pas un {genre}",
                              422)
    if brouillon["statut"] in ("VALIDE", "ECARTE"):
        raise IngestionErreur("REJ-ING-BROUILLON-DEJA-DECIDE", f"brouillon déjà {brouillon['statut']} "
                              f"(référence {brouillon['reference_definitive']})")
    if type(revision_attendue) is not int or revision_attendue != brouillon["revision"]:
        raise IngestionErreur("REJ-ING-BROUILLON-REVISION", f"révision attendue {brouillon['revision']} : relire le "
                              "brouillon avant de décider")


def lister_lots(cnx: Connection, *, limite: int = 20) -> list[dict[str, Any]]:
    from ..stockage.schema import INGESTION_LOTS

    port = TachesSQLite(cnx, maintenant=_horloge)
    lignes = cnx.execute(select(INGESTION_LOTS).order_by(INGESTION_LOTS.c.cree_le.desc()).limit(
        min(max(limite, 1), _PAGE_MAX))).mappings()
    return [_vue_lot(port, ligne) for ligne in lignes]


__all__ = [
    "CLE_PROFIL_IDENTITE", "ETAPES", "RANG", "avancer", "controler_decidable", "decider_brouillon", "deposer",
    "journal", "lire_brouillon", "lire_lot", "lister_lots",
]
