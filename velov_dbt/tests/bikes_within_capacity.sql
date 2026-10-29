select station_id, timestamp, bikes_available, capacity
from {{ ref("station_hourly") }}
where bikes_available < 0
   or bikes_available > capacity
