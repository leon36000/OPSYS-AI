import { capturerSessionAdminLecture } from "../protocole/configuration";
import { invoquerOutil } from "../protocole/client";
import { obtenirDepotLocal } from "../stockage/service";
import { creerChargeurDispatch } from "./dispatchCourant";

let enLigne = false;
/** NetInfo est fourni par l'écran ; les lectures hors ligne n'ouvrent pas le transport. */
export function actualiserConnectiviteDispatch(connectee: boolean): void { enLigne = connectee; }
const lectures = creerChargeurDispatch({
  capturerSession: capturerSessionAdminLecture, obtenirDepot: obtenirDepotLocal,
  appelerOutil: invoquerOutil, fetchImpl: fetch, enLigne: () => enLigne,
  horloge: () => { const maintenant = new Date(); return { maintenant, decalageMinutesUTC: -maintenant.getTimezoneOffset() }; },
});
export const chargerPageDispatch = lectures.chargerPage;
export const chargerMeteoDispatch = lectures.chargerMeteo;
export const chargerRetardsDispatch = lectures.chargerRetards;
export const chargerDigestDispatch = lectures.chargerDigest;
export const chargerPreparationDispatch = lectures.chargerPreparation;
