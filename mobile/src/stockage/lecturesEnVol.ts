import type { DepotCleValeur } from "./depotCleValeur";

/** Les lecteurs de production et la purge partagent le même dépôt.
 * La génération invalide les lectures tardives ; la file ordonne les écritures admises avant la purge.
 * Les brouillons et la file sortante ne passent pas par cette frontière. */
interface EtatLectures {
  generation: object;
  operations: Promise<void>;
  transitions: number;
  cacheBloque: boolean;
  sections: Map<string, object>;
}
const etats = new WeakMap<DepotCleValeur, EtatLectures>();
const vues = new WeakMap<DepotCleValeur, { base: DepotCleValeur; garde: GardeLecture }>();

function base(depot: DepotCleValeur): DepotCleValeur {
  return vues.get(depot)?.base ?? depot;
}
function etat(depot: DepotCleValeur): EtatLectures {
  const original = base(depot);
  let value = etats.get(original);
  if (!value) {
    value = { generation: {}, operations: Promise.resolve(), transitions: 0, cacheBloque: false, sections: new Map() };
    etats.set(original, value);
  }
  return value;
}
export interface GardeLecture {
  courante(): boolean;
  cachePermis(): boolean;
}
export const VERDICT_LECTURE_REMPLACEE = {
  code: "lecture_remplacee",
  detail: "L’identité de cette lecture a changé. Relire sous la session courante.",
} as const;

export function capturerGardeLecture(
  depot: DepotCleValeur,
  sessionCourante: () => boolean = () => true,
): GardeLecture {
  const state = etat(depot);
  const generation = state.generation;
  const admise = state.transitions === 0;
  const origine = vues.get(depot)?.garde;
  const courante = () =>
    admise && generation === state.generation && sessionCourante() && (origine?.courante() ?? true);
  return {
    courante,
    cachePermis: () => courante() && !state.cacheBloque && state.transitions === 0,
  };
}

export function serialiserCaches<T>(
  depot: DepotCleValeur,
  operation: () => Promise<T>,
): Promise<T> {
  const state = etat(depot);
  const result = state.operations.then(operation);
  state.operations = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

/** Un refus d'un slot invalide ses réponses parties avant ce refus, sans fermer les autres slots. */
export function capturerGardeSection(depot: DepotCleValeur, cle: string): GardeLecture {
  const state = etat(depot), globale = capturerGardeLecture(depot);
  let generation = state.sections.get(cle);
  if (!generation) { generation = {}; state.sections.set(cle, generation); }
  const courante = () => globale.courante() && state.sections.get(cle) === generation;
  return { courante, cachePermis: () => courante() && globale.cachePermis() };
}
export function invaliderLecturesSection(depot: DepotCleValeur, cle: string): void {
  etat(depot).sections.set(cle, {});
}

/** Invalide avant d’attendre les écritures admises. Une purge échouée bloque le cache
 * jusqu’à une confirmation ultérieure réussie ; les lectures fraîches du serveur peuvent reprendre. */
export function cacheRequiertPurge(depot: DepotCleValeur): boolean {
  return etat(depot).cacheBloque;
}

export function commencerTransitionCaches(depot: DepotCleValeur): (reussie: boolean) => void {
  const state = etat(depot);
  const generation = {};
  state.generation = generation;
  state.sections.clear();
  state.transitions += 1;
  state.cacheBloque = true;
  let terminee = false;
  return (reussie) => {
    if (terminee) return;
    terminee = true;
    state.transitions -= 1;
    if (state.generation === generation) state.cacheBloque = !reussie;
  };
}

export async function ecrireCacheSousGarde(
  depot: DepotCleValeur,
  ecriture: () => Promise<void>,
): Promise<void> {
  const garde = capturerGardeLecture(depot);
  await serialiserCaches(depot, async () => {
    if (garde.cachePermis()) await ecriture();
  });
}

/** Un service capture sa session avant d’obtenir le dépôt asynchrone.
 * La vue garde cette validité pour chaque lecture/écriture, y compris les chargeurs enchaînés. */
export function depotSousGardeLecture(
  depot: DepotCleValeur,
  sessionCourante: () => boolean,
): DepotCleValeur {
  const garde = capturerGardeLecture(depot, sessionCourante);
  const original = base(depot);
  const view: DepotCleValeur = {
    async lire(cle) {
      if (!garde.cachePermis()) return null;
      const value = await original.lire(cle);
      return garde.cachePermis() ? value : null;
    },
    async ecrire(cle, valeur) {
      if (garde.cachePermis()) await original.ecrire(cle, valeur);
    },
    async supprimer(cle) {
      if (garde.courante()) await original.supprimer(cle);
    },
    async supprimerParPrefixe(prefixe) {
      if (garde.courante()) await original.supprimerParPrefixe(prefixe);
    },
  };
  vues.set(view, { base: original, garde });
  return view;
}
