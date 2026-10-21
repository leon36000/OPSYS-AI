import type { AttenteDepartement } from "../approbations/contrat";
import { identifiantTransfertM1Valide } from "./contrat";

/** Même référence canonique pour À voir et les pages suivantes des attentes ; aucune fiche reconstruite. */
export function referenceTransfertM1(attente: Pick<AttenteDepartement, "departement" | "type" | "id">): string | null {
  return attente.departement === "m01-front-office" &&
    ["plainte_escaladee", "urgence_escaladee", "transfert_humain"].includes(attente.type) &&
    identifiantTransfertM1Valide(attente.id) ? attente.id : null;
}
