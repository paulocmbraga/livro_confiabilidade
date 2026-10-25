--
-- PostgreSQL database dump
--

\restrict 4nCmZfscQk4PhVNQ9DYeIYRSckNfzbtczcZmkejvDf387kcmJcgywelwP1Ev0Pb

-- Dumped from database version 18.6 (Debian 18.6-1.pgdg13+2)
-- Dumped by pg_dump version 18.6 (Debian 18.6-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

ALTER TABLE IF EXISTS ONLY l26_p22.outbox DROP CONSTRAINT IF EXISTS outbox_id_fkey;
ALTER TABLE IF EXISTS ONLY l26_p22.outbox DROP CONSTRAINT IF EXISTS outbox_pkey;
ALTER TABLE IF EXISTS ONLY l26_p22.jobs DROP CONSTRAINT IF EXISTS jobs_pkey;
ALTER TABLE IF EXISTS ONLY l26_p22.control DROP CONSTRAINT IF EXISTS control_pkey;
ALTER TABLE IF EXISTS ONLY l26_p22.attempts DROP CONSTRAINT IF EXISTS attempts_pkey;
DROP TABLE IF EXISTS l26_p22.outbox;
DROP TABLE IF EXISTS l26_p22.jobs;
DROP TABLE IF EXISTS l26_p22.control;
DROP TABLE IF EXISTS l26_p22.attempts;
DROP SCHEMA IF EXISTS l26_p22;
--
-- Name: l26_p22; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA l26_p22;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: attempts; Type: TABLE; Schema: l26_p22; Owner: -
--

CREATE TABLE l26_p22.attempts (
    id text NOT NULL,
    job text,
    mode text,
    token bigint,
    started timestamp with time zone DEFAULT clock_timestamp(),
    ended timestamp with time zone,
    outcome text
);


--
-- Name: control; Type: TABLE; Schema: l26_p22; Owner: -
--

CREATE TABLE l26_p22.control (
    id integer NOT NULL,
    admission boolean
);


--
-- Name: jobs; Type: TABLE; Schema: l26_p22; Owner: -
--

CREATE TABLE l26_p22.jobs (
    id text NOT NULL,
    request jsonb NOT NULL,
    state text DEFAULT 'prepared'::text NOT NULL,
    receipt jsonb,
    token bigint DEFAULT 0 NOT NULL,
    lease_until timestamp with time zone,
    updated timestamp with time zone DEFAULT clock_timestamp()
);


--
-- Name: outbox; Type: TABLE; Schema: l26_p22; Owner: -
--

CREATE TABLE l26_p22.outbox (
    id text NOT NULL,
    pending boolean DEFAULT true NOT NULL
);


--
-- Data for Name: attempts; Type: TABLE DATA; Schema: l26_p22; Owner: -
--

COPY l26_p22.attempts (id, job, mode, token, started, ended, outcome) FROM stdin;
\.


--
-- Data for Name: control; Type: TABLE DATA; Schema: l26_p22; Owner: -
--

COPY l26_p22.control (id, admission) FROM stdin;
1	t
\.


--
-- Data for Name: jobs; Type: TABLE DATA; Schema: l26_p22; Owner: -
--

COPY l26_p22.jobs (id, request, state, receipt, token, lease_until, updated) FROM stdin;
\.


--
-- Data for Name: outbox; Type: TABLE DATA; Schema: l26_p22; Owner: -
--

COPY l26_p22.outbox (id, pending) FROM stdin;
\.


--
-- Name: attempts attempts_pkey; Type: CONSTRAINT; Schema: l26_p22; Owner: -
--

ALTER TABLE ONLY l26_p22.attempts
    ADD CONSTRAINT attempts_pkey PRIMARY KEY (id);


--
-- Name: control control_pkey; Type: CONSTRAINT; Schema: l26_p22; Owner: -
--

ALTER TABLE ONLY l26_p22.control
    ADD CONSTRAINT control_pkey PRIMARY KEY (id);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: l26_p22; Owner: -
--

ALTER TABLE ONLY l26_p22.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);


--
-- Name: outbox outbox_pkey; Type: CONSTRAINT; Schema: l26_p22; Owner: -
--

ALTER TABLE ONLY l26_p22.outbox
    ADD CONSTRAINT outbox_pkey PRIMARY KEY (id);


--
-- Name: outbox outbox_id_fkey; Type: FK CONSTRAINT; Schema: l26_p22; Owner: -
--

ALTER TABLE ONLY l26_p22.outbox
    ADD CONSTRAINT outbox_id_fkey FOREIGN KEY (id) REFERENCES l26_p22.jobs(id);


--
-- PostgreSQL database dump complete
--

\unrestrict 4nCmZfscQk4PhVNQ9DYeIYRSckNfzbtczcZmkejvDf387kcmJcgywelwP1Ev0Pb

