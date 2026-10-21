import { formaterHorodatageLocal } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";

/**
 * Le jour de l'appareil, `AAAA-MM-JJ`, tel que M5 (`aujourd_hui`) et M4 (`date_cible`) le demandent : ni M5 ni M4 n'ont
 * d'horloge, ils ne devinent jamais la date, et c'est l'appareil qui dit quel jour on est (même règle que `horodatage`
 * de `m2_lister_leads`). Ce n'est pas une date produite pour l'affichage : c'est l'argument d'une lecture, et le serveur
 * en tire ce qu'il en tire (jours restants, semaines). Un appareil qui falsifie son horloge ne change que sa propre vue.
 *
 * Le jour est celui de l'heure LOCALE de l'appareil : à 23 h 30 à Montréal (UTC-4), c'est encore le jour même, pas le
 * lendemain d'UTC.
 */
export function jourLocal(horloge: HorlogeAppareil): string {
  return formaterHorodatageLocal(horloge).slice(0, 10);
}

/** L'instant de référence local avec fuseau (`AAAA-MM-JJTHH:MM:SS-04:00`), pour `horodatage_reference` du digest de M4. */
export function instantLocal(horloge: HorlogeAppareil): string {
  return formaterHorodatageLocal(horloge);
}
