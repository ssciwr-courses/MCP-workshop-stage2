## The policy

> **Missing values in monthly climate summaries — group policy**
>
> 1. Never report a monthly figure without saying how much of the record was
>    actually measured.
>
> 2. **Rainfall is never estimated from neighbouring days.** Rain does not carry
>    over from one day to the next. Interpolating it invents rain that did not
>    fall.
>
> 3. **A missing rainfall day is not a dry day.** Do not treat it as zero unless
>    it is documented that the station reports only on days when it rains.
>
> 4. For rainfall, exploratory work may leave missing days out of the total, as
>    long as coverage is reported. Anything going into a paper, a report, or a
>    comparison with another station must refuse to run on an incomplete record.
>
> 5. **Three or more consecutive missing rainfall days:** the total is a lower
>    bound, not a measurement. A single storm can carry most of a month's rain,
>    and a gap that long can hide one completely.
>
> 6. For temperature, estimating isolated missing days is acceptable. Estimating
>    across more than five consecutive days is not — weather systems last three
>    to seven days, so a gap that long can erase an entire cold snap or warm
>    spell.
>
> 7. **Below 90% coverage**, a monthly figure is not comparable to a complete
>    month. Say so plainly.
>
> 8. The raw input file is never modified. Ever.
>
> 9. **Missing rainfall days are not a random sample.** Gauges clog, freeze and
>    under-record during heavy rain, so a missing day is more likely than
>    average to have been a wet one. Any missing precipitation day makes the
>    total an underestimate, however short the gap.


The four options mean:

| | |
|---|---|
| `interpolate` | estimate the missing day from the days either side |
| `zero_fill` | treat the missing day as a measured zero |
| `drop` | leave it out of the calculation |
| `fail` | refuse to run |

## Questions

What should be the scope of the skill? (project, personal...)

When should the skill trigger?

What should the agent never do or rewrite?

