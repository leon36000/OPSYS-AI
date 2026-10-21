import type { ItemM9, FaitM9, ManqueM9 } from "../m9/briefing";
import { message, formaterDateOuInstant } from "./adminCommun";
import type { Message } from "./adminCommun";
import { texteSansChemin } from "./texteSur";

export interface LigneBriefing {
  readonly titre: Message;
  readonly lignes: readonly Message[];
}
const texte = (v: string): Message => {
  const sur = texteSansChemin(v);
  return sur === null
    ? message("admin.briefing.detailNonAffiche")
    : sur === ""
      ? message("admin.briefing.texteVide")
      : message("admin.briefing.texte", { texte: sur });
};
const source = (v: string): Message => {
  const sur = texteSansChemin(v);
  const sources: Readonly<Record<string, string>> = {
    "registre m09-strategic-intelligence/snapshots": "admin.briefing.sourceFaits",
    "registre m09-strategic-intelligence/alertes_m8": "admin.briefing.sourceAlertes",
    "opsys.approbations.file_proprietaire": "admin.briefing.sourceDecisions",
  };
  return Object.hasOwn(sources, v)
    ? message(sources[v])
    : sur === null
      ? message("admin.briefing.detailNonAffiche")
      : message("admin.briefing.source", { source: sur });
};
function reference(cle: string, parametre: string, valeur: string): Message {
  const sur = texteSansChemin(valeur);
  return sur === null
    ? message("admin.briefing.detailNonAffiche")
    : message(cle, { [parametre]: sur });
}
export function presenterContradictionM9(
  v: { module_source: string; ligne_id_a: number; ligne_id_b: number; horodatage: string },
  decalage: number,
): Message {
  const module = texteSansChemin(v.module_source);
  return module === null
    ? message("admin.briefing.detailNonAffiche")
    : message("admin.briefing.contradiction", {
        module,
        a: v.ligne_id_a,
        b: v.ligne_id_b,
        date: formaterDateOuInstant(v.horodatage, decalage),
      });
}
function presenterFait(fait: FaitM9, decalage: number): LigneBriefing {
  return {
    titre: texte(fait.module_source),
    lignes: [
      source(fait.module_source),
      message("admin.briefing.date", { date: formaterDateOuInstant(fait.horodatage, decalage) }),
      ...Object.entries(fait.valeurs).map(([champ, valeur]) => {
        const cle = texteSansChemin(champ),
          v = texteSansChemin(valeur);
        return cle === null || v === null
          ? message("admin.briefing.detailNonAffiche")
          : v === ""
            ? message("admin.briefing.faitVide", { champ: cle })
            : message("admin.briefing.fait", { champ: cle, valeur: v });
      }),
    ],
  };
}
export function presenterItemM9(item: ItemM9, decalage: number): LigneBriefing {
  if ("id" in item)
    return {
      titre: texte(item.resume),
      lignes: [
        reference("admin.briefing.identifiant", "id", item.id),
        source(item.departement),
        message("admin.briefing.date", { date: formaterDateOuInstant(item.depuis, decalage) }),
        item.niveau === null
          ? message("admin.briefing.niveauInconnu")
          : reference("admin.briefing.niveau", "niveau", item.niveau),
        texte(item.action_proposee),
      ],
    };
  if ("evenement_id" in item)
    return {
      titre: texte(item.quoi),
      lignes: [
        reference("admin.briefing.identifiant", "id", item.evenement_id),
        source(item.source),
        message("admin.briefing.date", {
          date: formaterDateOuInstant(item.horodatage_reference, decalage),
        }),
        texte(item.pourquoi),
        source(item.a_qui),
        ...(typeof item.preuve.wct_id === "string"
          ? [reference("admin.briefing.chantier", "id", item.preuve.wct_id)]
          : []),
      ],
    };
  return presenterFait(item, decalage);
}
export function presenterManqueM9(v: ManqueM9): LigneBriefing {
  return { titre: texte(v.constat), lignes: [source(v.verifie)] };
}
