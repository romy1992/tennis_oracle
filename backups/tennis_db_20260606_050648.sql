--
-- PostgreSQL database dump
--

\restrict wmaLvfzq2Ey2k2CCPNxawF0RHc5DszP9dt8jIQ7M5woeo6PoOWY0bHyHD8jdUc1

-- Dumped from database version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: event; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.event (
    id_event integer NOT NULL,
    event_type_key integer,
    event_type_type character varying
);


ALTER TABLE public.event OWNER TO postgres;

--
-- Name: event_id_event_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.event_id_event_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.event_id_event_seq OWNER TO postgres;

--
-- Name: event_id_event_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.event_id_event_seq OWNED BY public.event.id_event;


--
-- Name: fixture; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.fixture (
    id_fixture integer NOT NULL,
    event_key integer NOT NULL,
    event_date date,
    event_time time without time zone,
    event_first_player character varying,
    first_player_key integer,
    event_second_player character varying,
    second_player_key integer,
    event_final_result character varying,
    event_game_result character varying,
    event_serve character varying,
    event_winner character varying,
    event_status character varying,
    event_type_type character varying,
    tournament_name character varying,
    tournament_key integer,
    tournament_round character varying,
    tournament_season character varying,
    event_live character varying,
    event_first_player_logo character varying,
    event_second_player_logo character varying,
    event_qualification character varying,
    pointbypoint json,
    scores json,
    statistics json,
    odds json
);


ALTER TABLE public.fixture OWNER TO postgres;

--
-- Name: fixture_id_fixture_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.fixture_id_fixture_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.fixture_id_fixture_seq OWNER TO postgres;

--
-- Name: fixture_id_fixture_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.fixture_id_fixture_seq OWNED BY public.fixture.id_fixture;


--
-- Name: player; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.player (
    id_player integer NOT NULL,
    player_key integer NOT NULL,
    player_name character varying,
    player_full_name character varying,
    player_country character varying,
    player_bday character varying,
    player_logo character varying,
    stats json,
    tournaments json
);


ALTER TABLE public.player OWNER TO postgres;

--
-- Name: player_id_player_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.player_id_player_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.player_id_player_seq OWNER TO postgres;

--
-- Name: player_id_player_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.player_id_player_seq OWNED BY public.player.id_player;


--
-- Name: standing; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.standing (
    id_standing integer NOT NULL,
    place integer,
    player character varying,
    player_key integer,
    league character varying,
    movement character varying,
    country character varying,
    points integer
);


ALTER TABLE public.standing OWNER TO postgres;

--
-- Name: standing_id_standing_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.standing_id_standing_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.standing_id_standing_seq OWNER TO postgres;

--
-- Name: standing_id_standing_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.standing_id_standing_seq OWNED BY public.standing.id_standing;


--
-- Name: tournament; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tournament (
    id_tournament integer NOT NULL,
    tournament_key integer,
    tournament_name character varying,
    event_type_key integer,
    event_type_type character varying,
    tournament_sourface character varying
);


ALTER TABLE public.tournament OWNER TO postgres;

--
-- Name: tournament_id_tournament_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tournament_id_tournament_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tournament_id_tournament_seq OWNER TO postgres;

--
-- Name: tournament_id_tournament_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tournament_id_tournament_seq OWNED BY public.tournament.id_tournament;


--
-- Name: event id_event; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.event ALTER COLUMN id_event SET DEFAULT nextval('public.event_id_event_seq'::regclass);


--
-- Name: fixture id_fixture; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.fixture ALTER COLUMN id_fixture SET DEFAULT nextval('public.fixture_id_fixture_seq'::regclass);


--
-- Name: player id_player; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.player ALTER COLUMN id_player SET DEFAULT nextval('public.player_id_player_seq'::regclass);


--
-- Name: standing id_standing; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.standing ALTER COLUMN id_standing SET DEFAULT nextval('public.standing_id_standing_seq'::regclass);


--
-- Name: tournament id_tournament; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tournament ALTER COLUMN id_tournament SET DEFAULT nextval('public.tournament_id_tournament_seq'::regclass);


--
-- Data for Name: event; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.event (id_event, event_type_key, event_type_type) FROM stdin;
\.


--
-- Data for Name: fixture; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.fixture (id_fixture, event_key, event_date, event_time, event_first_player, first_player_key, event_second_player, second_player_key, event_final_result, event_game_result, event_serve, event_winner, event_status, event_type_type, tournament_name, tournament_key, tournament_round, tournament_season, event_live, event_first_player_logo, event_second_player_logo, event_qualification, pointbypoint, scores, statistics, odds) FROM stdin;
\.


--
-- Data for Name: player; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.player (id_player, player_key, player_name, player_full_name, player_country, player_bday, player_logo, stats, tournaments) FROM stdin;
\.


--
-- Data for Name: standing; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.standing (id_standing, place, player, player_key, league, movement, country, points) FROM stdin;
\.


--
-- Data for Name: tournament; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.tournament (id_tournament, tournament_key, tournament_name, event_type_key, event_type_type, tournament_sourface) FROM stdin;
\.


--
-- Name: event_id_event_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.event_id_event_seq', 1, false);


--
-- Name: fixture_id_fixture_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.fixture_id_fixture_seq', 1, false);


--
-- Name: player_id_player_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.player_id_player_seq', 1, false);


--
-- Name: standing_id_standing_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.standing_id_standing_seq', 1, false);


--
-- Name: tournament_id_tournament_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.tournament_id_tournament_seq', 1, false);


--
-- Name: event event_event_type_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT event_event_type_key_key UNIQUE (event_type_key);


--
-- Name: event event_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT event_pkey PRIMARY KEY (id_event);


--
-- Name: fixture fixture_event_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.fixture
    ADD CONSTRAINT fixture_event_key_key UNIQUE (event_key);


--
-- Name: fixture fixture_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.fixture
    ADD CONSTRAINT fixture_pkey PRIMARY KEY (id_fixture);


--
-- Name: player player_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.player
    ADD CONSTRAINT player_pkey PRIMARY KEY (id_player);


--
-- Name: player player_player_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.player
    ADD CONSTRAINT player_player_key_key UNIQUE (player_key);


--
-- Name: standing standing_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.standing
    ADD CONSTRAINT standing_pkey PRIMARY KEY (id_standing);


--
-- Name: tournament tournament_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tournament
    ADD CONSTRAINT tournament_pkey PRIMARY KEY (id_tournament);


--
-- Name: tournament tournament_tournament_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tournament
    ADD CONSTRAINT tournament_tournament_key_key UNIQUE (tournament_key);


--
-- PostgreSQL database dump complete
--

\unrestrict wmaLvfzq2Ey2k2CCPNxawF0RHc5DszP9dt8jIQ7M5woeo6PoOWY0bHyHD8jdUc1

