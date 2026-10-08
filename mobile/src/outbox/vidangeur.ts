import {
  marquerEchecPermanent,
  marquerEchecReessayable,
  marquerEnvoi,
  marquerEnvoyee,
  remettreEnAttenteSansFaute,
} from "./mutation";
import { identifierMutationsBloqueesParEchecPermanent, selectionnerProchainesEnvoyables } from "./planification";
import { identifierEnQuarantaine } from "./proprietaire";
import type { DepotOutbox } from "./depot";
import type { MutationOutbox, TypeMutation } from "./types";
import { estRefusAppareil } from "../protocole/classification";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";

/** Verdict serveur affichable (code + détail) — forme partagée par tout outil qui suit le
 * patron fail-closed `depuis_couple` (`src/opsys/outils.py`, IDEMPOTENCE.md §3.2), pas
 * seulement M4. Voir `src/m4/pointage.ts` pour la lecture spécifique à `m4_pointer`. */
export interface VerdictServeur {
  readonly code: string;
  readonly detail: string;
}

export type InterpretationResultatMetier =
  | { readonly accepte: true; readonly resume: unknown }
  | { readonly accepte: false; readonly verdict: VerdictServeur };

/**
 * Ce qu'un type de mutation doit fournir au vidangeur pour être envoyé : le nom de l'outil réel
 * (`/tools/invoke`, `tool`) et la lecture de sa réponse business (distincte du succès/échec HTTP,
 * déjà classé par `src/protocole/classification.ts` — voir la docstring de
 * `interpreterResultatPointage`, `src/m4/pointage.ts`, pour le pourquoi ce second niveau est
 * nécessaire). Enregistré par type dans `src/outbox/descripteurs.ts`.
 */
export interface DescripteurTypeMutation {
  readonly tool: string;
  readonly interpreterResultat: (resultatBrut: unknown, mutation?: MutationOutbox) => InterpretationResultatMetier;
  /** Projection RPC pour les types portant aussi une preuve locale persistée. null : aucun envoi deviné. */
  readonly construireArguments?: (mutation: MutationOutbox) => Readonly<Record<string, unknown>> | null;
  /** Une intention non terminale du groupe bloque les suivantes, même en recul/quarantaine. */
  readonly serialiserParChantier?: boolean;
  /** Un statut envoyé ne libère la série que si son reçu durable est lié à cette intention. */
  readonly validerRecuEnvoye?: (mutation: MutationOutbox) => boolean;
}

export interface ConfigurationVidangeur {
  readonly depot: DepotOutbox;
  readonly descripteurs: ReadonlyMap<TypeMutation, DescripteurTypeMutation>;
  /** Injecté (mission item 5 déjà appliquée par src/protocole/client.ts) : dans les tests, un
   * faux transport ; en production, `invoquerOutil` de src/protocole/client.ts. */
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  /**
   * Où envoyer, avec quel jeton et pour quelle personne (PLAN T1.4-l) — LU AVANT CHAQUE ENVOI, jamais
   * gardé d'une passe à l'autre : un nouvel appairage change le jeton, et la file doit suivre sans
   * redémarrage. `null` : rien ne part (pas apparié, ou personne pas encore confirmée pour le jeton
   * courant). En production, `obtenirSessionEnvoi` de `src/protocole/configuration.ts` ; dans les tests,
   * une fonction qui rend le jeton voulu. `appareilId` de la session = `opsys/appareil` / `deviceId`
   * (src/protocole/types.ts). Une mutation ne part que si `session.personne` est SON propriétaire.
   */
  readonly session: () => SessionEnvoi | null;
  /** Capture par passe avant stockage ; rôle/URL/génération sont revalidés avant chaque RPC. */
  readonly capturerGardeSession?: () => () => boolean;
  /** Injecté plutôt que lu via `Date.now()` (fonction pure, même principe que `recul.ts` et
   * `selectionnerProchainesEnvoyables`). */
  readonly maintenant: () => Date;
}

/** Un échec permanent, avec le verdict à afficher à l'employé (mission item 2 : « échec
 * définitif avec le verdict du serveur ») — qu'il vienne du classement HTTP
 * (`src/protocole/classification.ts`, ex. 400/403/404) ou d'un rejet business à HTTP 200
 * (`accepte:false`, voir `src/m4/pointage.ts`) : les DEUX sources sont normalisées vers la même
 * forme `{code, detail}` ici, pour que l'écran n'ait qu'une seule forme à afficher. */
export interface EchecMutation {
  readonly id: string;
  readonly verdict: VerdictServeur;
}

/** Une mutation acceptée, avec le `resume` métier renvoyé par son interprète (PLAN T1.4-f,
 * `RapportVidange.resultatsAcceptes` ci-dessous) — `resume` reste `unknown` à ce niveau
 * générique (le vidangeur ne connaît aucun contrat M4/M6 précis, voir `DescripteurTypeMutation`
 * ci-dessus) ; l'appelant (écran) le retype selon le type de mutation qu'il a lui-même soumis. */
export interface MutationAcceptee {
  readonly id: string;
  readonly resume: unknown;
}

/**
 * Pourquoi une passe s'est arrêtée avant la fin de la file (PLAN T1.4-l). Aucune de ces raisons n'est
 * un échec de mutation : la mutation en cours est remise `en_attente`, intacte (ni tentative comptée, ni
 * recul, même `id`), et le reste de la file n'est pas touché.
 */
export type ArretVidange =
  /** Rien à envoyer avec : pas apparié, ou la personne n'est pas confirmée pour le jeton courant. */
  | { readonly genre: "sans_session" }
  /** Le jeton ou la personne ont changé pendant la passe (nouvel appairage) : la suivante repart avec la
   * session courante. Le refus d'un ANCIEN jeton, qui arrive après ce changement, n'est pas un refus
   * d'appareil : il tombe ici. */
  | { readonly genre: "session_changee" }
  /**
   * Le serveur refuse l'APPAREIL (401 jeton révoqué ; 403 `device_unknown`/`role_unknown`, voir
   * `estRefusAppareil`) : rien d'autre ne passerait, la passe s'arrête tout de suite — jamais une boucle
   * de réessais, jamais un `echec_permanent` fabriqué pour une mutation qui n'a rien de faux. L'app relit
   * alors l'identité, ce qui la renvoie à l'écran d'identité ou d'appairage.
   */
  | {
      readonly genre: "appareil_refuse";
      readonly mutationId: string;
      readonly status: number | null;
      readonly message: string;
    };

export interface RapportVidange {
  readonly envoyees: readonly string[];
  /**
   * Même information que `envoyees`, mais avec le `resume` métier de CHAQUE mutation acceptée
   * (PLAN T1.4-f) — jusqu'ici calculé par `descripteur.interpreterResultat` puis jeté : `job_
   * completion` (« Terminer ») a besoin du `wct_id` de l'accusé renvoyé par
   * `m4_completer_intervention` pour enchaîner `materials_submit` (`m6_declarer_materiaux_utilises`
   * prend ce `wct_id` et relit lui-même le WCT publié, voir `src/m4/completion.ts`/
   * `src/m6/materiaux.ts`) — sans ce champ, le seul moyen de le retrouver aurait été un second
   * appel réseau, inutile ET plus fragile. Additif, ne change rien au comportement existant :
   * `envoyees` reste inchangé pour tout code déjà écrit contre lui.
   */
  readonly resultatsAcceptes: readonly MutationAcceptee[];
  /** Remises `en_attente` après un échec réessayable (recul appliqué). */
  readonly remisesEnAttente: readonly string[];
  readonly echecsPermanents: readonly EchecMutation[];
  /** Dépendances d'échec permanent et intentions bloquées par une série de groupe, recalculées dans cette passe (R12 §4 : « ne
   * jamais perdre silencieusement un événement mis en file ») — pour affichage/alerte, jamais
   * utilisé pour décider quoi que ce soit ici (la sélection l'exclut déjà correctement). */
  readonly bloquees: readonly string[];
  /**
   * La QUARANTAINE (PLAN T1.4-l), calculée après la passe : les mutations qui attendent un envoi mais
   * n'appartiennent pas à la personne de la session courante (autre personne, ou propriétaire inconnu).
   * Elles ne partent jamais sous cette identité et ne sont jamais supprimées ; l'app les compte et les
   * montre. Voir `src/outbox/proprietaire.ts`.
   */
  readonly quarantaine: readonly string[];
  /** Pourquoi la passe s'est arrêtée avant la fin de la file ; `null` : elle est allée au bout. */
  readonly arret: ArretVidange | null;
  /** `true` quand cet appel n'a rien fait car une vidange était déjà en cours (verrou simple,
   * mission item 1) — PAS une erreur : le prochain déclencheur (premier plan, retour réseau)
   * reprendra ce qui reste en file. */
  readonly ignoreeVerrouActif: boolean;
}

const RAPPORT_VERROU_ACTIF: RapportVidange = {
  envoyees: [],
  resultatsAcceptes: [],
  remisesEnAttente: [],
  echecsPermanents: [],
  bloquees: [],
  quarantaine: [],
  arret: null,
  ignoreeVerrouActif: true,
};

const RAPPORT_SANS_SESSION: RapportVidange = {
  envoyees: [],
  resultatsAcceptes: [],
  remisesEnAttente: [],
  echecsPermanents: [],
  bloquees: [],
  quarantaine: [],
  arret: { genre: "sans_session" },
  ignoreeVerrouActif: false,
};

export interface Vidangeur {
  /** Vide la file sortante une fois : sélectionne les mutations envoyables (avec `maintenant`
   * injecté), les envoie dans l'ordre chantier/sequence, et transitionne chacune selon la
   * classification (réseau/HTTP puis, si l'appel a réussi, le verdict business). Ne démarre
   * JAMAIS une deuxième passe concurrente (verrou simple) : voir `RapportVidange.ignoreeVerrouActif`.
   */
  vidangerFileSortante(courante?: () => boolean): Promise<RapportVidange>;
}

type IssueEnvoi =
  | { readonly genre: "envoyee"; readonly resume: unknown }
  | { readonly genre: "remise_en_attente" }
  | { readonly genre: "echec_permanent"; readonly verdict: VerdictServeur }
  | { readonly genre: "bloquee_serie" }
  | { readonly genre: "arret"; readonly arret: ArretVidange };

/** Politique optionnelle : une intention inconnue/en recul/quarantaine n'est jamais contournée.
 * Les champs d'ordre viennent du dépôt. Une série sans ordre sûr reste fermée. */
function terminaliteVerifiee(mutation: MutationOutbox, descripteur?: DescripteurTypeMutation): boolean {
  return mutation.statut === "echec_permanent" || (mutation.statut === "envoyee" &&
    (!descripteur?.validerRecuEnvoye || descripteur.validerRecuEnvoye(mutation) === true));
}

function premiereIntentionDuGroupe(mutation: MutationOutbox, toutes: readonly MutationOutbox[], descripteur: DescripteurTypeMutation): boolean {
  const serie = toutes.filter(m => m.type === mutation.type && m.chantierId === mutation.chantierId &&
    !terminaliteVerifiee(m, descripteur));
  if (serie.some(m => m.sequence === null || !Number.isSafeInteger(m.sequence) || m.sequence < 1)) return false;
  if (new Set(serie.map(m => m.sequence)).size !== serie.length) return false;
  const premiere = serie.slice().sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0))[0];
  return premiere?.id === mutation.id && premiere.proprietaire === mutation.proprietaire;
}

/** Le refus d'un jeton n'est un refus d'APPAREIL que si ce jeton est encore celui de la session : un
 * refus qui arrive après un nouvel appairage vise l'ancien jeton, pas l'appareil tel qu'il est maintenant. */
function memeSession(a: SessionEnvoi, b: SessionEnvoi | null): boolean {
  return b !== null && a.jeton === b.jeton && a.appareilId === b.appareilId && a.personne === b.personne;
}

/** Normalise un échec HTTP/réseau (classification.ts) vers la même forme `{code, detail}`
 * qu'un rejet business — ni l'un ni l'autre n'est privilégié, l'écran affiche l'un ou l'autre
 * de façon identique (voir `EchecMutation`). */
function verdictDepuisEchecHttp(echec: { readonly message: string; readonly erreur?: { readonly type: string; readonly message: string } }): VerdictServeur {
  if (echec.erreur) {
    return { code: echec.erreur.type, detail: echec.erreur.message };
  }
  return { code: "erreur_reseau", detail: echec.message };
}

/**
 * Le « vidangeur » (R12 §4, PLAN T1.4-d item 1) : relie `src/outbox` (logique de file, déjà
 * pure et testée) à `src/protocole` (client `/tools/invoke`, déjà pur et testé) — le seul
 * branchement qui manquait encore (MOBILE.md, « pas de boucle de vidage reliant src/outbox à
 * src/protocole »). Cette fonction elle-même reste pure côté ORCHESTRATION (aucune horloge ni
 * accès réseau en dur, tout est injecté par `ConfigurationVidangeur`) ; c'est l'adaptateur —
 * `src/outbox/service.ts` fournit la configuration réelle (SQLite, `fetch`, déclencheurs).
 */
export function creerVidangeur(config: ConfigurationVidangeur): Vidangeur {
  let vidangeEnCours = false;

  async function arreterGardeSession(mutation: MutationOutbox): Promise<IssueEnvoi> {
    // Le reçu peut avoir été persisté pendant une attente précédente : jamais le rouvrir.
    const actuelle = await config.depot.obtenir(mutation.id);
    if (actuelle?.statut === "envoi" && actuelle.proprietaire === mutation.proprietaire) {
      await config.depot.mettreAJour(remettreEnAttenteSansFaute(actuelle));
    }
    return { genre: "arret", arret: { genre: "session_changee" } };
  }

  async function envoyerUneMutation(mutation: MutationOutbox, courante: () => boolean): Promise<IssueEnvoi> {
    const descripteur = config.descripteurs.get(mutation.type);
    if (descripteur?.serialiserParChantier) {
      const actuelles = await config.depot.lister();
      const courante = actuelles.find(m => m.id === mutation.id);
      if (!courante || !premiereIntentionDuGroupe(mutation, actuelles, descripteur) ||
        (courante.statut !== "en_attente" && courante.statut !== "envoi")) return { genre: "bloquee_serie" };
      mutation = courante;
    }
    // Reprise (statut déjà `envoi` retrouvé au démarrage) : ne PAS transitionner à nouveau —
    // `envoi -> envoi` n'existe pas dans le graphe (transitions.ts) — et surtout renvoyer avec
    // LA MÊME mutation (donc la même `id` = idempotencyKey), jamais en la recréant (R12 §4).
    const enEnvoi = mutation.statut === "envoi" ? mutation : marquerEnvoi(mutation);
    if (enEnvoi !== mutation) {
      await config.depot.mettreAJour(enEnvoi);
    }
    if (!descripteur) throw new Error(`aucun descripteur enregistré pour le type de mutation « ${mutation.type} »`);

    if (descripteur.serialiserParChantier) {
      const actuelles = await config.depot.lister();
      const courante = actuelles.find(m => m.id === mutation.id);
      // Une réception concurrente déjà durable est terminale : jamais rouvrir/écraser son reçu.
      if (!courante || courante.statut === "envoyee" || courante.statut === "echec_permanent") return { genre: "bloquee_serie" };
      if (!premiereIntentionDuGroupe(enEnvoi, actuelles, descripteur)) {
        if (courante.statut === "envoi" && courante.proprietaire === enEnvoi.proprietaire) {
          await config.depot.mettreAJour(remettreEnAttenteSansFaute(courante));
        }
        return { genre: "bloquee_serie" };
      }
    }
    if (!courante()) {
      return arreterGardeSession(enEnvoi);
    }
    const argumentsRpc = descripteur.construireArguments ? descripteur.construireArguments(enEnvoi) : { ...mutation.payload };
    if (argumentsRpc === null) {
      await config.depot.mettreAJour(marquerEchecReessayable(enEnvoi, config.maintenant()));
      return { genre: "remise_en_attente" };
    }

    // La session est lue AU DERNIER MOMENT, juste avant l'appel : le jeton envoyé est le jeton courant, et
    // il est confirmé pour la personne de CETTE mutation. Le jeton et la personne viennent du même
    // instantané, jamais de deux lectures : la mutation d'une personne ne part jamais avec le jeton d'une
    // autre. Si la session a changé depuis la sélection, la mutation redevient `en_attente`, intacte.
    const session = config.session();
    if (!courante()) return arreterGardeSession(enEnvoi);
    if (session === null || session.personne !== mutation.proprietaire) {
      await config.depot.mettreAJour(remettreEnAttenteSansFaute(enEnvoi));
      return { genre: "arret", arret: { genre: "session_changee" } };
    }

    const resultatAppel = await config.appelerOutil({
      fetchImpl: config.fetchImpl,
      urlBase: session.urlBase,
      jeton: session.jeton,
      requete: {
        tool: descripteur.tool,
        args: { ...argumentsRpc },
        idempotencyKey: mutation.id,
        deviceId: session.appareilId,
        deviceTimestamp: mutation.createdAtLocal,
      },
    });

    if (!resultatAppel.ok) {
      if (estRefusAppareil(resultatAppel.echec)) {
        // Ce n'est pas la faute de la mutation : elle reste intacte, en file, et repartira avec la même
        // `id` quand une session valide existera. Rien ne passerait derrière elle : la passe s'arrête.
        await config.depot.mettreAJour(remettreEnAttenteSansFaute(enEnvoi));
        if (!memeSession(session, config.session())) {
          return { genre: "arret", arret: { genre: "session_changee" } };
        }
        return {
          genre: "arret",
          arret: {
            genre: "appareil_refuse",
            mutationId: mutation.id,
            status: resultatAppel.echec.status ?? null,
            message: verdictDepuisEchecHttp(resultatAppel.echec).detail,
          },
        };
      }
      if (resultatAppel.echec.reessayable) {
        await config.depot.mettreAJour(marquerEchecReessayable(enEnvoi, config.maintenant()));
        return { genre: "remise_en_attente" };
      }
      await config.depot.mettreAJour(marquerEchecPermanent(enEnvoi));
      return { genre: "echec_permanent", verdict: verdictDepuisEchecHttp(resultatAppel.echec) };
    }

    const interpretation = descripteur.interpreterResultat(resultatAppel.result, enEnvoi);
    if (interpretation.accepte) {
      await config.depot.mettreAJour(marquerEnvoyee(enEnvoi, interpretation.resume));
      return { genre: "envoyee", resume: interpretation.resume };
    }
    if (interpretation.verdict.code === "accuse_invalide") {
      // Réponse incompatible après un effet serveur possible : conserver la même clé et réessayer
      // avec recul, l'idempotence serveur empêchera un doublon si le premier appel a abouti.
      await config.depot.mettreAJour(marquerEchecReessayable(enEnvoi, config.maintenant()));
      return { genre: "remise_en_attente" };
    }
    // Rejet métier (HTTP 200, mais `accepte: false`) : définitif — réessayer le MÊME payload ne
    // changerait pas l'issue (fenêtre dépassée, contrat mal formé…). R12 §4 : jamais perdu
    // silencieusement, voir RapportVidange.bloquees pour les descendants.
    await config.depot.mettreAJour(marquerEchecPermanent(enEnvoi));
    return { genre: "echec_permanent", verdict: interpretation.verdict };
  }

  async function vidangerUneFois(courante: () => boolean): Promise<RapportVidange> {
    if (!courante()) return { ...RAPPORT_SANS_SESSION, arret: { genre: "session_changee" } };
    const sessionDebut = config.session();
    if (sessionDebut === null) {
      return RAPPORT_SANS_SESSION;
    }

    const toutes = await config.depot.lister();
    // La sélection regarde TOUTE la file (l'ordre et les parents `dependsOn` n'ont de sens que sur
    // l'ensemble) ; seules les mutations de la personne de la session partent. Les autres attendent :
    // c'est la quarantaine, comptée plus bas.
    const envoyables = selectionnerProchainesEnvoyables(toutes, config.maintenant()).filter(
      (m) => m.proprietaire === sessionDebut.personne,
    );

    const envoyees: string[] = [];
    const resultatsAcceptes: MutationAcceptee[] = [];
    const remisesEnAttente: string[] = [];
    const echecsPermanents: EchecMutation[] = [];
    const bloqueesSerie = new Set<string>();
    const seriesTraitees = new Set<string>();
    let arret: ArretVidange | null = null;

    // Séquentiel, jamais Promise.all : l'ordre chantier/sequence de selectionnerProchainesEnvoyables
    // n'a de sens que si les envois se succèdent, et deux appels concurrents pour la MÊME mutation
    // (reprise) briseraient le verrou simple visé par la mission.
    for (const mutation of envoyables) {
      if (!courante()) {
        arret = { genre: "session_changee" };
        break;
      }
      const enSerie = config.descripteurs.get(mutation.type)?.serialiserParChantier === true;
      const cleSerie = JSON.stringify([mutation.type, mutation.chantierId]);
      if (enSerie && seriesTraitees.has(cleSerie)) {
        bloqueesSerie.add(mutation.id);
        continue;
      }
      const issue = await envoyerUneMutation(mutation, courante);
      if (enSerie && issue.genre !== "bloquee_serie") seriesTraitees.add(cleSerie);
      if (issue.genre === "arret") {
        arret = issue.arret;
        break;
      }
      if (issue.genre === "bloquee_serie") {
        bloqueesSerie.add(mutation.id);
      } else if (issue.genre === "envoyee") {
        envoyees.push(mutation.id);
        resultatsAcceptes.push({ id: mutation.id, resume: issue.resume });
      } else if (issue.genre === "remise_en_attente") {
        remisesEnAttente.push(mutation.id);
      } else {
        echecsPermanents.push({ id: mutation.id, verdict: issue.verdict });
      }
    }

    const toutesApres = await config.depot.lister();
    const serieEncoreBloquee = [...bloqueesSerie].filter(id => toutesApres.some(m => m.id === id &&
      !terminaliteVerifiee(m, config.descripteurs.get(m.type))));
    const bloquees = [...new Set([...identifierMutationsBloqueesParEchecPermanent(toutesApres).map(m => m.id), ...serieEncoreBloquee])];
    const personneFin = config.session()?.personne ?? sessionDebut.personne;
    const quarantaine = identifierEnQuarantaine(toutesApres, personneFin).map((m) => m.id);

    return {
      envoyees,
      resultatsAcceptes,
      remisesEnAttente,
      echecsPermanents,
      bloquees,
      quarantaine,
      arret,
      ignoreeVerrouActif: false,
    };
  }

  return {
    async vidangerFileSortante(couranteExterne?: () => boolean): Promise<RapportVidange> {
      if (vidangeEnCours) {
        // Verrou simple (mission item 1) : jamais deux vidanges concurrentes. On ne bloque PAS
        // l'appelant derrière celle déjà en cours — un déclencheur (premier plan, retour réseau)
        // qui arrive pendant une vidange active est absorbé, pas empilé ; le prochain déclencheur
        // reprendra ce qu'il reste à envoyer (rien n'est perdu, tout reste en file).
        return RAPPORT_VERROU_ACTIF;
      }
      vidangeEnCours = true;
      try {
        const garde = config.capturerGardeSession?.();
        const courante = () => (garde?.() ?? true) && (couranteExterne?.() ?? true);
        return await vidangerUneFois(courante);
      } finally {
        vidangeEnCours = false;
      }
    },
  };
}
