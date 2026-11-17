# Kestrel Analytics - Information Security Standard

**Document ID:** KAS-SEC-042  
**Version:** 4.2  
**Owner:** Information Security & Compliance Team  
**Classification:** Internal Use Only  
**Applies To:** All Employees, Contractors, and Third-Party Vendors  

---

## 1. Purpose and Scope

Kestrel Analytics ("Kestrel") handles sensitive financial, operational, and client analytics data. Protecting this information is critical to maintaining client trust, meeting regulatory obligations, and ensuring business continuity. 

This Information Security Standard establishes the mandatory baseline requirements for all employees, contractors, and third-party vendors accessing Kestrel networks, systems, applications, and physical workspaces. Adherence to this standard is a condition of employment and service engagement.

---

## 2. Authentication and Access Control

### 2.1 Password Standards
Passwords remain a primary defense against unauthorized access to corporate accounts. All passwords created within the Kestrel ecosystem must comply with the following rule:
* Passwords must have a **minimum 14 characters**.

Users are strictly prohibited from using default passwords, easily guessable dictionary words, or personal information. Reusing recent passwords across multiple Kestrel platforms is forbidden. Password managers approved by the IT department should be used to generate and store credentials securely.

### 2.2 Multi-Factor Authentication (MFA)
Multi-factor authentication adds a critical layer of security beyond standard passwords. MFA must be enabled on all corporate email accounts, cloud environments, version control repositories, and internal productivity tools. The implementation model is role-based:
* **MFA:** hardware security keys for administrators; authenticator app for everyone else.

Administrators handling elevated privileges must register and use their assigned physical hardware security keys for every authentication request. Standard users must configure and utilize an approved software authenticator app on a secure mobile device.

### 2.3 Access Reviews
To prevent privilege creep and ensure the principle of least privilege is maintained across all systems, user access rights must be audited regularly. 
* **Access reviews are quarterly.**

Managers and system owners are required to review and certify the access rights of their direct reports and team members every three months. Any unneeded or outdated access must be revoked immediately upon discovery.

---

## 3. Endpoint Security

### 3.1 Device Configuration and Locking
All corporate laptops and desktop workstations must be configured with corporate endpoint management software, full-disk encryption, and active endpoint detection and response (EDR) agents. 

To prevent unauthorized physical access when a user steps away from their workstation, devices must lock automatically.
* **Laptops lock after 5 minutes of inactivity.**

Users should also manually lock their screens (using the appropriate keyboard shortcut) whenever they walk away from their devices, regardless of the duration.

---

## 4. Data Classification and Handling

Kestrel classifies all corporate and client data based on its sensitivity and potential impact if compromised. Every employee is responsible for handling data in accordance with its designated classification.

### 4.1 Data Classes
Kestrel recognizes four distinct categories of data:
* **Public**
* **Internal**
* **Confidential**
* **Restricted**

1. **Public:** Information approved for public release (e.g., marketing materials, public-facing website content).
2. **Internal:** General operational data meant solely for internal Kestrel business operations (e.g., internal phone lists, company policies).
3. **Confidential:** Sensitive business data requiring protection against unauthorized disclosure, which could cause financial or reputational harm (e.g., internal financial forecasts, client project metadata).
4. **Restricted:** Highly sensitive data subject to strict legal, regulatory, or contractual protection (e.g., Personally Identifiable Information [PII], raw client financial datasets, cryptographic private keys).

### 4.2 Storage Restrictions
Handling of Restricted data requires extreme caution. To mitigate the risk of loss, theft, or unauthorized extraction:
* **Restricted data may never be stored on laptops.**

Restricted data must reside exclusively within approved, secure, cloud-hosted storage repositories or dedicated server environments equipped with advanced data loss prevention (DLP) controls and rigorous access logging.

---

## 5. Vulnerability Management and Patching

Timely remediation of software vulnerabilities is vital to preventing exploitation by malicious actors. The Information Security team continuously scans corporate infrastructure, applications, and endpoints for known vulnerabilities.

Once vulnerabilities are identified and categorized by severity, system owners and engineering teams must remediate them within established timeframes:
* **Patching:** critical vulnerabilities within 7 days, high within 30 days.

Failure to remediate critical or high vulnerabilities within these windows may result in the affected system being isolated from the Kestrel corporate network until compliance is achieved.

---

## 6. Incident Reporting and Response

Any suspected or confirmed security incident—ranging from lost hardware and suspected phishing to unauthorized data access—must be reported immediately to the Information Security Incident Response Team (ISIRT). Early notification allows Kestrel to contain threats rapidly and minimize potential damage.

Security incidents are categorized by severity level, and specific reporting deadlines apply to each tier.

### 6.1 Incident Response Table

| Severity Level | Definition / Criteria | Reporting Deadline |
| :--- | :--- | :--- |
| **Sev1** | Critical security event involving active data breach, ransomware deployment, or complete system outage affecting core operations. | **Within 1 hour** |
| **Sev2** | Significant security event involving compromised privileged credentials, unauthorized access to Confidential data, or targeted malware on endpoints. | **Within 4 hours** |
| **Sev3** | Minor security event such as a policy violation, lost unencrypted device containing Internal data, or a blocked phishing attempt. | **Within 1 business day** |

To report an incident, notify the ISIRT via the internal ticketing portal, secure messaging channel, or the dedicated emergency security hotline listed on the Kestrel intranet portal.

---

## 7. Compliance and Enforcement

Compliance with this Information Security Standard is mandatory. The Information Security team conducts periodic audits and technical checks to verify adherence. 

Any employee or contractor found to be in willful violation of these standards may face disciplinary action, up to and including termination of employment or immediate revocation of vendor contracts.

Questions regarding this standard or requests for exception reviews must be submitted directly to the Information Security & Compliance Team through official support channels.