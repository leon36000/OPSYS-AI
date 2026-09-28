import type { DepotCleValeur } from "../stockage/depotCleValeur";
import type { ItemChecklist } from "./types";

/** Une clé par chantier (`src/stockage/depotCleValeur.ts`), versionnée comme `today/cache.ts`. */
function cleChecklist(chantierId: string): string {
  return `checklist_${chantierId}_v1`;
}

function estItemValide(valeur: unknown): valeur is ItemChecklist {
  return (
    typeof valeur === "object" &&
    valeur !== null &&
    typeof (valeur as { id?: unknown }).id === "string" &&
    typeof (valeur as { texte?: unknown }).texte === "string" &&
    typeof (valeur as { fait?: unknown }).fait === "boolean"
  );
}

/** Liste vide si rien n'est encore stocké, ou si la valeur stockée est corrompue/d'un format
 * inconnu — fail-closed (AGENTS.md), jamais une liste partielle ou devinée. */
export async function lireChecklist(depot: DepotCleValeur, chantierId: string): Promise<ItemChecklist[]> {
  const brut = await depot.lire(cleChecklist(chantierId));
  if (!brut) {
    return [];
  }
  try {
    const valeur: unknown = JSON.parse(brut);
    return Array.isArray(valeur) && valeur.every(estItemValide) ? valeur : [];
  } catch {
    return [];
  }
}

export async function ecrireChecklist(
  depot: DepotCleValeur,
  chantierId: string,
  items: readonly ItemChecklist[],
): Promise<void> {
  await depot.ecrire(cleChecklist(chantierId), JSON.stringify(items));
}
