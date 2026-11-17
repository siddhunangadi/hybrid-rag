# Kestrel Analytics: Customer Support & Service Level Agreement

**Document ID:** KA-SOP-2024-04V2  
**Effective Date:** October 1, 2024  
**Classification:** Internal / Confidential - Kestrel Analytics Operations  
**Owner:** Global Customer Success & Technical Support Directorate  

---

## 1. Purpose and Scope

This internal document outlines the operational procedures, service tiers, escalation workflows, and uptime commitments for Kestrel Analytics. Every member of the Support, Customer Success, Engineering, and Account Management teams must adhere to these guidelines when interacting with clients or managing platform reliability. 

As Kestrel Analytics continues to scale its data intelligence platform, maintaining clear, predictable, and enforceable service level agreements (SLAs) is paramount to retaining client trust. This document serves as the single source of truth regarding our support commitments, tier definitions, and remediation policies.

---

## 2. Support Architecture and Operating Principles

Kestrel Analytics provides data-driven insights and analytics infrastructure to a diverse client base, ranging from growing startups to Fortune 500 enterprises. To effectively allocate resources and meet varying client needs, our support model is structured around three distinct tiers: Basic, Pro, and Enterprise. 

Support availability is measured during standard business hours or extended windows depending on the tier purchased. Business hours are defined as Monday through Friday, 08:00 to 18:00 in the client's designated regional timezone (UTC-5 for the Americas, UTC+1 for EMEA, and UTC+8 for APAC), excluding official Kestrel Analytics corporate holidays.

### Incident Priority Definitions

Before evaluating tier-specific response times, support staff must correctly categorize incoming tickets based on operational impact:

*   **Priority 1 (P1 - Critical):** Complete system outage, inability to access the primary Kestrel Analytics dashboard, severe data corruption, or total failure of core data ingestion pipelines affecting multiple business functions with no immediate workaround.
*   **Priority 2 (P2 - High):** Partial service degradation, non-critical pipeline failures, or key reporting features malfunctioning where a restricted workaround is temporarily available.
*   **Priority 3 (P3 - Normal):** General user questions, feature requests, minor UI glitches, or non-urgent data export inquiries that do not disrupt core operational workflows.

---

## 3. Service Tier Matrix

All client subscriptions map directly to one of three service tiers. The matrix below dictates the operational boundaries, communication channels, response targets for P1 incidents, and uptime commitments associated with each tier.

| Service Tier | P1 First Response Time | Support Channels & Availability | Uptime SLA |
| :--- | :--- | :--- | :--- |
| **Basic** | Within 8 business hours | Email only | 99.5% |
| **Pro** | Within 2 hours | Phone support 24/5 | 99.9% |
| **Enterprise** | Within 30 minutes | 24/7 support, a named Technical Account Manager | 99.95% |

### Tier-Specific Operational Guidelines

#### Basic Tier
*   **Communication Channel:** Restricted exclusively to email support via `support@kestrel-analytics.internal` or the in-app ticketing widget. Phone and live chat requests cannot be serviced under this tier and will receive an automated redirect to the email intake portal.
*   **Response Commitment:** For P1 issues, the support desk guarantees a first response within 8 business hours. 
*   **Availability:** Standard business hours apply to all non-automated query handling.

#### Pro Tier
*   **Communication Channel:** Multi-channel access including dedicated ticketing and phone support available 24 hours a day, 5 days a week (Monday through Friday, spanning all global time zones).
*   **Response Commitment:** P1 issues are routed to senior tier-2 analysts with a mandatory first response within 2 hours of ticket generation.
*   **Escalation:** Pro tier clients benefit from proactive queue prioritization during peak market hours.

#### Enterprise Tier
*   **Communication Channel:** Comprehensive 24/7 support coverage spanning weekends and holidays, coupled with the assignment of a named Technical Account Manager (TAM) who acts as the single point of escalation for strategic guidance, architecture reviews, and critical incident management.
*   **Response Commitment:** High-priority P1 tickets trigger an immediate automated page to the on-call engineering squad, backed by a strict first response within 30 minutes, regardless of the time of day or day of the week.

---

## 4. Incident Management and Escalation Workflow

When a P1 incident is logged by a client, the Kestrel Analytics incident management protocol is automatically initiated. 

1.  **Ingestion and Triage:** The automated monitoring system or client submission creates a ticket. The triage bot evaluates the client's contract tier and stamps the appropriate SLA countdown timer.
2.  **Assignment:** Tickets are routed to the designated queue based on the tier matrix. For Enterprise clients, the named Technical Account Manager is simultaneously notified via internal paging systems (e.g., PagerDuty integration).
3.  **Investigation & Updates:** Engineers diagnose the root cause within the platform environment. Status updates must be communicated to the client within intervals appropriate to their tier until the incident is fully mitigated and resolved.
4.  **Post-Incident Review (PIR):** For any Enterprise-tier P1 incident resulting in extended service interruption, a formal PIR document must be compiled by the engineering lead and delivered to the client by their Technical Account Manager within 48 business hours of resolution.

---

## 5. System Availability and Uptime Measurement

Kestrel Analytics tracks platform availability continuously using redundant, third-party synthetic monitoring probes located across multiple global availability zones. 

### Uptime Calculation Methodology
Uptime percentage is calculated on a calendar-month basis. The calculation takes the total number of minutes in the given month, subtracts total downtime minutes resulting from outages or service degradations directly attributable to Kestrel Analytics infrastructure, and divides the result by the total minutes in the month. 

*Scheduled maintenance windows*—communicated to clients via email and the status page at least 72 hours in advance—are excluded from downtime calculations. Maintenance is preferentially scheduled during low-traffic windows (Saturday 01:00 to 05:00 UTC).

---

## 6. Service Credits and Remediation Policy

If Kestrel Analytics fails to meet the guaranteed monthly uptime SLA for a given subscription tier, the affected client is eligible to receive service credits applied directly to future billing cycles. Service credits do not constitute a cash refund.

### Claim Procedure and Limitations
To receive a service credit, the client must submit a formal written request via the support portal within 30 days following the end of the month in which the SLA was missed. The request must include the dates and times of the relevant downtime incidents. Finance and Support will cross-reference the claim against internal server telemetry logs. Upon validation, credits will be applied within two billing cycles.

### Credit Calculation Structure
Service credits are scaled proportionally to the severity and duration of the availability shortfall:

*   Service credits: 10% of the monthly fee for each 0.1% below the uptime SLA, capped at 30%.

#### Practical Application Example (Pro Tier - 99.9% SLA target):
*   If actual monthly uptime drops to 99.8%, the metric is 0.1% below the SLA threshold. The client receives a 10% service credit of their monthly subscription fee.
*   If actual monthly uptime drops to 99.7%, the metric is 0.2% below the SLA threshold. The client receives a 20% service credit.
*   If actual monthly uptime drops to 99.5% or lower, the metric is 0.4% (or more) below the SLA threshold. Due to protection limits, the payout is capped at 30% of the monthly fee.

Basic and Enterprise tiers utilize the exact same percentage scaling logic, measured strictly against their respective uptime baselines (99.5% and 99.95% respectively).

---

## 7. Review and Governance

This document is reviewed semi-annually by the VP of Engineering, Director of Customer Success, and Chief Revenue Officer to ensure alignment with market standards and internal technical capacity. Any proposed alterations to tier limits, support channels, or credit structures must be approved by executive leadership before dissemination to client-facing teams.

*End of Document. For questions concerning contractual interpretations, contact the Kestrel Analytics Legal and Compliance Department.*