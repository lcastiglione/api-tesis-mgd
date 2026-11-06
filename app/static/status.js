'use strict';

const byId = id => document.getElementById(id);
const operations = [
  ['quotes','Cotizaciones','Cotizaciones guardadas','Precios históricos por ticker y fechas.','GET','/api/v1/quotes'],
  ['study','Estudio','Contenido del estudio','Estructura y cantidades de la base.','GET','/api/v1/study'],
  ['instruments','Instrumentos','Instrumentos disponibles','ETF incluidos en el estudio.','GET','/api/v1/instruments'],
  ['configurations','Configuraciones','Configuraciones','Reglas y parámetros de las estrategias.','GET','/api/v1/configurations'],
  ['counts','Recuentos','Recuentos de configuraciones','Cantidades por instrumento y familia.','GET','/api/v1/configuration-counts'],
  ['executions','Ejecuciones','Ejecuciones guardadas','Casos calculados por instrumento, configuración y bloque.','GET','/api/v1/executions'],
  ['indicators','Indicadores','Indicadores de una ejecución','Medidas guardadas para el identificador elegido.','GET','/api/v1/executions/{execution_id}/indicators'],
  ['daily','Serie diaria','Resultados diarios','Recorrido de una ejecución por segmento y alternativa.','GET','/api/v1/executions/{execution_id}/daily'],
  ['operations','Operaciones','Operaciones guardadas','Operaciones de la ejecución elegida.','GET','/api/v1/executions/{execution_id}/operations'],
  ['verify','Motor','Comprobar un caso','Recalcula un caso y lo compara con la base, sin modificarla.','POST','/api/v1/verify-case'],
  ['status','Estado JSON','Estado del sistema','Estado del servidor y preparación de la base.','GET','/status'],
  ['schema','Esquema API','Esquema de la API','Definición de las consultas y sus parámetros.','GET','/openapi.json'],
].map(([id,label,title,description,method,path])=>({id,label,title,description,method,path}));
const labels = {ticker:'Ticker',instrument:'Instrumento',start_date:'Desde',end_date:'Hasta',limit:'Resultados',offset:'Omitir',configuration:'Configuración',family:'Familia',length:'Bloque (años)',execution_id:'ID de ejecución',segment:'Segmento',metric:'Indicador',alternative:'Alternativa',window_id:'ID de ventana'};
const state = {selected:operations[0],schema:null,status:null,values:{},result:null,table:null,view:'json',busy:false,schemaLoading:false,healthChecking:false,healthOk:null};
const decimal = new Intl.NumberFormat('es-AR',{maximumFractionDigits:1});

function metric(name,text,kind) {
  byId(`${name}-label`).textContent = text;
  byId(`${name}-metric`).className = `metric ${name==='database'?'database-metric ':''}${kind}`;
}
function bytes(value) {
  if (!Number.isFinite(value)) return '—';
  const unit = value>=1073741824?'GiB':'MiB';
  return `${decimal.format(value/(unit==='GiB'?1073741824:1048576))}${unit}`;
}
function renderStatus(status) {
  const phase = status.database.phase;
  metric('server','En línea','good');
  byId('version').textContent = `v${status.api_version}`;
  const apiError = status.services.api==='error';
  metric('health',apiError?'Revisar':status.ready?(state.healthOk===null?'Verificando':state.healthOk?'Operativa':'Revisar'):status.api_loaded?'En espera':'Iniciando',apiError||status.ready&&state.healthOk===false?'warning':status.ready&&state.healthOk?'good':'wait');
  const names = {pending:'Preparando',downloading:'Descargando',verifying:'Verificando',extracting:'Descomprimiendo',ready:'Lista',error:'Revisar'};
  metric('database',names[phase]||'Preparando',phase==='ready'?'good':phase==='error'?'warning':'wait');
  const percent = phase==='ready'?100:['pending','verifying','extracting'].includes(phase)?null:status.download.percent;
  byId('percent').textContent = percent===null?'—':`${decimal.format(percent)}%`;
  byId('ring-fill').style.strokeDashoffset = 263.8938*(1-(percent||0)/100);
  if (percent===null) byId('ring').removeAttribute('aria-valuenow');
  else byId('ring').setAttribute('aria-valuenow',percent);
  byId('ring').setAttribute('aria-valuetext',names[phase]||phase);
  byId('bytes').textContent = phase==='ready'?`${bytes(status.database.bytes)} · Solo lectura`:phase==='verifying'?'Comprobando integridad':phase==='extracting'?'Preparando el archivo':status.download.total_bytes?`${bytes(status.download.received_bytes)} / ${bytes(status.download.total_bytes)}`:'data/study.sqlite';
  byId('system-error').hidden = !status.error;
  if (status.error) byId('system-error').textContent = `${status.error.message}${status.retry_in_seconds===null?'':` Reintento en ${status.retry_in_seconds}s.`}`;
  enableQuery();
}
function available() {
  if (state.selected.id==='status') return true;
  if (state.selected.id==='schema') return Boolean(state.status?.api_loaded);
  return Boolean(state.status?.ready && state.schema);
}
function enableQuery() {
  byId('execute').disabled = state.busy || !available();
  byId('execute').textContent = state.busy?'Consultando…':'Consultar →';
}
async function poll() {
  try {
    const response = await fetch('/status',{cache:'no-store',signal:AbortSignal.timeout(4000)});
    if (!response.ok) throw new Error('Estado no disponible');
    state.status = await response.json();
    if (!state.status.ready) state.healthOk = null;
    renderStatus(state.status);
    if (state.status.api_loaded && !state.schema && !state.schemaLoading) loadSchema();
    if (state.status.ready && !state.healthChecking) checkHealth();
  } catch (error) {
    state.status = null;
    metric('server','Sin conexión','warning');
    metric('health','Sin conexión','warning');
    byId('system-error').hidden = false;
    byId('system-error').textContent = 'No se puede conectar con el servidor. Se reintentará automáticamente.';
    enableQuery();
  } finally { setTimeout(poll,1500); }
}
async function checkHealth() {
  state.healthChecking = true;
  try {
    const response = await fetch('/health',{cache:'no-store',signal:AbortSignal.timeout(4000)});
    state.healthOk = response.ok;
    if (state.status?.ready) metric('health',response.ok?'Operativa':'Revisar',response.ok?'good':'warning');
  } catch (error) {
    state.healthOk = false;
    if (state.status?.ready) metric('health','Revisar','warning');
  } finally { state.healthChecking = false; }
}
async function loadSchema() {
  state.schemaLoading = true;
  try {
    const response = await fetch('/openapi.json',{signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('No se pudo cargar el esquema');
    state.schema = await response.json();
    renderFields();
    enableQuery();
  } catch (error) {
    byId('fields').textContent = 'Se reintentará la carga de parámetros.';
  } finally { state.schemaLoading = false; }
}
function resolve(schema) {
  if (schema.$ref) return resolve(schema.$ref.split('/').slice(1).reduce((node,key)=>node[key],state.schema));
  if (schema.anyOf) return resolve(schema.anyOf.find(item=>item.type!=='null')||schema.anyOf[0]);
  return schema;
}
function definitions() {
  const operation = state.schema?.paths[state.selected.path]?.[state.selected.method.toLowerCase()];
  if (!operation) return [];
  const fields = (operation.parameters||[]).map(parameter=>({...parameter,schema:resolve(parameter.schema)}));
  if (operation.requestBody) {
    const body = resolve(operation.requestBody.content['application/json'].schema);
    for (const [name,schema] of Object.entries(body.properties||{})) fields.push({name,in:'body',required:body.required?.includes(name),schema:resolve(schema)});
  }
  const order = {execution_id:0,ticker:1,instrument:1,family:2,configuration:2,length:3,start_date:4,end_date:5,limit:90,offset:91};
  return fields.sort((left,right)=>(order[left.name]??10)-(order[right.name]??10));
}
function remember() {
  const values = {};
  byId('fields').querySelectorAll('input,select').forEach(input=>{ values[input.name]=input.value; });
  state.values[state.selected.id] = values;
}
function renderFields() {
  const area = byId('fields');
  area.replaceChildren();
  if (!state.schema && !['status','schema'].includes(state.selected.id)) {
    const text = document.createElement('p');
    text.className = 'loading-fields'; text.textContent = 'Cargando parámetros…';area.append(text);return;
  }
  const saved = state.values[state.selected.id]||{};
  for (const field of definitions()) {
    const schema = field.schema;
    const wrapper = document.createElement('div');wrapper.className = 'field';
    const label = document.createElement('label');label.htmlFor = `field-${field.name}`;label.textContent = labels[field.name]||field.name;
    if (field.required) { const mark = document.createElement('span');mark.className='required';mark.textContent='*';label.append(mark); }
    const input = document.createElement(schema.enum?'select':'input');
    input.id=`field-${field.name}`;input.name=field.name;input.required=Boolean(field.required);
    input.title = schema.description||field.description||labels[field.name]||field.name;
    if (schema.enum) {
      if (!field.required) input.add(new Option('Todos',''));
      for (const value of schema.enum) input.add(new Option(String(value),String(value)));
    } else {
      input.type = schema.format==='date'?'date':['integer','number'].includes(schema.type)?'number':'text';
      if (input.type==='number') {
        input.step = schema.type==='integer'?'1':'any';
        if (schema.minimum!==undefined) input.min=schema.minimum;
        if (schema.maximum!==undefined) input.max=schema.maximum;
      }
      if (schema.maxLength) input.maxLength=schema.maxLength;
      if (schema.minLength) input.minLength=schema.minLength;
      if (schema.pattern) input.pattern=schema.pattern;
      if (field.name==='execution_id') input.placeholder='Copiá un ID de Ejecuciones';
    }
    if (saved[field.name]!==undefined) input.value=saved[field.name];
    else if (schema.default!==undefined && schema.default!==null) input.value=String(schema.default);
    else if (schema.enum && field.required) input.value=String(schema.enum[0]);
    wrapper.append(label,input);area.append(wrapper);
  }
  if (!area.children.length) {
    const text=document.createElement('p');text.className='loading-fields';text.textContent='Esta consulta no requiere parámetros.';area.append(text);
  }
}
function selectOperation(id) {
  remember();
  state.selected=operations.find(operation=>operation.id===id);
  state.result=null;state.table=null;state.view='json';
  byId('query-title').textContent=state.selected.title;
  byId('query-description').textContent=state.selected.description;
  byId('method').textContent=state.selected.method;
  byId('request-path').textContent=state.selected.path;
  byId('mobile-operation').value=id;
  byId('operations').querySelectorAll('button').forEach(button=>{
    button.classList.toggle('active',button.dataset.operation===id);
    button.setAttribute('aria-current',button.dataset.operation===id?'true':'false');
  });
  byId('response-status').textContent='Sin consulta';byId('response-status').className='';byId('response-time').textContent='';
  renderFields();renderResponse();enableQuery();
}
function jsonView(value) {
  const pre=document.createElement('pre');const raw=JSON.stringify(value,null,2);
  const pattern=/("(?:\\.|[^"\\])*"\s*:|"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;
  let end=0;
  for (const match of raw.matchAll(pattern)) {
    pre.append(document.createTextNode(raw.slice(end,match.index)));
    const token=document.createElement('span');token.textContent=match[0];
    token.className=`json-${match[0].endsWith(':')?'key':match[0].startsWith('"')?'string':match[0]==='null'?'null':['true','false'].includes(match[0])?'boolean':'number'}`;
    pre.append(token);end=match.index+match[0].length;
  }
  pre.append(document.createTextNode(raw.slice(end)));return pre;
}
function renderResponse() {
  const area=byId('response');area.replaceChildren();
  byId('copy').disabled=state.result===null;
  byId('table-tab').disabled=!state.table;
  byId('json-tab').setAttribute('aria-selected',state.view==='json');byId('table-tab').setAttribute('aria-selected',state.view==='table');
  if (state.result===null) {
    const empty=document.createElement('div');empty.className='empty-state';
    const icon=document.createElement('span');icon.textContent='{ }';icon.setAttribute('aria-hidden','true');
    const text=document.createElement('p');text.textContent='Elegí los parámetros y presioná Consultar.';empty.append(icon,text);area.append(empty);return;
  }
  if (state.view==='json') { area.append(jsonView(state.result));return; }
  const table=document.createElement('table');
  const keys=[...new Set(state.table.flatMap(row=>Object.keys(row)))];
  const head=document.createElement('thead'),heading=document.createElement('tr');
  for (const key of keys) { const cell=document.createElement('th');cell.scope='col';cell.textContent=key;heading.append(cell); }
  head.append(heading);table.append(head);const body=document.createElement('tbody');
  for (const row of state.table) {
    const tr=document.createElement('tr');
    for (const key of keys) { const cell=document.createElement('td');const value=row[key];cell.textContent=value===null||value===undefined?'—':typeof value==='object'?JSON.stringify(value):String(value);tr.append(cell); }
    body.append(tr);
  }
  table.append(body);area.append(table);
}
async function execute(event) {
  event.preventDefault();
  if (state.busy || !available() || !byId('query-form').reportValidity()) return;
  remember();
  const selected=state.selected;let path=selected.path;const query=new URLSearchParams(),body={};
  for (const field of definitions()) {
    const raw=state.values[selected.id][field.name];
    if (raw==='') continue;
    const value=['integer','number'].includes(field.schema.type)?Number(raw):raw;
    if (field.in==='path') path=path.replace(`{${field.name}}`,encodeURIComponent(raw));
    else if (field.in==='body') body[field.name]=value;
    else query.set(field.name,raw);
  }
  if (query.size) path+=`?${query}`;
  byId('request-path').textContent=path;
  state.busy=true;enableQuery();const start=performance.now();
  byId('response-status').textContent='Consultando…';byId('response-status').className='';
  try {
    const options={method:selected.method,cache:'no-store'};
    if (selected.method==='POST') { options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(body); }
    const response=await fetch(path,options);const raw=await response.text();
    if (state.selected.id!==selected.id) return;
    try {state.result=JSON.parse(raw);} catch(error) {state.result={respuesta:raw};}
    state.table=Array.isArray(state.result?.items)&&state.result.items.length&&state.result.items.every(item=>item&&typeof item==='object'&&!Array.isArray(item))?state.result.items:null;
    byId('response-status').textContent=`HTTP ${response.status}`;byId('response-status').className=response.ok?'success':'failure';
    byId('response-time').textContent=`${Math.round(performance.now()-start)}ms`;
  } catch(error) {
    if (state.selected.id!==selected.id) return;
    state.result={mensaje:'No se pudo conectar con el servidor. Volvé a intentar la consulta.'};state.table=null;
    byId('response-status').textContent='Sin conexión';byId('response-status').className='failure';byId('response-time').textContent='';
  } finally {state.busy=false;state.view='json';renderResponse();enableQuery();}
}

for (const operation of operations) {
  const button=document.createElement('button');button.type='button';button.textContent=operation.label;button.dataset.operation=operation.id;
  button.addEventListener('click',()=>selectOperation(operation.id));byId('operations').append(button);
  byId('mobile-operation').add(new Option(operation.label,operation.id));
}
byId('mobile-operation').addEventListener('change',event=>selectOperation(event.target.value));
byId('query-form').addEventListener('submit',execute);
for (const view of ['json','table']) byId(`${view}-tab`).addEventListener('click',()=>{state.view=view;renderResponse();});
byId('copy').addEventListener('click',async()=>{
  try {await navigator.clipboard.writeText(JSON.stringify(state.result,null,2));byId('copy').textContent='Copiado';}
  catch(error) {byId('copy').textContent='Seleccioná el JSON';}
  setTimeout(()=>{byId('copy').textContent='Copiar';},1800);
});
selectOperation('quotes');poll();
