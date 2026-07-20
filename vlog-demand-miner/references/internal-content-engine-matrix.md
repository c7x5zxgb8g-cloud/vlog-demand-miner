# cheat-on-content Integration Matrix

## Upstream

- Repository: `https://github.com/XBuilderLAB/cheat-on-content.git`
- Commit: `9c42fe0c932fe81a12f07428492bdf7ae8488f41`
- License: MIT
- Local path: `vendor/content-engine/`

## Reuse Rule

If upstream already owns the business semantics, NextTake calls or routes to it. Input differences are handled by converters; lifecycle behavior is not copied.

| Capability | Owner | Preserved | Local validation | NextTake exposure | Offline demo |
| --- | --- | --- | --- | --- | --- |
| init | cheat-init | yes | source + required files | root Skill | fixture project |
| benchmark import | cheat-learn-from | yes | source present | root Skill | no |
| topic discussion/draft | cheat-seed | yes | source contract + source pack bridge | root Skill | representative fixture |
| scoring | cheat-score | yes | source present | root Skill | representative fixture |
| blind scoring | cheat-score-blind | yes | source + protocol present | cheat-predict route | representative fixture |
| blind prediction | cheat-predict | yes | immutable section hash | root Skill | yes |
| shoot registration | cheat-shoot | yes | source present | root Skill | state fixture |
| manual publication | cheat-publish | yes | source present | root Skill | state fixture |
| performance retro | cheat-retro | yes | raw metric validation + native report path | root Skill | yes |
| audience persona | cheat-persona | yes | native file projection | root Skill | yes |
| next recommendation | cheat-recommend | yes | native file projection | root Skill | yes |
| rubric bump | cheat-bump | yes | source/protocol present | root Skill | no, requires history |
| trends | cheat-trends | yes | adapters preserved | root Skill | no network in demo |
| status | cheat-status | yes | source present | root Skill | no |
| migrations | cheat-migrate | yes | migration chain preserved | root Skill | no |
| Douyin performance adapter | upstream adapter | yes | VDM resolver/provider tests | provider route | no login in demo |
| Bilibili/XHS/LinkedIn adapters | upstream adapters | yes | source preserved | upstream only | no |

## NextTake-Owned Gaps

- VDM Cluster to upstream candidate/source pack;
- immutable Artifact reference to creator-project files;
- identity-safe raw performance validation and deterministic ratios;
- static Creator Studio projection;
- desensitized hackathon fixture and demo command.

## Non-Goals

- Reimplementing any `cheat-*` lifecycle;
- claiming all external adapters work without login and platform verification;
- automatic publishing or draft upload;
- copying browser profiles, cookies, tokens or private creator data into the repository.
