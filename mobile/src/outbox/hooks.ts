import { useEffect, useState } from "react";

import { obtenirDepot } from "./service";
import { resumerQuarantaine, type ResumeQuarantaine } from "./proprietaire";
import { identiteDepuisEtat } from "../identite/etat";
import { useEtatIdentite } from "../roles/contexte";

/**
 * La quarantaine de la file sortante vue de la personne connectée (PLAN T1.4-l) : les envois en attente
 * qui appartiennent à quelqu'un d'autre. `null` : aucune (ou pas d'identité, ou lecture impossible : on
 * n'invente pas de chiffre). Relue à chaque changement de l'état de l'identité, c'est-à-dire après un
 * appairage, un retour au premier plan ou un retour du réseau (chacun relit l'identité). Le calcul est
 * `resumerQuarantaine` (pur, testé) ; ce hook ne fait que lire le dépôt.
 */
export function useQuarantaine(): ResumeQuarantaine | null {
  const etat = useEtatIdentite();
  const personne = identiteDepuisEtat(etat)?.personne ?? null;
  const [resume, definirResume] = useState<ResumeQuarantaine | null>(null);

  useEffect(() => {
    if (personne === null) {
      definirResume(null);
      return undefined;
    }
    let abandonne = false;
    void (async () => {
      try {
        const depot = await obtenirDepot();
        const resumeLu = resumerQuarantaine(await depot.lister(), personne);
        if (!abandonne) {
          definirResume(resumeLu.nombre > 0 ? resumeLu : null);
        }
      } catch (erreur) {
        // eslint-disable-next-line no-console
        console.error("opsys: quarantaine de la file sortante illisible", erreur);
        if (!abandonne) {
          definirResume(null);
        }
      }
    })();
    return () => {
      abandonne = true;
    };
  }, [etat, personne]);

  return resume;
}
