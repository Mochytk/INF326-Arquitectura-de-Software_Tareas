import { createSchema } from 'graphql-yoga';
import { call, requireUser, urls } from './upstream.js';

const URL_RE = /https?:\/\/[^\s<>]+/g;
const enc = encodeURIComponent;

export const typeDefs = /* GraphQL */ `
  scalar DateTime
  scalar File

  type User { id: ID! displayName: String! }

  type Channel {
    id: ID!
    name: String!
    "Los últimos mensajes; offset salta los más recientes."
    messages(limit: Int = 50, offset: Int = 0): [Message!]!
    attachments(category: AttachmentCategory, limit: Int = 20, offset: Int = 0): [Attachment!]!
    quota: Quota
  }

  type Message {
    id: ID!
    channelId: ID!
    channel: Channel
    author: User
    content: String!
    createdAt: DateTime!
    reactions: ReactionSummary
    previews: [LinkPreview!]!
    "Solo en resultados de búsqueda."
    highlights: [String!]!
    mentions: [ID!]!
    has: [String!]!
  }

  type ReactionSummary { total: Int! counts: [ReactionCount!]! reactions: [Reaction!]! }
  type ReactionCount { type: String! count: Int! }
  type Reaction { id: ID! messageId: ID! user: User type: String! createdAt: DateTime! }

  enum AttachmentCategory { IMAGE DOCUMENT LINK }
  type Attachment {
    id: ID!
    category: AttachmentCategory
    filename: String
    mimeType: String
    sizeBytes: Float
    url: String
    uploader: User
    createdAt: DateTime
    "Relativa al gateway; el navegador debe agregar ?userId=."
    downloadUrl: String
  }
  type Quota { usedBytes: Float! limitBytes: Float! availableBytes: Float! fileCount: Int! maxFiles: Int! maxFileBytes: Float! }
  type LinkPreview { url: String! finalUrl: String title: String description: String imageUrl: String }

  enum Has { LINK MENTION }
  enum SortBy { TIMESTAMP RELEVANCE }
  enum SortOrder { DESC ASC }
  type SearchResult { total: Int! messages: [Message!]! }
  type ServiceStatus { name: String! up: Boolean! latencyMs: Int }

  type Query {
    channels: [Channel!]!
    channel(id: ID!): Channel
    user(id: ID!): User
    search(
      content: String, authorIds: [ID!] = [], channelIds: [ID!] = [], mentions: [ID!] = [],
      has: [Has!] = [], sortBy: SortBy = TIMESTAMP, order: SortOrder = DESC,
      limit: Int = 25, offset: Int = 0
    ): SearchResult!
    preview(url: String!): LinkPreview
    services: [ServiceStatus!]!
  }

  type Mutation {
    createUser(displayName: String!): User!
    createChannel(name: String!): Channel!
    "El autor es el header X-User-Id salvo que se indique authorId."
    sendMessage(channelId: ID!, content: String!, authorId: ID): Message!
    addReaction(messageId: ID!, type: String!): Reaction!
    removeReaction(id: ID!): Boolean!
    uploadAttachment(channelId: ID!, file: File!): Attachment!
    deleteAttachment(id: ID!): Boolean!
  }
`;

const query = (params) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    for (const item of [value].flat()) if (item !== undefined && item !== null) search.append(key, item);
  }
  return search.toString();
};

async function health(name) {
  const started = Date.now();
  try {
    const response = await fetch(`${urls[name]}/health`, { signal: AbortSignal.timeout(2000) });
    return { name, up: response.ok, latencyMs: Date.now() - started };
  } catch {
    return { name, up: false, latencyMs: null };
  }
}

export const resolvers = {
  Query: {
    channels: () => call('channels', '/api/v1/channels'),
    channel: (_, { id }) => call('channels', `/api/v1/channels/${enc(id)}`, { nullOn404: true }),
    user: (_, { id }, { loaders }) => loaders.user.load(id),
    preview: (_, { url }, { loaders }) => loaders.preview.load(url),
    services: () => Promise.all(Object.keys(urls).map(health)),
    async search(_, args) {
      const data = await call('search', `/api/v1/search/messages?${query({
        content: args.content, author_id: args.authorIds, channel_id: args.channelIds,
        mentions: args.mentions, has: args.has.map((h) => h.toLowerCase()),
        sort_by: args.sortBy.toLowerCase(), sort_order: args.order.toLowerCase(),
        limit: args.limit, offset: args.offset,
      })}`);
      // 202: el índice aún no está listo y no trae resultados.
      return { total: data.total_results ?? 0, messages: data.messages ?? [] };
    },
  },

  Mutation: {
    createUser: (_, { displayName }) => call('users', '/api/v1/users', { method: 'POST', json: { display_name: displayName } }),
    createChannel: (_, { name }) => call('channels', '/api/v1/channels', { method: 'POST', json: { name } }),
    sendMessage: (_, { channelId, content, authorId }, context) =>
      call('messages', `/api/v1/channels/${enc(channelId)}/messages`, {
        method: 'POST', json: { author_id: authorId ?? requireUser(context), content },
      }),
    addReaction: (_, { messageId, type }, context) =>
      call('reactions', '/api/v1/reactions', {
        method: 'POST', json: { message_id: messageId, user_id: requireUser(context), reaction_type: type },
      }),
    removeReaction: async (_, { id }) => {
      await call('reactions', `/api/v1/reactions/${enc(id)}`, { method: 'DELETE' });
      return true;
    },
    uploadAttachment: async (_, { channelId, file }, context) => {
      const form = new FormData();
      // El File de Yoga no es el de Node: se copia a un Blob. shortcut: el archivo pasa entero
      // por memoria; aceptable bajo el tope de Media, pasar a streaming si crece.
      form.append('file', new Blob([await file.arrayBuffer()], { type: file.type }), file.name);
      return call('media', `/api/v1/channels/${enc(channelId)}/attachments`, { method: 'POST', form, userId: requireUser(context) });
    },
    deleteAttachment: async (_, { id }, context) => {
      await call('media', `/api/v1/attachments/${enc(id)}`, { method: 'DELETE', userId: requireUser(context) });
      return true;
    },
  },

  User: { displayName: (user) => user.display_name },

  Channel: {
    async messages(channel, { limit, offset }) {
      const all = await call('messages', `/api/v1/channels/${enc(channel.id)}/messages`);
      all.sort((a, b) => a.created_at.localeCompare(b.created_at));
      // shortcut: el núcleo no pagina, se trae todo y se corta aquí; migrar a cursor si el canal crece.
      return all.slice(Math.max(0, all.length - offset - limit), all.length - offset);
    },
    async attachments(channel, { category, limit, offset }, context) {
      const data = await call('media', `/api/v1/channels/${enc(channel.id)}/attachments?${query({ category, limit, offset })}`, { userId: requireUser(context) });
      return data.items;
    },
    quota: (channel, _, context) => call('media', `/api/v1/channels/${enc(channel.id)}/quota`, { userId: requireUser(context) }),
  },

  Message: {
    channelId: (m) => m.channel_id,
    channel: (m, _, { loaders }) => loaders.channel.load(m.channel_id),
    author: (m, _, { loaders }) => loaders.user.load(m.author_id),
    createdAt: (m) => m.created_at,
    reactions: (m, _, { loaders }) => loaders.reactions.load(m.id),
    async previews(m, _, { loaders }) {
      const urlsInMessage = m.links?.length ? m.links : (m.content.match(URL_RE) ?? []);
      const previews = await Promise.all(urlsInMessage.map((url) => loaders.preview.load(url).catch(() => null)));
      return previews.filter(Boolean);
    },
    highlights: (m) => m.highlights ?? [],
    mentions: (m) => m.mentions ?? [],
    has: (m) => m.has ?? [],
  },

  ReactionSummary: {
    total: (r) => r.total_reactions,
    counts: (r) => r.summary.map((s) => ({ type: s.reaction_type, count: s.count })),
  },
  Reaction: {
    messageId: (r) => r.message_id,
    user: (r, _, { loaders }) => loaders.user.load(r.user_id),
    type: (r) => r.reaction_type,
    createdAt: (r) => r.created_at,
  },

  Attachment: {
    mimeType: (a) => a.mime_type,
    sizeBytes: (a) => a.size_bytes,
    createdAt: (a) => a.created_at,
    uploader: (a, _, { loaders }) => (a.uploader_id ? loaders.user.load(a.uploader_id) : null),
    downloadUrl: (a) => (a.category === 'LINK' ? null : `/files/${a.id}`),
  },
  Quota: {
    usedBytes: (q) => q.used_bytes, limitBytes: (q) => q.limit_bytes, availableBytes: (q) => q.available_bytes,
    fileCount: (q) => q.file_count, maxFiles: (q) => q.max_files, maxFileBytes: (q) => q.max_file_bytes,
  },
  LinkPreview: { finalUrl: (p) => p.final_url, imageUrl: (p) => p.image_url },
};

export const schema = createSchema({ typeDefs, resolvers });
