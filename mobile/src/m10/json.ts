function constructeurNomme(prototype: object, nom: string): boolean {
  const c = Object.getOwnPropertyDescriptor(prototype, "constructor");
  return !!c && "value" in c && typeof c.value === "function" &&
    Object.getOwnPropertyDescriptor(c.value, "name")?.value === nom &&
    Function.prototype.toString.call(c.value) === Function.prototype.toString.call(nom === "Object" ? Object : Array);
}
function racineObjet(prototype: object | null): boolean {
  return prototype === Object.prototype || prototype !== null &&
    Object.getPrototypeOf(prototype) === null && constructeurNomme(prototype, "Object");
}
/** JSON ordinaire, y compris Response.json d'un autre realm ; aucune propriété héritée n'est lue. */
export function prototypeJsonValide(v: object): boolean {
  try {
    const p = Object.getPrototypeOf(v);
    if (!Array.isArray(v)) return p === null || racineObjet(p);
    return p === Array.prototype || p !== null && constructeurNomme(p, "Array") && racineObjet(Object.getPrototypeOf(p));
  } catch { return false; }
}
