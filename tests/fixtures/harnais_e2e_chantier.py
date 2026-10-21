"""Ce qui précède le geste de l'employé dans les tests E2E de T1.5 : un lead, un devis accepté, une
intervention planifiée et assignée, un matériel reçu. Fictif (`fictif: true`, AGENTS.md).

Ces étapes sont celles de l'amont (M2, M3, M4 cédule, M6 réception) : elles ne passent PAS par la porte
d'appareil, car aucune n'est un geste de l'app de l'employé (`m3_creer_devis` et `m4_planifier_intervention`
n'ont aucune portée d'appareil, docs/architecture/ROLES.md). Elles sont appelées comme le fait
`tests/test_cascade_travaux_termines.py` (T1.2-e) : le VRAI outil du VRAI manifeste, par
`opsys.outils.executer_atomique`. Ce qui est prouvé par la porte d'appareil commence à la première action
de l'employé.

Deux différences avec T1.2-e, voulues par T1.4-k1 et T1.5 : le technicien de la cédule EST l'identifiant
de la personne OPSYS (un appel d'appareil n'agit que sous son identifiant), et le prévu de matériaux vient
du devis accepté (`m3.devis_accepte`), que M6 consomme.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import hashlib
import struct
import zlib
from typing import Any

from harnais_e2e import DT_TZ, Reponse, iso
from m4_field_ops import cedule

from opsys.outils import executer_atomique

VILLE = "Repentigny"
MATERIAU_ID = "gouttiere-alu-5po-fictif"
QUANTITE_PREVUE = 40.0
SEL = "sel-t1-5-e2e-fictif"
# Position de l'employé sur le chantier, distincte du centre de référence de la ville : c'est la position qui
# ne doit jamais entrer en clair dans une trace, pas le référentiel public de la ville.
FIX_GPS = {"latitude": 45.740117, "longitude": -73.454833}
CENTRE_VILLE = {"latitude": 45.7392, "longitude": -73.4536}


@dataclasses.dataclass(frozen=True)
class Chantier:
    lead_id: str
    devis_id: str
    chantier_id: str
    intervention_id: str
    technicien: str  # identifiant de la personne OPSYS (T1.4-k1)
    debut: dt.datetime  # début de la journée de travail (heure locale)

    @property
    def fenetre(self) -> dict[str, str]:
        return {"debut": iso(self.debut), "fin": iso(self.debut, 12 * 3600)}

    @property
    def referentiel_villes(self) -> dict[str, Any]:
        return {cedule.tokeniser_ville(SEL, VILLE): {
            "latitude": CENTRE_VILLE["latitude"], "longitude": CENTRE_VILLE["longitude"], "rayon_km": 25.0}}


def _outils(deps: Any, dep_id: str) -> dict[str, Any]:
    return {o.nom: o for o in deps[dep_id].charger_outils()}


def _ok(reponse: dict[str, Any]) -> dict[str, Any]:
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse
    return reponse["resultat"]


def preparer_chantier(
    deps: Any, *, suffixe: str, technicien: str, debut: dt.datetime, version_lead: int = 1,
) -> Chantier:
    """Lead M2 qualifié -> devis M3 créé puis accepté (40 pi de gouttière prévus) -> intervention M4
    planifiée et assignée à `technicien`. Rien n'est encore arrivé sur le terrain.

    `version_lead` : 1 (LeadQualifie gelé, `type_travaux`) ou 2 (`schema_version` et `service` : le service
    « gouttieres » doit être déclaré au profil d'entreprise de l'instance, PLAN T0.13-b)."""
    m2, m3, m4 = (_outils(deps, d) for d in ("m02-revenue-crm", "m03-estimation", "m04-field-ops"))
    lead_id, devis_id = f"LEAD-{suffixe}-fictif", f"DEVIS-{suffixe}-fictif"
    chantier_id = f"CH-{suffixe}-fictif"
    contrat = {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100",
                    "courriel": f"{lead_id}@exemple-fictif.test"},
        "ville": VILLE, "urgence_declaree": False, "canal": "telephone",
    }
    if version_lead == 2:
        contrat.update({"schema_version": 2, "service": "gouttieres"})
    else:
        contrat["type_travaux"] = "renovation_totale"

    _ok(executer_atomique(m2["m2_ingerer_lead"], {"contrat": contrat, "horodatage": iso(debut, -86400)}))
    _ok(executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": iso(debut, -86340),
        "owner": "Alice Vendeuse (fictif)",
        "prochaine_action": {"description": "Planifier la visite technique (fictif)",
                             "echeance": iso(debut, -82800)},
    }))
    _ok(executer_atomique(m2["m2_enregistrer_interaction"], {
        "lead_id": lead_id, "auteur": "Alice Vendeuse (fictif)",
        "resume": "Appel de qualification effectué (fictif).", "horodatage": iso(debut, -86280)}))
    marqueur = _ok(executer_atomique(m2["m2_evaluer_readiness"], {
        "lead_id": lead_id, "horodatage": iso(debut, -86220)}))["resultat"]

    # Devis : 40 pi de gouttière (8,00 $/pi, marge 25 %) + main d'oeuvre forfaitaire (160,00 $) = 600,00 $
    # avant taxes ; TPS 30,00 $, TVQ 59,85 $, 689,85 $ après taxes (mêmes montants que T1.2-e).
    _ok(executer_atomique(m3["m3_creer_devis"], {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": chantier_id,
        "lignes": [
            {"description": "Gouttières 5po aluminium (fictif)", "quantite": "40", "unite": "pi",
             "cout_unitaire": "8.00", "reference_besoin_materiau": MATERIAU_ID},
            {"description": "Main d'oeuvre installation (fictif)", "quantite": "1", "unite": "forfait",
             "cout_unitaire": "160.00", "reference_besoin_materiau": None},
        ],
        "taux_marge": "0.25", "horodatage": iso(debut, -86160), "prix_total": "600.00"}))
    _ok(executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "converti", "horodatage": iso(debut, -86100),
        "reference_devis_m3": devis_id}))
    # T3 (frontière humaine) : l'acceptation du client est constatée par un humain ; sa décision signée est
    # prouvée par les tests de M3 et du socle. Ici, seule compte la cascade qui suit.
    _ok(executer_atomique(m3["m3_marquer_devis_accepte"], {
        "devis_id": devis_id, "approbateur": "Nathan Proprietaire (fictif, T3)", "horodatage": iso(debut, -86000)}))
    _ok(executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "cedule", "horodatage": iso(debut, -85900)}))

    plan = _ok(executer_atomique(m4["m4_planifier_intervention"], {
        "contrat": contrat, "marqueur": marqueur, "horodatage": iso(debut, -85800), "sel": SEL,
        "techniciens_disponibles": [technicien],
        "fenetres_disponibles": [{"debut": iso(debut), "fin": iso(debut, 12 * 3600)}],
        "devis_id": devis_id}))
    assert plan["assignation"] is not None and plan["assignation"]["technicien_id"] == technicien, plan
    _ok(executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": lead_id, "statut_cible": "chantier", "horodatage": iso(debut, -85700)}))
    return Chantier(lead_id, devis_id, chantier_id, plan["intervention_id"], technicien, debut)


def receptionner_materiel_args(chantier: Chantier, quantite: float = 200.0) -> dict[str, Any]:
    """Arguments de `m6_receptionner_commande` : le matériel arrive au chantier (réception complète). M6
    en tire le coût unitaire que la déclaration de matériaux utilisés exige (jamais un coût par défaut)."""
    po_id = f"PO-{chantier.devis_id}"
    veille = chantier.debut - dt.timedelta(days=1)
    return {
        "bon_demande": {
            "po_id": po_id, "chantier_id": chantier.chantier_id,
            "lignes_demandees": [{"materiau_id": MATERIAU_ID, "quantite_demandee": quantite}],
            "horodatage": iso(veille)},
        "reception_po": {
            "po_id": po_id, "chantier_id": chantier.chantier_id,
            "lignes_recues": [{"materiau_id": MATERIAU_ID, "quantite_recue": quantite}],
            "horodatage": iso(veille, 1800)},
        "catalogue_materiaux": {
            "version": "v1-fictif", "unite_monetaire": "CAD",
            "postes": {MATERIAU_ID: {"cout_unitaire": 8.0, "libelle": "Gouttière 5po alu (fictif)"}}},
    }


def debut_de_journee(jour: int) -> dt.datetime:
    return dt.datetime(2026, 9, jour, 7, 0, 0, tzinfo=DT_TZ)


# -- l'app de l'employé ------------------------------------------------------------------------------
def png_minimal(largeur: int = 1) -> bytes:
    """PNG RVB de `largeur` x 1 pixel, réel (signature, IHDR, IDAT, IEND, CRC32 corrects) :
    `m4_deposer_fichier` vérifie la taille, le SHA-256 et les octets magiques, un simple préfixe ne
    passerait pas (T1.4-e2). Deux largeurs donnent deux fichiers distincts (photo, signature)."""
    def bloc(etiquette: bytes, donnees: bytes) -> bytes:
        return struct.pack(">I", len(donnees)) + etiquette + donnees + struct.pack(
            ">I", zlib.crc32(etiquette + donnees))

    ligne = b"\x00" + b"\xff\xff\xff" * largeur
    return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, 1, 8, 2, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(ligne, 9)) + bloc(b"IEND", b""))


@dataclasses.dataclass(frozen=True)
class Appel:
    """Un appel de l'app tel qu'il est parti : de quoi le renvoyer à l'identique (même clé)."""

    outil: str
    args: dict[str, Any]
    cle: str
    horodatage_appareil: str
    reponse: Reponse


class AppEmploye:
    """Ce que fait l'app de l'employé, geste par geste, par la porte d'appareil (`PorteAppareil`).

    Chaque écriture porte une clé d'idempotence (le `mutation_id` de la file sortante) et l'heure de
    l'appareil, en retard de `derive_appareil_s` sur celle du serveur : l'heure d'un appareil peut
    dériver, seule l'heure de réception du serveur fait foi (R12 §4). L'horloge du moteur avance à la
    main, d'une durée choisie par le test.
    """

    def __init__(self, moteur: Any, porte: Any, chantier: Chantier, *, derive_appareil_s: int = -300) -> None:
        self.moteur = moteur
        self.porte = porte
        self.chantier = chantier
        self.derive_appareil_s = derive_appareil_s
        self.appels: list[Appel] = []
        self._n = 0

    # -- outillage ---------------------------------------------------------------------------------
    def maintenant(self) -> dt.datetime:
        return self.moteur.horloge.maintenant

    def heure_appareil(self) -> str:
        return iso(self.maintenant(), self.derive_appareil_s)

    def attendre(self, **duree: float) -> None:
        self.moteur.horloge.avancer(**duree)

    def _envoyer(self, outil: str, args: dict[str, Any]) -> Reponse:
        self._n += 1
        cle = f"mut-{self.chantier.lead_id}-{self._n:02d}"
        heure = self.heure_appareil()
        reponse = self.porte.appeler(outil, args, cle=cle, horodatage_appareil=heure)
        self.appels.append(Appel(outil, args, cle, heure, reponse))
        return reponse

    # -- les gestes ------------------------------------------------------------------------------------
    def chantiers_du_jour(self) -> Reponse:
        """Lecture (sans clé) : l'écran « chantier du jour »."""
        return self.porte.appeler("m4_lister_interventions", {})

    def statut(self) -> Reponse:
        return self.porte.appeler("m4_statut_intervention", {"intervention_id": self.chantier.intervention_id})

    def donner_consentement_gps(self) -> Reponse:
        return self._envoyer("m4_definir_consentement_gps", {
            "technicien_id": self.chantier.technicien, "action": "donne", "horodatage": self.heure_appareil(),
            "version_politique": "POLITIQUE-geolocalisation-v1-test",
            "preuve": {"fictif": True, "reference": "consentement-e2e-fictif"}})

    def en_route(self) -> Reponse:
        return self._envoyer("m4_demarrer_route", {
            "intervention_id": self.chantier.intervention_id, "technicien_id": self.chantier.technicien,
            "horodatage": self.heure_appareil()})

    def pointer(self, action: str) -> Reponse:
        return self._envoyer("m4_pointer", {
            "intervention_id": self.chantier.intervention_id, "technicien_id": self.chantier.technicien,
            "action": action, "horodatage": self.heure_appareil(), "fix_gps": FIX_GPS,
            "attestation": {"fictif": True, "appareil_id": self.porte.appareil_id},
            "fenetre_travail": self.chantier.fenetre, "referentiel_villes": self.chantier.referentiel_villes,
            "ville": VILLE, "sel": SEL})

    def deposer_fichier(self, contenu: bytes) -> str:
        """Un fichier en un seul bloc ; rend sa référence stable (`fichier:sha256:<hex>`)."""
        reponse = self._envoyer("m4_deposer_fichier", {
            "empreinte_sha256": hashlib.sha256(contenu).hexdigest(), "taille_octets": len(contenu),
            "type_mime": "image/png", "index_bloc": 0, "nombre_blocs": 1,
            "bloc_base64": base64.b64encode(contenu).decode("ascii")})
        resultat = reponse.resultat
        assert resultat["complet"] is True, resultat
        return resultat["reference"]

    def terminer(self, photo: str, signature: str) -> Reponse:
        return self._envoyer("m4_completer_intervention", {
            "intervention_id": self.chantier.intervention_id, "horodatage": self.heure_appareil(),
            "preuves_completion": {"checklist_complete": True, "photos_apres": [photo],
                                   "notes": "Installation terminée, aucun imprévu (fictif).",
                                   "signature": signature},
            "signature_requise": True})

    def declarer_materiaux(self, wct_id: str, quantite: float) -> Reponse:
        return self._envoyer("m6_declarer_materiaux_utilises", {
            "wct_id": wct_id, "formulaire": {
                "wct_id": wct_id, "intervention_id": self.chantier.intervention_id,
                "chantier_id": self.chantier.chantier_id,
                "lignes_materiaux": [{"type_ligne": "prevu", "materiau_id": MATERIAU_ID, "quantite": quantite,
                                      "unite": "pi", "quantite_estimee": QUANTITE_PREVUE}]}})

    def journee_jusqu_a_la_completion(self) -> Reponse:
        """De la maison au bouton « Terminer » : consentement, en route, arrivée, photo et signature
        déposées, départ, complétion. Rend la réponse de la complétion (elle porte le `wct_id`)."""
        assert self.chantiers_du_jour().resultat[0]["intervention_id"] == self.chantier.intervention_id
        self.attendre(minutes=1)
        assert self.donner_consentement_gps().metier["accepte"] is True
        self.attendre(minutes=29)
        assert self.en_route().metier["accepte"] is True
        self.attendre(minutes=30)
        assert self.pointer("arrivee").metier["accepte"] is True
        self.attendre(hours=2, minutes=55)
        photo = self.deposer_fichier(png_minimal(largeur=4))
        signature = self.deposer_fichier(png_minimal(largeur=2))
        self.attendre(minutes=5)
        assert self.pointer("depart").metier["accepte"] is True
        self.attendre(minutes=5)
        return self.terminer(photo, signature)

    # -- le rejeu ---------------------------------------------------------------------------------------
    def rejouer(self, appel: Appel) -> Reponse:
        """Renvoie l'appel à l'identique : même clé, mêmes arguments, même heure d'appareil."""
        return self.porte.appeler(appel.outil, appel.args, cle=appel.cle, horodatage_appareil=appel.horodatage_appareil)
