const select = document.querySelector('#case');
const results = document.querySelector('#results');
const button = document.querySelector('#run');
const mode = document.querySelector('#mode');
let cases = [];
let maintenanceAllowed = true;
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function authUI(authenticated, required=true) {
  document.querySelector('#app-shell').hidden=!authenticated;
}
async function request(url, options) {
  const response = await fetch(url, options);
  if (response.status === 401) {authUI(false,true);}
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status})`); }
  return response.json();
}
function log(title, check) {
  const status=check.evidence_valid === false ? `INCOMPLETE${check.evidence_error?' · '+check.evidence_error.replaceAll('_',' '):''}` : check.exit_code === 0 ? 'PASS' : 'FAIL';
  return `<details><summary>${escape(title)} · ${escape(status)} · ${check.seconds}s</summary><pre>${escape(check.command)}\n\n${escape(check.output)}</pre></details>`;
}
function reportUrl(report) {return report.saved_example ? '/api/examples/' + report.id.replace('example-', '') : '/api/runs/' + encodeURIComponent(report.id) + '/report';}
function render(report) {
  if (report.case === 'repository') {renderProject(report); return;}
  results.innerHTML = `<span class="verdict ${report.verdict !== 'verified' ? 'bad' : ''}">${escape(report.verdict.replaceAll('_',' '))}</span><p class="explanation">${escape(report.explanation)}</p>`;
  if (report.baseline) {
    results.innerHTML += `<h3>01 / Original behavior</h3>${log('Existing tests on original code', report.baseline)}${log('Frozen regression on original code', report.reproduction)}<details><summary>02 / Frozen test and integrity hashes</summary><pre>${escape(report.regression_test)}</pre><p class="hash">${escape(JSON.stringify(report.test_hashes, null, 2))}</p></details>`;
  }
  for (const attempt of report.attempts) {
    if (attempt.rejection || !attempt.regression || !attempt.existing || !attempt.independent) {
      results.innerHTML += `<h3>03 / Attempt ${attempt.number} · Rejected</h3><p>${escape(attempt.rejection || 'Execution evidence unavailable')}</p><pre>${escape(attempt.diff)}</pre>`;
      continue;
    }
    results.innerHTML += `<h3>03 / Attempt ${attempt.number} · ${attempt.accepted ? 'Accepted' : 'Rejected'}</h3><div class="check">Protected tests unchanged <span>${attempt.protected_tests_intact ? 'YES' : 'NO'}</span></div><pre>${escape(attempt.diff)}</pre>${log('Regression', attempt.regression)}${log('Existing suite', attempt.existing)}${log('Independent boundaries', attempt.independent)}`;
  }
  results.innerHTML += `<a class="download" href="${reportUrl(report)}">↓ Download evidence report</a><p class="note">${report.limitations.map(escape).join('<br>')}</p>`;
}
async function history() {
  const runs = await request('/api/runs?summaries=true');
  const host = document.querySelector('#history'); host.replaceChildren();
  for (const report of runs.slice(0, 6)) {
    const item = document.createElement('button'); item.className = 'history';
    item.textContent = `${report.case} · ${report.mode} · ${report.verdict.replaceAll('_', ' ')}`;
    item.onclick = async () => {const detail=await request('/api/runs/'+report.id);render(detail);if(detail.job_id)watchJob(detail.job_id);}; host.append(item);
  }
}
function renderMemory(capsule, score) {
  const evidence=capsule.evidence||{};
  const ai=capsule.ai_index;
  results.innerHTML=`<span class="verdict">memory v${escape(capsule.version)}</span>${score === undefined ? '' : `<span class="memory-score">relevance ${Math.round(score*100)}%</span>`}<h2>${escape(capsule.claim)}</h2><p class="explanation">Repository ${escape(capsule.repository_key)} · created ${escape(new Date(capsule.created_at).toLocaleString())}</p>${ai?`<h3>Agent recall index</h3><p>${escape(ai.summary)}</p><p class="note">${ai.keywords.map(escape).join(' · ')}<br>${escape(ai.model)} · ${escape(ai.role)} role</p>`:''}<h3>Behavioral scope</h3><pre>${escape((capsule.scope.paths||[]).join('\n'))}</pre><h3>Executable evidence</h3><div class="check">Recorded verdict <span>${escape(evidence.verdict)}</span></div><div class="check">Sandbox operations <span>${escape((evidence.operation_ids||[]).length)}</span></div><details><summary>Frozen regression</summary><pre>${escape(evidence.regression?.source||'')}</pre><p class="hash">${escape(evidence.regression?.sha256||'')}</p></details><h3>Known boundaries</h3><p class="note">${(capsule.risk_boundaries||[]).map(escape).join('<br>')}</p><p class="note">Memory is evidence linked to its original run; it is not a universal correctness claim.</p>`;
  if(!ai){const enrich=document.createElement('button');enrich.textContent='Build agent recall index with Nemotron Nano →';enrich.onclick=async()=>{enrich.disabled=true;enrich.textContent='Building bounded recall index…';try{renderMemory(await request(`/api/memories/${encodeURIComponent(capsule.id)}/enrich`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({authorize_nebius:true})}));await refreshMemories();}catch(error){enrich.textContent=error.message;enrich.disabled=false;}};results.append(enrich);}
}
async function refreshMemories() {
  const host=document.querySelector('#memories');host.replaceChildren();
  for(const capsule of await request('/api/memories')){
    const item=document.createElement('button');item.className='history';item.textContent=`v${capsule.version} · ${capsule.claim.slice(0,55)}`;
    item.onclick=()=>renderMemory(capsule);host.append(item);
  }
  const budget=await request('/api/budget');
  document.querySelector('#budget').textContent=`$${budget.remaining_spendable_usd.toFixed(2)} spendable credit remaining · $${budget.protected_reserve_usd.toFixed(2)} protected`;
}
document.querySelector('#search-memory').onclick=async()=>{
  const query=document.querySelector('#memory-query').value.trim();
  if(!query){results.textContent='Describe the proposed change or affected behavior.';return;}
  try {
    const semantic=document.querySelector('#semantic-memory').checked;
    const response=await request('/api/memories/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,semantic,authorize_nebius:semantic})});
    const matches=Array.isArray(response)?response:response.results;
    results.innerHTML=`<h2>Recalled behavior</h2><p class="explanation">${matches.length} relevant Memory Capsule${matches.length===1?'':'s'} found${response.model?' with '+escape(response.model):' using free lexical retrieval'}.</p>`;
    for(const match of matches){const card=document.createElement('button');card.className='history memory-card';card.textContent=`${Math.round(match.score*100)}% · ${match.capsule.claim}`;card.onclick=()=>renderMemory(match.capsule,match.score);results.append(card);}
    if(!matches.length)results.insertAdjacentHTML('beforeend','<p class="note">No stored behavior matched this change. Create memory from a completed investigation first.</p>');
    await refreshMemories();
  } catch(error) {results.textContent=error.message;}
};
select.onchange = () => document.querySelector('#issue').textContent = cases.find(c => c.id === select.value).issue;
mode.onchange = () => document.querySelector('#mode-note').textContent = mode.value === 'demo' ? 'Demo uses prewritten patches and tests.' : 'Generates an arithmetic pricing repair and verifies it remotely. Requires configured sandbox access and a Python image with pytest. Scenario patch scripts apply only to demo mode.';
button.onclick = async () => {
  button.disabled = true; button.textContent = 'Executing checks…';
  results.innerHTML = '<p class="explanation">Checking the original failure and repair candidates. Remote checks can take several minutes…</p>';
  try {render(await request('/api/runs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({case: select.value, mode: mode.value})})); await history();}
  catch(error) {results.textContent = error.message;}
  finally {button.disabled = false; button.textContent = 'Run verification →';}
};
(async () => {
  try {
    cases = await request('/api/cases');
    for (const item of cases) {const option = document.createElement('option'); option.value = item.id; option.textContent = item.title; select.append(option);}
    select.value = 'reject'; select.onchange(); await history();
  } catch(error) {results.textContent = error.message;}
})();

let watchedJob = null;
function renderProject(report) {
  watchedJob = null;
  results.dataset.runId=report.id;
  const positive=['checks_passed','memory_preserved'].includes(report.verdict);
  results.innerHTML = `<span class="verdict ${positive?'':'bad'}">${escape(report.verdict.replaceAll('_',' '))}</span><p class="explanation">${escape(report.explanation)}</p>${report.job_id?'<section id="execution-evidence" class="execution-evidence"><p class="note">Loading the recorded execution timeline…</p></section>':''}<h3>Included files</h3>`;
  if (report.pipeline && !report.verification) {results.innerHTML += '<h3>Original behavior</h3>';for(const [name,check] of Object.entries(report.pipeline))results.innerHTML += log(name.replaceAll('_',' '),check);for(const attempt of report.attempts || []){results.innerHTML += `<h3>Candidate ${attempt.number} · ${attempt.accepted?'Accepted':'Rejected'}</h3>`;if(attempt.diff)results.innerHTML += `<pre>${escape(attempt.diff)}</pre>`;if(attempt.rejection)results.innerHTML += `<p>${escape(attempt.rejection)}</p>`;for(const [name,check] of Object.entries(attempt.checks||{}))results.innerHTML += log(name,check);}}
  if (report.verification) { results.innerHTML += '<h3>Execution evidence</h3>'; for (const [name,check] of Object.entries(report.verification)) results.innerHTML += log(name.replaceAll('_',' '),check); }
  if(report.memory_audit){results.innerHTML+='<h3>Recalled behavioral memory</h3>';if(report.memory_audit.baseline)results.innerHTML+=log('Proposed revision baseline',report.memory_audit.baseline);for(const item of report.memory_audit.results){results.innerHTML+=`<div class="memory-card"><span class="verdict ${item.status==='preserved'?'':'bad'}">${escape(item.status)}</span><h3>${escape(item.claim)}</h3>${log('Historical regression replay',item.check)}</div>`;}if(report.memory_audit.analysis){const analysis=report.memory_audit.analysis;results.innerHTML+=`<h3>Risk-adaptive model analysis</h3><div class="memory-card"><strong>Nemotron Super · ${escape(analysis.engineering.risk)} risk</strong><p>${escape(analysis.engineering.summary)}</p><p class="note">Likely cause: ${escape(analysis.engineering.likely_cause)}<br>Next experiment: ${escape(analysis.engineering.next_experiment)}</p></div>`;if(analysis.reasoning)results.innerHTML+=`<div class="memory-card"><strong>Nemotron Ultra escalation · ${escape(analysis.reasoning.decision.replaceAll('_',' '))}</strong><p>${escape(analysis.reasoning.rationale)}</p><p class="note">Next experiment: ${escape(analysis.reasoning.next_experiment)}<br>Unresolved: ${analysis.reasoning.unresolved.map(escape).join('; ')}</p></div>`;}}
  for (const [name, source] of Object.entries({...report.sources, ...report.existing_tests, ...report.dependency_manifests, ...(report.resources || {})})) {
    const wrapper = document.createElement('details'); wrapper.className = 'file-review';
    const summary = document.createElement('summary'); summary.textContent = name;
    const pre = document.createElement('pre'); pre.textContent = source;
    wrapper.append(summary, pre); results.append(wrapper);
  }
  if (report.excluded_files.length) results.innerHTML += `<details><summary>Excluded files</summary><pre>${escape(report.excluded_files.join('\n'))}</pre></details>`;
  if (report.generated_regression) results.innerHTML += `<h3>Frozen generated regression</h3><pre>${escape(report.generated_regression.source)}</pre>`;
  if(report.verification && (report.attempts||[]).length>1){results.innerHTML += '<h3>Repair revisions</h3>';for(const attempt of report.attempts){results.innerHTML += `<details><summary>Candidate ${attempt.number} · ${attempt.accepted?'Accepted':'Not accepted'}</summary><pre>${escape(attempt.diff||attempt.rejection||'')}</pre>${Object.entries(attempt.checks||{}).map(([name,check])=>log(name,check)).join('')}</details>`;}}
  if (report.draft_diff) results.innerHTML += `<h3>Candidate patch</h3><pre>${escape(report.draft_diff)}</pre><a class="download" href="${report.saved_example ? '/api/examples/' + report.id.replace('example-','') + '/artifacts' : '/api/runs/' + encodeURIComponent(report.id) + '/artifacts'}">↓ Download repair draft</a><br>`;
  results.innerHTML += `<a class="download" href="${reportUrl(report)}">↓ Download inspection report</a><p class="note">${report.limitations.map(escape).join('<br>')}</p>`;
  if (report.saved_example) results.insertAdjacentHTML('afterbegin','<p class="note">Saved evidence from a real completed run. Viewing this makes no model or sandbox calls.</p>');
  if(report.verdict==='checks_passed'&&(!report.saved_example||maintenanceAllowed)){
    const remember=document.createElement('button');remember.textContent='Create executable Memory Capsule';
    remember.onclick=async()=>{remember.disabled=true;try{const endpoint=report.saved_example?'/api/examples/'+report.id.replace('example-','')+'/memory':'/api/runs/'+encodeURIComponent(report.id)+'/memory';const capsule=await request(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});renderMemory(capsule);await refreshMemories();}catch(error){remember.disabled=false;remember.textContent=error.message;}};
    results.append(remember);
  }
  if (report.verdict === 'awaiting_sandbox' && !report.saved_example) {
    const consent = document.createElement('label'); consent.className = 'consent';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
    consent.append(checkbox,document.createTextNode('Run this project and candidate in disposable Nebius Sandboxes with networking disabled. Up to six paid operations.'));
    const verify = document.createElement('button'); verify.textContent = 'Run remote verification →'; verify.disabled = true;
    checkbox.onchange = () => {verify.disabled = !checkbox.checked;};
    verify.onclick = async () => {
      verify.disabled = true; verify.textContent = 'Verifying remotely…';
      try {renderProject(await request(`/api/projects/${encodeURIComponent(report.id)}/verify`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({execute_remote:true})})); await history();}
      catch(error) { const message = document.createElement('p');message.textContent=error.message;results.append(message); }
    };
    results.append(consent,verify);
  }
  if(!report.saved_example&&maintenanceAllowed){const remove=document.createElement('button');remove.className='history';remove.textContent='Delete investigation data';remove.onclick=async()=>{if(!window.confirm('Delete this investigation and its stored source/evidence?'))return;const response=await fetch('/api/runs/'+encodeURIComponent(report.id),{method:'DELETE'});if(response.ok){results.textContent='Investigation deleted.';await history();await refreshJobs();}else{const error=await response.json();window.alert(error.detail);}};results.append(remove);}
  if (report.verdict === 'awaiting_model') {
    const scope=document.createElement('div');scope.innerHTML='<h3>Repair context</h3><p class="note">Choose relevant implementation files. Other project files still execute, but cannot be modified by the model.</p>';
    let contextSize=0;
    for(const [name,source] of Object.entries(report.sources)){
      const label=document.createElement('label');label.className='holdout';
      const input=document.createElement('input');input.type='checkbox';input.value=name;input.checked=contextSize+source.length<24000;
      if(input.checked)contextSize+=source.length;
      label.append(input,document.createTextNode(name+' ('+source.length+' chars)'));scope.append(label);
    }
    const holdouts = document.createElement('div');
    if (Object.keys(report.existing_tests).length) {
      holdouts.innerHTML = '<h3>Reserve independent checks</h3><p class="note">Selected test contents will stay out of both model requests.</p>';
      for (const name of Object.keys(report.existing_tests)) {
        const label = document.createElement('label'); label.className = 'holdout';
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = name;
        label.append(checkbox, document.createTextNode(name)); holdouts.append(label);
      }
    }
    const consent = document.createElement('label'); consent.className = 'consent';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
    consent.append(checkbox, document.createTextNode('Send the selected project context to Nebius, prepare wheel-only dependencies, and execute this project remotely. The investigation can continue through five repair attempts while shared project credit remains.'));
    const generate = document.createElement('button'); generate.textContent = 'Start full investigation →'; generate.disabled = true;
    checkbox.onchange = () => {generate.disabled = !checkbox.checked;};
    generate.onclick = async () => {
      generate.disabled = true; generate.textContent = 'Queueing investigation…';
      try {
        const paths = [...holdouts.querySelectorAll('input:checked')].map(item => item.value);
        const job = await request(`/api/projects/${encodeURIComponent(report.id)}/investigate`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({send_to_nebius:true,execute_remote:true,prepare_dependencies:true,independent_test_paths:paths,budget_usd:25,max_repairs:5,max_model_calls:12,max_sandbox_calls:40,source_paths:[...scope.querySelectorAll('input:checked')].map(item=>item.value)})});
        watchJob(job.id); await refreshJobs();
      } catch (error) {
        const message = document.createElement('p'); message.textContent = error.message; results.append(message);
        generate.textContent = 'Refresh investigation'; generate.disabled = false;
        generate.onclick = async () => {renderProject(await request(`/api/runs/${encodeURIComponent(report.id)}`));};
      }
    };
    results.append(scope,holdouts,consent,generate);
    attachMemoryAudit(report);
  }
  if(report.job_id)attachExecutionEvidence(report);
}
function collectOperations(report){
  const operations=[];
  const add=(phase,check)=>{if(!check||!check.operation_id)return;const summary=check.summary||{};operations.push({phase,check,tests:summary.tests??null});};
  add('Environment · wheel dependencies',report.environment);
  for(const [name,check] of Object.entries(report.pipeline||{}))add('Original · '+name.replaceAll('_',' '),check);
  for(const attempt of report.attempts||[])for(const [name,check] of Object.entries(attempt.checks||{}))add('Candidate '+attempt.number+' · '+name.replaceAll('_',' '),check);
  return operations;
}
async function attachExecutionEvidence(report){
  const host=document.querySelector('#execution-evidence');if(!host||results.dataset.runId!==report.id)return;
  try{
    const job=await request('/api/jobs/'+encodeURIComponent(report.job_id));if(!host.isConnected||results.dataset.runId!==report.id)return;
    const operations=collectOperations(report);
    const models=(report.model_requests||[]).map(item=>`<article class="model-call"><span>${escape(item.role||'model')}</span><strong>${escape(item.model||'unknown model')}</strong><small>${Number(item.prompt_tokens||0).toLocaleString()} input · ${Number(item.completion_tokens||0).toLocaleString()} output tokens · ${escape(item.finish_reason||'complete')}</small></article>`).join('');
    const operationCards=operations.map(item=>{const passed=item.check.evidence_valid!==false&&item.check.status==='SUCCESS';return `<article class="operation-card"><div><span class="operation-state ${passed?'':'failed'}">${passed?'verified':'expected failure'}</span><strong>${escape(item.phase)}</strong></div><p>${item.tests===null?'Executable check':item.tests+' tests'} · ${Number(item.check.seconds||0).toFixed(2)} seconds · network disabled</p><code>${escape(item.check.operation_id)}</code></article>`;}).join('');
    const events=(job.events||[]).map((event,index)=>`<li><span>${String(index+1).padStart(2,'0')}</span>${escape(event.stage.replaceAll('_',' '))}</li>`).join('');
    host.innerHTML=`<div class="evidence-heading"><div><span class="eyebrow">Recorded live execution</span><h2>Execution timeline</h2></div><span class="execution-status">${escape(job.state)}</span></div><p class="execution-usage">${job.model_calls} model calls · ${job.sandbox_calls} Nebius Sandbox operations · $${Number(job.reserved_usd).toFixed(3)} reserved allowance</p>${models?`<h3>Model routing</h3><div class="model-calls">${models}</div>`:''}<h3>Sandbox gates</h3><div class="operation-grid">${operationCards}</div><details class="stage-ledger"><summary>All ${job.events?.length||0} recorded workflow stages</summary><ol>${events}</ol></details>`;
  }catch(error){host.innerHTML=`<p class="note">Execution timeline unavailable: ${escape(error.message)}</p>`;}
}
async function attachMemoryAudit(report){
  try{
    const response=await request('/api/memories/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:report.issue,repository_key:report.repository?.full_name||null,limit:5})});
    if(!response.length||results.dataset.runId!==report.id)return;
    const host=document.createElement('section');host.innerHTML='<h3>Audit against executable memory</h3><p class="note">Replay selected historical behaviors on this proposed revision. No repair model is called.</p>';
    for(const match of response){const label=document.createElement('label');label.className='holdout';const input=document.createElement('input');input.type='checkbox';input.value=match.capsule.id;input.checked=true;label.append(input,document.createTextNode(`${Math.round(match.score*100)}% · ${match.capsule.claim}`));host.append(label);}
    const consent=document.createElement('label');consent.className='consent';const checkbox=document.createElement('input');checkbox.type='checkbox';consent.append(checkbox,document.createTextNode('Run selected historical regressions in fresh Nebius Sandboxes while shared project credit remains.'));
    const run=document.createElement('button');run.textContent='Replay repository memory →';run.disabled=true;checkbox.onchange=()=>{run.disabled=!checkbox.checked;};
    run.onclick=async()=>{run.disabled=true;try{const memory_ids=[...host.querySelectorAll('.holdout input:checked')].map(item=>item.value);const job=await request(`/api/projects/${encodeURIComponent(report.id)}/audit-memory`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({memory_ids,execute_remote:true,prepare_dependencies:true,max_sandbox_calls:20,max_model_calls:4,budget_usd:25,analyze_conflict:true,allow_ultra:true})});watchJob(job.id);await refreshJobs();}catch(error){run.textContent=error.message;run.disabled=false;}};
    host.append(consent,run);results.append(host);
  }catch(error){console.error(error.message);}
}
document.querySelector('#inspect-project').onclick = async () => {
  const control = document.querySelector('#inspect-project');
  const file = document.querySelector('#repository').files[0];
  const repositoryUrl = document.querySelector('#repository-url').value.trim();
  const ref = document.querySelector('#repository-ref').value.trim() || 'HEAD';
  const issue = document.querySelector('#bug-report').value.trim();
  if ((!file && !repositoryUrl) || !issue) {results.textContent = 'Provide a public GitHub repository or ZIP and describe the expected behavior.'; return;}
  if (file && repositoryUrl) {results.textContent = 'Choose either the GitHub repository or ZIP for this investigation.'; return;}
  if (file && file.size > 10000000) {results.textContent = 'Archive exceeds the 10 MB upload limit.'; return;}
  control.disabled = true;
  try {const report=repositoryUrl?await request('/api/projects/github',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repository_url:repositoryUrl,issue,ref})}):await request('/api/projects?issue=' + encodeURIComponent(issue), {method:'POST',headers:{'Content-Type':'application/zip'},body:file});renderProject(report);await history();}
  catch(error) {results.textContent = error.message;}
  finally {control.disabled = false;}
};

(async () => {
  try {
    const host = document.querySelector('#saved-examples');
    for (const example of await request('/api/examples')) {
      const control=document.createElement('button'); control.className='history';control.textContent=example.title;
      control.onclick=async()=>{try{render(await request('/api/examples/'+example.id));}catch(error){results.textContent=error.message;}};
      host.append(control);
    }
  } catch(error) {console.error(error.message);}
})();

async function refreshJobs() {
  const host=document.querySelector('#jobs');host.replaceChildren();
  for (const job of (await request('/api/jobs')).slice(0,8)) {
    const control=document.createElement('button');control.className='history';control.textContent=job.state+' · '+job.stage.replaceAll('_',' ');
    control.onclick=async()=>{render(await request('/api/runs/'+job.run_id));watchJob(job.id);};host.append(control);
  }
}
async function watchJob(id) {
  watchedJob=id;
  async function poll() {
    if(watchedJob!==id)return;
    try {
      const job=await request('/api/jobs/'+id);
      let host=document.querySelector('#job-progress');
      if(!host){host=document.createElement('section');host.id='job-progress';results.prepend(host);}
      host.replaceChildren();
      const heading=document.createElement('h3');heading.textContent=job.state+' · '+job.stage.replaceAll('_',' ');
      const usage=document.createElement('p');usage.className='note';usage.textContent=`${job.model_calls}/${job.options.max_model_calls} model calls · ${job.sandbox_calls}/${job.options.max_sandbox_calls} sandbox calls · $${job.reserved_usd.toFixed(3)} / $${job.options.budget_usd.toFixed(2)} reserved allowance`;
      host.append(heading,usage);
      if(job.events && job.events.length){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Completed stages';const pre=document.createElement('pre');pre.textContent=job.events.map(event=>new Date(event.created*1000).toLocaleTimeString()+' · '+event.stage.replaceAll('_',' ')).join('\n');details.append(summary,pre);host.append(details);}
      if(['queued','running'].includes(job.state)){
        const cancel=document.createElement('button');cancel.textContent=job.cancel_requested?'Cancellation requested…':'Cancel investigation';cancel.disabled=Boolean(job.cancel_requested);
        cancel.onclick=async()=>{await request('/api/jobs/'+id+'/cancel',{method:'POST'});};host.append(cancel);
        setTimeout(poll,1500);
      } else {
        render(await request('/api/runs/'+job.run_id));
        const terminal=document.createElement('p');terminal.className='note';terminal.textContent=`Job ${job.state}. Reserved allowance: $${job.reserved_usd.toFixed(3)}. Usage and completed checkpoints remain in the report.`;results.prepend(terminal);
        if(['interrupted','failed'].includes(job.state)){
          const resume=document.createElement('button');resume.textContent='Resume from completed checkpoints';resume.onclick=async()=>{await request('/api/jobs/'+id+'/resume',{method:'POST'});watchJob(id);};results.prepend(resume);
        }
        if(job.state==='completed'){
          const detail=await request('/api/runs/'+job.run_id);
          if(detail.verdict==='needs_clarification'){
            const answer=document.createElement('textarea');answer.placeholder='Clarify the expected behavior';answer.maxLength=2000;
            const send=document.createElement('button');send.textContent='Submit clarification and resume';send.onclick=async()=>{await request('/api/jobs/'+id+'/clarify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answer:answer.value})});watchJob(id);};results.prepend(answer,send);
          }
        }
        await history();await refreshJobs();
      }
    } catch(error){const message=document.createElement('p');message.textContent=error.message;results.prepend(message);}
  }
  await poll();
}
(async()=>{try{const status=await request('/api/health');maintenanceAllowed=!['public','judge'].includes(status.access_role);authUI(status.authenticated,status.authentication_required);if(status.authenticated){await refreshJobs();await refreshMemories();}}catch{authUI(false,true);}})();
