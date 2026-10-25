# Safe Pilot — Telegram user-flow map

This is the editable, code-aligned map of every pilot-facing question, button, branch, and result path in the Safe Pilot Telegram bot.

**Baseline:** commit `89bf658` plus the 2026-10-25 flow-audit fixes (see Changelog). Supersedes the older flow document; earlier history is in git.
**Notation:** rectangles are bot screens/questions; diamonds are decisions; arrow labels are the pilot’s answer or button. Every Mermaid diagram can be edited directly in Markdown and rendered by GitHub, GitLab, VS Code extensions, or Mermaid Live.

## Flow index

| Flow | Entry | Purpose |
|---|---|---|
| Main navigation | `/start`, `/menu` | Reaches calculations, aircraft actions, history, and help |
| Aircraft profile | **Aircraft → Add Aircraft** | Creates a reusable aircraft profile |
| Aircraft update | **Aircraft → Edit Aircraft** | Loads an existing profile and saves a new revision |
| Quick calculation | **Calculate → Takeoff (Quick)** | Fast takeoff check with combined loads and total fuel |
| Advanced calculation | **Calculate → Takeoff + Landing (Advanced)** | Per-station / per-tank calculation, including landing |
| Supporting actions | Aircraft / More menus | Select, archive, view profile, history, help |

## Shared interaction rules

- **Cancel:** inline `✖ Cancel` clears the active wizard and returns to the main menu. The command `/cancel` does the same.
- **Back:** returns to the prior question when that screen has history. For repeated station/tank questions, it returns to the exact prior item.
- **Invalid input:** the bot shows an error and remains on the same question; no partial profile or calculation is saved.
- **Units:** weights are lb, arms/CG are inches, moments are lb-in, and fuel is US gal.
- **Save point:** profile data is only persisted after **✅ Confirm**. Calculations are persisted immediately after their last answer; there is no separate confirmation screen in either calculation flow.

---

## 1. Main navigation

```mermaid
flowchart TD
    Start["/start"] --> Active{"Active aircraft selected?"}
    Active -- "Yes" --> Card["Aircraft card<br/>Calculate · Change Aircraft"]
    Active -- "No" --> Home["Main menu"]
    Card --> Home

    Home --> Calc["🧮 Calculate"]
    Home --> Aircraft["🛩 Aircraft"]
    Home --> More["⚙️ More"]

    Aircraft --> Select["🔁 Change Aircraft"]
    Aircraft --> Add["➕ Add Aircraft"]
    Aircraft --> Edit["⚙️ Edit Aircraft"]
    Aircraft --> Archive["🗑 Archive Aircraft"]
    Aircraft --> List["📋 My Aircrafts"]
    Aircraft --> Data["📄 View Profile"]

    More --> History["Calculation History"]
    More --> Help["Help"]

    Select --> Selected["Set active aircraft<br/>→ Main menu"]
    Add --> ProfileFlow["Aircraft profile flow"]
    Edit --> UpdateFlow["Aircraft update flow"]
    Archive --> Archived["Archive profile<br/>→ Main menu"]
    List --> ListResult["List profiles<br/>active one marked ⭐"]
    Data --> DataResult["Show current saved profile summary"]
    Calc --> Mode["Choose calculation type"]
    History --> HistoryResult["Show last 10 calculation summaries"]
    Help --> HelpResult["Show bot usage and safety note"]
```

The aircraft card is only shown on `/start` when a selected aircraft exists. Its **Calculate** button opens the same calculation-type chooser; **Change Aircraft** opens the aircraft picker.

---

## 2. Aircraft profile: Add Aircraft

The new-profile wizard collects only the data used to calculate weight, moment, and CG. Aircraft becomes the active aircraft only after its profile is confirmed and saved.

```mermaid
flowchart TD
    Start(["Aircraft → Add Aircraft"]) --> Tail["Tail number<br/>required text · uppercased · max 16 characters"]
    Tail --> Nick["Nickname<br/>optional text · max 64 characters"]
    Nick -- "text" --> EmptyWeight
    Nick -- "Skip or blank" --> EmptyWeight

    EmptyWeight["Basic empty weight, lb<br/>required number > 0"] --> EmptyRecord{"Which value is known?"}
    EmptyRecord -- "I know the empty CG" --> EmptyCG["Basic empty CG, in<br/>finite number; negative allowed"]
    EmptyRecord -- "I know the empty moment" --> EmptyMoment["Basic empty moment, lb-in<br/>finite number; negative allowed"]
    EmptyCG --> DerivedMoment["Store entered CG and derive moment"]
    EmptyMoment --> DerivedCG["Store entered moment and derive CG"]
    DerivedMoment --> Ramp
    DerivedCG --> Ramp

    Ramp["Max ramp weight, lb<br/>optional non-negative number"] --> Takeoff["Max takeoff weight, lb<br/>required number > 0"]
    Ramp -- "Skip" --> Takeoff
    Takeoff -- "below saved ramp or other invalid input" --> Takeoff
    Takeoff -- "valid" --> Landing["Max landing weight, lb<br/>optional non-negative number"]
    Landing -- "value or Skip" --> StationHub["Configure stations"]

    StationHub --> Envelope["Configure CG envelope"]
    Envelope --> Review["Review full profile"]
    Review -- "✅ Confirm and domain validation passes" --> Saved(["Aircraft saved<br/>becomes active → Main menu"])
    Review -- "validation fails" --> Review
```

Additional save-time validation protects the profile even when individual fields were valid: takeoff/ramp/landing limits cannot be below basic empty weight; ramp cannot be below takeoff; fuel stations need a positive capacity and density; and a completed CG envelope must be valid.

### 2.1 Station configuration loop

```mermaid
flowchart TD
    Hub["Add a station?<br/>Add another station · Done<br/>Edit/Remove appear after first station"] --> HubChoice{"Pilot action"}

    HubChoice -- "Add another station" --> Type["Station type<br/>Front Seats · Rear Seats · Baggage Area<br/>Custom Station · Fuel Tank"]
    Type -- "Done, when ≥1 station exists" --> Recap
    Type -- "type selected" --> Name["Station name<br/>typed or suggested default<br/>required · max 64 characters"]
    Name --> Arm["ARM, in<br/>finite number; negative allowed"]
    Arm --> FuelType{"Fuel Tank?"}
    FuelType -- "No" --> AddComplete["Add station to unsaved profile"]
    FuelType -- "Yes" --> Capacity["Maximum usable fuel capacity, US gal<br/>required number > 0"]
    Capacity --> Density["Attach configured default fuel density<br/>not asked to pilot"]
    Density --> AddComplete
    AddComplete --> Hub

    HubChoice -- "Remove a station" --> RemovePick["Pick station"] --> Remove["Remove from unsaved profile"] --> Hub
    HubChoice -- "Edit a station" --> EditPick["Pick station"] --> EditDetail["Edit station details<br/>see section 2.2"] --> Hub
    HubChoice -- "Done" --> Recap["If tanks exist: show combined usable capacity"]
    Recap --> EnvelopeEntry(["Continue to CG envelope"])
```

Important rules:

- A non-fuel station whose name contains a standalone word **fuel**, **tank**, or **tanks** is rejected. The pilot must use the **Fuel Tank** type.
- Fuel capacity is stored in gallons; its density comes from `DEFAULT_FUEL_DENSITY_LB_PER_GAL` (default: 6.0 for 100LL).
- Stations are still editable/removable until the final profile confirmation. Finalizing a station returns to the hub; it does not save the aircraft yet.
- The station hub offers **Back** (when the wizard has history) and **✖ Cancel**, like every other step.

### 2.2 Edit a station

```mermaid
flowchart TD
    Pick["Choose a configured station"] --> Arm["ARM, in<br/>type a replacement or Keep Current"]
    Arm --> Action{"Optional actions"}

    Action -- "Rename" --> Name["New station name<br/>type replacement or Keep Current"]
    Name --> Arm
    Action -- "Change type" --> Type["Pick new type"]
    Type -- "Change to Fuel Tank" --> Arm
    Type -- "Change away from Fuel Tank" --> NameCheck{"Existing name looks like fuel/tank?"}
    NameCheck -- "Yes" --> Block["Reject type change<br/>rename first"]
    Block --> Arm
    NameCheck -- "No" --> Arm

    Action -- "type ARM" --> Fuel{"Current type is Fuel Tank?"}
    Action -- "Keep Current ARM" --> Fuel
    Fuel -- "Yes" --> Capacity["Usable capacity, US gal<br/>type replacement or Keep Current"]
    Fuel -- "No" --> Done(["Return to station hub"])
    Capacity --> Done
```

Changing to **Fuel Tank** clears any old capacity and then requires a new positive capacity. Changing away from **Fuel Tank** clears the capacity and density. A fuel-like station name blocks a change away from Fuel Tank.

### 2.3 CG-envelope entry

```mermaid
flowchart TD
    Start["CG envelope<br/>enter: weight, forward limit, aft limit"] --> Row["Typed row<br/>three finite numbers"]
    Row --> Rows["Show entered rows"]
    Rows --> Choice{"Pilot action"}
    Choice -- "Enter another row" --> Row
    Choice -- "✏️ Edit a row" --> EditPick["Pick a row"] --> Edit["Enter replacement row"] --> Rows
    Choice -- "🗑 Remove a row" --> RemovePick["Pick a row"] --> Remove["Remove row"] --> Rows
    Choice -- "⚠️ Skip<br/>only when no rows exist" --> Skip["No envelope saved<br/>CG will not be evaluated"] --> Review
    Choice -- "✅ Done" --> Validate{"At least 2 rows,<br/>strictly increasing weight,<br/>weight > 0, forward ≤ aft?"}
    Validate -- "No" --> Rows
    Validate -- "Yes" --> Review(["Profile review"])
```

The pilot may skip the envelope deliberately. In that case, calculation results evaluate saved weight limits but clearly mark CG as **not evaluated**.

---

## 3. Aircraft update: Edit Aircraft

**Aircraft → Edit Aircraft** first asks the pilot to choose a saved aircraft. The current revision is loaded into the same profile wizard used for creation. The pilot may change values, maintain its station/envelope setup, or use the current values where that control is supported. Confirming creates a **new revision**, so prior calculation records still refer to the previous profile revision.

```mermaid
flowchart TD
    Start(["Aircraft → Edit Aircraft"]) --> Pick["Pick aircraft"]
    Pick --> Load["Load active revision into wizard"]
    Load --> Tail["Tail number<br/>type replacement or Keep Current"]
    Tail --> Nick["Nickname<br/>type value or skip to clear"]
    Nick --> Reuse["Continue through the Add Aircraft questions,<br/>with saved values/stations/envelope preloaded"]
    Reuse --> Review["Review revised profile"]
    Review -- "✅ Confirm" --> Revision(["Save new aircraft revision"])
```

In edit mode the nickname screen offers **✅ Keep Current** (keeps the saved nickname) and **Skip** (clears it).

---

## 4. Calculation-type choice

```mermaid
flowchart TD
    Start(["🧮 Calculate"]) --> Mode{"Choose calculation type"}
    Mode -- "Takeoff (Quick)" --> Quick["Quick calculation flow"]
    Mode -- "Takeoff + Landing (Advanced)" --> Advanced["Advanced calculation flow"]
    Mode -- "✖ Cancel" --> Menu(["Main menu"])
```

Before either flow starts, the bot uses the selected aircraft if one exists; otherwise, it asks the pilot to pick an aircraft. If none exists, it asks the pilot to add an aircraft instead.

---

## 5. Takeoff: Quick calculation

Quick calculation can only represent a profile with at most one Front Seats station, one Rear Seats station, one Baggage station, any number of Fuel Tanks, and no Custom / legacy Passenger stations. If the profile does not meet that condition, the bot explains why and offers **Advanced/Landing** instead.

```mermaid
flowchart TD
    Start(["Takeoff (Quick)"]) --> Aircraft{"Selected aircraft exists?"}
    Aircraft -- "No" --> Pick["Pick aircraft"]
    Aircraft -- "Yes" --> Profile
    Pick --> Profile

    Profile{"Quick-compatible profile?"}
    Profile -- "No" --> AdvancedOnly["Explain limitation<br/>offer Advanced/Landing or Cancel"]
    Profile -- "Yes" --> FrontCheck{"Front Seats station exists?"}

    FrontCheck -- "Yes" --> Front["Front seats combined weight, lb<br/>number ≥ 0 · Use last"]
    FrontCheck -- "No" --> RearCheck{"Rear Seats station exists?"}
    Front --> RearCheck
    RearCheck -- "Yes" --> Rear["Rear seats combined weight, lb<br/>number ≥ 0 · Use last · None = 0"]
    RearCheck -- "No" --> BagCheck{"Baggage station exists?"}
    Rear --> BagCheck
    BagCheck -- "Yes" --> Baggage["Baggage weight, lb<br/>number ≥ 0 · Use last · None = 0"]
    BagCheck -- "No" --> Fuel
    Baggage --> Fuel["Total usable fuel at takeoff, US gal<br/>number ≥ 0 and ≤ combined capacity<br/>Full tanks shortcut"]

    Fuel --> Calc["Immediately calculate and persist result<br/>no separate confirmation screen"]
    Calc --> Result{"Result state"}
    Result -- "Within / on limit" --> Actions["Change load · Advanced/Landing · Main menu"]
    Result -- "Exact tank split required" --> Exact["Explain exact per-tank fuel is needed"] --> Actions
    Result -- "Out of limits" --> Recommendations["Show safe load/fuel recommendations"] --> Actions
```

Notes:

- A prompt is skipped entirely if its matching station type is absent.
- **Back** becomes available after the first question. **Cancel** is always available. Despite an older document in the archive, Quick calculation now supports Back.
- **Change load** restarts Quick for the same aircraft and offers the just-entered front/rear/baggage values as **Use last** shortcuts. Fuel is entered again.
- **Advanced/Landing** after a Quick result carries the compatible front/rear/baggage values forward and starts at the per-tank fuel questions.
- With multiple tanks at different arms, Quick uses total fuel honestly: it returns a possible CG range rather than inventing a tank split. If some possible splits are safe and others are not, it asks the pilot to run Advanced with actual tank quantities.

---

## 6. Takeoff + Landing: Advanced calculation

Advanced calculation supports every configured non-fuel station and every tank individually. It produces ramp/takeoff/landing evaluations from the loads and per-tank fuel data.

```mermaid
flowchart TD
    Start(["Takeoff + Landing (Advanced)"]) --> Aircraft{"Selected aircraft exists?"}
    Aircraft -- "No" --> Pick["Pick aircraft"]
    Aircraft -- "Yes" --> HasLoads{"Non-fuel stations configured?"}
    Pick --> HasLoads

    subgraph LoadLoop["For each configured non-fuel station, in profile order"]
        direction TD
        Load["Weight at this station, lb<br/>number ≥ 0"]
        Load -- "Use last, if history exists" --> NextLoad
        Load -- "None, except Front Seats" --> NextLoad
        Load -- "typed value" --> NextLoad{"More non-fuel stations?"}
        NextLoad -- "Yes" --> Load
    end

    HasLoads -- "Yes" --> Load
    HasLoads -- "No" --> HasTanks{"Fuel tanks configured?"}
    NextLoad -- "No" --> HasTanks

    subgraph TankLoop["For each configured Fuel Tank"]
        direction TD
        TankStart["Fuel in this tank at takeoff, US gal<br/>number ≥ 0 and ≤ tank capacity<br/>Full tank; None only with >1 tank"]
        TankStart --> Burn["Fuel burn from this tank, US gal<br/>number ≥ 0 and ≤ starting fuel<br/>No burn button = 0"]
        Burn --> MoreTanks{"More tanks?"}
        MoreTanks -- "Yes" --> TankStart
    end

    HasTanks -- "Yes" --> TankStart
    HasTanks -- "No" --> Calc
    MoreTanks -- "No" --> Calc["Immediately calculate and persist<br/>no separate confirmation screen"]
    Calc --> Result{"Overall result"}
    Result -- "Within / on limit" --> Actions["Change load · Main menu"]
    Result -- "Out of limits" --> Recommendations["Show adjustment recommendations"] --> Actions
```

Notes:

- **Back** follows the exact station/tank sequence. **Cancel** returns to the main menu.
- **Change load** restarts Advanced for the same aircraft and offers the saved station loads as **Use last** shortcuts. Fuel is entered again.
- The Advanced result includes the pilot’s inputs, then the phase results. Ramp and takeoff are collapsed into one displayed phase when their weights are identical.
- The fuel-burn prompt has **No burn (0 gal)**, **Back** and **Cancel**. **No burn** records an explicit 0, so the landing condition is still evaluated. There is deliberately no **Skip**: skipping once silently disabled landing evaluation for every tank.
- **Known limitation:** the wizard asks for fuel at takeoff, not at ramp, and taxi burn is stored as 0. The ramp phase therefore always equals the takeoff phase and is shown as one combined phase; the ramp weight limit is not independently exercised by taxi/run-up fuel.

---

## 7. Supporting actions

```mermaid
flowchart TD
    Start["Aircraft / More menu action"] --> Action{"Chosen action"}
    Action -- "Change Aircraft" --> Pick1["Pick profile"] --> Active["Set as active<br/>→ Main menu"]
    Action -- "Archive Aircraft" --> Pick2["Pick profile"] --> Archive["Archive it<br/>clear active profile if it was selected<br/>→ Main menu"]
    Action -- "My Aircrafts" --> Profiles["Show all non-archived profiles<br/>selected profile marked ⭐"]
    Action -- "View Profile" --> Pick3["Pick profile"] --> Summary["Show saved profile summary in chat"]
    Action -- "Calculation History" --> History["Show up to 10 saved calculation summaries"]
    Action -- "Help" --> Help["Show usage and data-entry safety note"]
```

---

## Source map for future updates

| Change needed | Source of truth |
|---|---|
| Menu labels, question wording, error copy | `app/bot/texts/i18n.py` |
| Add/edit profile states and branches | `app/bot/handlers/aircraft_wizard.py`, `app/bot/handlers/aircraft_update.py`, `app/bot/states/aircraft_wizard.py` |
| Main menu and supporting actions | `app/bot/handlers/menu.py`, `app/bot/keyboards/common.py` |
| Quick calculation questions / branches | `app/bot/handlers/quick_calculate.py`, `app/bot/states/quick_calc_wizard.py` |
| Advanced calculation questions / branches | `app/bot/handlers/flight_calculation.py`, `app/bot/states/flight_wizard.py` |
| Shared Back behavior | `app/bot/handlers/wizard_nav.py` |
| Input parsing and units | `app/bot/handlers/_common.py`, `app/domain/units.py` |
| Result math / compatibility rules | `app/domain/quick_calculation.py`, `app/domain/calculator.py`, `app/domain/envelope.py` |
| Recommendation logic | `app/domain/quick_recommendations.py`, `app/domain/recommendations.py` |

When a flow changes, update the relevant diagram in this file in the same pull request. The test suites `tests/test_bot_ui.py` and `tests/test_wizard_end_to_end.py` are the closest behavioural checks for the documented interaction flow.

---

## Changelog

### 2026-10-25 flow audit
- Edit Aircraft: **✅ Keep Current** on the nickname screen now works (it previously had no handler).
- Advanced calculation: added **No burn (0 gal)** button on the fuel-burn prompt.
- Add Aircraft: the station hub now has **Back** and **✖ Cancel**.
- Advanced result header changed from "Please confirm your inputs:" to "Your inputs:" (no confirmation step exists).
- **Download Data** renamed **View Profile**; it only ever showed the saved profile in chat. The callback and handler names are unchanged.
- Removed unused strings: `status_incomplete`, `btn_yes`, `btn_no`.
