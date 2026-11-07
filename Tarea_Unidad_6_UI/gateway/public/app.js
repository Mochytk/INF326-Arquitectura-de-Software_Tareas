// Todo se obtiene y modifica por GraphQL contra /graphql (el gateway).
// El DOM se arma con textContent: los mensajes son texto de usuarios, nunca HTML.
const $ = (selector) => document.querySelector(selector);
const REACTIONS = { like: '👍', heart: '❤️', laugh: '😂' };

let user = JSON.parse(localStorage.getItem('user') ?? 'null');
let channelId = null;
let searchTerm = '';

function h(tag, props = {}, ...children) {
  const element = Object.assign(document.createElement(tag), props);
  element.append(...children.filter((child) => child !== null && child !== undefined));
  return element;
}

async function send(body, headers = {}) {
  const response = await fetch('/graphql', {
    method: 'POST',
    headers: { ...(user ? { 'x-user-id': user.id } : {}), ...headers },
    body,
  });
  const result = await response.json();
  $('#warnings').hidden = !result.errors?.length;
  $('#warnings').textContent = (result.errors ?? [])
    .map((e) => `${e.extensions?.service ?? 'gateway'}: ${e.message}`).join(' · ');
  return result.data;
}

async function gql(query, variables = {}) {
  $('#last-query').textContent = `${query.trim()}\n\n# variables\n${JSON.stringify(variables)}`;
  return send(JSON.stringify({ query, variables }), { 'content-type': 'application/json' });
}

const MESSAGE_FIELDS = `id channelId content createdAt author { id displayName }
  reactions { total counts { type count } reactions { id type user { id } } }
  previews { url title description imageUrl } highlights`;

const CHANNEL = `query($id: ID!) { channel(id: $id) { id name
  messages(limit: 50) { ${MESSAGE_FIELDS} }
  attachments(limit: 20) { id category filename mimeType sizeBytes downloadUrl uploader { displayName } }
  quota { usedBytes limitBytes fileCount maxFiles } } }`;

const SEARCH = `query($q: String) { search(content: $q, limit: 25) { total messages { ${MESSAGE_FIELDS} channel { name } } } }`;

function highlighted(text) {
  return text.split('**').map((part, i) => (i % 2 ? h('mark', {}, part) : part));
}

function reactionBar(message) {
  const mine = new Map((message.reactions?.reactions ?? []).filter((r) => r.user?.id === user?.id).map((r) => [r.type, r.id]));
  const counts = new Map((message.reactions?.counts ?? []).map((c) => [c.type, c.count]));
  return h('div', { className: 'reactions' }, ...Object.entries(REACTIONS).map(([type, emoji]) => {
    const button = h('button', { className: mine.has(type) ? 'mine' : '', title: type }, `${emoji} ${counts.get(type) ?? 0}`);
    button.onclick = async () => {
      if (!user) return alert('Crea o elige un usuario primero');
      await (mine.has(type)
        ? gql('mutation($id: ID!) { removeReaction(id: $id) }', { id: mine.get(type) })
        : gql('mutation($c: ID!, $m: ID!, $t: String!) { addReaction(channelId: $c, messageId: $m, type: $t) { id } }',
          { c: message.channelId, m: message.id, t: type }));
      refresh();
    };
    return button;
  }));
}

function messageView(message) {
  return h('div', { className: 'msg' },
    h('div', { className: 'meta' }, h('span', { className: 'author' }, message.author?.displayName ?? 'desconocido'),
      ` · ${new Date(message.createdAt).toLocaleString()}`, message.channel ? ` · #${message.channel.name}` : ''),
    h('div', {}, ...highlighted(message.highlights?.[0] ?? message.content)),
    ...message.previews.map((p) => h('div', { className: 'preview' },
      p.imageUrl ? h('img', { src: p.imageUrl, alt: '' }) : null,
      h('div', {}, h('strong', {}, p.title ?? p.url), h('div', { className: 'muted' }, p.description ?? '')))),
    reactionBar(message));
}

function render(data) {
  const box = $('#messages');
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.replaceChildren(...data.messages.map(messageView));
  if (atBottom) box.scrollTop = box.scrollHeight;
}

async function refresh() {
  if (searchTerm) {
    const data = await gql(SEARCH, { q: searchTerm });
    $('#title').textContent = `Resultados para «${searchTerm}» (${data?.search.total ?? 0})`;
    if (data) render(data.search);
    return;
  }
  if (!channelId) return;
  const data = await gql(CHANNEL, { id: channelId });
  if (!data?.channel) return;
  $('#title').textContent = `# ${data.channel.name}`;
  $('#message-form').hidden = $('#media').hidden = false;
  render(data.channel);
  const { quota } = data.channel;
  $('#quota').textContent = quota ? `${quota.fileCount}/${quota.maxFiles} archivos · ${(quota.usedBytes / 1e6).toFixed(1)} MB usados` : 'Cuota no disponible (¿hay usuario?)';
  $('#attachments').replaceChildren(...data.channel.attachments.map((a) => h('li', {},
    a.downloadUrl ? h('a', { href: `${a.downloadUrl}?userId=${user?.id}` }, a.filename) : a.filename ?? a.url,
    h('div', { className: 'muted' }, `${a.category} · ${a.uploader?.displayName ?? ''}`),
    a.uploader?.displayName === user?.displayName ? deleteButton(a.id) : null)));
}

function deleteButton(id) {
  const button = h('button', {}, 'Eliminar');
  button.onclick = async () => { await gql('mutation($id: ID!) { deleteAttachment(id: $id) }', { id }); refresh(); };
  return button;
}

async function loadChannels() {
  const data = await gql('{ channels { id name } }');
  $('#channels').replaceChildren(...(data?.channels ?? []).map((channel) => {
    const button = h('button', { className: `channel${channel.id === channelId ? ' active' : ''}` }, `# ${channel.name}`);
    button.onclick = () => { channelId = channel.id; searchTerm = ''; loadChannels(); refresh(); };
    return h('li', {}, button);
  }));
}

async function loadServices() {
  const data = await gql('{ services { name up latencyMs } }');
  $('#services').replaceChildren(...(data?.services ?? []).map((s) =>
    h('small', {}, h('span', { className: `dot${s.up ? ' up' : ''}` }), s.name)));
}

function setUser(next) {
  user = next;
  localStorage.setItem('user', JSON.stringify(user));
  $('#whoami').textContent = user ? `Usuario: ${user.displayName}` : 'Sin usuario';
}

$('#user-form').onsubmit = async (event) => {
  event.preventDefault();
  const data = await gql('mutation($n: String!) { createUser(displayName: $n) { id displayName } }', { n: event.target.name.value });
  if (data) setUser(data.createUser);
  event.target.reset();
  refresh();
};
$('#channel-form').onsubmit = async (event) => {
  event.preventDefault();
  const data = await gql('mutation($n: String!) { createChannel(name: $n) { id } }', { n: event.target.name.value });
  if (data) channelId = data.createChannel.id;
  event.target.reset();
  loadChannels(); refresh();
};
$('#message-form').onsubmit = async (event) => {
  event.preventDefault();
  if (!user) return alert('Crea o elige un usuario primero');
  await gql('mutation($c: ID!, $t: String!) { sendMessage(channelId: $c, content: $t) { id } }', { c: channelId, t: event.target.content.value });
  event.target.reset();
  refresh();
};
$('#upload-form').onsubmit = async (event) => {
  event.preventDefault();
  if (!user) return alert('Crea o elige un usuario primero');
  const form = new FormData();
  form.append('operations', JSON.stringify({
    query: 'mutation($c: ID!, $file: File!) { uploadAttachment(channelId: $c, file: $file) { id } }',
    variables: { c: channelId, file: null },
  }));
  form.append('map', JSON.stringify({ 0: ['variables.file'] }));
  form.append('0', event.target.file.files[0]);
  await send(form);
  event.target.reset();
  refresh();
};
$('#search-form').onsubmit = (event) => { event.preventDefault(); searchTerm = event.target.q.value.trim(); refresh(); };
$('#search-clear').onclick = () => { searchTerm = ''; $('#search-form').reset(); refresh(); };

setUser(user);
loadChannels(); loadServices();
setInterval(refresh, 5000);
setInterval(loadServices, 15000);
