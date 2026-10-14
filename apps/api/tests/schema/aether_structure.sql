-- Structure (no data) of the Aether API database, loaded into the `aether_test` schema of the throw-away Postgres
-- service container of each API test job in .github/workflows/ci.yml.
--
-- Source: pg_dump --schema-only of the production schema (48 tables, enums, sequences, indexes, constraints) taken on
-- 2026-10-13 and renamed to aether_test. packages/db/src/schema.prisma documents only part of it (columns such as
-- Job.postedAt are added by the API's lazy DDL), so `prisma db push` alone is NOT enough for the suite.
--
-- Regenerate on the VPS (structure only, never data; drop the pg_dump \restrict lines, rename the schema):
--   docker exec aether-prod-postgres pg_dump -U aether -d aether_prod --schema-only --no-owner --no-privileges \
--     --no-comments -n aether | grep -v '^\\' | sed -e 's/aether\./aether_test./g' \
--     -e 's/CREATE SCHEMA aether;/CREATE SCHEMA IF NOT EXISTS aether_test;/'
--
-- PostgreSQL database dump
--


-- Dumped from database version 18.6
-- Dumped by pg_dump version 18.6

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

--
-- Name: aether; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS aether_test;


--
-- Name: AgentRunStatus; Type: TYPE; Schema: aether_test; Owner: -
--

CREATE TYPE aether_test."AgentRunStatus" AS ENUM (
    'queued',
    'running',
    'completed',
    'failed'
);


--
-- Name: ApplicationStatus; Type: TYPE; Schema: aether_test; Owner: -
--

CREATE TYPE aether_test."ApplicationStatus" AS ENUM (
    'draft',
    'submitted',
    'screening',
    'interview',
    'offer',
    'rejected',
    'withdrawn'
);


--
-- Name: ApprovalStatus; Type: TYPE; Schema: aether_test; Owner: -
--

CREATE TYPE aether_test."ApprovalStatus" AS ENUM (
    'pending',
    'approved',
    'rejected'
);


--
-- Name: ApprovalType; Type: TYPE; Schema: aether_test; Owner: -
--

CREATE TYPE aether_test."ApprovalType" AS ENUM (
    'application_submit',
    'email_send',
    'offer_response'
);


--
-- Name: ContactStage; Type: TYPE; Schema: aether_test; Owner: -
--

CREATE TYPE aether_test."ContactStage" AS ENUM (
    'identified',
    'contacted',
    'responded',
    'meeting',
    'referral'
);


--
-- Name: JobStatus; Type: TYPE; Schema: aether_test; Owner: -
--

CREATE TYPE aether_test."JobStatus" AS ENUM (
    'discovered',
    'screening',
    'matched',
    'tailoring',
    'ready',
    'applied',
    'archived',
    'rejected'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: AdminAuditLog; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AdminAuditLog" (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    "actorUserId" text NOT NULL,
    action text NOT NULL,
    "targetType" text,
    "targetId" text,
    "detailJson" jsonb,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    ip text
);


--
-- Name: AdminSetting; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AdminSetting" (
    key text NOT NULL,
    value jsonb NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: AgentConfig; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AgentConfig" (
    "userId" text NOT NULL,
    "agentKey" text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    model text,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL,
    "credentialRef" text,
    provider text,
    "authMode" text,
    temperature double precision DEFAULT 0.7,
    "thinkingEffort" text DEFAULT 'medium'::text
);


--
-- Name: AgentDirective; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AgentDirective" (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    "userId" text NOT NULL,
    "agentKey" text NOT NULL,
    directive jsonb NOT NULL,
    clamped jsonb,
    "rejectedKeys" jsonb,
    rationale text NOT NULL,
    "metricsCited" jsonb NOT NULL,
    "issuedBy" text DEFAULT 'supervisor-rules'::text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    "supersededById" text,
    outcome jsonb,
    "issuedAt" timestamp with time zone DEFAULT now() NOT NULL,
    "expiresAt" timestamp with time zone,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: AgentProvider; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AgentProvider" (
    "userId" text NOT NULL,
    provider text NOT NULL,
    status text DEFAULT 'connected'::text NOT NULL,
    model text,
    detail text,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: AgentQuotaBlock; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AgentQuotaBlock" (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    "userId" text NOT NULL,
    provider text NOT NULL,
    "expiresAt" timestamp with time zone NOT NULL,
    reason text,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: AgentRun; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AgentRun" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "agentName" text NOT NULL,
    status aether_test."AgentRunStatus" DEFAULT 'queued'::aether_test."AgentRunStatus" NOT NULL,
    input jsonb,
    output jsonb,
    error text,
    "costUsd" numeric(10,4),
    "startedAt" timestamp(3) without time zone,
    "completedAt" timestamp(3) without time zone,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "billingAuditJson" jsonb,
    "heartbeatAt" timestamp without time zone,
    "applicationId" text,
    "jobId" text,
    "policyTier" text,
    "metricSnapshot" jsonb,
    "qualityAttempts" jsonb,
    "qualityGateState" text,
    "parentRunId" text
);


--
-- Name: AnswerBankItem; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AnswerBankItem" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "questionText" text NOT NULL,
    "semanticKey" text NOT NULL,
    answer text NOT NULL,
    scope text DEFAULT 'global'::text NOT NULL,
    "scopeValue" text DEFAULT ''::text NOT NULL,
    provenance text NOT NULL,
    "provenanceDetail" text,
    sensitivity text DEFAULT 'factual'::text NOT NULL,
    "staleDays" integer,
    "expiresAt" timestamp with time zone,
    "autoAnswerOptIn" boolean DEFAULT false NOT NULL,
    "timesUsed" integer DEFAULT 0 NOT NULL,
    "lastUsedAt" timestamp with time zone,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: AnswerBankUsage; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AnswerBankUsage" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "itemId" text NOT NULL,
    "applicationId" text,
    "jobId" text,
    "questionAsSeen" text NOT NULL,
    "matchConfidence" double precision NOT NULL,
    "matchMethod" text NOT NULL,
    "usedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: AnthropicOAuthState; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AnthropicOAuthState" (
    "stateToken" text NOT NULL,
    "userId" text NOT NULL,
    "codeVerifier" text NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "expiresAt" timestamp with time zone DEFAULT (now() + '00:10:00'::interval) NOT NULL,
    provider text DEFAULT 'anthropic'::text NOT NULL,
    "redirectUri" text
);


--
-- Name: AnthropicOAuthToken; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."AnthropicOAuthToken" (
    "userId" text NOT NULL,
    ciphertext text NOT NULL,
    "refreshCipher" text,
    "secretHint" text,
    "expiresAt" timestamp with time zone,
    scopes text,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: Application; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."Application" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "jobId" text NOT NULL,
    "resumeId" text NOT NULL,
    status aether_test."ApplicationStatus" DEFAULT 'draft'::aether_test."ApplicationStatus" NOT NULL,
    "coverLetter" text,
    answers jsonb,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "transmittedAt" timestamp with time zone,
    "transmittedTo" text,
    "transmissionChannel" text,
    "transmissionRef" text,
    "coverLetterQuality" jsonb,
    "atsScoreAtSubmission" double precision,
    "tailoredResumeVersionId" text,
    "dimensionScoresAtSubmission" jsonb,
    "policyTierAtSubmission" text,
    "applyChannel" text,
    "manualStepReason" text,
    "manualStepDetail" text,
    "manualStepAt" timestamp with time zone,
    "submissionTruthState" text,
    "submissionTruthAt" timestamp with time zone,
    "manualStepQuestions" jsonb,
    "applyResolvedFrom" text,
    "applyResolvedUrl" text,
    "applyResolvedAt" timestamp with time zone,
    "siteSubmittedAt" timestamp with time zone
);


--
-- Name: ApplicationStatusEvent; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."ApplicationStatusEvent" (
    id text NOT NULL,
    seq bigint NOT NULL,
    "applicationId" text NOT NULL,
    "fromStatus" text,
    "toStatus" text NOT NULL,
    at timestamp with time zone DEFAULT now() NOT NULL,
    source text NOT NULL
);


--
-- Name: ApplicationStatusEvent_seq_seq; Type: SEQUENCE; Schema: aether_test; Owner: -
--

CREATE SEQUENCE aether_test."ApplicationStatusEvent_seq_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ApplicationStatusEvent_seq_seq; Type: SEQUENCE OWNED BY; Schema: aether_test; Owner: -
--

ALTER SEQUENCE aether_test."ApplicationStatusEvent_seq_seq" OWNED BY aether_test."ApplicationStatusEvent".seq;


--
-- Name: ApprovalRequest; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."ApprovalRequest" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "applicationId" text,
    type aether_test."ApprovalType" NOT NULL,
    status aether_test."ApprovalStatus" DEFAULT 'pending'::aether_test."ApprovalStatus" NOT NULL,
    payload jsonb NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "resolvedAt" timestamp(3) without time zone,
    "executedAt" timestamp with time zone,
    "resolvedByUserId" text,
    "resolvedFromIp" text,
    "executionCompletedAt" timestamp with time zone
);


--
-- Name: BackgroundJob; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."BackgroundJob" (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    "userId" text NOT NULL,
    "agentKey" text NOT NULL,
    "runId" text,
    params jsonb,
    status text DEFAULT 'enqueued'::text NOT NULL,
    "arqJobId" text,
    result jsonb,
    error text,
    attempts integer DEFAULT 0 NOT NULL,
    "quotaReserved" boolean DEFAULT false NOT NULL,
    "quotaReservedAt" timestamp with time zone,
    "quotaRefundedAt" timestamp with time zone,
    "quotaReservedCount" integer DEFAULT 0 NOT NULL,
    "quotaRefundedCount" integer DEFAULT 0 NOT NULL,
    "startedAt" timestamp with time zone,
    "finishedAt" timestamp with time zone,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL,
    "singletonKey" text,
    "retryAfterSeconds" integer
);


--
-- Name: BrandDocumentTemplate; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."BrandDocumentTemplate" (
    id text NOT NULL,
    kind text NOT NULL,
    body text NOT NULL,
    footnote text NOT NULL,
    footer text NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: CareerProfile; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."CareerProfile" (
    "userId" text NOT NULL,
    source text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    url text,
    content jsonb,
    summary text,
    error text,
    "syncedAt" timestamp with time zone,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: Contact; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."Contact" (
    id text NOT NULL,
    "userId" text NOT NULL,
    name text NOT NULL,
    title text,
    company text,
    stage aether_test."ContactStage" DEFAULT 'identified'::aether_test."ContactStage" NOT NULL,
    email text,
    "linkedinUrl" text,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL
);


--
-- Name: EmailThread; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."EmailThread" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "applicationId" text,
    "contactId" text,
    subject text NOT NULL,
    messages jsonb NOT NULL,
    classification text,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "draftReply" text,
    "gmailThreadId" text,
    "gmailMessageId" text,
    labels text[],
    "gmailAccountId" text,
    "aiScore" integer,
    "lastMessageAt" timestamp with time zone,
    "draftReplyAt" timestamp with time zone,
    "aiInsights" jsonb
);


--
-- Name: EvidenceCorpusItem; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."EvidenceCorpusItem" (
    "userId" text NOT NULL,
    "itemId" text NOT NULL,
    claim text NOT NULL,
    category text,
    source text,
    "sourceUrl" text,
    "statedOrInferred" text,
    confidence text,
    note text,
    "asOf" timestamp with time zone,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: GmailAccount; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."GmailAccount" (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    "userId" text NOT NULL,
    "accountEmail" text,
    "accessTokenCipher" text,
    "refreshTokenCipher" text,
    "tokenExpiry" timestamp with time zone,
    scopes text,
    "isPrimary" boolean DEFAULT false NOT NULL,
    "syncStatus" text,
    "lastSyncedAt" timestamp with time zone,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL,
    "usedForSalesAgent" boolean DEFAULT false NOT NULL
);


--
-- Name: GoogleCredential; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."GoogleCredential" (
    "userId" text NOT NULL,
    "googleEmail" text,
    "refreshToken" text NOT NULL,
    "accessToken" text,
    "accessTokenExpiresAt" timestamp with time zone,
    scopes text,
    "connectedAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: InterviewPack; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."InterviewPack" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "jobId" text NOT NULL,
    "applicationId" text,
    zip bytea NOT NULL,
    manifest jsonb NOT NULL,
    "supervisorRunId" text,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: InterviewSchedule; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."InterviewSchedule" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "applicationId" text NOT NULL,
    type text DEFAULT 'video'::text NOT NULL,
    status text DEFAULT 'scheduled'::text NOT NULL,
    "scheduledAt" timestamp with time zone NOT NULL,
    "durationMinutes" integer DEFAULT 60,
    location text,
    "meetingLink" text,
    notes text,
    "contactName" text,
    "contactEmail" text,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL,
    "calendarEventId" text,
    "calendarHtmlLink" text,
    "calendarSyncStatus" text,
    "calendarSyncedAt" timestamp with time zone
);


--
-- Name: Job; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."Job" (
    id text NOT NULL,
    "userId" text NOT NULL,
    title text NOT NULL,
    company text NOT NULL,
    location text,
    remote boolean DEFAULT false NOT NULL,
    "salaryMin" integer,
    "salaryMax" integer,
    currency text,
    description text NOT NULL,
    requirements jsonb,
    source text NOT NULL,
    "sourceUrl" text,
    status aether_test."JobStatus" DEFAULT 'discovered'::aether_test."JobStatus" NOT NULL,
    "fitScore" double precision,
    "atsScore" double precision,
    saved boolean DEFAULT false NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "postedAt" timestamp(3) without time zone,
    "dedupHash" text,
    "contentHash" text,
    "coverFailureClearedAt" timestamp with time zone,
    "lastSeenAt" timestamp with time zone,
    "applyEmail" text,
    "applyEmailSource" text,
    "applyContactCheckedAt" timestamp with time zone,
    "resolvedApplyUrl" text,
    "resolvedApplyUrlSource" text,
    "resolvedAt" timestamp with time zone
);


--
-- Name: JobEmbedding; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."JobEmbedding" (
    id text NOT NULL,
    "jobId" text NOT NULL,
    vector double precision[],
    model text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: JobSourceStatus; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."JobSourceStatus" (
    "userId" text NOT NULL,
    source text NOT NULL,
    "lastSyncAt" timestamp with time zone DEFAULT now() NOT NULL,
    "lastFetched" integer DEFAULT 0 NOT NULL,
    "lastPersisted" integer DEFAULT 0 NOT NULL,
    "lastError" text,
    status text DEFAULT 'ok'::text NOT NULL
);


--
-- Name: NotificationDigest; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."NotificationDigest" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "approvalId" text,
    "windowStart" timestamp with time zone,
    "windowEnd" timestamp with time zone NOT NULL,
    "statusUpdates" integer DEFAULT 0 NOT NULL,
    "newMatches" integer DEFAULT 0 NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: Offer; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."Offer" (
    id text NOT NULL,
    "userId" text NOT NULL,
    company text NOT NULL,
    role text,
    base integer NOT NULL,
    bonus integer DEFAULT 0 NOT NULL,
    equity integer DEFAULT 0 NOT NULL,
    location text NOT NULL,
    currency text DEFAULT 'AUD'::text NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: OutreachTask; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."OutreachTask" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "contactId" text,
    type text DEFAULT 'message'::text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    message text,
    "scheduledAt" timestamp with time zone,
    "sentAt" timestamp with time zone,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: PasswordResetToken; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."PasswordResetToken" (
    id text NOT NULL,
    "userId" text NOT NULL,
    "tokenHash" text NOT NULL,
    "expiresAt" timestamp with time zone NOT NULL,
    "usedAt" timestamp with time zone,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: Plan; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."Plan" (
    id text NOT NULL,
    name text NOT NULL,
    "priceAudMonthly" numeric DEFAULT 0 NOT NULL,
    "priceAudAnnual" numeric,
    "runsPerMonth" integer NOT NULL,
    "modelTier" text NOT NULL,
    "spendCapUsdMonthly" numeric NOT NULL,
    "stripeProductId" text,
    "stripePriceIdMonthly" text,
    "stripePriceIdAnnual" text,
    active boolean DEFAULT true NOT NULL,
    "sortOrder" integer DEFAULT 0 NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "Plan_modelTier_check" CHECK (("modelTier" = ANY (ARRAY['light'::text, 'standard'::text, 'advanced'::text, 'premium'::text])))
);


--
-- Name: ProviderCredential; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."ProviderCredential" (
    provider text NOT NULL,
    "authMode" text NOT NULL,
    ciphertext text NOT NULL,
    "secretHint" text,
    "baseUrl" text,
    "lastVerifiedAt" timestamp with time zone,
    "lastVerifyStatus" text,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: Resume; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."Resume" (
    id text NOT NULL,
    "userId" text NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    label text,
    sections jsonb NOT NULL,
    "sourceJobId" text,
    "parentId" text,
    "formatHash" text NOT NULL,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "approvalStatus" text DEFAULT 'approved'::text NOT NULL,
    "originalFile" bytea,
    "originalFilename" text,
    "originalContentType" text
);


--
-- Name: RunPlan; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."RunPlan" (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    "userId" text NOT NULL,
    status text DEFAULT 'planned'::text NOT NULL,
    initiator text DEFAULT 'user'::text NOT NULL,
    concurrency integer DEFAULT 1 NOT NULL,
    "spacingSeconds" double precision DEFAULT 0 NOT NULL,
    steps jsonb NOT NULL,
    summary jsonb,
    "haltedAtStep" text,
    "haltReason" text,
    "startedAt" timestamp with time zone,
    "finishedAt" timestamp with time zone,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: SalesAgent; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."SalesAgent" (
    id text NOT NULL,
    name text NOT NULL,
    email text,
    "referralCode" text NOT NULL,
    "commissionPct" numeric DEFAULT 0 NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    notes text,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL,
    "createdBy" text
);


--
-- Name: SalesBrandArtifact; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."SalesBrandArtifact" (
    id text NOT NULL,
    kind text NOT NULL,
    "inputHash" text NOT NULL,
    input jsonb NOT NULL,
    content text NOT NULL,
    "createdById" text NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: SalesCampaign; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."SalesCampaign" (
    id text NOT NULL,
    name text NOT NULL,
    type text NOT NULL,
    "templateBody" text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: SalesLead; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."SalesLead" (
    id text NOT NULL,
    email text NOT NULL,
    name text,
    source text NOT NULL,
    "sourceThreadId" text,
    "userId" text,
    "consentType" text NOT NULL,
    "consentEvidence" text NOT NULL,
    status text DEFAULT 'new'::text NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: SalesOutreachLog; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."SalesOutreachLog" (
    id text NOT NULL,
    "leadId" text,
    "campaignId" text,
    channel text NOT NULL,
    "gmailMessageId" text,
    "gmailThreadId" text,
    subject text,
    body text,
    recipient text,
    "sentAt" timestamp with time zone,
    outcome text,
    detail text,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: SalesSuppressionList; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."SalesSuppressionList" (
    email text NOT NULL,
    reason text NOT NULL,
    "suppressedAt" timestamp with time zone DEFAULT now() NOT NULL,
    "sourceThreadId" text
);


--
-- Name: StoryEntry; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."StoryEntry" (
    id text NOT NULL,
    "userId" text NOT NULL,
    title text NOT NULL,
    situation text NOT NULL,
    task text NOT NULL,
    action text NOT NULL,
    result text NOT NULL,
    metrics jsonb,
    tags text[],
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "contentHash" text,
    "archivedAt" timestamp with time zone,
    "mergedIntoId" text,
    "mergeSnapshot" jsonb,
    "achievementKey" text
);


--
-- Name: StripeEvent; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."StripeEvent" (
    id text NOT NULL,
    type text NOT NULL,
    status text DEFAULT 'processing'::text NOT NULL,
    "payloadJson" jsonb,
    "receivedAt" timestamp with time zone DEFAULT now() NOT NULL,
    "processedAt" timestamp with time zone,
    CONSTRAINT "StripeEvent_status_check" CHECK ((status = ANY (ARRAY['processing'::text, 'processed'::text, 'failed'::text, 'ignored'::text])))
);


--
-- Name: Subscription; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."Subscription" (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    "userId" text NOT NULL,
    "planId" text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    "billingInterval" text,
    "stripeCustomerId" text,
    "stripeSubscriptionId" text,
    "currentPeriodStart" timestamp with time zone,
    "currentPeriodEnd" timestamp with time zone,
    "cancelAtPeriodEnd" boolean DEFAULT false NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL,
    "trialEndNotifiedAt" timestamp with time zone,
    "customPriceAud" numeric,
    "customPriceInterval" text,
    "customPriceStripeId" text,
    "customPriceSetAt" timestamp with time zone,
    "customPriceSetBy" text,
    CONSTRAINT "Subscription_billingInterval_check" CHECK (("billingInterval" = ANY (ARRAY['month'::text, 'year'::text]))),
    CONSTRAINT "Subscription_status_check" CHECK ((status = ANY (ARRAY['active'::text, 'trialing'::text, 'past_due'::text, 'canceled'::text, 'incomplete'::text, 'incomplete_expired'::text, 'unpaid'::text, 'paused'::text])))
);


--
-- Name: UsageQuota; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."UsageQuota" (
    id text DEFAULT (gen_random_uuid())::text NOT NULL,
    "userId" text NOT NULL,
    "planId" text NOT NULL,
    "periodStart" timestamp with time zone NOT NULL,
    "periodEnd" timestamp with time zone NOT NULL,
    "runsAllowed" integer NOT NULL,
    "runsUsed" integer DEFAULT 0 NOT NULL,
    "spendCapUsd" numeric NOT NULL,
    "spendUsedUsd" numeric DEFAULT 0 NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: User; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."User" (
    id text NOT NULL,
    email text NOT NULL,
    name text,
    image text,
    "createdAt" timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    "updatedAt" timestamp(3) without time zone NOT NULL,
    "passwordHash" text,
    "targetRole" text,
    location text,
    "agentConfig" jsonb DEFAULT '{"autoApply": false, "approvalGate": true, "matchThreshold": 80}'::jsonb,
    username text,
    "isAdmin" boolean DEFAULT false NOT NULL,
    suspended boolean DEFAULT false NOT NULL,
    "lastLoginAt" timestamp with time zone,
    "passwordChangedAt" timestamp with time zone,
    "deletedAt" timestamp with time zone,
    "mustChangePassword" boolean DEFAULT false NOT NULL,
    "referredBy" text,
    "avatarFile" bytea,
    "avatarContentType" text,
    "signupSource" text
);


--
-- Name: UserEntitlementOverride; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."UserEntitlementOverride" (
    id text NOT NULL,
    "userId" text NOT NULL,
    kind text NOT NULL,
    "planId" text,
    note text,
    "setBy" text NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: UserProviderCredential; Type: TABLE; Schema: aether_test; Owner: -
--

CREATE TABLE aether_test."UserProviderCredential" (
    id text NOT NULL,
    "userId" text NOT NULL,
    provider text NOT NULL,
    "authMode" text NOT NULL,
    ciphertext text NOT NULL,
    "secretHint" text,
    "baseUrl" text,
    "oauthScopes" text,
    "expiresAt" timestamp with time zone,
    "lastVerifiedAt" timestamp with time zone,
    "lastVerifyStatus" text,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT "UserProviderCredential_authMode_check" CHECK (("authMode" = ANY (ARRAY['api_key'::text, 'subscription_oauth'::text, 'oauth_token'::text])))
);


--
-- Name: ApplicationStatusEvent seq; Type: DEFAULT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."ApplicationStatusEvent" ALTER COLUMN seq SET DEFAULT nextval('aether_test."ApplicationStatusEvent_seq_seq"'::regclass);


--
-- Name: AdminAuditLog AdminAuditLog_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AdminAuditLog"
    ADD CONSTRAINT "AdminAuditLog_pkey" PRIMARY KEY (id);


--
-- Name: AdminSetting AdminSetting_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AdminSetting"
    ADD CONSTRAINT "AdminSetting_pkey" PRIMARY KEY (key);


--
-- Name: AgentConfig AgentConfig_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AgentConfig"
    ADD CONSTRAINT "AgentConfig_pkey" PRIMARY KEY ("userId", "agentKey");


--
-- Name: AgentDirective AgentDirective_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AgentDirective"
    ADD CONSTRAINT "AgentDirective_pkey" PRIMARY KEY (id);


--
-- Name: AgentProvider AgentProvider_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AgentProvider"
    ADD CONSTRAINT "AgentProvider_pkey" PRIMARY KEY ("userId", provider);


--
-- Name: AgentQuotaBlock AgentQuotaBlock_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AgentQuotaBlock"
    ADD CONSTRAINT "AgentQuotaBlock_pkey" PRIMARY KEY (id);


--
-- Name: AgentRun AgentRun_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AgentRun"
    ADD CONSTRAINT "AgentRun_pkey" PRIMARY KEY (id);


--
-- Name: AnswerBankItem AnswerBankItem_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AnswerBankItem"
    ADD CONSTRAINT "AnswerBankItem_pkey" PRIMARY KEY (id);


--
-- Name: AnswerBankUsage AnswerBankUsage_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AnswerBankUsage"
    ADD CONSTRAINT "AnswerBankUsage_pkey" PRIMARY KEY (id);


--
-- Name: AnthropicOAuthState AnthropicOAuthState_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AnthropicOAuthState"
    ADD CONSTRAINT "AnthropicOAuthState_pkey" PRIMARY KEY ("stateToken");


--
-- Name: AnthropicOAuthToken AnthropicOAuthToken_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AnthropicOAuthToken"
    ADD CONSTRAINT "AnthropicOAuthToken_pkey" PRIMARY KEY ("userId");


--
-- Name: ApplicationStatusEvent ApplicationStatusEvent_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."ApplicationStatusEvent"
    ADD CONSTRAINT "ApplicationStatusEvent_pkey" PRIMARY KEY (id);


--
-- Name: Application Application_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Application"
    ADD CONSTRAINT "Application_pkey" PRIMARY KEY (id);


--
-- Name: ApprovalRequest ApprovalRequest_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."ApprovalRequest"
    ADD CONSTRAINT "ApprovalRequest_pkey" PRIMARY KEY (id);


--
-- Name: BackgroundJob BackgroundJob_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."BackgroundJob"
    ADD CONSTRAINT "BackgroundJob_pkey" PRIMARY KEY (id);


--
-- Name: BrandDocumentTemplate BrandDocumentTemplate_kind_key; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."BrandDocumentTemplate"
    ADD CONSTRAINT "BrandDocumentTemplate_kind_key" UNIQUE (kind);


--
-- Name: BrandDocumentTemplate BrandDocumentTemplate_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."BrandDocumentTemplate"
    ADD CONSTRAINT "BrandDocumentTemplate_pkey" PRIMARY KEY (id);


--
-- Name: CareerProfile CareerProfile_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."CareerProfile"
    ADD CONSTRAINT "CareerProfile_pkey" PRIMARY KEY ("userId", source);


--
-- Name: Contact Contact_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Contact"
    ADD CONSTRAINT "Contact_pkey" PRIMARY KEY (id);


--
-- Name: EmailThread EmailThread_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."EmailThread"
    ADD CONSTRAINT "EmailThread_pkey" PRIMARY KEY (id);


--
-- Name: EvidenceCorpusItem EvidenceCorpusItem_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."EvidenceCorpusItem"
    ADD CONSTRAINT "EvidenceCorpusItem_pkey" PRIMARY KEY ("userId", "itemId");


--
-- Name: GmailAccount GmailAccount_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."GmailAccount"
    ADD CONSTRAINT "GmailAccount_pkey" PRIMARY KEY (id);


--
-- Name: GoogleCredential GoogleCredential_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."GoogleCredential"
    ADD CONSTRAINT "GoogleCredential_pkey" PRIMARY KEY ("userId");


--
-- Name: InterviewPack InterviewPack_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."InterviewPack"
    ADD CONSTRAINT "InterviewPack_pkey" PRIMARY KEY (id);


--
-- Name: InterviewPack InterviewPack_userId_jobId_key; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."InterviewPack"
    ADD CONSTRAINT "InterviewPack_userId_jobId_key" UNIQUE ("userId", "jobId");


--
-- Name: InterviewSchedule InterviewSchedule_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."InterviewSchedule"
    ADD CONSTRAINT "InterviewSchedule_pkey" PRIMARY KEY (id);


--
-- Name: JobEmbedding JobEmbedding_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."JobEmbedding"
    ADD CONSTRAINT "JobEmbedding_pkey" PRIMARY KEY (id);


--
-- Name: JobSourceStatus JobSourceStatus_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."JobSourceStatus"
    ADD CONSTRAINT "JobSourceStatus_pkey" PRIMARY KEY ("userId", source);


--
-- Name: Job Job_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Job"
    ADD CONSTRAINT "Job_pkey" PRIMARY KEY (id);


--
-- Name: NotificationDigest NotificationDigest_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."NotificationDigest"
    ADD CONSTRAINT "NotificationDigest_pkey" PRIMARY KEY (id);


--
-- Name: Offer Offer_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Offer"
    ADD CONSTRAINT "Offer_pkey" PRIMARY KEY (id);


--
-- Name: OutreachTask OutreachTask_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."OutreachTask"
    ADD CONSTRAINT "OutreachTask_pkey" PRIMARY KEY (id);


--
-- Name: PasswordResetToken PasswordResetToken_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."PasswordResetToken"
    ADD CONSTRAINT "PasswordResetToken_pkey" PRIMARY KEY (id);


--
-- Name: Plan Plan_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Plan"
    ADD CONSTRAINT "Plan_pkey" PRIMARY KEY (id);


--
-- Name: ProviderCredential ProviderCredential_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."ProviderCredential"
    ADD CONSTRAINT "ProviderCredential_pkey" PRIMARY KEY (provider);


--
-- Name: Resume Resume_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Resume"
    ADD CONSTRAINT "Resume_pkey" PRIMARY KEY (id);


--
-- Name: RunPlan RunPlan_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."RunPlan"
    ADD CONSTRAINT "RunPlan_pkey" PRIMARY KEY (id);


--
-- Name: SalesAgent SalesAgent_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."SalesAgent"
    ADD CONSTRAINT "SalesAgent_pkey" PRIMARY KEY (id);


--
-- Name: SalesBrandArtifact SalesBrandArtifact_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."SalesBrandArtifact"
    ADD CONSTRAINT "SalesBrandArtifact_pkey" PRIMARY KEY (id);


--
-- Name: SalesCampaign SalesCampaign_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."SalesCampaign"
    ADD CONSTRAINT "SalesCampaign_pkey" PRIMARY KEY (id);


--
-- Name: SalesLead SalesLead_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."SalesLead"
    ADD CONSTRAINT "SalesLead_pkey" PRIMARY KEY (id);


--
-- Name: SalesOutreachLog SalesOutreachLog_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."SalesOutreachLog"
    ADD CONSTRAINT "SalesOutreachLog_pkey" PRIMARY KEY (id);


--
-- Name: SalesSuppressionList SalesSuppressionList_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."SalesSuppressionList"
    ADD CONSTRAINT "SalesSuppressionList_pkey" PRIMARY KEY (email);


--
-- Name: StoryEntry StoryEntry_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."StoryEntry"
    ADD CONSTRAINT "StoryEntry_pkey" PRIMARY KEY (id);


--
-- Name: StripeEvent StripeEvent_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."StripeEvent"
    ADD CONSTRAINT "StripeEvent_pkey" PRIMARY KEY (id);


--
-- Name: Subscription Subscription_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Subscription"
    ADD CONSTRAINT "Subscription_pkey" PRIMARY KEY (id);


--
-- Name: UsageQuota UsageQuota_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."UsageQuota"
    ADD CONSTRAINT "UsageQuota_pkey" PRIMARY KEY (id);


--
-- Name: UserEntitlementOverride UserEntitlementOverride_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."UserEntitlementOverride"
    ADD CONSTRAINT "UserEntitlementOverride_pkey" PRIMARY KEY (id);


--
-- Name: UserEntitlementOverride UserEntitlementOverride_userId_key; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."UserEntitlementOverride"
    ADD CONSTRAINT "UserEntitlementOverride_userId_key" UNIQUE ("userId");


--
-- Name: UserProviderCredential UserProviderCredential_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."UserProviderCredential"
    ADD CONSTRAINT "UserProviderCredential_pkey" PRIMARY KEY (id);


--
-- Name: UserProviderCredential UserProviderCredential_userId_provider_key; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."UserProviderCredential"
    ADD CONSTRAINT "UserProviderCredential_userId_provider_key" UNIQUE ("userId", provider);


--
-- Name: User User_pkey; Type: CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."User"
    ADD CONSTRAINT "User_pkey" PRIMARY KEY (id);


--
-- Name: AdminAuditLog_actor_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "AdminAuditLog_actor_idx" ON aether_test."AdminAuditLog" USING btree ("actorUserId");


--
-- Name: AdminAuditLog_target_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "AdminAuditLog_target_idx" ON aether_test."AdminAuditLog" USING btree ("targetType", "targetId");


--
-- Name: AgentDirective_active_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "AgentDirective_active_key" ON aether_test."AgentDirective" USING btree ("userId", "agentKey") WHERE (status = 'active'::text);


--
-- Name: AgentDirective_status_expires_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "AgentDirective_status_expires_idx" ON aether_test."AgentDirective" USING btree (status, "expiresAt");


--
-- Name: AgentDirective_user_agent_issued_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "AgentDirective_user_agent_issued_idx" ON aether_test."AgentDirective" USING btree ("userId", "agentKey", "issuedAt" DESC);


--
-- Name: AgentQuotaBlock_user_provider_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "AgentQuotaBlock_user_provider_key" ON aether_test."AgentQuotaBlock" USING btree ("userId", provider);


--
-- Name: AgentRun_jobId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "AgentRun_jobId_idx" ON aether_test."AgentRun" USING btree ("jobId");


--
-- Name: AgentRun_parentRunId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "AgentRun_parentRunId_idx" ON aether_test."AgentRun" USING btree ("parentRunId") WHERE ("parentRunId" IS NOT NULL);


--
-- Name: AgentRun_status_heartbeatAt_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "AgentRun_status_heartbeatAt_idx" ON aether_test."AgentRun" USING btree (status, "heartbeatAt");


--
-- Name: AgentRun_status_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "AgentRun_status_idx" ON aether_test."AgentRun" USING btree (status);


--
-- Name: AgentRun_userId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "AgentRun_userId_idx" ON aether_test."AgentRun" USING btree ("userId");


--
-- Name: AnswerBankItem_key_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "AnswerBankItem_key_idx" ON aether_test."AnswerBankItem" USING btree ("userId", "semanticKey", scope, "scopeValue");


--
-- Name: AnswerBankUsage_item_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "AnswerBankUsage_item_idx" ON aether_test."AnswerBankUsage" USING btree ("userId", "itemId", "usedAt" DESC);


--
-- Name: Application_jobId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "Application_jobId_idx" ON aether_test."Application" USING btree ("jobId");


--
-- Name: Application_userId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "Application_userId_idx" ON aether_test."Application" USING btree ("userId");


--
-- Name: ApprovalRequest_status_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "ApprovalRequest_status_idx" ON aether_test."ApprovalRequest" USING btree (status);


--
-- Name: ApprovalRequest_userId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "ApprovalRequest_userId_idx" ON aether_test."ApprovalRequest" USING btree ("userId");


--
-- Name: BackgroundJob_active_singleton_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "BackgroundJob_active_singleton_idx" ON aether_test."BackgroundJob" USING btree ("userId", "agentKey") WHERE (("agentKey" = 'scout'::text) AND (status = ANY (ARRAY['enqueued'::text, 'processing'::text])));


--
-- Name: BackgroundJob_active_singleton_v2_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "BackgroundJob_active_singleton_v2_idx" ON aether_test."BackgroundJob" USING btree ("userId", "singletonKey") WHERE (("singletonKey" IS NOT NULL) AND (status = ANY (ARRAY['enqueued'::text, 'processing'::text])));


--
-- Name: BackgroundJob_status_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "BackgroundJob_status_idx" ON aether_test."BackgroundJob" USING btree (status);


--
-- Name: BackgroundJob_userId_createdAt_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "BackgroundJob_userId_createdAt_idx" ON aether_test."BackgroundJob" USING btree ("userId", "createdAt" DESC);


--
-- Name: Contact_userId_email_lower_uidx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "Contact_userId_email_lower_uidx" ON aether_test."Contact" USING btree ("userId", lower(email)) WHERE (email IS NOT NULL);


--
-- Name: Contact_userId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "Contact_userId_idx" ON aether_test."Contact" USING btree ("userId");


--
-- Name: EmailThread_userId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "EmailThread_userId_idx" ON aether_test."EmailThread" USING btree ("userId");


--
-- Name: EvidenceCorpusItem_user_source_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "EvidenceCorpusItem_user_source_idx" ON aether_test."EvidenceCorpusItem" USING btree ("userId", source);


--
-- Name: InterviewPack_user_job; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "InterviewPack_user_job" ON aether_test."InterviewPack" USING btree ("userId", "jobId");


--
-- Name: JobEmbedding_jobId_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "JobEmbedding_jobId_key" ON aether_test."JobEmbedding" USING btree ("jobId");


--
-- Name: Job_status_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "Job_status_idx" ON aether_test."Job" USING btree (status);


--
-- Name: Job_userId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "Job_userId_idx" ON aether_test."Job" USING btree ("userId");


--
-- Name: Job_userId_sourceUrl_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "Job_userId_sourceUrl_key" ON aether_test."Job" USING btree ("userId", "sourceUrl");


--
-- Name: Resume_userId_formatHash_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "Resume_userId_formatHash_idx" ON aether_test."Resume" USING btree ("userId", "formatHash");


--
-- Name: Resume_userId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "Resume_userId_idx" ON aether_test."Resume" USING btree ("userId");


--
-- Name: RunPlan_active_per_user_v1_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "RunPlan_active_per_user_v1_idx" ON aether_test."RunPlan" USING btree ("userId") WHERE (status = ANY (ARRAY['planned'::text, 'running'::text]));


--
-- Name: RunPlan_status_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "RunPlan_status_idx" ON aether_test."RunPlan" USING btree (status);


--
-- Name: RunPlan_userId_createdAt_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "RunPlan_userId_createdAt_idx" ON aether_test."RunPlan" USING btree ("userId", "createdAt" DESC);


--
-- Name: SalesAgent_referralCode_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "SalesAgent_referralCode_key" ON aether_test."SalesAgent" USING btree ("referralCode");


--
-- Name: SalesBrandArtifact_kind_inputHash_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "SalesBrandArtifact_kind_inputHash_key" ON aether_test."SalesBrandArtifact" USING btree (kind, "inputHash");


--
-- Name: SalesLead_email_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "SalesLead_email_key" ON aether_test."SalesLead" USING btree (lower(email));


--
-- Name: SalesOutreachLog_message_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "SalesOutreachLog_message_key" ON aether_test."SalesOutreachLog" USING btree ("gmailMessageId") WHERE ("gmailMessageId" IS NOT NULL);


--
-- Name: SalesOutreachLog_sent_thread_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "SalesOutreachLog_sent_thread_key" ON aether_test."SalesOutreachLog" USING btree ("gmailThreadId") WHERE ((outcome = 'sent'::text) AND (channel = 'email'::text));


--
-- Name: StoryEntry_userId_achievementKey_live_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "StoryEntry_userId_achievementKey_live_key" ON aether_test."StoryEntry" USING btree ("userId", "achievementKey") WHERE (("achievementKey" IS NOT NULL) AND ("archivedAt" IS NULL));


--
-- Name: StoryEntry_userId_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "StoryEntry_userId_idx" ON aether_test."StoryEntry" USING btree ("userId");


--
-- Name: Subscription_stripeSubscriptionId_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "Subscription_stripeSubscriptionId_key" ON aether_test."Subscription" USING btree ("stripeSubscriptionId") WHERE ("stripeSubscriptionId" IS NOT NULL);


--
-- Name: Subscription_userId_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "Subscription_userId_key" ON aether_test."Subscription" USING btree ("userId");


--
-- Name: UsageQuota_userId_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "UsageQuota_userId_key" ON aether_test."UsageQuota" USING btree ("userId");


--
-- Name: User_email_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "User_email_key" ON aether_test."User" USING btree (email);


--
-- Name: User_referredBy_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "User_referredBy_idx" ON aether_test."User" USING btree ("referredBy");


--
-- Name: User_signupSource_idx; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "User_signupSource_idx" ON aether_test."User" USING btree ("signupSource");


--
-- Name: User_username_key; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX "User_username_key" ON aether_test."User" USING btree (username);


--
-- Name: idx_appstatusevent_app_at; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX idx_appstatusevent_app_at ON aether_test."ApplicationStatusEvent" USING btree ("applicationId", at, seq);


--
-- Name: idx_emailthread_account; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX idx_emailthread_account ON aether_test."EmailThread" USING btree ("userId", "gmailAccountId");


--
-- Name: idx_emailthread_gmail; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX idx_emailthread_gmail ON aether_test."EmailThread" USING btree ("userId", "gmailThreadId");


--
-- Name: idx_emailthread_last_message; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX idx_emailthread_last_message ON aether_test."EmailThread" USING btree ("userId", "lastMessageAt" DESC);


--
-- Name: idx_notificationdigest_userId; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "idx_notificationdigest_userId" ON aether_test."NotificationDigest" USING btree ("userId");


--
-- Name: idx_offer_userId; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "idx_offer_userId" ON aether_test."Offer" USING btree ("userId");


--
-- Name: idx_password_reset_token_hash; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX idx_password_reset_token_hash ON aether_test."PasswordResetToken" USING btree ("tokenHash");


--
-- Name: idx_password_reset_token_userId; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE INDEX "idx_password_reset_token_userId" ON aether_test."PasswordResetToken" USING btree ("userId");


--
-- Name: uq_gmailaccount_one_primary; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX uq_gmailaccount_one_primary ON aether_test."GmailAccount" USING btree ("userId") WHERE "isPrimary";


--
-- Name: uq_gmailaccount_user_email; Type: INDEX; Schema: aether_test; Owner: -
--

CREATE UNIQUE INDEX uq_gmailaccount_user_email ON aether_test."GmailAccount" USING btree ("userId", "accountEmail");


--
-- Name: AgentRun AgentRun_userId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."AgentRun"
    ADD CONSTRAINT "AgentRun_userId_fkey" FOREIGN KEY ("userId") REFERENCES aether_test."User"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ApplicationStatusEvent ApplicationStatusEvent_applicationId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."ApplicationStatusEvent"
    ADD CONSTRAINT "ApplicationStatusEvent_applicationId_fkey" FOREIGN KEY ("applicationId") REFERENCES aether_test."Application"(id) ON DELETE CASCADE;


--
-- Name: Application Application_jobId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Application"
    ADD CONSTRAINT "Application_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES aether_test."Job"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Application Application_resumeId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Application"
    ADD CONSTRAINT "Application_resumeId_fkey" FOREIGN KEY ("resumeId") REFERENCES aether_test."Resume"(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: Application Application_userId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Application"
    ADD CONSTRAINT "Application_userId_fkey" FOREIGN KEY ("userId") REFERENCES aether_test."User"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ApprovalRequest ApprovalRequest_applicationId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."ApprovalRequest"
    ADD CONSTRAINT "ApprovalRequest_applicationId_fkey" FOREIGN KEY ("applicationId") REFERENCES aether_test."Application"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: ApprovalRequest ApprovalRequest_userId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."ApprovalRequest"
    ADD CONSTRAINT "ApprovalRequest_userId_fkey" FOREIGN KEY ("userId") REFERENCES aether_test."User"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Contact Contact_userId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Contact"
    ADD CONSTRAINT "Contact_userId_fkey" FOREIGN KEY ("userId") REFERENCES aether_test."User"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: EmailThread EmailThread_applicationId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."EmailThread"
    ADD CONSTRAINT "EmailThread_applicationId_fkey" FOREIGN KEY ("applicationId") REFERENCES aether_test."Application"(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: EmailThread EmailThread_contactId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."EmailThread"
    ADD CONSTRAINT "EmailThread_contactId_fkey" FOREIGN KEY ("contactId") REFERENCES aether_test."Contact"(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: EmailThread EmailThread_userId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."EmailThread"
    ADD CONSTRAINT "EmailThread_userId_fkey" FOREIGN KEY ("userId") REFERENCES aether_test."User"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: JobEmbedding JobEmbedding_jobId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."JobEmbedding"
    ADD CONSTRAINT "JobEmbedding_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES aether_test."Job"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Job Job_userId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Job"
    ADD CONSTRAINT "Job_userId_fkey" FOREIGN KEY ("userId") REFERENCES aether_test."User"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: Resume Resume_parentId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Resume"
    ADD CONSTRAINT "Resume_parentId_fkey" FOREIGN KEY ("parentId") REFERENCES aether_test."Resume"(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: Resume Resume_sourceJobId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Resume"
    ADD CONSTRAINT "Resume_sourceJobId_fkey" FOREIGN KEY ("sourceJobId") REFERENCES aether_test."Job"(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: Resume Resume_userId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."Resume"
    ADD CONSTRAINT "Resume_userId_fkey" FOREIGN KEY ("userId") REFERENCES aether_test."User"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: StoryEntry StoryEntry_userId_fkey; Type: FK CONSTRAINT; Schema: aether_test; Owner: -
--

ALTER TABLE ONLY aether_test."StoryEntry"
    ADD CONSTRAINT "StoryEntry_userId_fkey" FOREIGN KEY ("userId") REFERENCES aether_test."User"(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


