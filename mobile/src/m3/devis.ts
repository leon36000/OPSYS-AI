import { estObjet, lireEnveloppeMetier, texteOuNull, VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";
import type { VerdictServeur } from "../outbox/vidangeur";

/**
 * Contrat mobile de `m3_lire_devis` (`(seller)/quotes.tsx`, PLAN T4.8 ; DEFINITION-PRODUIT §9.4 « soumissions »,
 * « ne voit pas : coûts internes au-delà de sa soumission »).
 *
 * Lecture SEULE de `departments/m03-estimation/src/m3_estimation/outils.py` (`lire_devis`,
 * `_vue_projection_effective`, `_VUE_PAR_ROLE_APPAREIL`) et de `devis_durable.py` (`projeter_devis`, `LigneDevis`)
 * — jamais exécuté ici (ADR-0008).
 *
 * **CE QUE LE SERVEUR REND AU VENDEUR, et ce que l'app en garde.** M3 n'a que deux vues (`devis_durable._ROLES_CONNUS`) :
 * `interne` (coût, marge et prix) et `employe` (ni coût, ni marge, NI PRIX). Un appareil `seller` reçoit la vue
 * `interne` (`_VUE_PAR_ROLE_APPAREIL`) : la réponse porte `cout_unitaire`, `cout_ligne`, `cout_total` et
 * `taux_marge`. Il n'existe pas de troisième vue « le prix, sans le coût ni la marge » : le PLAN T4.8 la suppose
 * livrée par T2.3-d, elle ne l'est pas (le commentaire de `_VUE_PAR_ROLE_APPAREIL` le dit : « aucune troisième
 * vue »). GATE NATHAN : vue de devis du vendeur avec ou sans coût et marge.
 *
 * Tant que le serveur ne la fournit pas, l'app applique la règle DEUX FOIS (R12 §6, « vues par rôle : appliquées
 * deux fois, l'app ne rend pas non plus ces champs si un bug les laissait passer ») : `lireDevisVendeur` ne recopie
 * que les champs de la liste blanche ci-dessous (identité, statut, prix, lignes décrites), jamais un coût ni une
 * marge ; ce que ce module rend — donc ce que l'écran affiche et ce que le cache garde — n'en porte aucun. Ce
 * n'est PAS une protection contre un appareil compromis (la réponse a transité) : c'est la vue « par défaut » du
 * vendeur, et la donnée n'est ni affichée, ni gardée sur le téléphone. La vraie protection est une vue serveur.
 *
 * `role` n'est PAS envoyé : `role="employe"` retirerait aussi le prix, ce que le vendeur doit voir.
 *
 * **Rien d'inventé.** Un montant absent ou illisible est `null` (dit absent par l'écran) : l'app ne recalcule
 * aucun total, aucun prix, aucune taxe (« le code calcule », et c'est M3 qui calcule). Une ligne illisible rend
 * tout le devis illisible : un devis montré sans une de ses lignes tromperait devant le client.
 */

export const OUTIL_LIRE_DEVIS = "m3_lire_devis";

/** `devis_durable.STATUTS_DEVIS`. `envoye` n'est posé par aucun outil avant T4.7 ; l'app le lit quand il viendra. */
export const STATUTS_DEVIS: readonly string[] = ["brouillon", "envoye", "accepte"];

export interface LigneDevisVendeur {
  readonly referenceLigne: string;
  readonly description: string;
  /** Texte décimal tel que M3 le rend (« 30 », « 12.5 ») ; `null` : absent ou illisible. */
  readonly quantite: string | null;
  readonly unite: string | null;
  /** Texte décimal CAD (« 12.00 ») ; `null` : absent ou illisible. */
  readonly prixUnitaire: string | null;
  readonly prixLigne: string | null;
}

/** Ce que l'app connaît d'un devis : la liste blanche, et rien d'autre. */
export interface DevisVendeur {
  readonly devisId: string;
  readonly leadId: string;
  readonly chantierId: string | null;
  /** `brouillon`, `envoye` ou `accepte` ; toute autre valeur est gardée telle quelle et dite inconnue par l'écran. */
  readonly statut: string;
  readonly horodatage: string;
  readonly prixTotal: string | null;
  readonly lignes: readonly LigneDevisVendeur[];
}

export type InterpretationDevis =
  | { readonly ok: true; readonly devis: DevisVendeur }
  | { readonly ok: false; readonly genre: "refus" | "technique" | "illisible"; readonly verdict: VerdictServeur };

/** Args EXACTS de `m3_lire_devis` : le seul `devis_id`. Jamais `role` (il ne peut que restreindre, et
 * `employe` retire le prix) ni une personne. */
export function construireArgumentsLireDevis(devisId: string): { devis_id: string } {
  return { devis_id: devisId };
}

const DECIMAL = /^-?\d+(\.\d+)?$/;

function decimalOuNull(valeur: unknown): string | null {
  return typeof valeur === "string" && DECIMAL.test(valeur) ? valeur : null;
}

function lireLigne(brut: unknown): LigneDevisVendeur | null {
  if (!estObjet(brut)) {
    return null;
  }
  const referenceLigne = texteOuNull(brut.reference_ligne);
  const description = texteOuNull(brut.description);
  if (referenceLigne === null || description === null) {
    return null;
  }
  return {
    referenceLigne,
    description,
    quantite: decimalOuNull(brut.quantite),
    unite: texteOuNull(brut.unite),
    prixUnitaire: decimalOuNull(brut.prix_unitaire),
    prixLigne: decimalOuNull(brut.prix_ligne),
  };
}

/**
 * Lit `R` d'une réponse acceptée de `m3_lire_devis` en ne gardant que la liste blanche. `null` : le devis est
 * illisible (identité, statut ou horodatage absents, ligne illisible). Toute autre clé de la réponse — coût,
 * marge, taux, approbateur, type d'entrée — est ignorée ici, jamais copiée.
 */
export function lireDevisVendeur(valeur: unknown): DevisVendeur | null {
  if (!estObjet(valeur)) {
    return null;
  }
  const devisId = texteOuNull(valeur.devis_id);
  const leadId = texteOuNull(valeur.lead_id);
  const statut = texteOuNull(valeur.statut);
  const horodatage = texteOuNull(valeur.horodatage);
  if (devisId === null || leadId === null || statut === null || horodatage === null || !Array.isArray(valeur.lignes)) {
    return null;
  }
  const lignes = valeur.lignes.map(lireLigne);
  if (!lignes.every((l): l is LigneDevisVendeur => l !== null)) {
    return null;
  }
  return {
    devisId,
    leadId,
    chantierId: texteOuNull(valeur.chantier_id),
    statut,
    horodatage,
    prixTotal: decimalOuNull(valeur.prix_total),
    lignes,
  };
}

/** Interprète la réponse de `m3_lire_devis`. Le refus `REJ-DEVIS-INTROUVABLE` est le même pour un devis inconnu,
 * celui d'un autre vendeur et celui d'un lead sans propriétaire : rien ne dit à un vendeur quels devis existent. */
export function interpreterResultatLireDevis(resultatBrut: unknown): InterpretationDevis {
  const lecture = lireEnveloppeMetier(resultatBrut);
  if (!lecture.ok) {
    return lecture;
  }
  const devis = lireDevisVendeur(lecture.valeur);
  return devis === null ? { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE } : { ok: true, devis };
}

const CLES_DEVIS = ["devisId", "leadId", "chantierId", "statut", "horodatage", "prixTotal", "lignes"];
const CLES_LIGNE = ["referenceLigne", "description", "quantite", "unite", "prixUnitaire", "prixLigne"];

function memesCles(objet: Record<string, unknown>, attendues: readonly string[]): boolean {
  const cles = Object.keys(objet);
  return cles.length === attendues.length && attendues.every((cle) => cles.includes(cle));
}

function texteOuNullStrict(valeur: unknown): boolean {
  return valeur === null || typeof valeur === "string";
}

/**
 * Le cache relit un devis qu'il a lui-même écrit : STRICT. Une valeur qui porte une clé de plus (un coût, une
 * marge qu'une version d'avant ou un bug y aurait laissé) ou une clé de moins n'est pas un devis du vendeur :
 * elle est refusée, jamais affichée.
 */
export function estDevisVendeurValide(valeur: unknown): valeur is DevisVendeur {
  if (!estObjet(valeur) || !memesCles(valeur, CLES_DEVIS)) {
    return false;
  }
  const { devisId, leadId, chantierId, statut, horodatage, prixTotal, lignes } = valeur;
  return (
    typeof devisId === "string" &&
    typeof leadId === "string" &&
    texteOuNullStrict(chantierId) &&
    typeof statut === "string" &&
    typeof horodatage === "string" &&
    (prixTotal === null || decimalOuNull(prixTotal) !== null) &&
    Array.isArray(lignes) &&
    lignes.every(
      (ligne) =>
        estObjet(ligne) &&
        memesCles(ligne, CLES_LIGNE) &&
        typeof ligne.referenceLigne === "string" &&
        typeof ligne.description === "string" &&
        (ligne.quantite === null || decimalOuNull(ligne.quantite) !== null) &&
        texteOuNullStrict(ligne.unite) &&
        (ligne.prixUnitaire === null || decimalOuNull(ligne.prixUnitaire) !== null) &&
        (ligne.prixLigne === null || decimalOuNull(ligne.prixLigne) !== null),
    )
  );
}
