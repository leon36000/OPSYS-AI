import { prototypeJsonValide } from "../m10/json";

/** Snapshot JSON commun des lectures : pas de getter, prototype inventé, cycle ou nombre non fini. */
export const JSON_LECTURE_INVALIDE = Symbol("JSON_LECTURE_INVALIDE");
export type JsonLecture = null | string | boolean | number | JsonLecture[] | { [cle: string]: JsonLecture };
export function copierJsonLecture(brut: unknown, profondeur = 16): JsonLecture | typeof JSON_LECTURE_INVALIDE {
  const vus = new Set<object>();
  function copie(v: unknown, p: number): JsonLecture | typeof JSON_LECTURE_INVALIDE {
    if (p < 0) return JSON_LECTURE_INVALIDE;
    if (v === null || typeof v === "string" || typeof v === "boolean") return v;
    if (typeof v === "number") return Number.isFinite(v) && (!Number.isInteger(v) || Number.isSafeInteger(v)) ? v : JSON_LECTURE_INVALIDE;
    if (typeof v !== "object" || vus.has(v)) return JSON_LECTURE_INVALIDE;
    try {
      vus.add(v);
      if (!prototypeJsonValide(v) || Reflect.ownKeys(v).some(k => typeof k !== "string")) return JSON_LECTURE_INVALIDE;
      const ds = Object.getOwnPropertyDescriptors(v);
      if (Array.isArray(v)) {
        const n = ds.length?.value;
        if (!Number.isSafeInteger(n) || n < 0 || Object.keys(ds).length !== n + 1) return JSON_LECTURE_INVALIDE;
        const sortie: JsonLecture[] = [];
        for (let i = 0; i < n; i++) {
          const d = ds[String(i)];
          if (!d || !("value" in d) || !d.enumerable) return JSON_LECTURE_INVALIDE;
          const lu = copie(d.value, p - 1); if (lu === JSON_LECTURE_INVALIDE) return lu; sortie.push(lu);
        }
        return sortie;
      }
      const sortie: { [cle: string]: JsonLecture } = Object.create(null);
      for (const [k, d] of Object.entries(ds)) {
        if (!("value" in d) || !d.enumerable) return JSON_LECTURE_INVALIDE;
        const lu = copie(d.value, p - 1); if (lu === JSON_LECTURE_INVALIDE) return lu; sortie[k] = lu;
      }
      return sortie;
    } catch { return JSON_LECTURE_INVALIDE; } finally { vus.delete(v); }
  }
  return Number.isSafeInteger(profondeur) && profondeur >= 0 ? copie(brut, profondeur) : JSON_LECTURE_INVALIDE;
}
