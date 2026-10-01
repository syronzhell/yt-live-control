import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {dirname,join} from 'node:path';
import {createHandler} from './api/index.js';
import {DemoStore} from './demo-store.js';
const root=dirname(fileURLToPath(import.meta.url)),port=Number(process.env.PORT||3000),demo=process.argv.includes('--demo');
if(!demo){try{const text=await readFile(join(root,'.env'),'utf8');for(const line of text.split(/\r?\n/)){const match=line.match(/^([A-Z_]+)=(.*)$/);if(match&&!process.env[match[1]])process.env[match[1]]=match[2].replace(/^['"]|['"]$/g,'');}}catch{}}
const env=demo?{NODE_ENV:'development',SUPABASE_URL:'https://demo.supabase.co',SUPABASE_SERVICE_ROLE_KEY:'demo-no-database',CMS_PASSWORD:'demo-title-loop',SESSION_SECRET:'demo-session-key-012345678901234567890',AGENT_KEY:'demo-agent-key-012345678901234567890',CMS_PUBLIC_URL:`http://127.0.0.1:${port}`}:{...process.env,NODE_ENV:'development'};
const store=new DemoStore(),handler=createHandler({env,dbFactory:demo?()=>store:undefined});
const server=createServer(async(req,res)=>{
  const path=new URL(req.url,'http://local').pathname;
  if(path.startsWith('/api/')){await handler(req,res);return;}
  const files={'/':['index.html','text/html; charset=utf-8'],'/app.js':['app.js','text/javascript; charset=utf-8'],'/style.css':['style.css','text/css; charset=utf-8']};
  if(!files[path]){res.writeHead(404);res.end('Not found');return;}
  const [file,type]=files[path];res.setHeader('Content-Type',type);res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
  res.end(await readFile(join(root,'public',file)));
});
server.listen(port,'127.0.0.1',()=>{console.log(`CMS ${demo?'DEMO':'LOCAL'}: http://127.0.0.1:${port}`);if(demo)console.log('Demo password: demo-title-loop\nDemo agent key: demo-agent-key-012345678901234567890\nData demo tersimpan di memori dan hilang saat program berhenti.');});
