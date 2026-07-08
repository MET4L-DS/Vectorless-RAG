---
description: Guided trajectory for building new features safely aligns scope, analyzes code state, drafts implementation plans, and verifies UI changes.
---

# Feature Drill Workflow

Follow this precise sequence when the user wants to implement a new feature or modify an existing UI component. Do not skip steps.

## Step 1: Scope Alignment & Grilling
1. Invoke the `/grill-me` command to ask the user clarifying questions about the feature scope, edge cases, and UI expectations.
2. Ensure you clearly understand the acceptance criteria before touching any code.

## Step 2: Analyze Local State

1. Scan the relevant project directories to understand the existing architecture.
2. Read existing modules, components, and routing files to prevent duplicate implementations.

## Step 3: Draft the Implementation Plan

1. Generate a structured Implementation Plan artifact.
2. Detail the exact files that will be added or modified, including proposed line diffs.
3. Pause and wait for explicit user approval before executing code modifications.

## Step 4: UI Verification & Browser Testing

1. Use the `/browser` command to launch a local debugging session.
2. Spin up the local development server.
3. Capture a split screenshot or record a short video artifact verifying that the UI changes work exactly as intended across common screen breakpoints.
