---
name: climate-missing-data
description: Use whenever the user asks to process, summarise or plot a climate dataset with the climate MCP - including when they say nothing about data quality. Chooses the missing-data policy for each metric and reports how much of the record was actually measured.
---

# Missing values in monthly climate summaries

`process_climate_data` takes an optional `missing_policy` per metric:
`interpolate`, `zero_fill`, `drop`, `fail`. Omitted, it uses `interpolate` for
temperature and `zero_fill` for precipitation. It will accept any of them
without complaint, and most of them are wrong.

## Workflow

1. Call `get_config_schema` and `list_sample_data`.
2. Choose a policy per metric using the rules below. Choose from what the user
   is doing, not from the data.
3. Call `process_climate_data`.
4. Read the data-quality section of the result before reporting anything.
5. Report the figure **and** its coverage. Never the figure alone.

## precipitation_mm - aggregated as a sum

- **Never `interpolate`.** Rain does not carry over from one day to the next.
  Interpolating invents rain that did not fall.
- **Never `zero_fill`** unless it is documented that the station reports only on
  days when it rains. A missing day is not a dry day.
- `drop` for exploratory work, and always report coverage.
- `fail` for anything going into a paper, a report, or a comparison with another
  station.

**If `longest_gap` is 3 or more:** the total is a **lower bound, not a
measurement**. A single storm can carry most of a month's rain and a gap that
long can hide one completely. Say this explicitly.

**Any missing precipitation day makes the total an underestimate, however short
the gap.** Gauges clog, freeze and under-record during heavy rain, so a missing
day is more likely than average to have been a wet one - missing days are not a
random sample. Never conclude that a short gap is safe *because* it is short:
the single wettest day of a month can sit in a one-day gap.

## temperature_c - aggregated as a mean

- `interpolate` is fine for isolated missing days. Temperature is
  autocorrelated, so a neighbouring day is a reasonable estimate.
- **Never `zero_fill`.** 0 °C is a plausible February temperature, so a filled
  value is indistinguishable from a measured one and silently drags the mean.
- `drop` is fine - the mean skips missing values.
- **If `longest_gap` is more than 5:** do not interpolate. Weather systems last
  three to seven days, so a gap that long can erase an entire cold snap or warm
  spell. Use `drop`, or `fail` if the figure must be defensible.

## Reading the result

- **Coverage below 100%:** state it with the number. "71 mm from 24 of 28 days
  (86% coverage)", never "71 mm".
- **Coverage below 90%:** say plainly that the figure is not comparable to a
  complete month.

## Ask before deciding

If it is not clear whether this is exploratory or headed for a report, **ask**.
The policy gives different answers and you cannot tell from the data which one
applies.

## Never

- Never modify the input CSV.
- Never report a figure without its coverage.
- Never choose a policy because it makes the run succeed.
