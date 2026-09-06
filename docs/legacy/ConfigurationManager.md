# Configuration Manager

## Goal

Provide a single source of configuration.

## Responsibilities

-   Load .env
-   Load config files
-   Validate required values
-   Expose typed settings
-   Support development/testing/production

## Public API

load() reload() get(key) validate()

## Acceptance Criteria

Application starts with validated configuration.
