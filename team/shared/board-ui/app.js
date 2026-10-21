const $=id=>document.getElementById(id);
let snapshot=null,selected=null,busy=false;
const columns=[['ready','Queued'],['running','Running'],['approval','Awaiting approval'],['done','Done'],['attention','Needs attention']];
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function render(){
 if(!snapshot)return;
 const projects=snapshot.projects.filter(p=>$('tests').checked||!p.test);
 if(!projects.some(p=>p.id===selected))selected=projects[0]?.id;
 $('projects').replaceChildren();
 for(const p of projects){const b=el('button',p.name,p.id===selected?'active':'');b.append(el('small',`${p.tasks.length} tasks${p.paused?' · decision needed':''}`));b.onclick=()=>{selected=p.id;render();};$('projects').append(b);}
 $('workspace').textContent=snapshot.workspace;
 const p=projects.find(p=>p.id===selected);$('board').replaceChildren();$('metrics').replaceChildren();
 $('name').textContent=p?.name||'No research projects yet';$('source').textContent=p?`${p.source||''} · ${p.commit?.slice(0,10)||''}`:'';
 $('banner').textContent=p?.error||(p?.paused?'Your decision is needed. New tasks are paused until the checkpoint is approved.':'');
 $('empty').hidden=Boolean(p?.tasks.length);
 if(!p)return;
 const done=p.tasks.filter(t=>t.column==='done').length;
 $('metrics').append(el('span',`${done} / ${p.tasks.length} accepted or automatic completions`),el('span',`${p.tasks.filter(t=>t.column==='running').length} running`),el('span',`${p.tasks.filter(t=>t.column==='approval').length} awaiting you`));
 for(const [key,label]of columns){const group=p.tasks.filter(t=>key==='attention'?['failed','blocked','partial','unknown'].includes(t.column):t.column===key);const col=el('section',undefined,'column');col.dataset.status=key;const heading=el('h3',label);heading.append(el('span',group.length));col.append(heading);for(const t of group){const card=el('button',undefined,'card');card.append(el('strong',t.id),el('small',t.assignee.replace('research-','')));if(t.after.length)card.append(el('small',`After: ${t.after.join(', ')}`));if(p.paused&&t.status==='ready')card.append(el('small','Project paused for approval'));card.append(el('span',`${t.outputs.filter(o=>o.available).length} outputs · attempt ${t.attempt}`,'pill'));card.onclick=()=>detail(p,t);col.append(card);}$('board').append(col);}
}
function detail(p,t){
 $('task-name').textContent=t.id;$('task-meta').textContent=`Assignee: ${t.assignee}\nStatus: ${t.column}\nWorker: ${t.claimed_by||'not claimed'}\nUpdated: ${t.updated||'—'}\nDependencies: ${t.after.join(', ')||'none'}`;
 $('report').textContent=t.report;$('approval').replaceChildren();$('outputs').replaceChildren();$('preview').hidden=true;
 if(t.approval_command){$('approval').append(el('h3','Review and confirm'),el('p','Send this exact reply in the task’s Mattermost thread. Only the configured human account can approve this version.'),el('pre',t.approval_command));const copy=el('button','Copy approval reply');copy.onclick=async()=>{try{await navigator.clipboard.writeText(t.approval_command);copy.textContent='Copied';}catch{copy.textContent='Select and copy the reply above';}};$('approval').append(copy);}
 if(!t.outputs.length)$('outputs').append(el('p','No outputs recorded yet.'));
 for(const o of t.outputs){const button=el('button',o.path+(o.available?'':' · not produced'));button.disabled=!o.available;button.onclick=async()=>{const url='/api/output?'+new URLSearchParams({project:p.id,path:o.path,commit:p.commit});if(o.path.endsWith('.pdf')){window.open(url,'_blank','noopener');return;}$('preview').hidden=false;$('preview').textContent='Loading…';try{const response=await fetch(url);const text=await response.text();$('preview').textContent=response.ok?text:`Unable to preview: ${text}`;}catch{$('preview').textContent='Board service is unavailable.';}};$('outputs').append(button);}
 $('detail').showModal();
}
async function refresh(){if(busy)return;busy=true;try{const r=await fetch('/api/projects'+($('tests').checked?'?tests=1':''));if(!r.ok)throw Error();snapshot=await r.json();const s=snapshot.service;const age=s.updated?Date.now()-Date.parse(s.updated):Infinity;const healthy=!s.issues?.length&&!s.stopped&&age<60000&&s.children?.length&&s.children.every(c=>c.state==='running');$('health').textContent=healthy?'Team service running':(s.issues?.length?`${s.issues.length} project service issue(s) — check Mattermost`:'Check team service');$('updated').textContent=`Updated ${new Date(snapshot.updated).toLocaleTimeString()} · Automatically refreshes every 10 seconds · Approvals are recorded through Mattermost`;render();}catch{$('health').textContent='Board disconnected';$('updated').textContent='Refresh failed. Displayed data may be stale. Start the team service through the installer.';}finally{busy=false;}}
$('tests').onchange=refresh;$('refresh').onclick=refresh;$('close').onclick=()=>$('detail').close();refresh();setInterval(refresh,10000);
