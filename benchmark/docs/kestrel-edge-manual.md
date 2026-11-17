# Kestrel Edge User Manual
**Document ID:** KEST-DOC-4482-Rev4  
**Classification:** Internal Use Only — Kestrel Analytics Engineering & Operations  
**Applies To:** Kestrel Edge Hardware v3.2 and later  

---

## 1. Executive Overview and Purpose

This internal operations and user manual details the deployment, configuration, troubleshooting, and hardware specifications for the **Kestrel Edge** remote data acquisition unit. Designed for field telemetry and localized sensor aggregation, the Kestrel Edge unit bridges remote field environments with Kestrel Analytics' cloud data pipelines. 

All field engineers, deployment technicians, and support staff must review this document prior to provisioning units for customer sites. Adherence to these operational guidelines ensures optimal performance, data integrity, and compliance with hardware warranty terms.

---

## 2. Hardware Specifications and Capabilities

The Kestrel Edge unit is engineered for rugged deployments in industrial, agricultural, and remote structural monitoring environments. Technicians must strictly observe the physical and operational boundaries detailed below during site planning and installation.

* **Power Supply:** Kestrel Edge is battery powered, utilizing an internal high-capacity 9000 mAh battery lasting about 14 months under standard operating conditions and reporting intervals.
* **Sensor Capacity:** The unit supports up to 16 sensors connected via proprietary multi-drop bus terminals or wireless local sub-GHz links.
* **Transmission Range:** The internal transceiver provides a wireless range of 80 m to compatible peripheral sensors in unobstructed line-of-sight environments.
* **Operating Temperature:** The device is certified to function reliably within an operating temperature range of -20 to 60 °C. Environmental housings or supplemental thermal shielding must be deployed if ambient conditions fall outside these parameters.

---

## 3. Installation and Deployment Procedures

Proper physical installation is critical to maintaining the operational lifespan of the unit and ensuring reliable data transmission.

### 3.1 Site Selection
1. **Temperature Verification:** Confirm that the mounting location remains within the -20 to 60 °C operating temperature range throughout diurnal cycles.
2. **Sensor Proximity:** Ensure that all connected or wireless peripherals are situated within the 80 m transmission range of the unit. Obstructions such as reinforced concrete or heavy machinery will degrade this distance and must be factored into the site survey.
3. **Cellular Considerations:** Verify cellular site lines to prevent prolonged modem connection failures during initial boot sequences.

### 3.2 Physical Mounting
* Secure the chassis using the provided stainless steel mounting brackets. 
* Ensure the enclosure latch is fully locked. Engaging the enclosure securely depresses the internal security mechanisms, preventing false triggers on the system tamper monitoring circuit.

---

## 4. Maintenance and Routine Checks

While Kestrel Edge is designed for low-maintenance, long-term deployments, routine physical inspections prevent unexpected data loss.

* **Battery Lifecycle Management:** Because Kestrel Edge is battery powered and utilizes a 9000 mAh battery lasting about 14 months, scheduled maintenance tickets should be automatically generated in the Kestrel Operations Portal at the 12-month mark to prepare for unit servicing or battery replacement.
* **Data Offloading:** Local ring buffers write telemetry to an internal secure digital storage medium. Technicians must monitor storage utilization metrics remotely to prevent buffer exhaustion.

---

## 5. Troubleshooting and Error Codes

When the device encounters anomalies, it generates system error codes visible on the local diagnostic LED array and piped via heartbeat telemetry to the Kestrel Analytics central dashboard. 

Field technicians must reference the following table to diagnose and resolve active error states:

| Error Code | Description / Condition | Corrective Action |
| :--- | :--- | :--- |
| **E101** | Battery below 10% capacity threshold | Replace it with an approved replacement power cell immediately. |
| **E117** | Cellular modem has no signal | Move the device to a location with better reception or fit the external antenna. |
| **E125** | SD card full / storage capacity reached | Offload logs to clear local memory buffers. |
| **E142** | Tamper switch triggered | Inspect physical enclosure integrity, check housing latch, and clear the warning log in the diagnostic tool. |

---

## 6. Warranty and Compliance

Kestrel Analytics stands behind the manufacturing quality and operational reliability of its hardware ecosystem.

* **Warranty Coverage:** The Kestrel Edge hardware carries a warranty of 2 years from the date of initial device activation or verifiable purchase registry. This warranty covers internal component defects, manufacturing flaws, and power management circuit failures, provided the unit has been operated strictly within its specified thermal and environmental boundaries. Tampering with internal sealed sub-assemblies outside of authorized maintenance procedures voids all active warranties.