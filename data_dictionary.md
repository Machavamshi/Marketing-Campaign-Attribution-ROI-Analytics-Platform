# Data dictionary

All dates use ISO-8601; event timestamps are UTC (`Z`). Baseline dates span 2026-01-01 through 2026-12-31; train is January–June, validation July–September, and test October–December. Currency amounts are decimal major units with two fractional digits. An empty CSV value is NULL. IDs are primary keys unless noted otherwise; generated IDs are immutable and deterministic for a given seed and scale.

| Entity / file | Field | Type | Req. | Allowed values / units | Uniqueness and validation |
|---|---|---:|:---:|---|---|
| Campaign / `campaigns.csv` | campaign_id | string | Yes | `CMP-2026-######` | PK |
| | name | string | Yes | Campaign label | Non-empty |
| | channel_id | string | Yes | Channel key | FK `channels`; exactly one channel per campaign |
| | audience_id | string | Yes | Audience key | FK `audiences` |
| | creative_id | string | Yes | Creative key | FK `creatives` |
| | start_date, end_date | date | Yes | ISO date | start <= end; within generated period |
| | budget_amount | decimal | Yes | Non-negative INR | >= 0 |
| | budget_currency | string | Yes | ISO-4217; baseline INR | Must match documented currency |
| | status | enum | Yes | active, completed | Date-derived lifecycle |
| CampaignEvent / `campaign_events.csv` | campaign_event_id | string | Yes | `CME-2026-######` | PK; append-only |
| | campaign_id | string | Yes | Campaign ID | FK |
| | event_type | enum | Yes | campaign_created, campaign_revised | Lifecycle/audit event |
| | occurred_at | timestamp | Yes | UTC | Event ordering |
| | details_json | JSON string | Yes | Campaign snapshot or before/after edit | Valid JSON; never overwrite prior event |
| Channel / `channels.csv` | channel_id | string | Yes | `CH-###` | PK |
| | name | string | Yes | Channel name | Non-empty |
| | channel_type | enum | Yes | digital, offline | Enum validation |
| Creative / `creatives.csv` | creative_id | string | Yes | `CRE-####` | PK |
| | name | string | Yes | Creative name | Non-empty |
| | format | enum | Yes | email, video, banner, webinar, direct_mail | Enum validation |
| | status | enum | Yes | active | Lifecycle state |
| Audience / `audiences.csv` | audience_id | string | Yes | `AUD-###` | PK |
| | name | string | Yes | Audience name | Non-empty |
| | segment | enum | Yes | SMB, Enterprise, Mid-market, New prospects | Enum validation |
| Contact / `contacts.csv` | contact_id | string | Yes | `CON-#######` | PK |
| | created_date | date | Yes | ISO date | Not after generation end |
| | region | enum | Yes | NA, EMEA, APAC, LATAM | Enum validation |
| | consent_status | enum | Yes | granted, withdrawn | Enum validation |
| | lifecycle_state | enum | Yes | prospect, customer | Enum validation |
| ContactAudience / `contact_audiences.csv` | contact_audience_id | string | Yes | `CA-#######` | PK |
| | contact_id, audience_id | string | Yes | Parent IDs | FK to contacts and audiences; bridge enables N:M |
| | valid_from | date | Yes | ISO date | Effective start |
| | valid_to | date | No | ISO date or NULL | Must be >= valid_from when present |
| Touchpoint / `touchpoints.csv` | touchpoint_id | string | Yes | `TOUCH-<contact-id>-######` | PK; per-contact sequence |
| | contact_id, campaign_id, channel_id, creative_id | string | Yes | Parent IDs | FKs; one contact/campaign/channel/creative per event |
| | occurred_at | timestamp | Yes | UTC | Within generation interval except the labelled post-conversion case, which remains within the interval |
| | touch_type | enum | Yes | online, offline | Must agree with channel class |
| | source | enum | Yes | campaign, field_sales, direct_mail | Provenance label |
| WebSession / `web_sessions.csv` | session_id | string | Yes | `SES-2026-######` | PK |
| | contact_id | string | No | Contact ID | Optional FK; NULL for anonymous session |
| | touchpoint_id | string | No | Touchpoint ID | Optional FK; identity evidence when present |
| | lead_id, opportunity_id | string | No | Lead/opportunity IDs | Optional FKs |
| | started_at | timestamp | Yes | UTC | Not before referenced touchpoint |
| | pages_viewed | integer | Yes | Count >= 0 | Non-negative |
| | session_type | enum | Yes | identified, anonymous | Anonymous does not imply a proven person |
| Lead / `leads.csv` | lead_id | string | Yes | `LEAD-2026-######` | PK |
| | contact_id | string | Yes | Contact ID | FK |
| | source_session_id | string | Yes | Session ID | Unique FK; one source session per lead |
| | created_at | timestamp | Yes | UTC | Not before source session |
| | lead_score | integer | Yes | 0–100 | Derived from eligible touches, unique campaigns, and session pages |
| | status | enum | Yes | new, qualified, converted, disqualified | Derived from score and opportunity outcome |
| LeadEvent / `lead_events.csv` | lead_event_id | string | Yes | `LE-#########-###` | PK; immutable event record |
| | lead_id | string | Yes | Lead ID | FK |
| | from_status | enum | No | NULL or prior lead state | NULL only for initial event |
| | to_status | enum | Yes | Lead state | Valid lifecycle transition |
| | changed_at | timestamp | Yes | UTC | Monotonic per lead |
| | reason | string | Yes | Rule explanation | Non-empty |
| Opportunity / `opportunities.csv` | opportunity_id | string | Yes | `OPP-2026-######` | PK |
| | lead_id | string | Yes | Lead ID | Unique FK; one opportunity per generated lead |
| | contact_id | string | Yes | Contact ID | FK; agrees with lead |
| | created_at, closed_at | timestamp | Yes / No | UTC | closed_at required for terminal status |
| | status | enum | Yes | closed_won, closed_lost, qualified | Score-derived; qualified is open |
| | estimated_amount | decimal | Yes | Non-negative INR | Revenue basis for won order |
| | currency | string | Yes | ISO-4217 | Baseline INR |
| OpportunityEvent / `opportunity_events.csv` | opportunity_event_id | string | Yes | `OE-######-###` | PK; immutable event record |
| | opportunity_id | string | Yes | Opportunity ID | FK |
| | from_status | enum | No | NULL or prior state | NULL only for initial event |
| | to_status | enum | Yes | new, closed_won, closed_lost, qualified | Lifecycle transition |
| | changed_at | timestamp | Yes | UTC | Monotonic per opportunity |
| | reason | string | Yes | Rule explanation | Non-empty |
| Order / `orders.csv` | order_id | string | Yes | `ORD-2026-######` | PK |
| | opportunity_id | string | Yes | Opportunity ID | FK; repeat opportunity is detected as duplicate revenue |
| | ordered_at | timestamp | Yes | UTC | Must match won conversion |
| | revenue_amount | decimal | Yes | Non-negative currency units | Canonical value equals opportunity amount |
| | currency | string | Yes | ISO-4217 | Must match opportunity for baseline |
| | status | enum | Yes | closed | Closed revenue only |
| CostRecord / `cost_records.csv` | cost_record_id | string | Yes | `COST-######` | PK |
| | campaign_id | string | Yes | Campaign ID | FK |
| | incurred_date | date | Yes | ISO date | Within campaign dates |
| | amount | decimal | Yes | Non-negative currency units | >= 0 |
| | currency | string | Yes | ISO-4217 | ROI only calculated in base currency INR |
| | cost_type | enum | Yes | campaign_spend | Enum validation |
| AttributionResult / `attribution_results.csv` | attribution_result_id | string | Yes | `ATTR-#########` | PK |
| | opportunity_id, campaign_id | string | Yes | Parent IDs | FKs; unique with model per opportunity/campaign allocation |
| | model | enum | Yes | first_touch, last_touch, linear | Explicit rule |
| | credit_weight | decimal | Yes | 0–1 | Per opportunity/model sums to 1 |
| | attributed_revenue | decimal | Yes | INR | Rounded; sums to canonical revenue per model |
| | conversion_date | date | Yes | ISO date | Same as won opportunity close date |
| | evaluation_period | enum | Yes | train, validation, test | Chronological split |
| | rule_version | string | Yes | `attribution-v1` | Versioned |
| CampaignMetric / `campaign_metrics.csv` | campaign_metric_id | string | Yes | `CM-#########` | PK |
| | campaign_id | string | Yes | Campaign ID | FK |
| | model | enum | Yes | first_touch, last_touch, linear | Attribution method |
| | evaluation_period | enum | Yes | train, validation, test | Chronological split |
| | attributed_revenue | decimal | Yes | INR | Sum of attribution results |
| | attributed_conversions | decimal | Yes | Fractional credits | Sum of credit weights |
| | spend_base_currency | decimal | No | INR | NULL when missing or currency-mismatched |
| | cost_status | enum | Yes | available, missing, currency_mismatch | Exception visibility |
| | roi | decimal | No | Ratio, not percent | NULL without valid spend; otherwise (revenue - spend) / spend |

## Cardinality and optionality

* Channel, Audience, and Creative each have 1:N Campaigns; each Campaign has exactly one of each. Campaign-to-Contact is N:M through Touchpoint. Campaign-to-Audience is N:1 (each campaign has one audience; an audience can serve many campaigns); Contact-to-Audience is N:M through the `contact_audiences` bridge.
* Contact 1:N Touchpoint, WebSession, Lead, and Opportunity. Contact-Audience is N:M with effective dates. A Contact may have zero or many sessions and touches.
* A Touchpoint can be referenced by 0:N WebSessions; each session's touchpoint reference is optional. Contact and touchpoint identity on a session are optional, while lead and opportunity links are also optional.
* Lead 1:1 source WebSession and 0:1 Opportunity in this dataset; a lead has 1:N LeadEvents. Opportunity 1:N OpportunityEvents and 0:1 canonical Order. Duplicate orders are an explicitly labelled exception.
* Campaign 0:N CostRecord, AttributionResult, and CampaignMetric. Missing cost is permitted and surfaced, not silently imputed. An attribution result always references a valid opportunity and campaign.
* Campaign 1:N CampaignEvent, with append-only creation/revision snapshots. Channel 1:N Campaign; Contact 1:N Touchpoint, WebSession, and Lead; Opportunity 0:1 canonical Order under normal conditions.
* Campaigns have start/end dates; contact-audience memberships have valid-from/valid-to intervals. Event, touch, session, lead, opportunity, order, and cost timestamps preserve their own histories rather than overwriting transitions.
