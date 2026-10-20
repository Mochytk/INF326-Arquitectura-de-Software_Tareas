CREATE TABLE outbox_events (
	event_id VARCHAR NOT NULL,
	payload JSON NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (event_id)
);

CREATE INDEX ix_outbox_events_created_at ON outbox_events (created_at);

CREATE TABLE reactions (
	id VARCHAR NOT NULL,
	message_id VARCHAR NOT NULL,
	user_id VARCHAR NOT NULL,
	reaction_type VARCHAR NOT NULL,
	created_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
	PRIMARY KEY (id),
	CONSTRAINT uq_reaction_message_user_type UNIQUE (message_id, user_id, reaction_type)
);

CREATE INDEX ix_reactions_id ON reactions (id);

CREATE INDEX ix_reactions_message_id ON reactions (message_id);

CREATE INDEX ix_reactions_user_id ON reactions (user_id);
