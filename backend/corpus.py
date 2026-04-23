"""Synthetic email corpus for the privacy-detector PoC.

Each email mirrors a realistic business scenario. The mix is intentional:
- Internal-to-internal chatter (mostly clean)
- Outbound to clients/vendors (some sensitive, some routine)
- Inbound from external senders (some contain resumes/PII, some phishing, some benign)
- A handful with clearly leaky content (SSN, bank accounts, API keys, etc.)

All names, domains, numbers, and addresses are fictitious.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Direction = Literal["inbound", "outbound", "internal"]


@dataclass
class Email:
    id: str
    direction: Direction
    sender: str
    recipients: list[str]
    subject: str
    body: str
    timestamp: str  # ISO 8601

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "direction": self.direction,
            "sender": self.sender,
            "recipients": self.recipients,
            "subject": self.subject,
            "body": self.body,
            "timestamp": self.timestamp,
        }


INTERNAL_DOMAINS = ["northwind-corp.com", "northwind.io"]

EMPLOYEES = [
    {"name": "Elena Martinez", "email": "elena.martinez@northwind-corp.com", "role": "CFO"},
    {"name": "Marcus Chen", "email": "marcus.chen@northwind-corp.com", "role": "Engineering Lead"},
    {"name": "Priya Kapoor", "email": "priya.kapoor@northwind-corp.com", "role": "HR Director"},
    {"name": "Jonas Weber", "email": "jonas.weber@northwind-corp.com", "role": "Sales Manager"},
    {"name": "Sofia Rossi", "email": "sofia.rossi@northwind-corp.com", "role": "Customer Success"},
    {"name": "Daniel Park", "email": "daniel.park@northwind.io", "role": "Software Engineer"},
    {"name": "Aisha Khan", "email": "aisha.khan@northwind-corp.com", "role": "Legal Counsel"},
    {"name": "Tomás Silva", "email": "tomas.silva@northwind-corp.com", "role": "IT Operations"},
]


def _emp(name: str) -> str:
    for e in EMPLOYEES:
        if e["name"] == name:
            return e["email"]
    raise KeyError(name)


EMAILS: list[Email] = [
    Email(
        id="e01",
        direction="outbound",
        sender=_emp("Elena Martinez"),
        recipients=["accounts@vendor-systems.com"],
        subject="Wire transfer details for Q2 licensing invoice",
        body=(
            "Hi Raj,\n\n"
            "Please find our banking coordinates for the Q2 invoice settlement:\n\n"
            "Account holder: Northwind Corp\n"
            "Bank: First Federal Trust\n"
            "IBAN: DE89370400440532013000\n"
            "SWIFT: COBADEFFXXX\n"
            "Routing: 026009593\n\n"
            "Kindly confirm receipt once the transfer is scheduled for 2026-04-28.\n\n"
            "Regards,\n"
            "Elena Martinez\n"
            "CFO, Northwind Corp\n"
            "+1 (415) 555-0137"
        ),
        timestamp="2026-04-22T09:14:00Z",
    ),
    Email(
        id="e02",
        direction="inbound",
        sender="careers-inbox@gmail.com",
        recipients=[_emp("Priya Kapoor")],
        subject="Application — Senior Backend Engineer role",
        body=(
            "Dear Hiring Team,\n\n"
            "I am Akira Tanaka and I'd like to apply for the Senior Backend Engineer position.\n\n"
            "Contact details:\n"
            "Phone: +81 90 1234 5678\n"
            "Email: akira.tanaka@gmail.com\n"
            "Address: 4-12-3 Roppongi, Minato, Tokyo\n"
            "DOB: 1989-07-14\n"
            "SSN (US tax ID): 412-88-3921\n\n"
            "Resume attached. Looking forward to hearing from you.\n\n"
            "Best,\n"
            "Akira Tanaka"
        ),
        timestamp="2026-04-22T10:02:00Z",
    ),
    Email(
        id="e03",
        direction="internal",
        sender=_emp("Marcus Chen"),
        recipients=[_emp("Daniel Park")],
        subject="Standup notes — platform squad",
        body=(
            "Hey Daniel,\n\n"
            "Quick recap from today's standup:\n"
            "- Ingestion pipeline throughput is back to baseline after the index rebuild.\n"
            "- We'll ship the retry-backoff change behind a feature flag Thursday.\n"
            "- I'll pair with Sam tomorrow afternoon on the metrics exporter.\n\n"
            "Cheers,\n"
            "Marcus"
        ),
        timestamp="2026-04-22T11:30:00Z",
    ),
    Email(
        id="e04",
        direction="outbound",
        sender=_emp("Daniel Park"),
        recipients=["devops@cloud-partner.io"],
        subject="Urgent: staging access for integration",
        body=(
            "Hi team,\n\n"
            "Here's a short-lived token to reach our staging environment. Please rotate after "
            "you finish the hook-up:\n\n"
            "API_KEY=sk-proj-9F2kLmQx7RvP4nT6yE1wZcH8bA3jDuXs\n"
            "BASE_URL=https://staging-api.northwind.io\n\n"
            "Happy to jump on a call if you hit CORS issues.\n\n"
            "Daniel"
        ),
        timestamp="2026-04-22T12:04:00Z",
    ),
    Email(
        id="e05",
        direction="inbound",
        sender="newsletter@industry-digest.com",
        recipients=[_emp("Jonas Weber")],
        subject="Weekly SaaS market pulse — April 22",
        body=(
            "This week in SaaS:\n"
            "- Three mid-market acquisitions in the data pipeline space.\n"
            "- Seed funding for two vertical-AI startups.\n"
            "- A thoughtful essay on retention math at https://industry-digest.com/issue-84.\n\n"
            "Unsubscribe: https://industry-digest.com/u/abc123"
        ),
        timestamp="2026-04-22T06:00:00Z",
    ),
    Email(
        id="e06",
        direction="outbound",
        sender=_emp("Sofia Rossi"),
        recipients=["procurement@globex-retail.com"],
        subject="Re: shipping confirmation for order #447213",
        body=(
            "Hi Laura,\n\n"
            "Confirming the delivery window for your order.\n\n"
            "Ship-to: Laura Jennings, 221B Baker Street, London NW1 6XE, United Kingdom\n"
            "Mobile: +44 20 7946 0958\n"
            "ETA: April 29, 2026\n\n"
            "Let me know if we need a different contact at the receiving dock.\n\n"
            "Sofia Rossi\n"
            "Northwind Customer Success"
        ),
        timestamp="2026-04-21T16:45:00Z",
    ),
    Email(
        id="e07",
        direction="inbound",
        sender="security-alerts@it-monitor.com",
        recipients=[_emp("Tomás Silva")],
        subject="Suspicious login activity for tomas.silva@northwind-corp.com",
        body=(
            "Hello,\n\n"
            "We observed a sign-in attempt for tomas.silva@northwind-corp.com from an "
            "unrecognized IP in Bucharest, Romania on 2026-04-22 at 03:11 UTC.\n\n"
            "If this was not you, please reset your password immediately at "
            "https://it-monitor.com/account/reset?u=tomas.silva\n\n"
            "IT Monitor Security"
        ),
        timestamp="2026-04-22T03:15:00Z",
    ),
    Email(
        id="e08",
        direction="internal",
        sender=_emp("Priya Kapoor"),
        recipients=[_emp("Elena Martinez")],
        subject="Offer letter — Senior Platform Engineer",
        body=(
            "Elena,\n\n"
            "Sending the final offer package for our Senior Platform Engineer candidate.\n\n"
            "Candidate: Liam O'Sullivan\n"
            "Home address: 18 Grafton Terrace, Dublin D02 XY45, Ireland\n"
            "Personal phone: +353 86 555 0144\n"
            "Start date: 2026-05-18\n"
            "Base: €128,000 + equity per the comp band.\n\n"
            "Let me know if you want to adjust anything before I send the signed PDF.\n\n"
            "Priya"
        ),
        timestamp="2026-04-21T14:20:00Z",
    ),
    Email(
        id="e09",
        direction="outbound",
        sender=_emp("Jonas Weber"),
        recipients=["chen.wei@harbor-logistics.co"],
        subject="Follow-up: pilot pricing proposal",
        body=(
            "Hi Wei,\n\n"
            "Thanks for the kickoff call yesterday. Attaching the pilot pricing sheet. "
            "Our standard discount at your volume is 12% for a one-year commit; happy to "
            "walk you through the math when you've had a moment to review.\n\n"
            "Best,\n"
            "Jonas"
        ),
        timestamp="2026-04-22T08:55:00Z",
    ),
    Email(
        id="e10",
        direction="inbound",
        sender="kate.dunn@lawfirm-rosenberg.com",
        recipients=[_emp("Aisha Khan")],
        subject="Settlement draft — Matter N-2204",
        body=(
            "Counsel,\n\n"
            "Attached is the draft settlement agreement for Matter N-2204.\n\n"
            "Key terms:\n"
            "- Settlement amount: $2,450,000 to be wired on or before June 15, 2026.\n"
            "- Counterparty bank details: Account 000123456789, Routing 121000248.\n"
            "- Counterparty signatory: Robert Fenwick, DOB 1968-03-22.\n\n"
            "Please redline by Friday.\n\n"
            "Kate Dunn\n"
            "Rosenberg & Partners LLP\n"
            "+1 (212) 555-0199"
        ),
        timestamp="2026-04-21T19:07:00Z",
    ),
    Email(
        id="e11",
        direction="internal",
        sender=_emp("Tomás Silva"),
        recipients=[_emp("Marcus Chen"), _emp("Daniel Park")],
        subject="Planned maintenance — Thursday 02:00 UTC",
        body=(
            "Heads up — we'll be rolling the kernel update on the build fleet Thursday at 02:00 "
            "UTC. Expect ~15 minutes of CI queue pause. No action needed from your side."
        ),
        timestamp="2026-04-22T07:41:00Z",
    ),
    Email(
        id="e12",
        direction="outbound",
        sender=_emp("Elena Martinez"),
        recipients=["audit@grant-thornton-assoc.com"],
        subject="Requested documents for FY25 audit",
        body=(
            "Hello James,\n\n"
            "Per your request, here are the owner references for the three accounts under review:\n\n"
            "1. Operating account — 4532 8812 6104 9207, signatory Elena Martinez.\n"
            "2. Payroll account — 5500 2341 7788 0031, signatory Priya Kapoor.\n"
            "3. Reserve account — 3782 822463 10005, signatory Jonas Weber.\n\n"
            "I can walk you through the reconciliation on a call Wednesday afternoon.\n\n"
            "Regards,\n"
            "Elena"
        ),
        timestamp="2026-04-20T11:22:00Z",
    ),
    Email(
        id="e13",
        direction="inbound",
        sender="orders-noreply@office-supplies-direct.com",
        recipients=[_emp("Tomás Silva")],
        subject="Your order has shipped — #NW-00881",
        body=(
            "Your order has shipped and will arrive by April 25, 2026.\n"
            "Track it at https://office-supplies-direct.com/track/NW-00881.\n\n"
            "Thanks for shopping with us!"
        ),
        timestamp="2026-04-22T05:30:00Z",
    ),
    Email(
        id="e14",
        direction="outbound",
        sender=_emp("Marcus Chen"),
        recipients=["oncall-external@partner-observability.com"],
        subject="Re: incident 7821 — follow-up context",
        body=(
            "Hi team,\n\n"
            "Thanks for the quick turnaround on incident 7821. For your follow-up investigation, "
            "the impacted tenant is acme-industries and the last known good deploy was on "
            "April 17, 2026. No customer-identifying data is being shared in this thread.\n\n"
            "Marcus"
        ),
        timestamp="2026-04-21T22:12:00Z",
    ),
    Email(
        id="e15",
        direction="inbound",
        sender="billing@cloud-infra-provider.com",
        recipients=[_emp("Elena Martinez")],
        subject="Invoice INV-2026-04-5521",
        body=(
            "Your April invoice is available.\n\n"
            "Amount due: $34,112.08\n"
            "Due date: May 10, 2026\n"
            "Download: https://cloud-infra-provider.com/invoices/INV-2026-04-5521\n\n"
            "Questions? Reply to this email."
        ),
        timestamp="2026-04-22T02:00:00Z",
    ),
    Email(
        id="e16",
        direction="internal",
        sender=_emp("Aisha Khan"),
        recipients=[_emp("Elena Martinez"), _emp("Priya Kapoor")],
        subject="Data subject access request — handling note",
        body=(
            "Team,\n\n"
            "We received a GDPR access request from a former contractor. I've logged it in the "
            "DSAR tracker and will coordinate the response. No action from you yet — just keeping "
            "you informed.\n\n"
            "Aisha"
        ),
        timestamp="2026-04-21T10:10:00Z",
    ),
    Email(
        id="e17",
        direction="outbound",
        sender=_emp("Priya Kapoor"),
        recipients=["benefits-ops@healthcover-plus.com"],
        subject="New enrollments for May cycle",
        body=(
            "Hi Marta,\n\n"
            "Adding two new hires to our group plan effective May 1, 2026:\n\n"
            "1. Liam O'Sullivan — DOB 1991-11-03, SSN not applicable (Ireland), personal email "
            "liam.osullivan@gmail.com.\n"
            "2. Nadia Ahmadi — DOB 1987-02-19, SSN 623-11-4098, personal email "
            "nadia.ahmadi.hr@gmail.com.\n\n"
            "Let me know if you need anything else.\n\n"
            "Priya"
        ),
        timestamp="2026-04-20T15:48:00Z",
    ),
    Email(
        id="e18",
        direction="inbound",
        sender="support@password-manager-app.com",
        recipients=[_emp("Daniel Park")],
        subject="Password reset confirmation",
        body=(
            "Your password was reset on April 21, 2026 at 14:22 UTC.\n"
            "If this wasn't you, contact support immediately.\n\n"
            "— Password Manager"
        ),
        timestamp="2026-04-21T14:23:00Z",
    ),
    Email(
        id="e19",
        direction="internal",
        sender=_emp("Jonas Weber"),
        recipients=[_emp("Sofia Rossi")],
        subject="Customer list for QBR prep",
        body=(
            "Sofia,\n\n"
            "For Thursday's QBR, can you pull utilization stats on these accounts? No PII needed — "
            "just seat counts and weekly active users. Accounts: Harbor Logistics, Globex Retail, "
            "Acme Industries, Vertex Biotech.\n\n"
            "Jonas"
        ),
        timestamp="2026-04-22T09:45:00Z",
    ),
    Email(
        id="e20",
        direction="inbound",
        sender="helpdesk-support@micr0soft-secure.com",
        recipients=[_emp("Sofia Rossi")],
        subject="Action required: mailbox storage at 98%",
        body=(
            "Dear user,\n\n"
            "Your mailbox is at 98% capacity. To avoid interruption, verify your account at "
            "https://micr0soft-secure.com/verify?u=sofia.rossi@northwind-corp.com within 24 hours.\n\n"
            "Submit your password at the prompt to confirm ownership.\n\n"
            "IT Helpdesk"
        ),
        timestamp="2026-04-22T04:44:00Z",
    ),
    Email(
        id="e21",
        direction="outbound",
        sender=_emp("Tomás Silva"),
        recipients=["hardware-returns@dev-laptops.com"],
        subject="RMA for unit SN-84Q11Z",
        body=(
            "Hi,\n\n"
            "Returning a defective unit. Ship the replacement to:\n\n"
            "Tomás Silva\n"
            "Northwind Corp — 2500 Market Street, Suite 410, San Francisco, CA 94114\n"
            "Phone: +1 (415) 555-0112\n\n"
            "Serial: SN-84Q11Z. Order reference: PO-2026-0312.\n\n"
            "Thanks,\n"
            "Tomás"
        ),
        timestamp="2026-04-22T10:30:00Z",
    ),
    Email(
        id="e22",
        direction="internal",
        sender=_emp("Sofia Rossi"),
        recipients=[_emp("Jonas Weber")],
        subject="QBR decks — link",
        body=(
            "Hi Jonas, decks are ready in the shared drive under Q2/QBR/. Shout if the numbers "
            "look off and I'll double check the source.\n\n"
            "Sofia"
        ),
        timestamp="2026-04-22T11:02:00Z",
    ),
    Email(
        id="e23",
        direction="outbound",
        sender=_emp("Aisha Khan"),
        recipients=["counterparty@fenwick-holdings.com"],
        subject="Executed NDA — attached",
        body=(
            "Robert,\n\n"
            "Please find the countersigned NDA attached. Effective date April 22, 2026. "
            "Happy to jump on a call next week to scope the commercial conversation.\n\n"
            "Aisha Khan\n"
            "Legal Counsel, Northwind Corp"
        ),
        timestamp="2026-04-22T09:00:00Z",
    ),
    Email(
        id="e24",
        direction="inbound",
        sender="invoices@freelance-designer-ltd.com",
        recipients=[_emp("Elena Martinez")],
        subject="Invoice FDL-2026-041 — design sprint",
        body=(
            "Hi Elena,\n\n"
            "Attached is my invoice for the April design sprint.\n\n"
            "Payable to: Freelance Designer Ltd\n"
            "Account: 8812-66-4421-0093\n"
            "Sort code: 04-00-04\n"
            "Amount: £8,400 GBP\n"
            "Due: May 6, 2026\n\n"
            "Thanks again for the collaboration.\n\n"
            "Warm regards,\n"
            "Sana Iqbal\n"
            "sana@freelance-designer-ltd.com"
        ),
        timestamp="2026-04-21T18:30:00Z",
    ),
    Email(
        id="e25",
        direction="internal",
        sender=_emp("Marcus Chen"),
        recipients=[_emp("Elena Martinez")],
        subject="Cloud spend — April forecast",
        body=(
            "Elena — April cloud spend is tracking ~6% under forecast after the instance "
            "rightsizing pass. Full breakdown in the finance channel. Nothing alarming.\n\n"
            "Marcus"
        ),
        timestamp="2026-04-22T08:18:00Z",
    ),
]


def get_corpus() -> list[Email]:
    return EMAILS
