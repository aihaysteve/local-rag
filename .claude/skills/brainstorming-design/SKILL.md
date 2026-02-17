---
name: brainstorming-design
description: "You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation."
---

# Brainstorming Ideas Into Designs

## Overview

Help turn ideas into fully formed designs and specs through natural collaborative dialogue.

Start by understanding the current project context, then ask questions one at a time to refine the idea. Once you understand what you're building, present the design in small sections (200-300 words), checking after each section whether it looks right so far.

## Prior Ideation

If user references an idea file (`docs/*-idea-*.md`) or mentions prior ideation:
- Read the referenced idea file
- Follow any `Related: [[...]]` links to gather context from connected ideas
- Use this context to skip or shorten discovery - the problem/opportunity is already captured

## The Process

**Understanding the idea:**
- Check out the current project state first (files, docs, recent commits)
- If prior ideation exists, start from that context
- Ask questions one at a time to refine the idea
- Prefer multiple choice questions when possible, but open-ended is fine too
- Only one question per message - if a topic needs more exploration, break it into multiple questions
- Focus on understanding: purpose, constraints, success criteria

**Exploring approaches:**
- Propose 2-3 different approaches with trade-offs
- Present options conversationally with your recommendation and reasoning
- Lead with your recommended option and explain why

**Presenting the design:**
- Once you believe you understand what you're building, present the design
- Break it into sections of 200-300 words
- Ask after each section whether it looks right so far
- Cover: architecture, components, data flow, error handling, testing
- Be ready to go back and clarify if something doesn't make sense

## Evaluating UX Design Need

After validating the design direction, evaluate whether detailed UX design is needed:

**Recommend ux-design-agent when:**
- User-facing interface (GUI, CLI, voice)
- Agentic system (AI takes actions on user's behalf)
- User model isn't obvious ("who uses this and how?")
- Complex interaction flows (onboarding, wizards, multi-step)

**Skip to writing-plans when:**
- Internal tooling (user model is "us")
- Simple feature with obvious interaction
- Backend/infrastructure work

**Ask explicitly:**
> "This involves [user-facing interface / agentic behavior / complex interaction].
> Would you like detailed UX design (requirements, user model, modality selection)?
> Or proceed directly to implementation planning?"

**If yes:**
- **REQUIRED SUB-SKILL:** Use ux-design-agent
- ux-design-agent will produce structured requirements
- Then continue to writing-plans

**If no:**
- Proceed to writing-plans with current design document

## After the Design

**Documentation:**
- Write the validated design to `docs/plans/YYYY-MM-DD-<topic>-design.md`
- Use writing-clearly-and-concisely skill if available
- Commit the design document to git

**Implementation (if continuing):**
- Ask: "Ready to set up for implementation?"
- Use using-git-worktrees to create isolated workspace
- Use writing-plans to create detailed implementation plan

## Key Principles

- **One question at a time** - Don't overwhelm with multiple questions
- **Multiple choice preferred** - Easier to answer than open-ended when possible
- **YAGNI ruthlessly** - Remove unnecessary features from all designs
- **Explore alternatives** - Always propose 2-3 approaches before settling
- **Incremental validation** - Present design in sections, validate each
- **Be flexible** - Go back and clarify when something doesn't make sense
