import { verifierDestinationClassementVariance } from "../m6/classementVariance";
import { lireChargeMateriauxAvecPreuves } from "../m6/materiauxAvecPreuves";
import * as SQLite from "expo-sqlite";

import { creerDeclencheurVidange } from "./declenchement";
import { DESCRIPTEURS_MUTATION } from "./descripteurs";
import { creerDepotOutboxSqlite, initialiserSchemaOutbox } from "./depot.sqlite";
import { avecProprietaire } from "./proprietaire";
import { creerVidangeur, type RapportVidange, type Vidangeur } from "./vidangeur";
import { invoquerOutil } from "../protocole/client";
import { capturerSessionLecture, capturerSessionMateriauxLecture, capturerSessionAdminLecture, obtenirSessionEnvoi } from "../protocole/configuration";
import type { DepotOutbox } from "./depot";

/**
 * Câblage RÉEL du vidangeur (SQLite + `fetch` + configuration de connexion) — le seul fichier de
 * `src/outbox` qui touche `expo-sqlite`/le réseau en dur, et donc, comme `depot.sqlite.ts`
 * lui-même, qualifié avec SQLite simulé dans Jest (pas de SQLite natif dans cet environnement — voir la
 * docstring de `depot.sqlite.ts`). La logique qu'il assemble (`creerVidangeur`,
 * `creerDepotOutboxSqlite`, `invoquerOutil`) est, elle, intégralement testée ailleurs.
 */

const NOM_BASE = "opsys-outbox.db";

let depotPromesse: Promise<DepotOutbox> | null = null;

/** Ouvre (une seule fois, mémoïsé) la base SQLite locale de la file sortante. Appelable depuis
 * n'importe quel écran qui doit créer/lire des mutations (`punch.tsx`, puis les tranches
 * suivantes) sans dupliquer l'ouverture de la base.
 *
 * Le dépôt rendu pose sur chaque mutation insérée la PERSONNE confirmée par le serveur (PLAN T1.4-l,
 * `avecProprietaire`) : c'est ce qui permet à la file de ne jamais envoyer la mutation d'une personne sous
 * l'identité d'une autre. Sans personne confirmée, l'insertion échoue (aucun écran de profil n'existe
 * alors). */
export function obtenirDepot(): Promise<DepotOutbox> {
  if (!depotPromesse) {
    depotPromesse = (async () => {
      const base = await SQLite.openDatabaseAsync(NOM_BASE);
      await initialiserSchemaOutbox(base);
      return avecProprietaire(creerDepotOutboxSqlite(base), () => obtenirSessionEnvoi()?.personne ?? null);
    })().catch((erreur: unknown) => {
      // Une ouverture qui échoue ne reste pas mémoïsée : la prochaine tentative rouvre la base.
      depotPromesse = null;
      throw erreur;
    });
  }
  return depotPromesse;
}

let vidangeurPromesse: Promise<Vidangeur> | null = null;

/**
 * Le vidangeur, construit UNE fois pour toute la vie de l'app (un seul verrou : jamais deux passes
 * concurrentes). Il ne garde AUCUN jeton : il lit la session courante (`obtenirSessionEnvoi`) avant chaque
 * envoi, donc un nouvel appairage est suivi sans redémarrer l'app (PLAN T1.4-l ; avant, le jeton du moment
 * de la construction était gardé pour toujours).
 */
function obtenirVidangeur(): Promise<Vidangeur> {
  if (!vidangeurPromesse) {
    vidangeurPromesse = (async () =>
      creerVidangeur({
        depot: await obtenirDepot(),
        descripteurs: DESCRIPTEURS_MUTATION,
        appelerOutil: invoquerOutil,
        fetchImpl: fetch,
        session: obtenirSessionEnvoi,
        capturerGardeSession: () => capturerSessionLecture().courante,
        maintenant: () => new Date(),
        verifierAvantEnvoi:async(mutation,session,courante)=>{
          if (mutation.type === "variance_cause_classification") {
            const admin = capturerSessionAdminLecture();
            return courante() && admin.courante() && admin.session !== null && admin.session.personne === session.personne &&
              admin.session.appareilId === session.appareilId && admin.session.urlBase === session.urlBase &&
              admin.session.jeton === session.jeton && verifierDestinationClassementVariance(mutation, session);
          }
          const gardeMateriaux=capturerSessionMateriauxLecture();const charge=lireChargeMateriauxAvecPreuves(mutation);if(!charge||!courante()||!gardeMateriaux.session||!gardeMateriaux.courante())return false;
          const verifier=()=>{const s=obtenirSessionEnvoi();return courante()&&gardeMateriaux.courante()&&s!==null&&s.urlBase===session.urlBase&&s.jeton===session.jeton&&s.personne===session.personne&&s.appareilId===session.appareilId;};
          if(!charge.fichiers.length)return verifier();
          const {envoyerFichiersPreuvesSelectionnes}=await import("../fichiers/service");if(!verifier())return false;
          const r=await envoyerFichiersPreuvesSelectionnes(mutation.chantierId,charge.fichiers,verifier);
          return verifier()&&r.length===charge.fichiers.length&&r.every((e,i)=>e.mutationId===charge.fichiers[i].capture_id&&e.sha256===charge.fichiers[i].empreinte_sha256&&e.resultat.pret);
        },
      }))().catch((erreur: unknown) => {
      vidangeurPromesse = null;
      throw erreur;
    });
  }
  return vidangeurPromesse;
}

/**
 * Déclenche une vidange best-effort. Renvoie `null` sans rien tenter tant qu'il n'y a pas de session pour
 * envoyer (pas d'appairage, ou personne pas encore confirmée pour le jeton courant — T1.4-l) — pas une
 * erreur, juste rien à faire pour l'instant : la file continue d'accumuler les mutations, prête à partir
 * dès que la session existera. Ne lève jamais pour une raison réseau/HTTP (déjà absorbée par la
 * classification de `src/protocole` et reflétée dans le `RapportVidange`/le statut de chaque mutation) ;
 * une erreur de couche stockage (SQLite) N'EST PAS avalée ici et remonte à l'appelant, qui décide comment
 * réagir (les déclencheurs d'arrière-plan de `declencheurs.ts` l'avalent, un appel explicite depuis un
 * écran peut choisir de la propager). Un refus de l'APPAREIL par le serveur arrête la passe et est signalé
 * à l'app (`refusAppareil.ts`) : voir `declenchement.ts`.
 */
export function declencherVidange(couranteExterne?: () => boolean): Promise<RapportVidange | null> {
  // Avant l'ouverture asynchrone SQLite : aucune capture partagée entre appels.
  const capture = capturerSessionLecture();
  const courante = () => capture.courante() && (couranteExterne?.() ?? true);
  return creerDeclencheurVidange({
    sessionDisponible: () => capture.session !== null && courante(),
    obtenirVidangeur: async () => {
      const singleton = await obtenirVidangeur();
      // Façade par appel, même vidangeur et même verrou pour tous les déclencheurs.
      return { vidangerFileSortante: () => singleton.vidangerFileSortante(courante) };
    },
  })();
}

/**
 * Une vidange lancée hors d'un écran (fin d'un appairage, redémarrage) : jamais attendue, jamais bloquante,
 * une panne est journalisée plutôt qu'avalée.
 */
export function vidangerEnArrierePlan(): void {
  declencherVidange().catch((erreur: unknown) => {
    // eslint-disable-next-line no-console
    console.error("opsys: échec de la vidange lancée en arrière-plan", erreur);
  });
}
