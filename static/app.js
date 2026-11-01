async function api(url,method='POST',body=null){const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):null});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||'Something went wrong');return d}
function closeModal(id){document.getElementById(id).classList.remove('show')}
async function toggleTask(id,status){try{await api('/api/tasks/'+id,'PATCH',{status:status==='Done'?'To do':'Done'});location.reload()}catch(e){alert(e.message)}}
async function deleteItem(url){if(!confirm('Delete this item?'))return;try{await api(url,'DELETE');location.reload()}catch(e){alert(e.message)}}
async function submitTask(e){e.preventDefault();const d=Object.fromEntries(new FormData(e.target));try{await api('/api/tasks','POST',d);location.reload()}catch(x){alert(x.message)}}
async function submitIdea(e){e.preventDefault();const d=Object.fromEntries(new FormData(e.target));try{await api('/api/ideas','POST',d);location.reload()}catch(x){alert(x.message)}}
async function submitCampaign(e){e.preventDefault();const d=Object.fromEntries(new FormData(e.target));try{await api('/api/campaigns','POST',d);location.reload()}catch(x){alert(x.message)}}
async function generateIdeas(btn){btn.disabled=true;btn.textContent='Generating…';try{const d=await api('/api/ideas/generate','POST',{niche:document.getElementById('niche').value||'your niche',audience:document.getElementById('audience').value||'your audience'});location.reload()}catch(e){alert(e.message);btn.disabled=false;btn.textContent='✳ Generate ideas'}}
async function syncGmail(btn){btn.disabled=true;btn.textContent='Syncing…';try{const d=await api('/gmail/sync');alert(`Synced ${d.synced} new messages.`);location.reload()}catch(e){alert(e.message);btn.disabled=false;btn.textContent='↻ Sync Gmail'}}
async function analyzePastedEmail(btn){const text=document.getElementById('email-text').value;if(!text.trim())return alert('Paste an email first.');btn.disabled=true;try{const d=await api('/api/email-suggestions','POST',{text});document.getElementById('email-results').innerHTML='<div class="suggestion-box"><b>Suggested tasks ('+d.suggestions.length+')</b>'+(d.suggestions.length?'<ul>'+d.suggestions.map(x=>'<li>'+escapeHtml(x)+'</li>').join('')+'</ul>':'<p>No obvious action items found.</p>')+'<small>'+d.created.length+' task(s) added to your task board. Review them before acting.</small></div>'; }catch(e){alert(e.message)}finally{btn.disabled=false}}
async function processEmail(id,btn){
  btn.disabled=true; const old=btn.textContent; btn.textContent='Checking…';
  try{
    const response=await fetch('/gmail/actions/'+id); const data=await response.json();
    if(!response.ok) throw new Error(data.error||'Could not analyse this email.');
    const actions=data.actions||[];
    if(!actions.length){alert('No clear action items were found in the synced email snippet.');return;}
    const lines=actions.map((a,i)=>`${i+1}. ${a.title}\n   Priority: ${a.priority} | Due: ${a.due_date||'Not detected'}`).join('\n\n');
    const answer=prompt(`Review suggested tasks from: ${data.email_subject}\n\n${lines}\n\nEnter the numbers to add, separated by commas (example: 1,3). Leave blank to cancel.`,'1');
    if(!answer || !answer.trim()) return;
    const approved=[...new Set(answer.split(',').map(x=>parseInt(x.trim(),10)-1).filter(x=>Number.isInteger(x)&&x>=0&&x<actions.length))];
    if(!approved.length){alert('No valid task numbers selected.');return;}
    const result=await api('/gmail/process/'+id,'POST',{approved});
    alert(`Added ${result.created.length} approved task(s) to your task board. Please verify any detected dates.`);
    location.reload();
  }catch(e){alert(e.message)}finally{btn.disabled=false;btn.textContent=old;}
}
function escapeHtml(s){return s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function applyTheme(theme){document.documentElement.setAttribute('data-theme',theme);try{localStorage.setItem('creatoros-theme',theme)}catch(e){}}
function toggleTheme(){const current=document.documentElement.getAttribute('data-theme')||'light';applyTheme(current==='light'?'dark':'light')}
(function(){try{applyTheme(localStorage.getItem('creatoros-theme')||'light')}catch(e){}})();

// Hamburger navigation
function toggleSidebar(){const open=document.body.classList.toggle('sidebar-open');const btn=document.getElementById('menuToggle');if(btn){btn.setAttribute('aria-expanded',String(open));btn.setAttribute('aria-label',open?'Close navigation menu':'Open navigation menu')}}
function closeSidebar(){document.body.classList.remove('sidebar-open');const btn=document.getElementById('menuToggle');if(btn){btn.setAttribute('aria-expanded','false');btn.setAttribute('aria-label','Open navigation menu')}}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeSidebar()});
document.addEventListener('click',e=>{if(e.target.closest('#appSidebar a'))closeSidebar()});

let activeReplyDraftId=null;
function showReplyDraft(d){activeReplyDraftId=d.id;document.getElementById('reply-editor').hidden=false;document.getElementById('draft-to').value=d.recipient||'';document.getElementById('draft-subject').value=d.subject||'';document.getElementById('draft-body').value=d.body||'';const send=document.getElementById('approve-send');send.disabled=!d.send_ready;document.getElementById('reply-status').textContent=d.send_ready?'Review the recipient, subject and full message. Nothing is sent until you click Approve & Send.':'Manual/demo draft: copy it into your email app. Sending is not available for this draft.';document.getElementById('reply-editor').scrollIntoView({behavior:'smooth',block:'nearest'})}
async function draftManualReply(btn){const message=document.getElementById('reply-source').value;if(!message.trim())return alert('Paste the original email first.');btn.disabled=true;try{const d=await api('/api/email-reply/manual','POST',{recipient:document.getElementById('reply-recipient').value,subject:document.getElementById('reply-subject').value,message});showReplyDraft(d)}catch(e){alert(e.message)}finally{btn.disabled=false}}
async function draftEmailReply(id,btn){btn.disabled=true;try{const d=await api('/api/email-reply/'+id);showReplyDraft(d)}catch(e){alert(e.message)}finally{btn.disabled=false}}
async function copyReplyDraft(){const text=`To: ${document.getElementById('draft-to').value}\nSubject: ${document.getElementById('draft-subject').value}\n\n${document.getElementById('draft-body').value}`;try{await navigator.clipboard.writeText(text);alert('Reply draft copied.')}catch(e){alert('Clipboard access unavailable. Select and copy the draft manually.')}}
async function approveAndSendReply(){if(!activeReplyDraftId)return;const send=document.getElementById('approve-send');if(!confirm('Send this exact reply now? Please review the recipient and message first.'))return;send.disabled=true;try{await api('/api/email-reply/'+activeReplyDraftId,'PATCH',{recipient:document.getElementById('draft-to').value,subject:document.getElementById('draft-subject').value,body:document.getElementById('draft-body').value});const d=await api('/api/email-reply/'+activeReplyDraftId+'/send');document.getElementById('reply-status').textContent='Email sent successfully.';alert('Email sent.');location.reload()}catch(e){alert(e.message);send.disabled=false}}
