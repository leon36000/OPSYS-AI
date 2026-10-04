import { File } from "expo-file-system";
import * as Crypto from "expo-crypto";

import { candidatSignature, candidatsPhotosApres, preparerEnvoiFichier } from "./envoiOrchestrateur";
import type { ConfigurationEnvoiFichier, ResultatPreparationEnvoiFichier } from "./envoiOrchestrateur";
import { construireArgumentsEtatFichier, interpreterResultatEtatFichier } from "./protocole";
import type { ResultatEtatFichier } from "./protocole";
import type { FonctionDigestSha256 } from "./empreinte";
import { genererMutationId } from "../outbox/id";
import { obtenirDepot } from "../outbox/service";
import { invoquerOutil } from "../protocole/client";
import { obtenirConfigurationAppel } from "../protocole/configuration";
import type { MutationOutbox } from "../outbox/types";
import { obtenirSessionEnvoi } from "../protocole/configuration";

/**
 * Câblage RÉEL de l'envoi de fichier (`expo-file-system` pour la lecture des octets,
 * `expo-crypto` pour le hachage, `invoquerOutil` pour la lecture directe de `m4_etat_fichier`) —
 * non testé unitairement, même limite documentée que `src/photos/service.ts`/
 * `src/signature/service.ts`/`src/outbox/service.ts` (natif, pas de FS/réseau réel sous Jest).
 * La logique qu'il assemble (`preparerEnvoiFichier`) est, elle, intégralement testée avec un
 * lecteur de fichier et un transport factices (`envoiOrchestrateur.test.ts`).
 */
const digestSha256Expo: FonctionDigestSha256 = (octets) => Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, octets);

async function lireOctetsReel(uri: string): Promise<Uint8Array<ArrayBuffer>> {
  return new File(uri).bytes();
}

/** Lecture DIRECTE de `m4_etat_fichier` (pas par la file, comme `m4_statut_intervention` —
 * `src/today/statut.ts`) : `null` sans configuration de connexion (pas d'appairage) OU sur un
 * rejet métier — jamais bloquant pour l'appelant (`preparerEnvoiFichier` traite `null` comme
 * « aucune information de reprise disponible », voir sa docstring). */
async function obtenirEtatServeurReel(sha256: string): Promise<ResultatEtatFichier | null> {
  const configuration = obtenirConfigurationAppel();
  if (!configuration) {
    return null;
  }
  const resultatAppel = await invoquerOutil({
    fetchImpl: fetch,
    urlBase: configuration.urlBase,
    jeton: configuration.jeton,
    requete: { tool: "m4_etat_fichier", args: { ...construireArgumentsEtatFichier(sha256) }, deviceId: configuration.appareilId },
  });
  if (!resultatAppel.ok) {
    return null;
  }
  const interpretation = interpreterResultatEtatFichier(resultatAppel.result);
  return interpretation.accepte ? interpretation.resultat : null;
}

async function obtenirConfigurationEnvoi(): Promise<ConfigurationEnvoiFichier> {
  return {
    depot: await obtenirDepot(),
    lireOctets: lireOctetsReel,
    digest: digestSha256Expo,
    genererId: genererMutationId,
    horloge: { maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() },
    obtenirEtatServeur: obtenirEtatServeurReel,
  };
}

/**
 * Prépare/poursuit l'envoi de TOUS les fichiers candidats d'un chantier (photos « après » +
 * signature) — appelé par `complete.tsx` (mission item 2). Renvoie un résultat par fichier
 * candidat, dans le même ordre ; la liste des candidats vient de la file sortante RÉELLE
 * (`obtenirDepot`), toujours relue à cet instant (jamais mise en cache par ce module).
 */
export interface EnvoiFichierChantier {
  readonly mutationId: string;
  readonly sha256: string;
  readonly resultat: ResultatPreparationEnvoiFichier;
}

export async function envoyerFichiersDuChantier(chantierId: string): Promise<EnvoiFichierChantier[]> {
  const depot = await obtenirDepot();
  const mutations: MutationOutbox[] = await depot.lister();
  const session = obtenirSessionEnvoi();
  if (!session) return [];
  const signature = candidatSignature(mutations, chantierId, session.personne);
  const candidats = [...candidatsPhotosApres(mutations, chantierId, session.personne), ...(signature ? [signature] : [])];

  const config = await obtenirConfigurationEnvoi();
  const resultats: EnvoiFichierChantier[] = [];
  // Séquentiel, jamais Promise.all : même raison que src/outbox/vidangeur.ts — chaque tour relit
  // la file (mutationsExistantes) et l'état du dépôt reste cohérent d'un fichier au suivant.
  for (const candidat of candidats) {
    const enFile = await depot.lister();
    const resultat = await preparerEnvoiFichier(config, candidat, enFile);
    resultats.push({ mutationId: candidat.mutationId, sha256: candidat.sha256, resultat });
  }
  return resultats;
}
