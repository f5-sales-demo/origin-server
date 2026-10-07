"""Restore exact synthetic Juice Shop SQL fixtures and process-local review journals."""

from __future__ import annotations

import json
import subprocess

NODE_SQL = r"""
const fs=require('fs'),sqlite=require('/juice-shop/node_modules/sqlite3');
const v=JSON.parse(fs.readFileSync(0,'utf8'));
const db=new sqlite.Database('/juice-shop/data/juiceshop.sqlite');
const profileRoot='/juice-shop/frontend/dist/frontend/assets/public/images/uploads';
function profileFiles(){const result={};for(const id of [1,2,3])for(const ext of ['jpg','jpeg','png','svg','gif']){const name=id+'.'+ext,path=profileRoot+'/'+name;if(fs.existsSync(path)){if(fs.lstatSync(path).isSymbolicLink()||!fs.lstatSync(path).isFile())throw Error('unsafe profile image');result[name]=fs.readFileSync(path).toString('base64')}}return result}
function all(sql,args=[]){return new Promise((resolve,reject)=>db.all(sql,args,(e,r)=>e?reject(e):resolve(r)))}
function run(sql,args=[]){return new Promise((resolve,reject)=>db.run(sql,args,e=>e?reject(e):resolve()))}
async function snapshot(){
 return {files:profileFiles(),users:await all('SELECT * FROM Users WHERE id IN (1,2,3) ORDER BY id'),
 feedback:await all('SELECT * FROM Feedbacks WHERE id IN (1,2,3) ORDER BY id'),
 baskets:await all('SELECT * FROM Baskets WHERE id IN (1,2,3) ORDER BY id'),
 items:await all('SELECT * FROM BasketItems WHERE BasketId IN (1,2,3) ORDER BY id'),
 temporary:await all('SELECT * FROM Users WHERE email=?',[v.marker+'@example.com'])};
}
(async()=>{
 await run('BEGIN IMMEDIATE');
 try {
  if(v.action==='restore'){
   const b=v.before,current=await snapshot();
   for(const user of b.users){if(!current.users.some(r=>r.id===user.id&&r.email===user.email))throw Error('user identity changed')}
   for(const row of b.feedback){if(!current.feedback.some(r=>r.id===row.id&&r.UserId===row.UserId))throw Error('feedback identity changed')}
   for(const basket of b.baskets){if(!current.baskets.some(r=>r.id===basket.id&&r.UserId===basket.UserId))throw Error('basket identity changed')}
   await run('DELETE FROM Feedbacks WHERE comment LIKE ? AND id NOT IN (1,2,3)',[v.marker+':%']);
   for(const user of current.temporary){
    for(const table of ['Addresses','Cards','Complaints','Memories','PrivacyRequests','Recycles','Wallets','Feedbacks']){
     if((await all('SELECT COUNT(*) AS n FROM '+table+' WHERE UserId=?',[user.id]))[0].n)throw Error('temporary actor has unrelated data');
    }
    if((await all('SELECT COUNT(*) AS n FROM BasketItems WHERE BasketId IN (SELECT id FROM Baskets WHERE UserId=?)',[user.id]))[0].n)throw Error('temporary actor has unrelated basket items');
    await run('DELETE FROM SecurityAnswers WHERE UserId=?',[user.id]);
    await run('DELETE FROM Baskets WHERE UserId=?',[user.id]);
    await run('DELETE FROM Users WHERE id=? AND email=?',[user.id,user.email]);
   }
   for(const user of b.users)await run('UPDATE Users SET password=?,lastLoginIp=?,profileImage=?,updatedAt=? WHERE id=? AND email=?',[user.password,user.lastLoginIp,user.profileImage,user.updatedAt,user.id,user.email]);
   for(const row of current.feedback){const original=b.feedback.find(r=>r.id===row.id);if(original&&row.comment!==original.comment&&!row.comment.startsWith(v.marker+':'))throw Error('unowned feedback change')}
   for(const row of b.feedback)await run('UPDATE Feedbacks SET comment=?,rating=?,updatedAt=? WHERE id=? AND UserId=?',[row.comment,row.rating,row.updatedAt,row.id,row.UserId]);
   const original=new Map(b.items.map(r=>[r.id,r]));
   for(const row of current.items){
    if(!original.has(row.id)){
     if(row.ProductId!==1||row.quantity!==1)throw Error('unowned new basket item');
     await run('DELETE FROM BasketItems WHERE id=? AND BasketId=? AND ProductId=?',[row.id,row.BasketId,row.ProductId]);
    }
   }
   for(const row of b.items){
    const currentRow=current.items.find(r=>r.id===row.id);
    if(currentRow&&(currentRow.BasketId!==row.BasketId||currentRow.ProductId!==row.ProductId))throw Error('item identity changed');
    await run('INSERT OR REPLACE INTO BasketItems(id,ProductId,BasketId,quantity,createdAt,updatedAt) VALUES(?,?,?,?,?,?)',[row.id,row.ProductId,row.BasketId,row.quantity,row.createdAt,row.updatedAt]);
   }
   await run('DELETE FROM Feedbacks WHERE comment LIKE ? AND id NOT IN (1,2,3)',[v.marker+':%']);
   for(const id of [1,2,3])for(const ext of ['jpg','jpeg','png','svg','gif']){const name=id+'.'+ext,path=profileRoot+'/'+name;if(Object.hasOwn(b.files,name))fs.writeFileSync(path,Buffer.from(b.files[name],'base64'));else if(fs.existsSync(path)){if(fs.lstatSync(path).isSymbolicLink())throw Error('unsafe profile image');fs.unlinkSync(path)}}
  }
  const result=await snapshot();
  if(v.action==='snapshot'&&result.temporary.length)throw Error('temporary marker already present');
  if(v.action==='restore'&&JSON.stringify(result)!==JSON.stringify(v.before))throw Error('SQL fixture recovery mismatch');
  await run('COMMIT');process.stdout.write(JSON.stringify(result));
 } catch(error){await run('ROLLBACK');throw error}
})().then(()=>db.close(),()=>{db.close();process.exitCode=2});
"""
NODE_SOCKET = r"""
const fs=require('fs'),net=require('net');
const input=fs.readFileSync(0,'utf8');
const socket=net.createConnection('/tmp/waap-catalog-reviews.sock');let output='';
socket.setTimeout(30000,()=>socket.destroy(Error('journal timeout')));
socket.on('connect',()=>socket.end(input));
socket.on('data',chunk=>{output+=chunk.toString();if(output.length>4000000)socket.destroy()});
socket.on('end',()=>process.stdout.write(output));socket.on('error',()=>{process.exitCode=2});
"""


def node(container: str, helper: str, value: dict) -> dict:
    """Run a fixed Node helper after verifying exact Compose replica ownership."""
    data = json.loads(
        subprocess.check_output(  # noqa: S603 - fixed declared inventory
            ["/usr/bin/docker", "inspect", container], text=True, timeout=10
        )
    )[0]
    labels = data.get("Config", {}).get("Labels", {})
    if (
        labels.get("com.docker.compose.project") != "origin-server"
        or labels.get("com.docker.compose.service") != container
        or labels.get("com.docker.compose.project.config_files")
        != "/opt/origin-server/docker-compose.yml"
    ):
        message = "Juice Shop replica ownership mismatch"
        raise ValueError(message)
    result = subprocess.run(  # noqa: S603 - fixed Node helper and structured data
        ["/usr/bin/docker", "exec", "-i", container, "/nodejs/bin/node", "-e", helper],
        input=json.dumps(value),
        text=True,
        capture_output=True,
        check=True,
        timeout=40,
    )
    return json.loads(result.stdout)


def juice_database(
    container: str, action: str, marker: str, before: dict | None = None
) -> dict:
    """Use SQL ownership and an in-process review journal; never resolve a broad reset."""
    value = {"action": action, "marker": marker}
    if action == "snapshot":
        sql = node(container, NODE_SQL, value)
        review = node(container, NODE_SOCKET, value)
        if not review.get("passed"):
            message = "Juice Shop review journal unavailable"
            raise ValueError(message)
        return {"sql": sql, "reviews": review["reviews"]}
    if before is None:
        message = "missing Juice Shop host baseline"
        raise ValueError(message)
    review = node(container, NODE_SOCKET, value)
    if review.get("restored") is not True:
        message = "Juice Shop review restoration failed"
        raise ValueError(message)
    sql = node(container, NODE_SQL, {**value, "before": before["sql"]})
    if review.get("reviews") != before["reviews"]:
        message = "Juice Shop observed review readback mismatch"
        raise ValueError(message)
    return {"sql": sql, "reviews": review["reviews"]}
