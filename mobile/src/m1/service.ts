import { capturerSessionAdminLecture } from "../protocole/configuration";
import { invoquerOutil } from "../protocole/client";
import { obtenirDepotLocal } from "../stockage/service";
import { creerChargeurLecturesTransferts } from "./lectures";

let enLigne = false;
/** L'écran transmet NetInfo ; aucune ouverture réseau par une lecture hors ligne. */
export function actualiserConnectiviteTransferts(connectee: boolean): void { enLigne = connectee; }
const lectures = creerChargeurLecturesTransferts({
  capturerSession: capturerSessionAdminLecture,
  appelerOutil: invoquerOutil,
  obtenirDepot: obtenirDepotLocal,
  fetchImpl: fetch,
  enLigne: () => enLigne,
  horloge: () => { const maintenant = new Date(); return { maintenant, decalageMinutesUTC: -maintenant.getTimezoneOffset() }; },
});
export const chargerDigestReception = lectures.chargerDigest;
export const chargerTransfertReception = lectures.chargerTransfert;
