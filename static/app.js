const byId = id => document.getElementById(id);
const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const stages = ['New', 'Qualified', 'Proposal', 'Won', 'Lost'];
const views = { overview: 'Overview', contacts: 'Contacts', imports: 'Imports', query: 'AI Query' };
let page = 1;
let current = 'overview';
let contactRequest = 0;
let searchTimer;

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value != null) node.textContent = value;
  if (className) node.className = className;
  return node;
}

async function api(url, options) {
  const response = await fetch('/api/' + url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}

function row(values) {
  const tr = element('tr');
  for (const value of values) {
    const td = element('td');
    if (value instanceof Node) td.append(value);
    else td.textContent = value ?? '—';
    tr.append(td);
  }
  return tr;
}

async function loadOverview() {
  try {
    const { stats, stages: counts, demo, ai } = await api('overview');
    byId('mode').textContent = demo ? 'Demo workspace' : 'Connected workspace';
    byId('count').textContent = stats.contacts.toLocaleString();
    byId('value').textContent = currency.format(stats.value);
    byId('won').textContent = stats.won.toLocaleString();
    byId('stages').replaceChildren(...stages.map(stage => {
      const count = counts[stage] || 0;
      const label = element('div', null, 'stage-label');
      label.append(element('span', stage), element('b', count.toLocaleString()));
      const fill = element('div');
      fill.style.width = (stats.contacts ? count / stats.contacts * 100 : 0) + '%';
      const track = element('div', null, 'stage-line');
      track.append(fill);
      const bar = element('div');
      bar.append(label, track);
      return bar;
    }));
    byId('file').disabled = demo;
    byId('import-form').querySelector('button').disabled = demo;
    byId('query-form').querySelector('button.primary').disabled = !ai;
    if (demo) byId('import-status').textContent = 'Start the Docker stack to import your own contacts.';
    if (!ai) byId('query-status').textContent = 'Run the connected stack with OPENAI_API_KEY to enable AI queries.';
  } catch (error) {
    byId('mode').textContent = 'Connection unavailable';
    byId('overview-error').textContent = error.message;
  }
}

async function loadContacts() {
  const request = ++contactRequest;
  const requestedPage = page;
  const params = new URLSearchParams({ q: byId('search').value, stage: byId('stage').value, page });
  try {
    const { rows, total } = await api('contacts?' + params);
    if (request !== contactRequest) return;
    byId('rows').replaceChildren(...rows.map(contact => {
      const profile = element('div', null, 'person');
      const initials = contact.name.split(/\s+/).slice(0, 2).map(word => word[0]).join('');
      const name = element('div', contact.name);
      name.append(element('small', contact.email));
      profile.append(element('span', initials, 'avatar'), name);
      return row([profile, contact.company, element('span', contact.stage, 'badge ' + contact.stage.toLowerCase()), currency.format(contact.value)]);
    }));
    const start = (requestedPage - 1) * 8;
    byId('range').textContent = rows.length ? `${start + 1}–${start + rows.length} of ${total} contacts` : 'No matching contacts';
    byId('prev').disabled = requestedPage <= 1;
    byId('next').disabled = start + rows.length >= total;
  } catch (error) {
    if (request === contactRequest) byId('range').textContent = error.message;
  }
}

async function loadJobs() {
  try {
    const { jobs } = await api('jobs');
    byId('jobs').replaceChildren(...(jobs.length ? jobs.map(job => row([
      job.filename, job.status.replaceAll('_', ' '), job.processed + ' / ' + job.chunks, job.accepted, job.rejected
    ])) : [row(['No imports yet', '—', '—', '—', '—'])]));
  } catch (error) {
    byId('jobs').replaceChildren(row([error.message]));
  }
}

function navigate(view) {
  current = view;
  byId('crumb').textContent = views[view];
  byId('overview').hidden = byId('summary').hidden = view !== 'overview';
  byId('contacts').hidden = !['overview', 'contacts'].includes(view);
  for (const id of ['imports', 'query']) byId(id).hidden = id !== view;
  document.querySelectorAll('nav button').forEach(button => {
    const active = button.dataset.view === view;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  if (view === 'imports') loadJobs();
  if (view === 'overview') loadOverview();
  if (['contacts', 'overview'].includes(view)) loadContacts();
}

document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => navigate(button.dataset.view)));
byId('prev').onclick = () => { page--; loadContacts(); };
byId('next').onclick = () => { page++; loadContacts(); };
byId('stage').onchange = () => { page = 1; loadContacts(); };
byId('search').oninput = () => {
  clearTimeout(searchTimer);
  page = 1;
  searchTimer = setTimeout(loadContacts, 180);
};
byId('refresh').onclick = loadJobs;
setInterval(() => { if (current === 'imports') loadJobs(); }, 3000);

byId('template').onclick = () => {
  const url = URL.createObjectURL(new Blob([
    'name,email,company,industry,region,stage,value\nAvery Chen,avery@example.com,Acme,Software,North America,Qualified,12000\n'
  ], { type: 'text/csv' }));
  const link = element('a');
  link.href = url;
  link.download = 'clientrel-contacts.csv';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

byId('import-form').onsubmit = async event => {
  event.preventDefault();
  const file = byId('file').files[0];
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  byId('import-status').textContent = 'Uploading CSV…';
  try {
    await api('import', { method: 'POST', headers: { 'X-Filename': encodeURIComponent(file.name) }, body: file });
    byId('import-status').textContent = 'Import queued. Progress appears below.';
    byId('file').value = '';
  } catch (error) {
    byId('import-status').textContent = error.message;
  } finally {
    button.disabled = false;
    loadJobs();
  }
};

document.querySelectorAll('.examples button').forEach(button => {
  button.onclick = () => { byId('question').value = button.textContent; byId('question').focus(); };
});
byId('query-form').onsubmit = async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('.primary');
  button.disabled = true;
  byId('query-result').hidden = true;
  byId('query-status').textContent = 'Generating and validating the query…';
  try {
    const result = await api('query', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: byId('question').value }) });
    const output = byId('result-table');
    if (result.rows.length) {
      const keys = [...new Set(result.rows.flatMap(Object.keys))];
      const table = element('table');
      const headings = table.createTHead().insertRow();
      headings.append(...keys.map(key => element('th', key)));
      table.createTBody().append(...result.rows.map(item => row(keys.map(key => item[key]))));
      output.replaceChildren(table);
    } else {
      output.replaceChildren(element('p', 'No matching records.', 'muted'));
    }
    byId('pipeline-json').textContent = JSON.stringify(result.pipeline, null, 2);
    byId('query-result').hidden = false;
    byId('query-status').textContent = '';
  } catch (error) {
    byId('query-status').textContent = error.message;
  } finally {
    button.disabled = false;
  }
};

navigate('overview');
