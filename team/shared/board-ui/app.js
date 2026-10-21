const $=id=>document.getElementById(id);
const route=new URLSearchParams(location.search);
let snapshot=null,selected=null,busy=false,view=route.get('view')==='checks'||route.get('project')?.startsWith('_selftest-')?'checks':'research',requested=route.get('project');
const checkNames={'t-author':'원고 작성','t-librarian':'문헌 검색','t-experimenter':'실행 환경','t-reviewer':'독립 심사'};
const checkStates={passed:'설치 확인 통과',incomplete:'설치 확인 미완료',running:'최종 검증 진행 중',unconfirmed:'최종 통과 여부 미확인'};
const columns=[['ready','Queued'],['running','Running'],['approval','Awaiting approval'],['done','Done'],['attention','Needs attention']];
function title(p){const m=p.name.match(/^_selftest-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/);return m?`설치 확인 · ${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}`:p.name;}
function selectProject(p){selected=p.id;requested=null;history.replaceState(null,'','?'+new URLSearchParams({view,project:p.name}));render();}
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function render(){
 if(!snapshot)return;
 const projects=snapshot.projects.filter(p=>Boolean(p.test)===(view==='checks')).sort((a,b)=>view==='checks'?b.name.localeCompare(a.name):a.name.localeCompare(b.name));
 if(requested){selected=projects.find(p=>p.name===requested)?.id;}else if(!projects.some(p=>p.id===selected))selected=projects[0]?.id;
 $('research-view').setAttribute('aria-pressed',String(view==='research'));$('checks-view').setAttribute('aria-pressed',String(view==='checks'));
 $('projects').replaceChildren();
 for(const p of projects){const b=el('button',title(p),p.id===selected?'active':'');b.append(el('small',p.test?(checkStates[p.check?.outcome]||'최종 통과 여부 미확인'):`${p.tasks.length} tasks${p.paused?' · decision needed':''}`));b.onclick=()=>selectProject(p);$('projects').append(b);}
 $('workspace').textContent=snapshot.workspace;
 const p=projects.find(p=>p.id===selected);$('board').replaceChildren();$('metrics').replaceChildren();
 $('name').textContent=p?title(p):(requested?'Requested project is not available yet':view==='checks'?'설치 확인 기록이 없습니다':'No research projects yet');$('source').textContent=p?`${p.source||''} · ${p.commit?.slice(0,10)||''}`:'';
 $('banner').textContent=p?.error||(p?.test?`${checkStates[p.check?.outcome]||'최종 통과 여부 미확인'} — ${p.check?.phase||'최종 설치 확인 기록이 없습니다.'}${p.check?.error?'\n상세 원인: '+p.check.error:''}`:p?.paused?'Your decision is needed. New tasks are paused until the checkpoint is approved.':'');
 $('empty').hidden=Boolean(p?.tasks.length);
 $('empty').textContent=requested&&!p?'The linked project has not appeared yet. This page will retry automatically; choose another project to switch.':view==='checks'?'설치기에서 연구팀 업데이트를 실행하면 확인 작업이 여기에 표시됩니다.':'This project has no tasks. Ask research-lead in Mattermost to plan a project. Installation results are in Installation checks.';
 if(!p)return;
 const done=p.tasks.filter(t=>t.column==='done').length;
 $('metrics').append(el('span',p.test?`역할 작업 ${done} / ${p.tasks.length} 완료 · 최종 설치 검증은 위 상태를 확인하세요`:`${done} / ${p.tasks.length} accepted or automatic completions`),el('span',`${p.tasks.filter(t=>t.column==='running').length} running`),el('span',`${p.tasks.filter(t=>t.column==='approval').length} awaiting you`));
 for(const [key,label]of columns){const group=p.tasks.filter(t=>key==='attention'?['failed','blocked','partial','unknown'].includes(t.column):t.column===key);const col=el('section',undefined,'column');col.dataset.status=key;const heading=el('h3',p.test?({ready:'대기',running:'진행 중',approval:'사용자 확인 대기',done:'완료',attention:'확인 필요'}[key]):label);heading.append(el('span',group.length));col.append(heading);for(const t of group){const card=el('button',undefined,'card');card.append(el('strong',p.test?checkNames[t.id]||t.id:t.id),el('small',t.assignee.replace('research-','')));if(t.after.length)card.append(el('small',`After: ${t.after.join(', ')}`));if(p.paused&&t.status==='ready')card.append(el('small','Project paused for approval'));card.append(el('span',`${t.outputs.filter(o=>o.available).length} outputs · attempt ${t.attempt}`,'pill'));card.onclick=()=>detail(p,t);col.append(card);}$('board').append(col);}
}
function detail(p,t){
 $('task-name').textContent=t.id;$('task-meta').textContent=`Assignee: ${t.assignee}\nStatus: ${t.column}\nWorker: ${t.claimed_by||'not claimed'}\nUpdated: ${t.updated||'—'}\nDependencies: ${t.after.join(', ')||'none'}`;
 $('report').textContent=t.report;$('approval').replaceChildren();$('outputs').replaceChildren();$('preview').hidden=true;
 if(t.approval_command){$('approval').append(el('h3','Review and confirm'),el('p','Send this exact reply in the task’s Mattermost thread. Only the configured human account can approve this version.'),el('pre',t.approval_command));const copy=el('button','Copy approval reply');copy.onclick=async()=>{try{await navigator.clipboard.writeText(t.approval_command);copy.textContent='Copied';}catch{copy.textContent='Select and copy the reply above';}};$('approval').append(copy);}
 if(!t.outputs.length)$('outputs').append(el('p','No outputs recorded yet.'));
 for(const o of t.outputs){const button=el('button',o.path+(o.available?'':' · not produced'));button.disabled=!o.available;button.onclick=async()=>{const url='/api/output?'+new URLSearchParams({project:p.id,path:o.path,commit:p.commit});if(o.path.endsWith('.pdf')){window.open(url,'_blank','noopener');return;}$('preview').hidden=false;$('preview').textContent='Loading…';try{const response=await fetch(url);const text=await response.text();$('preview').textContent=response.ok?text:`Unable to preview: ${text}`;}catch{$('preview').textContent='Board service is unavailable.';}};$('outputs').append(button);}
 $('detail').showModal();
}
async function refresh(){if(busy)return;busy=true;const loadingView=view;try{const r=await fetch('/api/projects'+(view==='checks'?'?tests=1&view=checks':''));if(!r.ok)throw Error();const data=await r.json();if(loadingView!==view)return;snapshot=data;const s=snapshot.service;const age=s.updated?Date.now()-Date.parse(s.updated):Infinity;const healthy=!s.issues?.length&&!s.stopped&&age<60000&&s.children?.length&&s.children.every(c=>c.state==='running');$('health').textContent=healthy?'Team service running':(s.issues?.length?`${s.issues.length} project service issue(s) — check Mattermost`:'Check team service');$('updated').textContent=`Updated ${new Date(snapshot.updated).toLocaleTimeString()} · Automatically refreshes every 10 seconds · Approvals are recorded through Mattermost`;render();}catch{$('health').textContent='Board disconnected';$('updated').textContent='Refresh failed. Displayed data may be stale. Start the team service through the installer.';}finally{busy=false;if(loadingView!==view)refresh();}}
function switchView(next){view=next;selected=null;requested=null;snapshot=null;$('board').replaceChildren();$('projects').replaceChildren();$('metrics').replaceChildren();$('banner').textContent='';$('name').textContent='Loading…';history.replaceState(null,'','?'+new URLSearchParams({view}));refresh();}
$('research-view').onclick=()=>switchView('research');$('checks-view').onclick=()=>switchView('checks');$('refresh').onclick=refresh;$('close').onclick=()=>$('detail').close();refresh();setInterval(refresh,10000);
