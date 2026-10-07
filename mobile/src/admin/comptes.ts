import type { ConfigurationChargeurAdmin } from "./appel";
import { appelerLecture } from "./appel";
import { interpreter } from "./enveloppe";
import { lireSection } from "./lecture";
import type { ResultatSection } from "./lecture";
import { jourLocal } from "./horloge";
import { capturerGardeLecture, VERDICT_LECTURE_REMPLACEE } from "../stockage/lecturesEnVol";
import { VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";
import { lireCreances, lireAP, lireAttentes, OUTIL_CREANCES, OUTIL_A_PAYER, OUTIL_ATTENTES } from "../m5/comptes";
import type { Creances, Masquee, PageAP, AttentesFacturation } from "../m5/comptes";

function epurerCouple<T>(reader: (v: unknown) => T | null, projection: (v: T) => unknown) {
  return (raw: unknown) => {
    const lu = interpreter(raw, "couple", reader);
    return lu.ok ? { ok: true, resultat: { accepte: true, resultat: projection(lu.valeur) } } : raw;
  };
}
function cacheCreances(v: Creances | Masquee) {
  if (v.genre === "masquee") return { role: v.role, nombre: v.nombre, montants_masques: true };
  const anomalie = (a: { facture_id: string; code: string }) => ({ facture_id: a.facture_id, verdict: { code: a.code } });
  return { role: v.role, nombre: v.nombre, factures: v.factures, total_a_recevoir: v.total_a_recevoir,
    total_complet: v.total_complet, illisibles: v.illisibles.map(anomalie),
    age: { ...v.age, exclues: v.age.exclues.map(anomalie) } };
}
function cacheAP(v: PageAP | Masquee, sansPO: boolean) {
  if (v.genre === "masquee") return { role: v.role, montants_masques: true,
    [sansPO ? "nombre_factures_sans_po" : "nombre_po"]: v.nombre };
  return { role: v.role, type: sansPO ? "COMPTES_A_PAYER_SANS_PO" : "COMPTES_A_PAYER",
    mention: v.mention, hypotheses: v.hypotheses, taxes_versions: v.taxes_versions,
    total: v.total, depart: v.depart, affichees: v.affichees, reste: v.reste, prochain_depart: v.prochain_depart,
    totaux: sansPO ? { apres_taxes: v.total_apres_taxes } : { a_payer_apres_taxes: v.total_apres_taxes,
      a_payer_connu_apres_taxes: v.connu_apres_taxes, complet: v.complet },
    comptes: v.comptes.map(p => ({ po_id: p.po_id, fournisseur_id: p.fournisseur_id, chantier_id: p.chantier_id,
      statut_po: p.statut_po, derniere_reception: p.derniere_reception, manque: p.manque,
      attendu: { apres_taxes: p.attendu_apres_taxes }, factures: { apres_taxes: p.facture_apres_taxes },
      a_payer_apres_taxes: p.a_payer_apres_taxes, rapprochement: { statut: "PROPOSE", verdict: p.verdict } })),
    factures: v.factures };
}
/** T4.22 : lectures financières indépendantes, première page en cache personnel et suites courantes en ligne. */
export function creerChargeurComptes(config: ConfigurationChargeurAdmin) {
  const garde = capturerGardeLecture(config.depot);
  const remplacee = <T>(): ResultatSection<T> => ({ source: "aucune", raison: VERDICT_LECTURE_REMPLACEE });
  async function courante<T>(operation: () => Promise<ResultatSection<T>>): Promise<ResultatSection<T>> {
    if (!garde.courante()) return remplacee();
    const lu = await operation();
    return garde.courante() ? lu : remplacee();
  }
  return {
    chargerCreances(): Promise<ResultatSection<Creances | Masquee>> {
      const jour = jourLocal(config.horloge());
      const lire = (raw: unknown) => lireCreances(raw, jour);
      return courante(() => lireSection(config, {
        outil: OUTIL_CREANCES, args: { aujourd_hui: jour }, cache: `creances_m5:${jour}`,
        interpreter: raw => interpreter(raw, "couple", lire), epurerPourLeCache: epurerCouple(lire, cacheCreances),
      }));
    },
    chargerAP(sansPO = false, depart = 0): Promise<ResultatSection<PageAP | Masquee>> {
      if (!Number.isSafeInteger(depart) || depart < 0) return Promise.resolve({ source: "aucune", raison: VERDICT_REPONSE_ILLISIBLE });
      const args = sansPO ? { sans_po: true, depart } : { depart };
      const lire = (raw: unknown) => lireAP(raw, sansPO, depart);
      return courante(async () => {
        if (depart === 0) return lireSection(config, {
          outil: OUTIL_A_PAYER, args, cache: sansPO ? "comptes_sans_po_m5" : "comptes_po_m5",
          interpreter: raw => interpreter(raw, "couple", lire), epurerPourLeCache: epurerCouple(lire, v => cacheAP(v, sansPO)),
        });
        const appel = await appelerLecture(config, OUTIL_A_PAYER, args);
        if (!garde.courante()) return remplacee<PageAP | Masquee>();
        if (appel.genre === "refuse") return { source: "refus", verdict: appel.verdict };
        if (appel.genre === "injoignable") return { source: "aucune", raison: appel.verdict };
        const lu = interpreter(appel.resultat, "couple", lire);
        if (!lu.ok) return lu.genre === "refus" ? { source: "refus", verdict: lu.verdict } : { source: "aucune", raison: lu.verdict };
        return { source: "serveur", valeur: lu.valeur, misAJourLe: config.horloge().maintenant.toISOString() };
      });
    },
    chargerAttentes(): Promise<ResultatSection<AttentesFacturation>> {
      return courante(() => lireSection(config, {
        outil: OUTIL_ATTENTES, args: {}, cache: "attentes_facturation_m5",
        interpreter: raw => interpreter(raw, "directe", lireAttentes),
        epurerPourLeCache: raw => {
          const lu = interpreter(raw, "directe", lireAttentes);
          return lu.ok ? { ok: true, resultat: { attentes_devis: lu.valeur.devis, attentes_wct_sans_devis_id: lu.valeur.wct } } : raw;
        },
      }));
    },
  };
}
