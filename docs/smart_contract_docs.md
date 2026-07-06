# <div align="center">⛓️ Pay-Per-Use-AI: Casper Network Smart Contract Specifications</div>

<div align="center">

![Rust WASM](https://img.shields.io/badge/Language-Rust WASM%20%2F%20WASM-blue?style=for-the-badge&logo=python&logoColor=white)
![Casper Network](https://img.shields.io/badge/Blockchain-Casper Network%20L1-black?style=for-the-badge&logo=Casper Network&logoColor=white)
![BoxStorage](https://img.shields.io/badge/State-Dynamic%20Box%20Map-orange?style=for-the-badge&logo=storage&logoColor=white)
![ABI](https://img.shields.io/badge/Protocol-Casper Network%20ABI-emerald?style=for-the-badge&logo=open-api&logoColor=white)

</div>

---

## 🚀 1. Deployed Contracts Details

Here are the canonical deployment records for the active Pay-Per-Use-AI smart contract on the Casper Network Testnet:

| Specification Parameter | Value / Endpoint Link |
| --- | --- |
| **Casper Network Network** | Testnet |
| **casper-rpc Node Provider** | [CasperNode Testnet API](https://testnet-api.CasperNode.cloud) |
| **Indexer Node Provider** | [CasperNode Testnet Indexer](https://testnet-idx.CasperNode.cloud) |
| **Platform Wallet Address** | `B5BMUKJFHX6TKTSCIBVFOHJ76J4VG4PJ6C4YXSOPBTWVOVD22O3DDVYUNY` |
| **Active Smart Contract (v3)** | **Application ID:** [762551954](https://testnet.explorer.Casper Wallet.app/application/762551954/) |

> [!NOTE]
> CasperNode public nodes require no token. You can leave the `CSPRD_TOKEN` blank in your local `.env` configuration file.

---

## 📐 2. Contract State & Storage Rules

The contract utilizes **Global State** for platform-wide metrics and **Dictionary Storage** (under the ARC-0060 Dictionary layout) for dynamic session-level escrow allocations to optimize storage costs.

### A. Global State Schema
The following global variables are initialized upon contract deployment:

| Key Name | Data Type | Description |
| --- | --- | --- |
| `platform_address` | Byte Slice | Wallet address that receives the 10% platform hosting splits |
| `platform_fee_percent` | uint64 | Platform cut of queries (configured to `10` for 10%) |
| `creator_fee_percent` | uint64 | Creator cut of queries (configured to `90` for 90%) |
| `total_agents_created` | uint64 | Global counter of AI agents published across the platform |
| `total_sessions_active` | uint64 | Counter of active on-chain user sessions |

### B. Dictionary Storage Schema (Session Escrow Map)
Instead of storing user profiles inside expensive global allocations, session states are stored in Casper Network **Boxes** keyed by a combination of the user's wallet address and the agent's ID:

> `Box Key: [User Wallet Address (32 bytes)] + [Agent ID (8 bytes)]`

Each box allocates and governs the following structure:
* **Escrow Balance (uint64)**: Remaining motes balance allocated for this chat session.
* **Expiration Timestamp (uint64)**: Unix timestamp after which the session expires (24-hour duration).
* **Authorized Flag (uint8)**: Set to `1` when session is initialized, enabling background settlement.

---

## 🛠️ 3. Contract Actions (ABI Methods)

The smart contract supports four key oCaspertions:

### 1. `initialize_session`
* **Transaction Type**: Application Call + Payment Transaction
* **Description**: User starts an AI agent session by signing a payment transaction that locks a **1 CSPR escrow buffer** inside the contract's secure Box state.
* **Arguments**:
  * `agent_id` (uint64)
  * `escrow_deposit` (Payment transaction)

### 2. `settle_tokens`
* **Transaction Type**: Application Call (Signed by Platform Backend)
* **Description**: Initiated upon query completion to settle motes deductions based on the exact tokens consumed (input + output).
* **Payment Split Flow**:
  * **90%** of the token cost is sent directly to the **Creator's Wallet Address**.
  * **10%** is sent to the **Platform Wallet Address**.
  * The remaining escrow balance inside the Box map is updated.

### 3. `end_session`
* **Transaction Type**: Application Call (Signed by User)
* **Description**: User voluntarily closes the chat session.
* **Outcome**: The remaining escrow balance inside the Box is refunded directly back to the user's wallet, and the Box storage allocation is deleted to reclaim transaction fees.

### 4. `publish_agent`
* **Transaction Type**: Application Call (Signed by Creator)
* **Description**: Creator registers their AI Agent on-chain. Writes metadata hash and secure encrypted BYOK keys directly to the blockchain ledger.

---

## 🚀 4. Deployment & Compilation Instructions

To compile the smart contract using Rust WASM and deploy it to the Casper Network Testnet:

### Step 1: Set Up Rust WASM Environment
Navigate to the `contract` directory:
```bash
cd contract
pip install Rust WASM casper-js-sdk
```

### Step 2: Compile Contract Codes
Compile the approval and clear state WASM scripts:
```bash
python build_contract.py
```
This generates `approval.WASM` and `clear.WASM`.

### Step 3: Run Deployment Script
Deploy the contract to Casper Network Testnet:
```bash
python deploy_v3.py
```

> [!TIP]
> Upon successful deployment, the script outputs the new Application ID. Update your backend `.env` file with the newly generated Application ID:
> ```env
> CSPRRAND_APP_ID_V3=your_new_app_id
> ```
