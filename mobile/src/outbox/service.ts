import * as SQLite from "expo-sqlite";

import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerDepotOutboxSqlite, initialiserSchemaOutbox } from "./depot.sqlite";
import { creerVidangeur, type RapportVidange, type Vidangeur } from "./vidangeur";
import { invoquerOutil } from "../protocole/client";
import { obtenirConfigurationAppel } from "../protocole/configuration";
import type { DepotOutbox } from "./depot";

/**
 * Câblage RÉEL du vidangeur (SQLite + `fetch` + configuration de connexion) — le seul fichier de
 * `src/outbox` qui touche `expo-sqlite`/le réseau en dur, et donc, comme `depot.sqlite.ts`
 * lui-même, non exercé par les tests Jest (pas de SQLite natif dans cet environnement — voir la
 * docstring de `depot.sqlite.ts`). La logique qu'il assemble (`creerVidangeur`,
 * `creerDepotOutboxSqlite`, `invoquerOutil`) est, elle, intégralement testée ailleurs.
 */

const NOM_BASE = "opsys-outbox.db";

let depotPromesse: Promise<DepotOutbox> | null = null;

/** Ouvre (une seule fois, mémoïsé) la base SQLite locale de la file sortante. Appelable depuis
 * n'importe quel écran qui doit créer/lire des mutations (`punch.tsx`, puis les tranches
 * suivantes) sans dupliquer l'ouverture de la base. */
export function obtenirDepot(): Promise<DepotOutbox> {
  if (!depotPromesse) {
    depotPromesse = (async () => {
      const base = await SQLite.openDatabaseAsync(NOM_BASE);
      await initialiserSchemaOutbox(base);
      return creerDepotOutboxSqlite(base);
    })();
  }
  return depotPromesse;
}

let vidangeurCache: Vidangeur | null = null;

/** `null` tant qu'aucune configuration de connexion n'est disponible (pas d'appairage, T1.4-c) —
 * voir `src/protocole/configuration.ts`. Ce n'est PAS une erreur : la file continue
 * d'accumuler les mutations, prête à partir dès que la configuration existera. */
async function obtenirVidangeur(): Promise<Vidangeur | null> {
  const configuration = obtenirConfigurationAppel();
  if (!configuration) {
    return null;
  }
  if (!vidangeurCache) {
    const depot = await obtenirDepot();
    vidangeurCache = creerVidangeur({
      depot,
      descripteurs: DESCRIPTEURS_MUTATION,
      appelerOutil: invoquerOutil,
      fetchImpl: fetch,
      urlBase: configuration.urlBase,
      jeton: configuration.jeton,
      appareilId: configuration.appareilId,
      maintenant: () => new Date(),
    });
  }
  return vidangeurCache;
}

/**
 * Déclenche une vidange best-effort. Renvoie `null` sans rien tenter si aucune configuration de
 * connexion n'existe encore (voir `obtenirVidangeur`) — pas une erreur, juste rien à faire pour
 * l'instant. Ne lève jamais pour une raison réseau/HTTP (déjà absorbée par la classification de
 * `src/protocole` et reflétée dans le `RapportVidange`/le statut de chaque mutation) ; une
 * erreur de couche stockage (SQLite) N'EST PAS avalée ici et remonte à l'appelant, qui décide
 * comment réagir (les déclencheurs d'arrière-plan de `declencheurs.ts` l'avalent, un appel
 * explicite depuis un écran peut choisir de la propager).
 */
export async function declencherVidange(): Promise<RapportVidange | null> {
  const vidangeur = await obtenirVidangeur();
  if (!vidangeur) {
    return null;
  }
  return vidangeur.vidangerFileSortante();
}
