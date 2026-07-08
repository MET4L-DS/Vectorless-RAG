---
description: Scans recent git history and modified workspace files to autonomously update the project memory artifact, tracking architecture shifts and completed goals.
---

# Maintain Project Memory Workflow

Run this trajectory to synchronize the workspace memory file with recent development activity, ensuring future agent sessions have perfect, up-to-date context.

## Step 1: Analyze Recent Workspace Diffs

1. Run a local git status and check recent diffs (`git diff`) across the codebase.
2. Identify which core files were added, refactored, or removed during recent sessions.
3. Check for any new architectural patterns, routes, database schemas, or state changes.

## Step 2: Read Current Memory State

1. Open and read the existing project memory or context file (e.g., `PROJECT_MEMORY.md` or `current_state.md` at the workspace root).
2. Note what goals were previously listed as "In Progress" or "Pending."

## Step 3: Reconcile and Update Document

1. Rewrite or patch the project memory file using a structured layout.
2. Move completed tasks from "In Progress" to "Completed."
3. Log any crucial technical decisions made (e.g., "Switched NBA attainment formula calculation from fractional to whole numbers").
4. List the immediate next logical milestones to serve as a clean handoff for the next session.

## Step 4: Verify Artifact Integrity

1. Review the updated memory document to ensure it remains dense, scannable, and free of conversational fluff.
2. Present a short summary of the memory updates to the user.
