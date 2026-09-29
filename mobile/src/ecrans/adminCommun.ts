import type { ResultatSection } from "../admin/lecture";
import type { VerdictServeur } from "../outbox/vidangeur";
import { formaterDepuis } from "./approvals";
import { formaterMontant, formaterQuantite } from "./quotes";
import type { LangueMontant } from "./quotes";

/**
 * Ce que les trois écrans du profil admin (`(admin)/admin.tsx`, `chiffres.tsx`, `chantiers.tsx`, PLAN T4.20) ont en
 * commun. Logique PURE : les fichiers `.tsx` ne font que le câblage React, tout ce qui décide est ici, testé.
 *
 * **Un texte de l'app est une clé i18n, jamais une phrase en dur.** Les modèles de vue rendent des `Message`
 * (`{cle, params}`) que l'écran passe à `t(cle, params)` ; les textes fr-CA et en-CA vivent dans
 * `src/i18n/locales/*.ts`. Ce que le serveur écrit lui-même (le détail d'un manque, le résumé d'une attente, la
 * « lecture » de M5, la mention « Analyse préparatoire IA ») est montré tel quel, jamais réécrit ni traduit : c'est
 * lui qui fait foi. Un test (`messagesAdmin.test.ts`) passe chaque réponse réelle du moteur dans chaque modèle de vue et
 * vérifie que chaque clé produite existe dans les DEUX langues avec exactement les variables que son texte attend.
 *
 * **Aucun montant, pourcentage ni date n'est calculé ici** : un montant est un texte décimal du serveur mis en forme
 * sans jamais devenir un nombre (`formaterMontant`), une date est celle que le serveur a écrite, un instant est ramené
 * à l'heure de l'appareil (`formaterDepuis`), et un compte (jours, heures, minutes) est l'entier du serveur, tel quel.
 */

export type ParametresMessage = Readonly<Record<string, string | number>>;

export interface Message {
  readonly cle: string;
  readonly params?: ParametresMessage;
}

export function message(cle: string, params?: ParametresMessage): Message {
  return params === undefined ? { cle } : { cle, params };
}

/**
 * Le libellé d'une valeur qui vient d'un catalogue du serveur (`prefixe.valeur`) quand l'app la connaît ; sinon la
 * valeur telle quelle, DITE inconnue (une version plus récente du serveur peut en avoir ajouté : jamais un libellé
 * deviné, jamais une valeur cachée).
 */
export function libelleDeCatalogue(
  prefixe: string,
  valeur: string,
  connues: readonly string[],
  params?: ParametresMessage,
): Message {
  return connues.includes(valeur) ? message(`${prefixe}.${valeur}`, params) : message("admin.commun.inconnu", { valeur });
}

/** Le montant d'un texte décimal du serveur, mis en forme ; à défaut de pouvoir le mettre en forme, le texte tel quel. */
export function montantOuTexte(texte: string, langue: LangueMontant): string {
  return formaterMontant(texte, langue) ?? texte;
}

export function quantiteOuTexte(texte: string, langue: LangueMontant): string {
  return formaterQuantite(texte, langue) ?? texte;
}

export function montantNullable(texte: string | null, langue: LangueMontant): string | null {
  return texte === null ? null : montantOuTexte(texte, langue);
}

const DATE_SEULE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Une pièce ou un fait que le serveur date : un jour (`AAAA-MM-JJ`, gardé tel quel : un jour n'a pas de fuseau) ou un
 * instant (ramené à l'heure locale de l'appareil). Faire passer un jour par la conversion d'un instant le décalerait
 * d'une journée (minuit UTC est la veille au soir à Montréal).
 */
export function formaterDateOuInstant(texte: string, decalageMinutesUTC: number): string {
  return DATE_SEULE.test(texte) ? texte : formaterDepuis(texte, decalageMinutesUTC);
}

/** Un identifiant long (empreinte de 64 caractères) abrégé pour l'affichage ; l'identifiant entier reste celui qu'on envoie. */
export function abreger(identifiant: string): string {
  return identifiant.length > 12 ? `${identifiant.slice(0, 8)}…` : identifiant;
}

/**
 * Une section d'écran telle que l'écran la montre. Quatre issues, jamais confondues (`lireSection`) :
 *  - `contenu` : lue au serveur (`horsLigne` nul) ou, faute de serveur, dans le cache (`horsLigne` dit la date et la
 *    raison : ce n'est pas la lecture d'aujourd'hui) ;
 *  - `refus` : le serveur dit non ; son verdict est montré, et aucun cache ne le remplace ;
 *  - `aucune` : ni serveur ni cache ; jamais une valeur inventée, jamais un zéro.
 */
export type VueSection<C> =
  | {
      readonly genre: "contenu";
      readonly contenu: C;
      /** « Lue le … », à l'heure de l'appareil : quand la donnée a été lue (au serveur, ou pour le cache, ce jour-là). */
      readonly lue: Message;
      readonly horsLigne: Message | null;
    }
  | { readonly genre: "refus"; readonly avis: Message; readonly verdict: VerdictServeur }
  | { readonly genre: "aucune"; readonly avis: Message; readonly raison: VerdictServeur };

export function presenterSection<T, C>(
  resultat: ResultatSection<T>,
  decalageMinutesUTC: number,
  presenter: (valeur: T) => C,
): VueSection<C> {
  switch (resultat.source) {
    case "serveur":
      return {
        genre: "contenu",
        contenu: presenter(resultat.valeur),
        lue: message("admin.commun.lueLe", { date: formaterDepuis(resultat.misAJourLe, decalageMinutesUTC) }),
        horsLigne: null,
      };
    case "cache": {
      const date = formaterDepuis(resultat.misAJourLe, decalageMinutesUTC);
      return {
        genre: "contenu",
        contenu: presenter(resultat.valeur),
        lue: message("admin.commun.lueLe", { date }),
        horsLigne: message("admin.commun.cache", { date, code: resultat.raisonHorsLigne.code }),
      };
    }
    case "refus":
      return {
        genre: "refus",
        avis: message("admin.commun.refus", { code: resultat.verdict.code, detail: resultat.verdict.detail }),
        verdict: resultat.verdict,
      };
    case "aucune":
      return {
        genre: "aucune",
        avis: message("admin.commun.aucune", { code: resultat.raison.code, detail: resultat.raison.detail }),
        raison: resultat.raison,
      };
  }
}
