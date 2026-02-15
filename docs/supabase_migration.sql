-- Supabase migration: Add FreeRADIUS tables for iron-claw RADIUS session control
--
-- This migration creates the standard FreeRADIUS SQL tables needed by rlm_sql_postgresql:
--   radcheck, radreply, radusergroup, radgroupcheck, radgroupreply, radacct, radpostauth
--
-- It also seeds the iron-claw-scraper user with password + VSA reply attributes.
--
-- Target: missing-table Supabase database
-- Migration name: 20260215000000_add_radius_tables.sql
--
-- IMPORTANT: This is additive only — no changes to existing tables.

-- ============================================================================
-- radcheck: Per-user check attributes (authentication)
-- ============================================================================
CREATE TABLE IF NOT EXISTS radcheck (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    attribute TEXT NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT ':=',
    value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radcheck_username ON radcheck (username);

-- ============================================================================
-- radreply: Per-user reply attributes (authorization)
-- ============================================================================
CREATE TABLE IF NOT EXISTS radreply (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    attribute TEXT NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT ':=',
    value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radreply_username ON radreply (username);

-- ============================================================================
-- radusergroup: User-to-group mappings
-- ============================================================================
CREATE TABLE IF NOT EXISTS radusergroup (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    groupname TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS radusergroup_username ON radusergroup (username);

-- ============================================================================
-- radgroupcheck: Per-group check attributes
-- ============================================================================
CREATE TABLE IF NOT EXISTS radgroupcheck (
    id BIGSERIAL PRIMARY KEY,
    groupname TEXT NOT NULL DEFAULT '',
    attribute TEXT NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT ':=',
    value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radgroupcheck_groupname ON radgroupcheck (groupname);

-- ============================================================================
-- radgroupreply: Per-group reply attributes
-- ============================================================================
CREATE TABLE IF NOT EXISTS radgroupreply (
    id BIGSERIAL PRIMARY KEY,
    groupname TEXT NOT NULL DEFAULT '',
    attribute TEXT NOT NULL DEFAULT '',
    op CHAR(2) NOT NULL DEFAULT ':=',
    value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radgroupreply_groupname ON radgroupreply (groupname);

-- ============================================================================
-- radacct: Accounting records
-- ============================================================================
CREATE TABLE IF NOT EXISTS radacct (
    radacctid BIGSERIAL PRIMARY KEY,
    acctsessionid TEXT NOT NULL DEFAULT '',
    acctuniqueid TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    nasipaddress TEXT NOT NULL DEFAULT '',
    nasportid TEXT,
    nasporttype TEXT,
    acctstarttime TIMESTAMPTZ,
    acctupdatetime TIMESTAMPTZ,
    acctstoptime TIMESTAMPTZ,
    acctsessiontime BIGINT,
    acctauthentic TEXT,
    connectinfo_connect TEXT,
    connectinfo_stop TEXT,
    acctinputoctets BIGINT,   -- Repurposed: stores token count
    acctoutputoctets BIGINT,  -- Repurposed: stores matches found
    calledstationid TEXT,
    callingstationid TEXT,
    acctterminatecause TEXT,
    servicetype TEXT,
    framedprotocol TEXT,
    framedipaddress TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS radacct_acctuniqueid ON radacct (acctuniqueid);
CREATE INDEX IF NOT EXISTS radacct_acctsessionid ON radacct (acctsessionid);
CREATE INDEX IF NOT EXISTS radacct_username ON radacct (username);
CREATE INDEX IF NOT EXISTS radacct_acctstarttime ON radacct (acctstarttime);
CREATE INDEX IF NOT EXISTS radacct_acctstoptime ON radacct (acctstoptime);

-- ============================================================================
-- radpostauth: Post-authentication logging
-- ============================================================================
CREATE TABLE IF NOT EXISTS radpostauth (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    pass TEXT NOT NULL DEFAULT '',
    reply TEXT NOT NULL DEFAULT '',
    authdate TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS radpostauth_username ON radpostauth (username);

-- ============================================================================
-- Seed data: iron-claw-scraper user
-- ============================================================================

-- Authentication: Cleartext-Password for PAP
INSERT INTO radcheck (username, attribute, op, value) VALUES
    ('iron-claw-scraper', 'Cleartext-Password', ':=', 'scraper-secret');

-- Reply attributes: standard RADIUS + MissTable VSAs
INSERT INTO radreply (username, attribute, op, value) VALUES
    ('iron-claw-scraper', 'Session-Timeout',      ':=', '1800'),
    ('iron-claw-scraper', 'MT-Token-Budget',       ':=', '50000'),
    ('iron-claw-scraper', 'MT-Model-Allowed',      ':=', 'claude-haiku-4-5'),
    ('iron-claw-scraper', 'MT-Allowed-Domains',    ':=', 'mlssoccer.com'),
    ('iron-claw-scraper', 'MT-Browser-Enabled',    ':=', '0'),
    ('iron-claw-scraper', 'MT-Shell-Enabled',      ':=', '0'),
    ('iron-claw-scraper', 'MT-Max-Pages',          ':=', '20'),
    ('iron-claw-scraper', 'MT-Max-LLM-Calls',      ':=', '100'),
    ('iron-claw-scraper', 'MT-Output-Queue',       ':=', 'match_processing'),
    ('iron-claw-scraper', 'MT-Monthly-Budget',     ':=', '500000');
