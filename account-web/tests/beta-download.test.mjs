// SPDX-License-Identifier: AGPL-3.0-or-later
import test from 'node:test';
import assert from 'node:assert/strict';
import {downloadBeta} from '../lib/beta-download-http.mjs';
const env={APP_BASE_URL:'https://account.example.test',SAIPH_ACCOUNT_MODE:'friends-beta',
  SAIPH_HOSTED_API_URL:'https://api.example.test',SAIPH_HOSTED_API_AUDIENCE:'https://aud.example.test'};
const request = (body='artifact=windows', origin=env.APP_BASE_URL) => new Request(env.APP_BASE_URL+'/api/beta/download',{
  method:'POST',headers:{origin,'content-type':'application/x-www-form-urlencoded'},body});
test('download requires same origin, session, one allowlisted artifact and a pinned ticket URL',async()=>{
  let calls=0;
  const deps={env,getSession:async()=>({user:{sub:'synthetic'}}),download:async()=>{calls++;return env.SAIPH_HOSTED_API_URL+'/v1/download/'+'a'.repeat(43)}};
  for(const r of [request('artifact=windows','https://evil.test'),request('artifact=windows','null'),request('artifact=../../x'),request('artifact=windows&account=x')])
    assert.notEqual((await downloadBeta(r,deps)).status,303);
  assert.equal(calls,0);
  assert.equal((await downloadBeta(request(),{...deps,getSession:async()=>null})).status,401);
  const response=await downloadBeta(request(),deps);
  assert.equal(response.status,303);
  assert.equal(response.headers.get('location'),env.SAIPH_HOSTED_API_URL+'/v1/download/'+'a'.repeat(43));
  assert.equal((await downloadBeta(request(),{...deps,download:async()=> 'https://evil.test/'})).status,403);
});
