/* Static localhost-only design preview; allowlisted assets, no production files. */
const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const files=new Map(['index.html','app.js','fixtures.js','style.css','gallery.html'].map(f=>['/'+f,path.join(__dirname,f)]));
files.set('/',path.join(__dirname,'index.html'));
for(const f of fs.readdirSync(path.join(__dirname,'screenshots')))if(/^[a-z0-9-]+\.png$/.test(f))files.set('/screenshots/'+f,path.join(__dirname,'screenshots',f));
http.createServer((req,res)=>{
  const name=new URL(req.url,'http://127.0.0.1').pathname,file=files.get(name);
  if(req.method!=='GET'||!file){res.writeHead(404);res.end('Not found');return;}
  const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png'};
  res.writeHead(200,{'Content-Type':types[path.extname(file)],'Cache-Control':'no-store'});fs.createReadStream(file).pipe(res);
}).listen(8024,'127.0.0.1',()=>console.log('Nutrition QA preview: http://127.0.0.1:8024'));
