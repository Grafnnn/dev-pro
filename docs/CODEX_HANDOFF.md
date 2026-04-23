# DEVLAND — Codex Handoff

## Product summary
DEVLAND is a B2B platform for development and redevelopment assets.

Core workflows already implemented:
- role-based auth with demo accounts
- marketplace and listing detail page
- shortlist and compare workspace
- NDA / access requests
- seller CRM listings table
- listing create/edit flow
- data room document management
- seller questions inbox with answers
- deals pipeline kanban
- admin CRUD for companies and users
- export JSON / reset demo data

## Technical notes
- frontend only, no backend
- all state is stored in localStorage
- React Router SPA
- suitable for migration to API / Supabase / custom backend

## Recommended next Codex tasks
1. move localStorage store to repository pattern
2. introduce TypeScript types for entities
3. connect auth, listings, companies, users, deals to real API
4. replace simulated documents with file upload storage
5. add drag-and-drop kanban
6. add permissions matrix per module and action
7. add charts and analytics pages
8. add unit and integration tests
