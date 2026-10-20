let
    Source = fnLoadCsv("analytics/dim_date.csv", {
        {"date_key", Int64.Type},
        {"calendar_date", type date},
        {"year", Int64.Type},
        {"quarter", Int64.Type},
        {"month", Int64.Type},
        {"month_start", type date},
        {"year_month", Int64.Type},
        {"weekday_number", Int64.Type},
        {"week_start_saturday", type date},
        {"week_end_friday", type date}
    })
in
    Source
