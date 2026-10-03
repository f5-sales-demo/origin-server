import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
const files = JSON.parse(fs.readFileSync(new URL('../provisioning/files.json', import.meta.url)));
const adapter = files.find(file=>file.path.endsWith('crapi-frontend/adapt.mjs')).content;
const root=fs.mkdtempSync(path.join(os.tmpdir(),'crapi-adapter-'));
try {
 fs.mkdirSync(path.join(root,'src/components/bot'),{recursive:true});
 fs.writeFileSync(path.join(root,'src/index.tsx'),'<BrowserRouter>');
 const statement='const stateUrl = APIService.CHATBOT_SERVICE + "genai/state";';
 fs.writeFileSync(path.join(root,'src/components/bot/Bot.tsx'),statement+'\n'+statement);
 const result=spawnSync(process.execPath,['--input-type=module','-e',adapter],{cwd:root,encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);
 const transformed=fs.readFileSync(path.join(root,'src/components/bot/Bot.tsx'),'utf8');
 assert.equal(transformed.split('if (!props.isLoggedIn || !props.accessToken)').length-1,2);
} finally {fs.rmSync(root,{recursive:true,force:true});}
