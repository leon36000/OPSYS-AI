import type { ContextePointageM4 } from "./pointage";

/**
 * SEULE source, aujourd'hui, du `ContextePointageM4` (GPS, fenêtre de travail, référentiel de
 * villes, sel, identifiant d'appareil) que `m4_pointer` exige. Isolée dans ce fichier pour
 * qu'un remplacement futur (GPS consenti + `expo-location`, fenêtre/référentiel fournis par le
 * serveur, appareil issu d'une vraie session appairée) n'ait à toucher qu'ici — jamais
 * `src/m4/pointage.ts`, `src/outbox/vidangeur.ts` ni `app/(employee)/punch.tsx`.
 *
 * Pourquoi ces valeurs ne peuvent PAS encore être réelles (voir aussi `ContextePointageM4` et
 * MOBILE.md) :
 *  - `fixGps` : la capture GPS est hors périmètre de cette tranche — R12 §6, la lecture
 *    « fenêtre bornée = compatible Loi 25 » attend une confirmation Nathan/juriste, et
 *    `expo-location` n'est volontairement pas installé ;
 *  - `fenetreTravail`/`referentielVilles`/`ville`/`sel` : aucune route serveur ne les expose
 *    encore au mobile (pas de `today.tsx`, pas d'appairage T1.4-c) ;
 *  - `appareilId` : pas de jeton d'appareil scellé (T1.4-c) — identifiant de processus, PAS un
 *    identifiant d'appareil persistant (voir `genererAppareilIdProvisoire`).
 *
 * Ce n'est PAS une donnée métier inventée et présentée comme réelle (interdit, AGENTS.md) :
 * c'est un contexte de câblage, du même esprit que `attestation.fictif: true` que le serveur
 * LUI-MÊME impose aujourd'hui (« mode ombre uniquement », outils.py `_ATTESTATION`) — l'outil
 * entier n'est pas encore ouvert à de vraies données de production. Ce fichier documente
 * explicitement chaque champ plutôt que de le laisser deviner.
 */

/**
 * Fenêtre de travail couvrant toute une journée locale, ISO 8601 avec un décalage neutre
 * (`+00:00`) : suffisamment large pour qu'un pointage de démonstration ou de test tombe presque
 * toujours dedans, sans prétendre représenter un quart réel (aucune donnée de cédule n'existe
 * encore côté mobile).
 */
const FENETRE_LARGE = { debut: "2000-01-01T00:00:00+00:00", fin: "2999-12-31T23:59:59+00:00" } as const;

const SEL_PROVISOIRE = "provisoire-t1.4-d";
const VILLE_PROVISOIRE = "provisoire";
// Jeton de référentiel arbitraire mais STABLE (couplé à SEL_PROVISOIRE/VILLE_PROVISOIRE ci-
// dessus) : le serveur exige normalement `cedule.tokeniser_ville(sel, ville)`, fonction que ce
// client ne réimplémente pas (elle est encore à confirmer/exposer côté serveur) — un jeton fixe
// documente ce manque au lieu de le masquer derrière un calcul qui semblerait correct.
const JETON_REFERENTIEL_PROVISOIRE = "provisoire-t1.4-d";
const CENTRE_PROVISOIRE = { latitude: 0, longitude: 0, rayon_km: 20000 } as const; // couvre tout point valide (-90..90, -180..180) : aucune incohérence GPS artificielle tant que le vrai référentiel n'existe pas.

let appareilIdMemoise: string | null = null;

/**
 * Identifiant d'appareil PROVISOIRE : stable pour la durée du processus (mémoïsé), mais jamais
 * persisté — regénéré à chaque démarrage de l'app tant que `expo-secure-store` et l'appairage
 * (T1.4-c) ne fournissent pas la vraie identité scellée par le serveur. Sans persistance,
 * l'idempotence de bout en bout `(appareil, idempotencyKey)` ne peut être garantie d'une session
 * à l'autre — connu, documenté, et sans conséquence tant que T1.4-c n'a pas câblé la lecture de
 * ces champs côté serveur (`src/protocole/types.ts`, docstring de `deviceId`).
 */
export function genererAppareilIdProvisoire(genererId: () => string): string {
  if (appareilIdMemoise === null) {
    appareilIdMemoise = genererId();
  }
  return appareilIdMemoise;
}

export function obtenirContextePointageProvisoire(genererIdAppareil: () => string): ContextePointageM4 {
  return {
    fixGps: { latitude: CENTRE_PROVISOIRE.latitude, longitude: CENTRE_PROVISOIRE.longitude },
    appareilId: genererAppareilIdProvisoire(genererIdAppareil),
    fenetreTravail: FENETRE_LARGE,
    referentielVilles: { [JETON_REFERENTIEL_PROVISOIRE]: CENTRE_PROVISOIRE },
    ville: VILLE_PROVISOIRE,
    sel: SEL_PROVISOIRE,
  };
}
