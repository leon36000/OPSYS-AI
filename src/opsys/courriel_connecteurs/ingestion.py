"""Ingestion : un compte (ou un export mbox) alimente la file d'ingestion d'onboarding EXISTANTE, en brouillon à
confirmer.

Rien n'est contourné : les pièces jointes admises sont empaquetées dans une archive ZIP déterministe, déposée dans le
dossier d'onboarding et confiée à `ingestion_onboarding.service.deposer` (qui refait ses propres contrôles : type par
signature ET extension, archive gardée, quotas, dédoublonnage SHA-256, chiffrement). Les brouillons AP (M5) et CRM (M2)
qui en sortent attendent une décision humaine ; aucune donnée définitive n'est écrite ici. Les pièces ne sont ni
ouvertes ni exécutées : empreinte, signature, empaquetage.

Garanties :
- **Reprise** : le curseur d'un dossier n'est persisté qu'APRÈS la page traitée (dépôt compris), dans la même
  transaction que les clés d'idempotence de la page. Un arrêt à n'importe quel moment laisse soit la page à refaire,
  soit rien : jamais un message perdu. L'archive d'une page est déterministe (noms triés, dates fixes, SHA-256) et sa
  clé de mutation en dérive : refaire la page rejoue le même lot (`rejeu`), jamais un second.
- **Idempotence et déduplication** : clé = `Message-ID` (sinon la référence du fournisseur) + empreinte du CONTENU.
  Même clé et même empreinte = doublon (copie dans un autre dossier, reconnexion, nouvel amorçage) ; même clé et
  contenu différent = version distincte, traitée.
- **Débit** : un limiteur à jetons (horloge injectée) borne les messages lus par minute ; à sec, on s'arrête SANS
  avancer le curseur (`quota`). Les limites du fournisseur (429) sont gérées plus bas par `ClientApi`.
- **Contenu non fiable** : le corps n'est ni stocké ni interprété ici ; il ne sort que par `isolation.vue_pour_agent`.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import os
import re
import stat
import time
import zipfile
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, insert, select

from ..ingestion_onboarding import contacts_courriel, depot
from ..ingestion_onboarding import service as ingestion
from ..ingestion_onboarding.codes import IngestionErreur
from ..stockage.schema import COURRIEL_MESSAGES, COURRIEL_REFS
from . import comptes, isolation
from .erreurs import ErreurCourriel
from .modele import Adresse, MessageNormalise, PieceJointe
from .normalisation import normaliser
from .port import FournisseurCourriel
from .reception import Recepteur, construire

FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]
MODE = "brouillon_a_confirmer"
# Interruptions du planificateur (arrêt propre, bail repris par un autre exécuteur) : propagées telles quelles.
CODES_INTERRUPTION = frozenset({"REJ-COURRIEL-ARRET-DEMANDE", "REJ-COURRIEL-BAIL-PERDU"})
ARCHIVE_OCTETS_MAX = 24 * 1024 * 1024
ARCHIVE_MEMBRES_MAX = 400
_EXTENSION = {
    "application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "text/plain": "txt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}
_GENERIQUES = frozenset({"application/octet-stream", "binary/octet-stream", "application/x-download"})
# En-tête du document de contacts déposé à l'onboarding (genre de brouillon « courriel_contact ») : le classement de
# l'ingestion le reconnaît à cette première ligne et à elle seule.
MAGIE_CONTACTS = contacts_courriel.MAGIE
COLONNES_CONTACTS = contacts_courriel.COLONNES
CONTACTS_PAR_PAGE_MAX = 500
NOM_CONTACT_MAX = 80
_DOMAINES_PERSONNELS = frozenset({
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.ca", "hotmail.fr", "outlook.com", "outlook.fr", "live.com",
    "live.ca", "msn.com", "yahoo.com", "yahoo.ca", "yahoo.fr", "icloud.com", "me.com", "mac.com", "aol.com",
    "protonmail.com", "proton.me", "videotron.ca", "bell.net", "sympatico.ca", "cgocable.ca", "videotron.qc.ca",
})
_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")


class LimiteurDebit:
    """Seau à jetons : `par_minute` messages au plus par minute, rechargé en continu (horloge injectée)."""

    def __init__(self, par_minute: int, horloge: Callable[[], float] = time.monotonic) -> None:
        if type(par_minute) is not int or par_minute < 1:
            raise ValueError("par_minute : entier positif")
        self._capacite, self._horloge = float(par_minute), horloge
        self._jetons, self._dernier = float(par_minute), horloge()

    def prendre(self, n: int = 1) -> bool:
        maintenant = self._horloge()
        self._jetons = min(self._capacite, self._jetons + (maintenant - self._dernier) * self._capacite / 60.0)
        self._dernier = maintenant
        if self._jetons >= n:
            self._jetons -= n
            return True
        return False


@dataclasses.dataclass
class RapportIngestion:
    mode: str = MODE
    pages: int = 0
    messages_lus: int = 0
    nouveaux: int = 0
    doublons: int = 0
    deja_vus: int = 0
    refuses: int = 0
    pieces_transmises: int = 0
    pieces_non_transmises: dict[str, int] = dataclasses.field(default_factory=dict)
    lots: list[str] = dataclasses.field(default_factory=list)
    reprises_curseur: int = 0
    statut: str = "termine"  # termine | quota | erreur | page_max
    code: str | None = None
    recus_m1: int = 0  # courriels ENTRANTS devenus une réception de M1
    deja_recus_m1: int = 0  # déjà reçus par M1 (autre voie, autre compte, rejeu) : aucun doublon
    refuses_m1: dict[str, int] = dataclasses.field(default_factory=dict)
    contacts: int = 0  # correspondants déposés à l'onboarding (amorçage seulement)
    amorce_termine: bool = False

    def refuser_piece(self, raison: str) -> None:
        self.pieces_non_transmises[raison] = self.pieces_non_transmises.get(raison, 0) + 1

    def vers_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def classer_piece(piece: PieceJointe) -> tuple[str | None, str | None]:
    """`(extension, None)` si la pièce peut entrer dans la file d'ingestion ; `(None, raison)` sinon."""
    if piece.refus is not None:
        return None, "trop_gros"
    if piece.dangereux:
        return None, "dangereux"
    if not piece.octets:
        return None, "vide"
    extension = _EXTENSION.get(piece.mime_detecte)
    if extension is None:
        return None, "type_non_accepte"
    declare_compatible = (piece.mime_declare in _GENERIQUES or piece.mime_verifie
                          or (piece.mime_declare.startswith("text/") and piece.mime_detecte == "text/plain"))
    if not declare_compatible:
        return None, "type_incoherent"
    if not piece.extension_coherente:
        return None, "extension_incoherente"
    if extension == "txt" and (piece.nom.lower().endswith(".csv") or piece.mime_declare == "text/csv"):
        extension = "csv"
    membre = f"{piece.sha256[:16]}.{extension}"
    type_detecte, _ = depot.detecter_type(membre, piece.octets)
    if type_detecte is None:
        return None, "type_non_accepte"
    return extension, None


def construire_archive(membres: list[tuple[str, bytes]]) -> bytes:
    """Archive ZIP DÉTERMINISTE (noms triés, dates fixes, sans compression) : les mêmes pièces donnent les mêmes
    octets."""
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_STORED) as archive:
        for nom, octets in sorted(membres):
            info = zipfile.ZipInfo(nom, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, octets)
    return sortie.getvalue()


def deposer_archive(octets: bytes, dossier: Path | None = None) -> str:
    """Écrit l'archive (nom = son SHA-256) sans jamais écraser ni suivre un lien ; rend son nom."""
    nom = f"courriel-{hashlib.sha256(octets).hexdigest()[:40]}.zip"
    racine = dossier if dossier is not None else depot.dossier_depot()
    racine.mkdir(mode=0o700, parents=True, exist_ok=True)
    etat = os.lstat(racine)
    if not stat.S_ISDIR(etat.st_mode):
        raise ErreurCourriel("REJ-COURRIEL-INGESTION-REFUSEE", "dossier de dépôt d'onboarding invalide", 500)
    chemin = racine / nom
    try:
        descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if chemin.is_symlink() or not chemin.is_file() or chemin.read_bytes() != octets:
            raise ErreurCourriel("REJ-COURRIEL-INGESTION-REFUSEE", "archive de dépôt existante différente",
                                 409) from None
        return nom
    with os.fdopen(descripteur, "wb") as flux:
        flux.write(octets)
    return nom


def _nom_contact(nom: str, filtre: isolation.Filtre) -> str:
    """Le nom affiché d'un correspondant : DONNÉE NON FIABLE, neutralisée comme tout texte de courriel, une ligne."""
    propre, _ = isolation._neutraliser(nom, filtre)
    return " ".join(_CONTROLE.sub(" ", propre).split())[:NOM_CONTACT_MAX]


def _organisation(adresse: str) -> str:
    domaine = adresse.rsplit("@", 1)[-1].lower()
    return "" if domaine in _DOMAINES_PERSONNELS else domaine


def releves_contacts(message: MessageNormalise, propre_courriel: str, filtre: isolation.Filtre,
                     cumul: dict[str, dict[str, Any]]) -> None:
    """Ajoute au `cumul` de la page les correspondants d'un message (expéditeur, destinataires, copie) hors l'adresse du
    compte lui-même : nom (neutralisé), nombre de messages reçus et envoyés, premier et dernier échange."""
    propre = propre_courriel.lower()
    envoye = message.expediteur is not None and message.expediteur.courriel.lower() == propre
    personnes: list[Adresse] = ([message.expediteur] if message.expediteur and not envoye else []) + (
        [*message.destinataires, *message.copie] if envoye else [])
    date = message.date_utc or ""
    for personne in personnes:
        adresse = personne.courriel.lower()
        if adresse == propre or not adresse:
            continue
        fiche = cumul.setdefault(adresse, {"nom": "", "recus": 0, "envoyes": 0, "premier": date, "dernier": date})
        if not fiche["nom"] and personne.nom:
            fiche["nom"] = _nom_contact(personne.nom, filtre)
        fiche["envoyes" if envoye else "recus"] += 1
        if date and (not fiche["premier"] or date < fiche["premier"]):
            fiche["premier"] = date
        if date and date > fiche["dernier"]:
            fiche["dernier"] = date


def document_contacts(cumul: dict[str, dict[str, Any]]) -> bytes | None:
    """Le CSV déterministe des correspondants d'une page (adresses triées, plafonné), ou `None` s'il n'y en a pas."""
    if not cumul:
        return None
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, lineterminator="\n")
    ecrivain.writerow([MAGIE_CONTACTS])
    ecrivain.writerow(COLONNES_CONTACTS)
    for adresse in sorted(cumul)[:CONTACTS_PAR_PAGE_MAX]:
        f = cumul[adresse]
        ecrivain.writerow([f["nom"], adresse, _organisation(adresse), f["recus"], f["envoyes"], f["premier"],
                           f["dernier"]])
    return sortie.getvalue().encode("utf-8")


class IngestionCourriel:
    def __init__(self, fabrique: FabriqueConnexion, *, acteur: str, limiteur: LimiteurDebit | None = None,
                 dossier_depot: Path | None = None, taille_page: int = 50, pages_max: int = 10_000,
                 serveurs_fiables: frozenset[str] | None = None,
                 signaler: Callable[[str, ErreurCourriel], None] | None = None,
                 recepteur: Recepteur | None = None, entre_pages: Callable[[], None] | None = None) -> None:
        self._fabrique, self._acteur, self._limiteur = fabrique, acteur, limiteur
        self._dossier, self._taille_page, self._pages_max = dossier_depot, taille_page, pages_max
        self._serveurs_fiables, self._signaler = serveurs_fiables, signaler
        # `recepteur` : M1 (réception des courriels ENTRANTS, comptes qui l'ont demandé) ; `entre_pages` : appelé avant
        # chaque page (renouvellement du bail, arrêt propre) ; il lève `ErreurCourriel` pour interrompre.
        self._recepteur, self._entre_pages = recepteur, entre_pages

    def synchroniser_compte(self, compte_id: str, fournisseur: FournisseurCourriel) -> dict[str, RapportIngestion]:
        """Tous les dossiers suivis du compte, l'un après l'autre ; un dossier en erreur n'empêche pas les autres, sauf
        quand le compte lui-même est refusé (jeton révoqué : inutile d'insister sur les autres dossiers)."""
        with self._fabrique() as cnx:
            suivis = comptes.vue(comptes.ligne_brute(cnx, compte_id))["dossiers_suivis"]
        rapports: dict[str, RapportIngestion] = {}
        for dossier in suivis:
            rapports[dossier] = self.synchroniser(compte_id, fournisseur, dossier)
            if rapports[dossier].code in {"REJ-COURRIEL-QUOTA-DEBIT"} or (
                    rapports[dossier].code or "").startswith(("REJ-COURRIEL-AUTH", "REJ-COURRIEL-JETON")):
                break
        return rapports

    # -- un dossier -----------------------------------------------------------------------------------------------
    def synchroniser(self, compte_id: str, fournisseur: FournisseurCourriel, dossier: str) -> RapportIngestion:
        rapport = RapportIngestion()
        with self._fabrique() as cnx:
            etat = comptes.ligne_brute(cnx, compte_id)["etat"]
        if etat != "connecte":
            raise ErreurCourriel("REJ-COURRIEL-COMPTE-INACTIF", f"compte non connecté ({etat})", 409)
        try:
            self._boucle(compte_id, fournisseur, dossier, rapport)
        except ErreurCourriel as exc:
            if exc.code in CODES_INTERRUPTION:
                raise  # arrêt demandé ou bail perdu : ce n'est pas une erreur du compte, rien n'est signalé
            rapport.statut, rapport.code = "erreur", exc.code
            if self._signaler is not None:
                self._signaler(compte_id, exc)
            with self._fabrique() as cnx:
                comptes.enregistrer_synchro(cnx, compte_id, self._acteur, curseurs_a_jour={}, statut="erreur",
                                            ajoutes=0, code=exc.code)
            return rapport
        with self._fabrique() as cnx:
            comptes.enregistrer_synchro(cnx, compte_id, self._acteur, curseurs_a_jour={}, statut=rapport.statut,
                                        ajoutes=0, code=rapport.code)
        return rapport

    def _boucle(self, compte_id: str, fournisseur: FournisseurCourriel, dossier: str,
                rapport: RapportIngestion) -> None:
        for _ in range(self._pages_max):
            if self._entre_pages is not None:
                self._entre_pages()
            with self._fabrique() as cnx:
                curseur = comptes.curseurs(cnx, compte_id).get(dossier)
            try:
                page = fournisseur.synchroniser(dossier, curseur, limite=self._taille_page)
            except ErreurCourriel as exc:
                if exc.code != "REJ-COURRIEL-CURSEUR-EXPIRE" or curseur is None:
                    raise
                # Curseur caduc : nouvel amorçage ; l'idempotence absorbe les messages déjà vus.
                rapport.reprises_curseur += 1
                with self._fabrique() as cnx:
                    comptes.enregistrer_synchro(cnx, compte_id, self._acteur, curseurs_a_jour={dossier: None},
                                                statut="reprise", ajoutes=0)
                continue
            rapport.pages += 1
            if not self._traiter_page(compte_id, fournisseur, dossier, page, rapport):
                return
            if page.termine:
                return
        rapport.statut = "page_max"

    # -- une page -------------------------------------------------------------------------------------------------
    def _traiter_page(self, compte_id: str, fournisseur: FournisseurCourriel, dossier: str, page: Any,
                      rapport: RapportIngestion) -> bool:
        """Traite une page. Rend `False` si le quota de débit l'a interrompue : les messages déjà faits sont VALIDÉS
        (clés d'idempotence, références, dépôt) mais le curseur n'avance PAS ; la page entière sera relue, les
        références déjà vues sautées sans appel au fournisseur."""
        retenus: list[tuple[MessageNormalise, list[tuple[str, bytes]], int]] = []
        refs_faites: list[str] = []
        membres_page: dict[str, bytes] = {}
        interrompu = False
        with self._fabrique() as cnx:
            ligne_compte = comptes.ligne_brute(cnx, compte_id)
            curseurs_compte = comptes.curseurs(cnx, compte_id)
            propre_courriel = ligne_compte["adresse"]
            vers_m1 = comptes.option(ligne_compte, "reception_m1") and self._recepteur is not None
            vers_contacts = comptes.option(ligne_compte, "contacts_courriel")
        amorce_faite = comptes.amorce_terminee(curseurs_compte, dossier)
        filtre = isolation.filtre_m1() if (vers_contacts and not amorce_faite) or (vers_m1 and amorce_faite) else None
        contacts_page: dict[str, dict[str, Any]] = {}
        for ref in page.ajouts:
            ref_cle = hashlib.sha256(f"{dossier}\x1f{ref.ref}".encode()).hexdigest()
            with self._fabrique() as cnx:
                connue = cnx.execute(select(COURRIEL_REFS.c.ref_cle).where(
                    COURRIEL_REFS.c.compte_id == compte_id, COURRIEL_REFS.c.ref_cle == ref_cle)).first()
            if connue is not None:
                rapport.deja_vus += 1
                continue
            if self._limiteur is not None and not self._limiteur.prendre():
                rapport.statut, rapport.code = "quota", "REJ-COURRIEL-QUOTA-DEBIT"
                interrompu = True
                break
            rapport.messages_lus += 1
            try:
                brut = fournisseur.lire_message(ref)
                message = normaliser(brut, serveurs_fiables=self._serveurs_fiables)
            except ErreurCourriel as exc:
                if exc.code in {"REJ-COURRIEL-INTROUVABLE", "REJ-COURRIEL-MESSAGE-TROP-GROS",
                                "REJ-COURRIEL-MESSAGE-INVALIDE"}:
                    rapport.refuses += 1  # un message hostile ou disparu n'arrête pas l'ingestion
                    refs_faites.append(ref_cle)
                    continue
                raise
            refs_faites.append(ref_cle)
            with self._fabrique() as cnx:
                deja = cnx.execute(select(COURRIEL_MESSAGES.c.statut).where(
                    COURRIEL_MESSAGES.c.compte_id == compte_id,
                    COURRIEL_MESSAGES.c.cle_message == message.cle_idempotence(),
                    COURRIEL_MESSAGES.c.empreinte == message.empreinte)).first()
            if deja is not None or any(m.cle_idempotence() == message.cle_idempotence()
                                       and m.empreinte == message.empreinte for m, _, _ in retenus):
                rapport.doublons += 1
                continue
            if vers_m1 and amorce_faite:
                self._vers_m1(compte_id, fournisseur, message, brut.recu_le, filtre, rapport)
            if vers_contacts and not amorce_faite:
                releves_contacts(message, propre_courriel, filtre, contacts_page)
            transmises: list[tuple[str, bytes]] = []
            for piece in message.pieces_jointes:
                extension, raison = classer_piece(piece)
                if extension is None:
                    rapport.refuser_piece(raison or "inconnu")
                    continue
                nom = f"{piece.sha256[:16]}.{extension}"
                membres_page.setdefault(nom, piece.octets)
                transmises.append((nom, piece.octets))
            retenus.append((message, transmises, len(message.pieces_jointes)))
        contacts = document_contacts(contacts_page)
        if contacts is not None:
            membres_page.setdefault(f"contacts-{hashlib.sha256(contacts).hexdigest()[:16]}.csv", contacts)
            rapport.contacts += min(len(contacts_page), CONTACTS_PAR_PAGE_MAX)
        lots = self._deposer(compte_id, membres_page, rapport)
        lot_de: dict[str, str] = {}
        for nom_lot, noms in lots:
            for nom in noms:
                lot_de[nom] = nom_lot
        with self._fabrique() as cnx:
            for message, transmises, total in retenus:
                lot = lot_de.get(transmises[0][0]) if transmises else None
                cnx.execute(insert(COURRIEL_MESSAGES).values(
                    compte_id=compte_id, cle_message=message.cle_idempotence(), empreinte=message.empreinte,
                    statut="INGERE" if transmises else "SANS_PIECE", lot_id=lot, nb_pieces=total,
                    nb_pieces_transmises=len(transmises), vu_le=comptes.instant()))
                rapport.nouveaux += 1
                rapport.pieces_transmises += len(transmises)
            for ref_cle in refs_faites:
                cnx.execute(insert(COURRIEL_REFS).values(compte_id=compte_id, ref_cle=ref_cle, vu_le=comptes.instant()))
            a_jour: dict[str, str | None] = {} if interrompu else {dossier: page.curseur}
            if not interrompu and page.termine and not amorce_faite:
                a_jour[comptes.CLE_AMORCE + dossier] = "1"  # l'historique est lu : la suite est de l'ENTRANT
                rapport.amorce_termine = True
            comptes.enregistrer_synchro(
                cnx, compte_id, self._acteur, curseurs_a_jour=a_jour,
                statut="quota" if interrompu else "page", ajoutes=len(retenus))
            comptes.journaliser(cnx, compte_id, "ingestion.page", self._acteur, details={
                "dossier": dossier[:64], "messages": len(retenus), "pieces_transmises": sum(len(t) for _, t,
                                                                                            _ in retenus),
                "doublons": rapport.doublons, "page": rapport.pages, "termine": not interrompu})
        return not interrompu

    def _vers_m1(self, compte_id: str, fournisseur: FournisseurCourriel, message: MessageNormalise,
                 recu_brut: str | None, filtre: isolation.Filtre | None, rapport: RapportIngestion) -> None:
        """Un courriel ENTRANT : sa vue neutralisée devient une réception de M1. Un message non transmissible est
        compté et laissé ; un refus de configuration de M1 arrête la page (rien n'avance, reprenable)."""
        assert self._recepteur is not None
        vue = isolation.vue_pour_agent(message, compte_id=compte_id, fournisseur=fournisseur.identifiant,
                                       filtre=filtre)
        entrant, raison = construire(message, vue, compte_id=compte_id, fournisseur=fournisseur.identifiant,
                                     recu_brut=recu_brut)
        if entrant is None:
            rapport.refuses_m1[raison or "inconnu"] = rapport.refuses_m1.get(raison or "inconnu", 0) + 1
            return
        try:
            resultat = self._recepteur(entrant)
        except ErreurCourriel:
            raise
        except ValueError as exc:
            raise ErreurCourriel("REJ-COURRIEL-M1-REFUSE", f"M1 refuse la réception : {str(exc)[:200]}", 503,
                                 reprenable=True) from None
        statut = resultat.get("statut")
        if statut == "recu":
            rapport.recus_m1 += 1
        elif statut == "deja_recu":
            rapport.deja_recus_m1 += 1
        else:
            cle = str(resultat.get("code") or statut or "inconnu")[:48]
            rapport.refuses_m1[cle] = rapport.refuses_m1.get(cle, 0) + 1

    def _deposer(self, compte_id: str, membres: dict[str, bytes], rapport: RapportIngestion) -> list[tuple[str,
                                                                                                           list[str]]]:
        """Dépose les pièces dans la file d'onboarding ; rend `[(lot_id, [noms de membres])]`."""
        if not membres:
            return []
        groupes: list[list[str]] = [[]]
        octets = 0
        for nom in sorted(membres):
            plein = octets + len(membres[nom]) > ARCHIVE_OCTETS_MAX or len(groupes[-1]) >= ARCHIVE_MEMBRES_MAX
            if groupes[-1] and plein:
                groupes.append([])
                octets = 0
            groupes[-1].append(nom)
            octets += len(membres[nom])
        lots = []
        for groupe in groupes:
            archive = construire_archive([(nom, membres[nom]) for nom in groupe])
            nom_fichier = deposer_archive(archive, self._dossier)
            mutation = f"courriel:{compte_id[:20]}:{hashlib.sha256(archive).hexdigest()[:30]}"
            try:
                with self._fabrique() as cnx:
                    lot = ingestion.deposer(cnx, self._acteur, nom=nom_fichier, mutation_id=mutation,
                                            dossier=self._dossier)
            except IngestionErreur as exc:
                raise ErreurCourriel("REJ-COURRIEL-INGESTION-REFUSEE",
                                     f"la file d'onboarding a refusé le dépôt ({exc.code})", exc.statut_http,
                                     reprenable=exc.statut_http in {429, 507, 503}) from None
            rapport.lots.append(lot["lot_id"])
            lots.append((lot["lot_id"], groupe))
        return lots
