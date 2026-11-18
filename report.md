# Smart Campus Facility Booking and Maintenance Platform

**Software Engineering Assignment 3 | CSA10**  
**Student Name:** MOHAMED HAARUN M.H  
**Register Number:** 192524430  
**Programme and Section:** ______________________  
**Submission Date:** ____________________________

## Problem Statement

The university needs one dependable workflow for facility requests and maintenance work. A booking, sensor alert, assignment, inspection, approval and closure should be visible in one application with a lasting record. This release connects a browser interface, an API and a shared PostgreSQL database. It applies database rules to overlapping reservations, server-side role checks to protected operations, request keys to booking retries, version checks to ticket changes and audit events to consequential actions. The issue-tracker link is explicitly simulated. The implementation is a working source package; live deployment evidence must be recorded in the student's own Docker environment because the Docker engine was unavailable during preparation.

## Task 1 Define Scope and Select the Technology Stack

### Users and first-release workflows

The administrator configures the service and can manage operations. A facility manager reviews reservations, assigns technicians and closes verified tickets. A technician records inspection and repair progress. A department approver records a justified approval or rejection for a restricted booking. Faculty members and students request facilities. Sensor events enter through a controlled manager-facing form, receive transparent rule-based category and priority suggestions, and become tickets. A manager or technician can create a locally stored developer issue link.

### User stories and measurable acceptance criteria

| User story | Acceptance criterion |
|---|---|
| As a student, I want to see facilities and request a time slot so I can plan an activity. | The catalogue lists facility names, types and restriction status; a well-formed request is stored and appears on refresh. |
| As a user, I want a duplicate booking submission to return the first result. | Reusing the same `Idempotency-Key` returns the same booking ID and creates no second booking row. |
| As a facility manager, I want to receive a ticket when a reading reaches its threshold. | A reading below threshold creates no ticket; a reading at or above threshold creates one ticket with a category and priority explanation. |
| As a manager, I want to assign a technician and follow the ticket lifecycle. | Invalid transitions are rejected; valid changes increment the ticket version and add an audit event. |
| As a technician, I want to record inspection and repair notes. | Notes persist after refresh and each update checks the submitted version. |
| As a department approver, I want to decide a restricted booking with a reason. | Only an approver or administrator can decide; a decision requires a non-empty reason and is recorded. |
| As a manager, I want to avoid conflicting facility reservations. | The database rejects overlapping active intervals for the same facility with a conflict response. |
| As an engineer, I want a traceable issue link. | The application stores one stable local link per ticket and discloses that it is simulated. |

### Scope boundaries and planning assumptions

The one-week release covers three synthetic facilities and six demo identities, one campus, browser-based booking and sensor intake, maintenance triage, approval, audit history and a local issue-link simulation. It does not provide real campus SSO, email or calendar integration, a trained machine-learning model, live sensor ingestion, payment, mobile-native clients, real external issue-tracker calls, multi-campus tenancy or production security hardening.

For planning, the initial workload assumption is 60 active users at peak and about 10 booking submissions per minute, with requests normally completing in under two seconds. A critical ticket has a 15-minute response and four-hour resolution target; high priority has a 60-minute response and eight-hour resolution target; medium is four and 24 hours; low is eight and 72 hours. These are example service policies, not measured performance. First-release acceptance is zero accepted overlaps among active bookings, one ticket per unique sensor event, all unauthorized state changes rejected, every accepted state change audited, and a clean deployment reproducing the same catalogue and workflows. The expanded 300-user assumption is a planning target only; no 300-user capacity claim is made.

### Technology comparison and choice

| Option | Advantages | Trade-offs for this release |
|---|---|---|
| Vue + Django REST Framework + PostgreSQL | Mature admin and ORM, strong ecosystem, clear frontend/backend boundary. | More setup and separate frontend build/deployment steps for a one-week individual project. |
| HTML/JavaScript + Flask + PostgreSQL | Small, direct API and interface integration; PostgreSQL supports shared durable state and exclusion constraints; easy to containerize. | Requires explicit validation and API organization; the simple UI is not a large-app component architecture. |
| React + Node.js + MongoDB | Familiar JSON-oriented application model and broad ecosystem. | A relational reservation conflict and audit model needs additional discipline; no advantage for this relational workflow. |

I selected HTML with JavaScript for the compact browser client, Flask for the REST-style API, PostgreSQL for durable relational records and concurrency controls, Git for history and review, and Docker Compose with Nginx for repeatable local deployment. PostgreSQL's exclusion constraint directly represents the no-overlap rule. Compose describes the database, API and proxy together. Git branches, commits, tags and pull requests support traceability and recovery. These choices satisfy CO3 through full-stack integration, version control and containerization.

## Task 2 Create the Integrated Application Design

### Component view

```text
Browser UI (HTML / JavaScript)
           | HTTP / JSON
           v
Nginx reverse proxy :8080
           | campus_api upstream
           v
Flask API instances (one or two)
           | PostgreSQL protocol
           v
Shared PostgreSQL database + named persistent volume
  users | facilities | bookings | tickets | alerts | SLA
  approvals | integration_links | audit_events
```

The browser handles input feedback and rendering. Flask parses and validates requests, checks the actor role, enforces transitions and writes audit events. PostgreSQL owns durable records, unique keys, interval exclusion and transactional updates. Nginx provides one browser-facing endpoint. A two-instance deployment shares the same database; no booking or ticket state is kept only in process memory.

### Data model

`users` stores role-bearing demo identities. `facilities` stores facility type and restriction. `bookings` references one facility and requester and stores interval, status, version and optional unique request key. `sensor_alerts` stores a unique event key, measurement and threshold and references its ticket. `tickets` stores its source key, facility or booking link, category, priority, status, assignee, notes and version. `sla_policies` maps priority to response and resolution targets. `approvals` records the approver, decision and reason for exactly one booking or ticket. `integration_links` stores a local simulated external key and mode. `audit_events` records actor, object, action, detail and time.

### Principal API contracts

| Method and path | Operation | Permission / conflict behavior |
|---|---|---|
| `GET /api/dashboard` | Read facilities, bookings, tickets, SLA targets and demo users. | Any known demo user. |
| `POST /api/bookings` | JSON facility, ISO start/end and purpose; requires `Idempotency-Key`. | Student, faculty, manager or admin. 400 invalid input; 409 overlap. Same key replays the original result. |
| `POST /api/sensors` | JSON event key, facility, reading, threshold and message. | Manager/admin. Below threshold returns 422; duplicate event reuses ticket. |
| `PATCH /api/tickets/{id}` | JSON expected `version`, next `status`, optional notes and assignee. | Technician/manager/admin. 409 stale version or invalid transition; manager/admin required to assign or close. |
| `POST /api/bookings/{id}/approval` | JSON decision and required justification. | Approver/admin only; overlap on approval returns 409. |
| `PATCH /api/bookings/{id}` | JSON expected version and next status. | Manager/admin only; invalid or stale transitions return 409. |
| `POST /api/tickets/{id}/issue-link` | Creates/reuses a local simulated developer link. | Technician/manager/admin; response discloses simulation. |

### State and consistency rules

Booking progression is `requested -> approved -> confirmed -> in_use -> completed`; rejection or allowed cancellation moves the booking to `cancelled`. Approval decisions are recorded separately with a justification. Ticket progression is `intake -> assigned -> inspection -> pending_work -> inspection` or `resolved -> closed`. A technician can inspect and resolve but only an administrator or manager can close. A conditional update compares the caller's version with the stored version; a stale writer receives 409 and must reload.

PostgreSQL's GiST exclusion constraint prevents overlapping half-open time ranges `[start,end)` for the same facility when bookings are approved, confirmed or in use. Thus adjacent reservations are allowed and two requested reservations can wait for approval, but only a non-conflicting request can become active. Unique booking request keys make a timed-out booking retry return the existing record. Unique sensor event keys and ticket source keys prevent duplicate ticket effects. Row locks and version checks coordinate competing ticket updates. Audit events are inserted in the same database transaction as state changes so accepted transitions and their history commit together.

The interface gives immediate input feedback, the API repeats every critical permission and transition check, and the database enforces durable uniqueness, valid references, allowed status values and interval exclusion. Client validation improves usability but is never treated as authorization.

## Task 3 Develop the Working Full-Stack Application

The included source provides a facility catalogue, booking form, current bookings, maintenance queue, SLA targets, sensor threshold intake, deterministic category/priority suggestions, ticket assignment and lifecycle updates, restricted booking approval, audit persistence and simulated issue linking. Flask serves the interface and JSON endpoints; the UI refreshes from the API and the database persists records across API process restarts. User-facing rejected operations show the server's conflict or permission message.

The triage logic uses message keywords: temperature, humidity or air maps to environment; power, voltage or electrical maps to electrical; other text maps to general. The priority is critical at or above 1.5 times the submitted threshold and high otherwise. This is explainable deterministic logic, not trained ML. The linked issue operation is local-only. The database seeds synthetic records on first volume initialization.

The complete demonstration journey is: choose a facility, submit a threshold event, inspect the explanation, assign a technician, advance through inspection and resolution with notes, create the disclosed local issue link, and close as the manager. A restricted booking can separately be requested by a student/faculty member and approved or rejected by the approver. The implementation source is included under `app/` with `schema.sql`, `Dockerfile`, `compose.yaml` and `nginx.conf`.

**Evidence status:** Python syntax compilation succeeded and `docker compose config` parsed the three-service deployment. An actual UI journey and database-persistence check could not run because the Docker Desktop Linux engine was unavailable (the engine named pipe did not exist). No screenshot or runtime result is represented as actual evidence. After starting Docker, follow the README and capture screenshots of the dashboard, approved booking, ticket resolution/closure and container list.

## Task 4 Establish and Demonstrate a Version-Control Workflow

The proposed repository structure separates the API/schema (`app/`), proxy configuration, Compose deployment, report and operating instructions. `.gitignore` excludes `.env`, Python bytecode, logs and generated caches. The committed `.env.example` contains only a replaceable local demo secret; an actual `.env` must stay untracked.

For an individual assignment, separate contributions must be simulated transparently; a self-review is not represented as another person's review. A suitable workflow is:

```bash
git init -b main
git add .
git commit -m "Build campus booking and maintenance release"
git switch -c feature/booking-controls
# make and commit the booking schema and API change
git switch main
git switch -c feature/maintenance-triage
# make and commit the sensor and ticket workflow change
git push -u origin feature/booking-controls
git push -u origin feature/maintenance-triage
```

I created a local Git repository with two feature branches, distinct commits, and a deliberately conflicting edit to the same README heading. I merged the booking branch, resolved the maintenance branch conflict on `main`, and tagged the integrated state `v1.0.0`. The commits are labeled as preparation/simulation; they are not presented as independent student contributors. No GitHub remote, pull request or external review was available in this workspace, so the repository still needs to be pushed to the student's account and the actual review record captured. If no classmate is available, document the PR as self-review rather than claiming another person's review.

This workflow makes interface, API and schema changes traceable to commits, gives integration a deliberate checkpoint and allows return to the tagged stable state if a change fails.

## Task 5 Create and Validate a Reproducible Container Deployment

The Compose definition builds the API image, runs PostgreSQL 16 with a named `pgdata` volume and initializes the schema on first volume creation, and runs Nginx as the public entry point on port 8080. Internal services communicate on Compose's private network; only the proxy publishes a host port. The API waits for PostgreSQL health and retries initial connections. Use a local `.env` file for the PostgreSQL password, which is excluded from Git.

From the project folder, copy `.env.example` to `.env`, replace the sample password, then run `docker compose up --build -d`. Open `http://localhost:8080`. For shutdown use `docker compose down`; the named database volume remains. `docker compose down -v` is destructive to demo data and is used only when intentionally testing a clean deployment. To scale the API, use `docker compose up -d --scale api=2`. To verify persistent state, create a booking and ticket, restart an API container, reload the page and confirm both remain. To verify a clean deployment, intentionally remove the volume, start Compose again and repeat the booking and sensor workflow.

This small multi-container design is appropriate to a one-week release. Compose provides reproducible local service wiring; Kubernetes would add operational overhead without evidence that this small demonstration needs orchestration. The two API containers are stateless with respect to business records, while PostgreSQL remains the shared state store. Credentials and image versions require stronger secret and patch management before a real deployment.

**Deployment evidence status:** Compose syntax was validated, but image build/startup, restart persistence and clean deployment could not be executed because Docker Desktop's Linux engine was not available. Therefore no deployment screenshot or persistence claim is included.

## Task 6 Adapt the Application for Concurrent Access and Deployment Changes

### A. Diagnose the impact

Growth from 60 to 300 planned peak users increases contention on shared facilities and tickets. A process-local overlap check would allow two API instances to accept the same interval. A check-then-insert sensor handler can duplicate work after a timeout. An unconditional ticket update can overwrite a technician's newer inspection. Local in-memory state would disappear on restart and differ between replicas. The design therefore places overlap and uniqueness rules in PostgreSQL, stores all operating state in the shared database and makes each update conditional on its version.

### B. Adaptation

The PostgreSQL exclusion constraint compares `facility_id` and overlapping timestamp ranges for active statuses. Booking requests require a stable unique `Idempotency-Key`; same-key retries return the original row. Sensor event and ticket source keys are unique. Ticket updates lock the current row and compare the submitted version before committing a transition and audit event. Compose can run two API containers behind Nginx while both use the same PostgreSQL service and volume. If one API instance restarts, the proxy and remaining instance continue to reach the shared records.

These are database-backed controls, not a claim that a particular throughput target is met. For the assignment's conflicting technician case, submit two updates with the same version and incompatible statuses: the first valid transition increments the version; the later stale transition receives 409 and cannot overwrite it. For competing lab reservations, create overlapping requests and approve them in succession; the database admits at most one active reservation.

### C. Validation and limitations

The intended bounded experiment is 20 concurrent clients for 60 seconds against two API instances, with a fixed synthetic set of 10 facilities and a mix of dashboard reads, bookings and ticket reads. Record request count, success/conflict/error counts, p50/p95 latency and duplicate-row counts. This is a modest repeatable experiment, not proof of 300 simultaneous users. For restart validation, create records, stop one API container while the other remains, confirm `/health` and reload records, then restart the stopped container and confirm audit history remains.

The experiment could not run in the supplied environment because the Docker engine was unavailable. Accordingly, there are no fabricated latency numbers, concurrency screenshots or restart claims. The code and deployment configuration implement the controls, and the README gives repeatable manual checks. The reservation exclusion constraint and version lock protect correctness but serialize some conflicting writes; PostgreSQL remains a single database service and a scaling or failover plan would be needed for campus-wide production. Identity is a demo selector, integration is local simulation, and the 300-user workload needs measurement on suitable hardware.

## Task 7 Individual Technical Reflection

The most consequential integration decision was to keep the reservation and ticket rules in PostgreSQL-backed API operations instead of spreading them across the browser and separate components. The overlap exclusion constraint is shared by every API instance, and version checks make competing technician updates visible rather than silently replacing one another. Designing around the shared database also makes a backend restart less significant to record persistence.

The main operational limitation surfaced while preparing the deployment evidence: the project files and Compose configuration are valid, but this machine did not have an available Docker engine. That prevented me from honestly claiming a clean deployment, a restart check or a measured load result. The next implementation step is to run the documented checks with Docker enabled and attach real screenshots and measurements.

Git provides a traceable place for each change and recovery point; container definitions capture service wiring and startup expectations. Before wider deployment, I would replace the user selector with campus SSO and enforce authorization from verified identity claims, add automated API/database tests and CI, pin and scan images, add TLS and secret management, instrument real SLA elapsed times, and integrate a real issue tracker with safe retry handling. The current release is a bounded educational prototype, not a production campus service.

## Source and execution checklist

The folder includes the working source, schema, image build file, Compose configuration, Nginx proxy configuration, environment example, ignore file and this report. Before submission, add student details, push the repository to GitHub, complete the actual branch/review/merge/tag evidence, start Docker, run the restart and bounded-load checks, and add screenshots with captions. The absence of a live Docker run is stated explicitly so the evidence can be completed honestly.
