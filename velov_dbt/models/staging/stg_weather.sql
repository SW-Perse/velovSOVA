{{ config(materialized="view") }}

with expanded as (
    select
        unnest(hourly.time) as hour_ts,
        unnest(hourly.temperature_2m) as temperature,
        unnest(hourly.precipitation) as precipitation,
        unnest(hourly.rain) as rain
    from read_json_auto('{{ var("bronze_path", "../data/bronze") }}/weather/*.json')
)
select
    cast(hour_ts as timestamptz) as hour_ts,
    cast(temperature as double) as temperature,
    cast(precipitation as double) as precipitation,
    cast(rain > 0 as boolean) as is_raining
from expanded
qualify row_number() over (
    partition by hour_ts
    order by hour_ts
) = 1
