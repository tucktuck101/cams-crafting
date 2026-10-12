# MATERIAL_CREATION_RULES.md

# Operational Specification for the Magical Material System

**Purpose:** Enable another AI agent to create, revise, classify,
balance, and present homebrew D&D 5e magical materials in a way that
reproduces the user's established methodology.

**Status:** Working specification compiled from the accessible saved
memories, recent conversation context, and the user's uploaded task
brief. Confirmed rules are separated from inferred practices and
unresolved questions.

------------------------------------------------------------------------

## 1. Overview

### 1.1 Purpose and scope

This document defines the user's custom process for designing magical
materials for a D&D 5e campaign and crafting system. It covers:

-   Material rarity and worldbuilding.
-   Crafting modifiers and the relationship between rarity, difficulty,
    and power.
-   Mechanical design for materials used in weapons, armour, staffs,
    rods, spellcasting foci, clothing, capes, and leather goods.
-   Lore, naming, formatting, and sourcebook-ready presentation.
-   Revision, balance checks, and validation.
-   Known material classifications and examples.

The goal is not merely to imitate the wording of past entries. An agent
should reproduce the **decision process**: identify the material's
central identity, decide how difficult it is to obtain or work, assign a
rarity and crafting modifier, create effects appropriate to the object
made from it, and validate both mechanics and lore against established
constraints.

### 1.2 Intended users

-   The user, as a reference for consistent material design.
-   Another AI agent that has no access to the original conversation
    history.
-   A human game master adapting the materials to a campaign.

### 1.3 Sources examined

This specification draws on:

1.  **User's uploaded task brief** (`message.txt`, provided in the
    current conversation), including its requirements for traceability,
    explicit/inferred rules, workflows, precedence, validation, and
    gaps.
2.  **Accessible saved memories** containing explicit material-system
    preferences, rarity definitions, mechanical conventions, and
    selected material decisions.
3.  **Accessible recent conversation context**, including corrections to
    rarity classifications and the user's stated crafting-modifier
    ranges.
4.  **Current and previously edited writing-block text surfaced in
    context**, including material entries for Asterwood,
    Chronocalcite/Tempus Steel, Lifewood, Elderbeast Hide, Dragonfire
    Leather, Darkwood, Ironwood, and others.
5.  **Prior discussion of Kibbles' Crafting Guide / Compendium of Craft
    and Creation**, which established the comparison point that crafting
    modifiers should reflect the difficulty of processing/working a
    material rather than directly measure combat strength.

### 1.4 Access limitations

This is not a complete export of every historical conversation. The
agent cannot claim to have reviewed conversations, attachments, or
instructions that are not surfaced in the current context or available
memory. Some older material mechanics are represented in summaries
rather than their full original text. Where full wording is unavailable,
this document records the established identity or known rule and marks
details as needing verification.

No private system/developer instructions are reproduced. Unrelated
personal information is excluded.

### 1.5 Evidence labels

-   **Explicit:** Directly established by the user or preserved as an
    explicit preference.
-   **Inferred:** A consistent pattern inferred from examples or
    revisions.
-   **Provisional:** A proposal appeared in the conversation but the
    user has not clearly approved it.
-   **Unknown:** Evidence is incomplete or conflicting; do not invent a
    definitive answer.

### 1.6 Authoritative handouts

The handout files in this repository are the current authoritative
canon for material names, rarities, difficulty modifiers, gold costs,
lore, and mechanics:

-   `Hides-and-leather.md`
-   `ores-and-ingots.md`
-   `woods-and-branches.md`
-   `material-rarity-preface.md`

Where this specification disagrees with a handout, the handout wins.
Materials that do not appear in a handout are not part of the current
canon.

------------------------------------------------------------------------

## 2. Core Principles

### 2.1 A material is not automatically a magic item

The core design goal is to create **materials with characteristic
properties**, not merely magic items with a material-themed name. The
material's lore should explain why it behaves as it does, and its
mechanical properties should express that identity.

Examples: - Darkwood is unusually light and strong. - Ironwood remains
wood for relevant magical interactions while having metal-like strength
and fire resistance. - Shadowhide improves hiding in dim light or
darkness. -
Chronocalcite/Tempus Steel manipulates time. - Asterwood channels
constellation-themed powers.

This is a guiding principle, not a prohibition on a material having
several substantial effects. Rarity and the particular material's design
determine how broad the package may be.

### 2.2 Rarity-specific design principles

Rarity is about the material's place in the world: availability,
knowledge, provenance, production, and extraordinary nature. It is not
just a label for damage numbers.

**Uncommon-specific simplicity guideline:** Uncommon materials should
generally have one strong defining property or two closely related minor
properties. Avoid giving them an entire suite of unrelated combat,
defence, movement, and utility powers.

**Important scope limit:** This simplification applies to **Uncommon
materials only**. It must not be automatically imposed on Rare, Very
Rare, or Legendary materials. Higher tiers can support greater
mechanical depth and more numerous effects.

### 2.3 Rarity and crafting modifier are separate measures

The rarity answers, broadly, how extraordinary, scarce, or difficult to
access the material is. The crafting modifier represents the difficulty
of processing, harvesting, stabilising, or working the material into a
usable form.

Do not automatically equate: - higher rarity with a higher crafting
modifier in every case; - stronger combat effects with greater crafting
difficulty; or - a known technique with easy access to the raw material.

A material may be powerful but workable using established techniques.
Another material may have modest effects but require a very difficult or
nearly lost process.

### 2.4 Lore communicates rarity indirectly

Do **not** explicitly state rarity in the lore prose. Instead, show it
through: - how widely the material is known; - whether it occurs
naturally or requires a special process; - whether techniques are
established, guarded, obscure, or lost; - how many craftspeople can work
it; - whether merchant groups can source it; - whether the material
requires divine favour, planar origin, or an ancient ritual.

The rarity label may appear in the material's heading or metadata. The
lore itself should demonstrate the reason for that classification rather
than announcing it.

### 2.5 Crafting should be reproducible where the rarity permits

Uncommon materials generally have known sources or workable methods.
Rare materials may require limited supply, specialised processing, or
particular contacts. Very Rare materials may be understood by only a
handful of specialists, with incomplete records or imitation methods.
Legendary materials have no reliable mundane acquisition or production
method, though they may still appear on the Material Plane.

### 2.6 Distinct identities matter

Each material should have a recognisable fantasy and mechanical
identity. Avoid giving every material the same damage rider, reaction
defence, or generic bonus. When choosing between multiple possible
effects, favour the effect that best expresses the material's
established theme.

### 2.7 Preserve approved decisions

When the user revises a name, rarity, effect, or piece of lore, use the
latest approved version. Do not revive superseded names or older
mechanics unless the user explicitly asks to compare or restore them.

------------------------------------------------------------------------

## 3. Rules Catalogue

Each rule has a stable identifier. Priority: - **Mandatory:** Must be
followed unless the user explicitly overrides it. - **Conditional:**
Applies when its trigger or condition is met. - **Preferred:** Strong
design guidance that may be overridden by a direct user instruction.

### RULE-001 --- Use the user's current material canon

-   **Classification:** Explicit.
-   **Trigger:** Every creation, revision, list, or audit.
-   **Conditions:** A material's current name, rarity, or mechanics have
    been corrected or edited.
-   **Required behaviour:** Use the most recent explicit user correction
    or edited version available. Treat the latest corrected
    classification in this document as the baseline.
-   **Prohibited behaviour:** Reintroducing a superseded rarity, name,
    or effect from older summaries.
-   **Exceptions:** If the user asks to compare historical versions,
    describe the versions separately.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-002, RULE-023.
-   **Source evidence:** The user designated the repository handouts
    (Section 1.6) as the current authoritative canon.
-   **Confidence:** High.
-   **Example:** Classify Fireglass as Uncommon, not Rare.

### RULE-002 --- Use the current rarity classification

-   **Classification:** Explicit.
-   **Trigger:** Assigning rarity, auditing materials, or presenting a
    catalogue.
-   **Required behaviour:** Use the current list in Section 3.1. If a
    material is absent or uncertain, ask or mark it unresolved rather
    than guessing.
-   **Prohibited behaviour:** Using a generic published game's rarity to
    override the user's custom tier.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-001, RULE-003.
-   **Source evidence:** User corrections across the material project.
-   **Confidence:** High for listed materials; medium for materials
    whose full historical status is not surfaced.

#### 3.1 Current rarity catalogue

Derived from the authoritative handouts (Section 1.6).

**Uncommon** - Darkwood (Zalantar) - Ironwood - Cryptomeria - Mithril -
Adamantine - Black Iron - Shadowhide - Skysteel - Fireglass - Tidehide

**Rare** - Phoenix Ashwood - Moonroot - Worldroot - Stormwood - Mizzium -
Covolt - Frostfell Alloy - Gloomsteel - Glintsteel - Nimbusium -
Voidleather - Angelforged Leather - Gravemantle - Abyssal Hide

**Very Rare** - Spirit Bark - Gaiawood - Sablewood - Chromatite -
Radiatite - Nanom - Formsteel - Aetherium - Dragonfire Leather

**Legendary** - Lignum Vitae / Lifewood - Asterwood - Chronocalcite /
Tempus Steel - Metoricite / Astral Iron - Fateskin

**Rarity not stated in the handout:** Starlight Leather, Soulweave,
Elderbeast Hide. Ask the user before assigning a tier.

### RULE-003 --- Apply the user's crafting modifier bands

-   **Classification:** Explicit.
-   **Trigger:** Assigning or reviewing a material's crafting modifier.
-   **Required behaviour:** Use these ranges:
    -   Uncommon: **+2 to +7**
    -   Rare: **+5 to +7**
    -   Very Rare: **+7 to +9**
    -   Legendary: **+10 minimum**
-   **Prohibited behaviour:** Treating these ranges as a fixed modifier
    per rarity or assuming every item of one rarity has the same
    modifier.
-   **Exceptions:** The user may later change these ranges.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-004, RULE-005.
-   **Source evidence:** User's explicit statement: "I have set the
    crafting modifier range for uncommon crafting materials, depending
    on their mechanics, to be from plus 2-7, while Rare is from plus
    5-7, Very Rare is from plus 7-9, and Legendary is plus 10 minimum."
-   **Confidence:** High.
-   **Example:** A difficult-to-forge Uncommon material can be +7; a
    Legendary material must be at least +10.

### RULE-004 --- Set crafting modifiers based on working difficulty

-   **Classification:** Explicit principle with inferred application
    details.
-   **Trigger:** Choosing a modifier within the permitted band.
-   **Required behaviour:** Consider the real work required to harvest,
    prepare, stabilise, refine, weave, tan, alloy, forge, or enchant the
    material. Consider whether techniques are known, specialist,
    hazardous, unstable, or lost.
-   **Prohibited behaviour:** Assigning the modifier solely from the
    material's damage bonus or rarity label.
-   **Exceptions:** None established.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-003, RULE-005, RULE-006.
-   **Source evidence:** User requested an audit against Kibbles'
    Crafting Guide, especially crafting modifiers; prior discussion
    established that Kibbles' modifiers represent
    material-processing/harvesting difficulty rather than item combat
    power.
-   **Confidence:** High.
-   **Example:** Darkwood may have a low modifier because woodworking
    techniques are established, while a less combat-powerful material
    requiring lost temporal forging knowledge may have a very high
    modifier.

### RULE-005 --- Do not collapse rarity and modifier into one scale

-   **Classification:** Explicit.
-   **Trigger:** Balancing or comparing materials.
-   **Required behaviour:** Evaluate rarity and crafting difficulty
    independently, while allowing lore to make them related where
    appropriate.
-   **Prohibited behaviour:** Automatically assigning the top modifier
    in every tier or treating Legendary as necessarily +12.
-   **Exceptions:** Legendary is explicitly +10 minimum.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-003, RULE-004.
-   **Source evidence:** User's modifier ranges and the Kibbles
    comparison discussion.
-   **Confidence:** High.
-   **Example:** A Rare material with an established but hazardous
    process may be +5; a Very Rare material requiring highly specialised
    work may be +9.

### RULE-006 --- Use Kibbles as a benchmark, not as an override

-   **Classification:** Explicit.
-   **Trigger:** Auditing crafting difficulty or comparing the material
    system to Kibbles' Crafting Guide / Compendium of Craft and
    Creation.
-   **Required behaviour:** Use Kibbles' examples and concepts to check
    whether modifiers fit a plausible crafting difficulty curve. Clearly
    distinguish Kibbles' published rules from the user's custom rules.
-   **Prohibited behaviour:** Silently importing Kibbles' rarity
    classifications or mechanics when the user has established different
    ones.
-   **Exceptions:** If the user asks for a faithful Kibbles rules
    implementation, follow the requested source and edition.
-   **Priority:** Mandatory when conducting a Kibbles comparison.
-   **Dependencies:** RULE-003, RULE-004, RULE-005.
-   **Source evidence:** User explicitly requested exploration of
    Kibbles' Crafting Guide and fit with the system's difficulty curve.
-   **Confidence:** High.
-   **Example:** A published crafting DC for Mithril can be a comparison
    point, but the user's custom rarity and modifier bands remain
    authoritative.

### RULE-007 --- Uncommon materials have a focused mechanical identity

-   **Classification:** Explicit preference.
-   **Trigger:** Creating or balancing an Uncommon material.
-   **Required behaviour:** Generally design one strong defining
    property or two closely related minor properties. Keep the effects
    cohesive and understandable.
-   **Prohibited behaviour:** Applying this Uncommon simplicity rule to
    Rare, Very Rare, or Legendary materials as though it were a global
    cap.
-   **Exceptions:** The user can expressly approve a broader Uncommon
    design.
-   **Priority:** Preferred, with the rarity scope mandatory.
-   **Dependencies:** RULE-008, RULE-009.
-   **Source evidence:** Saved memory records the Uncommon design
    guideline; user later clarified that the proposed direction applies
    only to Uncommon grade materials.
-   **Confidence:** High.
-   **Example:** Shadowhide's Umbral Camouflage (advantage on Stealth in
    dim light or darkness) is a focused Uncommon effect.

### RULE-008 --- Do not impose an unapproved property-selection rule

-   **Classification:** Explicit, based on a later reversal.
-   **Trigger:** Designing materials with multiple effects.
-   **Required behaviour:** Use the item's approved effect package
    unless the user asks for a selection system.
-   **Prohibited behaviour:** Assuming that Uncommon items can choose
    one property and Rare items can choose two as a mandatory
    system-wide rule.
-   **Exceptions:** If the user reintroduces that rule explicitly, apply
    it according to the new instruction.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-007, RULE-009.
-   **Source evidence:** User proposed "choose up to 2 effects" for Rare
    and below, then said "Actually, never mind. We don't need to do
    this."
-   **Confidence:** High.
-   **Example:** Do not automatically turn a material's armour effects
    into a choose-one menu.

### RULE-009 --- Match effect power and complexity to rarity

-   **Classification:** Inferred from repeated balancing decisions.
-   **Trigger:** Creating or auditing mechanics.
-   **Required behaviour:** Compare the overall package, action economy,
    damage, control, defensive coverage, use frequency, and passive
    benefits against the material's tier and against relevant
    official/third-party benchmarks.
-   **Prohibited behaviour:** Assuming an individual effect is balanced
    merely because it has a limited number of uses.
-   **Exceptions:** Legendary materials may be extraordinary; evaluate
    them against the campaign's intended power level.
-   **Priority:** Preferred.
-   **Dependencies:** RULE-007, RULE-010, RULE-011.
-   **Source evidence:** Repeated rarity audits, official 5e
    comparisons, and user requests to keep materials from becoming
    generic magic items.
-   **Confidence:** High.
-   **Example:** A repeatable stun effect on a Rare weapon deserves
    greater scrutiny than a modest damage rider.

### RULE-010 --- Avoid unnecessarily strong control at lower tiers

-   **Classification:** Inferred.
-   **Trigger:** A material grants stun, restraint, incapacitation,
    broad disadvantage, or a strong movement lock.
-   **Required behaviour:** Check the condition's practical impact, save
    frequency, duration, immunity windows, and uses. Consider a narrower
    alternative such as reduced speed or no reactions if that preserves
    the concept.
-   **Prohibited behaviour:** Treating all conditions as equal in power.
-   **Exceptions:** Higher-tier materials can intentionally support
    stronger control.
-   **Priority:** Preferred.
-   **Dependencies:** RULE-009.
-   **Source evidence:** Stormwood's stun effect was identified as a
    balance concern, with a proposed replacement of no reactions and
    speed 0.
-   **Confidence:** Medium-high.

### RULE-011 --- Use the correct per-turn use convention

-   **Classification:** Explicit.
-   **Trigger:** Any D&D material effect written "once per turn."
-   **Required behaviour:** Replace "once per turn" with: **"You can use
    this effect several times equal to your Proficiency Bonus, regaining
    all uses on a long rest."**
-   **Prohibited behaviour:** Leaving an unrestricted once-per-turn
    effect where this preference applies.
-   **Exceptions:** If the user expressly specifies another usage limit
    for a particular effect, follow the specific instruction.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-009.
-   **Source evidence:** Saved memory explicitly records this requested
    rule.
-   **Confidence:** High.
-   **Example:** If a weapon rider triggers on a hit, it can be used up
    to the wielder's Proficiency Bonus times per Long Rest.

### RULE-012 --- Prefer necrotic or acid over poison when thematically suitable

-   **Classification:** Explicit.
-   **Trigger:** Selecting damage type for a new material or revising an
    existing one.
-   **Required behaviour:** Consider necrotic or acid damage instead of
    poison when either fits the material's theme, because poison is
    commonly resisted in 5e.
-   **Prohibited behaviour:** Automatically replacing poison where the
    material's established identity specifically depends on poison.
-   **Exceptions:** Preserve the user's explicit damage type in an
    approved current version unless asked to revise it.
-   **Priority:** Preferred, overridden by specific approved mechanics.
-   **Dependencies:** RULE-009, RULE-023.
-   **Source evidence:** Saved memory explicitly says to prefer
    necrotic/acid when suitable and records Radiatite as necrotic rather
    than poison.
-   **Confidence:** High.
-   **Example:** Radiatite's rider should use necrotic damage and
    prevent the target from regaining hit points until the end of its
    next turn, according to the saved preference.

### RULE-013 --- Separate weapon properties from focus properties

-   **Classification:** Explicit.
-   **Trigger:** A material can be used for weapons and for staffs,
    rods, wands, or spellcasting foci.
-   **Required behaviour:** Write distinct subsections for weapon and
    focus uses. Focus mechanics should express spellcasting,
    concentration, range, magical control, or another fitting focus
    identity.
-   **Prohibited behaviour:** Giving a focus generic weapon effects as
    though it were a weapon unless the user explicitly wants that.
-   **Exceptions:** A staff may be both a weapon and a focus if the user
    requests both rules; state which properties apply to which use.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-014, RULE-015.
-   **Source evidence:** Saved memory explicitly distinguishes wooden
    weapon effects from staff/rod/focus effects.
-   **Confidence:** High.
-   **Example:** Darkwood's bow range property belongs to weapons; its
    ranged spell attack and concentration benefits belong to a
    staff/rod.

### RULE-014 --- Apply wood weapon effects only to primarily wooden weapons

-   **Classification:** Explicit.
-   **Trigger:** Creating weapon mechanics for a magical wood.
-   **Required behaviour:** Limit weapon properties to weapons that can
    be primarily made from wood.
-   **Allowed melee weapons:** Club, Greatclub, Javelin, Quarterstaff,
    Spear, Glaive, Halberd, Lance, Pike.
-   **Allowed ranged weapons:** Dart, Shortbow, Longbow, Hand Crossbow,
    Light Crossbow, Heavy Crossbow, Blowgun.
-   **Prohibited by default:** Trident, Maul, or metal-primary weapons.
-   **Exceptions:** The user may explicitly allow a particular
    construction or material combination.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-013.
-   **Source evidence:** Saved memory contains the explicit list.
-   **Confidence:** High.

### RULE-015 --- Clothing and capes are not armour by default

-   **Classification:** Explicit project intent / inferred
    implementation.
-   **Trigger:** Designing cloth or wool materials for robes, everyday
    garments, Monk gi, capes, and similar clothing.
-   **Required behaviour:** Create clothing and cape mechanics
    separately where requested. Effects should be appropriate to a
    non-armour garment and not assume the wearer is proficient in
    armour.
-   **Prohibited behaviour:** Quietly treating clothing as
    light/medium/heavy armour or copying armour-specific effects without
    justification.
-   **Exceptions:** If the user explicitly designs a cloth as armour,
    use the requested armour category.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-013, RULE-016.
-   **Source evidence:** User stated that Cloth/Wool is for clothing
    that does not count as armour, including wizard robes, Monk gi,
    capes, and clothing for classes without armour proficiencies.
-   **Confidence:** High.

### RULE-016 --- Distinguish clothing effects from cape effects

-   **Classification:** Explicit.
-   **Trigger:** A cloth material can be made into both clothing and a
    cape.
-   **Required behaviour:** Give each form its own mechanics and
    thematic role; do not merely duplicate the clothing effect list on
    the cape.
-   **Prohibited behaviour:** Reusing the same mobility feature on both
    forms without a deliberate reason.
-   **Exceptions:** A shared minor property may be appropriate if the
    user approves it.
-   **Priority:** Mandatory when both forms are requested.
-   **Dependencies:** RULE-015.
-   **Source evidence:** User explicitly said "Separate cape and
    clothing mechanics."
-   **Confidence:** High.

### RULE-017 --- Leather magic comes from processing, not a specific creature

-   **Classification:** Explicit.
-   **Trigger:** Writing lore or mechanics for leather/hide materials.
-   **Required behaviour:** Explain effects through tanning, treatment,
    reagents, ritual, magical exposure, or other crafting processes.
-   **Prohibited behaviour:** Requiring a specific creature's hide as
    the source of the leather's inherent magical properties.
-   **Exceptions:** A user-approved lore element may mention creature
    remnants as ingredients in a ritual, as in Elderbeast Hide, without
    making the hide itself the required source creature.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-018.
-   **Source evidence:** Saved memory explicitly states that leather
    effects come from the process rather than the creature that provided
    the hide.
-   **Confidence:** High.
-   **Example:** Dragonfire Leather reproduces draconic elemental
    lineages through magical treatment and does not require a particular
    dragon hide.

### RULE-018 --- Make rarity evident through worldbuilding

-   **Classification:** Explicit.
-   **Trigger:** Writing lore for a material.
-   **Required behaviour:** Use access, source, specialist skill, lost
    techniques, ritual requirements, merchant knowledge, or provenance
    to communicate rarity.
-   **Prohibited behaviour:** Explicitly saying in the lore prose that a
    material is rare/Very Rare/Legendary as the explanation for its
    rarity.
-   **Exceptions:** Rarity can appear in the heading/metadata.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-019, RULE-020.
-   **Source evidence:** Saved memory says lore should not explicitly
    state rarity; rarity should be evident from lore.
-   **Confidence:** High.

### RULE-019 --- Use rarity-specific lore logic

-   **Classification:** Explicit.
-   **Trigger:** Writing or reviewing lore.
-   **Required behaviour:** Use the following worldbuilding
    expectations:
    -   **Uncommon:** Known sources or repeatable methods; not
        commonplace, but reputable suppliers can often obtain it.
    -   **Rare:** Limited regional/national supply, exacting processing,
        or restricted access; large merchant groups may have stock at
        high cost.
    -   **Very Rare:** Few records and very few competent specialists;
        merchants may not seek it unless they have unusual contacts,
        though auctions or eccentric buyers are possible.
    -   **Legendary:** No reliable mundane method; may arise through
        divine favour, extraplanar origin, or an ancient lost ritual.
        Treat as a miracle rather than an ordinary commodity.
-   **Prohibited behaviour:** Treating Legendary as necessarily absent
    from the Material Plane; it may exist there, but not through
    reliable ordinary acquisition.
-   **Exceptions:** The user can set specific setting facts.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-018.
-   **Source evidence:** Saved rarity definitions and the final
    Legendary preface preserved in memory.
-   **Confidence:** High.

### RULE-020 --- Legendary lore should explain exceptional origin and inaccessible process

-   **Classification:** Explicit.
-   **Trigger:** Writing a Legendary material.
-   **Required behaviour:** Explain why ordinary production/acquisition
    fails. Divine favour, extraplanar origin, and lost rituals are
    established models.
-   **Prohibited behaviour:** Presenting it as a routinely purchasable
    resource without explicit setting justification.
-   **Exceptions:** A rare artifact may be discovered or a fragment
    granted in the story.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-018, RULE-019.
-   **Source evidence:** Saved final Legendary rarity preface.
-   **Confidence:** High.

### RULE-021 --- Use setting-ready lore and sourcebook structure

-   **Classification:** Inferred.
-   **Trigger:** Producing a material entry.
-   **Required behaviour:** Usually provide a material name, a thematic
    subtitle, evocative but practical lore, and clearly separated
    mechanics for each item form.
-   **Prohibited behaviour:** Mixing lore and rules so that the usable
    mechanics are hard to find.
-   **Exceptions:** If the user asks for mechanics only or lore only,
    provide only that.
-   **Priority:** Preferred.
-   **Dependencies:** RULE-022.
-   **Source evidence:** Repeated material entries and requests to
    display only certain sections.
-   **Confidence:** High.

### RULE-022 --- Use clean, copyable formatting

-   **Classification:** Inferred from repeated use.
-   **Trigger:** Presenting a finished material.
-   **Required behaviour:** Use Markdown headings, bold property names,
    bullets, short paragraphs, and tables only where they improve
    scanning. Make finished entries easy to paste into a sourcebook.
-   **Prohibited behaviour:** Adding long meta-commentary when the user
    asks for the material entry itself.
-   **Exceptions:** Audits and research reports should explain reasoning
    and sources.
-   **Priority:** Preferred.
-   **Dependencies:** RULE-021.
-   **Source evidence:** Repeated user requests for full effects,
    revisions, and "show only" sections.
-   **Confidence:** High.

### RULE-023 --- Preserve the current edited writing-block version

-   **Classification:** Explicit workflow requirement.
-   **Trigger:** The user asks to revise an existing writing artifact.
-   **Required behaviour:** Use the edited/current version, not an
    earlier assistant-authored version. Preserve its ID when revising
    the same block, if available.
-   **Prohibited behaviour:** Reverting user edits accidentally or
    reintroducing removed wording.
-   **Exceptions:** If the user explicitly asks to restore an earlier
    version, do so.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-001.
-   **Source evidence:** Explicit writing-block edit instructions in the
    conversation context.
-   **Confidence:** High.

### RULE-024 --- Respect user corrections and explicit reversals

-   **Classification:** Explicit.
-   **Trigger:** The user corrects a detail or cancels a proposed
    direction.
-   **Required behaviour:** Treat the correction/reversal as controlling
    going forward.
-   **Prohibited behaviour:** Continuing to apply a proposal that the
    user has withdrawn.
-   **Exceptions:** Ask if the correction is ambiguous or conflicts with
    another current explicit rule.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-001, RULE-008.
-   **Source evidence:** User cancelled the proposed property-selection
    rule; later corrected material rarities.
-   **Confidence:** High.

### RULE-025 --- Use current material names

-   **Classification:** Explicit.
-   **Trigger:** Naming or listing materials.
-   **Required behaviour:** Use current approved names. Known examples:
    Worldheart was renamed Gaiawood in one project context; Dreamwood
    was renamed Spiritbark; Starbloom was renamed Asterwood; Eclipsite
    was renamed Sablewood.
-   **Prohibited behaviour:** Presenting retired names as current
    entries.
-   **Exceptions:** Mention old names only when explaining a historical
    rename.
-   **Priority:** Mandatory.
-   **Dependencies:** RULE-001, RULE-024.
-   **Source evidence:** Saved memories and explicit correction.
-   **Confidence:** High.

### RULE-026 --- Balance by actual play impact, not by number of bullet points

-   **Classification:** Inferred.
-   **Trigger:** Reviewing an effect package.
-   **Required behaviour:** Evaluate the magnitude, reliability, action
    economy, number of targets, duration, save/DC, use frequency,
    stacking, and ability to bypass core limitations.
-   **Prohibited behaviour:** Assuming three modest effects are
    automatically stronger than one powerful effect, or that a
    limited-use effect is always safe.
-   **Exceptions:** User may intentionally want extreme Legendary
    effects.
-   **Priority:** Preferred.
-   **Dependencies:** RULE-009, RULE-010.
-   **Source evidence:** Balance audits of Stormwood, Soulweave,
    Asterwood, Lifewood, and Elderbeast Hide.
-   **Confidence:** High.

### RULE-027 --- Check official and third-party precedents when requested

-   **Classification:** Explicit.
-   **Trigger:** User asks to double-check or research against official
    D&D 5e sources or third-party works such as The Griffon's Saddlebag
    or Kibbles.
-   **Required behaviour:** Research relevant benchmarks; cite claims
    based on web sources; distinguish precedent from the user's own
    rules.
-   **Prohibited behaviour:** Claiming a mechanic is balanced solely
    because an item of the same rarity exists, without comparing scope
    and impact.
-   **Exceptions:** If the user says not to use outside sources, do not
    browse.
-   **Priority:** Mandatory when requested.
-   **Dependencies:** RULE-006, RULE-009.
-   **Source evidence:** User requested comparisons against official and
    third-party material.
-   **Confidence:** High.

### RULE-028 --- Prefer acid or necrotic over poison only when thematically suitable

-   **Classification:** Explicit preference with context dependency.
-   **Trigger:** A new damage type is being chosen.
-   **Required behaviour:** Consider acid or necrotic if they fit the
    material's concept.
-   **Prohibited behaviour:** Overriding a current approved poison
    mechanic without instruction.
-   **Exceptions:** Keep poison where it is integral to the design, such
    as an established poison/venom theme.
-   **Priority:** Preferred.
-   **Dependencies:** RULE-012.
-   **Source evidence:** Saved damage-type preference.
-   **Confidence:** High.

------------------------------------------------------------------------

## 4. Decision Logic

### 4.1 Choose the rarity

Inputs: - Source and availability. - Whether the material is naturally
occurring or created. - Whether production is known and repeatable. -
Required specialist knowledge, ritual, or planar access. - Merchant
access and surviving records.

``` text
IF ordinary specialists know how to obtain and work it, and supply is limited but established:
    consider Uncommon
ELSE IF access is geographically or commercially limited, or processing needs specialists:
    consider Rare
ELSE IF few records survive and only a handful of specialists can produce/work it:
    consider Very Rare
ELSE IF no reliable mundane method exists and origin depends on divine favour,
        extraplanar origin, or a lost ritual:
    consider Legendary
```

This is a guideline, not a purely mechanical lookup. Use explicit
user-approved rarity first (RULE-001, RULE-002).

### 4.2 Choose the crafting modifier

Inputs: - Complexity of preparation and processing. - Risk of failure or
hazards. - Need for specialist tools or controlled environments. -
Availability of a reliable technique. - Whether the method is guarded,
obscure, or lost.

  Rarity        Allowed modifier
  ----------- ------------------
  Uncommon              +2 to +7
  Rare                  +5 to +7
  Very Rare             +7 to +9
  Legendary        +10 or higher

``` text
1. Determine the material's rarity using current canon.
2. Identify the actual difficult steps in its processing.
3. Determine whether those steps are routine, specialist, unstable, hazardous, or lost.
4. Choose a modifier within that rarity's permitted band.
5. Explain the modifier through the crafting lore when useful.
6. Do not increase the modifier merely because the finished item's damage is high.
```

If two rarity bands overlap at +5 or +7, the modifier alone does not
identify the rarity. Rarity is separately assigned.

### 4.3 Select mechanical properties

``` text
IF the material is Uncommon:
    normally choose one strong defining property
    OR two closely related minor properties
    keep the identity focused
ELSE IF Rare:
    allow more depth and multiple complementary properties
    assess each effect and the complete package
ELSE IF Very Rare:
    allow powerful and versatile packages
    test interactions, action economy, and use frequency
ELSE IF Legendary:
    allow extraordinary and potentially transformational effects
    check whether the power is intentionally campaign-defining
```

Do **not** apply a property-selection cap such as "one effect at
Uncommon, two at Rare" unless the user explicitly reinstates it
(RULE-008).

### 4.4 Choose object form and mechanic category

  -----------------------------------------------------------------------
  Material/object form                Design approach
  ----------------------------------- -----------------------------------
  Primarily wooden weapon             Apply wood weapon rules only to
                                      approved primarily wooden weapon
                                      types (RULE-014)

  Staff/rod/wand/focus                Give focus-specific properties;
                                      separate them from weapon effects
                                      (RULE-013)

  Metal weapon or armour              Match effects to metal's central
                                      identity and the item's function

  Leather/hide armour                 Use light/medium armour subsections
                                      only where requested; source magic
                                      from the preparation process
                                      (RULE-017)

  Non-armour clothing                 Do not treat as armour; effects
                                      should support garments and the
                                      wearer (RULE-015)

  Cape                                Give a distinct effect profile from
                                      clothing (RULE-016)
  -----------------------------------------------------------------------

### 4.5 Choose a damage type

``` text
IF a damage type is already part of the material's approved identity:
    preserve it
ELSE:
    choose the most thematically appropriate type
    consider acid or necrotic rather than poison when either fits
    do not use poison merely by default
```

### 4.6 Balance an effect

For each property, ask: 1. What action or reaction does it consume? 2.
Is it passive, always available, or limited-use? 3. How many times can
it be used, and when does it recharge? 4. What damage/healing/control
does it provide? 5. Does it bypass a normal limitation, such as cover,
concentration, armour requirements, or forced movement? 6. Does it stack
with other material properties or official magic items? 7. Is the effect
too broad for the material's rarity? 8. Does it communicate the
material's identity?

Then assess the complete item, not just each property in isolation.

### 4.7 Resolve conflicting instructions

Precedence order: 1. Latest direct user correction or explicit
instruction. 2. Current edited version of the relevant writing block. 3.
Explicit saved preference/rule. 4. Previously approved material entry.
5. Inferred design pattern. 6. General D&D conventions or external
precedents.

If two current explicit instructions conflict and neither clearly
supersedes the other, ask for clarification rather than silently
choosing.

------------------------------------------------------------------------

## 5. Material Creation Workflows

### 5.1 End-to-end workflow

1.  **Interpret the request.** Determine whether the user wants a new
    material, lore, mechanics, a balance audit, a rarity/modifier
    assignment, or a revision.
2.  **Retrieve current canon.** Check current name, rarity, previous
    effects, user edits, and applicable saved preferences. If a previous
    file or artifact is referenced and unavailable in the immediate
    context, search available files rather than guessing.
3.  **Identify object forms.** Determine whether the material is for
    weapons, armour, staffs/foci, clothing, capes, or several forms.
4.  **Establish theme.** Identify one central fantasy concept (e.g.,
    lightness, storms, dreams, concealment, vitality, time).
5.  **Write lore.** Explain appearance, origin, magical behaviour,
    production, access, and crafting knowledge. Let the lore imply
    rarity (RULE-018, RULE-019).
6.  **Assign rarity.** Use current canon and rarity criteria (RULE-002,
    RULE-019).
7.  **Assign crafting modifier.** Use the user's permitted band and
    actual process difficulty (RULE-003 through RULE-006).
8.  **Design properties.** Keep Uncommon focused; allow appropriately
    broader effects at higher tiers. Separate mechanics by item form.
9.  **Balance.** Check damage, action economy, save DCs, duration, uses,
    reactions, condition strength, defensive breadth, and interactions.
10. **Validate conventions.** Check once-per-turn wording, damage-type
    preference, weapon applicability, and object form.
11. **Present.** Use sourcebook-ready Markdown with clear headings and
    separated mechanics.
12. **Iterate.** Apply the user's corrections exactly, preserving the
    edited state and avoiding unrelated changes.

### 5.2 Workflow diagram

``` mermaid
flowchart TD
    A[Interpret request] --> B[Retrieve current material canon]
    B --> C{New material or revision?}
    C -->|New| D[Establish theme and object forms]
    C -->|Revision| E[Load latest edited version]
    D --> F[Write lore and production logic]
    E --> G[Apply requested changes only]
    F --> H[Assign rarity]
    G --> I[Check current rules and constraints]
    H --> J[Assign crafting modifier within rarity band]
    I --> K[Design or revise mechanics]
    J --> K
    K --> L[Balance and consistency audit]
    L --> M{Compliant?}
    M -->|No| N[Revise or ask clarification]
    N --> L
    M -->|Yes| O[Produce copyable final entry]
```

### 5.3 Revision workflow

When the user asks to revise a current material: - Start from the latest
edited text. - Change only the requested portions unless the user asks
for a full rebalance. - Preserve approved names, rarity, lore facts, and
unaffected mechanics. - If a requested change has consequences for
balance or consistency, explain them briefly when appropriate. - If the
user says "show only" a section, do not add unrelated commentary. - If
the user cancels a proposed direction, stop applying it.

### 5.4 Audit workflow

For a whole-catalogue audit: 1. List the current materials and their
assigned rarities. 2. Verify names and replacements. 3. Review modifiers
against the appropriate range. 4. Assess whether each modifier matches
process difficulty. 5. Review each material's mechanical identity and
package. 6. Flag issues separately from confirmed corrections. 7. Do not
present guesses as historical facts. 8. Provide corrected tables and
clearly state unresolved items.

------------------------------------------------------------------------

## 6. Formatting and Content Standards

### 6.1 Standard material entry

A typical entry should include:

``` markdown
## Material Name

*Rarity Magical Material — Theme / Theme*

Lore paragraphs describing:
- Appearance and physical behaviour
- Magical properties
- Origin or creation process
- Availability and specialist knowledge
- Common uses and reputation

### Weapon — Property Name

Rules text.

### Armour — Property Name

Rules text.

### Staff / Rod / Focus — Property Name

Rules text.
```

Only include object forms that make sense for the material. Clothing
materials may use:

``` markdown
### Clothing — Property Name
...

### Cape — Property Name
...
```

### 6.2 Lore style

-   Evocative but functional; suitable for a setting guide or
    sourcebook.
-   Explain what the material looks and feels like, how it behaves, and
    how it is obtained or produced.
-   Tie the mechanics to lore.
-   Prefer concrete process details over vague statements that the
    material is "magical."
-   Communicate rarity through access and craft knowledge rather than
    stating rarity in prose.
-   Avoid repeating the same lore principle mechanically in every entry
    unless it matters to that material.

### 6.3 Mechanics style

-   Use named properties and concise rules text.
-   State action type, range, duration, target, save, damage, condition,
    use limit, and recharge where relevant.
-   Use D&D terminology consistently: action, bonus action, reaction,
    Short Rest, Long Rest, Concentration, advantage/disadvantage,
    proficiency bonus.
-   Distinguish "until the start of your next turn," "until the end of
    your next turn," and other durations carefully.
-   Clarify what happens on a successful save.
-   Avoid vague wording such as "cannot be moved" unless the scope is
    defined.
-   Avoid adding a spellcasting-focus property automatically.
-   Use tables for genuinely comparative options, not for every effect.

### 6.4 Rarity heading and crafting metadata

The heading may identify rarity,
e.g. `*Rare Magical Wood — Storm / Lightning*`. Lore prose should not
simply state "this is rare." A separate metadata line may include:

-   **Crafting Modifier:** +X

The modifier should be shown only when it has been assigned or
requested; do not invent one if uncertain.

### 6.5 Writing blocks and copyability

For finished material entries, use a reusable writing block where the
interface supports it. When revising an existing writing block, preserve
its identifier if available and refer to the user's edited state. Do not
include analysis inside the copyable artifact unless requested.

------------------------------------------------------------------------

## 7. Quality Assurance

### 7.1 Pre-delivery checklist

**Canon** - \[ \] Current material name used. - \[ \] Correct rarity
used. - \[ \] No retired name accidentally presented as current. - \[ \]
Latest user-edited text preserved.

**Lore** - \[ \] Origin/process is coherent. - \[ \] Appearance and
behaviour are concrete. - \[ \] Rarity is implied through
worldbuilding. - \[ \] Leather magic comes from processing, not a
required source creature. - \[ \] Lore and mechanics reinforce the same
identity.

**Crafting** - \[ \] Modifier falls inside the user's rarity band. - \[
\] Modifier reflects the process difficulty rather than damage power
alone. - \[ \] Published Kibbles benchmarks are used as context, not as
a replacement for the user's system. - \[ \] Unverified modifier
assignments are marked provisional.

**Mechanics** - \[ \] Effect package fits the material's rarity. - \[ \]
Uncommon material remains focused. - \[ \] The Uncommon guideline has
not been mistakenly applied to higher tiers. - \[ \] No unapproved
choose-one/choose-two property-selection rule is added. - \[ \]
Weapon/focus/armour/clothing/cape effects are correctly separated. - \[
\] Wood weapon applicability follows the approved list. - \[ \]
Once-per-turn effects use the preferred Proficiency Bonus/Long Rest
convention, unless a specific override exists. - \[ \] Damage type
follows the approved theme and poison preference. - \[ \] Uses, actions,
ranges, durations, saves, and recharge are explicit. - \[ \] Conditions
and defensive effects have been checked for excessive power.

**Presentation** - \[ \] Clean headings and bold property names. - \[ \]
Rules are copyable and unambiguous. - \[ \] No unnecessary
meta-commentary when the user asked for an entry only. - \[ \] Citations
are provided when external sources were used.

### 7.2 Common failure modes

1.  **Rarity drift:** Assigning a material the wrong tier from memory or
    a prior mistaken answer.
2.  **Stale versions:** Reusing text from before the user's edits.
3.  **Modifier by rarity alone:** Assigning every Rare material +6
    without assessing process difficulty.
4.  **Material becomes magic item:** Combining too many unrelated
    effects, particularly at Uncommon.
5.  **Overgeneralising Uncommon simplicity:** Applying its
    focused-design guideline to Rare and above.
6.  **Reviving cancelled rule:** Applying the withdrawn
    choose-one/choose-two property-selection system.
7.  **Wrong object form:** Giving clothing armour-like benefits or
    copying weapon effects onto a focus.
8.  **Overpowered control:** Underestimating the impact of stun,
    restraint, denial of healing, or repeated disadvantage.
9.  **Damage-type mismatch:** Choosing poison by default despite the
    user's preference for acid/necrotic where appropriate.
10. **False certainty about sources:** Claiming all past conversations
    were examined when only summaries and surfaced context were
    available.
11. **Silent contradiction resolution:** Choosing between conflicting
    instructions without noting the conflict.

### 7.3 Acceptance criteria

A material is ready for presentation when: - its identity is distinct; -
its name and rarity match current canon; - its lore explains origin,
behaviour, and working difficulty; - its crafting modifier is within the
correct band and has a defensible rationale; - its mechanics match the
intended object form and rarity; - no active rule has been violated; -
unresolved balance choices are clearly identified rather than hidden.

------------------------------------------------------------------------

## 8. Conflicts and Rule Precedence

### 8.1 Precedence hierarchy

1.  **Latest explicit user correction or instruction.**
2.  **Latest user-edited writing block or approved final version.**
3.  **Explicit saved system preferences.**
4.  **Previously approved material entry.**
5.  **Inferred design pattern.**
6.  **Official 5e or third-party precedents.**
7.  **Assistant-generated suggestion that has not been approved.**

External rules are benchmarks unless the user specifically asks to use
them as the governing system.

### 8.2 Known changes and superseded directions

  -----------------------------------------------------------------------
  Topic                   Earlier direction       Current controlling
                                                  rule
  ----------------------- ----------------------- -----------------------
  Property selection by   Proposed: Uncommon      **Withdrawn.** Do not
  rarity                  chooses one property;   apply unless
                          Rare chooses up to two  reinstated.

  Uncommon simplicity     Not always articulated  Generally one strong
                          in early designs        property or two related
                                                  minor properties;
                                                  applies only to
                                                  Uncommon.

  Fireglass               Previously mislabelled  **Uncommon**.
                          Rare in an assistant    
                          response                

  Skysteel                Previously mislabelled  **Uncommon**.
                          Rare in an assistant    
                          response                

  Angelforged Leather     Previously mislabelled  **Rare**.
                          Very Rare               

  Gravemantle             Previously mislabelled  **Rare**.
                          Very Rare               

  Abyssal Hide            Previously mislabelled  **Rare**.
                          Very Rare               

  Radiatite               Previously mislabelled  **Very Rare**.
                          Rare                    

  Chromatite              Previously mislabelled  **Very Rare**.
                          Rare                    

  Nanom                   Previously mislabelled  **Very Rare**.
                          Rare                    

  Poison damage           Earlier entries         Prefer acid/necrotic
                          sometimes used poison   where thematically
                                                  appropriate; preserve
                                                  explicit approved
                                                  mechanics unless asked
                                                  to revise.

  Once-per-turn mechanics Earlier drafts used     Use up to Proficiency
                          unrestricted "once per  Bonus times per Long
                          turn"                   Rest, unless a specific
                                                  current exception
                                                  applies.

  Leather source          Could be read as        Leather magic comes
                          creature-dependent      from the process;
                                                  source hide need not be
                                                  a magical creature.
  -----------------------------------------------------------------------

### 8.3 Unresolved or potentially conflicting points

-   **Leather crafting data:** `Hides-and-leather.md` has no difficulty
    modifiers or gold costs. Do not invent them; ask the user.
-   **Leather rarity gaps:** Starlight Leather, Soulweave, and Elderbeast
    Hide have no rarity in the handout.
-   **Nanom modifier:** The handout gives +5, below the Very Rare band
    (+7 to +9). Ask whether the value or the band is correct.
-   **Once-per-turn wording:** Several handout effects still use "once
    per turn" or "up to 3 times per Long Rest" (e.g. Abyssal Power,
    Emberstrike, Stored Strength), which conflicts with RULE-011. Treat
    the handout wording as current unless the user asks for a revision.
-   **Stormwood stun:** Flagged under RULE-010 as strong for Rare; the
    handout still uses stun. Do not change it without instruction.
-   **Asterwood, Lifewood, and Elderbeast Hide:** Current effects are
    intentionally powerful and have previously been flagged for possible
    balance review. Do not silently nerf them; ask whether the user
    wants a balance revision.

### 8.4 How to resolve uncertainty

``` text
IF an explicit current correction exists:
    apply it
ELSE IF the latest edited writing block is available:
    use that version
ELSE IF saved memory records an explicit rule:
    apply it within its scope
ELSE IF only an assistant proposal is visible:
    treat it as provisional
ELSE:
    ask the user or mark the fact as unknown
```

------------------------------------------------------------------------

## 9. Worked Examples

### Example A --- Create an Uncommon cloth

**Input request:** "Create an Uncommon cloth that helps spellcasters."

**Context/assumptions:** Cloth is for non-armour clothing and possibly a
cape. Uncommon should have a focused identity. No cloth materials exist
in the current canon yet.

**Applicable rules:** RULE-007, RULE-013, RULE-015, RULE-016, RULE-018,
RULE-021.

**Decision process:** 1. Check the existing material list for
overlapping themes. 2. Choose a distinct spellcasting niche. 3. Write
lore showing a known, repeatable textile process. 4. Keep the Uncommon
mechanic focused.

**Expected output:** A compact, sourcebook-ready entry with clearly
separated clothing/cape mechanics if both forms are requested.

**Validation:** It is not armour; it does not receive an unnecessary
focus property; its power is focused; it does not reuse a retired
selection rule.

### Example B --- Assign a modifier to Adamantine

**Input request:** "What crafting modifier should Adamantine have?"

**Applicable rules:** RULE-002 through RULE-006.

**Decision process:** 1. Confirm it is Uncommon in the user's custom
catalogue. 2. Allowed band is +2 to +7. 3. Consider the difficulty of
smelting, alloying, and forging it, not just the weapon's finished
strength. 4. The previously suggested +7 is a plausible high-end
proposal because processing is difficult, but do not call it an
immutable approved number unless the user confirmed it.

**Expected output:** A modifier within +2 to +7 with a concise
process-based rationale and clear indication if the value is a
recommendation.

### Example C --- Design a Rare elemental metal

**Input request:** "Create a Rare metal tied to storms."

**Applicable rules:** RULE-002 through RULE-006, RULE-009 through
RULE-012, RULE-021.

**Decision process:** 1. Check whether Covolt or Stormwood already
covers the theme. 2. Avoid duplication or explain the distinct niche. 3.
Rare permits more mechanical depth than Uncommon. 4. Choose a modifier
from +5 to +7 based on how the material is processed. 5. If a weapon
rider says "once per turn," convert it to the preferred PB uses per Long
Rest convention unless the user explicitly specifies another use limit.
6. If the effect is a stun, evaluate whether a weaker control effect
better fits the tier.

**Expected output:** Distinct lore, a coherent weapon/armour or focus
package, modifier rationale, and clearly specified use limits.

### Example D --- Write Legendary lore

**Input request:** "Write lore for a Legendary material tied to time."

**Applicable rules:** RULE-018 through RULE-020, RULE-021.

**Decision process:** 1. Use an exceptional origin such as divine
favour, extraplanar source, or lost ritual. 2. Explain why ordinary
acquisition or reproduction is unreliable. 3. Make the lore communicate
rarity through history, access, and specialist knowledge, not by simply
stating it is Legendary. 4. The modifier must be +10 or higher; choose
the exact number from process difficulty. 5. Do not assume the material
is absent from the Material Plane.

**Expected output:** Setting-ready lore with a clear provenance,
distinctive physical appearance, and a credible explanation for why
current craftspeople cannot reproduce it.

### Example E --- Revise an edited material

**Input request:** "Change the Aquarius weapon effect, but leave the
rest alone."

**Applicable rules:** RULE-001, RULE-023, RULE-024.

**Decision process:** 1. Load the most recent user-edited Asterwood
entry. 2. Change only Aquarius's weapon effect. 3. Preserve its
Legendary classification, +3 enhancement, other constellations, and dawn
rules. 4. Do not revive older versions of Aquarius or rewrite unrelated
sections.

**Expected output:** The updated entry or requested section with the
exact change applied and no accidental regression.

------------------------------------------------------------------------

## 10. Known Materials and Modifier Working Register

Values below are copied from the authoritative handouts (Section 1.6).
"—" means the handout does not give a value.

| Material | Rarity | Modifier | Gold cost |
| --- | --- | --- | --- |
| Darkwood (Zalantar) | Uncommon | +3 | 25 GP / branch |
| Ironwood | Uncommon | +5 | 25 GP / branch |
| Cryptomeria | Uncommon | +4 | 25 GP / branch |
| Mithril | Uncommon | +5 | 30 GP / ingot |
| Adamantine | Uncommon | +7 | 60 GP / ingot |
| Black Iron | Uncommon | +2 | 40 GP / ingot |
| Shadowhide | Uncommon | — | — |
| Skysteel | Uncommon | — | — |
| Fireglass | Uncommon | — | — |
| Tidehide | Uncommon | — | — |
| Phoenix Ashwood | Rare | +6 | 80 GP / branch |
| Moonroot | Rare | +6 | 80 GP / branch |
| Worldroot | Rare | +5 | 80 GP / branch |
| Stormwood | Rare | +7 | 80 GP / branch |
| Mizzium | Rare | +7 | 80 GP / ingot |
| Covolt | Rare | +6 | 200 GP / ingot |
| Frostfell Alloy | Rare | +6 | 200 GP / ingot |
| Gloomsteel | Rare | +6 | 200 GP / ingot |
| Glintsteel | Rare | +6 | 200 GP / ingot |
| Nimbusium | Rare | +6 | 200 GP / ingot |
| Voidleather | Rare | — | — |
| Angelforged Leather | Rare | — | — |
| Gravemantle | Rare | — | — |
| Abyssal Hide | Rare | — | — |
| Spirit Bark | Very Rare | +8 | 800 GP / branch |
| Gaiawood | Very Rare | +8 | 800 GP / branch |
| Sablewood | Very Rare | +9 | 800 GP / branch |
| Chromatite | Very Rare | +7 | 1500 GP / ingot |
| Radiatite | Very Rare | +8 | 1500 GP / ingot |
| Nanom | Very Rare | +5 (below band) | 1500 GP / ingot |
| Formsteel | Very Rare | +8 | 1500 GP / ingot |
| Aetherium | Very Rare | +9 | 1800 GP / ingot |
| Dragonfire Leather | Very Rare | — | — |
| Lignum Vitae / Lifewood | Legendary | +10 | 3000 GP / branch |
| Asterwood | Legendary | +10 | 3000 GP / branch |
| Chronocalcite / Tempus Steel | Legendary | +10 | 5000 GP / ingot |
| Metoricite / Astral Iron | Legendary | +10 | 5000 GP / ingot |
| Fateskin | Legendary | — | — |
| Starlight Leather | — | — | — |
| Soulweave | — | — | — |
| Elderbeast Hide | — | — | — |

Gold costs are not governed by an explicit rule; the handouts follow
the pattern Uncommon 25–60 GP, Rare 80–200 GP, Very Rare 800–1800 GP,
Legendary 3000–5000 GP.

------------------------------------------------------------------------

## 11. Unknowns and Knowledge Gaps

1.  **Full historical transcript:** Not all prior conversations are
    accessible. This document cannot guarantee that every past decision
    has been captured.
2.  **Exact Kibbles edition and rule implementation:** Prior context
    refers to Kibbles' Crafting Guide / Compendium of Craft and Creation
    and later Modular Crafting material. The user's chosen modifier
    bands are custom and take precedence.
3.  **Leather crafting data:** Difficulty modifiers, gold costs, and
    three rarities are missing from `Hides-and-leather.md`.
4.  **Balance target for Legendary:** The user allows extraordinary
    effects; the precise intended upper bound for artifact-level effects
    is not formally specified.
5.  **Stacking rules:** It is not established whether two materials'
    effects can be combined in one item, or how that interacts with
    magical enhancement bonuses. Ask rather than assume when relevant.
6.  **Crafting check formula:** The user's modifier bands are known, but
    this document does not define how the modifier combines with DCs,
    proficiency, tools, or other elements of Kibbles' system. Do not
    invent a replacement formula.
7.  **Use limits:** The PB-times-per-Long-Rest preference applies to
    effects worded "once per turn," but specific entries may have
    explicit current exceptions. Inspect the current approved entry
    before changing wording.

### Recommended next step

Before using the register as a final crafting reference, fill in the
missing leather values and resolve the open points in Section 8.3 with
the user.

------------------------------------------------------------------------

## Appendix A --- Compact operational checklist for an AI agent

Before returning a material entry, ask internally:

1.  What is the user actually asking for: lore, mechanics, modifier,
    audit, or revision?
2.  What is the current name and rarity?
3.  Which version is most recent?
4.  What is the material's single clearest identity?
5.  Which object form is being designed?
6.  What does its lore say about source, processing, and access?
7.  Which rarity-specific design guidance applies?
8.  What is the permitted crafting modifier band?
9.  Does the proposed modifier reflect processing difficulty?
10. Do the effects use correct actions, ranges, DCs, durations, and
    recharge?
11. Does "once per turn" need the PB/LR convention?
12. Is poison the best damage type, or would acid/necrotic fit better?
13. Are effects distinct from other materials?
14. Have I preserved all unaffected approved text?
15. Have I marked assumptions or unresolved facts instead of pretending
    they are known?

If any essential input is missing, ask a concise clarification rather
than silently inventing the answer.
