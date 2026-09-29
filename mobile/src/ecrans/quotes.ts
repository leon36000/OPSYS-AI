import { STATUTS_DEVIS } from "../m3/devis";
import type { DevisVendeur } from "../m3/devis";
import type { VerdictServeur } from "../outbox/vidangeur";
import type { EntreeDevis, SourceDevis } from "../vendeur/chargeurDevis";
import type { OrigineDevis } from "../vendeur/devisConnus";

/**
 * Logique PURE de `(seller)/quotes.tsx` (PLAN T4.8) : ce que l'écran montre des devis du vendeur. Le fichier `.tsx`
 * ne fait que le câblage React ; tout ce qui décide est ici, testé (`quotes.test.ts`).
 *
 * **Le statut et le prix, jamais le coût ni la marge.** Les modèles reçus (`DevisVendeur`) n'en portent aucun : la
 * liste blanche de `src/m3/devis.ts` les a déjà retirés. Ce module n'a donc rien à cacher, et ne sait rien en calculer.
 *
 * **Aucun montant produit ici.** Un prix est un texte décimal que M3 a calculé ; l'écran le met en forme (séparateurs,
 * symbole) sans jamais le convertir en nombre, l'additionner ni l'arrondir. Un prix absent est dit absent.
 */

export type LangueMontant = "fr-CA" | "en-CA";

const ESPACE_INSECABLE = " ";
const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/;

/** Groupes de trois chiffres, de droite à gauche, sur des CHIFFRES (jamais un nombre : aucun flottant, aucune
 * perte de précision). */
function grouper(entier: string, separateur: string): string {
  const groupes: string[] = [];
  for (let fin = entier.length; fin > 0; fin -= 3) {
    groupes.unshift(entier.slice(Math.max(0, fin - 3), fin));
  }
  return groupes.join(separateur);
}

function formaterDecimal(texte: string, langue: LangueMontant): { signe: string; corps: string } | null {
  const trouve = DECIMAL.exec(texte);
  if (trouve === null) {
    return null;
  }
  const [, signe, entier, decimales] = trouve;
  const fr = langue === "fr-CA";
  const corps = grouper(entier, fr ? ESPACE_INSECABLE : ",") + (decimales === undefined ? "" : (fr ? "," : ".") + decimales);
  return { signe, corps };
}

/** Un montant en dollars canadiens, mis en forme SANS le convertir en nombre : « 1234.50 » -> « 1 234,50 $ » (fr-CA) ou
 * « $1,234.50 » (en-CA). `null` ou illisible : `null` (dit absent par l'écran), jamais 0 ni un texte inventé. */
export function formaterMontant(texte: string | null, langue: LangueMontant): string | null {
  if (texte === null) {
    return null;
  }
  const decimal = formaterDecimal(texte, langue);
  if (decimal === null) {
    return null;
  }
  return langue === "fr-CA"
    ? `${decimal.signe}${decimal.corps}${ESPACE_INSECABLE}$`
    : `${decimal.signe}$${decimal.corps}`;
}

/** Une quantité mise en forme comme un montant, sans symbole ; `null` : absente. */
export function formaterQuantite(texte: string | null, langue: LangueMontant): string | null {
  if (texte === null) {
    return null;
  }
  const decimal = formaterDecimal(texte, langue);
  return decimal === null ? null : `${decimal.signe}${decimal.corps}`;
}

export interface LigneDevisPresentee {
  readonly referenceLigne: string;
  readonly description: string;
  readonly quantite: string | null;
  readonly unite: string | null;
  readonly prixUnitaire: string | null;
  readonly prixLigne: string | null;
}

export interface CarteDevis {
  readonly devisId: string;
  /** Le lead du devis, tel que M3 le dit. */
  readonly leadId: string;
  readonly origine: OrigineDevis;
  readonly statut: string;
  /** `false` : un statut que ce code ne connaît pas (gardé tel quel, dit inconnu). */
  readonly statutConnu: boolean;
  readonly prixTotal: string | null;
  readonly lignes: readonly LigneDevisPresentee[];
  /** `null` : lu à l'instant. Sinon : lu dans le cache, avec sa date et pourquoi le serveur n'a pas été lu. */
  readonly cache: { readonly misAJourLe: string; readonly raison: VerdictServeur } | null;
  readonly misAJourLe: string;
}

export function presenterDevis(
  devis: DevisVendeur,
  origine: OrigineDevis,
  cache: CarteDevis["cache"],
  misAJourLe: string,
  langue: LangueMontant,
): CarteDevis {
  return {
    devisId: devis.devisId,
    leadId: devis.leadId,
    origine,
    statut: devis.statut,
    statutConnu: STATUTS_DEVIS.includes(devis.statut),
    prixTotal: formaterMontant(devis.prixTotal, langue),
    lignes: devis.lignes.map((ligne) => ({
      referenceLigne: ligne.referenceLigne,
      description: ligne.description,
      quantite: formaterQuantite(ligne.quantite, langue),
      unite: ligne.unite,
      prixUnitaire: formaterMontant(ligne.prixUnitaire, langue),
      prixLigne: formaterMontant(ligne.prixLigne, langue),
    })),
    cache,
    misAJourLe,
  };
}

export type VueEntreeDevis =
  | { readonly genre: "devis"; readonly carte: CarteDevis }
  /** Le serveur dit non : le même refus pour un devis inconnu et celui d'un autre vendeur. Son verdict, tel quel. */
  | { readonly genre: "refus"; readonly devisId: string; readonly verdict: VerdictServeur }
  /** Ni serveur ni cache pour ce devis. */
  | { readonly genre: "indisponible"; readonly devisId: string; readonly raison: VerdictServeur };

export function presenterEntree(entree: EntreeDevis, langue: LangueMontant): VueEntreeDevis {
  const { connu, etat } = entree;
  switch (etat.genre) {
    case "serveur":
      return { genre: "devis", carte: presenterDevis(etat.devis, connu.origine, null, etat.misAJourLe, langue) };
    case "cache":
      return {
        genre: "devis",
        carte: presenterDevis(
          etat.devis,
          connu.origine,
          { misAJourLe: etat.misAJourLe, raison: etat.raisonHorsLigne },
          etat.misAJourLe,
          langue,
        ),
      };
    case "refus":
      return { genre: "refus", devisId: connu.devisId, verdict: etat.verdict };
    case "indisponible":
      return { genre: "indisponible", devisId: connu.devisId, raison: etat.raison };
  }
}

/** Ce que la découverte des devis n'a pas pu dire, à montrer au-dessus de la liste : la liste ne doit jamais avoir
 * l'air complète quand elle ne l'est pas. */
export type AvisSourceDevis =
  /** M2 ne peut pas calculer ce segment (seuil à configurer...) : son « manque X », tel quel. */
  | { readonly genre: "non_calculable"; readonly segment: string; readonly manque: string }
  | { readonly genre: "echouee"; readonly segment: string; readonly verdict: VerdictServeur }
  /** La lecture des leads du segment n'est pas allée au bout : `reste` leads n'ont pas été lus. */
  | { readonly genre: "partielle"; readonly segment: string; readonly reste: number }
  | { readonly genre: "depuis_cache"; readonly segment: string; readonly raison: VerdictServeur };

export function avisDesSources(sources: readonly SourceDevis[]): readonly AvisSourceDevis[] {
  const avis: AvisSourceDevis[] = [];
  for (const { segment, etat } of sources) {
    if (etat.genre === "non_calculable") {
      avis.push({ genre: "non_calculable", segment, manque: etat.verdict.detail });
    } else if (etat.genre === "echouee") {
      avis.push({ genre: "echouee", segment, verdict: etat.verdict });
    } else {
      if (etat.depuisCache !== null) {
        avis.push({ genre: "depuis_cache", segment, raison: etat.depuisCache });
      }
      if (etat.reste > 0) {
        avis.push({ genre: "partielle", segment, reste: etat.reste });
      }
    }
  }
  return avis;
}
