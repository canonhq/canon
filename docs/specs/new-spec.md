---
title: ZenHub Connector
status: draft
---

## Overview

This feature adds a ZenHub connector to Canon, enabling bidirectional synchronization between Canon specs and ZenHub issues. ZenHub is a popular project management layer built on top of GitHub, providing enhanced workflow capabilities like epics, estimates, and pipeline management. By integrating with ZenHub, teams can maintain their existing ZenHub workflows while leveraging Canon's spec-driven development approach.

The connector will allow users to link specs to ZenHub issues, sync acceptance criteria as task lists, update issue metadata based on spec status, and optionally create ZenHub epics from high-level specs. This integration complements the existing GitHub integration by adding ZenHub-specific features without disrupting the core GitHub workflow.

## Requirements

Canon must provide a ZenHub connector that authenticates via ZenHub API tokens and enables linking between specs and ZenHub issues. The connector should support both manual linking (via spec frontmatter) and automatic issue creation from specs.

The integration must sync spec acceptance criteria to ZenHub issues as GitHub task lists, allowing teams to track progress directly in ZenHub. When a spec's status changes (e.g., from draft to approved), the connector should update corresponding ZenHub issue metadata such as pipeline position, labels, or estimates.

Users should be able to configure ZenHub workspace settings including workspace ID, default pipeline mappings for different spec statuses, and whether to automatically create epics for specs tagged with specific keywords. The connector must respect existing GitHub issue links and enhance them with ZenHub-specific data rather than creating duplicate issues.

The system should provide visibility into sync status, showing which specs are linked to ZenHub issues, when the last sync occurred, and any sync errors. Users must be able to manually trigger syncs for individual specs or bulk sync multiple specs.

For teams using ZenHub epics, the connector should support creating parent-child relationships where a high-level spec becomes a ZenHub epic and related specs become child issues. The connector must handle ZenHub API rate limits gracefully and queue sync operations when necessary.

### Acceptance Criteria

- [ ] Users can authenticate with ZenHub using API tokens stored securely in Canon configuration
- [ ] Specs can declare `zenhub_issue` in frontmatter to link to existing ZenHub issues
- [ ] Acceptance criteria from specs sync to linked ZenHub issues as GitHub task lists
- [ ] Spec status changes trigger ZenHub pipeline updates based on configurable mappings
- [ ] Users can configure ZenHub workspace ID and pipeline mappings in repository settings
- [ ] Connector creates new ZenHub issues from specs when `zenhub_issue: auto` is specified
- [ ] Sync status is visible in spec metadata showing last sync time and any errors
- [ ] Manual sync trigger is available via CLI command for individual or bulk specs
- [ ] ZenHub epics can be created from specs tagged with `epic` or similar keywords
- [ ] Parent-child relationships between specs map to ZenHub epic hierarchies
- [ ] API rate limiting is handled with exponential backoff and sync queuing
- [ ] Connector respects existing GitHub issue links and enhances them with ZenHub data
- [ ] Sync errors are logged with actionable error messages for troubleshooting

## Design

The ZenHub connector will be implemented as a new module in the Canon integrations layer, following the same architectural patterns as the existing GitHub and Slack integrations. The connector will use the ZenHub REST API v4 for all operations.

## Rollout Plan

The ZenHub connector will be rolled out in phases to ensure stability and gather user feedback.
