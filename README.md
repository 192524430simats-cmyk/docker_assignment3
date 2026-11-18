# Smart Campus Assignment 3

This repository contains the Smart Campus web application, Docker Compose deployment configuration, and assignment report.

## Start locally

1. Install Docker Desktop and start the Docker engine.
2. From the repository root run `docker compose up --build -d`.
3. Check service status with `docker compose ps -a`.
4. Open `http://localhost:8080` in a browser. The health endpoint is `http://localhost:8080/health`.
5. View recent service logs with `docker compose logs --tail=80 proxy api db`.
6. Stop services with `docker compose down`.

The report includes the student details provided for submission.
