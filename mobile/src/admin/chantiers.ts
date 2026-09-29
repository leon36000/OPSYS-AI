import {
  construireArgumentsDigest,
  construireArgumentsListerInterventions,
  construireArgumentsPreparation,
  lireDigest,
  lireInterventions,
  lirePreparation,
  OUTIL_LISTER_INTERVENTIONS,
  OUTIL_PRODUIRE_DIGEST,
  OUTIL_VERIFIER_PREPARATION,
  STATUTS_DU_DISPATCH,
} from "../m4/dispatch";
import type { DigestDuJour, InterventionsLues, Preparation } from "../m4/dispatch";
import type { ConfigurationChargeurAdmin } from "./appel";
import { interpreter } from "./enveloppe";
import { instantLocal, jourLocal } from "./horloge";
import { lireSection } from "./lecture";
import type { DefinitionSection, ResultatSection } from "./lecture";

/**
 * Les lectures de l'écran « Chantiers du jour » (`(admin)/chantiers.tsx`, PLAN T4.20, §9.5 M4 « dispatch du jour,
 * retards, file de complétion ») : les interventions par statut, le digest du jour et la préparation d'une intervention.
 * Que des lectures : aucune cédule n'est proposée ni appliquée, aucune intervention ne change d'état, aucun report
 * n'est signalé. La MÉTÉO d'un créneau n'est pas lue : `m4_verifier_meteo_creneau` exige le `plan_id` d'une cédule
 * PROPOSÉE (`m4_proposer_cedule`, qui écrit un maillon au registre) et des dates que l'appelant fournirait ; il n'existe
 * aucun outil qui rende la météo sans écrire (voir la réponse de PLAN T4.20).
 *
 * Un groupe par statut (`STATUTS_DU_DISPATCH`), chacun lu SÉPARÉMENT : un groupe trop gros pour la réponse du serveur, ou
 * refusé, ne cache pas les autres. Lecture d'abord, cache marqué (date, raison), une clé par personne ; un refus du
 * serveur n'est jamais remplacé par le cache.
 */
export function sectionInterventions(statut: string): DefinitionSection<InterventionsLues> {
  return {
    outil: OUTIL_LISTER_INTERVENTIONS,
    args: construireArgumentsListerInterventions(statut),
    cache: `interventions:${statut}`,
    interpreter: (brut) => interpreter(brut, "directe", (valeur) => lireInterventions(valeur, statut)),
  };
}

/** Le digest d'UN jour : le cache aussi (un digest du 21 n'est jamais servi pour le 22, il dirait autre chose). */
export function sectionDigest(dateCible: string, horodatageReference: string): DefinitionSection<DigestDuJour> {
  return {
    outil: OUTIL_PRODUIRE_DIGEST,
    args: construireArgumentsDigest(dateCible, horodatageReference),
    cache: `digest:${dateCible}`,
    interpreter: (brut) => interpreter(brut, "couple", lireDigest),
  };
}

export function sectionPreparation(interventionId: string): DefinitionSection<Preparation> {
  return {
    outil: OUTIL_VERIFIER_PREPARATION,
    args: construireArgumentsPreparation(interventionId),
    cache: `preparation:${interventionId}`,
    interpreter: (brut) => interpreter(brut, "couple", lirePreparation),
  };
}

export interface GroupeInterventions {
  readonly statut: string;
  readonly resultat: ResultatSection<InterventionsLues>;
}

export interface ChargeurChantiers {
  /** Un résultat par statut du dispatch, dans l'ordre de `STATUTS_DU_DISPATCH`. Ne lève jamais pour une raison réseau. */
  chargerGroupes(): Promise<readonly GroupeInterventions[]>;
  chargerDigest(): Promise<ResultatSection<DigestDuJour>>;
  chargerPreparation(interventionId: string): Promise<ResultatSection<Preparation>>;
}

export function creerChargeurChantiers(config: ConfigurationChargeurAdmin): ChargeurChantiers {
  return {
    chargerGroupes: () =>
      Promise.all(
        STATUTS_DU_DISPATCH.map(async (statut) => ({ statut, resultat: await lireSection(config, sectionInterventions(statut)) })),
      ),
    chargerDigest() {
      const horloge = config.horloge();
      return lireSection(config, sectionDigest(jourLocal(horloge), instantLocal(horloge)));
    },
    chargerPreparation: (interventionId) => lireSection(config, sectionPreparation(interventionId)),
  };
}
