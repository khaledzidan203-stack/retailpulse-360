(relativeFile as text, columnTypes as list) as table =>
let
    Root = Text.TrimEnd(pProjectRoot, {"\", "/"}),
    GenInput = Text.Upper(Text.Trim(pGeneration)),
    Generation = if GenInput = "CURRENT"
        then Text.Trim(Text.FromBinary(File.Contents(Root & "\data\processed\p3_3\CURRENT"), TextEncoding.Utf8))
        else GenInput,
    ValidGeneration = if Text.Length(Generation) = 5 and Text.Start(Generation, 1) = "G"
        and (try Number.FromText(Text.Range(Generation, 1, 4)) otherwise null) <> null
        then Generation else error "Invalid generation identifier",
    Path = Root & "\data\processed\p3_3\generations\" & ValidGeneration & "\" & Text.Replace(relativeFile, "/", "\"),
    Csv = Csv.Document(File.Contents(Path), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Head = Table.PromoteHeaders(Csv, [PromoteAllScalars=true]),
    ExactColumns = if Table.ColumnNames(Head) = List.Transform(columnTypes, each _{0}) then Head
        else error "CSV column contract differs",
    DateFields = List.Transform(List.Select(columnTypes, each _{1} = type date), each _{0}),
    CleanDates = Table.ReplaceValue(ExactColumns, "", null, Replacer.ReplaceValue, DateFields),
    Typed = Table.TransformColumnTypes(CleanDates, columnTypes, "en-US")
in
    Typed
