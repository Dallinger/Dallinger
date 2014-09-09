#!/usr/bin/env bash

# Set up the local database
psql -c "CREATE USER postgres WITH PASSWORD '';"
psql -c "CREATE DATABASE db WITH OWNER postgres;"
export DATABASE_URL=postgresql://postgres@localhost/db
