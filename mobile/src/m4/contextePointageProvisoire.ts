import type { ContextePointageM4 } from "./pointage";

/**
 * SEULE source, aujourd'hui, du `ContextePointageM4` (GPS, fenêtre de travail, référentiel de
 * villes, sel) que `m4_pointer` exige. Isolée dans ce fichier pour qu'un remplacement futur (GPS
 * consenti + `expo-location`, fenêtre/référentiel fournis par le serveur) n'ait à toucher qu'ici
 * — jamais `src/m4/pointage.ts`, `src/outbox/vidangeur.ts` ni les écrans appelants.
 *
 * PLAN T1.4-e (mission item 3) : `appareilId` N'EST PLUS généré ici. Avant cette tranche, ce
 * fichier mémoïsait son propre identifiant PAR PROCESSUS (`genererAppareilIdProvisoire`,
 * `expo-crypto` non persisté) — un second identifiant d'appareil, DIFFÉRENT de celui que
 * l'appairage (T1.4-c3, `src/appairage/identite.ts`) dérive de la clé publique Ed25519 et
 * persiste dans `expo-secure-store`. « Un seul identifiant d'appareil dans toute l'app » exige
 * de faire CONVERGER les deux : `appareilId` est maintenant un PARAMÈTRE explicite de
 * `obtenirContextePointageProvisoire`, que les écrans appelants (`punch.tsx`, `job/[id]/index.tsx`)
 * lisent tous depuis la MÊME source — `src/protocole/configuration.ts::obtenirConfigurationAppel()`
 * (`ConfigurationAppel.appareilId`, lui-même `SessionAppairee.appareilId` = `identite.deviceId`,
 * voir `src/appairage/client.ts:207` et `app/pairing/index.tsx`/`app/_layout.tsx`, qui l'écrivent
 * TOUJOURS ensemble avec la session de rôle). Fail-closed : un écran sans configuration de
 * connexion (aucun appairage réussi, ce qui ne devrait jamais arriver à l'intérieur du groupe
 * `(employee)`, gardé par `evaluerGarde`) doit refuser l'action plutôt que d'inventer un id — voir
 * les écrans appelants, jamais ce fichier (module pur, sans accès à la configuration).
 *
 * Pourquoi les AUTRES valeurs ne peuvent PAS encore être réelles (voir aussi `ContextePointageM4`
 * et MOBILE.md) :
 *  - `fixGps` : la capture GPS est hors périmètre de cette tranche — R12 §6, la lecture
 *    « fenêtre bornée = compatible Loi 25 » attend une confirmation Nathan/juriste, et
 *    `expo-location` n'est volontairement pas installé ;
 *  - `fenetreTravail`/`referentielVilles`/`ville`/`sel` : aucune route serveur ne les expose
 *    encore au mobile (`m4_lister_interventions`, lu pour cette tranche, T1.4-e, ne les porte pas
 *    — voir `src/m4/interventions.ts`) ;
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

/**
 * `appareilId` : identité RÉELLE de l'appareil (voir l'en-tête de fichier), fournie par
 * l'appelant — jamais générée ici. Fonction pure : aucun accès stockage/réseau, testable telle
 * quelle.
 */
export function obtenirContextePointageProvisoire(appareilId: string): ContextePointageM4 {
  return {
    fixGps: { latitude: CENTRE_PROVISOIRE.latitude, longitude: CENTRE_PROVISOIRE.longitude },
    appareilId,
    fenetreTravail: FENETRE_LARGE,
    referentielVilles: { [JETON_REFERENTIEL_PROVISOIRE]: CENTRE_PROVISOIRE },
    ville: VILLE_PROVISOIRE,
    sel: SEL_PROVISOIRE,
  };
}
