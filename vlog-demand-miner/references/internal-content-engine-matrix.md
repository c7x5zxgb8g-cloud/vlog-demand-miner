# NextTake Content Engine Integration Matrix

## Upstream

- Repository: `UPSTREAM.md`
- Commit: `9c42fe0c932fe81a12f07428492bdf7ae8488f41`
- License: MIT
- Local path: `vendor/content-engine/`

## Reuse Rule

If upstream already owns the business semantics, NextTake calls or routes to it. Input differences are handled by converters; lifecycle behavior is not copied.

| Capability | Owner | Preserved | Local validation | NextTake exposure | Offline demo |
| --- | --- | --- | --- | --- | --- |
| init | initialize | yes | source + required files | root Skill | fixture project |
| benchmark import | learn-from | yes | source present | root Skill | no |
| topic discussion/draft | ideate | yes | source contract + source pack bridge | root Skill | representative fixture |
| scoring | score | yes | source present | root Skill | representative fixture |
| blind scoring | score-blind | yes | source + protocol present | predict route | representative fixture |
| blind prediction | predict | yes | immutable section hash | root Skill | yes |
| shoot registration | shoot | yes | source present | root Skill | state fixture |
| manual publication | publish | yes | source present | root Skill | state fixture |
| performance retro | retro | yes | raw metric validation + native report path | root Skill | yes |
| audience persona | persona | yes | native file projection | root Skill | yes |
| next recommendation | recommend | yes | native file projection | root Skill | yes |
| rubric bump | calibrate | yes | source/protocol present | root Skill | no, requires history |
| trends | trends | yes | adapters preserved | root Skill | no network in demo |
| status | status | yes | source present | root Skill | no |
| migrations | migrate | yes | migration chain preserved | root Skill | no |
| Douyin performance adapter | upstream adapter | yes | VDM resolver/provider tests | provider route | no login in demo |
| Bilibili/XHS/LinkedIn adapters | upstream adapters | yes | source preserved | upstream only | no |

## NextTake-Owned Gaps

- VDM Cluster to upstream candidate/source pack;
- immutable Artifact reference to creator-project files;
- identity-safe raw performance validation and deterministic ratios;
- static Creator Studio projection;
- desensitized hackathon fixture and demo command.

## Non-Goals

- Reimplementing any internal content lifecycle;
- claiming all external adapters work without login and platform verification;
- automatic publishing or draft upload;
- copying browser profiles, cookies, tokens or private creator data into the repository.
