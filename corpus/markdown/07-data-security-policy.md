# Data Security and Acceptable Use Policy
**Document ID:** POL-IT-001  
**Effective Date:** January 1, 2025  
**Last Reviewed:** September 1, 2025  
**Owner:** Information Security & IT  

---

## 1. Purpose

This policy establishes Acme Corp's requirements for protecting company data, systems, and networks from unauthorized access, disclosure, or misuse. It applies to all employees, contractors, and vendors with access to Acme systems.

---

## 2. Acceptable Use

Acme Corp systems, devices, and network resources are provided for business purposes. Incidental personal use is permitted provided it does not:
- Interfere with job performance
- Violate any law or regulation
- Expose Acme systems to security risks
- Consume excessive bandwidth or storage

### 2.1 Prohibited Uses
- Accessing, downloading, or distributing illegal content
- Using company systems to harass or threaten any person
- Unauthorized access to other users' data or accounts
- Installing unlicensed software on company devices
- Sharing company credentials with third parties
- Using company email or systems for personal business activities
- Circumventing security controls (VPN bypass, proxy avoidance)

---

## 3. Data Classification

| Level | Description | Examples | Handling Requirements |
|---|---|---|---|
| **Public** | Approved for external sharing | Marketing materials, job postings | No restrictions |
| **Internal** | Internal use only; not for external distribution | Policy documents, project plans | Protect from external disclosure |
| **Confidential** | Sensitive business or personal data | Employee records, financial projections, customer data | Encrypt in transit and at rest; need-to-know access only |
| **Restricted** | Highest sensitivity; regulated data | PII, health data, PCI data, trade secrets | Strict access controls; legal/compliance approval required |

---

## 4. Password and Authentication Requirements

- **Minimum length:** 14 characters
- **Complexity:** Must include uppercase, lowercase, numbers, and at least one special character
- **MFA required** for all company systems accessible via SSO (Okta)
- Passwords must not be reused within the last 12 rotations
- Do not share passwords with colleagues — use shared credential vaults (1Password Teams) for team accounts
- Corporate SSO credentials (Okta) must not be used for personal accounts

---

## 5. Device Requirements

### 5.1 Company-Issued Devices
- Full-disk encryption required (FileVault for Mac, BitLocker for Windows — enabled by IT at provisioning)
- Endpoint protection (CrowdStrike Falcon) must remain installed and active
- OS and security patches must be applied within **72 hours** of availability
- Device must auto-lock after **5 minutes** of inactivity
- Do not remove or disable any IT-installed security software

### 5.2 Personal Devices (BYOD)
- Personal devices may access company email and Slack only via the approved MDM profile (Jamf/Intune)
- Personal devices may not access code repositories, internal wikis, or confidential data
- If a personal device is lost or stolen, notify IT immediately: **helpdesk@acmecorp.example.com**

---

## 6. Network Security

- **VPN required** whenever accessing company systems from outside the corporate network (including home office)
- VPN client: Cisco AnyConnect; download from IT portal
- Do not connect to company systems over unsecured public Wi-Fi without VPN
- Home router security: employees are encouraged (not required) to use WPA3 encryption on their home Wi-Fi

---

## 7. Data Handling

### 7.1 Transmission
- Email encryption: use Proofpoint Encryption for Confidential or Restricted data sent externally
- File sharing: use Box (company-sanctioned) for all file sharing; do not use personal Dropbox, Google Drive, or iCloud for company data
- Do not transmit Restricted data via Slack, email, or SMS in plain text

### 7.2 Storage
- Do not store company data on personal devices beyond what is cached by sanctioned apps
- Confidential and Restricted data must not be stored on unencrypted external drives
- Cloud storage: only Box and SharePoint (Acme-managed) are sanctioned for company data

### 7.3 Disposal
- Before returning or disposing of a company device, submit a device wipe request to IT
- Paper documents containing Confidential or Restricted data must be shredded (cross-cut)

---

## 8. Phishing and Social Engineering

- Do not click links or open attachments from unknown or unexpected senders
- Report suspected phishing to **security@acmecorp.example.com** or use the "Report Phishing" button in Outlook
- IT will never ask for your password via email, phone, or Slack
- When in doubt about an email's legitimacy, call the sender directly using a known number

---

## 9. Incident Reporting

Any suspected security incident must be reported immediately:
- **Email:** security@acmecorp.example.com  
- **Phone:** IT Security Hotline x5001 (24/7)

Incidents include: lost/stolen device, suspected unauthorized access, malware, accidental data disclosure to unauthorized parties, or phishing email clicked.

**Do not attempt to investigate or remediate an incident on your own.** Preserve evidence and contact IT Security immediately.

---

## 10. Consequences of Violation

Violations of this policy may result in disciplinary action up to and including termination, civil liability, or referral to law enforcement, depending on the severity of the violation.

---

## 11. Contact

Information Security: **security@acmecorp.example.com**  
IT Helpdesk: **helpdesk@acmecorp.example.com** or ext. 5000
