import json, os, time
from datetime import datetime
from flask import Flask, request, jsonify, Response
import psycopg
from psycopg.rows import dict_row

app=Flask(__name__)
DB=os.getenv('DATABASE_URL','postgresql://campus:campus@db:5432/campus')
def conn():
    for i in range(30):
        try:return psycopg.connect(DB,row_factory=dict_row)
        except psycopg.OperationalError:
            if i==29:raise
            time.sleep(2)
def actor():
    try:uid=int(request.headers.get('X-User-Id','1'))
    except ValueError:return None
    with conn() as c:return c.execute('SELECT * FROM users WHERE id=%s',(uid,)).fetchone()
def require(*roles):
    u=actor()
    if not u:return None,(jsonify(error='Unknown user'),401)
    if roles and u['role'] not in roles:return None,(jsonify(error='Forbidden for this role'),403)
    return u,None
def audit(c,u,typ,oid,action,detail=None):
    c.execute('INSERT INTO audit_events(actor_id,object_type,object_id,action,detail) VALUES(%s,%s,%s,%s,%s)',(u['id'],typ,oid,action,json.dumps(detail or {})))

@app.get('/health')
def health():
    with conn() as c:c.execute('SELECT 1')
    return {'ok':True,'instance':os.getenv('HOSTNAME','local')}
@app.get('/api/dashboard')
def dashboard():
    u,e=require()
    if e:return e
    with conn() as c:
        f=c.execute('SELECT * FROM facilities ORDER BY id').fetchall()
        b=c.execute('SELECT b.*,f.name facility,u.name requester FROM bookings b JOIN facilities f ON f.id=b.facility_id JOIN users u ON u.id=b.user_id ORDER BY b.created_at DESC LIMIT 30').fetchall()
        t=c.execute("SELECT t.*,f.name facility,u.name assignee,s.response_minutes,s.resolution_minutes FROM tickets t LEFT JOIN facilities f ON f.id=t.facility_id LEFT JOIN users u ON u.id=t.assignee_id JOIN sla_policies s ON s.priority=t.priority ORDER BY t.created_at DESC LIMIT 30").fetchall()
        us=c.execute('SELECT id,name,role FROM users ORDER BY id').fetchall()
        counts=c.execute("SELECT (SELECT count(*) FROM bookings WHERE status IN ('requested','approved','confirmed','in_use')) active_bookings,(SELECT count(*) FROM tickets WHERE status<>'closed') open_tickets").fetchone()
    return jsonify(facilities=f,bookings=b,tickets=t,users=us,counts=counts)

@app.post('/api/bookings')
def booking_create():
    u,e=require('admin','manager','faculty','student')
    if e:return e
    d=request.get_json(force=True)
    try:
        fid=int(d['facility_id']);start=datetime.fromisoformat(d['starts_at'].replace('Z','+00:00'));end=datetime.fromisoformat(d['ends_at'].replace('Z','+00:00'))
        if end<=start:raise ValueError()
    except (KeyError,ValueError,TypeError):return jsonify(error='Provide a facility and valid timestamps; end must follow start'),400
    key=request.headers.get('Idempotency-Key')
    if not key:return jsonify(error='Idempotency-Key header is required'),400
    with conn() as c:
        f=c.execute('SELECT * FROM facilities WHERE id=%s',(fid,)).fetchone()
        if not f:return jsonify(error='Facility not found'),404
        status='requested' if u['role'] in ('faculty','student') or f['restricted'] else 'confirmed'
        try:r=c.execute('INSERT INTO bookings(request_key,facility_id,user_id,starts_at,ends_at,status,purpose) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(request_key) DO NOTHING RETURNING *',(key,fid,u['id'],start,end,status,d.get('purpose','Campus activity'))).fetchone()
        except psycopg.errors.ExclusionViolation:return jsonify(error='Facility already has an overlapping active reservation'),409
        if not r:return jsonify(c.execute('SELECT * FROM bookings WHERE request_key=%s',(key,)).fetchone()),200
        audit(c,u,'booking',r['id'],'booking_'+status,{'facility':f['name']})
    return jsonify(r),201

@app.post('/api/sensors')
def sensor():
    u,e=require('admin','manager')
    if e:return e
    d=request.get_json(force=True)
    try:key=str(d['event_key']);fid=int(d['facility_id']);reading=float(d['reading']);threshold=float(d['threshold'])
    except (KeyError,TypeError,ValueError):return jsonify(error='event_key, facility_id, reading and threshold are required'),400
    with conn() as c:
        prev=c.execute('SELECT t.* FROM sensor_alerts s JOIN tickets t ON t.id=s.ticket_id WHERE s.event_key=%s',(key,)).fetchone()
        if prev:return jsonify(ticket=prev,duplicate=True),200
        if reading<threshold:return jsonify(error='Reading is below threshold; no ticket created'),422
        f=c.execute('SELECT * FROM facilities WHERE id=%s',(fid,)).fetchone()
        if not f:return jsonify(error='Facility not found'),404
        msg=d.get('message','Sensor threshold exceeded').lower()
        cat='environment' if any(x in msg for x in ['temperature','humidity','air']) else ('electrical' if any(x in msg for x in ['power','voltage','electrical']) else 'general')
        pri='critical' if reading>=threshold*1.5 else 'high'
        t=c.execute("INSERT INTO tickets(source_key,facility_id,title,category,priority,status) VALUES(%s,%s,%s,%s,%s,'intake') ON CONFLICT(source_key) DO UPDATE SET source_key=EXCLUDED.source_key RETURNING *",('sensor:'+key,fid,d.get('message','Sensor threshold exceeded'),cat,pri)).fetchone()
        c.execute('INSERT INTO sensor_alerts(event_key,facility_id,reading,threshold,ticket_id) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(event_key) DO NOTHING',(key,fid,reading,threshold,t['id']))
        audit(c,u,'ticket',t['id'],'sensor_intake',{'event_key':key,'rule_category':cat,'rule_priority':pri})
    return jsonify(ticket=t,duplicate=False,explanation={'category':'keyword rule','priority':'critical when reading >= 1.5x threshold, else high'}),201

@app.patch('/api/tickets/<int:tid>')
def ticket_update(tid):
    u,e=require('admin','manager','technician')
    if e:return e
    d=request.get_json(force=True);expected=d.get('version');new=d.get('status')
    allowed={'intake':['assigned'],'assigned':['inspection'],'inspection':['pending_work','resolved'],'pending_work':['inspection','resolved'],'resolved':['closed']}
    with conn() as c:
        old=c.execute('SELECT * FROM tickets WHERE id=%s FOR UPDATE',(tid,)).fetchone()
        if not old:return jsonify(error='Ticket not found'),404
        if expected is None or int(expected)!=old['version']:return jsonify(error='Version conflict; refresh before retry',current_version=old['version']),409
        if new not in allowed.get(old['status'],[]):return jsonify(error='Invalid ticket transition',allowed=allowed.get(old['status'],[])),409
        if new=='closed' and u['role'] not in ('admin','manager'):return jsonify(error='Manager authorization required to close'),403
        if 'assignee_id' in d and u['role'] not in ('admin','manager'):return jsonify(error='Manager authorization required to assign'),403
        r=c.execute('UPDATE tickets SET status=%s,assignee_id=%s,notes=%s,version=version+1,updated_at=now() WHERE id=%s AND version=%s RETURNING *',(new,d.get('assignee_id',old['assignee_id']),d.get('notes',old['notes']),tid,expected)).fetchone()
        if not r:return jsonify(error='Concurrent update won; reload current ticket'),409
        audit(c,u,'ticket',tid,'ticket_'+new,{'version':r['version'],'notes':r['notes']})
    return jsonify(r)

@app.patch('/api/bookings/<int:bid>')
def booking_transition(bid):
    u,e=require('admin','manager')
    if e:return e
    d=request.get_json(force=True);expected=d.get('version');target=d.get('status')
    transitions={'approved':['confirmed','cancelled'],'confirmed':['in_use','cancelled'],'in_use':['completed']}
    with conn() as c:
        old=c.execute('SELECT * FROM bookings WHERE id=%s FOR UPDATE',(bid,)).fetchone()
        if not old:return jsonify(error='Booking not found'),404
        if expected is None or int(expected)!=old['version']:return jsonify(error='Version conflict; refresh before retry',current_version=old['version']),409
        if target not in transitions.get(old['status'],[]):return jsonify(error='Invalid booking transition',allowed=transitions.get(old['status'],[])),409
        try:r=c.execute('UPDATE bookings SET status=%s,version=version+1 WHERE id=%s AND version=%s RETURNING *',(target,bid,expected)).fetchone()
        except psycopg.errors.ExclusionViolation:return jsonify(error='Transition would create an overlapping active reservation'),409
        audit(c,u,'booking',bid,'booking_'+target,{'version':r['version']})
    return jsonify(r)

@app.post('/api/bookings/<int:bid>/approval')
def approval(bid):
    u,e=require('admin','approver')
    if e:return e
    d=request.get_json(force=True);decision=d.get('decision');reason=d.get('reason','')
    if decision not in ('approved','rejected') or not reason.strip():return jsonify(error='Decision and justification are required'),400
    with conn() as c:
        b=c.execute('SELECT * FROM bookings WHERE id=%s FOR UPDATE',(bid,)).fetchone()
        if not b:return jsonify(error='Booking not found'),404
        if b['status']!='requested':return jsonify(error='Only requested bookings can be decided'),409
        target='approved' if decision=='approved' else 'cancelled'
        try:c.execute('UPDATE bookings SET status=%s,version=version+1 WHERE id=%s',(target,bid))
        except psycopg.errors.ExclusionViolation:return jsonify(error='Approval would overlap an active reservation'),409
        c.execute('INSERT INTO approvals(booking_id,approver_id,decision,reason) VALUES(%s,%s,%s,%s)',(bid,u['id'],decision,reason));audit(c,u,'booking',bid,'approval_'+decision,{'reason':reason})
    return jsonify(booking_id=bid,status=target,decision=decision)

@app.post('/api/tickets/<int:tid>/issue-link')
def issue_link(tid):
    u,e=require('admin','manager','technician')
    if e:return e
    key='local-issue-'+str(tid)
    with conn() as c:
        if not c.execute('SELECT id FROM tickets WHERE id=%s',(tid,)).fetchone():return jsonify(error='Ticket not found'),404
        r=c.execute("INSERT INTO integration_links(object_type,object_id,external_key,mode,state) VALUES('ticket',%s,%s,'simulated_local','created') ON CONFLICT(external_key) DO UPDATE SET external_key=EXCLUDED.external_key RETURNING *",(tid,key)).fetchone()
        audit(c,u,'ticket',tid,'developer_issue_linked',{'mode':'simulated_local','external_key':key})
    return jsonify(link=r,disclosure='Simulated local integration; no external tracker request was made.'),201

@app.get('/')
def index():return Response(HTML,mimetype='text/html')

HTML='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Smart Campus Operations</title><style>body{font:15px Arial;color:#111;margin:28px;background:#f5f6f8}h1,h2,h3{color:#111}header,.card{background:white;padding:18px;border-radius:10px;margin:12px 0;box-shadow:0 1px 4px #bbb}button,select,input{padding:8px;margin:4px;color:#111}button{cursor:pointer}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}.row{border-top:1px solid #ddd;padding:8px}</style></head><body><header><h1>Smart Campus Operations</h1><p>Bookings, sensor triage and maintenance. The demo role selector represents an unverified local identity.</p><label>Act as <select id="user"></select></label><button onclick="load()">Refresh</button><span id="msg"></span><p id="counts"></p></header><section><div class="card"><h2>Facilities and bookings</h2><div id="facilities"></div><label>Facility <select id="facility"></select></label><br>Start <input id="start" type="datetime-local"><br>End <input id="end" type="datetime-local"><br><input id="purpose" placeholder="Purpose"><button onclick="book()">Request booking</button><h3>Bookings</h3><div id="bookings"></div></div><div class="card"><h2>Sensor intake</h2><input id="event" placeholder="Unique event key"><input id="reading" type="number" value="82"><input id="threshold" type="number" value="70"><input id="sensorMsg" value="high temperature"><button onclick="sensor()">Submit event</button><h3>Maintenance queue</h3><div id="tickets"></div><button onclick="linkLast()">Link last ticket to simulated issue</button></div></section><script>let data={},lastTicket=null,bookingKey=null;function hdr(){return {'Content-Type':'application/json','X-User-Id':user.value||'1'}}async function api(p,o={}){let r=await fetch(p,{...o,headers:{...hdr(),...(o.headers||{})}}),j=await r.json();if(!r.ok)throw Error(j.error||r.status);return j}function say(x){msg.textContent=' '+x;setTimeout(()=>msg.textContent='',4000)}async function load(){try{data=await api('/api/dashboard');counts.textContent='Active bookings: '+data.counts.active_bookings+' | Open tickets: '+data.counts.open_tickets;user.innerHTML=data.users.map(x=>`<option value="${x.id}">${x.name} (${x.role})</option>`).join('');facility.innerHTML=data.facilities.map(x=>`<option value="${x.id}">${x.name}${x.restricted?' (restricted)':''}</option>`).join('');facilities.innerHTML=data.facilities.map(x=>`<div class="row">${x.name} - ${x.kind}${x.restricted?' - approval required':''}</div>`).join('');bookings.innerHTML=data.bookings.map(x=>`<div class="row">#${x.id} ${x.facility} | ${x.status} | ${new Date(x.starts_at).toLocaleString()} | ${x.requester}${x.status==='requested'?` <button onclick="approve(${x.id})">Approve</button>`:''}</div>`).join('')||'No bookings';tickets.innerHTML=data.tickets.map(x=>`<div class="row"><b>#${x.id} ${x.title}</b> | ${x.category}/${x.priority} | ${x.status} | SLA ${x.response_minutes}m/${x.resolution_minutes}m<br>${x.notes}<br><input id="note${x.id}" placeholder="Inspection or resolution note"><button onclick="assign(${x.id},${x.version})">Assign</button><button onclick="advance(${x.id},${x.version},'${x.status}')">Advance</button></div>`).join('')||'No tickets'}catch(e){say(e.message)}}async function book(){try{bookingKey ||= crypto.randomUUID();let x=await api('/api/bookings',{method:'POST',headers:{'Idempotency-Key':bookingKey},body:JSON.stringify({facility_id:facility.value,starts_at:new Date(start.value).toISOString(),ends_at:new Date(end.value).toISOString(),purpose:purpose.value})});bookingKey=null;say('Booking #'+x.id+' '+x.status);load()}catch(e){say(e.message)}}async function sensor(){try{let x=await api('/api/sensors',{method:'POST',body:JSON.stringify({event_key:event.value||crypto.randomUUID(),facility_id:facility.value,reading:+reading.value,threshold:+threshold.value,message:sensorMsg.value})});lastTicket=x.ticket.id;say(x.duplicate?'Retry reused ticket #'+lastTicket:'Ticket #'+lastTicket+' created; '+x.ticket.category+'/'+x.ticket.priority);load()}catch(e){say(e.message)}}async function assign(id,v){try{await api('/api/tickets/'+id,{method:'PATCH',body:JSON.stringify({version:v,status:'assigned',assignee_id:3,notes:'Assigned to Technician A'})});say('Assigned');load()}catch(e){say(e.message)}}async function advance(id,v,s){let n={intake:'assigned',assigned:'inspection',inspection:'resolved',pending_work:'resolved',resolved:'closed'}[s];if(!n)return;try{await api('/api/tickets/'+id,{method:'PATCH',body:JSON.stringify({version:v,status:n,notes:document.querySelector('#note'+id).value||'Inspection completed; repair verified'})});say('Moved to '+n);load()}catch(e){say(e.message)}}async function approve(id){try{await api('/api/bookings/'+id+'/approval',{method:'POST',body:JSON.stringify({decision:'approved',reason:'Department activity approved'})});say('Approved');load()}catch(e){say(e.message)}}async function linkLast(){try{let id=lastTicket||data.tickets[0]?.id;if(!id)throw Error('Create a ticket first');let x=await api('/api/tickets/'+id+'/issue-link',{method:'POST'});say(x.disclosure)}catch(e){say(e.message)}}load();</script></body></html>'''
