import { creerChargeurApercuPreuve, type DependancesApercuPreuve, type TemporairePreuve } from './apercuPreuve';
import { createHash } from 'node:crypto';
const bytes = new Uint8Array([137,80,78,71,13,10,26,10,1,2,3]);
const sha = createHash('sha256').update(bytes).digest('hex');
const selection = { wct_id: 'WCT-FICTIF', preuve: { index: 0, hash_maillon: 'a'.repeat(64) }, position_photo: 0 };
const photo = { position_photo: 0, reference: 'fichier:sha256:' + sha, empreinte_sha256: sha,
  type_mime: 'image/png' as const, taille_octets: bytes.length, etat_actuel: 'disponible' as const };
function monde() {
  let actuelle = true, supprime = 0, ferme = 0, taille = 0;
  const recus: Uint8Array[] = [];
  const fichier: TemporairePreuve = { uri: 'file:///PRIVATE-FICTIF.png',
    ecrire: b => { recus.push(b.slice()); taille += b.byteLength; }, fermer: () => { ferme++; },
    taille: () => taille, empreinte: async () => sha, supprimer: () => { supprime++; } };
  const d: DependancesApercuPreuve = { courante: () => actuelle, creerTemporaire: async () => fichier,
    fetchPhoto: async (_url, init) => ({ status: 200, headers: { get: n => ({ 'content-type':'image/png',
      'content-length':String(bytes.length), 'x-opsys-sha256':sha, etag:'"'+sha+'"' })[n] ?? null },
      body: { getReader: () => { let lu = false; return { read: async () => lu ? { done: true as const } :
        (lu = true, { done: false as const, value: bytes }), cancel: async () => undefined }; } } }),
    urlBase: 'https://GATEWAY-FICTIF.example', jeton: 'DEVICE-FICTIF', signal: new AbortController().signal };
  return { d, invalider: () => { actuelle = false; }, statistiques: () => ({ supprime, ferme, recus }) };
}
test('sélection exacte, pixels privés et purge explicite sans bearer dans URL', async () => {
  const m = monde(); const original = m.d.fetchPhoto;
  const d = { ...m.d, fetchPhoto: async (url: string, init: Parameters<typeof original>[1]) => {
    expect(url).toBe('https://GATEWAY-FICTIF.example/opsys/m6/preuves/photo');
    expect(url).not.toContain('DEVICE-FICTIF'); expect(JSON.parse(init.body)).toEqual(selection);
    expect(init.headers.authorization).toBe('Bearer DEVICE-FICTIF');
    return original(url, init);
  } };
  const r = await creerChargeurApercuPreuve(d).charger(selection, photo);
  expect(r.genre).toBe('pret'); expect(m.statistiques().ferme).toBe(1);
  if (r.genre === 'pret') await r.purger();
  expect(m.statistiques().supprime).toBe(1);
});
test('SHA local différent ferme et purge, aucun aperçu', async () => {
  const m = monde(); const tmp = await m.d.creerTemporaire('image/png');
  const r = await creerChargeurApercuPreuve({ ...m.d, creerTemporaire: async () => ({ ...tmp, empreinte: async () => 'b'.repeat(64) }) }).charger(selection, photo);
  expect(r.genre).toBe('echec'); expect(m.statistiques().supprime).toBe(1);
});
test('session réattribuée pendant lecture purge avant exposition et arrête flux', async () => {
  const m = monde(); const original = m.d.fetchPhoto;
  const r = await creerChargeurApercuPreuve({ ...m.d, fetchPhoto: async (u,i) => {
    const response = await original(u,i); m.invalider(); return response;
  } }).charger(selection, photo);
  expect(r.genre).toBe('echec'); expect(m.statistiques().supprime).toBe(1);
});
test('image déjà indisponible ne crée pas de temporaire ni réseau', async () => {
  const m = monde(); const r = await creerChargeurApercuPreuve(m.d).charger(selection, { ...photo, etat_actuel: 'indisponible' });
  expect(r.genre).toBe('echec'); expect(m.statistiques()).toEqual({ supprime:0, ferme:0, recus:[] });
});

test('annulation du reader bloquée ne retient pas nettoyage ni résultat', async () => {
  const m = monde(); const original = m.d.fetchPhoto;
  const operation = creerChargeurApercuPreuve({ ...m.d, fetchPhoto: async (u,i) => ({ ...await original(u,i),
    body: { getReader: () => ({ read: async () => ({ done:false as const, value:new Uint8Array() }),
      cancel: () => new Promise<void>(() => undefined) }) } }) }).charger(selection, photo);
  for (let n=0;n<12;n++) await Promise.resolve();
  expect(m.statistiques().ferme).toBe(1); expect(m.statistiques().supprime).toBe(1);
  expect((await operation).genre).toBe('echec');
});

test.each(['taille','mime','sha','redirect-body'])('en-tête %s invalide purgé sans exposer de fichier', async kind => {
  const m=monde(), original=m.d.fetchPhoto;
  const r=await creerChargeurApercuPreuve({...m.d,fetchPhoto:async(u,i)=>{
    const rep=await original(u,i);return {...rep,headers:{get:(n:string)=>
      kind==='taille'&&n==='content-length'?'10485761':kind==='mime'&&n==='content-type'?'image/svg+xml':
      kind==='sha'&&n==='x-opsys-sha256'?'b'.repeat(64):kind==='redirect-body'&&n==='content-encoding'?'gzip':rep.headers.get(n)}};
  }}).charger(selection,photo);
  expect(r.genre).toBe('echec');expect(m.statistiques().supprime).toBe(1);expect(m.statistiques().recus).toHaveLength(0);
});
test('excès de bytes refuse avant écriture supplémentaire et purge',async()=>{
  const m=monde(), original=m.d.fetchPhoto;
  const r=await creerChargeurApercuPreuve({...m.d,fetchPhoto:async(u,i)=>({...await original(u,i),body:{getReader:()=>({
    read:async()=>({done:false as const,value:new Uint8Array(bytes.length+1)}),cancel:async()=>undefined
  })}})}).charger(selection,photo);
  expect(r.genre).toBe('echec');expect(m.statistiques().recus).toHaveLength(0);expect(m.statistiques().supprime).toBe(1);
});
test('purge invalide l’autorité d’affichage même si session reste courante',async()=>{
  const m=monde(),r=await creerChargeurApercuPreuve(m.d).charger(selection,photo);
  expect(r.genre).toBe('pret');if(r.genre==='pret'){expect(r.courante()).toBe(true);await r.purger();expect(r.courante()).toBe(false);}
});
