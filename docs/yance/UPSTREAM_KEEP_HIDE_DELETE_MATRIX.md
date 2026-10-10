# UPSTREAM_KEEP_HIDE_DELETE_MATRIX

| Upstream surface/capability | Action | Reason |
|---|---|---|
| Conversation/session history | KEEP | Mature message/conversation owner |
| Shared inbox/conversation services | KEEP | Mature routing and real-time primitives |
| Customer / People backend | KEEP | Canonical Yance Person owner |
| ChannelAccount / ChannelConversation abstractions | KEEP | Canonical channel/account routing owners |
| WhatsApp / Telegram / Messenger / Instagram / Email / SMS adapters | KEEP | Mature business transport primitives; personal semantics remain separate |
| Assignment / human handoff backend | KEEP | Reusable responder/handoff owner |
| AI agent framework | KEEP | Reused by Reply Brain/Girlfriend Brain adapters |
| Model provider plumbing | KEEP | Reused by Yance model controls |
| Workflow engine | KEEP | Mature execution owner |
| Knowledge base | KEEP | Mature knowledge owner |
| Tools / MCP | KEEP | Mature tool execution owner |
| Notification backend | KEEP | Mature notification primitive |
| Translation capability | KEEP | Existing upstream capability; project requires intact reuse |
| CRM primitives/integrations | KEEP | Useful backend primitive, presentation can be reduced |
| Media/file upload/send primitives | KEEP | Mature transport primitive |
| Ticket investigation backend | KEEP | Potential mature investigation/diagnostics owner |
| Analytics backend/events | KEEP | Useful health/attention signals |
| Human-agent seat/team administration UI | HIDE / DE-PRESENT | Enterprise support operations presentation is not a Yance product surface |
| Analytics dashboard UI | HIDE / DE-PRESENT | Yance Home/Relationship projections replace dashboard presentation |
| FAQ/help-center authoring UI | HIDE / DE-PRESENT | Not a primary private-Yance surface; backend knowledge remains |
| Ticketing workspace UI | HIDE / DE-PRESENT | Support-desk presentation not primary; backend investigator may be reused |
| Shopify/e-commerce-specific UI | HIDE / DE-PRESENT | Not part of private social Yance surface |
| Widget builder/branding UI | HIDE / DE-PRESENT | Support widget presentation is not final Yance UI |
| Enterprise subscription/pricing/signup UI | HIDE / DE-PRESENT | Private Yance has no SaaS subscription presentation requirement |
| Jira/help-center support presentation | HIDE / DE-PRESENT | Backend/tool integrations may still be reused |
| Any mature backend capability | DELETE = NO in foundation | Deletion deferred until reachability/dependency proof shows it is truly unused |
