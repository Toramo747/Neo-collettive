# MYCELIX Reddit API access request draft

Use this as the basis for Reddit's API access request form.

## Role / use case

Independent developer / general non-commercial developer use.

## Product or service

MYCELIX is an open-source experimental Agent-to-Agent collaboration system. The repository is public:

https://github.com/Toramo747/Neo-collettive

Public runtime:

https://neo-collettive.onrender.com/

## Requested Reddit capability

A narrowly scoped external integration that allows the project operator to manually publish an occasional text post about MYCELIX to a relevant subreddit.

Initial intended target:

r/AI_Agents

The GitHub Actions workflow is manual-only. It does not post on a schedule and cannot publish unless the operator explicitly selects `publish` and types `PUBLISH`.

## Why Devvit is not a fit

The goal is not to install a community extension or moderation tool in a subreddit. The integration is an external project workflow used by the project operator to publish an ordinary text post from their own Reddit account.

## Data use

The integration does not need bulk Reddit data.

For the initial use case it only needs permission to submit a self/text post.

It will not:

- scrape Reddit;
- bulk export posts or comments;
- vote;
- send private messages;
- automate replies or comments;
- perform moderation;
- use Reddit user content to train AI/ML models;
- resell or redistribute Reddit data;
- perform commercial outreach.

## Automation and safety

Publication is explicitly human-triggered through GitHub Actions.

The workflow includes:

- a default validation-only mode;
- a separate publish mode;
- an explicit confirmation string;
- repository-side approval gate;
- secrets stored only in GitHub Actions Secrets;
- no credentials committed to the repository;
- no autonomous posting loop.

## Expected volume

Very low volume. Initial use is a single project manifesto/announcement post. Future posts, if any, would remain occasional and manually triggered.

## Purpose

The post invites developers of public A2A-compatible agents to test interoperable machine-to-machine conversations with MYCELIX and discuss agent collaboration architecture.

## AI-related clarification

MYCELIX itself is an AI-agent project, but this Reddit integration will not use Reddit user content for model training. The requested capability is simply to publish project-authored content from the operator's Reddit account.
