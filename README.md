# Distributed Disaster Control & Emergency Response System

**COE892 - Distributed Cloud Computing | Winter 2026 | Toronto Metropolitan University**

**Group 6:** Raidah Nazimuddin, Nadia Jahan, Anthony Teti, Rikhina Sarker

---

## Overview

A distributed system that simulates how emergency units (police, fire, ambulance) are dynamically dispatched and coordinated during disasters. The system uses independent microservices communicating asynchronously via RabbitMQ message queues, demonstrating distributed cloud computing concepts including publish-subscribe messaging, service coordination, and real-time monitoring.

## Architecture

```
                          incident_exchange (fanout)
Incident Service  ──publish──>  RabbitMQ  ──consume──>  Dispatch Service
                                  │                        │
                                  │                   dispatch_exchange
                                  │                        │
                                  ├──────────────────>  Unit Service
                                  │                        │
                                  │                   status_exchange
                                  │                        │
                                  ├<─────────────────  (status updates)
                                  │
                            Dashboard Service
                          (listens to all 3 exchanges
                           via exclusive queues)
                                  │
                              Browser (SSE)
```

### Services

| Service | File | Role |
|---------|------|------|
| **Incident Service** | `incident_service.py` | Generates emergency incidents with type, severity, location, and risk level |
| **Dispatch Service** | `dispatch_service.py` | Central coordinator. Assigns units using composite scoring (distance + severity + zone risk). Dispatches additional units for high-risk incidents |
| **Unit Service** | `unit_service.py` | Simulates emergency vehicle response lifecycle: en_route -> on_scene -> completed |
| **Dashboard Service** | `dashboard_service.py` | Flask web app with real-time SSE updates, risk heatmap, and unit tracking |
| **Risk Analysis** | `risk_analysis.py` | Neighborhood risk engine with historical, dynamic, and base risk scoring |
| **Common** | `common.py` | Shared RabbitMQ connection and fanout exchange setup |

## Prerequisites

- **Python 3.8+**
- **RabbitMQ** installed and running on `localhost` (default port 5672)

### Installing RabbitMQ

**Ubuntu/Debian:**
```bash
sudo apt-get install rabbitmq-server
sudo systemctl start rabbitmq-server
```

**Windows:**
1. Install Erlang from https://www.erlang.org/downloads
2. Install RabbitMQ from https://www.rabbitmq.com/install-windows.html
3. Start the RabbitMQ service from the Start Menu or run `rabbitmq-server` in the command prompt

**macOS:**
```bash
brew install rabbitmq
brew services start rabbitmq
```

## Setup

1. Clone or extract the project:
   ```bash
   cd disaster-control-system
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate        # Linux/macOS
   venv\Scripts\activate           # Windows
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## How to Run

Make sure RabbitMQ is running, then open **four separate terminals** (all in the project directory with the virtual environment activated):

**Terminal 1 - Dispatch Service (start first):**
```bash
python dispatch_service.py
```

**Terminal 2 - Unit Service:**
```bash
python unit_service.py
```

**Terminal 3 - Dashboard:**
```bash
python dashboard_service.py
```
Then open **http://localhost:5000** in a browser.

**Terminal 4 - Incident Service (generates incidents):**
```bash
# Generate incidents continuously (one every 5 seconds):
python incident_service.py --loop

# Or generate a single incident:
python incident_service.py
```

## Running Tests

The test suite validates risk analysis, composite scoring, dispatch logic, and service behavior without requiring RabbitMQ:

```bash
python test_suite.py
```

All 55 tests should pass.

## Key Features

- **Microservice Architecture:** Independent services communicating via RabbitMQ fanout exchanges
- **Publish-Subscribe Messaging:** Fanout exchanges allow multiple consumers (services + dashboard) to receive the same messages without interference
- **Neighborhood Risk Analysis:** 4 zones (Downtown, Suburb, Industrial, Residential) on a 7x7 grid with base, historical, and dynamic risk components
- **Composite Scoring Dispatch:** Unit selection weighs both proximity and severity - critical incidents get the closest unit while low-severity incidents avoid pulling units from high-risk zones
- **Dual-Unit High-Risk Dispatch:** Incidents with risk > 0.7 automatically receive a second unit
- **Proactive Unit Relocation:** Idle units are suggested to relocate toward uncovered high-risk neighborhoods
- **Real-Time Dashboard:** Flask + SSE web interface with live grid map, risk heatmap, unit status table, neighborhood risk panel, and event log
- **Dynamic Risk Tracking:** Active incidents raise neighborhood risk in real-time; resolved incidents lower it

## Project Structure

```
disaster-control-system/
├── common.py               # Shared RabbitMQ connection & fanout exchange setup
├── incident_service.py     # Incident generator (single or continuous mode)
├── dispatch_service.py     # Central dispatch with composite scoring
├── unit_service.py         # Emergency vehicle response simulation
├── risk_analysis.py        # Neighborhood risk analysis engine
├── dashboard_service.py    # Flask dashboard with SSE
├── status_listener.py      # Debug tool - prints status updates to console
├── test_suite.py           # 55 unit tests
├── requirements.txt        # Python dependencies (pika, flask)
├── templates/
│   └── dashboard.html      # Dashboard frontend (HTML/CSS/JS)
└── README.md               # This file
```

## Technologies

| Technology | Purpose |
|------------|---------|
| Python | Primary language for all services |
| RabbitMQ | Message broker for async inter-service communication |
| Pika | Python RabbitMQ client library |
| Flask | Web framework for dashboard HTTP/SSE endpoints |
| Server-Sent Events | Real-time push from server to browser |
| HTML/CSS/JavaScript | Dashboard frontend (no external frameworks) |
