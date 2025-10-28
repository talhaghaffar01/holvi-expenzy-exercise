# Expenzy API integration

## Assignment

See docs/assignment.md (or .pdf if you prefer).

## Requirements

* A relatively recent version of Docker (tested: 24.0.7) and Docker-Compose (tested: 2.23.1)

## Setup

* Initial setup: `make setup`. This will also cleanup Expenzy database which can be needed for testing from scratch.
* For development good to install pre commit hooks: `pre-commit install`

## How to run

`make up`

## Producing payouts

`make call attempts=1`

## Checking results

To check the results and see if all payouts ended up in Holvi's database:
`make report`
