import { createHash } from 'node:crypto';
import native from '../m6/fixturesPreuvesNative.json';
import { construireArgumentsPreuves, lirePreuvesPertesWct } from '../m6/preuvesLecture';
import { creerChargeurApercuPreuve, type TemporairePreuve } from './apercuPreuve';

test.each(native.reads)('corps original HTTP $phase consommé, sans réexécution Native', capture => {
  expect(createHash('sha256').update(capture.body_utf8,'utf8').digest('hex')).toBe(capture.body_sha256);
  const args=capture.request.args;
  const lu=lirePreuvesPertesWct(JSON.parse(capture.body_utf8).result,construireArgumentsPreuves(args.wct_id,args.decalage,args.limite));
  expect(lu.ok).toBe(capture.phase!=='role-revoked-read');
  if(lu.ok)expect(lu.value.wct_id).toBe(args.wct_id);
});
test('pixels originaux2blocs exacts Native servent au client SHA/temporaire privé',async()=>{
  const bytes=new Uint8Array(Buffer.from(native.photo.bytes_base64,'base64'));
  expect(bytes.byteLength).toBe(307899);
  expect(createHash('sha256').update(bytes).digest('hex')).toBe(native.photo.bytes_sha256);
  let buffer=Buffer.alloc(0),ferme=false,supprime=false,lu=false;
  const f:TemporairePreuve={uri:'file:///PRIVATE-NATIVE-REPLAY.png',ecrire:b=>{buffer=Buffer.concat([buffer,b]);},
    fermer:()=>{ferme=true;},taille:()=>buffer.byteLength,empreinte:async()=>createHash('sha256').update(buffer).digest('hex'),
    supprimer:()=>{supprime=true;buffer=Buffer.alloc(0);}};
  const photo={position_photo:0,reference:'fichier:sha256:'+native.photo.bytes_sha256,empreinte_sha256:native.photo.bytes_sha256,
    type_mime:'image/png' as const,taille_octets:307899,etat_actuel:'disponible' as const};
  const r=await creerChargeurApercuPreuve({courante:()=>true,urlBase:'https://GATEWAY-FICTIF.example',jeton:'DEVICE-FICTIF',
    signal:new AbortController().signal,creerTemporaire:async()=>f,fetchPhoto:async(_url,init)=>{
      expect(JSON.parse(init.body)).toEqual(native.photo.selection);
      return {status:200,headers:{get:n=>Object.entries(native.photo.headers).find(([k])=>k===n)?.[1]??null},
        body:{getReader:()=>({read:async()=>lu?{done:true as const}:(lu=true,{done:false as const,value:bytes}),cancel:async()=>undefined})}};
    }}).charger(native.photo.selection,photo);
  expect(r.genre).toBe('pret');expect(ferme).toBe(true);expect(buffer.equals(Buffer.from(bytes))).toBe(true);
  if(r.genre==='pret')await r.purger();expect(supprime).toBe(true);
});
