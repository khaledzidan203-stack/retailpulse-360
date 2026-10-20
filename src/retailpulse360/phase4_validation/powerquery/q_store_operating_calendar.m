let
    Source = fnLoadCsv("analytics/store_operating_calendar.csv", {
        {"store_key", type text},
        {"date_key", Int64.Type},
        {"calendar_date", type date},
        {"is_operating", Int64.Type},
        {"lifecycle_state", type text}
    })
in
    Source
