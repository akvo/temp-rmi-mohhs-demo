# JMP WASH Facility Assessment — service-level scoring

Form **1783393878133**. Six `autofield` questions (saved) in a new **JMP Service Levels** group compute each domain's basic/limited/no-service ladder per JMP-2018-core-questions-for-monitoring-WinHCF.pdf (Section 2.2, Table 3), plus an overall pass/fail flag. Generated + validated by `scripts/add_jmp_service_level_scoring.mjs` against akvo-react-form's engine.

> Keep "Support Multiline Function" **unchecked** — one-line formulas.

## Known limitation

JMP's Basic Sanitation definition requires **menstrual hygiene facilities** (JMP question G-S5: bin with lid + water/soap in a private space). This form does not ask about them — its sanitation questions go straight from sex-separation to mobility accessibility. Per project decision, `sanitation_service_level` below computes "Basic service" from the 4 criteria this form actually collects (usable, staff-dedicated, sex-separated, mobility-accessible), **excluding** the menstrual-hygiene criterion. A site scored "Basic service" here is not a guaranteed JMP-standard "Basic" without separately confirming menstrual hygiene facilities.

## Water-source classification

Not exercised by the round already imported (all 19 sites answered "rainwater").

- `tanker_truck` -> **improved**. JMP's water-source technology ladder is fixed across household/school/facility monitoring and splits "delivered water" into packaged (bottled/sachet) and tanker-truck/cart sub-types, both improved. This HCF document's summary table just condenses that to "packaged delivered water" -- not a real ambiguity.

- `other_ground_water_well` -> **unimproved** (conservative default). This is a form-design gap, not a JMP ambiguity: JMP classifies dug wells by protection status (protected = improved, unprotected = unimproved), and this option doesn't capture protection status at all. Proper fix: split it into "Protected dug well" / "Unprotected dug well" per JMP's actual G-W1 categories.

## Colours

`fnColor` on each autofield uses the official JMP 2020 colour palette (washdata.org/report/jmp-2020-colour-palette), "WASH services in Health Care Facilities" ladders. "No service"/"No facility" is `#FEBC11` and "Limited" is `#FFF176` across every domain; "Basic" is domain-specific (water blue, sanitation green, hygiene purple, health-care waste red, environmental cleaning pink). `meets_jmp_basic_wash` has no official JMP ladder colour -- it reuses the same green/orange pass-fail sense.

## Domain formulas

### `water_service_level` — Water service level (JMP)

```
#what_is_the_main_water_source_used_by_the_facility#.includes("piped_water") || #what_is_the_main_water_source_used_by_the_facility#.includes("borehole_tubewell") || #what_is_the_main_water_source_used_by_the_facility#.includes("rainwater") || #what_is_the_main_water_source_used_by_the_facility#.includes("bottled_water") || #what_is_the_main_water_source_used_by_the_facility#.includes("tanker_truck") ? ( #is_the_main_water_supply_located_on_the_premises#.includes("yes") && #is_water_available_from_the_main_water_supply_today#.includes("yes") ? "Basic service" : "Limited service" ) : "No service"
```

`fnColor`:

```json
{
  "Basic service": "#00B8EC",
  "Limited service": "#FFF176",
  "No service": "#FEBC11"
}
```

### `sanitation_service_level` — Sanitation service level (JMP; menstrual hygiene not assessed by this form)

```
#what_types_of_toilets_latrines_are_available_for_patients#.includes("flush_toilet") || #what_types_of_toilets_latrines_are_available_for_patients#.includes("pour_flush_toilet") || #what_types_of_toilets_latrines_are_available_for_patients#.includes("pit_latrine_with_slab") || #what_types_of_toilets_latrines_are_available_for_patients#.includes("composting_toilet") ? ( #is_at_least_one_toilets_usable_today#.includes("yes") && #are_toilets_separated_for_staff_and_patients#.includes("yes") && #are_toilets_sex_separated#.includes("yes") && #are_toilets_accessible_to_people_with_limited_mobility#.includes("yes") ? "Basic service" : "Limited service" ) : "No service"
```

`fnColor`:

```json
{
  "Basic service": "#51B453",
  "Limited service": "#FFF176",
  "No service": "#FEBC11"
}
```

### `hygiene_service_level` — Hygiene service level (JMP)

```
#is_there_a_functional_hand_hygiene_facility_at_at_least_one_point_of_care#.includes("yes") && #is_there_a_functional_hand_hygiene_facility_near_at_least_one_toilet#.includes("yes") ? "Basic service" : ( #is_there_a_functional_hand_hygiene_facility_at_at_least_one_point_of_care#.includes("yes") || #is_there_a_functional_hand_hygiene_facility_near_at_least_one_toilet#.includes("yes") ) ? "Limited service" : "No service"
```

`fnColor`:

```json
{
  "Basic service": "#AB47BC",
  "Limited service": "#FFF176",
  "No service": "#FEBC11"
}
```

### `health_care_waste_service_level` — Health care waste management service level (JMP)

```
#does_the_facility_segregate_waste_into_minimum_required_categories#.includes("yes_sharps_infectious_and_non_infectious") && #is_sharps_waste_safely_treated_and_disposed_of#.includes("yes") && #is_infectious_wastes_safely_treated_and_disposed_of#.includes("yes") ? "Basic service" : ( #does_the_facility_segregate_waste_into_minimum_required_categories#.includes("no") && #is_sharps_waste_safely_treated_and_disposed_of#.includes("no") && #is_infectious_wastes_safely_treated_and_disposed_of#.includes("no") ) ? "No service" : "Limited service"
```

`fnColor`:

```json
{
  "Basic service": "#EF414A",
  "Limited service": "#FFF176",
  "No service": "#FEBC11"
}
```

### `environmental_cleaning_service_level` — Environmental cleaning service level (JMP)

```
#does_the_facility_have_cleaning_protocols_available#.includes("yes") && #are_staff_responsible_for_cleaning_trained#.includes("yes_all") ? "Basic service" : ( #does_the_facility_have_cleaning_protocols_available#.includes("no") && #are_staff_responsible_for_cleaning_trained#.includes("none") ) ? "No service" : "Limited service"
```

`fnColor`:

```json
{
  "Basic service": "#EF5BA1",
  "Limited service": "#FFF176",
  "No service": "#FEBC11"
}
```

## `meets_jmp_basic_wash` — Meets JMP basic WASH standard

```
#water_service_level#.includes("Basic") && #sanitation_service_level#.includes("Basic") && #hygiene_service_level#.includes("Basic") && #health_care_waste_service_level#.includes("Basic") && #environmental_cleaning_service_level#.includes("Basic") ? "Yes - meets JMP basic WASH standard (all 5 domains)" : "No - does not meet all 5 basic WASH domains"
```

`fnColor`:

```json
{
  "Yes - meets JMP basic WASH standard (all 5 domains)": "#51B453",
  "No - does not meet all 5 basic WASH domains": "#FEBC11"
}
```
