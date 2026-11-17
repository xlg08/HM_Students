const pages={overview:'平台总览',sources:'数据源中心',jobs:'采集任务',runs:'运行批次',records:'数据资产',review:'质量复核',audit:'操作审计'};
const kinds={jobs:'招聘岗位',products:'商品监测',notices:'政策公告'};
const labels={ACTIVE:'已启用',DRAFT:'待审批',SUSPENDED:'已停用',QUEUED:'排队中',RUNNING:'执行中',PAUSED:'已暂停',CANCELLED:'已取消',SUCCEEDED:'已完成',FAILED:'执行失败',PUBLISHED:'已发布',REVIEW:'待复核',REJECTED:'已驳回'};
let state={sources:[],jobs:[],runs:[],records:[],audit:[]},page='overview',query='',filter='',busy=false;
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=s=>s?new Date(s).toLocaleString('zh-CN',{hour12:false}):'—';
const tag=s=>`<span class="tag ${['ACTIVE','SUCCEEDED','PUBLISHED'].includes(s)?'green':['FAILED','REJECTED','CANCELLED'].includes(s)?'red':'orange'}">${labels[s]||esc(s)}</span>`;
const button=(text,action,id='',cls='secondary')=>`<button class="${cls}" data-action="${action}" data-id="${esc(id)}">${text}</button>`;
const sourceName=id=>esc(state.sources.find(s=>s.id===id)?.name||id);
function toast(s){$('#toast').textContent=s;$('#toast').style.display='block';setTimeout(()=>$('#toast').style.display='none',3500)}
let refreshing=false;
async function api(path,data){
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
 try{
  const headers={'Content-Type':'application/json'};
  if(data!==undefined&&/^jobs\/[^/]+\/runs$/.test(path))headers['Idempotency-Key']=crypto.randomUUID();
  const r=await fetch('/api/v1/'+path,{signal:controller.signal,...(data===undefined?{}:{method:'POST',headers,body:JSON.stringify(data)})});
  const body=await r.json();if(!r.ok)throw Error((body.error?.message||'请求失败')+' · 请求ID '+(body.error?.request_id||r.headers.get('X-Request-ID')));return body;
 }catch(e){if(e.name==='AbortError')throw Error('请求超时，请检查网络；提交任务前请先查看运行批次');throw e}finally{clearTimeout(timeout)}
}
async function refresh(){if(refreshing)return;refreshing=true;try{state=await api('state');const m=state.metrics;$('#connection').textContent=`● 后端已连接 · 工作线程 ${m?.workers??'—'} · 活跃批次 ${m?.active_runs??0}/${m?.capacity??'—'}`;render()}catch(e){$('#connection').textContent='后端连接失败，请检查服务';if(!state.sources.length)$('#content').innerHTML='<div class="panel empty">后端连接失败，请启动 python run.py 后刷新页面。</div>'}finally{refreshing=false}}
function table(headers,rows){return rows.length?`<table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`:'<div class="empty">暂无数据，先到采集任务中执行一次任务。</div>'}
function runsTable(runs){return table(['任务 / 批次','状态','进度','新增记录','操作'],runs.map(r=>`<tr><td>${esc(r.name)}<p>${r.id}</p></td><td>${tag(r.status)}</td><td><progress max="100" value="${r.progress}"></progress>${r.progress}%</td><td>${r.count}</td><td><div class="actions">${button('日志','logs',r.id)}${['RUNNING','QUEUED'].includes(r.status)?button('暂停','pause',r.id):''}${r.status==='PAUSED'?button('恢复','resume',r.id):''}${['RUNNING','QUEUED','PAUSED'].includes(r.status)?button('取消','cancel',r.id,'danger'):''}</div></td></tr>`))}
function render(){
 $('#nav').innerHTML=Object.entries(pages).map(([key,title])=>`<button data-page="${key}" class="${key===page?'active':''}">${title}</button>`).join('');$('#breadcrumb').textContent=pages[page];
 let headAction=page==='sources'?button('＋ 新建数据源','new-source','','primary'):page==='jobs'?button('＋ 创建采集任务','new-job','','primary'):page==='records'?'<a class="button" href="/api/v1/export.csv" download="aicrawl-published.csv">导出已发布 CSV</a>':'';
 let html=`<div class="page-head"><div><h1>${pages[page]}</h1><p>${{overview:'让每一次采集，都有据可循。',sources:'管理本地样本来源与准入状态。',jobs:'配置业务目标，启动端到端数据流水线。',runs:'跟踪执行进度、日志与结果。',records:'检索结构化结果，查看原始证据与数据血缘。',review:'质量异常记录隔离处理；硬性校验失败不可直接发布。',audit:'追溯数据源、任务与复核操作。'}[page]}</p></div>${headAction}</div>`;
 if(page==='overview'){
 const published=state.records.filter(r=>r.status==='PUBLISHED').length,review=state.records.filter(r=>r.status==='REVIEW').length;
 html+=`<div class="cards">${[['启用数据源',state.sources.filter(s=>s.status==='ACTIVE').length,'本地样本来源'],['采集任务',state.jobs.length,'手动触发 · 线程执行'],['已发布记录',published,'已通过规则校验'],['待复核记录',review,'异常数据已隔离']].map(([a,b,c])=>`<div class="card">${a}<strong>${b}</strong><span>${c}</span></div>`).join('')}</div><div class="panel"><h2>数据治理流水线</h2><div class="flow">${['来源准入','任务执行','规则提取','质量校验','发布 / 复核'].map((x,i)=>`${i?'<i>→</i>':''}<span>${x}</span>`).join('')}</div></div><div class="split"><div class="panel"><h2>最近运行</h2>${runsTable(state.runs.slice(0,5))}</div><div class="panel"><h2>开始体验</h2><p>预置三类数据源，每个包含 2 条合格记录和 1 条异常记录。执行后可查看证据、处理复核并导出结果。</p><br>${button('进入采集任务 →','go-jobs','','primary')}<div class="entry">运行环境<small>Python 标准库 / 原生前端 / 内存存储</small></div><div class="entry">AI 与外网采集<small>尚未接入，本版仅验证业务流程</small></div></div></div>`;
 }else if(page==='sources')html+=`<div class="panel">${table(['来源名称','业务类型','模式','状态','操作'],state.sources.map(s=>`<tr><td>${esc(s.name)}<p>${s.id}</p></td><td>${kinds[s.kind]}</td><td>本地样本</td><td>${tag(s.status)}</td><td>${button(s.status==='DRAFT'?'审批启用':s.status==='ACTIVE'?'停用':'重新启用','source-'+(s.status==='DRAFT'?'approve':s.status==='ACTIVE'?'suspend':'resume'),s.id)}</td></tr>`))}</div>`;
 else if(page==='jobs')html+=`<div class="panel">${table(['任务名称','数据源','执行方式','创建时间','操作'],state.jobs.map(j=>`<tr><td>${esc(j.name)}<p>${j.id}</p></td><td>${sourceName(j.source_id)}</td><td>本地样本 · 手动</td><td>${date(j.created_at)}</td><td>${button('▶ 立即运行','start',j.id,'primary')}</td></tr>`))}</div>`;
 else if(page==='runs')html+=`<div class="panel">${runsTable(state.runs)}</div>`;
 else if(page==='records'||page==='review'){
 const records=state.records.filter(r=>(page!=='review'||r.status==='REVIEW')&&(!filter||r.status===filter)&&JSON.stringify(r.payload).toLowerCase().includes(query.toLowerCase()));
 html+=`<div class="toolbar"><input id="search" placeholder="搜索标题、公司、商品…" value="${esc(query)}">${page==='records'?`<select id="filter"><option value="">全部状态</option>${['PUBLISHED','REVIEW','REJECTED'].map(s=>`<option value="${s}" ${filter===s?'selected':''}>${labels[s]}</option>`).join('')}</select>`:''}</div><div class="panel">${table(['记录标题','来源','质量评分¹','状态','操作'],records.map(r=>`<tr><td>${esc(r.payload.title)}<p>${kinds[r.kind]} · ${date(r.created_at)}</p></td><td>${sourceName(r.source_id)}</td><td>${r.score} / 100</td><td>${tag(r.status)}</td><td><div class="actions">${button('详情 / 证据','record',r.id)}${r.status==='REVIEW'?button('复核处理','review',r.id):''}</div></td></tr>`))}<p>¹ 评分表示本地规则完整性，不代表模型置信度或业务准确率。共 ${records.length} 条。</p></div>`;
 }else if(page==='tools')html+=`<div class="panel">${table(['?? / ??','??','????'],(state.tools||[]).map(t=>`<tr><td>${esc(t.name)}</td><td>${t.status==='READY'?'???':t.status==='NOT_INTEGRATED'?'???':'???'}</td><td>${esc(t.detail)}</td></tr>`))}</div>`;
 else html+=`<div class="panel">${table(['时间','操作者','动作','对象','说明'],state.audit.map(a=>`<tr><td>${date(a.at)}</td><td>${esc(a.actor)}</td><td>${esc(a.action)}</td><td>${esc(a.target)}</td><td>${esc(a.detail)}</td></tr>`))}</div>`;
 const focused=document.activeElement?.id,selection=focused==='search'?$('#search').selectionStart:null;
 $('#content').innerHTML=html;if(focused==='search'){$('#search').focus();$('#search').setSelectionRange(selection,selection)}
}
function open(content){$('#dialog-body').innerHTML=content;$('#dialog').showModal()}
function form(type){const isSource=type==='source';open(`<h2>${isSource?'新建本地样本源':'创建采集任务'}</h2><p>${isSource?'选择样本类型；保存后需要审批启用。':'选择已启用来源，保存后手动运行。'}</p><form data-form="${type}"><label>名称</label><input name="name" required maxlength="80" placeholder="输入名称"><label>${isSource?'业务类型':'已启用数据源'}</label><select name="${isSource?'kind':'source_id'}" required>${isSource?Object.entries(kinds).map(([k,v])=>`<option value="${k}">${v}</option>`).join(''):state.sources.filter(s=>s.status==='ACTIVE').map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select><button type="submit">保存${isSource?'草稿':''}</button></form>`)}
document.addEventListener('click',async e=>{
 const nav=e.target.closest('[data-page]');if(nav){page=nav.dataset.page;query='';filter='';render();return}
 const b=e.target.closest('[data-action]');if(!b||busy)return;const {action,id}=b.dataset;
 try{
 if(action==='new-source')return form('source');if(action==='new-job')return form('job');if(action==='go-jobs'){page='jobs';return render()}
 if(action==='record'){const r=state.records.find(r=>r.id===id);return open(`<h2>记录详情与原始证据</h2><p>原始证据独立保留，复核不修改证据。</p><pre>${esc(JSON.stringify(r,null,2))}</pre>`)}
 if(action==='logs'){const r=state.runs.find(r=>r.id===id);return open(`<h2>${esc(r.name)} · 执行日志</h2>${tag(r.status)}<pre>${esc(r.logs.map(l=>date(l.at)+'  '+l.message).join('\n')||'等待执行…')}${r.error?'\n错误：'+esc(r.error):''}</pre><p>关闭后可重新打开以查看最新日志。</p>`)}
 if(action==='review'){const r=state.records.find(r=>r.id===id);return open(`<h2>质量复核</h2><p>${esc(r.payload.title)}</p><pre>${esc(r.issues.join('\n'))}</pre><p>当前存在必填字段或价格硬性错误，请驳回并修复源数据。此版不提供人工覆盖质量门禁。</p><form data-form="review" data-id="${id}"><label>驳回理由</label><textarea name="note" required maxlength="500"></textarea><button type="submit">确认驳回</button></form>`)}
 busy=true;b.disabled=true;
 if(action==='start'){await api(`jobs/${id}/runs`,{});page='runs';toast('任务已提交')}
 else if(action.startsWith('source-')){const source=state.sources.find(s=>s.id===id);if(source.mode==='PUBLIC_API'&&action==='source-approve'){busy=false;return open(`<h2>?? API ????</h2><p>${esc(source.name)} ? ??? PyPI ????????????????</p><form data-form="approval" data-id="${id}"><label>?????????</label><textarea name="note" required maxlength="500" placeholder="?????????????????????? API???????"></textarea><button type="submit">????</button></form>`)}await api(`sources/${id}/${action.slice(7)}`,{});}
 else await api(`runs/${id}/${action}`,{});
 await refresh();
 }catch(err){toast(err.message)}finally{busy=false;b.disabled=false}
});
document.addEventListener('submit',async e=>{const f=e.target;if(!f.dataset.form)return;e.preventDefault();if(busy)return;busy=true;const submit=f.querySelector('button');submit.disabled=true;try{const data=Object.fromEntries(new FormData(f));const type=f.dataset.form;await api(type==='approval'?`sources/${f.dataset.id}/approve`:type==='review'?`records/${f.dataset.id}/review`:type==='source'?'sources':'jobs',type==='review'?{...data,decision:'reject'}:data);$('#dialog').close();toast('保存成功');await refresh()}catch(err){toast(err.message)}finally{busy=false;submit.disabled=false}});
document.addEventListener('input',e=>{if(e.target.id==='search'){query=e.target.value;render()}});
document.addEventListener('change',e=>{if(e.target.id==='filter'){filter=e.target.value;render()}});
$('#close-dialog').onclick=()=>$('#dialog').close();
async function poll(){if(!busy&&!document.hidden)await refresh();setTimeout(poll,1500)}
refresh();setTimeout(poll,1500);
