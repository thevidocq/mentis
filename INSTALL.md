# Installing Mentis

> Draft. Only the infrastructure services exist so far; the API, worker and frontend will be added in the 0.1.0 work.

## Requirements

- Linux VPS with Docker Engine and the Docker Compose plugin.
- At least 4 vCPU and 8 GB RAM (local embeddings and OCR are CPU-heavy). More RAM if you run a local LLM on the same host.

## Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/thevidocq/mentis.git
   cd mentis
   ```
2. Create the environment file and set strong passwords:
   ```bash
   cp .env.example .env
   nano .env
   ```
3. Start the infrastructure:
   ```bash
   docker compose up -d
   docker compose ps
   ```

All services bind to `127.0.0.1` only; nothing is exposed publicly until the frontend and a reverse proxy are added.
